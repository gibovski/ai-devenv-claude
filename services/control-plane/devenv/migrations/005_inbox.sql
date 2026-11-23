-- Issues in the GitHub control repository that became tasks, and what was last reported back.
CREATE TABLE inbox_issues (
  repo TEXT NOT NULL,
  issue INTEGER NOT NULL,
  task_id INTEGER,                      -- NULL when the issue could not be queued (see error)
  reported TEXT NOT NULL DEFAULT '',    -- task status last posted as a comment
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (repo, issue)
);
