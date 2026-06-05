"""DataReceiverBridge — мост worker thread → Qt main thread.

Использует внутренний Signal + явный QueuedConnection для гарантированной
доставки из произвольного Python thread (не обязательно QThread).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class DataReceiverBridge(QObject):
    """Классифицирует IPC-сообщения и вызывает callbacks в Qt main thread.

    Используется из worker thread data_receiver.
    Внутренний _deliver signal с Qt.QueuedConnection гарантирует
    вызов _on_deliver в main thread даже из non-QThread.
    """

    _deliver = Signal(object)

    # Публичные сигналы для подписки извне
    frame_received = Signal(object)
    state_updated = Signal(object)
    command_response = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_cb: Callable | None = None
        self._state_cb: Callable | None = None
        self._command_cb: Callable | None = None
        # §11.15: multi-subscriber для state. Раньше второй потребитель
        # (topology_bridge) подключался обёрткой-closure поверх single-slot
        # set_state_callback (скрытый fan-out _state_multiplexer в app.py) —
        # теперь явный список слушателей: каждый подписчик регистрируется
        # отдельно через add_state_listener, без перехвата чужого callback.
        self._state_listeners: list[Callable] = []
        # AutoConnection: DirectConnection в main thread, QueuedConnection из worker thread
        self._deliver.connect(self._on_deliver, Qt.ConnectionType.AutoConnection)

    def set_frame_callback(self, cb: Callable) -> None:
        self._frame_cb = cb

    def set_state_callback(self, cb: Callable) -> None:
        """Основной (первичный) state-callback. Сохранён для обратной совместимости;
        дополнительные потребители — через add_state_listener (§11.15)."""
        self._state_cb = cb

    def add_state_listener(self, cb: Callable) -> None:
        """Добавить ещё одного слушателя state-сообщений (multi-subscriber, §11.15).

        Вызывается в Qt main thread (после _state_cb) на каждое state-сообщение.
        Идемпотентность не гарантируется — один и тот же cb добавляется один раз
        на стороне вызывающего.
        """
        if cb not in self._state_listeners:
            self._state_listeners.append(cb)

    def set_command_callback(self, cb: Callable) -> None:
        self._command_cb = cb

    def dispatch(self, msg_dict: dict) -> None:
        """Из worker thread — отправить в main thread через internal signal."""
        data_type = msg_dict.get("data_type", "")
        if data_type in ("frame_ready", "frame") or "frame" in msg_dict:
            kind = "frame"
        elif data_type in ("status", "state_changed", "fps_update", "state_delta"):
            kind = "state"
        else:
            kind = "command"
        self._deliver.emit((kind, msg_dict))

    @Slot(object)
    def _on_deliver(self, payload: tuple) -> None:
        """Slot в main thread — вызвать нужный callback и emit публичный signal."""
        kind, msg_dict = payload
        if kind == "frame":
            if self._frame_cb:
                self._frame_cb(msg_dict)
            self.frame_received.emit(msg_dict)
        elif kind == "state":
            if self._state_cb:
                self._state_cb(msg_dict)
            for listener in self._state_listeners:
                listener(msg_dict)
            self.state_updated.emit(msg_dict)
        elif kind == "command":
            if self._command_cb:
                self._command_cb(msg_dict)
            self.command_response.emit(msg_dict)
