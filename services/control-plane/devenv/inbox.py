"""GitHub as the controller channel.

A controller (Claude, ChatGPT, a person, a script) opens an issue labelled `devenv-task` in the control
repository. Every 30 seconds the VM queues new issues as tasks and comments on each issue when its task
changes state, with the PR link, and closes the issue when the task is done. The VM only makes outgoing
calls to GitHub, so this works without a tunnel and from sandboxes that cannot reach the VM.

Issue format: the title is the task title; the body is the description. Lines like these anywhere in the
body set fields and are removed from the description (case-insensitive):

    repo: my-app | owner/name | new:my-new-app
    depends-on: #12, #15        (other issues in the control repo)
    complexity: trivial | small | medium | large | hard
    reason: why that complexity
    priority: 5
    provider: any | claude | codex
    model: claude-sonnet-5-5
    effort: low | medium | high | xhigh | max
    base: main
    attach: specs/api.yaml      (a file in the control repo, copied to the task)

Only issues from the repository owner, members and collaborators are accepted. Closing an issue cancels
its task."""

import base64
import hashlib
import logging
import re

import httpx

from . import queue, repos
from .catalogue.loader import complexity_levels
from .db import Database
from .github import GitHub
from .settings_schema import GitHubSettings
from .state import kv_get, kv_set, load_settings

log = logging.getLogger(__name__)

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**(repo|depends[- ]on|complexity|reason|priority|provider|model|effort|base|attach)\**\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MAX_ATTACHMENT = 20 * 1024 * 1024
STATUS_TEXT = {
    "queued": "Queued; waiting for its dependencies or a free agent.",
    "in_progress": "An agent is working on it.",
    "in_review": "Pull request open; waiting for checks and merge.",
    "deploying": "Merged; waiting for the deploy workflow.",
    "done": "Done: merged{deploy}.",
    "needs_human": "Needs a person: {error}",
    "failed": "Attempt failed: {error}",
    "cancelled": "Cancelled.",
}


def control_repo(gh: GitHubSettings) -> str:
    name = gh.inbox_repo.strip()
    if not name:
        return ""
    return name if "/" in name else f"{gh.owner}/{name}" if gh.owner else ""


def parse_issue(body: str) -> tuple[dict, str]:
    """Pull `key: value` lines out of an issue body. Returns (fields, remaining description)."""
    fields: dict[str, str | list[str]] = {}
    attach: list[str] = []
    for m in FIELD_RE.finditer(body or ""):
        key = m.group(1).lower().replace(" ", "-")
        value = m.group(2).strip().strip("`")
        if key == "attach":
            attach.append(value)
        elif key not in fields:
            fields[key] = value
    if attach:
        fields["attach"] = attach
    description = FIELD_RE.sub("", body or "").strip()
    return fields, re.sub(r"\n{3,}", "\n\n", description)


def _deps(value: str) -> list[int]:
    return [int(n) for n in re.findall(r"#?(\d+)", value or "")]


