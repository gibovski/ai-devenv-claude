"""Agent status for the dashboard and controllers."""

import time

from fastapi import APIRouter, Depends, Request

from ..auth import require
from ..state import load_settings

router = APIRouter(prefix="/api", tags=["agents"])


def agent_status(request: Request) -> dict:
    db, cfg = request.app.state.db, request.app.state.cfg
    rows = db.all(
        "SELECT w.*, t.title AS task_title, t.repo AS task_repo FROM workers w "
        "LEFT JOIN tasks t ON t.id = w.current_task_id ORDER BY w.provider, w.id"
    )
    now = time.time()
    agents = []
    for w in rows:
        age = now - w["last_heartbeat"]
        status = "offline" if age > cfg.heartbeat_timeout else w["state"]
        if status == "offline" and age > 24 * 3600:
            continue  # long-gone containers drop off the dashboard
        agents.append(
            {
                "id": w["id"],
                "provider": w["provider"],
                "model": w["model"],
                "status": status,
                "message": w["message"],
                "last_heartbeat_seconds": round(age),
                "current_task": {"id": w["current_task_id"], "title": w["task_title"], "repo": w["task_repo"]}
                if w["current_task_id"]
                else None,
                "tasks_done": w["tasks_done"],
                "tasks_failed": w["tasks_failed"],
                "version": w["version"],
            }
        )
    s = load_settings(db)
    desired = {"claude": s.agents.claude.count, "codex": s.agents.codex.count}
    summary = {k: sum(1 for a in agents if a["status"] == k) for k in ("idle", "busy", "error", "offline")}
    online = {p: sum(1 for a in agents if a["provider"] == p and a["status"] != "offline") for p in desired}
    queue_counts = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}
    return {"agents": agents, "summary": summary, "desired": desired, "online": online, "queue": queue_counts}


@router.get("/agents", dependencies=[Depends(require("admin", "controller"))])
def agents(request: Request):
    return agent_status(request)
