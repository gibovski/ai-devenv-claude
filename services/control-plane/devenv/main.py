"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__, auth
from .apply import ApplyEngine
from .config import Config, load
from .db import Database
from .routes import auth as auth_routes
from .routes import settings as settings_routes
from .secretstore import SecretStore, load_key


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load()
    db = Database(cfg.db_path)
    secrets = SecretStore(db, load_key(cfg.state_dir))
    auth.bootstrap_admin(db, cfg.state_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for hook in app.state.startup:
            hook(app)
        yield
        for hook in app.state.shutdown:
            hook(app)

    app = FastAPI(title="AI Dev Environment control plane", version=__version__, lifespan=lifespan)
    app.state.cfg, app.state.db, app.state.secrets = cfg, db, secrets
    app.state.apply = ApplyEngine(cfg, db, secrets)
    app.state.startup, app.state.shutdown = [], []

    @app.get("/api/health", tags=["health"])
    def health():
        return {"ok": True, "version": __version__, "schema": db.migrate()}

    app.include_router(auth_routes.router)
    app.include_router(settings_routes.router)
    return app
