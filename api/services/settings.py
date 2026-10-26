"""Settings, provider keys (encrypted at rest) and engine configuration."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from api import config, db, security
from api.errors import ApiError


def _fernet() -> Fernet:
    config.SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not config.SECRET_FILE.exists():
        config.SECRET_FILE.write_bytes(Fernet.generate_key())
        try:
            config.SECRET_FILE.chmod(0o600)
        except OSError:
            pass
    return Fernet(config.SECRET_FILE.read_bytes())


def _stored_providers(conn: sqlite3.Connection) -> dict[str, str]:
    raw = db.get_setting(conn, "providers.enc")
    if not raw:
        return {}
    try:
        return json.loads(_fernet().decrypt(raw.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError):
        return {}


def _save_providers(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    token = _fernet().encrypt(json.dumps(values).encode()).decode()
    db.set_setting(conn, "providers.enc", token)


def _provider_list(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    stored = _stored_providers(conn)
    out = []
    for provider, env_name in config.PROVIDER_ENV.items():
        env_value = os.environ.get(env_name, "")
        value = stored.get(provider) or env_value
        out.append(
            {
                "id": provider,
                "configured": bool(value),
                "key_preview": security.mask_key(value) if value else None,
                "source": "database" if stored.get(provider) else ("env" if env_value else "none"),
            }
        )
    return out


def read(conn: sqlite3.Connection) -> dict[str, Any]:
    stored_map = db.get_setting(conn, "engine.model_map", None)
    return {
        "providers": _provider_list(conn),
        "engine": {
            "default_map": stored_map if isinstance(stored_map, dict) else config.DEFAULT_MODEL_MAP,
            "providers": {"harness": config.DEFAULT_ENGINE, "anthropic_compatible": True},
        },
        "retention": db.get_setting(conn, "retention", {"projects_days": 90, "renders_days": 30}),
        "budget": db.get_setting(conn, "budget", {"total_usd": config.DEFAULT_BUDGET_USD, "mode": "warn"}),
        "backup": db.get_setting(conn, "backup", {"enabled": True, "hour": 3, "keep": config.BACKUP_KEEP}),
    }


def update(conn: sqlite3.Connection, payload: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    if "engine" in payload and isinstance(payload["engine"], dict):
        model_map = payload["engine"].get("default_map")
        if isinstance(model_map, dict):
            valid = {k: str(v) for k, v in model_map.items() if k in config.DEFAULT_MODEL_MAP or k == ""}
            db.set_setting(conn, "engine.model_map", valid)
    if "retention" in payload and isinstance(payload["retention"], dict):
        db.set_setting(conn, "retention", payload["retention"])
    if "budget" in payload and isinstance(payload["budget"], dict):
        db.set_setting(conn, "budget", payload["budget"])
    if "backup" in payload and isinstance(payload["backup"], dict):
        db.set_setting(conn, "backup", payload["backup"])
    if "providers" in payload and isinstance(payload["providers"], dict):
        current = _stored_providers(conn)
        for provider, value in payload["providers"].items():
            if provider not in config.PROVIDER_ENV:
                raise ApiError(422, "invalid_request", f"Unknown provider {provider!r}")
            if value:
                current[provider] = str(value)
            else:
                current.pop(provider, None)
        _save_providers(conn, current)
    db.audit(conn, user_id, "settings.updated", "global")
    return read(conn)
