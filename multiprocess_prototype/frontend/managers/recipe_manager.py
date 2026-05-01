"""RecipeManager — доменный менеджер рецептов для Inspector Bottles.

Тонкий subclass ConfigSnapshotManager с доменными методами (ensure_slot_from_registers,
ensure_app_slot_from_snapshot) и дефолтными путями относительно корня прототипа.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

from multiprocess_framework.modules.frontend_module.managers import ConfigSnapshotManager

_PROTO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_RECIPE_SLOT_ID = "default"


class RecipeManager(ConfigSnapshotManager):
    """Доменный менеджер рецептов для Inspector Bottles."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        app_recipes_path: Optional[str] = None,
    ) -> None:
        resolved_data = Path(data_path) if data_path else _PROTO_ROOT / "data" / "recipes.yaml"
        resolved_app = (
            Path(app_recipes_path)
            if app_recipes_path
            else resolved_data.parent / "settings_recipes.yaml"
        )
        super().__init__(resolved_data, resolved_app)

    # ------------------------------------------------------------------
    # Доменные методы (специфичны для Inspector Bottles)
    # ------------------------------------------------------------------

    def ensure_slot_from_registers(self, registers_manager: Any, slot_id: str) -> None:
        """Создать слот из текущих значений регистров если он не существует."""
        if slot_id in self._slots:
            return
        try:
            snapshot: Dict[str, Any] = {}
            for name, reg in registers_manager.registers.items():
                snapshot[name] = reg.model_dump()
            self.save_slot(slot_id, snapshot)
        except Exception:
            pass

    def ensure_app_slot_from_snapshot(self, slot_id: str, snapshot: Dict[str, Any]) -> None:
        """Создать app-слот из snapshot если он не существует."""
        if slot_id in self._app_slots:
            return
        self._app_slots[slot_id] = copy.deepcopy(snapshot)
        self._write_yaml(self._app_path, self._app_slots)
