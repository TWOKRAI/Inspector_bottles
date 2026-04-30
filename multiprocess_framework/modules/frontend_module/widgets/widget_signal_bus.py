# multiprocess_framework\modules\frontend_module\widgets\widget_signal_bus.py
# -*- coding: utf-8 -*-
"""
Шина событий виджета — для внешних подписчиков (логгер, метрики, мониторинг ошибок).

Вынесена из `base_widget/`, чтобы `tabs/tab_widget` и другие виджеты без BaseWidget
могли использовать тот же канал без циклического импорта с `BaseWidget`.
"""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QObject, Signal


class WidgetSignalBus(QObject):
    """
    QObject с сигналами для подписки менеджеров.

    event_emitted(str, object): event_id (строка), payload (dict, str, None и т.д.).
    """

    event_emitted = Signal(str, object)
