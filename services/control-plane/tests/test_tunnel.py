import time


def wait(admin, run_id):
    for _ in range(100):
        run = admin.get(f"/api/apply/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("apply did not finish")


def test_apply_runs_terraform_and_enables_tunnel(admin, cfg, app):
    tf = cfg.stack_dir / "terraform" / "cloudflare"
    tf.mkdir(parents=True)
    script = tf / "tf.sh"
    script.write_text(
        "#!/bin/sh\n"
        'echo "$@" >> calls.log\n'
        'case "$1 $3 $4" in\n'
        '  "output -raw tunnel_token") printf eyJ0IjoiYWJjIn0= ;;\n'
        '  "output -json service_tokens") echo \'{"baz-claude":{"client_id":"x","client_secret":"y"}}\' ;;\n'
        '  *) echo "Apply complete! host=$TF_VAR_hostname" ;;\n'
        "esac\n"
    )
    script.chmod(0o755)
    admin.put("/api/secrets", json={"values": {"cloudflare_api_token": "cf-token"}})
    s = admin.get("/api/settings").json()["settings"]
    s["cloudflare"].update(
        account_id="acc",
        zone="example.com",
        hostname="devenv.example.com",
        tunnel_enabled=True,
        mode="named",
        access_emails=["me@example.com"],
    )
    admin.put("/api/settings", json=s)
    run = wait(admin, admin.post("/api/apply").json()["run_id"])
    assert run["status"] == "succeeded", run["log"]
    assert "host=devenv.example.com" in run["log"]
    assert app.state.secrets.get("cloudflare_tunnel_token") == "eyJ0IjoiYWJjIn0="
    env = cfg.env_path.read_text()
    assert "COMPOSE_PROFILES=tunnel" in env and "TUNNEL_TOKEN=eyJ0IjoiYWJjIn0=" in env


def test_terraform_failure_fails_apply(admin, cfg):
    tf = cfg.stack_dir / "terraform" / "cloudflare"
    tf.mkdir(parents=True)
    (tf / "tf.sh").write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
    (tf / "tf.sh").chmod(0o755)
    admin.put("/api/secrets", json={"values": {"cloudflare_api_token": "cf-token"}})
    s = admin.get("/api/settings").json()["settings"]
    s["cloudflare"].update(
        account_id="acc", zone="example.com", hostname="h.example.com", tunnel_enabled=True, mode="named"
    )
    admin.put("/api/settings", json=s)
    run = wait(admin, admin.post("/api/apply").json()["run_id"])
    assert run["status"] == "failed" and "boom" in run["log"]


def test_no_tunnel_without_settings(admin, cfg):
    run = wait(admin, admin.post("/api/apply").json()["run_id"])
    assert run["status"] == "succeeded"
    assert "COMPOSE_PROFILES=''" in cfg.env_path.read_text()


def test_quick_tunnel_needs_no_account(admin, cfg, app, monkeypatch):
    from devenv import apply, tunnel
    from devenv.state import load_settings

    s = admin.get("/api/settings").json()["settings"]
    assert s["cloudflare"]["mode"] == "quick"
    s["cloudflare"]["tunnel_enabled"] = True
    admin.put("/api/settings", json=s)
    _, env = apply.render(load_settings(app.state.db), app.state.secrets, "w")
    assert "quicktunnel" in env["COMPOSE_PROFILES"].split(",")
    assert not apply.tunnel_wanted(load_settings(app.state.db), app.state.secrets)

    monkeypatch.setattr(tunnel, "_cache", {"url": "", "at": 0.0})

    class R:
        def json(self):
            return {"hostname": "brave-words-here.trycloudflare.com"}

    monkeypatch.setattr(tunnel.httpx, "get", lambda *a, **k: R())
    urls = admin.get("/api/controllers").json()["urls"]
    assert urls["public"] == "https://brave-words-here.trycloudflare.com"
    assert urls["tunnel_mode"] == "quick"
