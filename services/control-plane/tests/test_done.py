import base64

import httpx
import pytest

from devenv import done, queue
from devenv.github import GitHub


class FakeGitHub:
    def __init__(self):
        self.pr = {
            "merged": False,
            "state": "open",
            "base": {"ref": "main"},
            "head": {"sha": "abc"},
            "merge_commit_sha": "m123456",
            "mergeable": True,
            "draft": False,
        }
        self.checks = []
        self.files = {}
        self.runs = []
        self.merged = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/pulls/1/merge"):
            self.merged = True
            self.pr.update(merged=True, state="closed")
            return httpx.Response(200, json={"sha": "m123456", "merged": True})
        if p.endswith("/pulls/1"):
            return httpx.Response(200, json=self.pr)
        if p.endswith("/check-runs"):
            return httpx.Response(200, json={"check_runs": self.checks})
        if p.endswith("/status"):
            return httpx.Response(200, json={"statuses": []})
        if "/contents/" in p:
            path = p.split("/contents/", 1)[1]
            if path in self.files:
                return httpx.Response(200, json={"content": base64.b64encode(self.files[path].encode()).decode()})
            return httpx.Response(404, json={})
        if "/actions/workflows/" in p:
            return httpx.Response(200, json={"workflow_runs": self.runs})
        return httpx.Response(404, json={})

    def client(self):
        return GitHub(
            "t", client=httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(self.handler))
        )


@pytest.fixture
def review_task(admin, worker, app):
    (t,) = admin.post("/api/tasks/bulk", json={"tasks": [{"title": "A", "repo": "me/proj"}]}).json()
    worker("POST", "/api/workers/w1/claim")
    worker(
        "POST",
        f"/api/workers/w1/tasks/{t['id']}/result",
        json={"outcome": "pr", "pr_url": "u", "pr_number": 1, "branch": "b"},
    )
    return lambda: app.state.db.one("SELECT * FROM tasks WHERE id = ?", t["id"])


def test_waits_for_pending_checks(app, review_task):
    fake = FakeGitHub()
    fake.checks = [{"name": "ci", "status": "in_progress", "conclusion": None}]
    assert done.check_task(app.state.db, fake.client(), review_task(), auto_merge=True) == "in_review"
    assert not fake.merged


def test_auto_merge_then_done_without_deploy(app, review_task):
    fake = FakeGitHub()
    fake.checks = [{"name": "ci", "status": "completed", "conclusion": "success"}]
    gh = fake.client()
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "in_review"
    assert fake.merged
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "done"
    assert review_task()["deploy_status"] == "not needed"


def test_no_auto_merge_leaves_open(app, review_task):
    fake = FakeGitHub()
    fake.checks = [{"name": "ci", "status": "completed", "conclusion": "success"}]
    assert done.check_task(app.state.db, fake.client(), review_task(), auto_merge=False) == "in_review"
    assert not fake.merged


def test_failing_checks_requeue(app, review_task):
    fake = FakeGitHub()
    fake.checks = [{"name": "ci", "status": "completed", "conclusion": "failure"}]
    assert done.check_task(app.state.db, fake.client(), review_task(), auto_merge=True) == "queued"
    t = review_task()
    assert "ci" in t["last_error"] and t["branch"] == "b"  # next attempt continues the same branch


def test_deploy_workflow_verified(app, review_task):
    fake = FakeGitHub()
    fake.pr.update(merged=True, state="closed")
    fake.files[".github/workflows/deploy.yml"] = "on: push"
    gh = fake.client()
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    fake.runs = [{"status": "in_progress", "conclusion": None, "html_url": "r"}]
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    fake.runs = [{"status": "completed", "conclusion": "success", "html_url": "r"}]
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "done"


def test_deploy_failure_needs_human(app, review_task):
    fake = FakeGitHub()
    fake.pr.update(merged=True, state="closed")
    fake.files[".devenv.yaml"] = "deploy:\n  workflow: release.yml\n"
    fake.runs = [{"status": "completed", "conclusion": "failure", "html_url": "r"}]
    gh = fake.client()
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "deploying"
    assert done.check_task(app.state.db, gh, review_task(), auto_merge=True) == "needs_human"


def test_closed_unmerged_fails_attempt(app, review_task):
    fake = FakeGitHub()
    fake.pr.update(state="closed")
    assert done.check_task(app.state.db, fake.client(), review_task(), auto_merge=True) == "queued"


def test_merged_into_wrong_branch(app, review_task):
    fake = FakeGitHub()
    fake.pr.update(merged=True, state="closed", base={"ref": "dev"})
    assert done.check_task(app.state.db, fake.client(), review_task(), auto_merge=True) == "queued"


def test_dependents_unblock_after_done(admin, app):
    a, b = admin.post(
        "/api/tasks/bulk", json={"tasks": [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"]}]}
    ).json()
    queue.set_status(app.state.db, a["id"], "done")
    assert admin.get(f"/api/tasks/{b['id']}").json()["state"] == "ready"
