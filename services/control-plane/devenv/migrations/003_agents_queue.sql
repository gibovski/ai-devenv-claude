CREATE TABLE workers (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,              -- claude | codex | openhands
  model TEXT NOT NULL DEFAULT '',
  hostname TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'idle',  -- idle | busy | error (offline is derived from last_heartbeat)
  current_task_id INTEGER,
  message TEXT NOT NULL DEFAULT '',
  registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_heartbeat REAL NOT NULL,
  tasks_done INTEGER NOT NULL DEFAULT 0,
  tasks_failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  repo TEXT NOT NULL DEFAULT '',          -- owner/name; empty for tasks with no code change
  base_branch TEXT NOT NULL DEFAULT 'main',
  priority INTEGER NOT NULL DEFAULT 0,    -- higher runs first
  provider TEXT NOT NULL DEFAULT 'any',   -- any | claude | codex
  status TEXT NOT NULL DEFAULT 'queued',  -- queued | in_progress | in_review | deploying | done | failed | needs_human | cancelled
  worker_id TEXT,
  lease_expires REAL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  branch TEXT NOT NULL DEFAULT '',
  pr_url TEXT NOT NULL DEFAULT '',
  pr_number INTEGER,
  deploy_status TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '',
  plan_key TEXT,                          -- the key a controller used in a bulk plan
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  done_at TEXT
);
CREATE INDEX tasks_status ON tasks(status);

CREATE TABLE task_deps (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depends_on),
  CHECK (task_id != depends_on)
);

CREATE TABLE attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  kind TEXT NOT NULL,        -- status | log | error
  worker_id TEXT,
  message TEXT NOT NULL
);
CREATE INDEX task_events_task ON task_events(task_id, id);
