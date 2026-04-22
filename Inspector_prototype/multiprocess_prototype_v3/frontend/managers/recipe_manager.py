"""RecipeManager — YAML recipe storage (consolidated from v2's 5 files)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import yaml


DEFAULT_RECIPE_SLOT_ID = "default"
_PROTO_ROOT = Path(__file__).resolve().parent.parent.parent


class RecipeManagerProtocol(Protocol):
    def list_slots(self) -> List[str]: ...
    def get_slot(self, slot_id: str) -> Optional[Dict[str, Any]]: ...
    def save_slot(self, slot_id: str, data: Dict[str, Any]) -> bool: ...
    def delete_slot(self, slot_id: str) -> bool: ...


class RecipeManager:
    """YAML-backed recipe storage."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        app_recipes_path: Optional[str] = None,
    ):
        self._data_path = Path(data_path) if data_path else _PROTO_ROOT / "data" / "recipes.yaml"
        self._app_path = Path(app_recipes_path) if app_recipes_path else self._data_path.parent / "settings_recipes.yaml"
        self._slots: Dict[str, Dict[str, Any]] = {}
        self._app_slots: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        self._slots = self._read_yaml(self._data_path)
        self._app_slots = self._read_yaml(self._app_path)

    @staticmethod
    def _read_yaml(path: Path) -> Dict[str, Dict[str, Any]]:
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
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
            return True
        except OSError:
            return False

    def list_slots(self) -> List[str]:
        return list(self._slots.keys())

    def get_slot(self, slot_id: str) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._slots.get(slot_id))

    def save_slot(self, slot_id: str, data: Dict[str, Any]) -> bool:
        self._slots[slot_id] = copy.deepcopy(data)
        return self._write_yaml(self._data_path, self._slots)

    def delete_slot(self, slot_id: str) -> bool:
        if slot_id not in self._slots:
            return False
        del self._slots[slot_id]
        return self._write_yaml(self._data_path, self._slots)

    def ensure_slot_from_registers(self, registers_manager, slot_id: str) -> None:
        """Create default slot from current register values if it doesn't exist."""
        if slot_id in self._slots:
            return
        try:
            snapshot = {}
            for name, reg in registers_manager.registers.items():
                snapshot[name] = reg.model_dump()
            self.save_slot(slot_id, snapshot)
        except Exception:
            pass

    def ensure_app_slot_from_snapshot(self, slot_id: str, snapshot: Dict[str, Any]) -> None:
        if slot_id in self._app_slots:
            return
        self._app_slots[slot_id] = copy.deepcopy(snapshot)
        self._write_yaml(self._app_path, self._app_slots)

    def get_app_slot(self, slot_id: str) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._app_slots.get(slot_id))

    def save_app_slot(self, slot_id: str, data: Dict[str, Any]) -> bool:
        self._app_slots[slot_id] = copy.deepcopy(data)
        return self._write_yaml(self._app_path, self._app_slots)
