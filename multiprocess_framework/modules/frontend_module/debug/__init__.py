# -*- coding: utf-8 -*-
"""frontend_module.debug — отладочная инструментация GUI для агентов (backend_ctl).

UiEventTap ловит взаимодействия пользователя (кнопки, табы) на уровне
QApplication-фильтра и пушит их подписчику (внешнему driver'у) тем же
маршрутом, что log-tail (Ф1.5): targets=[subscriber] + queue_type=system →
мост 1.1b / relay 1.7 → события `ui.event` в driver.events() / MCP `events`.
"""

from .intent_taps import CommandSenderTap
from .tap_commands import register_ui_tap_commands
from .ui_event_tap import UiEventTap

__all__ = ["CommandSenderTap", "UiEventTap", "register_ui_tap_commands"]
