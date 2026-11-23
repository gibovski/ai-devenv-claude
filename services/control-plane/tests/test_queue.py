import time

import pytest

from devenv import queue


def plan(admin, tasks, **kw):
    return admin.post("/api/tasks/bulk", json={"tasks": tasks, **kw})


def test_find_cycle():
    assert queue.find_cycle({1: {2}, 2: {3}}) is None
    cyc = queue.find_cycle({1: {2}, 2: {3}, 3: {1}})
    assert cyc and cyc[0] == cyc[-1] and set(cyc) == {1, 2, 3}


def test_bulk_with_keys_and_states(admin):
    r = plan(admin, [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"]}])
    assert r.status_code == 201, r.text
    a, b = r.json()
    assert a["state"] == "ready" and b["state"] == "blocked"
    assert b["deps"][0]["id"] == a["id"]


def test_cycle_rejected(admin):
    a, b = plan(admin, [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"]}]).json()
    r = admin.put(f"/api/tasks/{a['id']}/deps", json={"depends_on": [b["id"]]})
    assert r.status_code == 400 and "cycle" in r.text
    r = plan(admin, [{"key": "x", "title": "X", "depends_on": ["y"]}, {"key": "y", "title": "Y", "depends_on": ["x"]}])
    assert r.status_code == 400
    assert len(admin.get("/api/tasks").json()) == 2  # nothing from the failed plan was kept


def test_unknown_dep_rejected(admin):
    assert plan(admin, [{"title": "A", "depends_on": [999]}]).status_code == 400
    assert plan(admin, [{"title": "A", "depends_on": ["nokey"]}]).status_code == 400


def test_claim_waits_for_dependencies(admin, worker, app):
    a, b = plan(
        admin, [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"], "priority": 9}]
    ).json()
    t = worker("POST", "/api/workers/w1/claim").json()
    assert t["id"] == a["id"]  # B has higher priority but is blocked
    assert worker("POST", "/api/workers/w1/claim").status_code == 204
    r = worker("POST", f"/api/workers/w1/tasks/{a['id']}/result", json={"outcome": "completed"})
    assert r.json()["status"] == "done"
    assert worker("POST", "/api/workers/w1/claim").json()["id"] == b["id"]


def test_repo_tasks_need_pr(admin, worker):
    (a,) = plan(admin, [{"title": "A", "repo": "me/proj"}]).json()
    worker("POST", "/api/workers/w1/claim")
    r = worker("POST", f"/api/workers/w1/tasks/{a['id']}/result", json={"outcome": "completed"})
    assert r.status_code == 400
    r = worker(
        "POST",
        f"/api/workers/w1/tasks/{a['id']}/result",
        json={"outcome": "pr", "pr_url": "https://x/pr/1", "pr_number": 1, "branch": "t/1"},
    )
    assert r.json()["status"] == "in_review"


def test_provider_filter(admin, worker):
    plan(admin, [{"title": "codex only", "provider": "codex"}])
    assert worker("POST", "/api/workers/w1/claim").status_code == 204


def test_failure_retries_then_needs_human(admin, worker):
    (a,) = plan(admin, [{"title": "A", "max_attempts": 2}]).json()
    for expected in ("queued", "needs_human"):
        worker("POST", "/api/workers/w1/claim")
        r = worker("POST", f"/api/workers/w1/tasks/{a['id']}/result", json={"outcome": "failed", "error": "boom"})
        assert r.json()["status"] == expected


def test_lease_expiry_requeues(admin, worker, app):
    (a,) = plan(admin, [{"title": "A"}]).json()
    worker("POST", "/api/workers/w1/claim")
    app.state.db.run("UPDATE tasks SET lease_expires = ? WHERE id = ?", time.time() - 1, a["id"])
    assert queue.expire_leases(app.state.db) == [a["id"]]
    assert admin.get(f"/api/tasks/{a['id']}").json()["status"] == "queued"


def test_heartbeat_extends_lease_and_agent_status(admin, worker, app):
    (a,) = plan(admin, [{"title": "A"}]).json()
    worker("POST", "/api/workers/w1/claim")
    r = worker("POST", "/api/workers/w1/heartbeat", json={"state": "busy", "task_id": a["id"], "message": "editing"})
    assert r.json()["continue"] is True
    st = admin.get("/api/agents").json()
    (ag,) = st["agents"]
    assert ag["status"] == "busy" and ag["current_task"]["id"] == a["id"]
    app.state.db.run("UPDATE workers SET last_heartbeat = ?", time.time() - 1000)
    assert admin.get("/api/agents").json()["agents"][0]["status"] == "offline"


def test_worker_cannot_use_admin_api(worker):
    assert worker("GET", "/api/settings").status_code == 403
    assert worker("POST", "/api/tasks", json={"title": "x"}).status_code == 403


def test_attachments_flow(admin, worker, cfg):
    (a,) = plan(admin, [{"title": "A"}]).json()
    r = admin.post(
        f"/api/tasks/{a['id']}/attachments", files=[("files", ("../../evil name.txt", b"hello", "text/plain"))]
    )
    assert r.status_code == 201
    att = r.json()[0]
    assert att["filename"] == "evil name.txt" and att["size"] == 5
    t = worker("POST", "/api/workers/w1/claim").json()
    (u,) = t["attachment_urls"]
    assert worker("GET", u["url"]).content == b"hello"


def test_import_tsv(admin):
    tsv = "M0\tFoundation\n0.1\tFirst\t\n0.2\tSecond\t0.1\n"
    r = admin.post("/api/tasks/import", files={"file": ("plan.tsv", tsv.encode(), "text/tab-separated-values")})
    assert r.status_code == 201, r.text
    assert [t["state"] for t in r.json()] == ["ready", "blocked"]


def test_graph(admin):
    plan(admin, [{"key": "a", "title": "A"}, {"key": "b", "title": "B", "depends_on": ["a"]}])
    g = admin.get("/api/graph").json()
    assert len(g["nodes"]) == 2 and len(g["edges"]) == 1


@pytest.mark.parametrize("action,status", [("cancel", "cancelled"), ("mark_done", "done")])
def test_patch_actions(admin, action, status):
    (a,) = plan(admin, [{"title": "A"}]).json()
    assert admin.patch(f"/api/tasks/{a['id']}", json={"action": action}).json()["status"] == status
