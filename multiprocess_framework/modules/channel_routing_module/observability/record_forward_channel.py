# -*- coding: utf-8 -*-
"""
RecordForwardChannel — форвардер записей наблюдаемости на GUI-подписчика (Ф5.20b).

Живой хвост hub→GUI: записи, дренированные из hub'а (log/stats) и пойманные
error-tap'ом (error/critical), пушатся адресно на GUI-процесс ОТДЕЛЬНЫМ каналом
``command="observability.record"`` — НЕ state-дельтой. Форма сообщения зеркалит
RouterPushChannel/state.changed: ``type=event`` + ``targets=[subscriber]`` +
``queue_type="system"`` → мост 1.1b → GuiProcess.register_message_handler →
DataReceiverBridge.dispatch(data_type="observability_record").

Симметрия со стором (Ф5.20a):
  - log/stats — пачкой из drain-петли (``push_batch``), уже в display-виде;
  - error/critical — по одной у tap'а на logger/error менеджерах (``write`` —
    IChannel: LogRecord-dict → display), min_level=ERROR.

Канал duck-typed: НЕ импортирует logger_module/router (только IChannel + router с
``send_async``); Dict at Boundary — наружу едет чистый pickle-safe dict.

QoS live-хвоста (решение 5.21 (d), 2026-07-10): хвост едет ``queue_type="system"``
и активатор держит подписку always-on на всех процессах — при error-storm это
теснит heartbeat (system-очередь никогда не дропается молча, Ф3.3). Отдельный
rate-limit/event-канал здесь НЕ вводим: единая QoS-модель профилей kind
(``reliability/history_depth/drop_policy/deadline_ms`` + drop-counter в state-дерево)
приземляется одним вскрытием в Ф7 G.4 (см. plan.md, «Cross-ref ObservabilityHub →
G.4»). Городить второй частный механизм до G.4 — это тот самый двойной проход по
доставке, которого консолидация Ф7 избегает. До G.4 живём на system-guard 3.3.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..interfaces import IChannel
from .observability_store import KIND_ERROR
from .record_display import log_record_to_display

FORWARD_COMMAND = "observability.record"


class RecordForwardChannel(IChannel):
    """Форвардер display-записей наблюдаемости через router на GUI-подписчика."""

    def __init__(
        self,
        *,
        router: Any,
        subscriber: str,
        sender: str = "",
        name: str = "observability_forward",
        kind: str = KIND_ERROR,
        command: str = FORWARD_COMMAND,
    ) -> None:
        """
        Args:
            router: RouterManager с ``send_async(dict, priority)`` — живой роутер процесса.
            subscriber: адрес получателя (GUI-процесс), ``targets=[subscriber]``.
            sender: имя процесса-источника (в сообщении и в ``data.process``).
            name: имя канала (хэндл tap'а для remove_log_tap).
            kind: kind при нормализации LogRecord-dict в ``write`` (обычно 'error').
            command: поле ``command`` пуша (роутинг-ключ у GUI-хендлера).
        """
        self._router = router
        self._subscriber = subscriber
        self._sender = sender or subscriber
        self._name = name
        self._kind = kind
        self._command = command

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "observability_forward"

    def write(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """IChannel (tap-путь): LogRecord-dict error/critical → display → push (одна запись)."""
        # process=sender (5.21 (c)): запись несёт процесс-источник, а не scope логгера.
        display = log_record_to_display(record_dict, kind=self._kind, process=self._sender)
        return self._push({"record": display})

    def push_batch(self, display_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Drain-путь: пачка уже-display записей (log/stats) → один push с ``records``."""
        if not display_records:
            return {"status": "success", "channel": self._name, "sent": 0}
        return self._push({"records": list(display_records)})

    def _push(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить адресный router-пуш подписчику (fire-and-forget, ошибки глушим)."""
        if self._router is None:
            return {"status": "error", "channel": self._name, "reason": "router=None"}
        message = {
            "type": "event",
            "sender": self._sender,
            "targets": [self._subscriber],
            "queue_type": "system",
            "command": self._command,
            "data": {"process": self._sender, **payload},
        }
        try:
            self._router.send_async(message, priority="normal")
            return {"status": "success", "channel": self._name}
        except Exception as exc:  # noqa: BLE001 — доставка хвоста best-effort
            return {"status": "error", "channel": self._name, "reason": str(exc)}

    def close(self) -> None:
        """IChannel-совместимость: канал закрывается без побочных эффектов (router общий)."""