class Inbox:
    def __init__(self, db: Database, gh: GitHub, settings: GitHubSettings, uploads_dir):
        self.db, self.gh, self.s, self.uploads = db, gh, settings, uploads_dir
        self.repo = control_repo(settings)

    # ---------- setup ----------

    def ensure_repo(self) -> None:
        if kv_get(self.db, "inbox_ready") == self.repo:
            return
        if not self.gh.get(f"/repos/{self.repo}"):
            owner, name = self.repo.split("/", 1)
            me = (self.gh.get("/user") or {}).get("login", "")
            path = "/user/repos" if me.lower() == owner.lower() else f"/orgs/{owner}/repos"
            r = self.gh.client.post(
                path,
                json={
                    "name": name,
                    "private": True,
                    "auto_init": True,
                    "has_issues": True,
                    "description": "Work queue inbox for the AI dev environment: issues labelled "
                    f"{self.s.inbox_label} become tasks",
                },
            )
            if r.status_code not in (200, 201):
                raise RuntimeError(f"cannot create {self.repo}: {r.status_code} {r.text[:200]}")
        r = self.gh.client.post(
            f"/repos/{self.repo}/labels",
            json={"name": self.s.inbox_label, "color": "4f46e5", "description": "Queue this issue for the agents"},
        )
        if r.status_code not in (200, 201, 422):  # 422: the label exists
            raise RuntimeError(f"cannot create label in {self.repo}: {r.status_code} {r.text[:200]}")
        kv_set(self.db, "inbox_ready", self.repo)

    # ---------- GitHub helpers ----------

    def comment(self, issue: int, text: str) -> None:
        self.gh.client.post(f"/repos/{self.repo}/issues/{issue}/comments", json={"body": text}).raise_for_status()

    def close(self, issue: int, reason: str) -> None:
        self.gh.client.patch(
            f"/repos/{self.repo}/issues/{issue}", json={"state": "closed", "state_reason": reason}
        ).raise_for_status()

    def open_issues(self) -> list[dict]:
        out = []
        for page in range(1, 6):
            batch = (
                self.gh.get(
                    f"/repos/{self.repo}/issues",
                    state="open",
                    labels=self.s.inbox_label,
                    per_page=100,
                    page=page,
                    sort="created",
                    direction="asc",
                )
                or []
            )
            out += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                break
        return out

    def _row(self, issue: int) -> dict | None:
        return self.db.one("SELECT * FROM inbox_issues WHERE repo = ? AND issue = ?", self.repo, issue)

    # ---------- issues → tasks ----------

    def import_issue(self, issue: dict) -> None:
        number = issue["number"]
        if (issue.get("author_association") or "").upper() not in TRUSTED:
            self._record(number, None, f"ignored: {issue['user']['login']} is not a collaborator")
            return
        fields, description = parse_issue(issue.get("body") or "")
        try:
            item = self._task_item(issue, fields, description)
        except ValueError as e:
            self._record(number, None, str(e))
            self.comment(
                number,
                f"Could not queue this issue: {e}\n\nFix it and remove/re-add the `{self.s.inbox_label}` label, or open a new issue.",
            )
            return
        if item is None:
            return  # waiting for a dependency issue to be imported first
        (task_id,) = queue.create_tasks(
            self.db, [item], f"github:{self.repo}#{number}", load_settings(self.db).agents.max_attempts
        )
        self._record(number, task_id, "")
        self._mark(number, "queued")  # the comment below says so
        for path in fields.get("attach", []):
            self._attach(task_id, path)
        task = queue.get_task(self.db, task_id)
        deps = ", ".join(f"#{d['id']}" for d in task["deps"]) or "none"
        rating = task["complexity"] or "not rated (Settings model)"
        self.comment(
            number,
            f"Queued as task **#{task_id}**.\n\n- Repository: `{task['repo'] or 'none (no code change)'}`\n"
            f"- Complexity: {rating}\n- Waits for tasks: {deps}\n\nI'll comment here as it progresses and close "
            "this issue when it is done. Close it yourself to cancel the task.",
        )

    def _task_item(self, issue: dict, f: dict, description: str) -> dict | None:
        settings = load_settings(self.db)
        try:
            repo = repos.normalize(f.get("repo") or repos.default_repo(settings.github), settings.github)
        except repos.RepoError as e:
            raise ValueError(str(e)) from None
        complexity = (f.get("complexity") or "").lower()
        if complexity and complexity not in complexity_levels():
            raise ValueError(f"complexity must be one of {', '.join(complexity_levels())}")
        provider = (f.get("provider") or "any").lower()
        if provider not in ("any", "claude", "codex"):
            raise ValueError("provider must be any, claude or codex")
        effort = (f.get("effort") or "").lower()
        if effort not in ("", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("effort must be low, medium, high, xhigh or max")
        deps = []
        for n in _deps(f.get("depends-on", "")):
            row = self._row(n)
            if row and row["task_id"]:
                deps.append(row["task_id"])
            elif row:
                raise ValueError(f"it depends on #{n}, which could not be queued ({row['error']})")
            else:
                dep = self.gh.get(f"/repos/{self.repo}/issues/{n}")
                if not dep:
                    raise ValueError(f"it depends on #{n}, which does not exist")
                if dep["state"] == "open" and any(lb["name"] == self.s.inbox_label for lb in dep.get("labels", [])):
                    return None  # imported later in this pass or the next one
                raise ValueError(f"it depends on #{n}, which is not an open `{self.s.inbox_label}` issue")
        try:
            priority = int(f.get("priority") or 0)
        except ValueError:
            raise ValueError("priority must be a whole number") from None
        return {
            "title": issue["title"][:300],
            "description": f"{description}\n\n(From {self.repo}#{issue['number']}: {issue['html_url']})".strip(),
            "repo": repo,
            "base_branch": f.get("base") or "main",
            "priority": priority,
            "provider": provider,
            "complexity": complexity,
            "model": f.get("model") or "",
            "effort": effort,
            "model_reason": f.get("reason") or "",
            "depends_on": deps,
        }

    def _attach(self, task_id: int, path: str) -> None:
        path = path.strip().lstrip("/")
        meta = self.gh.get(f"/repos/{self.repo}/contents/{path}")
        if not meta or meta.get("type") != "file" or meta.get("size", 0) > MAX_ATTACHMENT:
            queue.event(self.db, task_id, "error", f"attachment {path} not found in {self.repo} (or over 20 MB)")
            return
        if meta.get("content"):
            data = base64.b64decode(meta["content"])
        else:  # files over 1 MB come without inline content
            r = self.gh.client.get(
                f"/repos/{self.repo}/contents/{path}", headers={"Accept": "application/vnd.github.raw"}
            )
            r.raise_for_status()
            data = r.content
        from .routes.tasks import safe_name

        name = safe_name(path.rsplit("/", 1)[-1])
        aid = self.db.run(
            "INSERT INTO attachments(task_id, filename, size, sha256) VALUES (?, ?, ?, ?)",
            task_id,
            name,
            len(data),
            hashlib.sha256(data).hexdigest(),
        ).lastrowid
        d = self.uploads / str(task_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / str(aid)).write_bytes(data)
        queue.event(self.db, task_id, "log", f"attached {name} from {self.repo}/{path}")

    def _record(self, issue: int, task_id: int | None, error: str) -> None:
        self.db.run(
            "INSERT INTO inbox_issues(repo, issue, task_id, error) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(repo, issue) DO UPDATE SET task_id = excluded.task_id, error = excluded.error",
            self.repo,
            issue,
            task_id,
            error,
        )

    # ---------- tasks → issues ----------

    def report(self, open_numbers: set[int]) -> None:
        rows = self.db.all(
            "SELECT i.issue, i.reported, t.* FROM inbox_issues i JOIN tasks t ON t.id = i.task_id "
            "WHERE i.repo = ? AND i.reported NOT IN ('done', 'cancelled')",
            self.repo,
        )
        for r in rows:
            issue, status = r["issue"], r["status"]
            if issue not in open_numbers and status not in ("done", "cancelled"):
                # The issue was closed (or unlabelled) on GitHub: stop the work.
                still = self.gh.get(f"/repos/{self.repo}/issues/{issue}")
                if still and still["state"] == "closed":
                    queue.set_status(self.db, r["id"], "cancelled", f"issue {self.repo}#{issue} was closed", None,
                                     worker_id=None, lease_expires=None)  # fmt: skip
                    self._mark(issue, "cancelled")
                    continue
            if status == r["reported"]:
                continue
            text = STATUS_TEXT.get(status, status).format(
                error=r["last_error"] or "see the task log",
                deploy=f" and deployed ({r['deploy_status'].removeprefix('succeeded: ')})"
                if r["deploy_status"].startswith("succeeded")
                else "",
            )
            lines = [f"Task **#{r['id']}**: {text}"]
            if r["pr_url"]:
                lines.append(f"Pull request: {r['pr_url']}")
            if r["worker_id"] and status == "in_progress":
                lines.append(f"Agent: `{r['worker_id']}`")
            self.comment(issue, "\n\n".join(lines))
            if status == "done" and issue in open_numbers:
                self.close(issue, "completed")
            elif status == "cancelled" and issue in open_numbers:
                self.close(issue, "not_planned")
            self._mark(issue, status)

    def _mark(self, issue: int, status: str) -> None:
        self.db.run("UPDATE inbox_issues SET reported = ? WHERE repo = ? AND issue = ?", status, self.repo, issue)

    # ---------- one pass ----------

    def sync(self) -> dict:
        self.ensure_repo()
        issues = self.open_issues()
        numbers = {i["number"] for i in issues}
        # Issues that could not be queued are retried once someone fixes them and re-adds the label.
        for r in self.db.all("SELECT issue FROM inbox_issues WHERE repo = ? AND task_id IS NULL", self.repo):
            if r["issue"] not in numbers:
                self.db.run("DELETE FROM inbox_issues WHERE repo = ? AND issue = ?", self.repo, r["issue"])
        imported = 0
        for _ in range(3):  # later passes pick up issues whose dependencies were imported in this one
            pending = [i for i in issues if not self._row(i["number"])]
            if not pending:
                break
            for issue in pending:
                self.import_issue(issue)
            new = sum(1 for i in pending if (self._row(i["number"]) or {}).get("task_id"))
            imported += new
            if not new:
                break
        self.report(numbers)
        return {"repo": self.repo, "open": len(issues), "imported": imported}


def sync(db: Database, store, api: str, uploads_dir, client: httpx.Client | None = None) -> dict | None:
    """Background pass: import new issues and report task progress. Errors are kept for the Settings page."""
    s = load_settings(db).github
    token = store.get("github_token")
    if not s.inbox_enabled or not token:
        return None
    repo = control_repo(s)
    if not repo:
        kv_set(db, "inbox_status", {"repo": "", "error": "Set the GitHub owner in Settings"})
        return None
    try:
        result = Inbox(db, GitHub(token, api, client), s, uploads_dir).sync()
        kv_set(db, "inbox_status", {**result, "error": ""})
        return result
    except (httpx.HTTPError, RuntimeError) as e:
        log.warning("inbox: %s", e)
        kv_set(db, "inbox_status", {"repo": repo, "error": str(e)[:300]})
        return None
