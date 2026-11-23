"""Runtime configuration from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DEVENV_DATA", "/data")))
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get("DEVENV_STATE", "/state")))
    stack_dir: Path = field(default_factory=lambda: Path(os.environ.get("DEVENV_STACK", "/opt/devenv")))
    mcp_file: Path = field(default_factory=lambda: Path(os.environ.get("DEVENV_MCP_FILE", "/opt/devenv/mcp/mcp.yaml")))
    docker_enabled: bool = field(default_factory=lambda: os.environ.get("DEVENV_DOCKER", "1") == "1")
    github_api: str = field(default_factory=lambda: os.environ.get("DEVENV_GITHUB_API", "https://api.github.com"))
    lease_seconds: int = field(default_factory=lambda: int(os.environ.get("DEVENV_LEASE_SECONDS", "1800")))
    heartbeat_timeout: int = field(default_factory=lambda: int(os.environ.get("DEVENV_HEARTBEAT_TIMEOUT", "90")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "devenv.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def override_path(self) -> Path:
        return self.state_dir / "compose.override.yaml"

    @property
    def env_path(self) -> Path:
        return self.state_dir / "stack.env"


def load() -> Config:
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg
