"""Artifact schema loading, validation and filesystem helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from api import config
from api.errors import ApiError


@lru_cache(maxsize=1)
def _schema_files() -> dict[str, Path]:
    return {
        path.name.replace(".schema.json", ""): path
        for path in sorted(config.SCHEMA_DIR.glob("*.schema.json"))
    }


@lru_cache(maxsize=64)
def _schema(name: str) -> dict[str, Any]:
    path = _schema_files().get(name)
    if path is None:
        raise ApiError(422, "unsupported_artifact", f"No schema registered for artifact {name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def schema_names() -> list[str]:
    return sorted(_schema_files())


def validate_artifact(name: str, data: Any) -> None:
    validator = Draft202012Validator(_schema(name))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.path) or "<root>"
        raise ApiError(
            422,
            "artifact_invalid",
            f"Artifact {name!r} failed schema validation: {first.message}",
            {"artifact": name, "path": where, "errors": [e.message for e in errors[:8]]},
        )


def artifact_path(project_dir: Path, name: str) -> Path:
    return project_dir / "artifacts" / f"{name}.json"


def read_artifact(project_dir: Path, name: str) -> dict[str, Any]:
    path = artifact_path(project_dir, name)
    if not path.is_file():
        raise ApiError(404, "artifact_not_found", f"Artifact {name!r} not found", {"artifact": name})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(422, "artifact_invalid", f"Artifact {name!r} is not valid JSON", {"error": str(exc)})


def write_artifact(project_dir: Path, name: str, data: dict[str, Any]) -> Path:
    validate_artifact(name, data)
    path = artifact_path(project_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def artifact_summaries(project_dir: Path) -> list[dict[str, Any]]:
    artifacts_dir = project_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.glob("*.json")):
        name = path.stem
        entry: dict[str, Any] = {
            "name": name,
            "schema": name,
            "valid": True,
            "updated_at": None,
            "size_bytes": path.stat().st_size,
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_artifact(name, data)
        except ApiError:
            entry["valid"] = False
        except json.JSONDecodeError:
            entry["valid"] = False
        summaries.append(entry)
    return summaries


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
