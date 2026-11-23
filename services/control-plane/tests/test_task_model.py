import pytest

from devenv.catalogue.loader import catalogue, choose_model


def test_catalogue_maps_every_level_to_listed_models():
    cat = catalogue()
    assert list(cat["complexity"]) == ["trivial", "small", "medium", "large", "hard"]
    assert cat["complexity"]["trivial"]["anthropic"] == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("task", "provider", "expected"),
    [
        (
            {"complexity": "trivial"},
            "claude",
            {"model": "claude-haiku-5-5", "effort": "low", "source": "complexity trivial"},
        ),
        ({"complexity": "trivial"}, "codex", {"model": "gpt-5-nano", "effort": "low", "source": "complexity trivial"}),
        (
            {"complexity": "hard", "effort": "max"},
            "claude",
            {"model": "claude-opus-5-5", "effort": "max", "source": "complexity hard"},
        ),
        (
            {"complexity": "small", "model": "claude-fable-5-2"},
            "claude",
            {"model": "claude-fable-5-2", "effort": "medium", "source": "task"},
        ),
        # a Claude model on a Codex agent: the rating still applies
        (
            {"complexity": "small", "model": "claude-fable-5-2"},
            "codex",
            {"model": "gpt-5-mini", "effort": "medium", "source": "complexity small"},
        ),
        ({}, "claude", {"model": "", "effort": "", "source": "settings"}),
        ({"model": "gpt-5"}, "claude", {"model": "", "effort": "", "source": "settings"}),
    ],
)
def test_choose_model(task, provider, expected):
    assert choose_model(task, provider) == expected


def test_tasks_store_rating_and_override(admin, worker):
    t = admin.post(
        "/api/tasks", json={"title": "Fix typo", "complexity": "trivial", "model_reason": "one word in the README"}
    ).json()
    assert (t["complexity"], t["model"], t["model_reason"]) == ("trivial", "", "one word in the README")
    assert admin.post("/api/tasks", json={"title": "x", "complexity": "enormous"}).status_code == 400
    assert admin.post("/api/tasks", json={"title": "x", "model": "bad model; rm"}).status_code == 400
    assert admin.post("/api/tasks", json={"title": "x", "effort": "turbo"}).status_code == 422
    # the person overrides the controller's choice
    t = admin.patch(f"/api/tasks/{t['id']}", json={"model": "claude-sonnet-5-5", "effort": "high"}).json()
    assert t["model"] == "claude-sonnet-5-5"
    got = worker("POST", "/api/workers/w1/claim").json()
    assert got["run"] == {"model": "claude-sonnet-5-5", "effort": "high", "source": "task"}
    log = admin.get(f"/api/tasks/{t['id']}/events").json()
    assert any("model claude-sonnet-5-5 (high effort) from the task" in e["message"] for e in log)
    node = admin.get("/api/graph").json()["nodes"][0]
    assert node["complexity"] == "trivial" and node["model"] == "claude-sonnet-5-5"


def test_controller_rates_tasks(admin):
    from tests.test_mcp import rpc, tool

    token = admin.post("/api/controllers", json={"name": "claude"}).json()["token"]
    guide = tool(admin, token, "get_planning_guide", {})["content"][0]["text"]
    assert "| `trivial` |" in guide and "claude-haiku-5-5" in guide
    schema = next(
        t for t in rpc(admin, "tools/list", token=token).json()["result"]["tools"] if t["name"] == "create_tasks"
    )
    assert "complexity" in schema["inputSchema"]["properties"]["tasks"]["items"]["properties"]
    made = tool(
        admin, token, "create_tasks", {"tasks": [{"title": "Big", "complexity": "large", "model_reason": "new module"}]}
    )["structuredContent"]["created"][0]
    tool(admin, token, "update_task", {"id": made["id"], "complexity": "medium"})
    listed = tool(admin, token, "list_tasks", {})["structuredContent"]["tasks"][0]
    assert listed["complexity"] == "medium"
