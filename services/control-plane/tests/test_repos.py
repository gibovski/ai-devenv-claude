import base64
import json

import httpx
import pytest

from devenv import repos
from devenv.github import GitHub
from devenv.settings_schema import GitHubSettings


def gh(**kw) -> GitHubSettings:
    return GitHubSettings(owner="me", **kw)


def test_normalize_forms():
    s = gh()
    assert repos.normalize("", s) == ""
    assert repos.normalize("app", s) == "me/app"
    assert repos.normalize("other/app", s) == "other/app"
    assert repos.normalize("https://github.com/me/app.git", s) == "me/app"
    assert repos.normalize("new:status-page", s) == "new:me/status-page"
    assert repos.normalize("new:me/status-page", s) == "new:me/status-page"
    for bad in ("a/b/c", "new:", "bad name", "me/..", "x/y z"):
        with pytest.raises(repos.RepoError):
            repos.normalize(bad, s)


def test_suffix_and_creation_switch():
    s = gh(new_repo_suffix="-claude")
    assert repos.normalize("new:tool", s) == "new:me/tool-claude"
    assert repos.normalize("new:tool-claude", s) == "new:me/tool-claude"  # not doubled
    assert repos.normalize("tool", s) == "me/tool"  # existing repos keep their names
    with pytest.raises(repos.RepoError, match="turned off"):
        repos.normalize("new:tool", gh(allow_create_repos=False))
    with pytest.raises(repos.RepoError, match="only be created under me"):
        repos.normalize("new:someone/tool", s)


def test_allowed_and_blocked_lists():
    s = gh(allowed_repos=["infra-*", "friend/shared"], blocked_repos=["infra-secret", "*-openai"])
    assert repos.allowed("me/infra-dns", s)[0]
    assert repos.allowed("friend/shared", s)[0]
    assert not repos.allowed("me/infra-secret", s)[0]  # blocked wins
    assert not repos.allowed("me/app", s)[0]  # not on the allowed list
    assert not repos.allowed("friend/infra-x", s)[0]  # bare patterns only cover the owner's repos
    open_ = gh(blocked_repos=["ai-devenv"])
    assert repos.allowed("me/anything", open_)[0]
    assert not repos.allowed("ME/AI-DEVENV", open_)[0]
    with pytest.raises(repos.RepoError, match="blocked"):
        repos.normalize("ai-devenv", open_)


def save_github(admin, **github):
    s = admin.get("/api/settings").json()["settings"]
    s["github"].update(github)
    assert admin.put("/api/settings", json=s).status_code == 200


def test_tasks_use_policy_and_plan_names(admin):
    save_github(admin, owner="me", new_repo_suffix="-claude", blocked_repos=["private-*"])
    r = admin.post(
        "/api/tasks/bulk",
        json={
            "tasks": [
                {"key": "new", "title": "Scaffold", "repo": "new:status"},
                {"key": "next", "title": "Feature", "repo": "status", "depends_on": ["new"]},
                {"key": "tofu", "title": "DNS module", "repo": "tofu-modules"},
                {"key": "none", "title": "Research"},
            ]
        },
    )
    assert r.status_code == 201, r.text
    assert [t["repo"] for t in r.json()] == ["new:me/status-claude", "me/status-claude", "me/tofu-modules", ""]
    r = admin.post("/api/tasks", json={"title": "x", "repo": "private-keys"})
    assert r.status_code == 400 and "blocked" in r.json()["detail"]
    tid = r = admin.post("/api/tasks", json={"title": "x", "repo": "app"}).json()["id"]
    assert admin.patch(f"/api/tasks/{tid}", json={"repo": "private-x"}).status_code == 400
    assert admin.patch(f"/api/tasks/{tid}", json={"repo": "other"}).json()["repo"] == "me/other"


def test_default_repo_is_a_fallback(admin):
    save_github(admin, owner="me", default_repo="scratch")
    assert admin.post("/api/tasks", json={"title": "x"}).json()["repo"] == "me/scratch"
    assert admin.post("/api/tasks", json={"title": "y", "repo": "app"}).json()["repo"] == "me/app"


