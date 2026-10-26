"""Agent execution: prompt contract, Claude Code CLI, fake mode and checkpoints."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from api import config, db, schemas_io
from api.errors import ApiError
from api.services import pipelines, projects

_PROCS: dict[str, subprocess.Popen] = {}


class AgentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def terminate(job_id: str) -> None:
    proc = _PROCS.get(job_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


# --- schema-driven minimal artifact (fake mode + tests) --------------------
def _resolve_ref(node: dict, root: dict) -> dict:
    ref = node.get("$ref", "")
    if not ref.startswith("#/"):
        return node
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return target


def minimal_artifact(schema: dict, root: dict | None = None) -> Any:
    root = root or schema
    if "$ref" in schema:
        return minimal_artifact(_resolve_ref(schema, root), root)
    if "allOf" in schema:
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for part in schema["allOf"]:
            resolved = _resolve_ref(part, root) if "$ref" in part else part
            merged["properties"].update(resolved.get("properties", {}))
            merged["required"].extend(resolved.get("required", []))
        return minimal_artifact(merged, root)
    if "oneOf" in schema:
        return minimal_artifact(schema["oneOf"][0], root)
    if "anyOf" in schema:
        return minimal_artifact(schema["anyOf"][0], root)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {key: minimal_artifact(props[key], root) for key in schema.get("required", []) if key in props}
    if kind == "array":
        items = schema.get("items", {})
        return [minimal_artifact(items, root) for _ in range(schema.get("minItems", 0))]
    if kind == "string":
        fmt = schema.get("format")
        return {
            "uri": "https://example.com/x",
            "date": "2026-01-01",
            "date-time": "2026-01-01T00:00:00Z",
            "email": "a@b.co",
        }.get(fmt, "x" * max(1, schema.get("minLength", 1)))
    if kind in {"number", "integer"}:
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    return None


def _artifact_for(pipeline: str, stage: str) -> str:
    spec = pipelines.stage_spec(pipeline, stage)
    produces = spec.get("produces") or []
    if not produces:
        raise AgentError("unsupported_stage", f"Stage {stage!r} declares no artifact")
    return produces[0]


def _skill_text(pipeline: str, stage: str) -> str:
    spec = pipelines.stage_spec(pipeline, stage)
    skill = spec.get("skill")
    if not skill:
        return ""
    path = config.ROOT / "skills" / f"{skill}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _context_artifacts(project_dir: Path, limit: int = 80_000) -> str:
    chunks: list[str] = []
    artifacts_dir = project_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return ""
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if sum(len(c) for c in chunks) + len(raw) > limit:
            break
        chunks.append(f"### {path.stem}\n```json\n{raw}\n```")
    return "\n\n".join(chunks)


def build_prompt(conn, project: dict, stage: str, job: dict, artifact: str) -> str:
    project_dir = projects.project_dir(project["slug"])
    schema = json.loads((config.SCHEMA_DIR / f"{artifact}.schema.json").read_text(encoding="utf-8"))
    skill = _skill_text(project["pipeline"], stage)
    instruction = job.get("instruction") or f"Ejecutá el stage {stage} del pipeline."
    gate = pipelines.stage_gate(project["pipeline"], stage)
    model = job.get("model") or config.ENGINE_MODEL
    return f"""# Cabina Studio — Production agent

You are the production agent for a video pipeline. Execute exactly one stage and stop.

## Hard rules
- Working directory: `{project_dir}`. Write files only inside it.
- Produce the canonical artifact at `artifacts/{artifact}.json` (valid JSON, no markdown fences).
- Validate it against the schema below before finishing.
- Do not change the render runtime, provider or model unless the instruction explicitly asks.
- Do not invent data: use the brief, prior artifacts and your tools.
- Finish with a one-paragraph summary of what you produced.

## Run context
- project: {project["slug"]} ({project["title"]})
- pipeline: {project["pipeline"]}
- stage: {stage}
- human gate: {"yes — stop after writing the artifact" if gate else "no"}
- engine: claude-code · model: {model}
- instruction: {instruction}

## Stage director skill
{skill or "(no director skill found)"}

## Canonical artifact schema ({artifact})
```json
{json.dumps(schema, ensure_ascii=False)}
```

## Prior artifacts
{_context_artifacts(project_dir) or "(none yet)"}

