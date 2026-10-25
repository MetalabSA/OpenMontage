"""Cost aggregation from jobs and project artifacts."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from api import config, schemas_io
from api.services import projects


def summary(conn: sqlite3.Connection, project_id: str | None = None) -> dict[str, Any]:
    jobs_query = "SELECT project_id, cost_usd, finished_at FROM jobs"
    params: tuple = ()
    if project_id:
        jobs_query += " WHERE project_id = ?"
        params = (project_id,)
    by_project: dict[str, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)
    total = 0.0
    for row in conn.execute(jobs_query, params):
        cost = float(row["cost_usd"] or 0)
        total += cost
        by_project[row["project_id"]] += cost
        day = (row["finished_at"] or "")[:10]
        if day:
            by_day[day] += cost

    by_provider: dict[str, float] = defaultdict(float)
    if project_id:
        slugs = [project_id]
    else:
        slugs = [p.name for p in config.PROJECTS_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))]
    for slug in slugs:
        directory = config.PROJECTS_DIR / slug
        for checkpoint in directory.glob("checkpoint_*.json"):
            data = schemas_io.read_json(checkpoint, {}) or {}
            snapshot = data.get("cost_snapshot") or {}
            try:
                value = float(snapshot.get("spent_usd") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value:
                total += value
                by_project[slug] += value
                by_day[(data.get("timestamp") or "")[:10]] += value
        cost_log = schemas_io.read_json(directory / "artifacts" / "cost_log.json", {}) or {}
        for entry in cost_log.get("entries", []):
            if not isinstance(entry, dict):
                continue
            try:
                value = float(entry.get("actual_usd") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value:
                by_provider[entry.get("tool") or "unknown"] += value

    budget = float(db_budget(conn))
    return {
        "total_usd": round(total, 4),
        "budget_usd": budget,
        "remaining_usd": round(max(0.0, budget - total), 4),
        "by_project": [{"project_id": k, "cost_usd": round(v, 4)} for k, v in sorted(by_project.items())],
        "by_provider": [{"provider": k, "cost_usd": round(v, 4)} for k, v in sorted(by_provider.items())],
        "by_day": [{"date": k, "cost_usd": round(v, 4)} for k, v in sorted(by_day.items()) if k],
    }


def db_budget(conn: sqlite3.Connection) -> float:
    from api import db

    stored = db.get_setting(conn, "budget", {}) or {}
    try:
        return float(stored.get("total_usd") or config.DEFAULT_BUDGET_USD)
    except (TypeError, ValueError):
        return config.DEFAULT_BUDGET_USD
