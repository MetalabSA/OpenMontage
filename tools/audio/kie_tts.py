"""KIE.AI text-to-speech (Gemini 3.1 Flash TTS)."""

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
MODEL = "google/gemini-3-1-flash-tts"


class KieTTS(BaseTool):
    name = "kie_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "kie"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = "Set KIE_API_KEY to your KIE.AI API key (https://kie.ai/api-key)."
    agent_skills = ["voice"]
    capabilities = ["text_to_speech"]
    supports = {"style_control": True, "accent": True, "pace": True, "multi_language": True}
    best_for = ["expressive Spanish narration", "promo/explainer voice-over", "voice with accent and style control"]
    not_good_for = ["offline generation", "real-time streaming"]
    fallback_tools = ["piper_tts"]
    quality_score = 0.9

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "voice_name": {"type": "string", "default": "Zephyr"},
            "accent": {"type": "string", "default": "Neutral"},
            "style": {"type": "string", "default": "Newscaster"},
            "pace": {"type": "string", "default": "Natural"},
            "scene": {"type": "string"},
            "sample_context": {"type": "string"},
            "output_path": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["text", "voice_name", "accent", "style", "pace"]
    side_effects = ["writes audio file to output_path", "calls KIE.AI API"]

    def _api_key(self) -> str:
        return os.environ.get("KIE_API_KEY", "").strip()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.02

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        key = self._api_key()
        if not key:
            return ToolResult(success=False, error="KIE_API_KEY is not set. " + self.install_instructions)
        import requests

        payload = {
            "temperature": 1,
            "scene": inputs.get("scene", ""),
            "sample_context": inputs.get("sample_context", ""),
            "speakers": [
                {
                    "speaker_id": "Speaker 1",
                    "voice_name": inputs.get("voice_name", "Zephyr"),
                    "accent": inputs.get("accent", "Neutral"),
                    "style": inputs.get("style", "Newscaster"),
                    "pace": inputs.get("pace", "Natural"),
                }
            ],
            "dialogue_turns": [{"speaker_id": "Speaker 1", "text": inputs["text"]}],
        }
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
                return ToolResult(success=False, error=f"KIE TTS createTask {body.get('code')}: {body.get('msg')}")
            task_id = (body.get("data") or {}).get("taskId")
            if not task_id:
                return ToolResult(success=False, error=f"KIE TTS returned no taskId: {body}")
            data: dict[str, Any] = {}
            for _ in range(120):
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
                    return ToolResult(success=False, error=f"KIE TTS recordInfo {poll_body.get('code')}: {poll_body.get('msg')}")
                data = poll_body.get("data") or {}
                state = data.get("state")
                if state == "success":
                    break
                if state == "fail":
                    return ToolResult(success=False, error=f"KIE TTS failed ({data.get('failCode')}): {data.get('failMsg')}")
            else:
                return ToolResult(success=False, error="KIE TTS timed out", data={"task_id": task_id})
            url = _find_audio(data)
            if not url:
                return ToolResult(success=False, error=f"KIE TTS returned no audio URL: {data}", data={"task_id": task_id})
            output_path = Path(inputs.get("output_path", "kie_tts.wav"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(url, timeout=120)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"KIE TTS request failed: {exc}")
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
