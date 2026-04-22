# multiprocess_prototype/persistence/__init__.py
"""Персистентность прототипа: каталог данных, пользовательские настройки."""

from .paths import ensure_data_root, get_data_root, legacy_prefs_path
from .user_prefs import get_camera_type, set_camera_type

__all__ = [
    "ensure_data_root",
    "get_camera_type",
    "get_data_root",
    "legacy_prefs_path",
    "set_camera_type",
]
