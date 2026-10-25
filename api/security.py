"""Authentication primitives: password hashing, sessions and API tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from api import config, db


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: str) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=config.SESSION_HOURS)).isoformat()
    conn.execute(
        "INSERT INTO sessions(id, user_id, csrf, expires_at, created_at) VALUES(?,?,?,?,?)",
        (token, user_id, csrf, expires, db.now()),
    )
    conn.commit()
    return token, csrf, expires


def session_user(conn: sqlite3.Connection, token: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT s.id AS session_id, s.csrf, s.expires_at, u.id, u.email, u.name, u.role "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "session_id": row["session_id"],
        "csrf": row["csrf"],
    }


def token_user(conn: sqlite3.Connection, token: str) -> Optional[dict]:
    if config.STATIC_TOKEN and hmac.compare_digest(token, config.STATIC_TOKEN):
        return {"id": "system", "email": "system@cabina.local", "name": "System", "role": "admin"}
    row = conn.execute(
        "SELECT t.id AS token_id, t.last_used, u.id, u.email, u.name, u.role "
        "FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE api_tokens SET last_used = ? WHERE id = ?", (db.now(), row["token_id"]))
    conn.commit()
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


def ensure_admin(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    if row and row["n"]:
        return
    password = config.ADMIN_PASSWORD or secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO users(id, email, name, role, password_hash, created_at) VALUES(?,?,?,?,?,?)",
        (db.new_id("usr"), config.ADMIN_EMAIL, "Administrator", "admin", hash_password(password), db.now()),
    )
    conn.commit()
    if not config.ADMIN_PASSWORD:
        print(f"[cabina] generated admin password for {config.ADMIN_EMAIL}: {password}", flush=True)


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "…" + value[-2:]
    return value[:4] + "…" + value[-4:]
