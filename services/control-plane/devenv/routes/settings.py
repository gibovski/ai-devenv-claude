from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import checks
from ..apply import ensure_worker_token, preview, render
from ..auth import admin_only
from ..catalogue.loader import catalogue
from ..settings_schema import SECRET_FIELDS, Settings
from ..state import load_settings, save_settings

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(admin_only)])


class SecretsIn(BaseModel):
    # Only the provided keys change; an empty string clears a secret.
    values: dict[str, str]


@router.get("/settings")
def get_settings(request: Request):
    s = load_settings(request.app.state.db)
    return {"settings": s.model_dump(), "secrets": secret_status(request)}


@router.put("/settings")
def put_settings(body: Settings, request: Request):
    save_settings(request.app.state.db, body)
    return {"settings": body.model_dump()}


@router.get("/secrets")
def secret_status(request: Request):
    status = request.app.state.secrets.status()
    return {name: {"label": label, **status.get(name, {"set": False})} for name, label in SECRET_FIELDS.items()}


@router.put("/secrets")
def put_secrets(body: SecretsIn, request: Request):
    unknown = set(body.values) - set(SECRET_FIELDS)
    if unknown:
        raise HTTPException(400, f"Unknown secrets: {', '.join(sorted(unknown))}")
    for name, value in body.values.items():
        request.app.state.secrets.set(name, value.strip())
    return secret_status(request)


class CheckIn(BaseModel):
    value: str | None = Field(None, description="Test this typed value instead of the stored one; it is not saved")


@router.post("/settings/check/{provider}")
def check(provider: str, request: Request, body: CheckIn | None = None):
    """Run a live check for one provider, with a typed value if given, else the stored credential."""
    store = request.app.state.secrets
    s = load_settings(request.app.state.db)
    secret_name = {
        "github": "github_token",
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "claude": "claude_code_oauth_token",
        "cloudflare": "cloudflare_api_token",
        "tunnel": "cloudflare_tunnel_token",
    }.get(provider)
    if not secret_name:
        raise HTTPException(404, "Unknown provider")
    value = ((body.value if body else None) or "").strip() or store.get(secret_name)
    if not value:
        return {"ok": False, "detail": "Nothing to test: paste a value above (or save one first)"}
    if provider == "github":
        return checks.check_github(value, request.app.state.cfg.github_api)
    if provider == "openai":
        return checks.check_openai(value)
    if provider == "anthropic":
        return checks.check_anthropic(value)
    if provider == "claude":
        return checks.check_claude_oauth_token(value)
    if provider == "cloudflare":
        return checks.check_cloudflare(value, s.cloudflare.account_id)
    return checks.check_tunnel_token(value)


@router.get("/models")
def models():
    return catalogue()


@router.get("/apply/preview")
def apply_preview(request: Request):
    app = request.app.state
    override, env = render(load_settings(app.db), app.secrets, ensure_worker_token(app.db, app.secrets))
    return {"diff": preview(app.cfg, override, env)}


@router.post("/apply")
def apply(request: Request):
    app = request.app.state
    run_id = app.apply.start(load_settings(app.db))
    return {"run_id": run_id}


@router.get("/apply/runs")
def apply_runs(request: Request):
    return request.app.state.db.all(
        "SELECT id, status, started_at, finished_at FROM apply_runs ORDER BY id DESC LIMIT 20"
    )


@router.get("/apply/runs/{run_id}")
def apply_run(run_id: int, request: Request, offset: int = 0):
    row = request.app.state.db.one("SELECT * FROM apply_runs WHERE id = ?", run_id)
    if not row:
        raise HTTPException(404, "No such run")
    row["log"] = row["log"][offset:]
    row["next_offset"] = offset + len(row["log"])
    return row
