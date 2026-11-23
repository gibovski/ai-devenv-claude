"""Per-controller API tokens (Claude, ChatGPT, ...) and connection details."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth
from ..state import load_settings
from ..tunnel import quick_tunnel_url

router = APIRouter(prefix="/api/controllers", tags=["controllers"], dependencies=[Depends(auth.admin_only)])


class ControllerIn(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{1,30}$", description="e.g. claude, chatgpt")


def base_urls(request: Request) -> dict:
    s = load_settings(request.app.state.db)
    local = str(request.base_url).rstrip("/")
    cf = s.cloudflare
    if not cf.tunnel_enabled:
        public = ""
    elif cf.mode == "quick":
        public = quick_tunnel_url()
    else:
        public = f"https://{cf.hostname}" if cf.hostname else ""
    return {"local": local, "public": public, "tunnel_mode": cf.mode if cf.tunnel_enabled else ""}


@router.get("")
def list_controllers(request: Request):
    rows = request.app.state.db.all(
        "SELECT name, created_at, last_used_at, revoked FROM api_tokens WHERE kind = 'controller' ORDER BY created_at DESC"
    )
    return {"controllers": rows, "urls": base_urls(request)}


@router.post("", status_code=201)
def create_controller(body: ControllerIn, request: Request):
    db = request.app.state.db
    if db.one("SELECT 1 FROM api_tokens WHERE kind = 'controller' AND name = ? AND revoked = 0", body.name):
        raise HTTPException(409, f"{body.name} already has an active token; revoke it first")
    token = auth.issue_token(db, "controller", body.name)
    urls = base_urls(request)
    base = urls["public"] or urls["local"]
    return {
        "name": body.name,
        "token": token,
        "mcp_url": f"{base}/mcp",
        "mcp_url_with_token": f"{base}/mcp/t/{token}",
        "openapi_url": f"{base}/openapi.json",
        "note": "Shown once. Use the Bearer header where the client supports it, else the URL with the token.",
    }


@router.delete("/{name}")
def revoke(name: str, request: Request):
    cur = request.app.state.db.run("UPDATE api_tokens SET revoked = 1 WHERE kind = 'controller' AND name = ?", name)
    if not cur.rowcount:
        raise HTTPException(404, "No such controller")
    return {"ok": True}
