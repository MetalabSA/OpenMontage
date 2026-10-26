"""Production chat: persisted thread + intent routing to jobs (F3: no agent yet)."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from api import db
from api.errors import ApiError
from api.events import broker
from api.errors import ApiError
from api.services import jobs, projects

_STAGE_HINTS = [
    ("research", ("investig", "research", "fuentes")),
    ("proposal", ("propuesta", "concepto", "enfoque")),
    ("script", ("guion", "guión", "narración", "voz en off")),
    ("scene_plan", ("escena", "storyboard", "plan de escena")),
    ("assets", ("asset", "imagen", "clip", "footage", "recurso")),
    ("edit", ("editar", "corte", "montaje")),
    ("compose", ("render", "componer", "exportar")),
]


def _thread(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM chat_threads WHERE project_id = ? ORDER BY created_at LIMIT 1", (project_id,)
    ).fetchone()
    if row:
        return dict(row)
    thread_id = db.new_id("thr")
    conn.execute(
        "INSERT INTO chat_threads(id, project_id, title, created_at) VALUES(?,?,?,?)",
        (thread_id, project_id, f"Hilo {project_id}", db.now()),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,)).fetchone())


def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    try:
        actions = json.loads(data.get("actions_json") or "[]")
    except json.JSONDecodeError:
        actions = []
    return {
        "id": data["id"],
        "thread_id": data.get("thread_id"),
        "role": data["role"],
        "content": data["content"],
        "model": data.get("model"),
        "status": data.get("status") or "complete",
        "job_id": data.get("job_id"),
        "actions": actions,
        "created_at": data.get("created_at"),
    }


def history(conn: sqlite3.Connection, project_id: str, limit: int = 20) -> dict[str, Any]:
    projects.project_dir(project_id)
    thread = _thread(conn, project_id)
    rows = conn.execute(
        "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
        (thread["id"], max(1, min(limit, 100))),
    ).fetchall()
    return {"data": [_public(r) for r in reversed(rows)], "next_cursor": None}


STAGE_ORDER = ["research", "proposal", "script", "scene_plan", "assets", "edit", "compose", "publish"]


def _statuses(project_id: str) -> dict[str, str]:
    from api import schemas_io

    directory = projects.project_dir(project_id)
    statuses: dict[str, str] = {}
    for stage in STAGE_ORDER:
        data = schemas_io.read_json(directory / f"checkpoint_{stage}.json", {}) or {}
        if data.get("status"):
            statuses[stage] = data["status"]
    return statuses


def _blocker(statuses: dict[str, str], stage: str) -> str | None:
    if stage not in STAGE_ORDER:
        return None
    for previous in STAGE_ORDER[: STAGE_ORDER.index(stage)]:
        if statuses.get(previous) != "completed":
            return previous
    return None


def _classify(content: str, scope: dict | None) -> tuple[str | None, str | None]:
    scope = scope or {}
    stage = scope.get("stage")
    scene_id = scope.get("scene_id")
    if scene_id and not stage:
        stage = "assets"
    text = content.lower()
    scene_match = re.search(r"escena\s*(\d{1,3})", text)
    if scene_match and not scene_id:
        scene_id = f"sc_{int(scene_match.group(1)):02d}"
        stage = stage or "assets"
    if stage:
        return stage, scene_id
    for candidate, words in _STAGE_HINTS:
        if any(word in text for word in words):
            return candidate, scene_id
    return None, scene_id


async def post(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    content: str,
    model: str | None,
    scope: dict | None,
    user_id: str | None,
) -> dict[str, Any]:
    projects.project_dir(project_id)
    if not content or not content.strip():
        raise ApiError(422, "validation_failed", "Message content is required")
    thread = _thread(conn, project_id)
    user_msg_id = db.new_id("msg")
    now = db.now()
    conn.execute(
        "INSERT INTO chat_messages(id, thread_id, role, content, model, status, created_at) VALUES(?,?,?,?,?,?,?)",
        (user_msg_id, thread["id"], "user", content.strip(), model, "complete", now),
    )
    conn.commit()

    stage, scene_id = _classify(content, scope)
    job = None
    actions: list[dict[str, Any]] = []
    if stage:
        requested = stage
        statuses = _statuses(project_id)
        blocker = _blocker(statuses, requested)
        if blocker and statuses.get(blocker) == "awaiting_human":
            reply = (
                f"Para ejecutar `{requested}` falta aprobar el gate de `{blocker}`. "
                "Aprobalo en el board y decime de nuevo."
            )
        else:
            if blocker:
                stage = blocker
            try:
                job = await jobs.create(
                    conn,
                    project_id=project_id,
                    stage=stage,
                    scene_id=scene_id if stage == requested else None,
                    instruction=content.strip(),
                    model=model,
                    user_id=user_id,
                )
            except ApiError as exc:
                reply = f"No pude encolar `{stage}`: {exc.message}"
            else:
                if blocker:
                    reply = (
                        f"Para hacer `{requested}` primero falta `{blocker}`. "
                        f"Arranqué `{blocker}`; cuando termine seguimos (puede requerir un gate)."
                    )
                else:
                    reply = (
                        f"Entendido. Encolé el stage `{stage}`"
                        + (f" para `{scene_id}`" if scene_id else "")
                        + ". Te aviso cuando termine."
                    )
                actions = [
                    {"id": "undo", "type": "undo", "label": "Deshacer", "payload": {"job_id": job["id"]}, "enabled": True},
                    {"id": "cancel", "type": "retry", "label": "Cancelar job", "payload": {"job_id": job["id"]}, "enabled": True},
                ]
        if not reply:
            reply = "No pude procesar el pedido."
    else:
        reply = (
            "No hace falta un job para este mensaje. Puedo ejecutar stages del pipeline, "
            "regenerar una escena o revisar el board. ¿Qué querés hacer?"
        )
        actions = []

    assistant_id = db.new_id("msg")
    conn.execute(
        "INSERT INTO chat_messages(id, thread_id, role, content, model, job_id, actions_json, status, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (assistant_id, thread["id"], "assistant", reply, model, (job or {}).get("id"), json.dumps(actions), "complete", db.now()),
    )
    conn.commit()
    db.audit(conn, user_id, "chat.message", project_id, {"stage": stage, "job_id": (job or {}).get("id")})
    broker.publish(
        "chat.done",
        {"message_id": assistant_id, "actions": actions},
        project_id=project_id,
        job_id=(job or {}).get("id"),
    )
    message = _public(conn.execute("SELECT * FROM chat_messages WHERE id = ?", (assistant_id,)).fetchone())
    return {"message": message, "job": job}
