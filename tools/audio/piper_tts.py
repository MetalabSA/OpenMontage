"""Piper local text-to-speech provider tool."""

from __future__ import annotations

import os
import shutil
import subprocess
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


def default_voices_dir() -> Path:
    """Directory where Piper voice models (.onnx) live.

    Configurable via PIPER_VOICES_DIR; defaults to ~/.piper/voices.
    """
    configured = os.environ.get("PIPER_VOICES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".piper" / "voices"


class PiperTTS(BaseTool):
    name = "piper_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "piper"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:piper"]
    install_instructions = (
        "Install Piper TTS:\n"
        "  pip install piper-tts\n"
        "Or download from https://github.com/rhasspy/piper/releases\n"
        "Then download a voice model into the voices directory\n"
        "  (default ~/.piper/voices, override with PIPER_VOICES_DIR):\n"
        "  python -m piper.download_voices en_US-lessac-medium\n"
        "  mv en_US-lessac-medium.onnx* ~/.piper/voices/\n"
        "Spanish voices: es_AR-daniela-high, es_MX-claude-high, es_ES-sharvard-medium"
    )
    agent_skills = ["text-to-speech"]

    capabilities = [
        "text_to_speech",
        "offline_generation",
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": False,
        "offline": True,
        "native_audio": True,
    }
    best_for = [
        "offline narration fallback",
        "privacy-sensitive local-only workflows",
    ]
    not_good_for = [
        "best-in-class expressive voice quality",
        "voice clone matching",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "model": {
                "type": "string",
                "default": "en_US-lessac-medium",
            },
            "speaker_id": {
                "type": "integer",
                "default": 0,
            },
            "length_scale": {
                "type": "number",
                "default": 1.0,
            },
            "sentence_silence": {
                "type": "number",
                "default": 0.3,
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=200, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=[])
    idempotency_key_fields = ["text", "model", "speaker_id", "length_scale"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio for intelligibility"]

    def get_status(self) -> ToolStatus:
        if shutil.which("piper"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="Piper TTS not available. " + self.install_instructions)

        start = time.time()
        try:
            result = self._generate(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=f"Local TTS generation failed: {exc}")

        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _generate(self, inputs: dict[str, Any]) -> ToolResult:
        output_path = Path(inputs.get("output_path", "tts_output.wav"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        model = str(inputs.get("model", "en_US-lessac-medium"))
        voices_dir = default_voices_dir()
        model_file = Path(model).expanduser()
        if not model_file.is_absolute() and model_file.suffix != ".onnx":
            candidate = voices_dir / f"{model}.onnx"
            if candidate.exists():
                model_file = candidate

        proc = subprocess.run(
            [
                "piper",
                "--model", str(model_file),
                "--data-dir", str(voices_dir),
                "--speaker", str(inputs.get("speaker_id", 0)),
                "--length-scale", str(inputs.get("length_scale", 1.0)),
                "--sentence-silence", str(inputs.get("sentence_silence", 0.3)),
                "--output_file", str(output_path),
            ],
            input=inputs["text"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            available = sorted(p.stem for p in voices_dir.glob("*.onnx")) if voices_dir.exists() else []
            hint = (
                f" Available voices in {voices_dir}: {', '.join(available)}."
                if available
                else f" No voices found in {voices_dir}. Download one with: python -m piper.download_voices {model}"
            )
            return ToolResult(
                success=False,
                error=f"Piper failed (exit {proc.returncode}): {proc.stderr.strip()}{hint}",
            )
        if not output_path.exists():
            return ToolResult(success=False, error=f"Piper output file missing: {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": model,
                "speaker_id": inputs.get("speaker_id", 0),
                "text_length": len(inputs["text"]),
                "output": str(output_path),
                "format": "wav",
            },
            artifacts=[str(output_path)],
            model=model,
        )
