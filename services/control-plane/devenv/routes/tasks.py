"""Task queue API: create (single, bulk, plan file), read, update, dependencies, uploads, events."""

import csv
import hashlib
import io
import json
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import queue, repos
from ..auth import Principal, require
from ..catalogue.loader import complexity_levels
from ..state import load_settings

router = APIRouter(prefix="/api", tags=["tasks"])
editors = require("admin", "controller")
readers = require("admin", "controller", "worker")
MAX_UPLOAD = 200 * 1024 * 1024


class TaskIn(BaseModel):
    key: str | None = Field(None, description="Local reference other tasks in the same plan can depend on")
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    repo: str = Field(
        "",
        description="owner/name or name (an existing repository), new:name (create one for this task), "
        "or empty for the default repository (or no code changes when there is none)",
    )
    base_branch: str = "main"
    priority: int = 0
    provider: str = Field("any", pattern="^(any|claude|codex)$")
    max_attempts: int | None = Field(None, ge=1, le=10)
    complexity: str = Field("", description="trivial, small, medium, large or hard: picks the model (see /api/models)")
    model: str = Field("", max_length=100, description="A specific model id; overrides the complexity rating")
    effort: str = Field("", pattern="^(|low|medium|high|xhigh|max)$")
    model_reason: str = Field("", max_length=500, description="Why this complexity or model")
    depends_on: list[str | int] = Field(default_factory=list, description="Keys from this plan or existing task ids")


class PlanIn(BaseModel):
    tasks: list[TaskIn]
    default_repo: str = ""


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    repo: str | None = None
    provider: str | None = Field(None, pattern="^(any|claude|codex)$")
    complexity: str | None = None
    model: str | None = Field(None, max_length=100)
    effort: str | None = Field(None, pattern="^(|low|medium|high|xhigh|max)$")
    model_reason: str | None = Field(None, max_length=500)
    action: str | None = Field(None, pattern="^(cancel|requeue|mark_done)$")


class DepsIn(BaseModel):
    depends_on: list[int]


def _check_model(d: dict) -> None:
    if d.get("complexity") and d["complexity"] not in complexity_levels():
        raise HTTPException(400, f"complexity must be one of {', '.join(complexity_levels())} (or empty)")
    if d.get("model") and not re.fullmatch(r"[\w.:/@-]+", d["model"]):
        raise HTTPException(400, f"Not a model id: {d['model']!r}")


def _repo(spec: str, s) -> str:
    try:
        return repos.normalize(spec, s.github)
    except repos.RepoError as e:
        raise HTTPException(400, str(e)) from None


def _create(request: Request, plan: PlanIn, p: Principal) -> list[dict]:
    db = request.app.state.db
    s = load_settings(db)
    default_repo = plan.default_repo or repos.default_repo(s.github)
    items = [t.model_dump() for t in plan.tasks]
    for d in items:
        d["repo"] = _repo(d["repo"] or default_repo, s)
        _check_model(d)
    # Later tasks of a plan may name a repository that an earlier task creates (`new:x`) by its plain name,
    # without the configured suffix: point them at the repository that will exist.
    created = {
        r.removeprefix(repos.NEW_PREFIX).lower(): r.removeprefix(repos.NEW_PREFIX)
        for r in (d["repo"] for d in items)
        if r.startswith(repos.NEW_PREFIX)
    }
    for d, t in zip(items, plan.tasks, strict=True):
        if d["repo"] and not d["repo"].startswith(repos.NEW_PREFIX):
            owner, name = d["repo"].split("/", 1)
            target = created.get(f"{owner}/{repos.new_name(name, s.github)}".lower())
            if target and t.repo.strip():
                d["repo"] = target
    ids = queue.create_tasks(db, items, f"{p.kind}:{p.name}", s.agents.max_attempts)
    return [queue.get_task(db, i) for i in ids]


@router.get("/tasks", dependencies=[Depends(readers)])
def list_tasks(request: Request, status: str | None = None):
    return queue.list_tasks(request.app.state.db, status)


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, request: Request, p: Principal = Depends(editors)):
    return _create(request, PlanIn(tasks=[body]), p)[0]


@router.post("/tasks/bulk", status_code=201)
def create_plan(body: PlanIn, request: Request, p: Principal = Depends(editors)):
    """Create many tasks at once. Dependencies may refer to other tasks' `key` in this plan."""
    return _create(request, body, p)


def parse_plan_file(name: str, data: bytes) -> PlanIn:
    """Accept YAML/JSON ({tasks: [...]} or a list) or TSV (key, title, depends_on comma list, description)."""
    text = data.decode("utf-8-sig")
    if name.endswith((".tsv", ".txt")):
        tasks = []
        for row in csv.reader(io.StringIO(text), delimiter="\t"):
            if not row or row[0].startswith("#") or len(row) < 2:
                continue
            if re.fullmatch(r"M\d+", row[0]):  # milestone header lines
                continue
            deps = [d.strip() for d in row[2].split(",") if d.strip()] if len(row) > 2 else []
            tasks.append(TaskIn(key=row[0], title=row[1], depends_on=deps, description=row[3] if len(row) > 3 else ""))
        return PlanIn(tasks=tasks)
    obj = json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
    if isinstance(obj, list):
        obj = {"tasks": obj}
    return PlanIn.model_validate(obj)


