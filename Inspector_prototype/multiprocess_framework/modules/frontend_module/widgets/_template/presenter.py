# -*- coding: utf-8 -*-
"""
Presenter виджета — бизнес-логика UI без прямого доступа к Qt.

TODO: заменить TemplatePresenter на имя своего виджета.
TODO: добавить методы обработки событий и обновления view.

Presenter получает model (данные) и view (интерфейс отображения).
Паттерн: model обновляет данные → presenter вызывает методы view для отображения.
"""
from __future__ import annotations

from typing import Any


class TemplatePresenter:
    """
    Presenter виджета.

    TODO: добавить обработчики событий и логику обновления.

    Типичные методы:
        - on_activated() — вызывается после инициализации UI
        - on_<button>_clicked() — обработчики кнопок
        - update_<section>() — обновление секций view
        - sync_from_registers() — синхронизация данных из регистров
    """

    def __init__(self, model: Any, view: Any) -> None:
        self._model = model
        self._view = view

    def on_activated(self) -> None:
        """
        Вызывается после полной инициализации UI (из _on_presenter_ready).

        TODO: начальная загрузка данных, обновление view.
        """
        pass
