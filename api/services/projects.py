"""Production projects: filesystem truth + control-plane index."""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from api import config, db, schemas_io
from api.errors import ApiError
from api.events import broker
from api.services import pipelines

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or "produccion")[:62]


def project_dir(slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ApiError(404, "project_not_found", f"Unknown project {slug!r}")
    path = config.PROJECTS_DIR / slug
    if not path.is_dir():
        raise ApiError(404, "project_not_found", f"Unknown project {slug!r}", {"slug": slug})
    return path


def _checkpoint_statuses(path: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for checkpoint in sorted(path.glob("checkpoint_*.json")):
        data = schemas_io.read_json(checkpoint, {}) or {}
        stage = data.get("stage") or checkpoint.stem.replace("checkpoint_", "")
        if data.get("status"):
            statuses[stage] = data["status"]
    return statuses


def derive_status(slug: str, directory: Path, row: dict | None) -> str:
    if row and row.get("status") == "archived":
        return "archived"
    statuses = _checkpoint_statuses(directory)
    if any(value == "awaiting_human" for value in statuses.values()):
        return "awaiting_human"
    if statuses.get("compose") == "in_progress":
        return "composing"
    final = directory / "renders" / "final.mp4"
    report = directory / "artifacts" / "render_report.json"
    if final.is_file() and report.is_file():
        return "ready"
    rendered = [path for path in (directory / "renders").glob("*.mp4") if path.stat().st_size > 0]
    if statuses.get("compose") == "completed" and rendered:
        return "ready"
    if statuses and all(value == "completed" for value in statuses.values()):
        return "composing"
    if any(value == "failed" for value in statuses.values()):
        return "failed"
    if statuses:
        return "in_progress"
    return "draft"


_BRIEF_PLATFORM = {
    "instagram_reels": "instagram",
    "instagram_feed": "instagram",
    "tiktok": "tiktok",
    "youtube_shorts": "youtube",
    "youtube_landscape": "youtube",
    "linkedin": "linkedin",
    "custom": "generic",
}


def _brief_artifact(title: str, pipeline: str, platform: str, brief: dict | None) -> dict[str, Any]:
    brief = brief or {}
    data = {
        "version": "1.0",
        "title": title,
        "hook": brief.get("hook") or f"Por qué {title} importa",
        "key_points": brief.get("key_points") or [title],
        "tone": brief.get("tone") or "claro y directo",
        "style": brief.get("style") or "clean-professional",
        "target_platform": brief.get("target_platform") or _BRIEF_PLATFORM.get(platform, "generic"),
        "target_duration_seconds": float(brief.get("target_duration_seconds") or 30),
        "core_message": brief.get("core_message") or title,
        "target_audience": brief.get("target_audience") or "público general",
        "metadata": {"pipeline": pipeline, "source": "cabina"},
    }
    if brief.get("reference_material"):
        data["reference_material"] = brief["reference_material"]
    return data


def create(
    conn: sqlite3.Connection,
    *,
    user_id: str | None,
    title: str,
    pipeline: str,
    platform: str = "instagram_reels",
    brief: dict | None = None,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    if not title or len(title.strip()) < 3:
        raise ApiError(422, "validation_failed", "Title must have at least 3 characters")
    pipelines.get_pipeline(pipeline)
    slug = slugify(title)
    if (config.PROJECTS_DIR / slug).exists():
        raise ApiError(409, "slug_exists", f"A project with slug {slug!r} already exists", {"slug": slug})
    brief_data = _brief_artifact(title.strip(), pipeline, platform, brief)
    schemas_io.validate_artifact("brief", brief_data)

    from lib.checkpoint import init_project

    directory = init_project(slug, title=title.strip(), pipeline_type=pipeline, pipeline_dir=config.PROJECTS_DIR)
    schemas_io.write_artifact(directory, "brief", brief_data)

    row = conn.execute("SELECT COALESCE(MAX(prod_no), 0) + 1 AS n FROM projects").fetchone()
    prod_no = int(row["n"])
    now = db.now()
    conn.execute(
        "INSERT INTO projects(id, prod_no, slug, title, pipeline, version, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (db.new_id("prj"), prod_no, slug, title.strip(), pipeline, "V1", "draft", now, now),
    )
    conn.commit()
    db.audit(conn, user_id, "project.created", slug, {"pipeline": pipeline, "prod_no": prod_no})
    broker.publish(
        "artifact",
        {"name": "brief", "valid": True, "updated_at": now},
        project_id=slug,
    )
    return get(conn, slug)


def get(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    directory = project_dir(slug)
    marker = schemas_io.read_json(directory / "project.json", {}) or {}
    row = db.row_to_dict(
        conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
    )
    status = derive_status(slug, directory, row)
    render_dir = directory / "renders"
    renders = sorted(p for p in render_dir.glob("*.mp4") if p.is_file()) if render_dir.is_dir() else []
    return {
        "id": (row or {}).get("id") or f"fs_{slug}",
        "prod_no": (row or {}).get("prod_no") or 0,
        "slug": slug,
        "title": marker.get("title") or (row or {}).get("title") or slug.replace("-", " ").title(),
        "pipeline": marker.get("pipeline_type") or (row or {}).get("pipeline") or "unknown",
        "version": (row or {}).get("version") or "V1",
        "status": status,
        "platform": marker.get("platform") or "instagram_reels",
        "duration_seconds": marker.get("duration_seconds") or 0,
        "cost_usd": _project_cost(directory),
        "poster_url": f"/api/projects/{slug}/media/renders/{renders[0].name}" if renders else None,
        "active_stage": _active_stage(directory),
        "awaiting_human": status == "awaiting_human",
        "created_at": marker.get("created_at") or (row or {}).get("created_at"),
        "updated_at": (row or {}).get("updated_at") or marker.get("created_at"),
    }


def _active_stage(directory: Path) -> str | None:
    for checkpoint in sorted(directory.glob("checkpoint_*.json")):
        data = schemas_io.read_json(checkpoint, {}) or {}
        if data.get("status") in {"in_progress", "awaiting_human"}:
            return data.get("stage")
    return None


def _project_cost(directory: Path) -> float:
    total = 0.0
    for checkpoint in directory.glob("checkpoint_*.json"):
        data = schemas_io.read_json(checkpoint, {}) or {}
        snapshot = data.get("cost_snapshot") or {}
        try:
            total += float(snapshot.get("spent_usd") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 4)


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return max(0, int(base64.urlsafe_b64decode(padded).decode()))
    except Exception:
        raise ApiError(400, "invalid_cursor", "Invalid pagination cursor")


def list_projects(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    from backlot.state import list_projects as fs_list

    db_rows = {row["slug"]: dict(row) for row in conn.execute("SELECT * FROM projects")}
    summaries = []
    for item in fs_list(config.PROJECTS_DIR):
        slug = item["project_id"]
        row = db_rows.get(slug)
        if row and row.get("status") == "archived":
            continue
        declared = derive_status(slug, config.PROJECTS_DIR / slug, row)
        summary = {
            "id": (row or {}).get("id") or f"fs_{slug}",
            "prod_no": (row or {}).get("prod_no") or 0,
            "slug": slug,
            "title": item.get("title") or slug.replace("-", " ").title(),
            "pipeline": item.get("pipeline_type") or (row or {}).get("pipeline") or "unknown",
            "status": declared,
            "active_stage": item.get("active_stage"),
            "awaiting_human": declared == "awaiting_human",
            "duration_seconds": 0,
            "cost_usd": _project_cost(config.PROJECTS_DIR / slug),
            "poster_url": f"/api/projects/{slug}/media/{item['poster']}" if item.get("poster") else None,
            "updated_at": (row or {}).get("updated_at") or item.get("created_at"),
        }
        if status and summary["status"] != status:
            continue
        if query and query.lower() not in f"{summary['title']} {slug}".lower():
            continue
        summaries.append(summary)
    offset = _decode_cursor(cursor)
    page = summaries[offset : offset + max(1, min(limit, 100))]
    next_offset = offset + len(page)
    return {
        "data": page,
        "next_cursor": _encode_cursor(next_offset) if next_offset < len(summaries) else None,
    }


def archive(conn: sqlite3.Connection, slug: str, user_id: str | None) -> None:
    directory = project_dir(slug)
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if row:
        conn.execute("UPDATE projects SET status='archived', updated_at=? WHERE slug=?", (db.now(), slug))
        conn.commit()
    marker = schemas_io.read_json(directory / "project.json", {}) or {}
    marker["archived"] = True
    (directory / "project.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    db.audit(conn, user_id, "project.archived", slug)
    broker.publish("job", {"status": "archived"}, project_id=slug)
