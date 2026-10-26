"""Human approval gates: approve/reject with checkpoint enforcement."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from api import config, db, schemas_io
from api.errors import ApiError
from api.events import broker
from api.services import jobs, pipelines, projects


def _checkpoint(conn: sqlite3.Connection, slug: str, stage: str) -> dict[str, Any]:
    from lib.checkpoint import read_checkpoint

    directory = projects.project_dir(slug)
    try:
        checkpoint = read_checkpoint(config.PROJECTS_DIR, slug, stage)
    except ValueError as exc:
        raise ApiError(422, "artifact_invalid", f"Checkpoint for stage {stage!r} is invalid", {"error": str(exc)})
    if checkpoint is None:
        raise ApiError(404, "artifact_not_found", f"No checkpoint for stage {stage!r}", {"stage": stage})
    return checkpoint


def _resolve_artifacts(directory: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, value in (mapping or {}).items():
        if isinstance(value, dict):
            resolved[name] = value
        elif isinstance(value, str):
            path = (directory / value).resolve()
            try:
                path.relative_to(directory.resolve())
            except ValueError:
                raise ApiError(403, "path_escapes_project", f"Artifact path escapes project: {value}")
            data = schemas_io.read_json(path)
            if data is None:
                raise ApiError(422, "artifact_invalid", f"Artifact file missing or invalid: {value}", {"artifact": name})
            resolved[name] = data
    return resolved


def _validate_known(artifacts: dict[str, Any]) -> None:
    known = set(schemas_io.schema_names())
    for name, data in artifacts.items():
        if name in known:
            schemas_io.validate_artifact(name, data)


async def approve(
    conn: sqlite3.Connection,
    slug: str,
    stage: str,
    *,
    note: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    project = projects.get(conn, slug)
    if not pipelines.stage_gate(project["pipeline"], stage):
        raise ApiError(409, "gate_not_pending", f"Stage {stage!r} is not a human gate")
    checkpoint = _checkpoint(conn, slug, stage)
    if checkpoint.get("status") != "awaiting_human":
        raise ApiError(
            409,
            "gate_not_pending",
            f"Stage {stage!r} is not awaiting approval",
            {"stage": stage, "status": checkpoint.get("status")},
        )
    directory = projects.project_dir(slug)
    artifacts = _resolve_artifacts(directory, checkpoint.get("artifacts") or {})
    _validate_known(artifacts)

    from lib.checkpoint import write_checkpoint

    metadata = dict(checkpoint.get("metadata") or {})
    if note:
        metadata["approval_note"] = note
    metadata["approved_by"] = user_id or "system"
    path = write_checkpoint(
        config.PROJECTS_DIR,
        slug,
        stage,
        "completed",
        artifacts,
        pipeline_type=checkpoint.get("pipeline_type") or project["pipeline"],
        style_playbook=checkpoint.get("style_playbook"),
        human_approval_required=True,
        human_approved=True,
        review=checkpoint.get("review"),
        cost_snapshot=checkpoint.get("cost_snapshot"),
        metadata=metadata,
    )
    db.audit(conn, user_id, "gate.approved", f"{slug}:{stage}")
    broker.publish("checkpoint", {"stage": stage, "status": "completed", "human_approved": True}, project_id=slug)
    broker.publish("gate", {"stage": stage, "status": "approved"}, project_id=slug)

    jobs.resolve_paused(conn, slug, stage, "succeeded")
    next_stage = pipelines.next_stage(project["pipeline"], stage)
    job = None
    if next_stage:
        job = await jobs.create(
            conn,
            project_id=slug,
            stage=next_stage,
            instruction=f"Continuar pipeline tras aprobación de {stage}",
            user_id=user_id,
        )
    from lib.checkpoint import read_checkpoint

    return {
        "stage": stage,
        "status": "approved",
        "checkpoint": read_checkpoint(config.PROJECTS_DIR, slug, stage),
        "job": job,
    }


async def reject(
    conn: sqlite3.Connection,
    slug: str,
    stage: str,
    *,
    note: str,
    user_id: str | None,
) -> dict[str, Any]:
    if not note or not note.strip():
        raise ApiError(422, "missing_reason", "A rejection note is required", {"stage": stage})
    project = projects.get(conn, slug)
    if not pipelines.stage_gate(project["pipeline"], stage):
        raise ApiError(409, "gate_not_pending", f"Stage {stage!r} is not a human gate")
    checkpoint = _checkpoint(conn, slug, stage)
    if checkpoint.get("status") != "awaiting_human":
        raise ApiError(409, "gate_not_pending", f"Stage {stage!r} is not awaiting approval")

    directory = projects.project_dir(slug)
    artifacts = _resolve_artifacts(directory, checkpoint.get("artifacts") or {})
    _validate_known(artifacts)

    from lib.checkpoint import write_checkpoint

    metadata = dict(checkpoint.get("metadata") or {})
    metadata["rejection_note"] = note.strip()
    metadata["rejected_by"] = user_id or "system"
    write_checkpoint(
        config.PROJECTS_DIR,
        slug,
        stage,
        "awaiting_human",
        artifacts,
        pipeline_type=checkpoint.get("pipeline_type") or project["pipeline"],
        style_playbook=checkpoint.get("style_playbook"),
        human_approval_required=True,
        human_approved=False,
        review=checkpoint.get("review"),
        cost_snapshot=checkpoint.get("cost_snapshot"),
        metadata=metadata,
    )
    db.audit(conn, user_id, "gate.rejected", f"{slug}:{stage}", {"note": note.strip()})
    broker.publish("gate", {"stage": stage, "status": "rejected", "note": note.strip()}, project_id=slug)

    jobs.resolve_paused(conn, slug, stage, "succeeded")
    job = await jobs.create(
        conn,
        project_id=slug,
        stage=stage,
        instruction=f"Revisión solicitada: {note.strip()}",
        user_id=user_id,
    )
    from lib.checkpoint import read_checkpoint

    return {
        "stage": stage,
        "status": "rejected",
        "checkpoint": read_checkpoint(config.PROJECTS_DIR, slug, stage),
        "job": job,
    }
