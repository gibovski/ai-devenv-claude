import json
import tomllib

import pytest

from devenv import mcpconfig

GOOD = """
version: 1
servers:
  github: {type: http, url: "https://api.githubcopilot.com/mcp/", bearer_token_env: GITHUB_TOKEN}
  docs: {type: stdio, command: npx, args: ["-y", "pkg@1"], env: {A: "${A}"}, agents: [claude]}
  unused: {type: stdio, command: x, enabled: false}
plugins:
  claude:
    marketplaces: {official: {github: anthropics/claude-plugins-official}}
    enabled: [review@official]
"""


def test_render():
    cfg = mcpconfig.parse(GOOD)
    out = mcpconfig.render_all(cfg)
    claude = json.loads(out["claude"]["mcp.json"])["mcpServers"]
    assert set(claude) == {"github", "docs"}
    assert claude["github"]["headers"]["Authorization"] == "Bearer ${GITHUB_TOKEN}"
    settings = json.loads(out["claude"]["home/.claude/settings.json"])
    assert settings["enabledPlugins"] == {"review@official": True}
    assert settings["extraKnownMarketplaces"]["official"]["source"]["repo"] == "anthropics/claude-plugins-official"
    codex = tomllib.loads(out["codex"]["home/.codex/config.toml"])["mcp_servers"]
    assert set(codex) == {"github"} and codex["github"]["bearer_token_env_var"] == "GITHUB_TOKEN"


@pytest.mark.parametrize(
    "bad",
    [
        "servers: {x: {type: stdio}}",
        "servers: {x: {type: http, url: ftp://a}}",
        "servers: {'a b': {type: stdio, command: c}}",
        "plugins: {claude: {enabled: [noat]}}",
        "version: 2",
        ": [",
    ],
)
def test_invalid(bad):
    with pytest.raises(ValueError):
        mcpconfig.parse(bad)


def test_repo_mcp_yaml_is_valid():
    from pathlib import Path

    mcpconfig.parse((Path(__file__).parents[3] / "mcp" / "mcp.yaml").read_text())


def test_watcher_bumps_version_and_api(admin, app, cfg):
    cfg.mcp_file.write_text(GOOD)
    w = app.state.mcp_watcher
    assert w.check() is True
    assert w.check() is False  # unchanged
    out = cfg.state_dir / "agent-config"
    assert (out / "claude" / "mcp.json").exists() and (out / "codex" / "home/.codex/config.toml").exists()
    assert (out / "claude" / "mcp.json").stat().st_mode & 0o777 == 0o644
    r = admin.get("/api/plugins").json()
    assert r["version"] == 1 and r["error"] == "" and len(r["summary"]["servers"]) == 3
    assert admin.put("/api/plugins", json={"yaml": "servers: {x: {type: stdio}}"}).status_code == 400
    r = admin.put("/api/plugins", json={"yaml": GOOD.replace("pkg@1", "pkg@2")}).json()
    assert r["changed"] is True and r["version"] == 2


def test_heartbeat_reports_config_version(worker, app, cfg):
    cfg.mcp_file.write_text(GOOD)
    app.state.mcp_watcher.check()
    assert worker("POST", "/api/workers/w1/heartbeat", json={"state": "idle"}).json()["config_version"] == 1
