"""The repositories agents may work on, for people and controllers planning work."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import inbox, repos
from ..auth import require
from ..state import kv_get, load_settings

router = APIRouter(prefix="/api", tags=["repos"], dependencies=[Depends(require("admin", "controller"))])


def policy(gh) -> dict:
    return {
        "owner": gh.owner,
        "default_repo": repos.default_repo(gh),
        "can_create": gh.allow_create_repos,
        "new_repo_suffix": gh.new_repo_suffix,
        "new_repos_private": gh.new_repos_private,
        "allowed": gh.allowed_repos,
        "blocked": gh.blocked_repos,
        "how_to_target": "repo: 'name' or 'owner/name' for an existing repository, 'new:name' to create one "
        "(the suffix is added for you), empty for the default repository",
    }


def _token(request: Request) -> str:
    token = request.app.state.secrets.get("github_token")
    if not token:
        raise HTTPException(409, "Add a GitHub token in Settings first")
    return token


@router.get("/repos")
def list_repos(request: Request, q: str = "", include_archived: bool = False, refresh: bool = False):
    """Repositories agents may work on (the owner's, filtered by the allowed and blocked lists)."""
    s = load_settings(request.app.state.db)
    try:
        found = repos.list_repos(s.github, _token(request), request.app.state.cfg.github_api, fresh=refresh)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub: {e}") from None
    q = q.lower().strip()
    out = [
        r
        for r in found
        if repos.allowed(r["repo"], s.github)[0]
        and (include_archived or not r["archived"])
        and (not q or q in r["repo"].lower() or q in r["description"].lower() or any(q in t for t in r["topics"]))
    ]
    return {"policy": policy(s.github), "repos": out}


@router.get("/repos/{owner}/{name}/readme")
def repo_readme(owner: str, name: str, request: Request):
    s = load_settings(request.app.state.db)
    full = f"{owner}/{name}"
    ok, why = repos.allowed(full, s.github)
    if not ok:
        raise HTTPException(403, why)
    try:
        text = repos.readme(full, _token(request), request.app.state.cfg.github_api)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub: {e}") from None
    return {"repo": full, "readme": text}


@router.get("/inbox")
def inbox_status(request: Request):
    """The GitHub control repository: where controllers open issues, and how the last sync went."""
    s = load_settings(request.app.state.db).github
    status = kv_get(request.app.state.db, "inbox_status", {}) or {}
    repo = inbox.control_repo(s)
    return {
        "enabled": s.inbox_enabled,
        "repo": repo,
        "label": s.inbox_label,
        "url": f"https://github.com/{repo}/issues" if repo else "",
        "last": status,
    }


@router.post("/inbox/sync", dependencies=[Depends(require("admin"))])
def inbox_sync(request: Request):
    app = request.app.state
    s = load_settings(app.db).github
    if not s.inbox_enabled:
        raise HTTPException(409, "Turn on the GitHub inbox in Settings first")
    _token(request)
    inbox.sync(app.db, app.secrets, app.cfg.github_api, app.cfg.uploads_dir)
    return inbox_status(request)
