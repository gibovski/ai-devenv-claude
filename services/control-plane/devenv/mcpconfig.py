"""Plugins/MCP as code: validate mcp/mcp.yaml and render it into Claude Code and Codex configs."""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

AGENTS = ("claude", "codex")


class Server(BaseModel):
    description: str = ""
    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    bearer_token_env: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    agents: list[Literal["claude", "codex"]] = Field(default_factory=lambda: list(AGENTS))
    enabled: bool = True

    @model_validator(mode="after")
    def _shape(self):
        if self.type == "stdio" and not self.command:
            raise ValueError("stdio servers need a command")
        if self.type == "http" and not self.url.startswith(("http://", "https://")):
            raise ValueError("http servers need an http(s) url")
        return self


class Marketplace(BaseModel):
    github: str = ""
    git: str = ""


class ClaudePlugins(BaseModel):
    marketplaces: dict[str, Marketplace] = Field(default_factory=dict)
    enabled: list[str] = Field(default_factory=list)


class Plugins(BaseModel):
    claude: ClaudePlugins = Field(default_factory=ClaudePlugins)


class McpFile(BaseModel):
    version: Literal[1] = 1
    servers: dict[str, Server] = Field(default_factory=dict)
    plugins: Plugins = Field(default_factory=Plugins)

    @model_validator(mode="after")
    def _names(self):
        for name in self.servers:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError(f"server name {name!r} may only use letters, digits, _ and -")
        for p in self.plugins.claude.enabled:
            if "@" not in p:
                raise ValueError(f"plugin {p!r} must be name@marketplace")
        return self


def parse(text: str) -> McpFile:
    try:
        return McpFile.model_validate(yaml.safe_load(text) or {})
    except (yaml.YAMLError, ValidationError) as e:
        raise ValueError(str(e)) from e


def servers_for(cfg: McpFile, agent: str) -> dict[str, Server]:
    return {n: s for n, s in cfg.servers.items() if s.enabled and agent in s.agents}


def render_claude(cfg: McpFile) -> dict[str, str]:
    servers = {}
    for name, s in servers_for(cfg, "claude").items():
        if s.type == "stdio":
            entry = {"type": "stdio", "command": s.command, "args": s.args}
            if s.env:
                entry["env"] = s.env
        else:
            headers = dict(s.headers)
            if s.bearer_token_env:
                headers["Authorization"] = f"Bearer ${{{s.bearer_token_env}}}"
            entry = {"type": "http", "url": s.url}
            if headers:
                entry["headers"] = headers
        servers[name] = entry
    settings: dict = {}
    mk = cfg.plugins.claude.marketplaces
    if mk:
        settings["extraKnownMarketplaces"] = {
            n: {"source": {"source": "github", "repo": m.github} if m.github else {"source": "git", "url": m.git}}
            for n, m in mk.items()
        }
    if cfg.plugins.claude.enabled:
        settings["enabledPlugins"] = {p: True for p in cfg.plugins.claude.enabled}
    return {
        "mcp.json": json.dumps({"mcpServers": servers}, indent=2) + "\n",
        "home/.claude/settings.json": json.dumps(settings, indent=2) + "\n",
    }


def _toml_str(v: str) -> str:
    return json.dumps(v)  # JSON string escaping is valid TOML basic-string escaping


def render_codex(cfg: McpFile) -> dict[str, str]:
    lines = ["# Generated from mcp/mcp.yaml by the control plane. Do not edit.", ""]
    for name, s in servers_for(cfg, "codex").items():
        lines.append(f"[mcp_servers.{name}]")
        if s.type == "stdio":
            lines.append(f"command = {_toml_str(s.command)}")
            lines.append("args = [" + ", ".join(_toml_str(a) for a in s.args) + "]")
            if s.env:
                lines.append(
                    "env = { " + ", ".join(f"{_toml_str(k)} = {_toml_str(v)}" for k, v in s.env.items()) + " }"
                )
        else:
            lines.append(f"url = {_toml_str(s.url)}")
            if s.bearer_token_env:
                lines.append(f"bearer_token_env_var = {_toml_str(s.bearer_token_env)}")
        lines.append("")
    return {"home/.codex/config.toml": "\n".join(lines)}


def render_all(cfg: McpFile) -> dict[str, dict[str, str]]:
    return {"claude": render_claude(cfg), "codex": render_codex(cfg)}


def write(out_dir: Path, rendered: dict[str, dict[str, str]]) -> None:
    """Write rendered files world-readable (agents run as a non-root user and mount this read-only)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for agent, files in rendered.items():
        for rel, content in files.items():
            path = out_dir / agent / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(content)
            os.chmod(tmp, 0o644)
            tmp.replace(path)
    for d in [out_dir, *out_dir.rglob("*")]:
        if d.is_dir():
            os.chmod(d, 0o755)


class Watcher:
    """Re-renders agent config when mcp.yaml changes and bumps a version idle workers react to."""

    def __init__(self, src: Path, out_dir: Path, db):
        self.src, self.out_dir, self.db = src, out_dir, db
        self.digest = ""
        self.error = ""
        self.rendered_at = ""

    def check(self) -> bool:
        from .state import kv_get, kv_set

        if not self.src.exists():
            self.error = f"{self.src} not found"
            return False
        text = self.src.read_text()
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest == self.digest:
            return False
        self.digest = digest
        try:
            cfg = parse(text)
        except ValueError as e:
            self.error = str(e)
            return False
        write(self.out_dir, render_all(cfg))
        self.error = ""
        self.rendered_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if kv_get(self.db, "agent_config_digest") != digest:
            kv_set(self.db, "agent_config_digest", digest)
            kv_set(self.db, "agent_config_version", int(kv_get(self.db, "agent_config_version", 0)) + 1)
            return True
        return False
