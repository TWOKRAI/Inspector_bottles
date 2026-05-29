# -*- coding: utf-8 -*-
"""HistoryPresenter — презентер секции «История» для Settings таба.

Отвечает за:
- обновление таблицы из domain-истории (``services.commands.history()``)
- очистку истории через ``services.commands.clear_history()``
- экспорт истории в CSV через view.get_save_path()

НЕ импортирует Qt-классы напрямую. Работает исключительно через HistoryView Protocol.

G.4.4: переведён с legacy ActionBus на domain ``CommandDispatcher``
(``services.commands``). Запись истории — ``HistoryEntry`` (label / command_type /
timestamp), таблица показывает 3 колонки: Время / Тип / Описание. Фантомный
``services.commands.action_bus()`` (метода нет — всегда None) удалён.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from .view import HistoryView

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices

logger = logging.getLogger(__name__)


class HistoryPresenter(TabPresenterBase[HistoryView, None]):
    """Презентер секции «История» — запросы domain-истории, CSV-экспорт.

    Получает зависимости через конструктор. Не содержит Qt-кода.

    G.4.4: источник истории — domain ``CommandDispatcher`` (``services.commands``),
    единая глобальная undo/redo-история приложения.
    """

    def __init__(
        self,
        *,
        view: HistoryView,
        rm=None,
        ui=None,
        services: "AppServices",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._services = services

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Обновить таблицу из domain-истории (последние 50 записей).

        Формирует строки (Время, Тип, Описание) из ``HistoryEntry`` и передаёт
        в view. Также обновляет доступность кнопок «Сохранить» и «Очистить».
        """
        commands = self._services.commands
        entries = commands.history(50)
        rows = [
            (
                datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S"),
                entry.command_type,
                entry.label,
            )
            for entry in entries
        ]

        self._view.set_table_data(rows)

        has_history = len(rows) > 0
        self._view.set_save_enabled(has_history)
        self._view.set_clear_enabled(commands.can_undo() or commands.can_redo())

        if has_history:
            self._view.scroll_to_bottom()

    def clear(self) -> None:
        """Очистить undo/redo-историю через domain-диспетчер."""
        self._services.commands.clear_history()

    def save_to_csv(self) -> None:
        """Экспортировать историю в CSV через view.get_save_path().

        Получает путь от view (та показывает QFileDialog), записывает CSV
        с разделителем «;» и кодировкой UTF-8-BOM для совместимости с Excel.
        """
        entries = self._services.commands.history(0)  # все записи
        if not entries:
            return

        path = self._view.get_save_path()
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Время", "Тип", "Описание"])
                for entry in entries:
                    ts = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([ts, entry.command_type, entry.label])
        except OSError:
            logger.exception("Ошибка при сохранении истории в CSV: %s", path)
