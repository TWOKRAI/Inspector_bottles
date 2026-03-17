# multiprocess_prototype/prefs.py
"""
Настройки приложения (сохраняются между запусками).

camera_type: simulator | webcam | hikvision — выбор типа камеры в интерфейсе.
"""

import json
from pathlib import Path
_PREFS_FILE = Path(__file__).resolve().parent / ".inspector_prefs.json"
_VALID_TYPES = frozenset(("simulator", "webcam", "hikvision"))


def _load_prefs() -> dict:
    """Загрузить JSON-настройки."""
    if not _PREFS_FILE.exists():
        return {}
    try:
        with open(_PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_prefs(data: dict) -> bool:
    """Сохранить настройки в JSON."""
    try:
        with open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def get_camera_type() -> str:
    """
    Получить тип камеры: из prefs → env → default.
    Default: simulator на macOS (Hikvision только на Windows), hikvision на Windows.
    """
    import os
    import sys

    prefs = _load_prefs()
    ct = prefs.get("camera_type")
    if ct in _VALID_TYPES:
        # На macOS Hikvision не поддерживается — fallback на simulator
        if ct == "hikvision" and sys.platform != "win32":
            return "simulator"
        return ct
    env_ct = os.environ.get("INSPECTOR_CAMERA_TYPE")
    if env_ct in _VALID_TYPES:
        if env_ct == "hikvision" and sys.platform != "win32":
            return "simulator"
        return env_ct
    return "simulator" if sys.platform != "win32" else "hikvision"


def set_camera_type(camera_type: str) -> bool:
    """
    Сохранить тип камеры в prefs.
    Возвращает True при успехе.
    """
    if camera_type not in _VALID_TYPES:
        return False
    prefs = _load_prefs()
    prefs["camera_type"] = camera_type
    return _save_prefs(prefs)
