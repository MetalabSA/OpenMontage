"""Event broker with SSE formatting and JSONL persistence for replay."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from api import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Broker:
    def __init__(self, capacity: int = 2000, path=None) -> None:
        self._seq = 0
        self._ring: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue] = set()
        self._path = path or config.EVENTS_PATH
        self._load()

    def _load(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            lines = self._path.read_text(encoding="utf-8").splitlines()[-self._ring.maxlen :]
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._ring.append(event)
                self._seq = max(self._seq, int(str(event.get("id", "evt_0")).rsplit("_", 1)[-1] or 0))
        except OSError:
            pass

    def _persist(self, event: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        project_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        event = {
            "id": f"evt_{self._seq:06d}",
            "type": event_type,
            "ts": _now(),
            "project_id": project_id,
            "job_id": job_id,
            "payload": payload,
        }
        self._ring.append(event)
        self._persist(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def _persisted(self) -> list[dict[str, Any]]:
        try:
            if not self._path.exists():
                return []
            events = []
            for line in self._path.read_text(encoding="utf-8").splitlines()[-5000:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return events
        except OSError:
            return []

    def replay(self, since: str | None, project: str | None, limit: int = 1000) -> list[dict[str, Any]]:
        events = self._persisted() or list(self._ring)
        if since:
            try:
                seq = int(str(since).rsplit("_", 1)[-1])
                events = [e for e in events if int(str(e.get("id", "evt_0")).rsplit("_", 1)[-1]) > seq]
            except ValueError:
                pass
        if project:
            events = [e for e in events if e.get("project_id") in (project, None)]
        return events[-limit:]

    async def stream(self, since: str | None = None, project: str | None = None) -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        try:
            hello = {
                "id": f"evt_{self._seq:06d}",
                "type": "hello",
                "ts": _now(),
                "project_id": project,
                "job_id": None,
                "payload": {"server_time": _now(), "resume_from": since},
            }
            yield format_sse(hello)
            for event in self.replay(since, project):
                yield format_sse(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if project and event.get("project_id") not in (project, None):
                    continue
                yield format_sse(event)
        finally:
            self._subscribers.discard(queue)


def format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False)
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


broker = Broker()
