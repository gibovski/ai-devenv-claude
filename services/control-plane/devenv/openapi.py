"""OpenAPI document for controllers (ChatGPT actions, scripts): bearer auth and a public server URL."""

import json
import os
import sys

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def install(app: FastAPI) -> None:
    def custom():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
        schema["security"] = [{"bearer": []}]
        public = os.environ.get("DEVENV_PUBLIC_URL")
        if public:
            schema["servers"] = [{"url": public}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom


def main() -> None:
    """python -m devenv.openapi > docs/controllers/openapi.json"""
    import tempfile
    from pathlib import Path

    from .config import Config
    from .main import create_app

    tmp = Path(tempfile.mkdtemp())
    for d in (tmp / "d" / "uploads", tmp / "s"):
        d.mkdir(parents=True, exist_ok=True)
    cfg = Config(data_dir=tmp / "d", state_dir=tmp / "s", stack_dir=tmp, mcp_file=tmp / "m.yaml", docker_enabled=False)
    app = create_app(cfg, background=False)
    json.dump(app.openapi(), sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
