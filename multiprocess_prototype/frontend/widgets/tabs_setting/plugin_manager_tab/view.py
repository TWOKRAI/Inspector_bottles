"""Протокол вида для PluginManagerPresenter."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PluginManagerViewProtocol(Protocol):
    """Методы вкладки плагинов, вызываемые презентером."""

    def refresh_table(self, plugins: list[dict]) -> None:
        """Обновить таблицу каталога плагинов."""
        ...

    def show_plugin_detail(self, detail: dict) -> None:
        """Показать детали выбранного плагина в правой панели."""
        ...

    def clear_detail(self) -> None:
        """Очистить правую панель."""
        ...

    def set_status_text(self, text: str) -> None:
        """Установить текст в статусной строке toolbar."""
        ...

    def show_warning(self, title: str, text: str) -> None:
        """Показать предупреждение пользователю."""
        ...

    def get_current_filter(self) -> tuple[str | None, str]:
        """Текущий фильтр (category, search_text)."""
        ...
