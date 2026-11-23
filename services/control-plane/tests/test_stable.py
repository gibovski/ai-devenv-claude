import json

import httpx

from devenv import stable


def fake_cloudflare(calls, subdomain="gibbo"):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, req.content))
        if req.url.path.endswith("/workers/subdomain"):
            return httpx.Response(200, json={"success": True, "result": {"subdomain": subdomain}})
        return httpx.Response(200, json={"success": True, "result": {}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def enable(admin, **cf):
    admin.put("/api/secrets", json={"values": {"cloudflare_api_token": "cf-token"}})
    s = admin.get("/api/settings").json()["settings"]
    s["cloudflare"].update(tunnel_enabled=True, mode="quick", stable_enabled=True, account_id="acc", **cf)
    assert admin.put("/api/settings", json=s).status_code == 200


def test_worker_proxies_to_target():
    js = stable.worker_script("https://a-b-c.trycloudflare.com/")
    assert 'const TARGET = "https://a-b-c.trycloudflare.com";' in js
    assert "export default" in js


def test_sync_deploys_once_per_address_and_shows_it(admin, app):
    enable(admin, stable_name="my-devenv")
    db, store = app.state.db, app.state.secrets
    calls = []
    client = fake_cloudflare(calls)
    stable.sync(db, store, client, target="https://one.trycloudflare.com")
    puts = [c for c in calls if c[0] == "PUT"]
    assert puts and puts[0][1] == "/client/v4/accounts/acc/workers/scripts/my-devenv"
    assert b"https://one.trycloudflare.com" in puts[0][2]
    assert ("POST", "/client/v4/accounts/acc/workers/scripts/my-devenv/subdomain") in [(m, p) for m, p, _ in calls]

    n = len(calls)
    stable.sync(db, store, client, target="https://one.trycloudflare.com")
    assert len(calls) == n  # unchanged address: no redeploy
    stable.sync(db, store, client, target="https://two.trycloudflare.com")
    assert b"https://two.trycloudflare.com" in [c for c in calls if c[0] == "PUT"][-1][2]

    urls = admin.get("/api/controllers").json()["urls"]
    assert urls["stable"]["url"] == "https://my-devenv.gibbo.workers.dev"
    assert urls["public"] == "https://my-devenv.gibbo.workers.dev"


def test_default_name_is_per_install_and_errors_are_reported(admin, app):
    enable(admin)
    db, store = app.state.db, app.state.secrets
    name = stable.worker_name(db)
    assert name.startswith("devenv-") and name == stable.worker_name(db)

    def no_subdomain(req):
        return httpx.Response(200, json={"success": True, "result": {"subdomain": ""}})

    stable.sync(
        db, store, httpx.Client(transport=httpx.MockTransport(no_subdomain)), target="https://x.trycloudflare.com"
    )
    st = stable.status(db)
    assert st["url"] == "" and "workers.dev subdomain" in st["error"]


def test_off_by_default(app):
    calls = []
    stable.sync(app.state.db, app.state.secrets, fake_cloudflare(calls), target="https://x.trycloudflare.com")
    assert calls == [] and not stable.status(app.state.db)["enabled"]
    json.dumps(stable.status(app.state.db))
