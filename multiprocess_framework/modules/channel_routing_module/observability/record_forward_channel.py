# -*- coding: utf-8 -*-
"""
RecordForwardChannel — форвардер записей наблюдаемости на GUI-подписчика (Ф5.20b).

Живой хвост hub→GUI: записи, дренированные из hub'а (log/stats) и пойманные
error-tap'ом (error/critical), пушатся адресно на GUI-процесс ОТДЕЛЬНЫМ каналом
``command="observability.record"`` — НЕ state-дельтой. Форма сообщения зеркалит
RouterPushChannel/state.changed: ``type=event`` + ``targets=[subscriber]`` +
``queue_type="observability"`` → мост 1.1b → GuiProcess.register_message_handler →
DataReceiverBridge.dispatch(data_type="observability_record").

Симметрия со стором (Ф5.20a):
  - log/stats — пачкой из drain-петли (``push_batch``), уже в display-виде;
  - error/critical — по одной у tap'а на logger/error менеджерах (``write`` —
    IChannel: LogRecord-dict → display), min_level задаёт подписчик (Ф6.х.5;
    дефолт ERROR — прежний захардкоженный порог был половиной дефекта З-1).

Batch-путь ЖИВ с задачи 2.1: у stats-слота hub'а появился второй владелец —
канал `hub_stats` StatsManager'а, кладущий туда снапшот окна агрегации. До того
слот принадлежал только WorkerManager'у, который метрик не шлёт, и push_batch не
вызывался ни разу. См. ADR-CRM-015.

Канал duck-typed: НЕ импортирует logger_module/router (только IChannel + router с
``send(dict) -> dict``); Dict at Boundary — наружу едет чистый pickle-safe dict.

Синхронный ``router.send`` (Task 0.5c, вердикт CTO 4.3b Q1-B) вместо
``send_async``: прежде ``_push`` отвечал ``success`` безусловно (500 ``success``
при 500 ``delivery_failed``). Ответ роутера судит ``outcome_of`` и отображается в
ответ форвардера: ``accepted`` -> ``success``, ``refused`` -> ``dropped``,
``failed`` / исключение / ``router=None`` -> ``error``. Цена — поток эмиттера ждёт
доставку; поэтому никто на пути ``send`` не должен логировать под своим локом
(см. ``SocketChannel._write_locked``: WARNING под ``_write_lock`` замыкался на
тот же лок через этот форвардер).

Ответ ``write()`` судится (Task 0.5a): ``ChannelRoutingManager._emit_to_taps``
толкует его через ``outcome_of``. ``{"status": "error"}`` — tap не принял запись,
счёт ``tap_write_errors`` менеджера; ``{"status": "dropped"}`` —
``tap_refused_records``. До 0.5a любой ответ без исключения засчитывался доставкой.

Счётчики (Task 0.5c): :meth:`RecordForwardChannel.counters_snapshot` — ``sent`` /
``dropped`` / ``send_failed`` в записях, ``messages`` в пушах; читает их секция
``introspect.observability.forwarders`` через проводку ``wire_observability_forward``.

QoS live-хвоста — ДОЛГ ЗАКРЫТ (Ф7.3, 2026-08-06). Прежнее решение 5.21 (d)
(2026-07-10) оставляло хвост на ``queue_type="system"`` при always-on подписке
на всех процессах, и при error-storm это тесняло heartbeat: system-очередь
никогда не дропается молча (Ф3.3), поэтому её сотня ячеек забивалась записями —
живой прогон Б-6 намерил 97 066 отказов доставки за ~25 минут. Теперь у груза
свой класс: ``queue_type="observability"`` (best_effort / drop_oldest, **глубина
256** — ``DEFAULT_QUEUES``/``HUB_QUEUES``) — переполнение хвоста роняет записи со
счётчиком, а не блокирует управление. Число 1024 из профиля ``qos.py`` относится
к ёмкости ``BoundedChannel`` хаба, а не к этой очереди; прежняя редакция называла
здесь его, и читатель получал глубину вчетверо больше настоящей. Потеря видна счётчиком ``observability_evicted``
и НЕ пишется записью: запись о потере записи поехала бы в тот же хвост и
усиливала бы шторм (третье звено петли Б-6).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from ..interfaces import IChannel, outcome_of
from .record_display import log_record_to_display

FORWARD_COMMAND = "observability.record"


def _router_reason(result: Any, default: str) -> str:
    """Текст причины из ответа роутера; без строки ``reason`` — ``default``."""
    if isinstance(result, dict):
        reason = result.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return default


class RecordForwardChannel(IChannel):
    """Форвардер display-записей наблюдаемости через router на GUI-подписчика."""

    def __init__(
        self,
        *,
        router: Any,
        subscriber: str,
        sender: str = "",
        name: str = "observability_forward",
        command: str = FORWARD_COMMAND,
    ) -> None:
        """
        Args:
            router: RouterManager с синхронным ``send(dict) -> dict`` — живой роутер процесса.
            subscriber: адрес получателя (GUI-процесс), ``targets=[subscriber]``.
            sender: имя процесса-источника (в сообщении и в ``data.process``).
            name: имя канала (хэндл tap'а для remove_tap).
            command: поле ``command`` пуша (роутинг-ключ у GUI-хендлера).

        Ответ ``write()`` (tap-путь) — словарь со ``status``; его судит
        вызывающий (``_emit_to_taps``, Task 0.5a): ``error`` — запись не
        принята, а не «доставлена с оговоркой».

        Параметра ``kind`` больше нет (Ф5.2, Б-4): вид записи считает её важность.
        Прежний дефолт ``'error'`` метил ошибкой ВСЁ, что прошло порог tap'а, —
        а порог с Ф6.х.5 задаёт подписчик, то есть под ``kind=error`` в хвост
        поехали INFO-записи (живая находка: INFO-снимок метрик).
        """
        self._router = router
        self._subscriber = subscriber
        self._sender = sender or subscriber
        self._name = name
        self._command = command
        self._counters_lock = threading.Lock()
        self._counters: Dict[str, int] = {"sent": 0, "messages": 0, "dropped": 0, "send_failed": 0}

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "observability_forward"

    def write(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """IChannel (tap-путь): LogRecord-dict error/critical → display → push (одна запись)."""
        # process=sender (5.21 (c)): запись несёт процесс-источник, а не имя
        # источника внутри процесса (`module`) и не группу логирования (`scope`).
        display = log_record_to_display(record_dict, process=self._sender)
        return self._push({"record": display}, 1)

    def push_batch(self, display_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Drain-путь: пачка уже-display записей (log/stats) → один push с ``records``."""
        if not display_records:
            return {"status": "success", "channel": self._name, "sent": 0}
        records = list(display_records)
        return self._push({"records": records}, len(records))

    def counters_snapshot(self) -> Dict[str, int]:
        """Счётчики форвардера (Task 0.5c): ``sent`` / ``dropped`` / ``send_failed`` — в
        записях, ``messages`` — в пушах, дошедших до ``router.send`` (включая бросивший).

        Инвариант: ``sent + dropped + send_failed`` == предложено записей. Снимок —
        копия под тем же локом, что и счёт.
        """
        with self._counters_lock:
            return dict(self._counters)

    def _count(self, key: str, records: int, *, reached_router: bool) -> None:
        # Лок берётся ПОСЛЕ возврата send, не вокруг него: держать его на
        # синхронной доставке значило бы сериализовать эмиттеров.
        with self._counters_lock:
            self._counters[key] += records
            if reached_router:
                self._counters["messages"] += 1

    def _push(self, payload: Dict[str, Any], records: int) -> Dict[str, Any]:
        """Отправить адресный пуш подписчику синхронным ``router.send`` и судить ответ.

        Исход ``outcome_of``: ``accepted`` -> ``success``; ``refused`` -> ``dropped``;
        ``failed``, исключение ``send`` и ``router=None`` -> ``error`` (Task 0.5c, вердикт
        CTO 4.3b Q1-B). Исключение наружу не уходит: доставка хвоста best-effort.
        ``reason`` не несёт входного значения: имя класса исключения или текст
        причины из ответа роутера. ``records`` — сколько записей в пуше (для счёта).
        """
        if self._router is None:
            self._count("send_failed", records, reached_router=False)
            return {"status": "error", "channel": self._name, "reason": "router=None"}
        message = {
            "type": "event",
            "sender": self._sender,
            "targets": [self._subscriber],
            # Ф7.3: своя очередь вместо never-drop system-почты (см. докстринг модуля).
            "queue_type": "observability",
            "command": self._command,
            "data": {"process": self._sender, **payload},
        }
        try:
            result = self._router.send(message)
        except Exception as exc:  # noqa: BLE001 — доставка хвоста best-effort
            self._count("send_failed", records, reached_router=True)
            # Только имя класса: текст исключения может нести входное значение.
            return {"status": "error", "channel": self._name, "reason": type(exc).__name__}
        outcome = outcome_of(result)
        if outcome == "accepted":
            self._count("sent", records, reached_router=True)
            return {"status": "success", "channel": self._name}
        if outcome == "refused":
            self._count("dropped", records, reached_router=True)
            return {"status": "dropped", "channel": self._name, "reason": _router_reason(result, "router refused")}
        self._count("send_failed", records, reached_router=True)
        return {"status": "error", "channel": self._name, "reason": _router_reason(result, "router failed")}

    def close(self) -> None:
        """IChannel-совместимость: канал закрывается без побочных эффектов (router общий)."""
