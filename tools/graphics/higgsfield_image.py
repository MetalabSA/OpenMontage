"""Higgsfield image generation (Soul, Seedream, Ideogram, Recraft, ...)."""

from __future__ import annotations

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
DEFAULT_MODEL = "higgsfield-ai/soul/standard"
MODELS = [
    "higgsfield-ai/soul/standard",
    "higgsfield-ai/soul/v2/standard",
    "higgsfield-ai/soul/v2/image-to-image",
    "bytedance/seedream/v4/text-to-image",
    "ideogram/v4.0",
    "recraft/v4.1/pro/text-to-image",
    "xai/grok-imagine-image-2.0",
]


class HiggsFieldImage(BaseTool):
    name = "higgsfield_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "higgsfield"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set HF_KEY to key:secret from https://cloud.higgsfield.ai/api-keys. "
        "Alternatively set HF_API_KEY and HF_API_SECRET."
    )
    agent_skills = ["ai-image-gen"]
    capabilities = ["text_to_image", "image_to_image"]
    supports = {"text_to_image": True, "image_to_image": True, "aspect_ratio": True, "character_consistency": True}
    best_for = ["Soul character images", "photorealistic hero frames", "consistent character portraits"]
    not_good_for = ["offline generation"]
    fallback_tools = ["kie_image", "flux_image", "ideogram_fal_image"]
    quality_score = 0.92

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "enum": MODELS, "default": DEFAULT_MODEL},
            "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"], "default": "9:16"},
            "image_url": {"type": "string"},
            "extra_args": {"type": "object", "default": {}},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "aspect_ratio"]
    side_effects = ["writes image file to output_path", "calls Higgsfield API"]

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
        return 0.05

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 60.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        credentials = self._credentials()
        if not credentials:
            return ToolResult(success=False, error="Higgsfield credentials not set. " + self.install_instructions)
        import requests

        model = inputs.get("model") or DEFAULT_MODEL
        payload: dict[str, Any] = {"prompt": inputs["prompt"], "aspect_ratio": inputs.get("aspect_ratio", "9:16")}
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
            for _ in range(120):
                time.sleep(3)
                poll = requests.get(status_url, headers=headers, timeout=30)
                poll.raise_for_status()
                data = poll.json()
                status = str(data.get("status") or "").lower()
                if status == "completed":
                    break
                if status in ("failed", "nsfw", "cancelled", "canceled"):
                    return ToolResult(success=False, error=f"Higgsfield image {status}: {data.get('error') or data}", data={"request_id": request_id})
            else:
                return ToolResult(success=False, error="Higgsfield image timed out", data={"request_id": request_id})
            images = data.get("images") or []
            url = images[0].get("url") if images and isinstance(images[0], dict) else None
            if not url:
                return ToolResult(success=False, error=f"Higgsfield returned no image URL: {data}", data={"request_id": request_id})
            output_path = Path(inputs.get("output_path", "higgsfield_image.png"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            download = requests.get(url, timeout=120)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"Higgsfield image request failed: {exc}")
        return ToolResult(
            success=True,
            data={"provider": "higgsfield", "model": model, "request_id": request_id, "output": str(output_path), "output_path": str(output_path)},
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
        )