class FakeGitHub:
    def __init__(self, existing=()):
        self.repos = {
            r: {"full_name": r, "default_branch": "main", "html_url": f"https://github.com/{r}"} for r in existing
        }
        self.created: list[dict] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "me"})
        if req.method == "POST" and path == "/user/repos":
            body = json.loads(req.content)
            self.created.append(body)
            full = f"me/{body['name']}"
            self.repos[full] = {"full_name": full, "default_branch": "main", "html_url": f"https://github.com/{full}"}
            return httpx.Response(201, json=self.repos[full])
        if path.startswith("/repos/"):
            full = path.removeprefix("/repos/")
            if full.endswith("/readme"):
                return httpx.Response(200, json={"content": base64.b64encode(b"# Modules\nOpenTofu").decode()})
            return httpx.Response(200, json=self.repos[full]) if full in self.repos else httpx.Response(404, json={})
        if path == "/user/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "me/tofu-modules",
                        "description": "OpenTofu modules for Cloudflare",
                        "pushed_at": "2026-11-01",
                        "topics": ["cloudflare"],
                    },
                    {"full_name": "me/ai-devenv", "description": "the other one", "pushed_at": "2026-11-20"},
                    {"full_name": "me/old", "description": "", "archived": True, "pushed_at": "2020-01-01"},
                ],
            )
        return httpx.Response(404, json={})


@pytest.fixture
def fake_github(monkeypatch, app):
    fake = FakeGitHub()
    monkeypatch.setattr(
        repos,
        "_gh",
        lambda token, api, client=None: GitHub(
            token, api, httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(fake.handler))
        ),
    )
    app.state.secrets.set("github_token", "ghp_test")
    repos.forget_cache()
    return fake


def test_claim_creates_new_repo(admin, worker, fake_github):
    save_github(admin, owner="me", new_repo_suffix="-claude")
    t = admin.post("/api/tasks", json={"title": "Scaffold status page", "repo": "new:status"}).json()
    got = worker("POST", "/api/workers/w1/claim").json()
    assert got["id"] == t["id"] and got["repo"] == "me/status-claude" and got["new_repo"] is True
    assert fake_github.created == [
        {"name": "status-claude", "description": "Scaffold status page", "private": True, "auto_init": True}
    ]
    assert admin.get(f"/api/tasks/{t['id']}").json()["repo"] == "me/status-claude"


def test_claim_rechecks_policy(admin, worker, fake_github):
    save_github(admin, owner="me")
    t = admin.post("/api/tasks", json={"title": "New", "repo": "new:tool"}).json()
    save_github(admin, owner="me", allow_create_repos=False)
    assert worker("POST", "/api/workers/w1/claim").status_code == 204
    task = admin.get(f"/api/tasks/{t['id']}").json()
    assert task["status"] == "needs_human" and "turned off" in task["last_error"]
    assert fake_github.created == []


def test_repo_list_and_readme(admin, fake_github):
    save_github(admin, owner="me", blocked_repos=["ai-devenv"])
    body = admin.get("/api/repos").json()
    assert [r["repo"] for r in body["repos"]] == ["me/tofu-modules"]  # blocked and archived ones hidden
    assert body["policy"]["can_create"] is True
    assert admin.get("/api/repos?q=cloudflare").json()["repos"][0]["repo"] == "me/tofu-modules"
    assert admin.get("/api/repos?q=nothing").json()["repos"] == []
    assert "OpenTofu" in admin.get("/api/repos/me/tofu-modules/readme").json()["readme"]
    assert admin.get("/api/repos/me/ai-devenv/readme").status_code == 403


def test_controller_tools(admin, fake_github):
    from tests.test_mcp import tool

    save_github(admin, owner="me", blocked_repos=["ai-devenv"])
    token = admin.post("/api/controllers", json={"name": "claude"}).json()["token"]
    listed = tool(admin, token, "list_repos", {"query": "tofu"})["structuredContent"]
    assert [r["repo"] for r in listed["repos"]] == ["me/tofu-modules"] and listed["policy"]["owner"] == "me"
    assert "OpenTofu" in tool(admin, token, "get_repo_readme", {"repo": "tofu-modules"})["structuredContent"]["readme"]
    assert tool(admin, token, "get_repo_readme", {"repo": "ai-devenv"})["isError"]
    made = tool(admin, token, "create_tasks", {"tasks": [{"title": "x", "repo": "ai-devenv"}]})
    assert made["isError"] and "blocked" in made["content"][0]["text"]
