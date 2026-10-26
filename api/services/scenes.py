"""Scene-level operations: reordering and version bookkeeping."""

from __future__ import annotations

import sqlite3
from typing import Any

from api import config, db, schemas_io
from api.errors import ApiError
from api.events import broker
from api.services import projects


def reorder(conn: sqlite3.Connection, slug: str, order: list[str], user_id: str | None) -> dict[str, Any]:
    directory = projects.project_dir(slug)
    scene_plan = schemas_io.read_json(schemas_io.artifact_path(directory, "scene_plan"))
    if scene_plan is None:
        checkpoint = schemas_io.read_json(directory / "checkpoint_scene_plan.json", {}) or {}
        scene_plan = (checkpoint.get("artifacts") or {}).get("scene_plan")
    if not isinstance(scene_plan, dict) or not isinstance(scene_plan.get("scenes"), list):
        raise ApiError(404, "artifact_not_found", "No scene_plan found for this project")
    scenes = scene_plan.get("scenes") or []
    by_id = {scene.get("id"): scene for scene in scenes if isinstance(scene, dict) and scene.get("id")}
    if len(order) != len(scenes) or set(order) != set(by_id):
        raise ApiError(
            422,
            "validation_failed",
            "Scene order must contain every scene id exactly once",
            {"expected": list(by_id), "received": order},
        )
    scene_plan["scenes"] = [by_id[scene_id] for scene_id in order]
    schemas_io.write_artifact(directory, "scene_plan", scene_plan)

    checkpoint_path = directory / "checkpoint_scene_plan.json"
    if checkpoint_path.exists():
        checkpoint = schemas_io.read_json(checkpoint_path, {}) or {}
        artifacts = dict(checkpoint.get("artifacts") or {})
        artifacts["scene_plan"] = scene_plan
        metadata = dict(checkpoint.get("metadata") or {})
        metadata["reordered_at"] = db.now()
        metadata["reordered_by"] = user_id or "system"
        from lib.checkpoint import write_checkpoint

        write_checkpoint(
            config.PROJECTS_DIR,
            slug,
            "scene_plan",
            checkpoint.get("status") or "awaiting_human",
            artifacts,
            pipeline_type=checkpoint.get("pipeline_type"),
            style_playbook=checkpoint.get("style_playbook"),
            human_approval_required=bool(checkpoint.get("human_approval_required")),
            human_approved=bool(checkpoint.get("human_approved")),
            review=checkpoint.get("review"),
            cost_snapshot=checkpoint.get("cost_snapshot"),
            metadata=metadata,
        )
    db.audit(conn, user_id, "scenes.reordered", slug, {"order": order})
    broker.publish("artifact", {"name": "scene_plan", "valid": True}, project_id=slug)
    return {"scenes": scene_plan["scenes"]}