@router.post("/tasks/import", status_code=201)
async def import_plan(request: Request, file: UploadFile = File(...), p: Principal = Depends(editors)):
    plan = parse_plan_file(file.filename or "plan.yaml", await file.read())
    return _create(request, plan, p)


@router.get("/tasks/{task_id}", dependencies=[Depends(readers)])
def get_task(task_id: int, request: Request):
    return queue.get_task(request.app.state.db, task_id)


@router.patch("/tasks/{task_id}", dependencies=[Depends(editors)])
def patch_task(task_id: int, body: TaskPatch, request: Request):
    db = request.app.state.db
    task = queue.get_task(db, task_id)
    fields = body.model_dump(exclude_none=True, exclude={"action"})
    if "repo" in fields:
        fields["repo"] = _repo(fields["repo"], load_settings(db))
    _check_model(fields)
    if fields:
        db.run(
            f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in fields)}, updated_at = ? WHERE id = ?",
            *fields.values(),
            queue.now_iso(),
            task_id,
        )
    if body.action == "cancel":
        queue.set_status(db, task_id, "cancelled", "cancelled by user", None, worker_id=None, lease_expires=None)
    elif body.action == "requeue":
        if task["status"] == "in_progress":
            raise HTTPException(409, "Task is running; cancel it first")
        queue.set_status(db, task_id, "queued", "requeued by user", attempts=0, last_error="", worker_id=None)
    elif body.action == "mark_done":
        queue.set_status(db, task_id, "done", "marked done by user", lease_expires=None)
    return queue.get_task(db, task_id)


@router.put("/tasks/{task_id}/deps", dependencies=[Depends(editors)])
def put_deps(task_id: int, body: DepsIn, request: Request):
    queue.set_deps(request.app.state.db, task_id, body.depends_on)
    return queue.get_task(request.app.state.db, task_id)


@router.get("/tasks/{task_id}/events", dependencies=[Depends(readers)])
def task_events(task_id: int, request: Request, after: int = 0):
    return request.app.state.db.all(
        "SELECT * FROM task_events WHERE task_id = ? AND id > ? ORDER BY id LIMIT 2000", task_id, after
    )


@router.get("/graph", dependencies=[Depends(readers)])
def graph(request: Request, include_done: bool = True):
    tasks = queue.list_tasks(request.app.state.db)
    if not include_done:
        tasks = [t for t in tasks if t["status"] not in ("done", "cancelled")]
    ids = {t["id"] for t in tasks}
    nodes = [{k: t[k] for k in ("id", "title", "status", "state", "repo", "complexity", "model")} for t in tasks]
    edges = [{"from": d["id"], "to": t["id"]} for t in tasks for d in t["deps"] if d["id"] in ids]
    return {"nodes": nodes, "edges": edges}


# ---------- attachments ----------


def _dir(request: Request, task_id: int) -> Path:
    d = request.app.state.cfg.uploads_dir / str(task_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ]", "_", name).strip(" .")
    return name or "file"


@router.post("/tasks/{task_id}/attachments", status_code=201, dependencies=[Depends(editors)])
async def upload(task_id: int, request: Request, files: list[UploadFile] = File(...)):
    db = request.app.state.db
    queue.get_task(db, task_id)
    out = []
    for f in files:
        name = safe_name(f.filename or "file")
        digest, size = hashlib.sha256(), 0
        cur = db.run(
            "INSERT INTO attachments(task_id, filename, size, sha256, content_type) VALUES (?, ?, 0, '', ?)",
            task_id,
            name,
            f.content_type or "application/octet-stream",
        )
        aid = cur.lastrowid
        path = _dir(request, task_id) / f"{aid}"
        with open(path, "wb") as fh:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    fh.close()
                    path.unlink(missing_ok=True)
                    db.run("DELETE FROM attachments WHERE id = ?", aid)
                    raise HTTPException(413, f"{name} is larger than {MAX_UPLOAD // 1024 // 1024} MB")
                digest.update(chunk)
                fh.write(chunk)
        db.run("UPDATE attachments SET size = ?, sha256 = ? WHERE id = ?", size, digest.hexdigest(), aid)
        queue.event(db, task_id, "log", f"attached {name} ({size} bytes)")
        out.append({"id": aid, "filename": name, "size": size, "sha256": digest.hexdigest()})
    return out


@router.get("/tasks/{task_id}/attachments", dependencies=[Depends(readers)])
def list_attachments(task_id: int, request: Request):
    return queue.get_task(request.app.state.db, task_id)["attachments"]


@router.get("/tasks/{task_id}/attachments/{aid}/content", dependencies=[Depends(readers)])
def download(task_id: int, aid: int, request: Request):
    a = request.app.state.db.one("SELECT * FROM attachments WHERE id = ? AND task_id = ?", aid, task_id)
    if not a:
        raise HTTPException(404, "No such attachment")
    return FileResponse(_dir(request, task_id) / str(aid), filename=a["filename"], media_type=a["content_type"])


@router.delete("/tasks/{task_id}/attachments/{aid}", dependencies=[Depends(editors)])
def delete_attachment(task_id: int, aid: int, request: Request):
    db = request.app.state.db
    db.run("DELETE FROM attachments WHERE id = ? AND task_id = ?", aid, task_id)
    (_dir(request, task_id) / str(aid)).unlink(missing_ok=True)
    return {"ok": True}
