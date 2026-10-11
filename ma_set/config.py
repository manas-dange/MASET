"""
MA-SET Configuration
=====================
Central configuration loaded from environment variables and .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    # LLM
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str   = os.getenv("GROQ_API_KEY", "")

    # Paths
    PROJECT_ROOT: Path  = Path(__file__).parent.parent
    DEMO_TARGET: Path   = PROJECT_ROOT / "demo_target"
    RUNS_DIR: Path      = PROJECT_ROOT / "runs"
    CACHE_DIR: Path     = PROJECT_ROOT / ".ma_set_cache"

    # Protection
    ALLOW_LIST: list[str] = [
        "demo_target/app.py",
        "demo_target/tests/",
    ]
    DENY_LIST: list[str] = [
        "demo_target/legacy_billing.py",   # PROTECTED
        ".venv/",
        ".git/",
        "ma_set/",                          # agents should not self-modify
    ]

    # Budget caps (Phase 4)
    MAX_LLM_CALLS_PER_TASK: int = int(os.getenv("MAX_LLM_CALLS_PER_TASK", "20"))
    MAX_RETRIES_PER_LOOP: int   = int(os.getenv("MAX_RETRIES_PER_LOOP", "3"))

    # Visualization (Phase 5)
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8765"))
