"""Discover the public address of the quick tunnel (cloudflared --url, no Cloudflare account)."""

import os
import time

import httpx

METRICS_URL = os.environ.get("QUICK_TUNNEL_METRICS", "http://cloudflared-quick:20241/quicktunnel")
_cache: dict[str, float | str] = {"url": "", "at": 0.0}


def quick_tunnel_url(ttl: float = 30.0) -> str:
    """Return https://<name>.trycloudflare.com, or "" while the tunnel is not up."""
    if _cache["url"] and time.monotonic() - float(_cache["at"]) < ttl:
        return str(_cache["url"])
    try:
        host = httpx.get(METRICS_URL, timeout=2).json().get("hostname", "")
    except (httpx.HTTPError, ValueError):
        host = ""
    url = f"https://{host}" if host else ""
    _cache.update(url=url, at=time.monotonic())
    return url
