# -*- coding: utf-8 -*-
"""frontend_module.debug — отладочная инструментация GUI для агентов (backend_ctl).

UiEventTap ловит взаимодействия пользователя (кнопки, табы) на уровне
QApplication-фильтра и пушит их подписчику (внешнему driver'у) тем же
маршрутом, что log-tail (Ф1.5): targets=[subscriber] + queue_type=system →
мост 1.1b / relay 1.7 → события `ui.event` в driver.events() / MCP `events`.
"""

from .ui_event_tap import UiEventTap
from .tap_commands import register_ui_tap_commands

__all__ = ["UiEventTap", "register_ui_tap_commands"]