## Deliverable
Write `artifacts/{artifact}.json` now, validate it, and stop.
"""


def _provider_key(conn) -> str:
    if config.ENGINE_API_KEY:
        return config.ENGINE_API_KEY
    try:
        from api.services import settings

        return settings._stored_providers(conn).get(config.ENGINE_PROVIDER, "")
    except Exception:
        return ""


def _engine_env(conn) -> dict[str, str]:
    key = _provider_key(conn)
    if not key:
        raise AgentError(
            "provider_unavailable",
            f"No API key configured for engine provider {config.ENGINE_PROVIDER!r}. "
            "Set OM_ENGINE_API_KEY or save it in Settings.",
        )
    env = os.environ.copy()
    if config.ENGINE_PROVIDER == "deepseek":
        env["ANTHROPIC_BASE_URL"] = config.ENGINE_BASE_URL or config.DEEPSEEK_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = key
        env["ANTHROPIC_MODEL"] = config.ENGINE_MODEL
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = config.ENGINE_MODEL
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = config.ENGINE_MODEL
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = config.ENGINE_MODEL
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = config.ENGINE_MODEL
        env["CLAUDE_CODE_EFFORT_LEVEL"] = "max"
    else:
        env["ANTHROPIC_API_KEY"] = key
        env["ANTHROPIC_MODEL"] = config.ENGINE_MODEL
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return env


def _run_claude(job_id: str, prompt: str, cwd: Path, conn) -> dict[str, Any]:
    env = _engine_env(conn)
    model = config.ENGINE_MODEL
    args = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
    ]
    if model:
        args += ["--model", model]
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        raise AgentError("provider_unavailable", "Claude Code CLI is not installed in this image")
    _PROCS[job_id] = proc
    try:
        try:
            stdout, stderr = proc.communicate(timeout=config.AGENT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AgentError("upstream_timeout", f"Agent timed out after {config.AGENT_TIMEOUT}s")
    finally:
        _PROCS.pop(job_id, None)
    if proc.returncode != 0:
        tail = (stderr or stdout or "").strip()[-1200:]
        raise AgentError("agent_failed", f"Claude Code exited {proc.returncode}: {tail}")
    payload: dict[str, Any] | None = None
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is None:
        raise AgentError("agent_failed", f"Unparseable agent output: {(stdout or '')[:400]}")
    if payload.get("is_error"):
        raise AgentError("agent_failed", str(payload.get("result") or "agent reported an error")[:800])
    try:
        cost = float(payload.get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    return {"result": payload.get("result") or "", "cost": cost}


async def execute_job(
    conn,
    job: dict,
    *,
    progress: Callable[[int, str], None],
    emit: Callable[[str, dict], None],
) -> dict[str, Any]:
    slug = job["project_id"]
    stage = job.get("stage")
    if not stage:
        raise AgentError("unsupported_stage", "A job must target a pipeline stage")
    project = projects.get(conn, slug)
    artifact = _artifact_for(project["pipeline"], stage)
    project_dir = projects.project_dir(slug)
    gate = pipelines.stage_gate(project["pipeline"], stage)

    progress(10, "preparando prompt")
    prompt = build_prompt(conn, project, stage, job, artifact)
    target = schemas_io.artifact_path(project_dir, artifact)
    target.unlink(missing_ok=True)

    last_error = ""
    data: Any = None
    cost = 0.0
    for attempt in range(1, max(1, config.AGENT_MAX_ATTEMPTS) + 1):
        progress(20 if attempt == 1 else 55, f"agente (intento {attempt})")
        if config.AGENT_MODE == "fake":
            await asyncio.sleep(0.05)
            schema = json.loads((config.SCHEMA_DIR / f"{artifact}.schema.json").read_text(encoding="utf-8"))
            data = minimal_artifact(schema)
            schemas_io.write_artifact(project_dir, artifact, data)
            cost = 0.0
        else:
            attempt_prompt = prompt if not last_error else prompt + f"\n\n## Previous attempt failed\n{last_error}\nFix it and write a valid artifact."
            result = await asyncio.to_thread(_run_claude, job["id"], attempt_prompt, project_dir, conn)
            cost += float(result.get("cost") or 0)
            emit("log", {"level": "info", "line": (result.get("result") or "")[:4000]})
            data = schemas_io.read_json(target)
            if data is None:
                last_error = f"Artifact file `artifacts/{artifact}.json` was not created."
                continue
        try:
            schemas_io.validate_artifact(artifact, data)
            break
        except ApiError as exc:
            last_error = exc.message
            data = None
            continue
    if data is None:
        raise AgentError("artifact_invalid", last_error or "Agent did not produce a valid artifact")

    progress(85, "escribiendo checkpoint")
    from lib.checkpoint import write_checkpoint

    metadata = {
        "job_id": job["id"],
        "engine": config.DEFAULT_ENGINE,
        "model": job.get("model"),
        "agent_mode": config.AGENT_MODE,
    }
    write_checkpoint(
        config.PROJECTS_DIR,
        slug,
        stage,
        "awaiting_human" if gate else "completed",
        {artifact: data},
        pipeline_type=project["pipeline"],
        human_approval_required=gate,
        human_approved=False,
        cost_snapshot={"spent_usd": round(cost, 4), "total_usd": config.DEFAULT_BUDGET_USD},
        metadata=metadata,
    )
    progress(100, "checkpoint escrito")
    emit("checkpoint", {"stage": stage, "status": "awaiting_human" if gate else "completed", "artifact": artifact})
    return {
        "status": "awaiting_human" if gate else "succeeded",
        "gate": gate,
        "artifact": artifact,
        "cost": round(cost, 4),
        "next_stage": pipelines.next_stage(project["pipeline"], stage),
    }
