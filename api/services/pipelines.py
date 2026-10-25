"""Pipeline manifests: stages, gates and tool requirements."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from api import config
from api.errors import ApiError


@lru_cache(maxsize=1)
def _manifests() -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(config.PIPELINE_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        name = data.get("name") or path.stem
        manifests[name] = data
    return manifests


def all_pipelines() -> list[dict[str, Any]]:
    out = []
    for name, data in _manifests().items():
        stages = []
        for stage in data.get("stages", []):
            stages.append(
                {
                    "name": stage.get("name"),
                    "produces": stage.get("produces", []),
                    "gate": bool(stage.get("human_approval_default", False)),
                    "required_tools": stage.get("required_tools", []),
                    "optional_tools": stage.get("optional_tools", []),
                }
            )
        playbooks = (data.get("compatible_playbooks") or {}).get("recommended", [])
        out.append(
            {
                "name": name,
                "description": (data.get("description") or "").strip(),
                "category": data.get("category", ""),
                "stability": data.get("stability", "production"),
                "stages": stages,
                "playbooks": playbooks,
            }
        )
    return out


def get_pipeline(name: str) -> dict[str, Any]:
    data = _manifests().get(name)
    if data is None:
        raise ApiError(422, "unsupported_pipeline", f"Unknown pipeline {name!r}", {"pipeline": name})
    return data


def stage_names(name: str) -> list[str]:
    return [s.get("name") for s in get_pipeline(name).get("stages", []) if s.get("name")]


def stage_gate(name: str, stage: str) -> bool:
    for item in get_pipeline(name).get("stages", []):
        if item.get("name") == stage:
            return bool(item.get("human_approval_default", False))
    raise ApiError(422, "unsupported_stage", f"Stage {stage!r} is not part of pipeline {name!r}")


def stage_spec(name: str, stage: str) -> dict[str, Any]:
    for item in get_pipeline(name).get("stages", []):
        if item.get("name") == stage:
            return item
    raise ApiError(422, "unsupported_stage", f"Stage {stage!r} is not part of pipeline {name!r}")


def next_stage(name: str, stage: str) -> str | None:
    stages = stage_names(name)
    try:
        index = stages.index(stage)
    except ValueError:
        return None
    return stages[index + 1] if index + 1 < len(stages) else None
