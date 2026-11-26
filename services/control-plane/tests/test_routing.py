import time

import pytest
from test_done import FakeGitHub
from test_mcp import tool

from devenv import done
from devenv.routing import detect_images


@pytest.fixture
def controller(admin):
    r = admin.post("/api/controllers", json={"name": "claude"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


@pytest.mark.parametrize(
    "text",
    [
        "Generate a logo for Baz Industries",
        "Create favicons for the player app",
        "Design an icon set for the toolbar",
        "Draw map art for Stormwreck Isle",
        "Hero image to be generated for the landing page",
    ],
)
def test_detects_image_generation(text):
    assert detect_images(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fix the image upload bug",
        "Resize uploaded pictures on the server",
        "Add alt text to every image",
        "Create a REST endpoint for avatars metadata. It stores URLs.",
        "Generate the API client",
        "Update the icons to make them bigger",
        "Make sure the logo links home",
    ],
)
def test_ignores_other_image_work(text):
    assert not detect_images(text)


def test_image_task_goes_to_codex_with_warning(client, controller, worker):
    res = tool(
        client,
        controller,
        "create_tasks",
        {
            "tasks": [
                {"key": "art", "title": "Make the title card", "needs_images": True, "complexity": "small"},
                {"key": "logo", "title": "Generate a logo", "provider": "claude", "complexity": "small"},
                {"key": "code", "title": "Add a /health endpoint", "complexity": "trivial"},
            ]
        },
    )["structuredContent"]
    art, logo, code = res["created"]
    assert (art["provider"], logo["provider"], code["provider"]) == ("codex", "codex", "any")
    assert art["needs_images"] and logo["needs_images"] and not code["needs_images"]
    (warning,) = res["warnings"]
    assert "No OpenAI Codex agent" in warning and f"#{art['id']}" in warning and "start_agents" in warning
    # The Claude worker never picks up the image tasks.
    claimed = worker("POST", "/api/workers/w1/claim").json()
    assert claimed["id"] == code["id"]
    again = worker("POST", "/api/workers/w1/claim")
    assert again.status_code == 204 or again.json() is None
    log = client.get(f"/api/tasks/{logo['id']}/events").json()
    assert any("routed to an OpenAI Codex agent" in e["message"] for e in log)


def test_no_warning_when_codex_online(client, controller, worker):
    worker("POST", "/api/workers/register", json={"id": "c1", "provider": "codex", "model": "gpt-5-codex"})
    res = tool(client, controller, "create_tasks", {"tasks": [{"title": "Generate icons", "complexity": "small"}]})[
        "structuredContent"
    ]
    assert res["warnings"] == []
    task = worker("POST", "/api/workers/c1/claim").json()
    assert task["needs_images"] == 1 and task["provider"] == "codex"


def test_explicit_false_wins_on_update(admin):
    (t,) = admin.post("/api/tasks/bulk", json={"tasks": [{"title": "Generate a logo"}]}).json()
    assert t["provider"] == "codex"
    t = admin.patch(f"/api/tasks/{t['id']}", json={"needs_images": False, "provider": "claude"}).json()
    assert (t["provider"], t["needs_images"]) == ("claude", 0)
    t = admin.patch(f"/api/tasks/{t['id']}", json={"needs_images": True}).json()
    assert (t["provider"], t["needs_images"]) == ("codex", 1)


def test_start_agents_needs_credentials_then_starts(client, controller, admin, app):
    r = tool(client, controller, "start_agents", {"provider": "codex"})
    assert r.get("isError") and "sign-in" in r["content"][0]["text"]
    admin.put("/api/secrets", json={"values": {"openai_api_key": "sk-test"}})
    out = tool(client, controller, "start_agents", {"provider": "codex"})["structuredContent"]
    assert out["started"] and out["count"] == 1
    assert admin.get("/api/settings").json()["settings"]["agents"]["codex"]["count"] == 1
    again = tool(client, controller, "start_agents", {"provider": "codex"})["structuredContent"]
    assert not again["started"]


@pytest.fixture
def review_task(admin, worker, app):
    (t,) = admin.post("/api/tasks/bulk", json={"tasks": [{"title": "A", "repo": "me/proj"}]}).json()
    worker("POST", "/api/workers/w1/claim")
    worker(
        "POST",
        f"/api/workers/w1/tasks/{t['id']}/result",
        json={"outcome": "pr", "pr_url": "u", "pr_number": 1, "branch": "b"},
    )

    def get(age: float = 0):
        if age:
            old = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - age)) + "Z"
            app.state.db.run("UPDATE tasks SET updated_at = ? WHERE id = ?", old, t["id"])
        return app.state.db.one("SELECT * FROM tasks WHERE id = ?", t["id"])

    return get


def test_no_checks_is_not_tested(app, review_task):
    fake = FakeGitHub()
    assert done.check_task(app.state.db, fake.client(), review_task(age=600), auto_merge=True) == "queued"
    assert not fake.merged and "no CI checks ran" in review_task()["last_error"]


def test_no_checks_allowed_by_repo_config(app, review_task):
    fake = FakeGitHub()
    fake.files[".devenv.yaml"] = "checks:\n  required: false\n"
    assert done.check_task(app.state.db, fake.client(), review_task(age=600), auto_merge=True) == "in_review"
    assert fake.merged


class WorkflowsGitHub(FakeGitHub):
    def __init__(self, names):
        super().__init__()
        self.names = names

    def handler(self, request):
        import httpx

        if request.url.path.endswith("/contents/.github/workflows"):
            return httpx.Response(200, json=[{"name": n, "type": "file"} for n in self.names])
        return super().handler(request)


def test_pages_workflow_counts_as_deploy(app, review_task):
    fake = WorkflowsGitHub(["ci.yml", "cloudflare-pages.yml"])
    fake.pr.update(merged=True, state="closed")
    gh = fake.client()
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    assert review_task()["deploy_status"] == "auto:cloudflare-pages.yml@m123456"
    fake.runs = [{"status": "completed", "conclusion": "success", "html_url": "r"}]
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "done"


def test_auto_deploy_that_never_runs_is_not_needed(app, review_task):
    fake = WorkflowsGitHub(["pages-fleet.yml"])
    fake.pr.update(merged=True, state="closed")
    gh = fake.client()
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    assert done.check_task(app.state.db, gh, review_task(age=900), auto_merge=True) == "done"
    assert review_task()["deploy_status"] == "not needed"
