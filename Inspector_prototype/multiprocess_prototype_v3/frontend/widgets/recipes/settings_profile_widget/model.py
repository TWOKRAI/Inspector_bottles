# multiprocess_prototype_v3/frontend/widgets/settings_profile_widget/model.py
"""Модель панели профилей настроек (Phase 2, Task 2.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multiprocess_prototype_v3.registers.constants import SETTINGS_REGISTER

from ..recipes_widget.recipe_rows import format_value_for_cell
from ..recipes_widget.slot_combo_model import RecipeSlotComboModel
from .schemas import SettingsProfileTabConfig

_DEFAULT_PROFILE_ID = "default"


@dataclass
class SettingsProfileModel:
    """Данные панели профилей настроек приложения.

    Attributes:
        ui: UI-строки и настройки панели (SettingsProfileTabConfig).
        profile_manager: duck-typed SettingsProfileManagerProtocol (или None).
        rm: duck-typed RegistersManager (или None).
        combo_model: модель ComboBox профилей.
    """

    ui: SettingsProfileTabConfig
    profile_manager: Any  # SettingsProfileManagerProtocol duck-typed
    rm: Any  # RegistersManager duck-typed, может быть None
    combo_model: RecipeSlotComboModel

    def compute_initial_profile_id(self) -> str:
        """Текущий profile_id из менеджера или 'default' как fallback."""
        pm = self.profile_manager
        if pm is not None and hasattr(pm, "get_current_profile_id"):
            try:
                pid = pm.get_current_profile_id()
                if pid is not None:
                    return str(pid)
            except Exception:
                pass
        return _DEFAULT_PROFILE_ID

    def build_settings_rows(self) -> list[dict]:
        """Строки таблицы из регистра SETTINGS_REGISTER.

        Returns:
            Список словарей с ключами: field_id, param, value, info,
            register_name, field_name, _value_editable.
            Пустой список если rm is None.
        """
        if self.rm is None:
            return []

        reg = self.rm.get_register(SETTINGS_REGISTER)
        if reg is None:
            return []

        # Получаем данные из регистра
        if hasattr(reg, "model_dump"):
            data = reg.model_dump()
        elif isinstance(reg, dict):
            data = reg
        else:
            return []

        rows: list[dict] = []
        for field_name, value in data.items():
            # Получаем метаданные поля для label и info
            label = field_name
            info = ""
            if hasattr(reg, "get_field_meta"):
                fm = reg.get_field_meta(field_name)
                if fm is not None:
                    label = str(getattr(fm, "label", field_name) or field_name)
                    info = str(getattr(fm, "info", "") or "")

            field_id = f"{SETTINGS_REGISTER}.{field_name}"
            editable = value is None or isinstance(value, (bool, int, float, str))

            rows.append(
                {
                    "field_id": field_id,
                    "param": label,
                    "value": format_value_for_cell(value),
                    "info": info,
                    "register_name": SETTINGS_REGISTER,
                    "field_name": field_name,
                    "_value_editable": editable,
                }
            )
        return rows


__all__ = ["SettingsProfileModel"]
