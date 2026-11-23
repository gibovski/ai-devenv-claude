"""Remote MCP server (streamable HTTP, JSON responses) exposing the queue to Claude and ChatGPT.

Auth: `Authorization: Bearer <controller token>` or the token in the path (`/mcp/t/<token>`) for
clients that cannot send headers. Each controller (e.g. "claude", "chatgpt") has its own token."""

import base64
import hashlib
import json
from importlib import resources

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from . import __version__, auth, queue
from .routes.agents import agent_status
from .routes.tasks import PlanIn, TaskPatch, _create, patch_task

router = APIRouter(tags=["mcp"])
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "Local id other tasks in this plan can depend on"},
        "title": {"type": "string"},
        "description": {"type": "string", "description": "What to change, acceptance criteria, how to test"},
        "repo": {
            "type": "string",
            "description": "Existing repository as name or owner/name (see list_repos), new:name to create a "
            "repository for this task, or omit for the default repository",
        },
        "depends_on": {
            "type": "array",
            "items": {"type": ["string", "integer"]},
            "description": "Keys in this plan or existing task ids",
        },
        "priority": {"type": "integer"},
        "provider": {"type": "string", "enum": ["any", "claude", "codex"]},
    },
    "required": ["title"],
}

TOOLS = [
    {
        "name": "create_tasks",
        "description": "Queue a plan of tasks for the coding agents. Dependencies may use keys from the same plan. "
        "A task starts only when all its dependencies are done. Read get_planning_guide first.",
        "inputSchema": {
            "type": "object",
            "properties": {"tasks": {"type": "array", "items": TASK_SCHEMA}, "default_repo": {"type": "string"}},
            "required": ["tasks"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks with their state (ready, blocked, in_progress, in_review, deploying, done, needs_human) and dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
                "include_done": {"type": "boolean"},
            },
        },
    },
    {
        "name": "get_task",
        "description": "Get one task with dependencies, dependents, attachments, PR and the latest log lines.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "log_lines": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "get_status",
        "description": "Agent availability and status (idle, busy, error, offline), current tasks, and queue counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_task",
        "description": "Edit a task (title, description, priority, repo, provider) or act on it: cancel, requeue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "integer"},
                "repo": {"type": "string"},
                "provider": {"type": "string", "enum": ["any", "claude", "codex"]},
                "action": {"type": "string", "enum": ["cancel", "requeue"]},
            },
            "required": ["id"],
        },
    },
    {
        "name": "upload_file",
        "description": "Attach a file to a task; the agent finds it in its workspace when the task starts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "filename": {"type": "string"},
                "content_base64": {"type": "string", "description": "File content, base64-encoded"},
                "content_text": {"type": "string", "description": "Alternative to content_base64 for text files"},
            },
            "required": ["task_id", "filename"],
        },
    },
    {
        "name": "list_repos",
        "description": "Repositories the agents may work on, with descriptions, languages and topics, plus the "
        "rules for creating new ones. Use it to pick each task's repo; read get_repo_readme when unsure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filter by words in the name, description or topics"},
                "include_archived": {"type": "boolean"},
            },
        },
    },
    {
        "name": "get_repo_readme",
        "description": "The README of one repository (owner/name or name), to judge whether work belongs there.",
        "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}}, "required": ["repo"]},
    },
    {
        "name": "get_planning_guide",
        "description": "How to break an idea into the smallest practical tasks with dependencies for this queue.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def planning_prompt() -> str:
    return resources.files("devenv").joinpath("planning_prompt.md").read_text()


def _principal(request: Request, path_token: str | None) -> auth.Principal:
    token = path_token
    header = request.headers.get("authorization", "")
    if not token and header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        raise HTTPException(401, "Controller token required", headers={"WWW-Authenticate": "Bearer"})
    row = request.app.state.db.one(
        "SELECT kind, name FROM api_tokens WHERE token_hash = ? AND revoked = 0", auth.sha(token)
    )
    if not row or row["kind"] not in ("controller", "admin"):
        raise HTTPException(401, "Invalid controller token", headers={"WWW-Authenticate": "Bearer"})
    request.app.state.db.run(
        "UPDATE api_tokens SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE token_hash = ?",
        auth.sha(token),
    )
    return auth.Principal("controller", row["name"])


def _text(obj) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(obj, indent=1, default=str)}],
        "structuredContent": obj if isinstance(obj, dict) else {"result": obj},
    }


