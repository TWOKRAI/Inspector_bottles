"""UiPrefsStore — простой kv-store для UI-предпочтений.

Хранит предпочтения в data/ui_prefs.yaml.
Поддерживает get/set по dotted-пути ('settings.view_mode').
Сохраняет атомарно через .tmp + os.replace.
Если файла нет — get() возвращает default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# data/ui_prefs.yaml рядом с multiprocess_prototype/
# parents[2] от prefs/store.py: [0]=prefs/, [1]=frontend/, [2]=multiprocess_prototype/
UI_PREFS_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "ui_prefs.yaml"


class UiPrefsStore:
    """data/ui_prefs.yaml — простой kv-store для UI-предпочтений.

    Поддерживает get/set по dotted-пути ('settings.view_mode').
    Данные хранятся как {'settings': {'view_mode': 'cards'}}.
    Сохраняет атомарно через .tmp + os.replace.
    Если файла нет — get() возвращает default.

    Используется в Settings-табе (cards/table выбор) и будет
    использоваться в других табах Phase 10B.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else UI_PREFS_PATH
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Прочитать YAML. При отсутствии файла — вернуть {}."""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            # При любой ошибке чтения — начинаем с пустого словаря
            return {}

    def _persist(self) -> None:
        """Атомарная запись через .tmp + os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".yaml.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self._data, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, self._path)
        except Exception:
            # При ошибке записи удаляем .tmp если он был создан
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение по dotted-пути.

        Например: get('settings.view_mode') → data['settings']['view_mode'].
        Если путь не существует — вернуть default.
        """
        parts = key.split(".")
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict):
                return default
            if part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Установить значение по dotted-пути и сохранить.

        Например: set('settings.view_mode', 'table') →
            data['settings']['view_mode'] = 'table'.
        Промежуточные словари создаются автоматически.
        """
        parts = key.split(".")
        node: dict[str, Any] = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        self._persist()

    def all(self) -> dict[str, Any]:
        """Вернуть копию всего словаря предпочтений."""
        import copy
        return copy.deepcopy(self._data)
