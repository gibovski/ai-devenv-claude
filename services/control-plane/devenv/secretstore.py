"""Encrypted secrets store. Values are Fernet-encrypted at rest and never returned by the API."""

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet

from .db import Database


def load_key(state_dir: Path) -> bytes:
    path = state_dir / "secret.key"
    if path.exists():
        return path.read_text().strip().encode()
    key = base64.urlsafe_b64encode(os.urandom(32))
    path.write_text(key.decode() + "\n")
    path.chmod(0o600)
    return key


class SecretStore:
    def __init__(self, db: Database, key: bytes):
        self.db = db
        self.fernet = Fernet(key)

    def set(self, name: str, value: str | None) -> None:
        if value is None or value == "":
            self.db.run("DELETE FROM secrets WHERE name = ?", name)
            return
        token = self.fernet.encrypt(value.encode())
        self.db.run(
            "INSERT INTO secrets(name, ciphertext) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            name,
            token,
        )

    def get(self, name: str) -> str | None:
        row = self.db.one("SELECT ciphertext FROM secrets WHERE name = ?", name)
        return self.fernet.decrypt(row["ciphertext"]).decode() if row else None

    def status(self) -> dict[str, dict]:
        """Names and update times only, safe to send to the browser."""
        return {
            r["name"]: {"set": True, "updated_at": r["updated_at"]}
            for r in self.db.all("SELECT name, updated_at FROM secrets")
        }
