"""Plugins page API: view and edit mcp.yaml, see what was rendered for each agent type."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import mcpconfig
from ..auth import admin_only
from ..state import kv_get

router = APIRouter(prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(admin_only)])


class YamlIn(BaseModel):
    yaml: str


@router.get("")
def get_plugins(request: Request):
    w: mcpconfig.Watcher = request.app.state.mcp_watcher
    text = w.src.read_text() if w.src.exists() else ""
    summary, error = None, w.error
    try:
        cfg = mcpconfig.parse(text)
        summary = {
            "servers": [
                {"name": n, "type": s.type, "description": s.description, "agents": s.agents, "enabled": s.enabled}
                for n, s in cfg.servers.items()
            ],
            "claude_plugins": cfg.plugins.claude.enabled,
            "marketplaces": list(cfg.plugins.claude.marketplaces),
            "rendered": mcpconfig.render_all(cfg),
        }
    except ValueError as e:
        error = str(e)
    return {
        "path": str(w.src),
        "yaml": text,
        "error": error,
        "summary": summary,
        "rendered_at": w.rendered_at,
        "version": kv_get(request.app.state.db, "agent_config_version", 0),
    }


@router.post("/validate")
def validate(body: YamlIn):
    try:
        mcpconfig.parse(body.yaml)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@router.put("")
def put_plugins(body: YamlIn, request: Request):
    try:
        mcpconfig.parse(body.yaml)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    w: mcpconfig.Watcher = request.app.state.mcp_watcher
    w.src.parent.mkdir(parents=True, exist_ok=True)
    w.src.write_text(body.yaml)
    changed = w.check()
    return {"ok": True, "changed": changed, "version": kv_get(request.app.state.db, "agent_config_version", 0)}
