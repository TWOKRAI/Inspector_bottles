# -*- coding: utf-8 -*-
"""HistoryPresenter — презентер секции «История» для Settings таба.

Отвечает за:
- обновление таблицы из ActionBus.history()
- очистку истории через bus.clear()
- экспорт истории в CSV через view.get_save_path()

НЕ импортирует Qt-классы напрямую. Работает исключительно через HistoryView Protocol.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from .view import HistoryView

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)


class HistoryPresenter(TabPresenterBase[HistoryView, None]):
    """Презентер секции «История» — запросы ActionBus, CSV-экспорт.

    Получает зависимости через конструктор. Не содержит Qt-кода.
    """

    def __init__(
        self,
        *,
        view: HistoryView,
        rm=None,
        ui=None,
        ctx: "AppContext",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Обновить таблицу из ActionBus.history(n=50).

        Формирует строки (Время, Вкладка, Параметр, Значение) и передаёт в view.
        Также обновляет доступность кнопок «Сохранить» и «Очистить».
        """
        bus = self._ctx.action_bus()
        if bus is None:
            self._view.set_table_data([])
            self._view.set_save_enabled(False)
            self._view.set_clear_enabled(False)
            return

        actions = bus.history(n=50)
        rows: list[tuple[str, str, str, str]] = []
        for action in actions:
            ts = datetime.fromtimestamp(action.timestamp).strftime("%H:%M:%S")
            tab_name = action.register_name or action.action_type
            param = action.field_name or action.description
            value = action.forward_patch.get("value", "")
            if action.action_type == "recipe_apply":
                value = action.forward_patch.get("recipe_name", "recipe")
            rows.append((ts, tab_name, param, str(value)))

        self._view.set_table_data(rows)

        has_history = len(rows) > 0
        self._view.set_save_enabled(has_history)
        self._view.set_clear_enabled(bus.can_undo() or bus.can_redo())

        if has_history:
            self._view.scroll_to_bottom()

    def clear(self) -> None:
        """Очистить историю через bus.clear()."""
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.clear()

    def save_to_csv(self) -> None:
        """Экспортировать историю в CSV через view.get_save_path().

        Получает путь от view (та показывает QFileDialog), записывает CSV
        с разделителем «;» и кодировкой UTF-8-BOM для совместимости с Excel.
        """
        bus = self._ctx.action_bus()
        if bus is None:
            return

        actions = bus.history(n=0)  # все записи
        if not actions:
            return

        path = self._view.get_save_path()
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Время", "Вкладка", "Параметр", "Значение"])
                for action in actions:
                    ts = datetime.fromtimestamp(action.timestamp).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    tab = action.register_name or action.action_type
                    param = action.field_name or action.description
                    value = action.forward_patch.get("value", "")
                    if action.action_type == "recipe_apply":
                        value = action.forward_patch.get("recipe_name", "recipe")
                    writer.writerow([ts, tab, param, str(value)])
        except OSError:
            logger.exception("Ошибка при сохранении истории в CSV: %s", path)
