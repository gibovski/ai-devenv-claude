import pytest
from fastapi.testclient import TestClient

from devenv.config import Config
from devenv.main import create_app


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVENV_DOCKER", "0")
    c = Config(
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        stack_dir=tmp_path / "stack",
        mcp_file=tmp_path / "mcp.yaml",
        docker_enabled=False,
    )
    for d in (c.data_dir, c.state_dir, c.stack_dir, c.uploads_dir):
        d.mkdir(parents=True, exist_ok=True)
    (c.state_dir / "initial-admin-password").write_text("first-boot-pw\n")
    return c


@pytest.fixture
def app(cfg):
    return create_app(cfg)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "first-boot-pw"})
    assert r.status_code == 200
    return client
