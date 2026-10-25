"""Shared fixtures: isolated projects dir, DB and an authenticated client."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_BASE = Path(tempfile.mkdtemp(prefix="cabina-api-"))
os.environ["OM_PROJECTS_DIR"] = str(_BASE / "projects")
os.environ["OM_DB_PATH"] = str(_BASE / "db" / "cabina.db")
os.environ["OM_SECRET_FILE"] = str(_BASE / "db" / "secret.key")
os.environ["OM_API_TOKEN"] = "test-token"
os.environ["OM_ADMIN_EMAIL"] = "admin@test.local"
os.environ["OM_ADMIN_PASSWORD"] = "secret123"
os.environ["OM_SIM_SPEED"] = "0.1"

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


def minimal(schema: dict) -> object:
    if "$ref" in schema:
        raise RuntimeError("unresolved $ref in minimal()")
    if "oneOf" in schema:
        return minimal(schema["oneOf"][0])
    if "anyOf" in schema:
        return minimal(schema["anyOf"][0])
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = [k for k in kind if k != "null"][0]
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {key: minimal(props[key]) for key in schema.get("required", []) if key in props}
    if kind == "array":
        items = schema.get("items", {})
        return [minimal(items) for _ in range(schema.get("minItems", 0))]
    if kind == "string":
        fmt = schema.get("format")
        value = {"uri": "https://example.com/x", "date": "2026-01-01", "date-time": "2026-01-01T00:00:00Z"}.get(
            fmt, "x" * max(1, schema.get("minLength", 1))
        )
        return value
    if kind in {"number", "integer"}:
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    return None


def artifact(name: str) -> dict:
    schema = json.loads((ROOT / "schemas" / "artifacts" / f"{name}.schema.json").read_text())
    return minimal(schema)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def project(client, auth) -> dict:
    import uuid

    response = client.post(
        "/api/projects",
        json={"title": f"Demo Reel {uuid.uuid4().hex[:6]}", "pipeline": "animated-explainer", "platform": "instagram_reels"},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_gate(slug: str, stage: str = "proposal") -> None:
    """Create research (completed) + a gated stage awaiting approval."""
    from api import config
    from lib.checkpoint import write_checkpoint

    research = artifact("research_brief")
    write_checkpoint(
        config.PROJECTS_DIR,
        slug,
        "research",
        "completed",
        {"research_brief": research},
        pipeline_type="animated-explainer",
        human_approved=False,
    )
    payload = artifact("proposal_packet")
    write_checkpoint(
        config.PROJECTS_DIR,
        slug,
        stage,
        "awaiting_human",
        {"proposal_packet": payload},
        pipeline_type="animated-explainer",
        human_approval_required=True,
        human_approved=False,
    )
