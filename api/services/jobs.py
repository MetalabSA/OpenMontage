"""Job queue and the F3 simulated runner (F4 replaces it with the agent)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from api import config, db
from api.errors import ApiError
from api.events import broker
from api.services import projects

ACTIVE = ("queued", "running", "awaiting_human")
_TASKS: dict[str, asyncio.Task] = {}
_SEMAPHORE: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(1)
    return _SEMAPHORE


def _row(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def _public(row: dict[str, Any]) -> dict[str, Any]:
    try:
        progress = json.loads(row.get("progress_json") or "{}")
    except json.JSONDecodeError:
        progress = {}
    try:
        result = json.loads(row.get("result_json") or "null")
    except json.JSONDecodeError:
        result = None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "stage": row.get("stage"),
        "scene_id": row.get("scene_id"),
        "status": row["status"],
        "engine": row.get("engine") or config.DEFAULT_ENGINE,
        "model": row.get("model"),
        "instruction": row.get("instruction"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "cost_usd": round(float(row.get("cost_usd") or 0), 4),
        "error": row.get("error"),
        "progress": progress,
        "result": result,
        "cancel_requested": bool(row.get("cancel_requested")),
    }


def get(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = _row(conn, job_id)
    if row is None:
        raise ApiError(404, "job_not_found", f"Unknown job {job_id!r}", {"job_id": job_id})
    return _public(row)


def list_jobs(
    conn: sqlite3.Connection,
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", (*params, max(1, min(limit, 100)))
    ).fetchall()
    return {"data": [_public(dict(row)) for row in rows], "next_cursor": None}


def active_for_project(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM jobs WHERE project_id = ? AND status IN ({','.join('?' * len(ACTIVE))}) "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id, *ACTIVE),
    ).fetchone()
    return _public(dict(row)) if row else None


def _emit(conn: sqlite3.Connection, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
    project_id = None
    row = conn.execute("SELECT project_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row:
        project_id = row["project_id"]
    seq_row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM job_events WHERE job_id = ?", (job_id,)
    ).fetchone()
    seq = int(seq_row["n"])
    conn.execute(
        "INSERT INTO job_events(id, job_id, seq, type, payload_json, created_at) VALUES(?,?,?,?,?,?)",
        (db.new_id("jevt"), job_id, seq, event_type, json.dumps(payload), db.now()),
    )
    conn.commit()
    broker.publish(event_type, payload, project_id=project_id, job_id=job_id)


def _default_model(stage: str | None, conn: sqlite3.Connection) -> str:
    stored = db.get_setting(conn, "engine.model_map", None)
    mapping = stored if isinstance(stored, dict) else config.DEFAULT_MODEL_MAP
    return mapping.get(stage or "", "deepseek-flash")


async def create(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    stage: str | None = None,
    scene_id: str | None = None,
    instruction: str | None = None,
    engine: str | None = None,
    model: str | None = None,
    budget_usd: float | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    projects.project_dir(project_id)
    active = active_for_project(conn, project_id)
    if active:
        raise ApiError(
            409,
            "job_already_running",
            "A job is already active for this project",
            {"job_id": active["id"], "status": active["status"]},
        )
    job_id = db.new_id("job")
    created = db.now()
    conn.execute(
        "INSERT INTO jobs(id, project_id, stage, scene_id, status, engine, model, instruction, created_at, cost_usd) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            project_id,
            stage,
            scene_id,
            "queued",
            engine or config.DEFAULT_ENGINE,
            model or _default_model(stage, conn),
            instruction,
            created,
            0.0,
        ),
    )
    conn.commit()
    db.audit(conn, user_id, "job.created", job_id, {"project": project_id, "stage": stage, "budget": budget_usd})
    _emit(conn, job_id, "job", {"status": "queued", "stage": stage, "progress": {"percent": 0, "message": "queued"}})
    _TASKS[job_id] = asyncio.get_running_loop().create_task(_run(job_id))
    return get(conn, job_id)


async def _run(job_id: str) -> None:
    async with _semaphore():
        conn = db.connect()
        try:
            row = _row(conn, job_id)
            if row is None:
                return
            if row.get("cancel_requested"):
                _finish(conn, job_id, "cancelled")
                return
            conn.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE id=?", (db.now(), job_id)
            )
            conn.commit()
            _emit(conn, job_id, "job", {"status": "running", "stage": row.get("stage"), "progress": {"percent": 5, "message": "iniciando"}})

            steps = [
                (20, "cargando contexto"),
                (45, "planificando"),
                (70, "ejecutando herramientas"),
                (90, "validando artefacto"),
            ]
            for percent, message in steps:
                await asyncio.sleep(max(config.SIM_SPEED, 0))
                current = _row(conn, job_id)
                if current and current.get("cancel_requested"):
                    _finish(conn, job_id, "cancelled")
                    return
                conn.execute(
                    "UPDATE jobs SET progress_json=? WHERE id=?",
                    (json.dumps({"percent": percent, "message": message}), job_id),
                )
                conn.commit()
                _emit(conn, job_id, "job", {"status": "running", "progress": {"percent": percent, "message": message}})

            result = {"simulated": True, "stage": row.get("stage"), "scene_id": row.get("scene_id")}
            _finish(conn, job_id, "succeeded", result=result)
        except Exception as exc:  # pragma: no cover - defensive
            try:
                _finish(conn, job_id, "failed", error=str(exc))
            except Exception:
                pass
        finally:
            conn.close()
            _TASKS.pop(job_id, None)


def _finish(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    progress = {"percent": 100, "message": "completado"} if status == "succeeded" else None
    if progress:
        conn.execute("UPDATE jobs SET progress_json=? WHERE id=?", (json.dumps(progress), job_id))
    conn.execute(
        "UPDATE jobs SET status=?, finished_at=?, result_json=?, error=? WHERE id=?",
        (status, db.now(), json.dumps(result) if result else None, error, job_id),
    )
    conn.commit()
    _emit(conn, job_id, "job", {"status": status, "error": error, "result": result, "progress": progress})


def cancel(conn: sqlite3.Connection, job_id: str, user_id: str | None = None) -> dict[str, Any]:
    row = _row(conn, job_id)
    if row is None:
        raise ApiError(404, "job_not_found", f"Unknown job {job_id!r}")
    if row["status"] in {"succeeded", "failed", "cancelled"}:
        raise ApiError(409, "conflict", f"Job already finished ({row['status']})")
    if row["status"] == "queued":
        _finish(conn, job_id, "cancelled")
    else:
        conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        conn.commit()
    db.audit(conn, user_id, "job.cancelled", job_id)
    return get(conn, job_id)
