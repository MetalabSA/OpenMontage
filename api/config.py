"""Runtime configuration for the Cabina Studio API (v1)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = Path(os.environ.get("OM_PROJECTS_DIR") or (ROOT / "projects")).resolve()
DB_PATH = Path(os.environ.get("OM_DB_PATH") or (ROOT / "db" / "cabina.db")).resolve()
SECRET_FILE = Path(os.environ.get("OM_SECRET_FILE") or (DB_PATH.parent / "secret.key")).resolve()

PIPELINE_DIR = ROOT / "pipeline_defs"
SCHEMA_DIR = ROOT / "schemas" / "artifacts"

STATIC_TOKEN = os.environ.get("OM_API_TOKEN", "").strip()
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@cabina.local").strip()
ADMIN_PASSWORD = os.environ.get("OM_ADMIN_PASSWORD", "")
SESSION_HOURS = int(os.environ.get("OM_SESSION_HOURS", "12"))
SIM_SPEED = float(os.environ.get("OM_SIM_SPEED", "0.25"))

DEFAULT_BUDGET_USD = float(os.environ.get("OM_DEFAULT_BUDGET_USD", "2.0"))
DEFAULT_ENGINE = os.environ.get("OM_ENGINE", "claude-code")

# Hybrid model map (D13): cheap Flash by default, Pro for decision stages.
DEFAULT_MODEL_MAP = {
    "research": "deepseek-flash",
    "proposal": "deepseek-v4-pro",
    "script": "deepseek-flash",
    "scene_plan": "deepseek-v4-pro",
    "assets": "deepseek-flash",
    "edit": "deepseek-flash",
    "compose": "deepseek-flash",
    "publish": "deepseek-flash",
}

PROVIDER_ENV = {
    "fal": "FAL_KEY",
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "unsplash": "UNSPLASH_ACCESS_KEY",
}
