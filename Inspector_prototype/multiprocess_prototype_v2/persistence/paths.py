# multiprocess_prototype/persistence/paths.py
"""
Каталог данных приложения (персистентное состояние, не исходный код).

Приоритет:
1. ``INSPECTOR_DATA_DIR`` — явный путь (CI, переносимая установка).
2. ``~/.inspector_prototype`` — пользовательский каталог по умолчанию.

Дальнейшие файлы (кэши, экспорты, расширенные prefs) — под тем же корнем.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_DATA_DIR = "INSPECTOR_DATA_DIR"
_DEFAULT_DIRNAME = ".inspector_prototype"


def get_data_root() -> Path:
    """Корень данных приложения (может ещё не существовать на диске)."""
    raw = os.environ.get(_ENV_DATA_DIR)
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / _DEFAULT_DIRNAME).resolve()


def ensure_data_root() -> Path:
    """Создать корень данных при необходимости."""
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def legacy_prefs_path() -> Path:
    """Старый путь prefs в корне пакета прототипа (только для однократной миграции)."""
    # multiprocess_prototype/persistence/paths.py -> multiprocess_prototype/
    return Path(__file__).resolve().parent.parent / ".inspector_prefs.json"
