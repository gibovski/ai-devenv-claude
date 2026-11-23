import base64
import json

import httpx
import pytest

from devenv import inbox, queue
from devenv.settings_schema import GitHubSettings

REPO = "me/devenv-control"


def test_parse_issue_fields():
    fields, desc = inbox.parse_issue(
        "Add a DNS module.\n\nrepo: tofu-modules\nDepends-on: #3, #4\n- **complexity**: small\n"
        "reason: copies the existing pattern\nattach: specs/dns.md\nattach: `specs/b.md`\n\nAcceptance: plan is clean."
    )
    assert fields == {
        "repo": "tofu-modules",
        "depends-on": "#3, #4",
        "complexity": "small",
        "reason": "copies the existing pattern",
        "attach": ["specs/dns.md", "specs/b.md"],
    }
    assert desc == "Add a DNS module.\n\nAcceptance: plan is clean."
    assert inbox._deps("#3, #4 and 7") == [3, 4, 7]
    assert inbox.control_repo(GitHubSettings(owner="me")) == REPO
    assert inbox.control_repo(GitHubSettings(owner="me", inbox_repo="org/ctl")) == "org/ctl"


class FakeGitHub:
    def __init__(self):
        self.repo_exists = False
        self.labels: list[str] = []
        self.issues: dict[int, dict] = {}
        self.comments: dict[int, list[str]] = {}
        self.files = {"specs/dns.md": b"# DNS spec"}

    def add(self, number, title, body, author="OWNER", labels=("devenv-task",), state="open"):
        self.issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "author_association": author,
            "user": {"login": "someone"},
            "labels": [{"name": n} for n in labels],
            "html_url": f"https://github.com/{REPO}/issues/{number}",
        }

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        if path == "/user":
            return httpx.Response(200, json={"login": "me"})
        if path == f"/repos/{REPO}" and m == "GET":
            return httpx.Response(200, json={"full_name": REPO}) if self.repo_exists else httpx.Response(404, json={})
        if path == "/user/repos" and m == "POST":
            body = json.loads(req.content)
            assert body["name"] == "devenv-control" and body["private"] is True
            self.repo_exists = True
            return httpx.Response(201, json={"full_name": REPO})
        if path == f"/repos/{REPO}/labels" and m == "POST":
            name = json.loads(req.content)["name"]
            if name in self.labels:
                return httpx.Response(422, json={})
            self.labels.append(name)
            return httpx.Response(201, json={})
        if path == f"/repos/{REPO}/issues" and m == "GET":
            label = req.url.params["labels"]
            out = [
                i for i in sorted(self.issues.values(), key=lambda i: i["number"])
                if i["state"] == "open" and any(lb["name"] == label for lb in i["labels"])
            ]  # fmt: skip
            return httpx.Response(200, json=out)
        if path.startswith(f"/repos/{REPO}/issues/"):
            rest = path.removeprefix(f"/repos/{REPO}/issues/")
            if rest.endswith("/comments") and m == "POST":
                n = int(rest.split("/")[0])
                self.comments.setdefault(n, []).append(json.loads(req.content)["body"])
                return httpx.Response(201, json={})
            n = int(rest)
            if m == "PATCH":
                self.issues[n].update(json.loads(req.content))
                return httpx.Response(200, json=self.issues[n])
            return httpx.Response(200, json=self.issues[n]) if n in self.issues else httpx.Response(404, json={})
        if path.startswith(f"/repos/{REPO}/contents/"):
            f = path.removeprefix(f"/repos/{REPO}/contents/")
            if f in self.files:
                return httpx.Response(
                    200,
                    json={
                        "type": "file",
                        "size": len(self.files[f]),
                        "content": base64.b64encode(self.files[f]).decode(),
                    },
                )
            return httpx.Response(404, json={})
        return httpx.Response(404, json={"path": path})


@pytest.fixture
def gh(admin, app):
    s = admin.get("/api/settings").json()["settings"]
    s["github"].update(owner="me", inbox_enabled=True, blocked_repos=["secret-*"])
    admin.put("/api/settings", json=s)
    app.state.secrets.set("github_token", "ghp_test")
    fake = FakeGitHub()

    def run():
        client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(fake.handler))
        return inbox.sync(app.state.db, app.state.secrets, "https://api.github.com", app.state.cfg.uploads_dir, client)

    fake.run = run
    return fake


def test_issues_become_tasks_and_get_reports(gh, app, admin):
    gh.add(1, "Scaffold status page", "Create the service.\nrepo: new:status-page\ncomplexity: large")
    gh.add(2, "Add DNS module", "repo: tofu-modules\ndepends-on: #1\ncomplexity: small\nattach: specs/dns.md")
    gh.add(3, "From a stranger", "repo: tofu-modules", author="NONE")
    gh.add(4, "Bad repo", "repo: secret-keys")
    gh.add(5, "Not labelled", "repo: x", labels=())
    result = gh.run()
    assert gh.repo_exists and gh.labels == ["devenv-task"]
    assert result == {"repo": REPO, "open": 4, "imported": 2}
    tasks = {t["created_by"]: t for t in admin.get("/api/tasks").json()}
    t1, t2 = tasks[f"github:{REPO}#1"], tasks[f"github:{REPO}#2"]
    assert t1["repo"] == "new:me/status-page" and t1["complexity"] == "large"
    assert t2["repo"] == "me/tofu-modules" and [d["id"] for d in t2["deps"]] == [t1["id"]] and t2["attachments"] == 1
    assert "Create the service." in t1["description"] and "repo:" not in t1["description"]
    assert "Queued as task **#" in gh.comments[1][0]
    assert 3 not in gh.comments  # strangers get no reply
    assert "blocked list" in gh.comments[4][0]
    assert len(tasks) == 2

    # progress is reported once per change, and done closes the issue
    gh.run()
    assert len(gh.comments[1]) == 1
    db = app.state.db
    queue.set_status(db, t1["id"], "in_review", "", pr_url="https://github.com/me/status-page/pull/1", pr_number=1)
    gh.run()
    gh.run()
    assert "Pull request: https://github.com/me/status-page/pull/1" in gh.comments[1][-1] and len(gh.comments[1]) == 2
    queue.set_status(db, t1["id"], "done", "")
    gh.run()
    assert gh.issues[1]["state"] == "closed" and gh.issues[1]["state_reason"] == "completed"
    assert "Done" in gh.comments[1][-1]

    # closing an issue cancels its task
    gh.issues[2]["state"] = "closed"
    gh.run()
    assert admin.get(f"/api/tasks/{t2['id']}").json()["status"] == "cancelled"


def test_failed_issue_is_retried_after_relabel(gh, admin):
    gh.add(7, "Bad", "repo: secret-x")
    gh.run()
    assert len(gh.comments[7]) == 1
    gh.issues[7]["labels"] = []  # the person fixes it and re-adds the label
    gh.run()
    gh.issues[7].update(body="repo: fine-repo", labels=[{"name": "devenv-task"}])
    gh.run()
    assert "Queued as task" in gh.comments[7][-1]
    assert admin.get("/api/inbox").json()["last"]["imported"] == 1


def test_disabled_or_missing_token_does_nothing(app, admin):
    assert inbox.sync(app.state.db, app.state.secrets, "https://api.github.com", app.state.cfg.uploads_dir) is None
    body = admin.get("/api/inbox").json()
    assert body["enabled"] is False and body["label"] == "devenv-task"
