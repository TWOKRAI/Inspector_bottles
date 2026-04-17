"""Persistence: data directory and user preferences (merged)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# --- Data directory ---

_ENV_DATA_DIR = "INSPECTOR_DATA_DIR"
_DEFAULT_DIRNAME = ".inspector_prototype"
_PREFS_FILENAME = "user_prefs.json"


def get_data_root() -> Path:
    raw = os.environ.get(_ENV_DATA_DIR)
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / _DEFAULT_DIRNAME).resolve()


def ensure_data_root() -> Path:
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


# --- User preferences ---

def _prefs_file() -> Path:
    return get_data_root() / _PREFS_FILENAME


def _load_prefs() -> Dict[str, Any]:
    path = _prefs_file()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_prefs(data: dict) -> bool:
    try:
        ensure_data_root()
        with open(_prefs_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def get_camera_type() -> str:
    """Camera type from prefs > env > platform default."""
    from multiprocess_prototype_v3.registers.camera import CAMERA_TYPES, DEFAULT_CAMERA_TYPE
    prefs = _load_prefs()
    ct = prefs.get("camera_type")
    if ct in CAMERA_TYPES:
        if ct == "hikvision" and sys.platform != "win32":
            return DEFAULT_CAMERA_TYPE
        return ct
    env_ct = os.environ.get("INSPECTOR_CAMERA_TYPE")
    if env_ct in CAMERA_TYPES:
        if env_ct == "hikvision" and sys.platform != "win32":
            return DEFAULT_CAMERA_TYPE
        return env_ct
    return DEFAULT_CAMERA_TYPE if sys.platform != "win32" else "hikvision"


def set_camera_type(camera_type: str) -> bool:
    """Save camera type to user_prefs.json."""
    from multiprocess_prototype_v3.registers.camera import CAMERA_TYPES
    if camera_type not in CAMERA_TYPES:
        return False
    prefs = _load_prefs()
    prefs["camera_type"] = camera_type
    return _save_prefs(prefs)
