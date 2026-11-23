"""Definition of done: a task is done only when its PR is merged into the base branch and, when the repo
has a deploy workflow, that deploy succeeded for the merge commit. Also auto-merges green PRs."""

import time
from datetime import UTC, datetime

from . import queue
from .db import Database
from .github import GitHub
from .state import load_settings

CHECK_GRACE_SECONDS = 120  # wait this long for CI to register before treating "no checks" as green
DEPLOY_TIMEOUT_SECONDS = 1800


def _age(iso: str) -> float:
    return time.time() - datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp()


def deploy_workflow(gh: GitHub, repo: str, ref: str) -> str | None:
    """The workflow file that deploys this repo: `deploy.workflow` in .devenv.yaml, else deploy.yml if present."""
    cfg = gh.repo_config(repo, ref)
    deploy = cfg.get("deploy") if isinstance(cfg, dict) else None
    if isinstance(deploy, dict):
        if deploy.get("enabled") is False:
            return None
        if deploy.get("workflow"):
            return str(deploy["workflow"])
    for name in ("deploy.yml", "deploy.yaml"):
        if gh.has_file(repo, f".github/workflows/{name}", ref):
            return name
    return None


def check_task(db: Database, gh: GitHub, task: dict, auto_merge: bool) -> str:
    """Advance one in_review/deploying task. Returns its (possibly new) status."""
    repo, number = task["repo"], task["pr_number"]
    pr = gh.pull(repo, number)
    if pr is None:
        return queue.fail_attempt(db, task, f"PR #{number} not found in {repo}")

    if task["status"] == "in_review":
        if pr["merged"]:
            if pr["base"]["ref"] != task["base_branch"]:
                return queue.fail_attempt(db, task, f"PR merged into {pr['base']['ref']}, not {task['base_branch']}")
            merge_sha = pr["merge_commit_sha"]
            wf = deploy_workflow(gh, repo, task["base_branch"])
            if wf:
                queue.set_status(
                    db,
                    task["id"],
                    "deploying",
                    f"merged as {merge_sha[:7]}; waiting for {wf}",
                    deploy_status=f"{wf}@{merge_sha}",
                )
                return "deploying"
            queue.set_status(
                db,
                task["id"],
                "done",
                f"merged into {task['base_branch']} as {merge_sha[:7]}; no deploy needed",
                deploy_status="not needed",
            )
            return "done"
        if pr["state"] == "closed":
            return queue.fail_attempt(db, task, f"PR #{number} was closed without merging")
        state, failing = gh.checks_state(repo, pr["head"]["sha"])
        if state == "failure":
            return queue.fail_attempt(db, task, f"checks failed on PR #{number}: {', '.join(failing)}")
        green = state == "success" or (state == "none" and _age(task["updated_at"]) > CHECK_GRACE_SECONDS)
        if auto_merge and green and pr.get("mergeable") is not False and not pr.get("draft"):
            ok, detail = gh.merge(repo, number, pr["head"]["sha"])
            queue.event(
                db,
                task["id"],
                "status" if ok else "error",
                f"auto-merge {'ok: ' + detail[:7] if ok else 'failed: ' + detail}",
            )
        return "in_review"

    # deploying
    wf, _, sha = task["deploy_status"].partition("@")
    runs = gh.workflow_runs(repo, wf, sha)
    if not runs:
        if _age(task["updated_at"]) > DEPLOY_TIMEOUT_SECONDS:
            queue.set_status(
                db, task["id"], "needs_human", f"no {wf} run appeared for {sha[:7]}", last_error="deploy did not start"
            )
            return "needs_human"
        return "deploying"
    run = runs[0]
    if run["status"] != "completed":
        return "deploying"
    if run["conclusion"] == "success":
        queue.set_status(
            db,
            task["id"],
            "done",
            f"deployed by {wf} run {run['html_url']}",
            deploy_status=f"succeeded: {run['html_url']}",
        )
        return "done"
    queue.set_status(
        db,
        task["id"],
        "needs_human",
        f"deploy {run['conclusion']}: {run['html_url']}",
        last_error=f"deploy {run['conclusion']}",
    )
    return "needs_human"


def check_all(db: Database, token: str | None, api: str) -> None:
    tasks = db.all("SELECT * FROM tasks WHERE status IN ('in_review', 'deploying') AND pr_number IS NOT NULL")
    if not tasks or not token:
        return
    gh = GitHub(token, api)
    auto = load_settings(db).github.auto_merge
    for t in tasks:
        try:
            check_task(db, gh, t, auto)
        except Exception as e:  # noqa: BLE001 - one bad task must not stop the loop
            queue.event(db, t["id"], "error", f"done check failed: {e}")
