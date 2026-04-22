# multiprocess_prototype_v3/frontend/widgets/settings_profile_widget/view.py
"""Протокол вида для SettingsProfilePresenter (Phase 2, Task 2.3)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SettingsProfilePanelViewProtocol(Protocol):
    """Методы виджета профилей настроек, используемые презентером."""

    def current_profile_id(self) -> str:
        """Profile-id из текущего выбора QComboBox."""
        ...

    def refresh_table_rows(self) -> None:
        """Полностью обновить дерево параметров из презентера."""
        ...

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        """Установить текст колонки value у листа (откат/синхронизация)."""
        ...

    def show_error(self, message: str) -> None:
        """Показать диалог с сообщением об ошибке."""
        ...


__all__ = ["SettingsProfilePanelViewProtocol"]
