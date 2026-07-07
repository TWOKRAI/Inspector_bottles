# -*- coding: utf-8 -*-
"""UiEventTap — глобальный фильтр UI-событий для отладки фронтенда агентами.

Ловит взаимодействия пользователя на уровне QApplication event filter
(по образцу WheelGuard прототипа): отпускание мыши на QAbstractButton
(кнопка нажата) и на QTabBar (переключение таба). Каждое событие
превращается в плоский dict и уходит в инжектированный ``send``-колбэк.

Дизайн под многопоточность процесса:
- Фильтр создаётся и устанавливается ОДИН раз в Qt main thread на старте GUI
  (как WheelGuard) и по умолчанию ВЫКЛЮЧЕН — прод-поведение не меняется.
- Команды ``ui.tap.subscribe/unsubscribe`` приходят в message_processor-потоке;
  они лишь переключают ``enable/disable`` (присваивание атрибутов — атомарно
  под GIL), НЕ трогая Qt-объекты из чужого потока. eventFilter при выключенном
  тапе — одна проверка ``self._send is None``.
- ``send`` — обычно ``RouterPushChannel.write`` (logger_module, Ф1.5): доставка
  targets=[subscriber]+queue_type=system, Dict at Boundary.

Фильтр НИКОГДА не поглощает события (всегда возвращает False) и глотает свои
ошибки — отладочная инструментация не имеет права ломать GUI.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractButton, QTabBar, QWidget

# Колбэк доставки события подписчику (обычно RouterPushChannel.write).
SendCallback = Callable[[Dict[str, Any]], Any]


def _widget_path(w: QWidget, max_depth: int = 8) -> str:
    """Путь виджета по objectName/классам вверх до окна — адрес кнопки для агента."""
    parts: list[str] = []
    node: Optional[QObject] = w
    for _ in range(max_depth):
        if node is None:
            break
        name = node.objectName() or type(node).__name__
        parts.append(name)
        node = node.parent()
    return "/".join(reversed(parts))


class UiEventTap(QObject):
    """Фильтр QApplication: нажатия кнопок и переключения табов → send(dict).

    Использование (в run_gui, рядом с WheelGuard)::

        tap = UiEventTap(app)
        app.installEventFilter(tap)
        process._ui_event_tap = tap   # команды ui.tap.* включают/выключают

    Пока ``enable()`` не вызван — фильтр no-op (одна проверка на событие).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._send: Optional[SendCallback] = None
        self._subscriber: str = ""
        # Счётчики для диагностики (introspect через ui.tap.subscribe-ответ/пинг).
        self.events_sent = 0
        self.send_errors = 0
        # Сквозной seq всех событий тапа (жест + намерение через emit_event):
        # упорядочивание «клик → команда» без гонок ts (debug-plane v1).
        self._seq = 0

    # ------------------------------------------------------------------ #
    #  Управление (зовётся из message_processor-потока — только атрибуты)  #
    # ------------------------------------------------------------------ #

    def enable(self, subscriber: str, send: SendCallback) -> None:
        """Включить тап: события едут в ``send`` (последний подписчик выигрывает)."""
        self._subscriber = subscriber
        self._send = send  # присваивание последним: фильтр видит согласованное состояние

    def disable(self) -> None:
        """Выключить тап (фильтр остаётся установленным, но no-op)."""
        self._send = None
        self._subscriber = ""

    @property
    def enabled(self) -> bool:
        return self._send is not None

    @property
    def subscriber(self) -> str:
        return self._subscriber

    # ------------------------------------------------------------------ #
    #  Публикация                                                          #
    # ------------------------------------------------------------------ #

    def emit_event(self, event: Dict[str, Any]) -> bool:
        """Отправить ui-событие подписчику (используется фильтром и ui.tap.ping).

        Возвращает True, если send отработал без исключения. Ошибки считаются
        и глотаются — отладка не роняет GUI.
        """
        send = self._send
        if send is None:
            return False
        self._seq += 1
        payload = {"ts": time.time(), "seq": self._seq, **event}
        try:
            send(payload)
            self.events_sent += 1
            return True
        except Exception:  # noqa: BLE001 — best-effort, GUI важнее доставки
            self.send_errors += 1
            return False

    # ------------------------------------------------------------------ #
    #  Qt event filter (Qt main thread)                                    #
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt API
        if self._send is None or event.type() != QEvent.Type.MouseButtonRelease:
            return False
        try:
            self._capture(obj, event)
        except Exception:  # noqa: BLE001 — инструментация не ломает GUI
            self.send_errors += 1
        return False  # событие НИКОГДА не поглощается

    def _capture(self, obj: QObject, event: QEvent) -> None:
        """Распознать интересный виджет по цепочке родителей и отправить событие."""
        node: Optional[QObject] = obj
        for _ in range(6):  # клик мог прийти в дочерний QLabel/viewport кнопки
            if node is None:
                return
            if isinstance(node, QAbstractButton):
                self.emit_event(
                    {
                        "kind": "button",
                        "text": node.text(),
                        "widget": node.objectName() or type(node).__name__,
                        "path": _widget_path(node),
                        "checked": node.isChecked() if node.isCheckable() else None,
                    }
                )
                return
            if isinstance(node, QTabBar):
                # Таб — по координате клика (currentIndex может ещё не примениться).
                idx = -1
                if node is obj and hasattr(event, "position"):
                    idx = node.tabAt(event.position().toPoint())
                if idx < 0:
                    idx = node.currentIndex()
                self.emit_event(
                    {
                        "kind": "tab",
                        "text": node.tabText(idx),
                        "index": idx,
                        "widget": node.objectName() or type(node).__name__,
                        "path": _widget_path(node),
                    }
                )
                return
            node = node.parent()
