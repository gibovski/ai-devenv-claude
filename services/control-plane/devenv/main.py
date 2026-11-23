"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__, auth, done, mcp, mcpconfig, openapi, queue, stable
from .apply import ApplyEngine, reconcile_workers
from .background import Loop
from .config import Config, load
from .db import Database
from .routes import agents as agent_routes
from .routes import auth as auth_routes
from .routes import controllers as controller_routes
from .routes import plugins as plugin_routes
from .routes import repos as repo_routes
from .routes import settings as settings_routes
from .routes import tasks as task_routes
from .routes import workers as worker_routes
from .secretstore import SecretStore, load_key
from .state import load_settings

log = logging.getLogger("devenv")


def create_app(cfg: Config | None = None, background: bool = True) -> FastAPI:
    cfg = cfg or load()
    db = Database(cfg.db_path)
    secrets = SecretStore(db, load_key(cfg.state_dir))
    auth.bootstrap_admin(db, cfg.state_dir)
    engine = ApplyEngine(cfg, db, secrets)

    watcher = mcpconfig.Watcher(cfg.mcp_file, cfg.state_dir / "agent-config", db)
    loop = Loop()
    loop.add("mcp-config", watcher.check, every=10)
    loop.add("leases", lambda: queue.expire_leases(db), every=15)
    loop.add("stable-address", lambda: stable.sync(db, secrets), every=30)
    loop.add("done", lambda: done.check_all(db, secrets.get("github_token"), cfg.github_api), every=30)

    def supervise():
        s = load_settings(db)
        note = reconcile_workers(engine, {"claude": s.agents.claude.count, "codex": s.agents.codex.count})
        if note:
            log.info(note)

    loop.add("supervisor", supervise, every=60)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if background:
            loop.start()
        for hook in app.state.startup:
            hook(app)
        yield
        loop.stop()

    app = FastAPI(
        title="AI Dev Environment control plane",
        version=__version__,
        description="Settings, agents, work queue and controller API for the AI dev environment.",
        lifespan=lifespan,
    )
    app.state.cfg, app.state.db, app.state.secrets, app.state.apply = cfg, db, secrets, engine
    app.state.loop, app.state.startup, app.state.mcp_watcher = loop, [], watcher

    @app.get("/api/health", tags=["health"])
    def health():
        return {"ok": True, "version": __version__, "schema": db.migrate()}

    for r in (
        auth_routes,
        settings_routes,
        worker_routes,
        agent_routes,
        task_routes,
        controller_routes,
        plugin_routes,
        repo_routes,
        mcp,
    ):
        app.include_router(r.router)
    openapi.install(app)
    return app
