"""HTTP surface for Cabina Studio API v1 (see docs/api-v1.md)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from api import config, db, schemas_io
from api.deps import COOKIE_NAME, AuthContext, current_auth, get_db, require_admin, require_producer, require_viewer
from api.errors import ApiError
from api.events import broker
from api.services import alerts, backups, board, chat, costs, gates, jobs, media, metrics, pipelines, projects, providers, remote_storage, scenes, settings, users
from api.services import chat as chat_service

router = APIRouter(prefix="/api")


# --- request models -------------------------------------------------------
class LoginBody(BaseModel):
    email: str
    password: str


class ProjectBody(BaseModel):
    title: str
    pipeline: str
    platform: str = "instagram_reels"
    brief: dict[str, Any] | None = None
    budget_usd: float | None = None
    slug: str | None = None


class JobBody(BaseModel):
    project_id: str
    stage: str | None = None
    scene_id: str | None = None
    instruction: str | None = None
    engine: str | None = None
    model: str | None = None
    budget_usd: float | None = None


class GateBody(BaseModel):
    note: str | None = None
    regenerate: bool = False


class ChatBody(BaseModel):
    content: str
    model: str | None = None
    scope: dict[str, Any] | None = None
    attachments: list[str] | None = None


class SceneBody(BaseModel):
    prompt: str | None = None
    instructions: str | None = None
    model: str | None = None


class UserCreateBody(BaseModel):
    email: str
    name: str | None = None
    role: str = "producer"
    password: str


class UserPatchBody(BaseModel):
    name: str | None = None
    role: str | None = None
    password: str | None = None


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class TokenBody(BaseModel):
    name: str = "token"
    user_id: str | None = None


class RetentionBody(BaseModel):
    dry_run: bool = True


class SceneOrderBody(BaseModel):
    order: list[str]


class UndoBody(BaseModel):
    target: dict[str, Any] | None = None
    reason: str | None = None


def _user_payload(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["id"], "email": user["email"], "name": user.get("name"), "role": user["role"]}


# --- health ---------------------------------------------------------------
@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        projects_count = sum(
            1 for p in config.PROJECTS_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
        ) if config.PROJECTS_DIR.is_dir() else 0
        active = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')").fetchone()["n"]
        current = conn.execute(
            "SELECT id FROM jobs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        db_ok = True
    except Exception:
        projects_count, active, current, db_ok = 0, 0, None, False
    usage = shutil.disk_usage(config.PROJECTS_DIR if config.PROJECTS_DIR.exists() else config.ROOT)
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0
    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - config.STARTED_AT, 1),
        "worker": {
            "status": "idle" if not active else "busy",
            "queue_depth": int(active),
            "current_job_id": current["id"] if current else None,
        },
        "storage": {
            "disk_free_gb": round(usage.free / 1024**3, 1),
            "disk_used_pct": used_pct,
            "disk_warning": used_pct >= config.DISK_WARN_PCT,
            "projects_count": projects_count,
        },
        "runtimes": {
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "remotion": (config.ROOT / "remotion-composer" / "node_modules").is_dir(),
            "hyperframes": bool(shutil.which("npx")),
        },
    }


# --- auth -----------------------------------------------------------------
@router.post("/auth/login")
def login(body: LoginBody, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    from api import security

    row = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
    if row is None or not security.verify_password(body.password, row["password_hash"]):
        raise ApiError(401, "unauthorized", "Invalid email or password")
    token, csrf, expires = security.create_session(conn, row["id"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=config.SESSION_HOURS * 3600,
    )
    return {"user": _user_payload(dict(row)), "csrf_token": csrf, "expires_at": expires}


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.post("/auth/password")
def change_password_route(
    body: PasswordBody,
    ctx: AuthContext = Depends(current_auth),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    users.change_password(conn, ctx.user["id"], body.current_password, body.new_password)
    return {"ok": True}


@router.get("/auth/me")
def me(ctx: AuthContext = Depends(current_auth)) -> dict[str, Any]:
    return {"user": _user_payload(ctx.user), "csrf_token": ctx.csrf}


# --- users / tokens / audit -----------------------------------------------
@router.get("/users")
def list_users(_: AuthContext = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return users.list_users(conn)


@router.post("/users", status_code=201)
def create_user(
    body: UserCreateBody,
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return users.create_user(
        conn,
        email=body.email,
        name=body.name,
        role=body.role,
        password=body.password,
        actor=ctx.user["id"],
    )


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserPatchBody,
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return users.update_user(conn, user_id, body.model_dump(exclude_none=True), ctx.user["id"])


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    users.delete_user(conn, user_id, ctx.user["id"])
    return Response(status_code=204)


@router.get("/tokens")
def list_tokens(_: AuthContext = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return users.list_tokens(conn)


@router.post("/tokens", status_code=201)
def create_token(
    body: TokenBody,
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return users.create_token(conn, body.user_id or ctx.user["id"], body.name, ctx.user["id"])


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(
    token_id: str,
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    users.delete_token(conn, token_id, ctx.user["id"])
    return Response(status_code=204)


@router.get("/audit")
def audit_log(
    limit: int = Query(100, ge=1, le=500),
    _: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return users.audit_log(conn, limit)


# --- backups / storage / retention (admin) --------------------------------
@router.post("/admin/backups", status_code=201)
def create_backup(
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return backups.create_backup(conn, ctx.user["id"])


@router.get("/admin/backups")
def list_backups(_: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    return backups.list_backups()


@router.get("/admin/backups/{name}")
def download_backup(name: str, _: AuthContext = Depends(require_admin)):
    local = backups.local_backup_path(name)
    if local is not None:
        return FileResponse(local, filename=name, media_type="application/gzip")
    if not remote_storage.enabled():
        raise ApiError(404, "not_found", "Backup not found")
    key = remote_storage.key_for(name)
    length = remote_storage.size(key)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if length:
        headers["Content-Length"] = str(length)
    return StreamingResponse(remote_storage.stream(key), media_type="application/gzip", headers=headers)


@router.post("/admin/backups/{name}/verify")
def verify_backup(name: str, _: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    return backups.verify_backup(name)


@router.get("/admin/storage")
def storage(_: AuthContext = Depends(require_admin)) -> dict[str, Any]:
    return backups.storage_stats()


@router.post("/admin/retention")
def retention(
    body: RetentionBody | None = None,
    _: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return backups.retention_report(conn, dry_run=(body.dry_run if body else True))


# --- observability -------------------------------------------------------
@router.get("/admin/metrics")
def admin_metrics(_: AuthContext = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return metrics.summary(conn)


@router.get("/metrics/prometheus")
def prometheus_metrics(_: AuthContext = Depends(require_viewer), conn: sqlite3.Connection = Depends(get_db)) -> PlainTextResponse:
    return PlainTextResponse(metrics.prometheus(conn), media_type="text/plain; version=0.0.4")


@router.post("/admin/alerts/test")
def test_alert(_: AuthContext = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return alerts.send(conn, "test", {"ok": True})


# --- providers / pipelines ------------------------------------------------
@router.get("/providers")
def provider_menu(_: AuthContext = Depends(require_viewer)) -> dict[str, Any]:
    return providers.menu()


@router.get("/pipelines")
def pipeline_list(_: AuthContext = Depends(require_viewer)) -> dict[str, Any]:
    return {"pipelines": pipelines.all_pipelines()}


# --- projects -------------------------------------------------------------
@router.get("/projects")
def list_projects(
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return projects.list_projects(conn, status=status, query=q, limit=limit, cursor=cursor)


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectBody,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return projects.create(
        conn,
        user_id=ctx.user["id"],
        title=body.title,
        pipeline=body.pipeline,
        platform=body.platform,
        brief=body.brief,
        budget_usd=body.budget_usd,
    )


@router.get("/projects/{slug}")
def get_project(
    slug: str,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return projects.get(conn, slug)


@router.delete("/projects/{slug}", status_code=204)
def archive_project(
    slug: str,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    projects.archive(conn, slug, ctx.user["id"])
    return Response(status_code=204)


@router.get("/projects/{slug}/board")
def project_board(
    slug: str,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return board.build(conn, slug)


@router.get("/projects/{slug}/artifacts/{name}")
def get_artifact(
    slug: str,
    name: str,
    raw: bool = False,
    _: AuthContext = Depends(require_viewer),
) -> Any:
    directory = projects.project_dir(slug)
    path = schemas_io.artifact_path(directory, name)
    if not path.is_file():
        raise ApiError(404, "artifact_not_found", f"Artifact {name!r} not found", {"artifact": name})
    data = schemas_io.read_json(path)
    if data is None:
        raise ApiError(422, "artifact_invalid", f"Artifact {name!r} is not valid JSON")
    if raw:
        return JSONResponse(content=data)
    try:
        schemas_io.validate_artifact(name, data)
        valid = True
    except ApiError:
        valid = False
    return {
        "name": name,
        "schema": name,
        "valid": valid,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


@router.get("/projects/{slug}/checkpoints")
def list_checkpoints(
    slug: str,
    _: AuthContext = Depends(require_viewer),
) -> dict[str, Any]:
    directory = projects.project_dir(slug)
    items = []
    for path in sorted(directory.glob("checkpoint_*.json")):
        data = schemas_io.read_json(path, {}) or {}
        history = directory / "history"
        count = len(list(history.glob(f"checkpoint_{data.get('stage')}_*.json"))) if history.is_dir() else 0
        items.append({**data, "history_entries": count})
    return {"data": items}


# --- gates ----------------------------------------------------------------
@router.post("/projects/{slug}/gates/{stage}/approve")
async def approve_gate(
    slug: str,
    stage: str,
    body: GateBody | None = None,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return await gates.approve(conn, slug, stage, note=(body.note if body else None), user_id=ctx.user["id"])


@router.post("/projects/{slug}/gates/{stage}/reject")
async def reject_gate(
    slug: str,
    stage: str,
    body: GateBody,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return await gates.reject(conn, slug, stage, note=(body.note or ""), user_id=ctx.user["id"])


# --- assets / renders / media --------------------------------------------
@router.get("/projects/{slug}/assets")
def project_assets(
    slug: str,
    scene_id: str | None = None,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    payload = media.assets(conn, slug)
    if scene_id:
        payload["assets"] = [a for a in payload["assets"] if a.get("scene_id") == scene_id]
    return payload


@router.get("/projects/{slug}/renders")
def project_renders(slug: str, _: AuthContext = Depends(require_viewer)) -> dict[str, Any]:
    return media.renders(slug)


@router.get("/projects/{slug}/media/{path:path}")
def serve_media(slug: str, path: str, _: AuthContext = Depends(require_viewer)) -> FileResponse:
    directory = projects.project_dir(slug)
    target = media.resolve_media(directory, path)
    return FileResponse(target)


@router.put("/projects/{slug}/scenes/order")
def reorder_scenes(
    slug: str,
    body: SceneOrderBody,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return scenes.reorder(conn, slug, body.order, ctx.user["id"])


@router.post("/projects/{slug}/scenes/{scene}/regenerate", status_code=202)
async def regenerate_scene(
    slug: str,
    scene: str,
    body: SceneBody | None = None,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    instruction = (body.instructions if body else None) or (body.prompt if body else None) or f"Regenerar {scene}"
    return await jobs.create(
        conn,
        project_id=slug,
        stage="assets",
        scene_id=scene,
        instruction=instruction,
        model=(body.model if body else None),
        user_id=ctx.user["id"],
    )


# --- undo -----------------------------------------------------------------
@router.post("/projects/{slug}/undo")
def undo(
    slug: str,
    body: UndoBody | None = None,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    directory = projects.project_dir(slug)
    current = {}
    for path in directory.glob("checkpoint_*.json"):
        current[path.stem.replace("checkpoint_", "")] = schemas_io.read_json(path, {}) or {}
    target = (body.target or {}) if body else {}
    stage = target.get("ref") if target.get("kind") == "checkpoint" else None
    if stage and current.get(stage, {}).get("human_approved"):
        raise ApiError(409, "cannot_undo_approved", "Cannot undo an approved stage")
    history = directory / "history"
    candidates = sorted(history.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if history.is_dir() else []
    if stage:
        candidates = [c for c in candidates if c.name.startswith(f"checkpoint_{stage}_")]
    if not candidates:
        raise ApiError(404, "not_found", "Nothing to undo")
    source = candidates[0]
    data = schemas_io.read_json(source, {}) or {}
    restored_stage = data.get("stage")
    if not restored_stage:
        raise ApiError(422, "artifact_invalid", "Archived checkpoint is missing its stage")
    if current.get(restored_stage, {}).get("human_approved"):
        raise ApiError(409, "cannot_undo_approved", "Cannot undo an approved stage")
    target_path = directory / f"checkpoint_{restored_stage}.json"
    target_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    db.audit(conn, ctx.user["id"], "undo", f"{slug}:{restored_stage}", {"source": source.name})
    broker.publish("undo", {"kind": "checkpoint", "ref": restored_stage, "restored_from": source.name}, project_id=slug)
    return {
        "undone": {
            "kind": "checkpoint",
            "ref": restored_stage,
            "restored_from": source.name,
            "created_at": data.get("timestamp") or db.now(),
        },
        "audit_id": db.new_id("aud"),
    }


# --- jobs -----------------------------------------------------------------
@router.get("/jobs")
def list_jobs(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return jobs.list_jobs(conn, project_id=project_id, status=status, limit=limit)


@router.post("/jobs", status_code=202)
async def create_job(
    body: JobBody,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return await jobs.create(
        conn,
        project_id=body.project_id,
        stage=body.stage,
        scene_id=body.scene_id,
        instruction=body.instruction,
        engine=body.engine,
        model=body.model,
        budget_usd=body.budget_usd,
        user_id=ctx.user["id"],
    )


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return jobs.get(conn, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return jobs.cancel(conn, job_id, ctx.user["id"])


@router.get("/jobs/{job_id}/log")
def job_log(
    job_id: str,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    jobs.get(conn, job_id)
    rows = conn.execute(
        "SELECT seq, type, payload_json, created_at FROM job_events WHERE job_id = ? ORDER BY seq",
        (job_id,),
    ).fetchall()
    data = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        data.append({"seq": row["seq"], "type": row["type"], "payload": payload, "created_at": row["created_at"]})
    return {"data": data}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> StreamingResponse:
    jobs.get(conn, job_id)
    since = request.headers.get("last-event-id")
    return StreamingResponse(
        broker.stream(since=since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events")
async def global_events(
    request: Request,
    project: str | None = None,
    _: AuthContext = Depends(require_viewer),
) -> StreamingResponse:
    since = request.headers.get("last-event-id")
    return StreamingResponse(
        broker.stream(since=since, project=project),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- chat -----------------------------------------------------------------
@router.get("/projects/{slug}/chat")
def chat_history(
    slug: str,
    limit: int = Query(20, ge=1, le=100),
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return chat.history(conn, slug, limit)


@router.post("/projects/{slug}/chat", status_code=202)
async def post_chat(
    slug: str,
    body: ChatBody,
    ctx: AuthContext = Depends(require_producer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return await chat_service.post(
        conn,
        slug,
        content=body.content,
        model=body.model,
        scope=body.scope,
        user_id=ctx.user["id"],
    )


@router.get("/projects/{slug}/chat/stream")
async def chat_stream(
    slug: str,
    request: Request,
    since: str | None = None,
    _: AuthContext = Depends(require_producer),
) -> StreamingResponse:
    since = since or request.headers.get("last-event-id")
    return StreamingResponse(
        broker.stream(since=since, project=slug),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- settings / costs -----------------------------------------------------
@router.get("/settings")
def get_settings(
    _: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return settings.read(conn)


@router.put("/settings")
def put_settings(
    body: dict[str, Any],
    ctx: AuthContext = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return settings.update(conn, body, ctx.user["id"])


@router.get("/costs")
def get_costs(
    project_id: str | None = None,
    _: AuthContext = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return costs.summary(conn, project_id)
