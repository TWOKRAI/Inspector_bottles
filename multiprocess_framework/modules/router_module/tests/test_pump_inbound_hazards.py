# -*- coding: utf-8 -*-
"""Task 1.8 (L-9, ADR-RTR-014) — тесты-ловушки автора ``RouterManager.pump_inbound``.

Приёмку (R1-R6) писал слепой тестер; здесь — то, что ломается тихо при правке буфера:
  * pump из ДРУГОГО потока, пока приёмный поток внутри receive, ничего не читает и не рвёт порядок;
  * исключение в обработчике не теряет буфер: следующий receive отдаёт его по порядку;
  * вложенный receive с другим фильтром не подменяет фильтр внешнего (pump после него — по внешнему);
  * pump после возврата из receive (depth снова 0) ничего не читает;
  * сбой poll канала не бросает из pump и пишется в лог, остальные каналы вычерпываются;
  * эпизод «буфер полон» сбрасывается, когда буфер опустел: следующий упор снова даёт WARNING.
"""

from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable

from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager

DEADLINE_S = 12.0


def _bounded(fn: Callable[[], Any], limit_s: float = DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном join; исключение потока перебрасывается в тест."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — перебрасывается ниже
            box["error"] = exc

    th = threading.Thread(target=_run, name="bounded-call", daemon=True)
    th.start()
    th.join(limit_s)
    assert not th.is_alive(), f"вызов не вернулся за {limit_s} с — завис"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _Log:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _rec(self, level: str, message: Any) -> None:
        self.records.append((level, message() if callable(message) else str(message)))

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

    def texts(self, level: str, needle: str) -> list[str]:
        return [t for lv, t in self.records if lv == level and needle in t]


class _Rig:
    def __init__(self) -> None:
        self.q_system: Queue = Queue()
        self.q_data: Queue = Queue()
        self.log = _Log()
        self.router = RouterManager(manager_name="PM", process=SimpleNamespace(name="PM"))
        self.router.register_manager("logger", self.log)
        self.router.register_channel(QueueChannel("PM_system", self.q_system))
        self.router.register_channel(QueueChannel("PM_data", self.q_data))
        assert self.router.initialize() is True
        self.router.register_message_handler("probe.msg", lambda _m: None)

    @staticmethod
    def msg(seq: int, command: str = "probe.msg") -> dict:
        return {"type": "command", "command": command, "seq": seq}

    def receive(self, channel_types: list[str] | None = None) -> list[dict]:
        return self.router.receive(timeout=0.0, return_messages=False, channel_types=channel_types or ["system"])

    @staticmethod
    def seqs(batch: list[dict]) -> list[int]:
        return [m["seq"] for m in batch if m.get("command") == "probe.msg"]

    def close(self) -> None:
        self.router.shutdown()


def test_pump_from_another_thread_while_receive_is_inside_a_handler_reads_nothing() -> None:
    rig = _Rig()
    inside, release = threading.Event(), threading.Event()
    box: dict[str, Any] = {}

    def _block(_msg: dict) -> None:
        inside.set()
        assert release.wait(DEADLINE_S), "тест не отпустил обработчик"

    rig.router.register_message_handler("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})
        receiver = threading.Thread(target=rig.receive, name="receiver", daemon=True)
        receiver.start()
        assert inside.wait(DEADLINE_S), "обработчик не стартовал"

        rig.q_system.put(rig.msg(1))
        rig.q_system.put(rig.msg(2))
        box["foreign_pump"] = _bounded(lambda: rig.router.pump_inbound())  # поток вне receive: depth == 0
        box["left"] = rig.q_system.qsize()

        release.set()
        receiver.join(DEADLINE_S)
        assert not receiver.is_alive()
        assert box["foreign_pump"] == 0, f"pump чужого потока вернул {box['foreign_pump']}, ожидалось 0"
        assert box["left"] == 2, "pump чужого потока вынул сообщения у приёмного потока"
        assert rig.seqs(_bounded(rig.receive)) == [1, 2], "порядок нарушен после чужого pump"
    finally:
        release.set()
        rig.close()


def test_stash_survives_exception_in_handler_and_comes_out_in_order() -> None:
    rig = _Rig()

    def _boom(_msg: dict) -> None:
        rig.q_system.put(rig.msg(1))
        rig.q_system.put(rig.msg(2))
        rig.router.pump_inbound()
        raise RuntimeError("handler exploded after pump")

    rig.router.register_message_handler("probe.boom", _boom)
    try:
        rig.q_system.put({"type": "command", "command": "probe.boom"})

        def _scenario() -> list[int]:
            try:
                rig.receive()  # сбой обработчика роутер ловит сам; если пробросит — буфер всё равно цел
            except RuntimeError:
                pass
            rig.q_system.put(rig.msg(3))
            return rig.seqs(rig.receive()) + rig.seqs(rig.receive())

        assert _bounded(_scenario) == [1, 2, 3], "буфер потерян или переупорядочен после сбоя обработчика"
    finally:
        rig.close()


def test_nested_receive_with_other_filter_does_not_replace_the_outer_filter_for_pump() -> None:
    rig = _Rig()
    box: dict[str, Any] = {}

    def _outer(_msg: dict) -> None:
        rig.router.receive(timeout=0.0, return_messages=False, channel_types=["data"])  # вложенный, другой фильтр
        rig.q_data.put(rig.msg(7))
        rig.q_system.put(rig.msg(8))
        box["pumped"] = rig.router.pump_inbound()  # фильтр внешнего receive: только system
        box["data_left"] = rig.q_data.qsize()

    rig.router.register_message_handler("probe.outer", _outer)
    try:
        rig.q_system.put({"type": "command", "command": "probe.outer"})
        _bounded(rig.receive)
        assert box["pumped"] == 1, f"pump после вложенного receive перенёс {box['pumped']}, ожидалось 1 (system)"
        assert box["data_left"] == 1, "pump после вложенного receive вынул data: фильтр внешнего потерян"
    finally:
        rig.close()


def test_pump_after_receive_returned_reads_nothing() -> None:
    rig = _Rig()
    try:
        _bounded(rig.receive)
        rig.q_system.put(rig.msg(1))
        assert _bounded(lambda: rig.router.pump_inbound()) == 0
        assert rig.q_system.qsize() == 1, "pump после выхода из receive читает pipe — depth/filter не сброшены"
    finally:
        rig.close()


class _BrokenChannel(QueueChannel):
    def poll(self, timeout: float = 0.0, max_items: int = 0) -> list[dict]:
        raise OSError("pipe is broken")


def test_poll_failure_in_pump_does_not_raise_and_other_channels_are_still_drained() -> None:
    rig = _Rig()
    rig.router.register_channel(_BrokenChannel("PM_state"))
    box: dict[str, Any] = {}

    def _block(_msg: dict) -> None:
        rig.q_system.put(rig.msg(5))
        box["pumped"] = rig.router.pump_inbound()  # PM_state бросает, PM_system вычерпывается

    rig.router.register_message_handler("probe.block", _block)
    try:
        rig.q_system.put({"type": "command", "command": "probe.block"})
        _bounded(lambda: rig.router.receive(timeout=0.0, return_messages=False, channel_types=["system", "state"]))
        assert box["pumped"] == 1, f"pump вернул {box['pumped']}, ожидалось 1 (сбой одного канала не мешает другим)"
        assert rig.log.texts("error", "PM_state"), f"сбой poll не записан в лог: {rig.log.records}"
    finally:
        rig.close()


class _Flood(QueueChannel):
    """Отдаёт по ``per_call`` сообщений за ``poll``, пока ``active``."""

    def __init__(self, name: str, per_call: int) -> None:
        super().__init__(name)
        self.per_call = per_call
        self.active = False
        self.emitted = 0

    def poll(self, timeout: float = 0.0, max_items: int = 0) -> list[dict]:
        if not self.active:
            return []
        batch = [{"type": "command", "command": "probe.msg", "seq": self.emitted + k} for k in range(self.per_call)]
        self.emitted += self.per_call
        return batch


def test_full_stash_warning_is_per_episode_and_repeats_after_the_stash_was_drained() -> None:
    rig = _Rig()
    flood = _Flood("PM_state", per_call=4096)
    rig.router.register_channel(flood)
    both = ["system", "state"]

    def _episode(_msg: dict) -> None:
        flood.active = True
        try:
            for _ in range(3):  # 1-й наполняет до потолка, 2-й и 3-й упираются: WARNING один
                rig.router.pump_inbound()
        finally:
            flood.active = False

    rig.router.register_message_handler("probe.episode", _episode)
    try:

        def _scenario() -> None:
            for _ in range(2):
                rig.q_system.put({"type": "command", "command": "probe.episode"})
                rig.router.receive(timeout=0.0, return_messages=False, channel_types=both)  # исполняет эпизод
                rig.router.receive(timeout=0.0, return_messages=False, channel_types=both)  # опустошает буфер

        _bounded(_scenario)
        warns = rig.log.texts("warning", "PM_state")
        assert len(warns) == 2, f"WARNING на два разделённых эпизода: {len(warns)}, ожидалось 2: {warns}"
    finally:
        rig.close()
