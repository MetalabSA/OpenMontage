"""KIE.AI music generation through Suno (ai-music-api/generate)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

KIE_BASE = "https://api.kie.ai"
MODEL = "ai-music-api/generate"


class KieMusic(BaseTool):
    name = "kie_music"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "music_generation"
    provider = "kie"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = "Set KIE_API_KEY to your KIE.AI API key (https://kie.ai/api-key)."
    agent_skills = ["music"]
    capabilities = ["generate_background_music", "generate_song", "generate_instrumental"]
    supports = {"instrumental": True, "vocals": True, "style_control": True, "custom_lyrics": True}
    best_for = ["background music for social videos", "instrumental beds", "Suno V6 quality tracks"]
    not_good_for = ["sound effects", "offline generation"]
    fallback_tools = ["suno_music", "elevenlabs_soundtrack"]
    quality_score = 0.9

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string", "description": "Idea/description, or lyrics in custom mode."},
            "style": {"type": "string", "description": "Genre/style, e.g. cinematic ambient, latin pop."},
            "title": {"type": "string"},
            "instrumental": {"type": "boolean", "default": True},
            "custom_mode": {"type": "boolean", "default": False},
            "model": {"type": "string", "enum": ["V6", "V6_MINI", "V6_WILD"], "default": "V6"},
            "output_path": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "style", "instrumental", "model"]
    side_effects = ["writes audio file to output_path", "calls KIE.AI API"]

    def _api_key(self) -> str:
        return os.environ.get("KIE_API_KEY", "").strip()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.2

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        key = self._api_key()
        if not key:
            return ToolResult(success=False, error="KIE_API_KEY is not set. " + self.install_instructions)
        import requests

        payload: dict[str, Any] = {
            "custom_mode": bool(inputs.get("custom_mode", False)),
            "instrumental": bool(inputs.get("instrumental", True)),
            "model": inputs.get("model", "V6"),
            "prompt": inputs["prompt"],
        }
        for field in ("style", "title"):
            if inputs.get(field):
                payload[field] = inputs[field]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            submit = requests.post(
                f"{KIE_BASE}/api/v1/jobs/createTask",
                headers=headers,
                json={"model": MODEL, "input": payload},
                timeout=30,
            )
            submit.raise_for_status()
            body = submit.json()
            if body.get("code") != 200:
                return ToolResult(success=False, error=f"KIE music createTask {body.get('code')}: {body.get('msg')}")
            task_id = (body.get("data") or {}).get("taskId")
            if not task_id:
                return ToolResult(success=False, error=f"KIE music returned no taskId: {body}")
            data: dict[str, Any] = {}
            for _ in range(180):
                time.sleep(3)
                poll = requests.get(
                    f"{KIE_BASE}/api/v1/jobs/recordInfo",
                    headers=headers,
                    params={"taskId": task_id},
                    timeout=30,
                )
                poll.raise_for_status()
                poll_body = poll.json()
                if poll_body.get("code") != 200:
                    return ToolResult(success=False, error=f"KIE music recordInfo {poll_body.get('code')}: {poll_body.get('msg')}")
                data = poll_body.get("data") or {}
                state = data.get("state")
                if state == "success":
                    break
                if state == "fail":
                    return ToolResult(success=False, error=f"KIE music failed ({data.get('failCode')}): {data.get('failMsg')}")
            else:
                return ToolResult(success=False, error="KIE music timed out", data={"task_id": task_id})
            url = _find_audio(data)
            if not url:
                return ToolResult(success=False, error=f"KIE music returned no audio URL: {data}", data={"task_id": task_id})
            suffix = ".mp3" if ".mp3" in url.lower() else ".wav"
            output_path = Path(inputs.get("output_path", f"kie_music{suffix}"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(url, timeout=180)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"KIE music request failed: {exc}")
        credits = float(data.get("creditsConsumed") or 0)
        cost = round(credits * float(os.environ.get("KIE_CREDIT_USD", "0.005")), 4)
        return ToolResult(
            success=True,
            data={"provider": "kie", "model": MODEL, "task_id": task_id, "credits": credits, "cost_usd": cost, "output": str(output_path), "output_path": str(output_path)},
            artifacts=[str(output_path)],
            cost_usd=cost,
        )


def _find_audio(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("audio_url", "stream_audio_url", "url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("http"):
                return candidate
        for key in ("resultJson", "response", "result"):
            child = value.get(key)
            if isinstance(child, str):
                try:
                    child = json.loads(child)
                except json.JSONDecodeError:
                    continue
            found = _find_audio(child)
            if found:
                return found
        for child in value.values():
            found = _find_audio(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            if isinstance(child, str) and child.startswith("http"):
                return child
            found = _find_audio(child)
            if found:
                return found
    return None
