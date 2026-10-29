"""Backups, restore verification, retention and storage stats (F7)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api import config, db
from api.errors import ApiError
from api.services import remote_storage

NAME_RE = r"cabina-[0-9]{8}-[0-9]{6}\.tar\.gz"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_snapshot(destination: Path) -> None:
    source = sqlite3.connect(config.DB_PATH)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _projects_list() -> list[str]:
    if not config.PROJECTS_DIR.is_dir():
        return []
    return sorted(
        path.name for path in config.PROJECTS_DIR.iterdir() if path.is_dir() and not path.name.startswith(("_", "."))
    )


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def create_backup(conn: sqlite3.Connection, actor: str | None, note: str | None = None) -> dict[str, Any]:
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    name = f"cabina-{_stamp()}.tar.gz"
    path = config.BACKUPS_DIR / name
    projects = _projects_list()
    with tempfile.TemporaryDirectory(prefix="cabina-backup-") as tmp:
        root = Path(tmp)
        snapshot = root / "cabina.db"
        _db_snapshot(snapshot)
        manifest = {
            "version": "1.0",
            "created_at": created_at.isoformat(),
            "app_version": "1.0.0",
            "projects": projects,
            "project_count": len(projects),
            "db_bytes": snapshot.stat().st_size,
            "note": note,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with tarfile.open(path, "w:gz") as archive:
            if config.PROJECTS_DIR.is_dir():
                archive.add(config.PROJECTS_DIR, arcname="projects")
            music = config.DATA_DIR / "music_library"
            if music.is_dir():
                archive.add(music, arcname="music_library")
            if config.BACKUP_INCLUDE_VOICES:
                voices = config.DATA_DIR / "piper"
                if voices.is_dir():
                    archive.add(voices, arcname="piper")
            archive.add(snapshot, arcname="db/cabina.db")
            if config.SECRET_FILE.is_file():
                archive.add(config.SECRET_FILE, arcname="db/secret.key")
            archive.add(root / "manifest.json", arcname="manifest.json")
    size = path.stat().st_size
    meta = {
        "name": name,
        "size": size,
        "sha256": _sha256(path),
        "created_at": created_at.isoformat(),
        "project_count": len(projects),
        "note": note,
    }
    meta_path = config.BACKUPS_DIR / f"{name}.json"
    if remote_storage.enabled():
        try:
            remote_storage.upload(path, remote_storage.key_for(name))
            meta["remote"] = True
            meta["remote_key"] = remote_storage.key_for(name)
        except Exception as exc:  # local backup stays valid
            meta["remote"] = False
            meta["remote_error"] = str(exc)[:300]
            db.audit(conn, actor, "backup.remote_failed", name, {"error": str(exc)[:300]})
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if remote_storage.enabled() and meta.get("remote"):
        try:
            remote_storage.upload(meta_path, remote_storage.key_for(f"{name}.json"), "application/json")
        except Exception:
            pass
    db.audit(conn, actor, "backup.created", name, {"size": size, "projects": len(projects), "remote": bool(meta.get("remote"))})
    _prune_backups(conn, actor)
    return meta


def _meta_path(name: str) -> Path:
    if not name.startswith("cabina-") or not name.endswith(".tar.gz"):
        raise ApiError(400, "invalid_request", "Invalid backup name")
    return config.BACKUPS_DIR / f"{name}.json"


def _backup_path(name: str) -> Path:
    _meta_path(name)
    path = (config.BACKUPS_DIR / name).resolve()
    if config.BACKUPS_DIR.resolve() not in path.parents:
        raise ApiError(403, "path_escapes_project", "Invalid backup path")
    if not path.is_file():
        raise ApiError(404, "not_found", "Backup not found")
    return path


def local_backup_path(name: str) -> Path | None:
    _meta_path(name)
    path = (config.BACKUPS_DIR / name).resolve()
    if config.BACKUPS_DIR.resolve() not in path.parents:
        raise ApiError(403, "path_escapes_project", "Invalid backup path")
    return path if path.is_file() else None


def list_backups() -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    if config.BACKUPS_DIR.is_dir():
        for meta_path in sorted(config.BACKUPS_DIR.glob("*.tar.gz.json"), reverse=True):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta["local"] = (config.BACKUPS_DIR / meta["name"]).is_file()
            items[meta["name"]] = meta
    remote_error = None
    if remote_storage.enabled():
        try:
            keys = remote_storage.list_keys(remote_storage.key_for(""))
            for item in keys:
                key = item["key"]
                if not key.endswith(".tar.gz"):
                    continue
                name = key.rsplit("/", 1)[-1]
                if name in items:
                    items[name]["remote"] = True
                    continue
                meta = remote_storage.get_json(remote_storage.key_for(f"{name}.json")) or {}
                meta.update({"name": name, "size": item["size"], "created_at": meta.get("created_at") or item["last_modified"], "remote": True, "local": False})
                items[name] = meta
        except Exception as exc:
            remote_error = str(exc)[:300]
    ordered = sorted(items.values(), key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "data": ordered,
        "backups_dir": str(config.BACKUPS_DIR),
        "remote_enabled": remote_storage.enabled(),
        "remote_bucket": config.S3_BUCKET or None,
        "remote_endpoint": config.S3_ENDPOINT or None,
        "remote_error": remote_error,
    }


def verify_backup(name: str) -> dict[str, Any]:
    _meta_path(name)
    report: dict[str, Any] = {"name": name, "valid": True, "checks": []}
    with tempfile.TemporaryDirectory(prefix="cabina-restore-") as tmp:
        target = Path(tmp)
        path = local_backup_path(name)
        if path is None:
            if not remote_storage.enabled():
                raise ApiError(404, "not_found", "Backup not found")
            path = target / name
            remote_storage.download(remote_storage.key_for(name), path)
            report["source"] = "remote"
        else:
            report["source"] = "local"
        with tarfile.open(path, "r:gz") as archive:
            archive.extractall(target, filter="data")
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file():
            raise ApiError(422, "artifact_invalid", "Backup has no manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report["manifest"] = manifest
        report["checks"].append({"name": "manifest", "ok": True})

        restored_db = target / "db" / "cabina.db"
        if restored_db.is_file():
            conn = sqlite3.connect(restored_db)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            ok = integrity == "ok"
            report["checks"].append({"name": "sqlite_integrity", "ok": ok, "detail": integrity})
            report["valid"] = report["valid"] and ok
            report["tables"] = sorted(tables)
        else:
            report["checks"].append({"name": "sqlite_integrity", "ok": False, "detail": "db missing"})
            report["valid"] = False

        projects_dir = target / "projects"
        projects = []
        if projects_dir.is_dir():
            for project in sorted(projects_dir.iterdir()):
                if not project.is_dir() or project.name.startswith(("_", ".")):
                    continue
                marker = project / "project.json"
                if not marker.is_file():
                    report["valid"] = False
                    report["checks"].append({"name": f"project:{project.name}", "ok": False, "detail": "missing project.json"})
                    continue
                try:
                    json.loads(marker.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    report["valid"] = False
                    report["checks"].append({"name": f"project:{project.name}", "ok": False, "detail": "invalid project.json"})
                    continue
                checkpoints = list(project.glob("checkpoint_*.json"))
                projects.append({"slug": project.name, "checkpoints": len(checkpoints)})
        report["projects"] = projects
        report["checks"].append({"name": "projects", "ok": bool(projects), "count": len(projects)})
    audit_conn = db.connect()
    try:
        db.audit(audit_conn, None, "backup.verified", name, {"valid": report["valid"]})
    finally:
        audit_conn.close()
    return report


def _prune_backups(conn: sqlite3.Connection, actor: str | None) -> None:
    remote = remote_storage.enabled()
    metas = sorted(config.BACKUPS_DIR.glob("*.tar.gz.json"), reverse=True)
    keep = max(1, config.BACKUP_LOCAL_KEEP if remote else config.BACKUP_KEEP)
    for meta_path in metas[keep:]:
        name = meta_path.name.removesuffix(".json")
        try:
            if remote:
                # Never drop the only local copy until the remote object exists.
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if not meta.get("remote"):
                    continue
            meta_path.unlink(missing_ok=True)
            (config.BACKUPS_DIR / name).unlink(missing_ok=True)
            db.audit(conn, actor, "backup.pruned", name, {"scope": "local"})
        except OSError:
            continue
    if remote:
        try:
            keys = remote_storage.list_keys(remote_storage.key_for(""))
            names = sorted({item["key"].rsplit("/", 1)[-1] for item in keys if item["key"].endswith(".tar.gz")}, reverse=True)
            for name in names[max(1, config.BACKUP_REMOTE_KEEP):]:
                remote_storage.delete(remote_storage.key_for(name))
                remote_storage.delete(remote_storage.key_for(f"{name}.json"))
                db.audit(conn, actor, "backup.pruned", name, {"scope": "remote"})
        except Exception:
            pass


def storage_stats() -> dict[str, Any]:
    usage = shutil.disk_usage(config.DATA_DIR if config.DATA_DIR.exists() else config.ROOT)
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0
    projects = _projects_list()
    return {
        "disk_total_gb": round(usage.total / 1024**3, 1),
        "disk_used_gb": round(usage.used / 1024**3, 1),
        "disk_free_gb": round(usage.free / 1024**3, 1),
        "disk_used_pct": used_pct,
        "disk_warning": used_pct >= config.DISK_WARN_PCT,
        "projects_count": len(projects),
        "projects_bytes": _dir_size(config.PROJECTS_DIR),
        "backups_bytes": _dir_size(config.BACKUPS_DIR),
        "backups_count": len(list(config.BACKUPS_DIR.glob("*.tar.gz"))) if config.BACKUPS_DIR.is_dir() else 0,
        "backups_dir": str(config.BACKUPS_DIR),
        "remote_enabled": remote_storage.enabled(),
        "remote_bucket": config.S3_BUCKET or None,
        "remote_endpoint": config.S3_ENDPOINT or None,
    }


def retention_report(conn: sqlite3.Connection, dry_run: bool = True) -> dict[str, Any]:
    settings = db.get_setting(conn, "retention", {"projects_days": 90, "renders_days": 30}) or {}
    renders_days = int(settings.get("renders_days") or 30)
    cutoff = time.time() - renders_days * 86400
    candidates = []
    freed = 0
    if config.PROJECTS_DIR.is_dir():
        for render in config.PROJECTS_DIR.glob("*/renders/*.mp4"):
            try:
                stat = render.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                candidates.append({"path": str(render.relative_to(config.PROJECTS_DIR)), "bytes": stat.st_size})
                freed += stat.st_size
                if not dry_run:
                    try:
                        render.unlink()
                    except OSError:
                        continue
    db.audit(conn, None, "retention.run" if not dry_run else "retention.preview", "renders", {"count": len(candidates), "bytes": freed})
    return {
        "dry_run": dry_run,
        "renders_days": renders_days,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "freed_bytes": freed,
    }


async def backup_scheduler() -> None:
    """Daily in-app backup (settings.backup), safe to run alongside the API."""
    while True:
        try:
            conn = db.connect()
            try:
                settings = db.get_setting(conn, "backup", {"enabled": True, "hour": 3, "keep": config.BACKUP_KEEP}) or {}
                now = datetime.now(timezone.utc)
                enabled = bool(settings.get("enabled", True))
                hour = int(settings.get("hour", 3))
                today = now.strftime("%Y%m%d")
                existing = list(config.BACKUPS_DIR.glob(f"cabina-{today}-*.tar.gz")) if config.BACKUPS_DIR.is_dir() else []
                if enabled and now.hour == hour and not existing:
                    create_backup(conn, "scheduler", "daily")
            finally:
                conn.close()
        except Exception:
            pass
        await asyncio.sleep(600)
