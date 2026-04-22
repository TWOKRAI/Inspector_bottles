# multiprocess_prototype_v3/frontend/widgets/settings_profile_widget/presenter.py
"""Логика панели профилей настроек (Phase 2, Task 2.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_prototype_v3.frontend.managers.settings_profile_manager import ShmBudgetError
from multiprocess_prototype_v3.registers.constants import SETTINGS_REGISTER

from ..recipes_widget.recipe_rows import coerce_string_to_value, format_value_for_cell
from .model import SettingsProfileModel

if TYPE_CHECKING:
    from .view import SettingsProfilePanelViewProtocol


class SettingsProfilePresenter:
    """Обрабатывает действия пользователя в панели профилей настроек."""

    def __init__(
        self,
        *,
        view: SettingsProfilePanelViewProtocol,
        model: SettingsProfileModel,
    ) -> None:
        self._view = view
        self._model = model

    def on_apply_clicked(self) -> bool:
        """Применить выбранный профиль в регистры.

        Returns:
            True — успешно применено, False — ошибка.
        """
        profile_id = self._view.current_profile_id()
        try:
            self._model.profile_manager.switch_profile(profile_id, self._model.rm)
        except ShmBudgetError as e:
            self._view.show_error(str(e))
            return False
        except Exception as e:
            self._view.show_error(str(e))
            return False
        self._view.refresh_table_rows()
        return True

    def on_save_clicked(self) -> None:
        """Сохранить текущее состояние регистров в выбранный профиль."""
        profile_id = self._view.current_profile_id()
        rm = self._model.rm
        if rm is None:
            return
        # model_dump_all() → {register_name: {field: val}}, нужен только settings
        snapshot = rm.model_dump_all().get(SETTINGS_REGISTER, {})
        self._model.profile_manager.save_profile_snapshot(profile_id, snapshot)

    def on_default_clicked(self) -> bool:
        """Применить профиль 'default' в регистры.

        Returns:
            True — успешно применено, False — ошибка.
        """
        try:
            self._model.profile_manager.switch_profile("default", self._model.rm)
        except ShmBudgetError as e:
            self._view.show_error(str(e))
            return False
        except Exception as e:
            self._view.show_error(str(e))
            return False
        self._view.refresh_table_rows()
        return True

    def on_leaf_value_changed(
        self, group_id: str, field_id: str, column_key: str, text: str
    ) -> None:
        """Применить текст ячейки value к полю регистра.

        Парсит field_id вида "settings.camera_count", coerce-ит строку к нужному типу
        и записывает в rm. При ошибке откатывает ячейку к предыдущему значению.
        """
        if column_key != "value":
            return
        rm = self._model.rm
        if rm is None:
            return

        # Разобрать field_id = "register_name.field_name"
        parts = field_id.split(".", 1)
        if len(parts) != 2:
            return
        register_name, field_name = parts

        # Получить текущее значение как предыдущее
        reg = rm.get_register(register_name)
        if reg is None:
            return
        if hasattr(reg, "model_dump"):
            reg_data = reg.model_dump()
        elif isinstance(reg, dict):
            reg_data = reg
        else:
            return
        prev = reg_data.get(field_name)

        # Преобразовать строку к значению с учётом типа предыдущего
        new_val = coerce_string_to_value(text, prev)

        # Записать в регистр — set_field_value возвращает (bool, Optional[str])
        ok, _err = rm.set_field_value(register_name, field_name, new_val)
        if not ok:
            # Откат — показать предыдущее значение
            self._view.set_leaf_value_text(group_id, field_id, format_value_for_cell(prev))

    def build_tree_groups(self) -> list:
        """Данные для StructuredTwoLevelTreeWidget.set_data().

        Returns:
            Список кортежей (group_id, rows) — формат set_data.
        """
        rows = self._model.build_settings_rows()
        return [(SETTINGS_REGISTER, rows)]

    def refresh_from_registers(self) -> None:
        """Обновить таблицу из текущих значений регистров."""
        self._view.refresh_table_rows()


__all__ = ["SettingsProfilePresenter"]
