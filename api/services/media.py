"""Assets, renders and safe media serving."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from api import schemas_io
from api.errors import ApiError
from api.services import projects


def resolve_media(project_dir: Path, relative: str) -> Path:
    target = (project_dir / relative).resolve()
    try:
        target.relative_to(project_dir.resolve())
    except ValueError:
        raise ApiError(403, "path_escapes_project", "Path escapes the project directory")
    if not target.is_file():
        raise ApiError(404, "not_found", "File not found", {"path": relative})
    return target


def assets(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    directory = projects.project_dir(slug)
    manifest = schemas_io.read_json(directory / "artifacts" / "asset_manifest.json", {}) or {}
    items = []
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict):
            continue
        path = asset.get("path")
        url = None
        if isinstance(path, str) and (directory / path).is_file():
            url = f"/api/projects/{slug}/media/{path.lstrip('/')}"
        items.append(
            {
                "id": asset.get("id"),
                "type": asset.get("type"),
                "path": path,
                "url": url,
                "scene_id": asset.get("scene_id"),
                "prompt": asset.get("prompt"),
                "provider": asset.get("provider"),
                "model": asset.get("model"),
                "seed": asset.get("seed"),
                "cost_usd": float(asset.get("cost_usd") or 0),
                "duration_seconds": asset.get("duration_seconds"),
                "resolution": asset.get("resolution"),
                "quality_score": asset.get("quality_score"),
                "license": asset.get("license"),
                "original_url": asset.get("original_url"),
            }
        )
    return {"assets": items, "total_cost_usd": float(manifest.get("total_cost_usd") or 0)}


def renders(slug: str) -> dict[str, Any]:
    directory = projects.project_dir(slug)
    render_dir = directory / "renders"
    items = []
    for path in sorted(render_dir.glob("*.mp4")) if render_dir.is_dir() else []:
        stat = path.stat()
        items.append(
            {
                "id": path.stem,
                "path": f"renders/{path.name}",
                "url": f"/api/projects/{slug}/media/renders/{path.name}",
                "duration_seconds": None,
                "width": None,
                "height": None,
                "size_bytes": stat.st_size,
                "is_final": path.name == "final.mp4",
                "created_at": None,
            }
        )
    return {"renders": items}
