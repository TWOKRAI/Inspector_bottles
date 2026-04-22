# -*- coding: utf-8 -*-
"""
Привязка обработчиков к сигналам с идентификатором действия (str).

Паттерн для config-driven панелей: виджет эмитит один сигнал ``pyqtSignal(str)``
с ключом действия; приложение передаёт словарь ``{action_id: callable}`` и
опционально fallback для неизвестных ключей (например навигация по window_registry).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional


def connect_action_handlers(
    signal: Any,
    *,
    handlers: Mapping[str, Callable[[], None]],
    on_unmatched: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Подключить маршрутизацию: при эмите signal(action_id) вызывается handlers[action_id]
    или on_unmatched(action_id).

    Args:
        signal: pyqtSignal(str) или совместимый объект с .connect.
        handlers: Соответствие id действия → вызываемый без аргументов.
        on_unmatched: Вызывается для action_id, которого нет в handlers (например show_window).
    """

    def _dispatch(action_id: str) -> None:
        fn = handlers.get(action_id)
        if fn is not None:
            fn()
        elif on_unmatched is not None:
            on_unmatched(action_id)

    signal.connect(_dispatch)
