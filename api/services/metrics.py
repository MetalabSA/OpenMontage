"""Operational metrics for the ops screen and Prometheus scraping."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from api import config, db
from api.services import backups, projects
from api.telemetry import http_stats


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = [dict(row) for row in conn.execute("SELECT * FROM jobs")]
    by_status = Counter(row["status"] for row in rows)
    by_stage: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "duration_seconds": 0.0, "cost_usd": 0.0})
    by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "cost_usd": 0.0})
    total_cost = 0.0
    today = datetime.now(timezone.utc).date()
    today_cost = 0.0
    for row in rows:
        stage = row.get("stage") or "project"
        model = row.get("model") or "—"
        cost = float(row.get("cost_usd") or 0)
        total_cost += cost
        bucket = by_stage[stage]
        bucket["count"] += 1
        bucket["cost_usd"] += cost
        by_model[model]["count"] += 1
        by_model[model]["cost_usd"] += cost
        start, end = _dt(row.get("started_at")), _dt(row.get("finished_at"))
        if start and end:
            bucket["duration_seconds"] += max(0.0, (end - start).total_seconds())
        finished = _dt(row.get("finished_at"))
        if finished and finished.date() == today:
            today_cost += cost
    finished = by_status.get("succeeded", 0) + by_status.get("failed", 0) + by_status.get("cancelled", 0)
    success_rate = (by_status.get("succeeded", 0) / finished * 100) if finished else 0.0
    stages = []
    for stage, bucket in sorted(by_stage.items()):
        count = bucket["count"] or 1
        stages.append(
            {
                "stage": stage,
                "jobs": bucket["count"],
                "avg_duration_seconds": round(bucket["duration_seconds"] / count, 1),
                "cost_usd": round(bucket["cost_usd"], 4),
            }
        )
    storage = backups.storage_stats()
    active = by_status.get("queued", 0) + by_status.get("running", 0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": {
            "total": len(rows),
            "by_status": dict(by_status),
            "success_rate_pct": round(success_rate, 1),
            "active": active,
            "awaiting_human": by_status.get("awaiting_human", 0),
            "by_stage": stages,
            "by_model": [
                {"model": model, "jobs": data["count"], "cost_usd": round(data["cost_usd"], 4)}
                for model, data in sorted(by_model.items())
            ],
        },
        "cost": {"total_usd": round(total_cost, 4), "today_usd": round(today_cost, 4)},
        "projects": {"count": len(projects.list_projects(conn)["data"])},
        "storage": storage,
        "http": http_stats.snapshot(),
        "engine": {
            "mode": config.AGENT_MODE,
            "provider": config.ENGINE_PROVIDER,
            "model": config.ENGINE_MODEL,
        },
    }


def prometheus(conn: sqlite3.Connection) -> str:
    data = summary(conn)
    lines: list[str] = []
    lines.append("# HELP cabina_jobs_total Jobs by status")
    lines.append("# TYPE cabina_jobs_total gauge")
    for status, count in data["jobs"]["by_status"].items():
        lines.append(f'cabina_jobs_total{{status="{status}"}} {count}')
    lines.append("# HELP cabina_jobs_by_stage Jobs by stage")
    lines.append("# TYPE cabina_jobs_by_stage gauge")
    for stage in data["jobs"]["by_stage"]:
        lines.append(f'cabina_jobs_by_stage{{stage="{stage["stage"]}"}} {stage["jobs"]}')
        lines.append(f'cabina_job_duration_seconds_avg{{stage="{stage["stage"]}"}} {stage["avg_duration_seconds"]}')
    lines.append("# HELP cabina_cost_usd_total Total LLM/generation cost")
    lines.append("# TYPE cabina_cost_usd_total counter")
    lines.append(f'cabina_cost_usd_total {data["cost"]["total_usd"]}')
    lines.append("# HELP cabina_queue_depth Active jobs")
    lines.append("# TYPE cabina_queue_depth gauge")
    lines.append(f'cabina_queue_depth {data["jobs"]["active"]}')
    lines.append("# HELP cabina_projects_total Projects")
    lines.append("# TYPE cabina_projects_total gauge")
    lines.append(f'cabina_projects_total {data["projects"]["count"]}')
    lines.append("# HELP cabina_disk_used_pct Disk used percent")
    lines.append("# TYPE cabina_disk_used_pct gauge")
    lines.append(f'cabina_disk_used_pct {data["storage"]["disk_used_pct"]}')
    lines.append("# HELP cabina_http_requests_total HTTP requests served")
    lines.append("# TYPE cabina_http_requests_total counter")
    lines.append(f'cabina_http_requests_total {data["http"]["total"]}')
    return "\n".join(lines) + "\n"
