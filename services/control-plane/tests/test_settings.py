import time

from devenv.catalogue.loader import catalogue


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]


def test_login_required(client):
    assert client.get("/api/settings").status_code == 401


def test_login_and_password_change(admin, cfg):
    assert admin.get("/api/auth/me").json()["must_change_password"] is True
    r = admin.post("/api/auth/password", json={"current": "first-boot-pw", "new": "a-much-better-password"})
    assert r.status_code == 200
    assert not (cfg.state_dir / "initial-admin-password").exists()
    assert admin.get("/api/auth/me").json()["must_change_password"] is False


def test_secrets_never_returned(admin, app):
    r = admin.put("/api/secrets", json={"values": {"anthropic_api_key": "sk-ant-secret-value"}})
    assert r.status_code == 200
    body = admin.get("/api/settings").text
    assert "sk-ant-secret-value" not in body
    assert admin.get("/api/secrets").json()["anthropic_api_key"]["set"] is True
    raw = app.state.db.one("SELECT ciphertext FROM secrets WHERE name = 'anthropic_api_key'")["ciphertext"]
    assert b"sk-ant-secret-value" not in raw
    assert app.state.secrets.get("anthropic_api_key") == "sk-ant-secret-value"


def test_unknown_secret_rejected(admin):
    assert admin.put("/api/secrets", json={"values": {"nope": "x"}}).status_code == 400


def test_settings_roundtrip(admin):
    s = admin.get("/api/settings").json()["settings"]
    s["agents"]["claude"]["count"] = 3
    s["agents"]["codex"]["count"] = 2
    assert admin.put("/api/settings", json=s).status_code == 200
    assert admin.get("/api/settings").json()["settings"]["agents"]["claude"]["count"] == 3


def test_settings_validation(admin):
    s = admin.get("/api/settings").json()["settings"]
    s["agents"]["claude"]["count"] = 99
    assert admin.put("/api/settings", json=s).status_code == 422


def test_catalogue_tiers_sorted():
    tiers = [m["usage"] for m in catalogue()["anthropic"]]
    order = ["very-high", "high", "medium", "low"]
    assert tiers == sorted(tiers, key=order.index)


def test_apply_preview_and_run(admin, cfg):
    admin.put("/api/secrets", json={"values": {"anthropic_api_key": "sk-ant-xyz"}})
    s = admin.get("/api/settings").json()["settings"]
    s["agents"]["claude"]["count"] = 2
    admin.put("/api/settings", json=s)
    diff = admin.get("/api/apply/preview").json()["diff"]
    assert "replicas: 2" in diff and "sk-ant-xyz" not in diff and "ANTHROPIC_API_KEY='********'" in diff
    run_id = admin.post("/api/apply").json()["run_id"]
    for _ in range(50):
        run = admin.get(f"/api/apply/runs/{run_id}").json()
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "succeeded", run["log"]
    assert "replicas: 2" in cfg.override_path.read_text()
    assert (cfg.env_path.stat().st_mode & 0o777) == 0o600
    assert "ANTHROPIC_API_KEY=sk-ant-xyz" in cfg.env_path.read_text()


def test_claude_oauth_token_check():
    from devenv import checks

    assert checks.check_claude_oauth_token("sk-ant-oat01-abc")["ok"]
    assert not checks.check_claude_oauth_token("sk-ant-api03-abc")["ok"]