def call_tool(request: Request, p: auth.Principal, name: str, args: dict) -> dict:
    db = request.app.state.db
    if name == "create_tasks":
        created = _create(request, PlanIn.model_validate(args), p)
        return _text(
            {
                "created": [
                    {
                        "id": t["id"],
                        "key": t["plan_key"],
                        "title": t["title"],
                        "state": t["state"],
                        "depends_on": [d["id"] for d in t["deps"]],
                    }
                    for t in created
                ]
            }
        )
    if name == "list_tasks":
        tasks = queue.list_tasks(db, args.get("status"))
        if not args.get("include_done", False) and not args.get("status"):
            tasks = [t for t in tasks if t["status"] not in ("done", "cancelled")]
        return _text(
            {
                "tasks": [
                    {k: t[k] for k in ("id", "title", "state", "repo", "attempts", "pr_url", "worker_id")}
                    | {"depends_on": [{"id": d["id"], "status": d["status"]} for d in t["deps"]]}
                    for t in tasks
                ]
            }
        )
    if name == "get_task":
        t = queue.get_task(db, int(args["id"]))
        n = int(args.get("log_lines", 40))
        t["log"] = list(
            reversed(
                db.all(
                    "SELECT at, kind, message FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT ?", t["id"], n
                )
            )
        )
        return _text(t)
    if name == "get_status":
        return _text(agent_status(request))
    if name == "update_task":
        body = TaskPatch.model_validate({k: v for k, v in args.items() if k != "id"})
        if body.action == "mark_done":
            raise HTTPException(
                400, "Controllers cannot mark tasks done; the definition of done is checked automatically"
            )
        t = patch_task(int(args["id"]), body, request)
        return _text({"id": t["id"], "status": t["status"], "state": t["state"]})
    if name == "upload_file":
        from .routes.tasks import _dir, safe_name

        task_id = int(args["task_id"])
        queue.get_task(db, task_id)
        data = (
            base64.b64decode(args["content_base64"])
            if args.get("content_base64")
            else (args.get("content_text") or "").encode()
        )
        fname = safe_name(args["filename"])
        aid = db.run(
            "INSERT INTO attachments(task_id, filename, size, sha256) VALUES (?, ?, ?, ?)",
            task_id,
            fname,
            len(data),
            hashlib.sha256(data).hexdigest(),
        ).lastrowid
        (_dir(request, task_id) / str(aid)).write_bytes(data)
        queue.event(db, task_id, "log", f"{p.name} attached {fname} ({len(data)} bytes)")
        return _text({"attachment_id": aid, "filename": fname, "size": len(data)})
    if name == "list_repos":
        from .routes.repos import list_repos

        return _text(
            list_repos(request, q=args.get("query") or "", include_archived=bool(args.get("include_archived")))
        )
    if name == "get_repo_readme":
        from .repos import RepoError, normalize
        from .routes.repos import repo_readme
        from .state import load_settings

        try:
            full = normalize(str(args.get("repo", "")), load_settings(db).github)
        except RepoError as e:
            raise HTTPException(400, str(e)) from None
        if not full or full.startswith("new:"):
            raise HTTPException(400, "Give an existing repository as owner/name or name")
        owner, repo = full.split("/", 1)
        return _text(repo_readme(owner, repo, request))
    if name == "get_planning_guide":
        return {"content": [{"type": "text", "text": planning_prompt()}]}
    raise KeyError(name)


def handle(request: Request, p: auth.Principal, msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
    if mid is None:  # notification
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok(
            {
                "protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                "serverInfo": {"name": "devenv", "title": "AI Dev Environment queue", "version": __version__},
                "instructions": "Use get_planning_guide and list_repos, then create_tasks to queue work. get_status and list_tasks show progress.",
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "prompts/list":
        return ok(
            {
                "prompts": [
                    {
                        "name": "plan_project",
                        "description": "Break an idea into queued tasks",
                        "arguments": [{"name": "idea", "required": True}],
                    }
                ]
            }
        )
    if method == "prompts/get":
        idea = (params.get("arguments") or {}).get("idea", "")
        return ok(
            {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": planning_prompt() + "\n\n# The idea\n" + idea}}
                ]
            }
        )
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            return ok(call_tool(request, p, name, args))
        except KeyError:
            return err(-32602, f"Unknown tool {name}")
        except (HTTPException, ValidationError, ValueError) as e:
            detail = e.detail if isinstance(e, HTTPException) else str(e)
            return ok({"content": [{"type": "text", "text": f"Error: {detail}"}], "isError": True})
    return err(-32601, f"Method not found: {method}")


async def _serve(request: Request, token: str | None):
    p = _principal(request, token)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400
        )
    if isinstance(body, list):
        out = [r for r in (handle(request, p, m) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    r = handle(request, p, body)
    return JSONResponse(r) if r is not None else Response(status_code=202)


@router.post("/mcp")
async def mcp(request: Request):
    return await _serve(request, None)


@router.post("/mcp/t/{token}")
async def mcp_path_token(token: str, request: Request):
    return await _serve(request, token)


@router.get("/mcp")
@router.get("/mcp/t/{token}")
def mcp_get():
    # No server-initiated stream; clients fall back to plain request/response.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
@router.delete("/mcp/t/{token}")
def mcp_delete():
    return Response(status_code=204)
