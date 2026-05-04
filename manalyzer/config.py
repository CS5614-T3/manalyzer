from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
PRIVATE_DIR = os.path.join(ROOT_DIR, "private")
DB_CONFIG_PATH = os.path.join(PRIVATE_DIR, "db_env.json")

class ConfigError(Exception):
    pass


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {path}: {e}") from e


def get_db_config() -> Dict[str, str]:
    data = load_json(DB_CONFIG_PATH)

    supabase_url = data.get("supabase_url")
    supabase_key = data.get("supabase_key")

    if not supabase_url:
        raise ConfigError("db_env.json doesn't contain 'supabase_url'.")
    if not supabase_key:
        raise ConfigError("db_env.json doesn't contain 'supabase_key'.")

    return {
        "supabase_url": supabase_url,
        "supabase_key": supabase_key,
    }