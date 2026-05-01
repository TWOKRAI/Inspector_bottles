"""ConfigSnapshotManager — generic YAML-хранилище именованных слотов конфигурации."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_SNAPSHOT_SLOT_ID = "default"
# Alias для обратной совместимости с прототипом
DEFAULT_RECIPE_SLOT_ID = DEFAULT_SNAPSHOT_SLOT_ID


class ConfigSnapshotManager:
    """Generic YAML-хранилище именованных слотов (register-slots + app-slots).

    Два файла: основной (register-слоты) и дополнительный (app-слоты).
    Пути передаются снаружи — никакой привязки к конкретному проекту.
    """

    def __init__(
        self,
        data_path: Path,
        app_slots_path: Path,
    ) -> None:
        self._data_path = Path(data_path)
        self._app_path = Path(app_slots_path)
        self._slots: Dict[str, Dict[str, Any]] = {}
        self._app_slots: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Загрузить оба файла в память."""
        self._slots = self._read_yaml(self._data_path)
        self._app_slots = self._read_yaml(self._app_path)

    @staticmethod
    def _read_yaml(path: Path) -> Dict[str, Dict[str, Any]]:
        """Прочитать YAML-файл; вернуть {} при отсутствии или ошибке."""
        if not path.is_file():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except (yaml.YAMLError, OSError):
            return {}

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> bool:
        """Записать dict в YAML (создаёт директорию при необходимости)."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Register-slots API
    # ------------------------------------------------------------------

    def list_slots(self) -> List[str]:
        """Список идентификаторов register-слотов."""
        return list(self._slots.keys())

    def get_slot(self, slot_id: str) -> Optional[Dict[str, Any]]:
        """Получить копию register-слота по ID."""
        return copy.deepcopy(self._slots.get(slot_id))

    def save_slot(self, slot_id: str, data: Dict[str, Any]) -> bool:
        """Сохранить register-слот и записать в файл."""
        self._slots[slot_id] = copy.deepcopy(data)
        return self._write_yaml(self._data_path, self._slots)

    def delete_slot(self, slot_id: str) -> bool:
        """Удалить register-слот; False если не существовал."""
        if slot_id not in self._slots:
            return False
        del self._slots[slot_id]
        return self._write_yaml(self._data_path, self._slots)

    # ------------------------------------------------------------------
    # App-slots API
    # ------------------------------------------------------------------

    def get_app_slot(self, slot_id: str) -> Optional[Dict[str, Any]]:
        """Получить копию app-слота по ID."""
        return copy.deepcopy(self._app_slots.get(slot_id))

    def save_app_slot(self, slot_id: str, data: Dict[str, Any]) -> bool:
        """Сохранить app-слот и записать в файл."""
        self._app_slots[slot_id] = copy.deepcopy(data)
        return self._write_yaml(self._app_path, self._app_slots)
