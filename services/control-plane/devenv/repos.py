"""Which repositories agents may work on, and creating new ones.

A task's `repo` can be:
- `owner/name` or just `name` (the configured owner is assumed): an existing repository;
- `new:name` (or `new:owner/name`): a repository the agent's task needs created. The control plane
  creates it (private by default, with a README) when an agent picks the task up;
- empty: the default repository if one is set, otherwise a task without code changes.

Settings fence this in: an allow list (empty means every repository of the owner), a block list that
always wins, and a switch for creating repositories. Patterns are shell-style (`infra-*`) and match
either `owner/name` or, for the owner's repositories, `name`."""

import base64
import fnmatch
import re
import threading
import time

import httpx

from .github import GitHub
from .settings_schema import GitHubSettings

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
NEW_PREFIX = "new:"
README_LIMIT = 8000
CACHE_SECONDS = 300


class RepoError(ValueError):
    pass


def _patterns(items: list[str]) -> list[str]:
    return [p.strip().lower() for p in items if p.strip()]


def _matches(full: str, owner: str, patterns: list[str]) -> bool:
    full_l = full.lower()
    o, _, name = full_l.partition("/")
    for p in patterns:
        if fnmatch.fnmatchcase(full_l, p):
            return True
        if "/" not in p and o == owner.lower() and fnmatch.fnmatchcase(name, p):
            return True
    return False


def allowed(full: str, gh: GitHubSettings) -> tuple[bool, str]:
    """Whether agents may work on `owner/name`, and why not."""
    if _matches(full, gh.owner, _patterns(gh.blocked_repos)):
        return False, f"{full} is on the blocked list in Settings → GitHub"
    allow = _patterns(gh.allowed_repos)
    if allow and not _matches(full, gh.owner, allow):
        return False, f"{full} is not on the allowed list in Settings → GitHub"
    return True, ""


def new_name(name: str, gh: GitHubSettings) -> str:
    suffix = gh.new_repo_suffix.strip()
    if suffix and not name.lower().endswith(suffix.lower()):
        name += suffix
    return name


def normalize(spec: str, gh: GitHubSettings) -> str:
    """Turn what a person or controller typed into `owner/name` or `new:owner/name`, applying the policy.

    Raises RepoError with a message for the person when the repo is malformed or not allowed."""
    spec = (spec or "").strip()
    if spec.startswith("https://github.com/"):
        spec = spec.removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if not spec:
        return ""
    create = spec.lower().startswith(NEW_PREFIX)
    if create:
        spec = spec[len(NEW_PREFIX) :].strip()
    owner, _, name = spec.rpartition("/")
    owner = owner or gh.owner
    if not owner:
        raise RepoError(f"Set the GitHub owner in Settings, or write the repo as owner/name (got {spec!r})")
    if "/" in owner or not NAME_RE.fullmatch(owner) or not NAME_RE.fullmatch(name) or name in (".", ".."):
        raise RepoError(f"repo must look like owner/name, name or new:name, got {spec!r}")
    if create:
        if not gh.allow_create_repos:
            raise RepoError("Creating repositories is turned off in Settings → GitHub")
        if gh.owner and owner.lower() != gh.owner.lower():
            raise RepoError(f"New repositories can only be created under {gh.owner}")
        name = new_name(name, gh)
    full = f"{owner}/{name}"
    ok, why = allowed(full, gh)
    if not ok:
        raise RepoError(why)
    return NEW_PREFIX + full if create else full


def default_repo(gh: GitHubSettings) -> str:
    d = gh.default_repo.strip()
    if not d:
        return ""
    return d if "/" in d else f"{gh.owner}/{d}" if gh.owner else d


# ---------- GitHub calls ----------


def _gh(token: str, api: str, client: httpx.Client | None = None) -> GitHub:
    return GitHub(token, api, client)


def ensure_repo(full: str, description: str, gh: GitHubSettings, token: str, api: str, client=None) -> dict:
    """Create `owner/name` unless it already exists. Returns {"created": bool, "default_branch": str, "url": str}."""
    g = _gh(token, api, client)
    existing = g.get(f"/repos/{full}")
    if existing:
        return {"created": False, "default_branch": existing.get("default_branch", "main"), "url": existing["html_url"]}
    owner, name = full.split("/", 1)
    me = (g.get("/user") or {}).get("login", "")
    path = "/user/repos" if me.lower() == owner.lower() else f"/orgs/{owner}/repos"
    r = g.client.post(
        path,
        json={
            "name": name,
            "description": description[:300],
            "private": gh.new_repos_private,
            "auto_init": True,  # a README and a main branch, so the agent can branch and open a PR
        },
    )
    if r.status_code not in (200, 201):
        try:
            msg = r.json().get("message", r.text)
            errors = "; ".join(e.get("message", "") for e in r.json().get("errors", []) if isinstance(e, dict))
        except ValueError:
            msg, errors = r.text, ""
        raise RepoError(f"GitHub refused to create {full}: {msg}{' (' + errors + ')' if errors else ''}")
    data = r.json()
    return {"created": True, "default_branch": data.get("default_branch") or "main", "url": data["html_url"]}


_cache: dict[tuple, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def list_repos(gh: GitHubSettings, token: str, api: str, client=None, fresh: bool = False) -> list[dict]:
    """The owner's repositories (private ones too when the token can see them), newest activity first."""
    key = (api, gh.owner.lower(), token[-8:])
    with _lock:
        hit = _cache.get(key)
        if hit and not fresh and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    g = _gh(token, api, client)
    me = (g.get("/user") or {}).get("login", "")
    owner = gh.owner or me
    if me.lower() == owner.lower():
        path, params = "/user/repos", {"affiliation": "owner", "sort": "pushed"}
    else:
        org = g.get(f"/orgs/{owner}")
        path, params = (
            (f"/orgs/{owner}/repos", {"sort": "pushed"}) if org else (f"/users/{owner}/repos", {"sort": "pushed"})
        )
    out: list[dict] = []
    for page in range(1, 11):
        batch = g.get(path, per_page=100, page=page, **params) or []
        out += batch
        if len(batch) < 100:
            break
    repos = [
        {
            "repo": r["full_name"],
            "description": r.get("description") or "",
            "private": r.get("private", False),
            "archived": r.get("archived", False),
            "default_branch": r.get("default_branch", "main"),
            "language": r.get("language") or "",
            "topics": r.get("topics", []),
            "pushed_at": r.get("pushed_at", ""),
            "url": r.get("html_url", ""),
        }
        for r in out
    ]
    repos.sort(key=lambda r: r["pushed_at"] or "", reverse=True)
    with _lock:
        _cache[key] = (time.time(), repos)
    return repos


def forget_cache() -> None:
    with _lock:
        _cache.clear()


def readme(full: str, token: str, api: str, client=None, limit: int = README_LIMIT) -> str:
    data = _gh(token, api, client).get(f"/repos/{full}/readme")
    if not data or "content" not in data:
        return ""
    text = base64.b64decode(data["content"]).decode("utf-8", "replace")
    return text if len(text) <= limit else text[:limit] + "\n\n[README truncated]"
