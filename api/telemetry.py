"""Process-level HTTP telemetry and structured request logging."""

from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger("cabina.http")


class HttpStats:
    def __init__(self) -> None:
        self.total = 0
        self.by_status: dict[int, int] = {}
        self.duration_ms_sum = 0.0
        self._lock = threading.Lock()

    def record(self, status: int, duration_ms: float) -> None:
        with self._lock:
            self.total += 1
            self.by_status[status] = self.by_status.get(status, 0) + 1
            self.duration_ms_sum += duration_ms

    def snapshot(self) -> dict:
        with self._lock:
            avg = (self.duration_ms_sum / self.total) if self.total else 0.0
            return {"total": self.total, "by_status": dict(self.by_status), "avg_ms": round(avg, 2)}


http_stats = HttpStats()


def log_request(request_id: str, method: str, path: str, status: int, duration_ms: float, user: str | None = None) -> None:
    logger.info(
        json.dumps(
            {
                "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "event": "http.request",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "user": user,
            },
            ensure_ascii=False,
        )
    )
