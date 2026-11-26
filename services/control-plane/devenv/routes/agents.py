"""Agent status for the dashboard and controllers."""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import require
from ..catalogue.loader import default_model
from ..settings_schema import SECRET_FIELDS
from ..state import load_settings, save_settings

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


LABELS = {"claude": "Claude", "codex": "OpenAI Codex"}
SECTIONS = {"claude": "anthropic", "codex": "openai"}
# Any one of these secrets lets an agent of that kind sign in.
CREDENTIALS = {
    "claude": ("claude_code_oauth_token", "anthropic_api_key"),
    "codex": ("codex_auth_json", "openai_api_key"),
}


def availability_warnings(request: Request, tasks: list[dict]) -> list[str]:
    """Warnings for queued tasks that no online agent can run right now, and a note on each task's log."""
    from .. import queue

    status = agent_status(request)
    online, desired = status["online"], status["desired"]
    warnings = []
    for provider in ("codex", "claude"):
        stuck = [t for t in tasks if t["provider"] == provider and t["status"] == "queued"]
        if not stuck or online.get(provider):
            continue
        ids = ", ".join(f"#{t['id']}" for t in stuck)
        label = LABELS[provider]
        why = (
            " (they need images, which only Codex agents can make)" if any(t.get("needs_images") for t in stuck) else ""
        )
        msg = f"No {label} agent is available right now. Task(s) {ids}{why} are queued and will wait until one starts."
        if desired.get(provider):
            msg += f" Settings ask for {desired[provider]}, so one may still be starting; check get_status shortly."
        else:
            msg += (
                f' Ask the person whether to start one; if they say yes, call start_agents with provider "{provider}".'
            )
        warnings.append(msg)
        for t in stuck:
            queue.event(request.app.state.db, t["id"], "log", f"waiting: no {label} agent is online")
    anyone = [t for t in tasks if t["provider"] == "any" and t["status"] == "queued"]
    if anyone and not any(online.values()):
        warnings.append(
            "No agents are online at all; task(s) "
            + ", ".join(f"#{t['id']}" for t in anyone)
            + " will wait. Ask the person whether to start one (start_agents)."
        )
    return warnings


class StartIn(BaseModel):
    provider: str = Field(..., pattern="^(claude|codex)$")
    count: int = Field(1, ge=1, le=16, description="At least this many agents of that kind")


def start_agents(request: Request, body: StartIn) -> dict:
    """Raise the agent count for a provider in Settings (never lowers it) and apply, which starts the containers."""
    app = request.app.state
    label = LABELS[body.provider]
    if not any(app.secrets.get(name) for name in CREDENTIALS[body.provider]):
        raise HTTPException(
            400,
            f"{label} agents have no sign-in yet: add one of "
            + " or ".join(SECRET_FIELDS[n].split(" (")[0] for n in CREDENTIALS[body.provider])
            + " in Settings first",
        )
    s = load_settings(app.db)
    pool = getattr(s.agents, body.provider)
    before = pool.count
    pool.count = max(pool.count, body.count)
    if not pool.model:
        pool.model = default_model(SECTIONS[body.provider])
    if pool.count == before:
        return {"provider": body.provider, "count": pool.count, "started": False, "note": "already set; see get_status"}
    save_settings(app.db, s)
    run_id = app.apply.start(s)
    return {
        "provider": body.provider,
        "count": pool.count,
        "started": True,
        "apply_run": run_id,
        "note": f"{label} agents going from {before} to {pool.count}; they appear in get_status in a minute or two",
    }


@router.post("/agents/start", dependencies=[Depends(require("admin", "controller"))])
def start(body: StartIn, request: Request):
    return start_agents(request, body)
