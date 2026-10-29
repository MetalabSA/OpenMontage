"""Higgsfield video generation via the current Cloud API.

Auth: Authorization: Key <key:secret> (HF_KEY) against https://api.higgsfield.ai
Submit returns a request id; poll its status_url until completed and read video.url.
"""

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

BASE_URL = "https://api.higgsfield.ai"
_DEFAULT_TEXT = "bytedance/seedance-2.5/text-to-video"
_DEFAULT_IMAGE = "bytedance/seedance-2.5/image-to-video"
MODELS = [
    "bytedance/seedance-2.5/text-to-video",
    "bytedance/seedance-2.5/image-to-video",
    "bytedance/seedance-2.0/text-to-video",
    "kling-video/v3.0/pro/text-to-video",
    "kling-video/v3.0/pro/image-to-video",
    "kling-video/v4.0/text-to-video",
    "alibaba/wan-3.0-prime/text-to-video",
    "minimax/h3/text-to-video",
    "lightricks/ltx-2.5/text-to-video/pro",
]


class HiggsFieldVideo(BaseTool):
    name = "higgsfield_video"
    version = "0.2.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "higgsfield"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set HF_KEY to key:secret from https://cloud.higgsfield.ai/api-keys.\n"
        "  Alternatively set HF_API_KEY and HF_API_SECRET."
    )
    agent_skills = ["seedance-2-5", "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "aspect_ratio": True,
        "native_audio": True,
        "character_consistency": True,
        "cinematic_quality": True,
        "multi_model": True,
    }
    best_for = [
        "premium hero shots with Seedance 2.5 / Kling 3.0",
        "character-consistent clips and cinematic quality",
        "models that need native audio or reference images",
    ]
    not_good_for = ["offline generation", "budget bulk generation"]
    fallback_tools = ["kie_video", "seedance_video", "kling_video"]
    quality_score = 0.93

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "enum": MODELS,
                "default": _DEFAULT_TEXT,
                "description": "Higgsfield application slug.",
            },
            "operation": {"type": "string", "enum": ["text_to_video", "image_to_video"], "default": "text_to_video"},
            "duration": {"type": "integer", "enum": [5, 10], "default": 5},
            "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"], "default": "9:16"},
            "image_url": {"type": "string"},
            "extra_args": {"type": "object", "default": {}},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "duration", "aspect_ratio"]
    side_effects = ["writes video file to output_path", "calls Higgsfield API"]
    user_visible_verification = ["Watch the clip for motion and audio quality"]

    @staticmethod
    def _credentials() -> str:
        combined = (os.environ.get("HF_KEY") or os.environ.get("HIGGSFIELD_KEY") or "").strip()
        if combined:
            return combined
        key = (os.environ.get("HF_API_KEY") or os.environ.get("HIGGSFIELD_API_KEY") or "").strip()
        secret = (os.environ.get("HF_API_SECRET") or os.environ.get("HIGGSFIELD_API_SECRET") or "").strip()
        return f"{key}:{secret}" if key and secret else ""

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._credentials() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        duration = int(inputs.get("duration", 5))
        return round(0.8 * (duration / 5), 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        credentials = self._credentials()
        if not credentials:
            return ToolResult(success=False, error="Higgsfield credentials not set. " + self.install_instructions)
        import requests

        model = inputs.get("model") or (_DEFAULT_IMAGE if inputs.get("image_url") else _DEFAULT_TEXT)
        payload: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "duration": int(inputs.get("duration", 5)),
            "aspect_ratio": inputs.get("aspect_ratio", "9:16"),
        }
        if inputs.get("image_url"):
            payload["image_url"] = inputs["image_url"]
        payload.update(inputs.get("extra_args") or {})
        headers = {"Authorization": f"Key {credentials}", "Content-Type": "application/json"}
        try:
            submit = requests.post(f"{BASE_URL}/{model}", headers=headers, json=payload, timeout=60)
            if submit.status_code >= 400:
                return ToolResult(success=False, error=f"Higgsfield submit {submit.status_code}: {submit.text[:300]}")
            body = submit.json()
            status_url = body.get("status_url")
            request_id = body.get("request_id")
            if not status_url:
                return ToolResult(success=False, error=f"Higgsfield submit returned no status_url: {body}")
            data: dict[str, Any] = {}
            for _ in range(180):  # up to 15 minutes
                time.sleep(5)
                poll = requests.get(status_url, headers=headers, timeout=30)
                poll.raise_for_status()
                data = poll.json()
                status = str(data.get("status") or "").lower()
                if status == "completed":
                    break
                if status in ("failed", "nsfw", "cancelled", "canceled"):
                    return ToolResult(success=False, error=f"Higgsfield task {status}: {data.get('error') or data}", data={"request_id": request_id})
            else:
                return ToolResult(success=False, error="Higgsfield task timed out", data={"request_id": request_id})

            video_url = (data.get("video") or {}).get("url")
            if not video_url:
                video_url = _find_url(data)
            if not video_url:
                return ToolResult(success=False, error=f"Higgsfield returned no video URL: {data}", data={"request_id": request_id})
            output_path = Path(inputs.get("output_path", "higgsfield_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(video_url, timeout=180)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"Higgsfield request failed: {exc}")

        from tools.video._shared import probe_output

        try:
            probed = probe_output(output_path)
        except Exception:
            probed = {}
        return ToolResult(
            success=True,
            data={
                "provider": "higgsfield",
                "model": model,
                "request_id": request_id,
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                "cost_usd": self.estimate_cost(inputs),
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
        )


def _find_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("url", "video_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and ".mp4" in candidate:
                return candidate
        for child in value.values():
            found = _find_url(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_url(child)
            if found:
                return found
    return None
