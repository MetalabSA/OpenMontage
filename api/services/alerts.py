"""Webhook alerts for failed jobs and disk pressure (F8)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import requests

from api import db
from api.services import backups

DEFAULTS = {
    "enabled": False,
    "webhook_url": "",
    "on_job_failed": True,
    "disk_pct": 80,
}


def config(conn) -> dict[str, Any]:
    stored = db.get_setting(conn, "alerts", {}) or {}
    merged = dict(DEFAULTS)
    merged.update({key: value for key, value in stored.items() if key in DEFAULTS})
    return merged


def send(conn, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = config(conn)
    url = (cfg.get("webhook_url") or "").strip()
    if not cfg.get("enabled") or not url:
        return {"sent": False, "reason": "alerts_disabled"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"sent": False, "reason": "invalid_url"}
    body = {
        "source": "cabina-studio",
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        response = requests.post(url, json=body, timeout=5)
        return {"sent": True, "status": response.status_code}
    except requests.RequestException as exc:
        return {"sent": False, "reason": "request_failed", "error": str(exc)[:300]}


async def notify(conn, event: str, payload: dict[str, Any]) -> None:
    await asyncio.to_thread(send, conn, event, payload)


async def ops_scheduler() -> None:
    while True:
        try:
            conn = db.connect()
            try:
                cfg = config(conn)
                storage = backups.storage_stats()
                threshold = int(cfg.get("disk_pct") or 80)
                if storage["disk_used_pct"] >= threshold:
                    last = float(db.get_setting(conn, "alerts.last_disk_alert", 0) or 0)
                    if time.time() - last > 86400:
                        send(conn, "disk.warning", {"disk_used_pct": storage["disk_used_pct"], "disk_free_gb": storage["disk_free_gb"]})
                        db.set_setting(conn, "alerts.last_disk_alert", time.time())
            finally:
                conn.close()
        except Exception:
            pass
        await asyncio.sleep(600)
