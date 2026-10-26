"""User management and API tokens (F6)."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from api import db, security
from api.errors import ApiError

ROLES = {"admin", "producer", "viewer"}


def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "email": data["email"],
        "name": data.get("name"),
        "role": data["role"],
        "created_at": data.get("created_at"),
    }


def list_users(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    return {"data": [_public(row) for row in rows]}


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    name: str | None,
    role: str,
    password: str,
    actor: str | None,
) -> dict[str, Any]:
    email = email.strip().lower()
    if "@" not in email:
        raise ApiError(422, "validation_failed", "A valid email is required")
    if role not in ROLES:
        raise ApiError(422, "validation_failed", f"Role must be one of {sorted(ROLES)}")
    if len(password) < 8:
        raise ApiError(422, "validation_failed", "Password must have at least 8 characters")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise ApiError(409, "conflict", "A user with this email already exists")
    user_id = db.new_id("usr")
    conn.execute(
        "INSERT INTO users(id, email, name, role, password_hash, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, email, name, role, security.hash_password(password), db.now()),
    )
    conn.commit()
    db.audit(conn, actor, "user.created", user_id, {"email": email, "role": role})
    return _public(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def update_user(conn: sqlite3.Connection, user_id: str, payload: dict[str, Any], actor: str | None) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "User not found")
    if "role" in payload:
        role = payload["role"]
        if role not in ROLES:
            raise ApiError(422, "validation_failed", f"Role must be one of {sorted(ROLES)}")
        if row["role"] == "admin" and role != "admin" and _admin_count(conn) <= 1:
            raise ApiError(409, "conflict", "Cannot demote the last admin")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if "name" in payload:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (payload["name"], user_id))
    if payload.get("password"):
        password = str(payload["password"])
        if len(password) < 8:
            raise ApiError(422, "validation_failed", "Password must have at least 8 characters")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(password), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    db.audit(conn, actor, "user.updated", user_id, {k: v for k, v in payload.items() if k != "password"})
    return _public(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def delete_user(conn: sqlite3.Connection, user_id: str, actor: str | None) -> None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "User not found")
    if actor and actor == user_id:
        raise ApiError(409, "conflict", "You cannot delete your own user")
    if row["role"] == "admin" and _admin_count(conn) <= 1:
        raise ApiError(409, "conflict", "Cannot delete the last admin")
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    db.audit(conn, actor, "user.deleted", user_id, {"email": row["email"]})


def _admin_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'").fetchone()["n"])


def change_password(conn: sqlite3.Connection, user_id: str, current: str, new: str) -> None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "User not found")
    if not security.verify_password(current, row["password_hash"]):
        raise ApiError(401, "unauthorized", "Current password is incorrect")
    if len(new) < 8:
        raise ApiError(422, "validation_failed", "Password must have at least 8 characters")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(new), user_id))
    conn.commit()
    db.audit(conn, user_id, "user.password_changed", user_id)


def list_tokens(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT t.id, t.user_id, t.scopes, t.last_used, t.created_at, u.email "
        "FROM api_tokens t JOIN users u ON u.id = t.user_id ORDER BY t.created_at DESC"
    ).fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "email": row["email"],
                "name": row["scopes"] or "token",
                "last_used": row["last_used"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }


def create_token(conn: sqlite3.Connection, user_id: str, name: str, actor: str | None) -> dict[str, Any]:
    raw = "om_" + secrets.token_urlsafe(32)
    token_id = db.new_id("tok")
    conn.execute(
        "INSERT INTO api_tokens(id, user_id, token_hash, scopes, created_at) VALUES(?,?,?,?,?)",
        (token_id, user_id, security.hash_token(raw), name or "token", db.now()),
    )
    conn.commit()
    db.audit(conn, actor, "token.created", token_id, {"user_id": user_id, "name": name})
    return {"id": token_id, "token": raw, "name": name or "token"}


def delete_token(conn: sqlite3.Connection, token_id: str, actor: str | None) -> None:
    row = conn.execute("SELECT id FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Token not found")
    conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    conn.commit()
    db.audit(conn, actor, "token.deleted", token_id)


def audit_log(conn: sqlite3.Connection, limit: int = 100) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)
    ).fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "action": row["action"],
                "target": row["target"],
                "meta": row["meta_json"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }
