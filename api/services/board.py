"""Board aggregation for the workspace UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api import config, db, schemas_io
from api.services import projects


def _media_url(slug: str, path: str | None) -> str | None:
    if not path:
        return None
    return f"/api/projects/{slug}/media/{path.lstrip('/')}"


def _tag_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("shot_size", "camera_movement", "lighting_key", "type", "name", "label"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return ""


def _cost_usd(snapshot: Any) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    for key in ("spent_usd", "total_usd", "actual_usd"):
        try:
            if snapshot.get(key) is not None:
                return float(snapshot[key])
        except (TypeError, ValueError):
            continue
    return 0.0


def _decisions(project_dir: Path) -> list[dict[str, Any]]:
    data = schemas_io.read_json(project_dir / "artifacts" / "decision_log.json", {}) or {}
    out = []
    for index, item in enumerate(data.get("decisions", [])):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id") or f"dec_{index}",
                "category": item.get("category") or "general",
                "subject": item.get("subject") or item.get("decision") or "",
                "chosen": item.get("chosen") or item.get("choice") or "",
                "options_considered": item.get("options_considered") or [],
                "rejected_because": item.get("rejected_because"),
                "confidence": item.get("confidence"),
                "decided_at": item.get("timestamp") or item.get("decided_at") or "",
                "status": item.get("status") or "approved",
            }
        )
    return out


def _activity(state: dict[str, Any]) -> list[dict[str, Any]]:
    items = state.get("events") or []
    out = []
    for index, item in enumerate(items[-50:]):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id") or f"evt_{index}",
                "ts": item.get("timestamp") or item.get("ts") or "",
                "type": item.get("type") or "event",
                "message": item.get("message") or item.get("description") or "",
                "actor": item.get("actor") or "system",
                "level": item.get("level") or "info",
                "job_id": item.get("job_id"),
            }
        )
    return out


def build(conn, slug: str) -> dict[str, Any]:
    from backlot.state import load_board_state

    directory = projects.project_dir(slug)
    state = load_board_state(directory)
    project = projects.get(conn, slug)

    stages: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for item in state.get("stages") or []:
        produces = item.get("produces") or []
        stages.append(
            {
                "name": item.get("name"),
                "status": item.get("status") or "pending",
                "gate": bool(item.get("gated")),
                "started_at": item.get("timestamp") if item.get("status") == "in_progress" else None,
                "completed_at": item.get("timestamp") if item.get("status") == "completed" else None,
                "human_approved": item.get("human_approved"),
                "artifact": produces[0] if produces else None,
                "cost_usd": _cost_usd(item.get("cost_snapshot")),
            }
        )
        if item.get("gated"):
            if item.get("status") == "awaiting_human":
                status = "pending"
            elif item.get("status") == "completed" and item.get("human_approved"):
                status = "approved"
            elif item.get("status") == "completed" and item.get("human_approved") is False:
                status = "rejected"
            else:
                status = "not_required"
            gates.append(
                {
                    "stage": item.get("name"),
                    "required": True,
                    "status": status,
                    "requested_at": item.get("timestamp") if item.get("status") == "awaiting_human" else None,
                    "decided_at": item.get("timestamp") if item.get("human_approved") else None,
                    "decided_by": None,
                    "note": None,
                }
            )

    storyboard = state.get("storyboard") or {}
    scenes: list[dict[str, Any]] = []
    for index, card in enumerate(storyboard.get("scenes") or []):
        visual = card.get("visual") if isinstance(card.get("visual"), dict) else None
        scenes.append(
            {
                "id": card.get("id"),
                "index": index + 1,
                "start_seconds": card.get("start_seconds") or 0,
                "end_seconds": card.get("end_seconds") or 0,
                "type": card.get("type"),
                "title": card.get("section_label"),
                "description": card.get("description"),
                "hero": bool(card.get("hero_moment")),
                "status": "generating" if card.get("generating") else ("ready" if card.get("visual") else "draft"),
                "asset_id": (visual or {}).get("id"),
                "thumbnail_url": _media_url(slug, (visual or {}).get("path")),
                "prompt": (visual or {}).get("prompt"),
                "quality_score": (visual or {}).get("quality_score"),
                "cost_usd": (visual or {}).get("cost_usd"),
                "provider": (visual or {}).get("provider"),
                "model": (visual or {}).get("model"),
                "tags": [tag for tag in (_tag_text(card.get("framing")), _tag_text(card.get("movement")), _tag_text(card.get("shot_language"))) if tag],
            }
        )

    renders = []
    for item in (state.get("media") or {}).get("renders", []):
        path = item.get("path")
        renders.append(
            {
                "id": path,
                "path": path,
                "url": _media_url(slug, path),
                "duration_seconds": None,
                "width": None,
                "height": None,
                "size_bytes": item.get("size"),
                "is_final": path.endswith("final.mp4"),
                "created_at": None,
            }
        )

    cost_state = state.get("cost") or {}
    spent = project["cost_usd"]
    budget = config.DEFAULT_BUDGET_USD
    if isinstance(cost_state, dict):
        spent = float(cost_state.get("budget_spent_usd") or spent)
        budget = float(cost_state.get("budget_total_usd") or budget)

    return {
        "project": project,
        "stages": stages,
        "gates": gates,
        "artifacts": schemas_io.artifact_summaries(directory),
        "scenes": scenes,
        "decisions": _decisions(directory),
        "activity": _activity(state),
        "cost": {"spent_usd": round(spent, 4), "budget_usd": budget, "reserved_usd": 0.0},
        "renders": renders,
    }
