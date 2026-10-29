"""KIE.AI video generation gateway (Kling, Veo, Seedance, Runway, ...).

KIE exposes a unified Market API: create a task with a model id + input,
then poll `/api/v1/jobs/recordInfo` for the result. This adapter keeps the
model id configurable so new KIE models can be used without a code change.
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

KIE_BASE = "https://api.kie.ai"
DEFAULT_MODEL = "kling/v2-5-turbo-text-to-video-pro"


class KieVideo(BaseTool):
    name = "kie_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "kie"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set KIE_API_KEY to your KIE.AI API key.\n"
        "  Get it at https://kie.ai/api-key"
    )
    agent_skills = ["ai-video-gen", "seedance-2-0"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "aspect_ratio": True,
        "native_audio": True,
        "multi_model": True,
        "cinematic_quality": True,
    }
    best_for = [
        "multi-model video generation through one KIE.AI key",
        "Kling, Veo, Seedance, Runway, Wan and other Market models",
        "social vertical clips (9:16) with optional native audio",
        "cost/quality routing across several video vendors",
    ]
    not_good_for = ["offline generation", "models that require a dedicated SDK"]
    fallback_tools = ["higgsfield_video", "seedance_video", "kling_video", "veo_video"]
    quality_score = 0.92

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "default": DEFAULT_MODEL,
                "description": "KIE model id, e.g. kling/v2-5-turbo-text-to-video-pro, bytedance/seedance-2-5.",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "default": "text_to_video",
            },
            "duration": {"type": "string", "enum": ["5", "10"], "default": "5"},
            "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"], "default": "9:16"},
            "image_url": {"type": "string", "description": "Reference image for image_to_video."},
            "negative_prompt": {"type": "string"},
            "extra_input": {
                "type": "object",
                "description": "Model-specific KIE input fields merged into the request.",
                "default": {},
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "duration", "aspect_ratio"]
    side_effects = ["writes video file to output_path", "calls KIE.AI API"]
    user_visible_verification = ["Watch the clip for motion coherence and check audio sync"]

    def _api_key(self) -> str:
        return os.environ.get("KIE_API_KEY", "").strip()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        duration = float(inputs.get("duration", 5) or 5)
        return round(0.25 * (duration / 5), 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        key = self._api_key()
        if not key:
            return ToolResult(success=False, error="KIE_API_KEY is not set. " + self.install_instructions)
        import requests

        model = inputs.get("model") or DEFAULT_MODEL
        operation = inputs.get("operation", "text_to_video")
        payload_input: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "duration": str(inputs.get("duration", "5")),
            "aspect_ratio": inputs.get("aspect_ratio", "9:16"),
        }
        if inputs.get("negative_prompt"):
            payload_input["negative_prompt"] = inputs["negative_prompt"]
        if operation == "image_to_video" and inputs.get("image_url"):
            payload_input["image_url"] = inputs["image_url"]
        payload_input.update(inputs.get("extra_input") or {})
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            submit = requests.post(
                f"{KIE_BASE}/api/v1/jobs/createTask",
                headers=headers,
                json={"model": model, "input": payload_input},
                timeout=30,
            )
            submit.raise_for_status()
            body = submit.json()
            if body.get("code") != 200:
                return ToolResult(success=False, error=f"KIE createTask {body.get('code')}: {body.get('msg')}")
            task_id = (body.get("data") or {}).get("taskId")
            if not task_id:
                return ToolResult(success=False, error=f"KIE createTask returned no taskId: {body}")

            data: dict[str, Any] = {}
            for _ in range(180):  # up to 15 minutes
                time.sleep(5)
                poll = requests.get(
                    f"{KIE_BASE}/api/v1/jobs/recordInfo",
                    headers=headers,
                    params={"taskId": task_id},
                    timeout=30,
                )
                poll.raise_for_status()
                poll_body = poll.json()
                if poll_body.get("code") != 200:
                    return ToolResult(success=False, error=f"KIE recordInfo {poll_body.get('code')}: {poll_body.get('msg')}")
                data = poll_body.get("data") or {}
                state = data.get("state")
                if state == "success":
                    break
                if state == "fail":
                    return ToolResult(
                        success=False,
                        error=f"KIE task failed ({data.get('failCode')}): {data.get('failMsg')}",
                        data={"task_id": task_id, "provider": "kie", "model": model},
                    )
            else:
                return ToolResult(success=False, error="KIE task timed out", data={"task_id": task_id})

            result = data.get("resultJson") or "{}"
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = {}
            urls = result.get("resultUrls") or result.get("resultUrl") or []
            if isinstance(urls, str):
                urls = [urls]
            if not urls:
                return ToolResult(success=False, error=f"KIE returned no result URLs: {result}", data={"task_id": task_id})

            output_path = Path(inputs.get("output_path", "kie_video.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(urls[0], timeout=180)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"KIE video request failed: {exc}")

        from tools.video._shared import probe_output

        try:
            probed = probe_output(output_path)
        except Exception:
            probed = {}
        credits = float(data.get("creditsConsumed") or 0)
        cost = round(credits * float(os.environ.get("KIE_CREDIT_USD", "0.005")), 4)
        return ToolResult(
            success=True,
            data={
                "provider": "kie",
                "model": model,
                "operation": operation,
                "task_id": task_id,
                "credits": credits,
                "cost_usd": cost,
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=cost,
        )
