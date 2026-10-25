"""In-process event broker and SSE formatting."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Broker:
    def __init__(self, capacity: int = 2000) -> None:
        self._seq = 0
        self._ring: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue] = set()

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
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def replay(self, since: str | None, project: str | None) -> list[dict[str, Any]]:
        events = list(self._ring)
        if since:
            try:
                seq = int(since.rsplit("_", 1)[-1])
                events = [e for e in events if int(e["id"].rsplit("_", 1)[-1]) > seq]
            except ValueError:
                pass
        if project:
            events = [e for e in events if e.get("project_id") in (project, None)]
        return events

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
