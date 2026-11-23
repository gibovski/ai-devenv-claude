"""Worker protocol: register, heartbeat, claim, report. Authenticated with the worker token."""

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import queue, repos
from ..auth import require
from ..catalogue.loader import choose_model

router = APIRouter(prefix="/api/workers", tags=["workers"], dependencies=[Depends(require("worker"))])


class RegisterIn(BaseModel):
    id: str
    provider: str
    model: str = ""
    hostname: str = ""
    version: str = ""


class HeartbeatIn(BaseModel):
    state: str = "idle"  # idle | busy | error
    task_id: int | None = None
    message: str = ""


class EventIn(BaseModel):
    kind: str = "log"
    message: str


class ResultIn(BaseModel):
    outcome: str  # pr | completed | failed
    branch: str = ""
    pr_url: str = ""
    pr_number: int | None = None
    error: str = ""
    summary: str = ""


def _worker(request: Request, worker_id: str) -> dict:
    w = request.app.state.db.one("SELECT * FROM workers WHERE id = ?", worker_id)
    if not w:
        raise HTTPException(404, "Unknown worker; register first")
    return w


def _own_task(request: Request, worker_id: str, task_id: int) -> dict:
    t = request.app.state.db.one("SELECT * FROM tasks WHERE id = ?", task_id)
    if not t or t["worker_id"] != worker_id or t["status"] != "in_progress":
        raise HTTPException(409, "Task is not leased to this worker")
    return t


