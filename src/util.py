"""Shared helpers: config/prompt loading, paths, logging, env."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
FIXTURES_DIR = ROOT / "fixtures"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def load_settings() -> dict[str, Any]:
    with open(CONFIG_DIR / "settings.yaml") as f:
        return yaml.safe_load(f)


def load_queries() -> list[dict[str, Any]]:
    with open(CONFIG_DIR / "queries.yaml") as f:
        data = yaml.safe_load(f)
    return [q for q in data.get("queries", []) if q.get("enabled", True)]


def load_prompt(name: str) -> str:
    with open(PROMPTS_DIR / name) as f:
        return f.read()


def env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def collapse_ws(text: str | None) -> str:
    return " ".join((text or "").split())
