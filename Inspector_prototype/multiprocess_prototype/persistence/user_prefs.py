# multiprocess_prototype/persistence/user_prefs.py
"""
Пользовательские настройки прототипа (JSON под ``get_data_root()``).

Сейчас: ``camera_type``. Дальнейшие ключи — в том же файле или отдельных модулях рядом.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .paths import ensure_data_root, get_data_root, legacy_prefs_path

_PREFS_FILENAME = "user_prefs.json"
_VALID_CAMERA = frozenset(("simulator", "webcam", "hikvision"))


def _prefs_file() -> Path:
    return get_data_root() / _PREFS_FILENAME


def _load_raw() -> Dict[str, Any]:
    path = _prefs_file()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _migrate_legacy_if_needed() -> None:
    """Перенести ``.inspector_prefs.json`` из корня пакета в user_prefs.json один раз."""
    new_path = _prefs_file()
    if new_path.is_file():
        return
    legacy = legacy_prefs_path()
    if not legacy.is_file():
        return
    try:
        with open(legacy, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        ensure_data_root()
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            legacy.unlink()
        except OSError:
            pass
    except (json.JSONDecodeError, OSError):
        pass


def _load_prefs() -> dict:
    _migrate_legacy_if_needed()
    return _load_raw()


def _save_prefs(data: dict) -> bool:
    try:
        ensure_data_root()
        with open(_prefs_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def get_camera_type() -> str:
    """
    Тип камеры: prefs → env ``INSPECTOR_CAMERA_TYPE`` → default по ОС.
    """
    import os
    import sys

    prefs = _load_prefs()
    ct = prefs.get("camera_type")
    if ct in _VALID_CAMERA:
        if ct == "hikvision" and sys.platform != "win32":
            return "simulator"
        return ct
    env_ct = os.environ.get("INSPECTOR_CAMERA_TYPE")
    if env_ct in _VALID_CAMERA:
        if env_ct == "hikvision" and sys.platform != "win32":
            return "simulator"
        return env_ct
    return "simulator" if sys.platform != "win32" else "hikvision"


def set_camera_type(camera_type: str) -> bool:
    """Сохранить тип камеры в user_prefs.json."""
    if camera_type not in _VALID_CAMERA:
        return False
    prefs = _load_prefs()
    prefs["camera_type"] = camera_type
    return _save_prefs(prefs)
