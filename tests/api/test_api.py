"""F3 integration tests for the Cabina Studio API."""

from __future__ import annotations

import time

from conftest import artifact, seed_gate


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "runtimes" in body


def test_auth_required(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_create_and_list_projects(client, auth):
    created = client.post(
        "/api/projects",
        json={"title": "Reel de Prueba", "pipeline": "animated-explainer"},
        headers=auth,
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["slug"] == "reel-de-prueba"
    assert project["status"] == "draft"
    assert project["prod_no"] >= 1

    listing = client.get("/api/projects", headers=auth)
    assert listing.status_code == 200
    assert any(item["slug"] == project["slug"] for item in listing.json()["data"])


def test_duplicate_slug_conflict(client, auth):
    body = {"title": "Duplicado", "pipeline": "animated-explainer"}
    assert client.post("/api/projects", json=body, headers=auth).status_code == 201
    assert client.post("/api/projects", json=body, headers=auth).status_code == 409


def test_board_and_brief_artifact(client, auth, project):
    board = client.get(f"/api/projects/{project['slug']}/board", headers=auth)
    assert board.status_code == 200
    body = board.json()
    assert body["project"]["slug"] == project["slug"]
    assert [stage["name"] for stage in body["stages"]][:2] == ["research", "proposal"]
    assert any(item["name"] == "brief" for item in body["artifacts"])

    artifact_response = client.get(f"/api/projects/{project['slug']}/artifacts/brief", headers=auth)
    assert artifact_response.status_code == 200
    assert artifact_response.json()["valid"] is True


def test_unknown_project_404(client, auth):
    assert client.get("/api/projects/nope/board", headers=auth).status_code == 404


def test_gate_approve_writes_checkpoint_and_queues_next(client, auth, project):
    seed_gate(project["slug"], "proposal")
    response = client.post(
        f"/api/projects/{project['slug']}/gates/proposal/approve",
        json={"note": "ok"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["checkpoint"]["status"] == "completed"
    assert body["checkpoint"]["human_approved"] is True
    assert body["job"]["stage"] == "script"


def test_gate_cannot_be_skipped(client, auth, project):
    seed_gate(project["slug"], "proposal")
    # Approving a stage that is completed (not awaiting) must fail.
    first = client.post(f"/api/projects/{project['slug']}/gates/proposal/approve", json={}, headers=auth)
    assert first.status_code == 200
    second = client.post(f"/api/projects/{project['slug']}/gates/proposal/approve", json={}, headers=auth)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "gate_not_pending"


def test_gate_reject_requires_note(client, auth, project):
    seed_gate(project["slug"], "proposal")
    missing = client.post(f"/api/projects/{project['slug']}/gates/proposal/reject", json={}, headers=auth)
    assert missing.status_code == 422
    rejected = client.post(
        f"/api/projects/{project['slug']}/gates/proposal/reject",
        json={"note": "Cambiar el enfoque"},
        headers=auth,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["job"]["stage"] == "proposal"


def test_job_lifecycle(client, auth, project):
    created = client.post(
        "/api/jobs",
        json={"project_id": project["slug"], "stage": "research"},
        headers=auth,
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    deadline = time.time() + 5
    status = "queued"
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        status = job["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert status == "succeeded", status


def test_only_one_active_job_per_project(client, auth, project):
    first = client.post("/api/jobs", json={"project_id": project["slug"], "stage": "research"}, headers=auth)
    assert first.status_code == 202
    second = client.post("/api/jobs", json={"project_id": project["slug"], "stage": "script"}, headers=auth)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "job_already_running"


def test_chat_routes_intent_to_job(client, auth, project):
    response = client.post(
        f"/api/projects/{project['slug']}/chat",
        json={"content": "Hacé el guion con tono cálido"},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["job"]["stage"] == "script"
    assert body["message"]["role"] == "assistant"
    assert any(action["type"] == "undo" for action in body["message"]["actions"])

    history = client.get(f"/api/projects/{project['slug']}/chat", headers=auth)
    assert len(history.json()["data"]) == 2


def test_settings_mask_secrets(client, auth):
    response = client.get("/api/settings", headers=auth)
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers and all("key_preview" in item for item in providers)
    updated = client.put(
        "/api/settings",
        json={"engine": {"default_map": {"script": "deepseek-v4-pro"}}},
        headers=auth,
    )
    assert updated.status_code == 200
    assert updated.json()["engine"]["default_map"]["script"] == "deepseek-v4-pro"


def test_costs_endpoint(client, auth, project):
    response = client.get("/api/costs", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"total_usd", "budget_usd", "remaining_usd", "by_project"}


def test_media_path_traversal_is_blocked(client, auth, project):
    response = client.get(f"/api/projects/{project['slug']}/media/../../etc/passwd", headers=auth)
    assert response.status_code in {403, 404}


def test_undo_without_history_404(client, auth, project):
    response = client.post(f"/api/projects/{project['slug']}/undo", json={}, headers=auth)
    assert response.status_code == 404


def test_unknown_artifact_404(client, auth, project):
    response = client.get(f"/api/projects/{project['slug']}/artifacts/scene_plan", headers=auth)
    assert response.status_code == 404


def test_pipelines_and_providers(client, auth):
    pipelines = client.get("/api/pipelines", headers=auth)
    assert pipelines.status_code == 200
    names = {item["name"] for item in pipelines.json()["pipelines"]}
    assert "animated-explainer" in names and "animation" in names
    providers = client.get("/api/providers", headers=auth)
    assert providers.status_code == 200
    assert "composition_runtimes" in providers.json()


def test_pipeline_runs_until_gate_then_waits(client, auth):
    import uuid

    created = client.post(
        "/api/projects",
        json={"title": f"Pipeline {uuid.uuid4().hex[:6]}", "pipeline": "animated-explainer"},
        headers=auth,
    )
    assert created.status_code == 201
    slug = created.json()["slug"]
    job = client.post("/api/jobs", json={"project_id": slug, "stage": "research"}, headers=auth)
    assert job.status_code == 202

    deadline = time.time() + 15
    status = None
    board = {}
    while time.time() < deadline:
        board = client.get(f"/api/projects/{slug}/board", headers=auth).json()
        status = board["project"]["status"]
        if status == "awaiting_human":
            break
        time.sleep(0.1)
    assert status == "awaiting_human"
    gates = [g for g in board["gates"] if g["status"] == "pending"]
    assert gates and gates[0]["stage"] == "proposal"

    checkpoints = client.get(f"/api/projects/{slug}/checkpoints", headers=auth).json()["data"]
    proposal = next(item for item in checkpoints if item["stage"] == "proposal")
    assert proposal["status"] == "awaiting_human"
    assert proposal["human_approved"] is False

    approved = client.post(f"/api/projects/{slug}/gates/proposal/approve", json={}, headers=auth)
    assert approved.status_code == 200, approved.text
    assert approved.json()["job"]["stage"] == "script"

    deadline = time.time() + 15
    script = []
    while time.time() < deadline:
        checkpoints = client.get(f"/api/projects/{slug}/checkpoints", headers=auth).json()["data"]
        script = [item for item in checkpoints if item["stage"] == "script"]
        if script and script[0]["status"] == "awaiting_human":
            break
        time.sleep(0.1)
    assert script and script[0]["status"] == "awaiting_human"


def test_reorder_scenes_and_job_log(client, auth):
    import uuid

    from api import config
    from lib.checkpoint import write_checkpoint

    created = client.post(
        "/api/projects",
        json={"title": f"Escenas {uuid.uuid4().hex[:6]}", "pipeline": "animated-explainer"},
        headers=auth,
    )
    slug = created.json()["slug"]
    from conftest import artifact

    write_checkpoint(config.PROJECTS_DIR, slug, "research", "completed", {"research_brief": artifact("research_brief")}, pipeline_type="animated-explainer")
    write_checkpoint(config.PROJECTS_DIR, slug, "proposal", "completed", {"proposal_packet": artifact("proposal_packet")}, pipeline_type="animated-explainer", human_approved=True)
    write_checkpoint(config.PROJECTS_DIR, slug, "script", "completed", {"script": artifact("script")}, pipeline_type="animated-explainer", human_approved=True)
    plan = artifact("scene_plan")
    plan["scenes"] = [
        {"id": f"sc_{index:02d}", "type": "animation", "description": f"Escena {index}", "start_seconds": index - 1, "end_seconds": index}
        for index in (1, 2, 3)
    ]
    write_checkpoint(config.PROJECTS_DIR, slug, "scene_plan", "awaiting_human", {"scene_plan": plan}, pipeline_type="animated-explainer", human_approval_required=True, human_approved=False)

    reordered = client.put(
        f"/api/projects/{slug}/scenes/order",
        json={"order": ["sc_03", "sc_01", "sc_02"]},
        headers=auth,
    )
    assert reordered.status_code == 200, reordered.text
    assert [scene["id"] for scene in reordered.json()["scenes"]] == ["sc_03", "sc_01", "sc_02"]

    board = client.get(f"/api/projects/{slug}/board", headers=auth).json()
    assert [scene["id"] for scene in board["scenes"]] == ["sc_03", "sc_01", "sc_02"]

    job = client.post("/api/jobs", json={"project_id": slug, "stage": "assets"}, headers=auth)
    assert job.status_code == 202
    log = client.get(f"/api/jobs/{job.json()['id']}/log", headers=auth)
    assert log.status_code == 200
    assert log.json()["data"]
