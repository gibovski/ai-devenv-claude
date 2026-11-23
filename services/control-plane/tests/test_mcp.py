import json

import pytest


@pytest.fixture
def controller(admin):
    r = admin.post("/api/controllers", json={"name": "claude"})
    assert r.status_code == 201, r.text
    return r.json()


def rpc(client, method, params=None, token=None, path="/mcp", id=1):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        path, json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}, headers=headers
    )


def tool(client, token, name, args):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, token)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_requires_token(client):
    assert rpc(client, "tools/list").status_code == 401


def test_initialize_and_list(client, controller):
    r = rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}},
        controller["token"],
    ).json()
    assert r["result"]["protocolVersion"] == "2025-06-18"
    names = {t["name"] for t in rpc(client, "tools/list", token=controller["token"]).json()["result"]["tools"]}
    assert {"create_tasks", "list_tasks", "get_status", "upload_file", "get_task", "update_task"} <= names
    n = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {controller['token']}"},
    )
    assert n.status_code == 202


def test_path_token(client, controller):
    r = rpc(client, "tools/list", path=f"/mcp/t/{controller['token']}")
    assert r.status_code == 200


def test_plan_flow(client, controller, admin):
    tok = controller["token"]
    res = tool(
        client,
        tok,
        "create_tasks",
        {"tasks": [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"]}]},
    )
    created = res["structuredContent"]["created"]
    assert [c["state"] for c in created] == ["ready", "blocked"]
    up = tool(client, tok, "upload_file", {"task_id": created[0]["id"], "filename": "notes.md", "content_text": "# hi"})
    assert up["structuredContent"]["size"] == 4
    listed = tool(client, tok, "list_tasks", {})["structuredContent"]["tasks"]
    assert len(listed) == 2 and listed[1]["depends_on"][0]["id"] == created[0]["id"]
    got = tool(client, tok, "get_task", {"id": created[0]["id"]})["structuredContent"]
    assert got["attachments"][0]["filename"] == "notes.md"
    st = tool(client, tok, "get_status", {})["structuredContent"]
    assert st["queue"]["queued"] == 2
    assert (
        tool(client, tok, "update_task", {"id": created[1]["id"], "action": "cancel"})["structuredContent"]["status"]
        == "cancelled"
    )


def test_cycle_is_tool_error(client, controller):
    res = tool(
        client,
        controller["token"],
        "create_tasks",
        {"tasks": [{"key": "a", "title": "A", "depends_on": ["b"]}, {"key": "b", "title": "B", "depends_on": ["a"]}]},
    )
    assert res["isError"] and "cycle" in res["content"][0]["text"]


def test_planning_guide(client, controller):
    text = tool(client, controller["token"], "get_planning_guide", {})["content"][0]["text"]
    assert "smallest practical tasks" in text


def test_revoked_token(client, controller, admin):
    admin.delete("/api/controllers/claude")
    assert rpc(client, "tools/list", token=controller["token"]).status_code == 401


def test_controller_rest_access(client, controller):
    h = {"Authorization": f"Bearer {controller['token']}"}
    assert client.post("/api/tasks", json={"title": "x"}, headers=h).status_code == 201
    assert client.get("/api/agents", headers=h).status_code == 200
    assert client.get("/api/settings", headers=h).status_code == 403


def test_openapi_has_bearer(client):
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert "/api/tasks/bulk" in spec["paths"]
    json.dumps(spec)
