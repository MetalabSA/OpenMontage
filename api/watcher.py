"""Filesystem watcher: publishes SSE events when a project changes on disk."""

from __future__ import annotations

import asyncio
from pathlib import Path

from watchfiles import awatch

from api import config
from api.events import broker


async def watch_projects() -> None:
    if not config.PROJECTS_DIR.is_dir():
        return
    async for changes in awatch(config.PROJECTS_DIR):
        for _, raw in changes:
            path = Path(raw)
            try:
                rel = path.relative_to(config.PROJECTS_DIR)
            except ValueError:
                continue
            parts = rel.parts
            if len(parts) < 2 or parts[0].startswith(("_", ".")):
                continue
            slug = parts[0]
            name = path.name
            if name.startswith("checkpoint_") and name.endswith(".json"):
                broker.publish(
                    "checkpoint",
                    {"stage": name[len("checkpoint_") : -len(".json")], "path": str(rel)},
                    project_id=slug,
                )
            elif parts[1] == "artifacts" and name.endswith(".json"):
                broker.publish("artifact", {"name": path.stem, "path": str(rel)}, project_id=slug)
            elif parts[1] == "renders" and name.endswith(".mp4"):
                broker.publish("render", {"path": str(rel)}, project_id=slug)
