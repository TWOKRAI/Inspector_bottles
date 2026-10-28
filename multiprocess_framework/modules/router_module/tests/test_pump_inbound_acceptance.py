# -*- coding: utf-8 -*-
"""Task 1.8 (L-9, `plans/lifecycle-stop-ownership.md`) — слепая приёмка ``RouterManager.pump_inbound``, ДО реализации.

Контракт (стадия 0, `docs/reviews/2026-10-19_lifecycle-1.8-stage0.md` §4 D1, REDS R1-R6):
пока обработчик команды исполняется ВНУТРИ ``receive()`` и долго ждёт (стоп ребёнка), тот же
поток зовёт ``pump_inbound() -> int`` — он только переносит сообщения из каналов текущего
``receive`` в FIFO-буфер роутера. Разбор, middleware и диспетчеризация остаются следующему
``receive()``; порядок сохраняется; вне ``receive`` вызов ничего не читает; у буфера на канал
есть потолок, об упоре в него — один WARNING за эпизод.

Тесты пишутся вслепую: источник — публичные имена и числа REDS, реализация не читалась.
Всё, что может зависнуть, идёт в daemon-потоке с дедлайном join 12 с (зависание = упавший
ассерт, а не зависший прогон). Ожидаемые значения — литералы из REDS.

ОТКЛОНЕНИЕ ОТ ТЕКСТА R2 (см. отчёт): «m1 лежал раньше» выражено так: обработчик кладёт m1 и зовёт
pump (m1 уходит в буфер), затем кладёт m2, m3 и зовёт pump ещё раз; m4 кладётся после возврата
обработчика. Если бы m1 просто лежал в очереди до входа в ``receive``, тот же ``receive`` отдал бы его
сам, и «буфер раньше свежего опроса» (I6) нечем было бы наблюдать.
"""

from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable

from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager

DEADLINE_S = 12.0
SYS = ["system"]


# --------------------------------------------------------------------------- #
# Стенд
# --------------------------------------------------------------------------- #


