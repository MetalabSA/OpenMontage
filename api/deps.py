"""Request dependencies: DB connection and authentication."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request

from api import db, security
from api.errors import ApiError

COOKIE_NAME = "oms_session"


@dataclass
class AuthContext:
    user: dict
    via: str  # "bearer" | "cookie"
    csrf: Optional[str] = None


def get_db():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _bearer(request: Request) -> Optional[str]:
    raw = request.headers.get("authorization", "")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return None


def current_auth(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> AuthContext:
    token = _bearer(request)
    if token:
        user = security.token_user(conn, token)
        if not user:
            raise ApiError(401, "invalid_token", "Invalid API token")
        return AuthContext(user=user, via="bearer")
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        user = security.session_user(conn, cookie)
        if not user:
            raise ApiError(401, "session_expired", "Session expired")
        return AuthContext(user=user, via="cookie", csrf=user.get("csrf"))
    raise ApiError(401, "unauthorized", "Authentication required")


def require_role(*roles: str):
    def dependency(request: Request, ctx: AuthContext = Depends(current_auth)) -> AuthContext:
        role = ctx.user.get("role")
        if role != "admin" and roles and role not in roles:
            raise ApiError(403, "role_required", f"Role {role!r} cannot perform this action")
        if ctx.via == "cookie" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.headers.get("x-csrf-token")
            if not token or token != ctx.csrf:
                raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token")
        return ctx
    return dependency


require_viewer = require_role("viewer", "producer")
require_producer = require_role("producer")
require_admin = require_role("admin")
