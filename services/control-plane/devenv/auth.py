"""Admin login (scrypt password, cookie session) and bearer tokens for workers and controllers."""

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from .db import Database

SESSION_COOKIE = "devenv_session"
SESSION_TTL = 7 * 24 * 3600


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored) and bool(digest)


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bootstrap_admin(db: Database, state_dir: Path) -> None:
    """Create the admin user from the one-time password written at first boot."""
    if db.one("SELECT 1 FROM users"):
        return
    initial = state_dir / "initial-admin-password"
    password = initial.read_text().strip() if initial.exists() else os.environ.get("DEVENV_ADMIN_PASSWORD", "")
    if not password:
        password = secrets.token_urlsafe(12)
        initial.write_text(password + "\n")
    db.run("INSERT INTO users(username, password_hash, must_change) VALUES ('admin', ?, 1)", hash_password(password))


def login(db: Database, username: str, password: str) -> str | None:
    user = db.one("SELECT * FROM users WHERE username = ?", username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    db.run("DELETE FROM sessions WHERE expires_at < ?", time.time())
    db.run("INSERT INTO sessions VALUES (?, ?, ?)", sha(token), username, time.time() + SESSION_TTL)
    return token


def change_password(db: Database, state_dir: Path, username: str, new: str) -> None:
    if len(new) < 10:
        raise HTTPException(400, "Password must be at least 10 characters")
    db.run("UPDATE users SET password_hash = ?, must_change = 0 WHERE username = ?", hash_password(new), username)
    (state_dir / "initial-admin-password").unlink(missing_ok=True)


def token_kind(db: Database, token: str) -> str | None:
    """Return 'worker' or 'controller:<name>' for a bearer token, else None."""
    row = db.one("SELECT kind FROM api_tokens WHERE token_hash = ? AND revoked = 0", sha(token))
    return row["kind"] if row else None


def issue_token(db: Database, kind: str, name: str) -> str:
    token = "dv_" + secrets.token_urlsafe(32)
    db.run("INSERT INTO api_tokens(token_hash, kind, name) VALUES (?, ?, ?)", sha(token), kind, name)
    return token


class Principal:
    def __init__(self, kind: str, name: str):
        self.kind = kind  # admin | worker | controller
        self.name = name


def current_principal(request: Request) -> Principal:
    db: Database = request.app.state.db
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        row = db.one("SELECT kind, name FROM api_tokens WHERE token_hash = ? AND revoked = 0", sha(token))
        if row:
            db.run(
                "UPDATE api_tokens SET last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE token_hash = ?",
                sha(token),
            )
            return Principal(row["kind"], row["name"])
        raise HTTPException(401, "Invalid token")
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        row = db.one("SELECT username FROM sessions WHERE token_hash = ? AND expires_at > ?", sha(cookie), time.time())
        if row:
            return Principal("admin", row["username"])
    raise HTTPException(401, "Not logged in")


def require(*kinds: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.kind not in kinds:
            raise HTTPException(403, f"Requires one of: {', '.join(kinds)}")
        return p

    return dep


admin_only = require("admin")