def _bounded(fn: Callable[[], Any], limit_s: float = DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном join; исключение потока перебрасывается в тест."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — перебрасывается ниже, в потоке теста
            box["error"] = exc

    th = threading.Thread(target=_run, name="bounded-call", daemon=True)
    th.start()
    th.join(limit_s)
    assert not th.is_alive(), f"вызов не вернулся за {limit_s} с — завис"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _LoggerRecorder:
    """Менеджер ``logger`` роутера: пишет (уровень, текст). Это и есть наблюдаемая граница лога."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def _rec(self, level: str, message: Any) -> None:
        text = message() if callable(message) else str(message)
        with self._lock:
            self.records.append((level, text))

    def debug(self, message: Any, **_kw: Any) -> None:
        self._rec("debug", message)

    def info(self, message: Any, **_kw: Any) -> None:
        self._rec("info", message)

    def warning(self, message: Any, **_kw: Any) -> None:
        self._rec("warning", message)

    def error(self, message: Any, **_kw: Any) -> None:
        self._rec("error", message)

    def critical(self, message: Any, **_kw: Any) -> None:
        self._rec("critical", message)

    def warnings_about(self, needle: str) -> list[str]:
        with self._lock:
            return [text for level, text in self.records if level == "warning" and needle in text]


class _Rig:
    """Роутер «PM» с настоящими ``QueueChannel`` поверх ``queue.Queue`` по каналам system/data."""

    def __init__(self) -> None:
        self.q_system: Queue = Queue()
        self.q_data: Queue = Queue()
        self.log = _LoggerRecorder()
        self.router = RouterManager(manager_name="PM", process=SimpleNamespace(name="PM"))
        self.router.register_manager("logger", self.log)
        self.router.register_channel(QueueChannel("PM_system", self.q_system))
        self.router.register_channel(QueueChannel("PM_data", self.q_data))
        assert self.router.initialize() is True
        self.router.register_message_handler("probe.msg", lambda _m: None)
        self.handler_errors: list[BaseException] = []

    def on(self, key: str, body: Callable[[dict], Any]) -> None:
        """Обработчик команды; исключение тела не глотается роутером, а доходит до теста.

        ``receive`` ловит сбой обработчика и пишет в лог — без этого AttributeError «нет pump_inbound»
        выглядел бы как пустой результат, а не как причина красного.
        """

        def _guarded(msg: dict) -> None:
            try:
                body(msg)
            except BaseException as exc:  # noqa: BLE001
                self.handler_errors.append(exc)

        self.router.register_message_handler(key, _guarded)

    def raise_handler_errors(self) -> None:
        if self.handler_errors:
            raise self.handler_errors[0]

    @staticmethod
    def msg(seq: int, command: str = "probe.msg") -> dict:
        return {"type": "command", "command": command, "seq": seq}

    def receive(self, channel_types: list[str] | None = None) -> list[dict]:
        return self.router.receive(timeout=0.0, return_messages=False, channel_types=channel_types or SYS)

    def seqs(self, batch: list[dict]) -> list[int]:
        return [m["seq"] for m in batch if m.get("command") == "probe.msg"]

    def close(self) -> None:
        self.router.shutdown()


def _rig() -> _Rig:
    return _Rig()


# --------------------------------------------------------------------------- #
# R1. Вне receive pump ничего не читает
# --------------------------------------------------------------------------- #


def test_r1_pump_outside_receive_reads_nothing_and_next_receive_returns_all_five() -> None:
    rig = _rig()
    try:
        for i in range(5):
            rig.q_system.put(rig.msg(i))

        pumped = _bounded(lambda: rig.router.pump_inbound())
        assert pumped == 0, f"pump вне receive вернул {pumped}, ожидалось 0 (иначе гонка с настоящим приёмником)"
        assert rig.q_system.qsize() == 5, "pump вне receive вынул сообщения из очереди — он обязан ничего не читать"

        batch = _bounded(lambda: rig.receive())
        assert rig.seqs(batch) == [0, 1, 2, 3, 4]
    finally:
        rig.close()


# --------------------------------------------------------------------------- #
# R2. Порядок: буфер раньше свежего опроса
# --------------------------------------------------------------------------- #


def test_r2_order_is_stashed_first_then_fresh_pipe_content() -> None:
    rig = _rig()
    box: dict[str, Any] = {}

    def _block(_msg: dict) -> None:
        rig.q_system.put(rig.msg(1))
        box["pump_m1"] = rig.router.pump_inbound()  # m1 уходит в буфер
        rig.q_system.put(rig.msg(2))
        rig.q_system.put(rig.msg(3))
        box["pump_m23"] = rig.router.pump_inbound()  # m2, m3 — за m1
        box["in_pipe_after_pump"] = rig.q_system.qsize()

    rig.on("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})

        def _scenario() -> list[int]:
            rig.receive()  # исполняет probe.block, внутри — pump
            rig.q_system.put(rig.msg(4))  # m4 лежит в pipe, свежее всего буфера
            return rig.seqs(rig.receive()) + rig.seqs(rig.receive())

        order = _bounded(_scenario)
        rig.raise_handler_errors()
        assert box["in_pipe_after_pump"] == 0, "pump не вычерпал pipe внутри receive"
        assert box["pump_m1"] == 1 and box["pump_m23"] == 2, f"pump вернул {box}, ожидалось число перенесённых 1 и 2"
        assert order == [1, 2, 3, 4], f"порядок двух следующих receive {order}, ожидалось [1, 2, 3, 4]"
    finally:
        rig.close()


# --------------------------------------------------------------------------- #
# R3. pump не диспетчеризует
# --------------------------------------------------------------------------- #


def test_r3_pump_does_not_dispatch_command_it_moved() -> None:
    rig = _rig()
    order: list[str] = []

    def _block(_msg: dict) -> None:
        rig.q_system.put({"type": "command", "command": "probe.count", "seq": 0})
        rig.router.pump_inbound()
        order.append("block-end")

    rig.on("probe.block", _block)
    rig.on("probe.count", lambda _m: order.append("count"))
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})

        def _scenario() -> None:
            rig.receive()
            rig.raise_handler_errors()
            assert order == ["block-end"], f"команда исполнена внутри pump: {order}"
            rig.receive()

        _bounded(_scenario)
        rig.raise_handler_errors()
        assert order == ["block-end", "count"]
    finally:
        rig.close()


# --------------------------------------------------------------------------- #
# R4. pump уважает фильтр каналов текущего receive
# --------------------------------------------------------------------------- #


def test_r4_pump_drains_only_channels_of_the_current_receive_filter() -> None:
    rig = _rig()
    box: dict[str, Any] = {}

    def _block(_msg: dict) -> None:
        rig.q_data.put(rig.msg(7))
        rig.q_system.put(rig.msg(8))
        box["pumped"] = rig.router.pump_inbound()
        box["data_left"] = rig.q_data.qsize()
        box["system_left"] = rig.q_system.qsize()

    rig.on("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})

        def _scenario() -> tuple[list[int], list[int]]:
            rig.receive(["system"])
            system_batch = rig.receive(["system"])
            data_batch = rig.receive(["data"])
            return rig.seqs(system_batch), rig.seqs(data_batch)

        system_seqs, data_seqs = _bounded(_scenario)
        rig.raise_handler_errors()
        assert box["system_left"] == 0 and box["pumped"] == 1, f"system не вычерпан: {box}"
        assert box["data_left"] == 1, "pump вынул сообщение из data-канала, хотя receive смотрел только system"
        assert system_seqs == [8]
        assert data_seqs == [7], f"сообщение data-канала не дошло до receive(['data']): {data_seqs}"
    finally:
        rig.close()


# --------------------------------------------------------------------------- #
# R5, R6. Потолок буфера на канал
# --------------------------------------------------------------------------- #


class _BurstChannel(QueueChannel):
    """Канал, отдающий за вызов ``poll`` ровно ``per_call`` сообщений, пока включён (``active``).

    Выключен по умолчанию: приёмный такт ``receive`` его не трогает, пока обработчик не включит.
    """

    def __init__(self, name: str, per_call: int, total: int | None = None) -> None:
        super().__init__(name)
        self.per_call = per_call
        self.total = total
        self.active = False
        self.emitted = 0

    def poll(self, timeout: float = 0.0, max_items: int = 0) -> list[dict]:
        if not self.active:
            return []
        n = self.per_call
        if self.total is not None:
            n = min(n, self.total - self.emitted)
        batch = [{"type": "command", "command": "probe.flood", "seq": self.emitted + k} for k in range(n)]
        self.emitted += n
        return batch


def _flood_rig(channel: _BurstChannel) -> _Rig:
    rig = _rig()
    rig.router.register_channel(channel)
    rig.router.register_message_handler("probe.flood", lambda _m: None)
    return rig


def _drain_flood(rig: _Rig, max_receives: int = 20) -> list[int]:
    seqs: list[int] = []
    for _ in range(max_receives):
        batch = rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"])
        got = [m["seq"] for m in batch if m.get("command") == "probe.flood"]
        if not got:
            break
        seqs.extend(got)
    return seqs


def test_r5_endless_channel_is_capped_returns_zero_and_warns_once_with_channel_name() -> None:
    flood = _BurstChannel("PM_state", per_call=4096)
    rig = _flood_rig(flood)
    box: dict[str, Any] = {"returns": []}

    def _block(_msg: dict) -> None:
        flood.active = True
        try:
            for _ in range(5):
                box["returns"].append(rig.router.pump_inbound())
        finally:
            flood.active = False

    rig.on("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})

        def _scenario() -> list[int]:
            rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"])
            return _drain_flood(rig)

        delivered = _bounded(_scenario)
        rig.raise_handler_errors()
        assert flood.emitted <= 8191, f"из канала вынуто {flood.emitted} сообщений за 5 pump — потолка нет (≤ 8191)"
        assert box["returns"][-1] == 0, f"пятый pump у полного буфера вернул {box['returns'][-1]}, ожидалось 0"
        assert sum(box["returns"]) == flood.emitted, f"счёт pump {box['returns']} расходится с вынутым {flood.emitted}"
        assert len(delivered) == flood.emitted, "сообщения из буфера потеряны или продублированы"
        assert delivered == list(range(flood.emitted)), "порядок FIFO внутри канала нарушен"
        warns = rig.log.warnings_about("PM_state")
        assert len(warns) == 1, f"WARNING с именем канала: {len(warns)}, ожидался ровно 1 за эпизод: {warns}"
    finally:
        rig.close()


def test_r6_five_thousand_stashed_messages_come_out_as_4096_then_904() -> None:
    flood = _BurstChannel("PM_state", per_call=5000, total=5000)
    rig = _flood_rig(flood)
    box: dict[str, Any] = {}

    def _block(_msg: dict) -> None:
        flood.active = True
        try:
            box["pumped"] = rig.router.pump_inbound()
        finally:
            flood.active = False

    rig.on("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})

        def _scenario() -> tuple[list[int], list[int]]:
            rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"])
            first = rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"])
            second = rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"])
            as_seqs = lambda batch: [m["seq"] for m in batch if m.get("command") == "probe.flood"]  # noqa: E731
            return as_seqs(first), as_seqs(second)

        first, second = _bounded(_scenario)
        rig.raise_handler_errors()
        assert box["pumped"] == 5000, f"pump перенёс {box['pumped']} из 5000 отданных каналом одним вызовом"
        assert (len(first), len(second)) == (4096, 904), f"отдано {len(first)} и {len(second)}, ожидалось 4096 и 904"
        assert first + second == list(range(5000)), "порядок или состав сообщений нарушены"
    finally:
        rig.close()
