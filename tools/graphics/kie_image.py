"""KIE.AI image generation gateway (Seedream, GPT-image, Flux, ...)."""

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
DEFAULT_MODEL = "gpt-image-2-text-to-image"


class KieImage(BaseTool):
    name = "kie_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
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
    agent_skills = ["ai-image-gen"]

    capabilities = ["text_to_image", "image_to_image"]
    supports = {"text_to_image": True, "image_to_image": True, "aspect_ratio": True, "multi_model": True}
    best_for = [
        "multi-model image generation through one KIE.AI key",
        "Seedream, GPT-image, Flux and other Market image models",
        "social thumbnails and storyboard frames",
    ]
    not_good_for = ["offline generation"]
    fallback_tools = ["flux_image", "openai_image", "google_imagen", "fal_image"]
    quality_score = 0.9

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "default": DEFAULT_MODEL,
                "description": "KIE image model id, e.g. gpt-image-2-text-to-image or seedream/4-5-text-to-image.",
            },
            "operation": {"type": "string", "enum": ["text_to_image", "image_to_image"], "default": "text_to_image"},
            "aspect_ratio": {"type": "string", "default": "9:16"},
            "image_url": {"type": "string"},
            "extra_input": {"type": "object", "default": {}},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "aspect_ratio"]
    side_effects = ["writes image file to output_path", "calls KIE.AI API"]
    user_visible_verification = ["Inspect the generated image for composition and legibility"]

    def _api_key(self) -> str:
        return os.environ.get("KIE_API_KEY", "").strip()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.04

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        key = self._api_key()
        if not key:
            return ToolResult(success=False, error="KIE_API_KEY is not set. " + self.install_instructions)
        import requests

        model = inputs.get("model") or DEFAULT_MODEL
        payload_input: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "aspect_ratio": inputs.get("aspect_ratio", "9:16"),
        }
        if inputs.get("image_url"):
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
            for _ in range(120):  # up to 10 minutes
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
                    return ToolResult(success=False, error=f"KIE recordInfo {poll_body.get('code')}: {poll_body.get('msg')}")
                data = poll_body.get("data") or {}
                state = data.get("state")
                if state == "success":
                    break
                if state == "fail":
                    return ToolResult(success=False, error=f"KIE image failed ({data.get('failCode')}): {data.get('failMsg')}")
            else:
                return ToolResult(success=False, error="KIE image task timed out", data={"task_id": task_id})

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
                return ToolResult(success=False, error=f"KIE returned no image URL: {result}")
            output_path = Path(inputs.get("output_path", "kie_image.png"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(urls[0], timeout=120)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"KIE image request failed: {exc}")
        credits = float(data.get("creditsConsumed") or 0)
        cost = round(credits * float(os.environ.get("KIE_CREDIT_USD", "0.005")), 4)
        return ToolResult(
            success=True,
            data={
                "provider": "kie",
                "model": model,
                "task_id": task_id,
                "credits": credits,
                "cost_usd": cost,
                "output": str(output_path),
                "output_path": str(output_path),
            },
            artifacts=[str(output_path)],
            cost_usd=cost,
        )
