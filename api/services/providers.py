"""Provider capability menu with a short-lived cache."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

_CACHE_TTL = 60.0
_lock = threading.Lock()
_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def menu() -> dict[str, Any]:
    now = time.time()
    with _lock:
        if _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL:
            return _cache["data"]
    from tools.tool_registry import registry  # imported lazily: discovery scans 150+ modules

    registry.discover()
    summary = registry.provider_menu_summary()
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _cache["data"] = summary
        _cache["ts"] = time.time()
    return summary


def runtimes() -> dict[str, bool]:
    return dict(menu().get("composition_runtimes", {}))
