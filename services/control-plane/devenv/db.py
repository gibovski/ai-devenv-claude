"""SQLite access with numbered SQL migrations in devenv/migrations."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

_lock = threading.RLock()


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def migrate(self) -> int:
        with _lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            files = sorted(
                (f for f in resources.files("devenv.migrations").iterdir() if f.name.endswith(".sql")),
                key=lambda f: int(f.name.split("_", 1)[0]),
            )
            for f in files:
                version = int(f.name.split("_", 1)[0])
                if version <= current:
                    continue
                self.conn.executescript(
                    "BEGIN;" + f.read_text() + f";INSERT INTO schema_version VALUES ({version});COMMIT;"
                )
                current = version
            return current

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def all(self, sql: str, *args) -> list[dict]:
        with _lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, *args) -> dict | None:
        with _lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def run(self, sql: str, *args) -> sqlite3.Cursor:
        with _lock:
            return self.conn.execute(sql, args)