@router.post("/register")
def register(body: RegisterIn, request: Request):
    db = request.app.state.db
    db.run(
        "INSERT INTO workers(id, provider, model, hostname, version, state, last_heartbeat) VALUES (?, ?, ?, ?, ?, 'idle', ?) "
        "ON CONFLICT(id) DO UPDATE SET provider = excluded.provider, model = excluded.model, hostname = excluded.hostname, "
        "version = excluded.version, state = 'idle', current_task_id = NULL, last_heartbeat = excluded.last_heartbeat",
        body.id,
        body.provider,
        body.model,
        body.hostname,
        body.version,
        time.time(),
    )
    # A re-registering worker lost whatever it was doing.
    for t in db.all("SELECT * FROM tasks WHERE worker_id = ? AND status = 'in_progress'", body.id):
        queue.fail_attempt(db, t, "worker restarted", body.id)
    cfg = request.app.state.cfg
    from ..state import kv_get

    return {
        "worker_id": body.id,
        "config_version": kv_get(db, "agent_config_version", 0),
        "heartbeat_seconds": max(5, cfg.heartbeat_timeout // 3),
        "lease_seconds": cfg.lease_seconds,
    }


@router.post("/{worker_id}/heartbeat")
def heartbeat(worker_id: str, body: HeartbeatIn, request: Request):
    _worker(request, worker_id)
    db, cfg = request.app.state.db, request.app.state.cfg
    db.run(
        "UPDATE workers SET last_heartbeat = ?, state = ?, current_task_id = ?, message = ? WHERE id = ?",
        time.time(),
        body.state,
        body.task_id,
        body.message[:500],
        worker_id,
    )
    lease_ok = True
    if body.task_id:
        lease_ok = queue.extend_lease(db, body.task_id, worker_id, cfg.lease_seconds)
    # Tell the worker to stop if its task was cancelled or reassigned, and which agent config is current.
    from ..state import kv_get

    return {"ok": True, "continue": lease_ok, "config_version": kv_get(db, "agent_config_version", 0)}


def _prepare_repo(request: Request, worker_id: str, task: dict, s) -> bool:
    """Check the task's repo against the current policy and create it for `new:` tasks. False: not runnable now."""
    db, cfg = request.app.state.db, request.app.state.cfg
    create = task["repo"].startswith(repos.NEW_PREFIX)
    full = task["repo"].removeprefix(repos.NEW_PREFIX)
    ok, why = repos.allowed(full, s.github)
    if ok and create and not s.github.allow_create_repos:
        ok, why = False, "Creating repositories is turned off in Settings → GitHub"
    if not ok:
        # The settings changed after the task was queued: a person has to decide.
        queue.set_status(
            db, task["id"], "needs_human", why, worker_id, worker_id=None, lease_expires=None, last_error=why
        )
        return False
    if not create:
        return True
    token = request.app.state.secrets.get("github_token")
    if not token:
        queue.fail_attempt(db, task, "no GitHub token in Settings, so the new repository cannot be created", worker_id)
        return False
    try:
        info = repos.ensure_repo(full, task["title"], s.github, token, cfg.github_api)
    except (repos.RepoError, httpx.HTTPError) as e:
        queue.fail_attempt(db, task, str(e), worker_id)
        return False
    base = task["base_branch"]
    if info["created"] and base == "main":
        base = info["default_branch"]
    db.run("UPDATE tasks SET repo = ?, base_branch = ? WHERE id = ?", full, base, task["id"])
    note = "created repository" if info["created"] else "repository already exists, using"
    queue.event(db, task["id"], "log", f"{note} {info['url']}", worker_id)
    repos.forget_cache()
    task["repo"], task["base_branch"], task["new_repo"] = full, base, info["created"]
    return True


@router.post("/{worker_id}/claim")
def claim(worker_id: str, request: Request):
    w = _worker(request, worker_id)
    db, cfg = request.app.state.db, request.app.state.cfg
    db.run("UPDATE workers SET last_heartbeat = ? WHERE id = ?", time.time(), worker_id)
    task = queue.claim(db, worker_id, w["provider"], cfg.lease_seconds)
    if not task:
        return Response(status_code=204)
    from ..state import load_settings

    s = load_settings(db)
    if task["repo"] and not _prepare_repo(request, worker_id, task, s):
        db.run("UPDATE workers SET state = 'idle', current_task_id = NULL WHERE id = ?", worker_id)
        return Response(status_code=204)
    task["run"] = choose_model(task, w["provider"])
    if task["run"]["model"]:
        queue.event(
            db, task["id"], "log",
            f"model {task['run']['model']}{' (' + task['run']['effort'] + ' effort)' if task['run']['effort'] else ''} "
            f"from the {task['run']['source']}",
            worker_id,
        )  # fmt: skip
    task["git"] = {"user_name": s.github.git_user_name, "user_email": s.github.git_user_email}
    task["attachment_urls"] = [
        {
            "id": a["id"],
            "filename": a["filename"],
            "sha256": a["sha256"],
            "url": f"/api/tasks/{task['id']}/attachments/{a['id']}/content",
        }
        for a in task["attachments"]
    ]
    return task


@router.post("/{worker_id}/tasks/{task_id}/events")
def task_event(worker_id: str, task_id: int, body: EventIn, request: Request):
    _own_task(request, worker_id, task_id)
    queue.event(
        request.app.state.db,
        task_id,
        body.kind if body.kind in ("log", "error") else "log",
        body.message[:20000],
        worker_id,
    )
    return {"ok": True}


@router.post("/{worker_id}/tasks/{task_id}/result")
def task_result(worker_id: str, task_id: int, body: ResultIn, request: Request):
    task = _own_task(request, worker_id, task_id)
    db = request.app.state.db
    if body.summary:
        queue.event(db, task_id, "log", f"Summary: {body.summary[:5000]}", worker_id)
    if body.outcome == "pr":
        if not body.pr_url:
            raise HTTPException(400, "pr outcome needs pr_url")
        queue.set_status(
            db, task_id, "in_review", body.pr_url, worker_id,
            branch=body.branch, pr_url=body.pr_url, pr_number=body.pr_number, lease_expires=None,
        )  # fmt: skip
        db.run("UPDATE workers SET tasks_done = tasks_done + 1 WHERE id = ?", worker_id)
        status = "in_review"
    elif body.outcome == "completed":
        if task["repo"]:
            raise HTTPException(400, "Tasks with a repo must finish with a merged PR (outcome 'pr')")
        queue.set_status(db, task_id, "done", "completed without code changes", worker_id, lease_expires=None)
        db.run("UPDATE workers SET tasks_done = tasks_done + 1 WHERE id = ?", worker_id)
        status = "done"
    elif body.outcome == "failed":
        status = queue.fail_attempt(db, task, body.error or "agent reported failure", worker_id)
        db.run("UPDATE workers SET tasks_failed = tasks_failed + 1 WHERE id = ?", worker_id)
    else:
        raise HTTPException(400, "outcome must be pr, completed or failed")
    db.run("UPDATE workers SET state = 'idle', current_task_id = NULL WHERE id = ?", worker_id)
    return {"status": status}
