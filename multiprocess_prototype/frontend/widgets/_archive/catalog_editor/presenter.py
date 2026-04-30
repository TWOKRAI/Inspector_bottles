"""Презентер редактора каталога (MVP-заглушка)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .panel_widget import CatalogEditorWidget


class CatalogEditorPresenter:
    """Минимальный presenter для CatalogEditorWidget.

    Вся логика в MVP сосредоточена в виджете.
    Presenter зарезервирован под будущие команды (загрузка из регистров,
    синхронизация с chain_editor и т.п.).
    """

    def __init__(self, *, view: "CatalogEditorWidget") -> None:
        self._view = view

    def load_from_path(self, path: str) -> None:
        """Загрузить каталог из файла и отобразить в виджете."""
        from registers.processor.catalog.loader import load_catalog

        self._view.set_catalog_path(path)
        catalog = load_catalog(path)
        self._view.set_data(catalog)
