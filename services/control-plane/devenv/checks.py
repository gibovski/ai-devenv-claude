"""Live credential checks against each provider. Each returns {ok, detail, ...} and never echoes the secret."""

import httpx

TIMEOUT = httpx.Timeout(10.0)


def _fail(e: Exception | str) -> dict:
    return {"ok": False, "detail": str(e)}


def check_github(token: str, api: str = "https://api.github.com") -> dict:
    try:
        r = httpx.get(
            f"{api}/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        return _fail(e)
    if r.status_code != 200:
        return _fail(f"GitHub returned {r.status_code}")
    scopes = r.headers.get("x-oauth-scopes", "")
    return {
        "ok": True,
        "detail": f"Signed in as {r.json().get('login')}",
        "login": r.json().get("login"),
        "scopes": scopes,
    }


def check_openai(key: str) -> dict:
    try:
        r = httpx.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        return _fail(e)
    if r.status_code != 200:
        return _fail(f"OpenAI returned {r.status_code}")
    ids = sorted(m["id"] for m in r.json().get("data", []))
    return {"ok": True, "detail": f"{len(ids)} models available", "models": ids}


def check_anthropic(key: str) -> dict:
    try:
        r = httpx.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            params={"limit": 100},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        return _fail(e)
    if r.status_code != 200:
        return _fail(f"Anthropic returned {r.status_code}")
    ids = sorted(m["id"] for m in r.json().get("data", []))
    return {"ok": True, "detail": f"{len(ids)} models available", "models": ids}


def check_claude_oauth_token(token: str) -> dict:
    """Format check only: subscription tokens are used by Claude Code itself, not the public API."""
    if not token.startswith("sk-ant-oat"):
        return _fail("This does not look like a token from `claude setup-token` (it should start with sk-ant-oat)")
    return {
        "ok": True,
        "detail": "Looks like a Claude subscription token. Agents share your plan's usage limits.",
    }


def check_cloudflare(token: str, account_id: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    urls = ["https://api.cloudflare.com/client/v4/user/tokens/verify"]
    if account_id:
        urls.append(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/verify")
    last = "no response"
    for url in urls:
        try:
            r = httpx.get(url, headers=headers, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            last = str(e)
            continue
        if r.status_code == 200 and r.json().get("success"):
            return {"ok": True, "detail": f"Token is {r.json()['result'].get('status', 'valid')}"}
        last = f"Cloudflare returned {r.status_code}"
    return _fail(last)


def check_tunnel_token(token: str) -> dict:
    import base64
    import json

    try:
        data = json.loads(base64.b64decode(token + "==="))
        return {"ok": bool(data.get("t")), "detail": f"Tunnel {data.get('t', '?')}"}
    except ValueError as e:
        return _fail(f"Not a tunnel token: {e}")
