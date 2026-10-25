"""SQLite control-plane storage for Cabina Studio."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from api import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT,
  role TEXT NOT NULL DEFAULT 'producer', password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
  scopes TEXT, last_used TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, prod_no INTEGER NOT NULL, slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL, pipeline TEXT NOT NULL, version TEXT NOT NULL DEFAULT 'V1',
  status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, stage TEXT, scene_id TEXT,
  status TEXT NOT NULL, engine TEXT NOT NULL, model TEXT, instruction TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  cost_usd REAL NOT NULL DEFAULT 0, error TEXT, progress_json TEXT,
  result_json TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_events (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, seq INTEGER NOT NULL,
  type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY, user_id TEXT, action TEXT NOT NULL, target TEXT,
  meta_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_threads (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  model TEXT, job_id TEXT, actions_json TEXT, status TEXT NOT NULL DEFAULT 'complete',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scene_versions (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scene_id TEXT NOT NULL,
  version INTEGER NOT NULL, asset_path TEXT, prompt_json TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, status);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_messages(thread_id, created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value), now()),
    )
    conn.commit()


def audit(conn: sqlite3.Connection, user_id: str | None, action: str, target: str = "", meta: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(id, user_id, action, target, meta_json, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("aud"), user_id, action, target, json.dumps(meta or {}), now()),
    )
    conn.commit()
