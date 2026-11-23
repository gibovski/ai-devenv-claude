"""Shared application state: settings persistence on top of the kv table."""

import json

from .db import Database
from .settings_schema import Settings


def load_settings(db: Database) -> Settings:
    row = db.one("SELECT value FROM kv WHERE key = 'settings'")
    return Settings.model_validate_json(row["value"]) if row else Settings()


def save_settings(db: Database, settings: Settings) -> None:
    db.run(
        "INSERT INTO kv(key, value) VALUES ('settings', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        settings.model_dump_json(),
    )


def kv_get(db: Database, key: str, default=None):
    row = db.one("SELECT value FROM kv WHERE key = ?", key)
    return json.loads(row["value"]) if row else default


def kv_set(db: Database, key: str, value) -> None:
    db.run(
        "INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        key,
        json.dumps(value),
    )
