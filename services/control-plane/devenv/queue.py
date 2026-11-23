"""Work queue: tasks, dependency validation with cycle detection, scheduling with leases."""

import time

from fastapi import HTTPException

from .db import Database

ACTIVE = ("in_progress",)
TERMINAL = ("done", "cancelled")
OPEN = ("queued", "in_progress", "in_review", "deploying", "failed", "needs_human")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def event(db: Database, task_id: int, kind: str, message: str, worker_id: str | None = None) -> None:
    db.run(
        "INSERT INTO task_events(task_id, kind, worker_id, message) VALUES (?, ?, ?, ?)",
        task_id,
        kind,
        worker_id,
        message,
    )


def set_status(db: Database, task_id: int, status: str, message: str = "", actor: str | None = None, **fields) -> None:
    sets = ["status = ?", "updated_at = ?"]
    args: list = [status, now_iso()]
    if status == "done":
        sets.append("done_at = ?")
        args.append(now_iso())
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        args.append(v)
    db.run(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", *args, task_id)
    event(db, task_id, "status", f"{status}{': ' + message if message else ''}", actor)


# ---------- dependencies ----------


def dep_graph(db: Database) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for r in db.all("SELECT task_id, depends_on FROM task_deps"):
        graph.setdefault(r["task_id"], set()).add(r["depends_on"])
    return graph


def find_cycle(graph: dict[int, set[int]]) -> list[int] | None:
    """Return one cycle as a list of task ids, or None. Iterative DFS with colouring."""
    white, grey, black = 0, 1, 2
    colour: dict[int, int] = {}
    parent: dict[int, int] = {}
    nodes = set(graph) | {d for ds in graph.values() for d in ds}
    for start in sorted(nodes):
        if colour.get(start, white) != white:
            continue
        stack = [(start, iter(sorted(graph.get(start, ()))))]
        colour[start] = grey
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = black
                stack.pop()
                continue
            c = colour.get(nxt, white)
            if c == white:
                parent[nxt] = node
                colour[nxt] = grey
                stack.append((nxt, iter(sorted(graph.get(nxt, ())))))
            elif c == grey:
                cycle = [nxt, node]
                while cycle[-1] != nxt:
                    cycle.append(parent[cycle[-1]])
                return list(reversed(cycle))
    return None


# ---------- reading ----------


def deps_of(db: Database, task_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {t: [] for t in task_ids}
    if not task_ids:
        return out
    marks = ",".join("?" * len(task_ids))
    rows = db.all(
        f"SELECT d.task_id, t.id, t.title, t.status FROM task_deps d JOIN tasks t ON t.id = d.depends_on "
        f"WHERE d.task_id IN ({marks}) ORDER BY t.id",
        *task_ids,
    )
    for r in rows:
        out[r["task_id"]].append({"id": r["id"], "title": r["title"], "status": r["status"]})
    return out


def with_state(task: dict, deps: list[dict]) -> dict:
    """Add `deps` and a derived `state`: blocked/ready for queued tasks, else the status."""
    task = dict(task)
    task["deps"] = deps
    if task["status"] == "queued":
        task["state"] = "ready" if all(d["status"] == "done" for d in deps) else "blocked"
    else:
        task["state"] = task["status"]
    return task


def list_tasks(db: Database, status: str | None = None) -> list[dict]:
    rows = db.all(
        "SELECT * FROM tasks" + (" WHERE status = ?" if status else "") + " ORDER BY id", *([status] if status else [])
    )
    deps = deps_of(db, [r["id"] for r in rows])
    counts = {r["task_id"]: r["n"] for r in db.all("SELECT task_id, COUNT(*) n FROM attachments GROUP BY task_id")}
    out = []
    for r in rows:
        t = with_state(r, deps[r["id"]])
        t["attachments"] = counts.get(r["id"], 0)
        out.append(t)
    return out


def get_task(db: Database, task_id: int) -> dict:
    row = db.one("SELECT * FROM tasks WHERE id = ?", task_id)
    if not row:
        raise HTTPException(404, f"No task {task_id}")
    t = with_state(row, deps_of(db, [task_id])[task_id])
    t["dependents"] = db.all(
        "SELECT t.id, t.title, t.status FROM task_deps d JOIN tasks t ON t.id = d.task_id WHERE d.depends_on = ?",
        task_id,
    )
    t["attachments"] = db.all(
        "SELECT id, filename, size, sha256, content_type, created_at FROM attachments WHERE task_id = ?", task_id
    )
    return t


# ---------- writing ----------


def create_tasks(db: Database, items: list[dict], created_by: str, default_max_attempts: int = 3) -> list[int]:
    """Create tasks atomically. Each item may use `key` and refer to other items' keys or existing ids in `depends_on`."""
    keys: dict[str, int] = {}
    with db.tx() as conn:
        ids = []
        for it in items:
            cur = conn.execute(
                "INSERT INTO tasks(title, description, repo, base_branch, priority, provider, max_attempts, plan_key, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    it["title"],
                    it.get("description", ""),
                    it.get("repo", ""),
                    it.get("base_branch") or "main",
                    int(it.get("priority", 0)),
                    it.get("provider", "any"),
                    int(it.get("max_attempts") or default_max_attempts),
                    it.get("key"),
                    created_by,
                ),
            )
            ids.append(cur.lastrowid)
            if it.get("key"):
                if str(it["key"]) in keys:
                    raise HTTPException(400, f"Duplicate key {it['key']}")
                keys[str(it["key"])] = cur.lastrowid
        additions: dict[int, set[int]] = {}
        for tid, it in zip(ids, items, strict=True):
            deps = set()
            for ref in it.get("depends_on", []) or []:
                if str(ref) in keys:
                    deps.add(keys[str(ref)])
                elif isinstance(ref, int) or str(ref).lstrip("#").isdigit():
                    deps.add(int(str(ref).lstrip("#")))
                else:
                    raise HTTPException(400, f"Unknown dependency reference {ref!r} in {it['title']!r}")
            additions[tid] = deps
        # validate inside the transaction (sees the new rows)
        _validate_in_tx(conn, additions)
        for tid, deps in additions.items():
            for d in deps:
                conn.execute("INSERT INTO task_deps(task_id, depends_on) VALUES (?, ?)", (tid, d))
            conn.execute(
                "INSERT INTO task_events(task_id, kind, message) VALUES (?, 'status', ?)",
                (tid, f"queued by {created_by}"),
            )
    return ids


def _validate_in_tx(conn, additions: dict[int, set[int]]) -> None:
    graph: dict[int, set[int]] = {}
    for a, b in conn.execute("SELECT task_id, depends_on FROM task_deps"):
        graph.setdefault(a, set()).add(b)
    known = {r[0] for r in conn.execute("SELECT id FROM tasks")}
    for tid, deps in additions.items():
        for d in deps:
            if d not in known:
                raise HTTPException(400, f"Task {tid} depends on unknown task {d}")
            if d == tid:
                raise HTTPException(400, f"Task {tid} cannot depend on itself")
        graph.setdefault(tid, set()).update(deps)
    cycle = find_cycle(graph)
    if cycle:
        raise HTTPException(400, "Dependency cycle: " + " -> ".join(f"#{n}" for n in cycle))


def set_deps(db: Database, task_id: int, deps: list[int]) -> None:
    get_task(db, task_id)
    with db.tx() as conn:
        conn.execute("DELETE FROM task_deps WHERE task_id = ?", (task_id,))
        _validate_in_tx(conn, {task_id: set(deps)})
        for d in set(deps):
            conn.execute("INSERT INTO task_deps(task_id, depends_on) VALUES (?, ?)", (task_id, d))


# ---------- scheduling ----------


def claim(db: Database, worker_id: str, provider: str, lease_seconds: int) -> dict | None:
    """Lease the highest-priority ready task this provider may run. Atomic."""
    with db.tx() as conn:
        rows = conn.execute(
            """
            SELECT t.* FROM tasks t
            WHERE t.status = 'queued' AND t.provider IN ('any', ?)
              AND NOT EXISTS (
                SELECT 1 FROM task_deps d JOIN tasks dt ON dt.id = d.depends_on
                WHERE d.task_id = t.id AND dt.status != 'done')
            ORDER BY t.priority DESC, t.id ASC LIMIT 1
            """,
            (provider,),
        ).fetchall()
        if not rows:
            return None
        task = dict(rows[0])
        conn.execute(
            "UPDATE tasks SET status = 'in_progress', worker_id = ?, lease_expires = ?, attempts = attempts + 1, "
            "updated_at = ? WHERE id = ?",
            (worker_id, time.time() + lease_seconds, now_iso(), task["id"]),
        )
        conn.execute(
            "INSERT INTO task_events(task_id, kind, worker_id, message) VALUES (?, 'status', ?, ?)",
            (task["id"], worker_id, f"in_progress: claimed by {worker_id} (attempt {task['attempts'] + 1})"),
        )
        conn.execute("UPDATE workers SET state = 'busy', current_task_id = ? WHERE id = ?", (task["id"], worker_id))
    return get_task(db, task["id"])


def extend_lease(db: Database, task_id: int, worker_id: str, lease_seconds: int) -> bool:
    cur = db.run(
        "UPDATE tasks SET lease_expires = ? WHERE id = ? AND worker_id = ? AND status = 'in_progress'",
        time.time() + lease_seconds,
        task_id,
        worker_id,
    )
    return cur.rowcount == 1


def fail_attempt(db: Database, task: dict, reason: str, actor: str | None = None) -> str:
    """Requeue a failed attempt, or mark the task needs_human once attempts are used up."""
    if task["attempts"] >= task["max_attempts"]:
        set_status(db, task["id"], "needs_human", reason, actor, worker_id=None, lease_expires=None, last_error=reason)
        return "needs_human"
    set_status(
        db,
        task["id"],
        "queued",
        f"retrying after: {reason}",
        actor,
        worker_id=None,
        lease_expires=None,
        last_error=reason,
    )
    return "queued"


def expire_leases(db: Database) -> list[int]:
    expired = db.all("SELECT * FROM tasks WHERE status = 'in_progress' AND lease_expires < ?", time.time())
    for t in expired:
        fail_attempt(db, t, "lease expired (worker stopped responding)")
        db.run(
            "UPDATE workers SET state = 'idle', current_task_id = NULL WHERE id = ? AND current_task_id = ?",
            t["worker_id"],
            t["id"],
        )
    return [t["id"] for t in expired]
