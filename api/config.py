"""Runtime configuration for the Cabina Studio API (v1)."""

from __future__ import annotations

import os
import time
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
COOKIE_SECURE = os.environ.get("OM_COOKIE_SECURE", "1") == "1"
SIM_SPEED = float(os.environ.get("OM_SIM_SPEED", "0.25"))

DEFAULT_BUDGET_USD = float(os.environ.get("OM_DEFAULT_BUDGET_USD", "2.0"))
DEFAULT_ENGINE = os.environ.get("OM_ENGINE", "claude-code")

# Agent execution (F4). "fake" writes schema-valid placeholder artifacts so the
# orchestration can be exercised before an engine key is configured.
AGENT_MODE = os.environ.get("OM_AGENT_MODE", "fake").strip().lower()
ENGINE_PROVIDER = os.environ.get("OM_ENGINE_PROVIDER", "deepseek").strip().lower()
ENGINE_API_KEY = os.environ.get("OM_ENGINE_API_KEY", "").strip()
ENGINE_BASE_URL = os.environ.get("OM_ENGINE_BASE_URL", "").strip()
ENGINE_MODEL = os.environ.get("OM_ENGINE_MODEL", "deepseek-flash").strip()
AGENT_TIMEOUT = int(os.environ.get("OM_AGENT_TIMEOUT", "1200"))
AGENT_MAX_ATTEMPTS = int(os.environ.get("OM_AGENT_MAX_ATTEMPTS", "2"))
AGENT_MAX_TURNS = int(os.environ.get("OM_AGENT_MAX_TURNS", "30"))

# DeepSeek list prices (USD per 1M tokens) — used to compute the real cost from usage,
# because Claude Code reports an Anthropic-priced estimate for unknown models.
DEEPSEEK_PRICES = {
    "deepseek-flash": {"miss": 0.15, "hit": 0.003, "out": 0.60},
    "deepseek-v4-pro": {"miss": 0.66, "hit": 0.022, "out": 1.98},
}
EVENTS_PATH = Path(os.environ.get("OM_EVENTS_PATH") or (DB_PATH.parent / "events.jsonl")).resolve()
DATA_DIR = PROJECTS_DIR.parent
BACKUPS_DIR = Path(os.environ.get("OM_BACKUPS_DIR") or (DATA_DIR / "backups")).resolve()
BACKUP_KEEP = int(os.environ.get("OM_BACKUP_KEEP", "7"))
BACKUP_INCLUDE_VOICES = os.environ.get("OM_BACKUP_INCLUDE_VOICES", "0") == "1"
DISK_WARN_PCT = int(os.environ.get("OM_DISK_WARN_PCT", "80"))

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"

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

STARTED_AT = time.time()
