CREATE TABLE api_tokens (
  token_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL,          -- worker | controller
  name TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_used_at TEXT
);
