# -*- coding: utf-8 -*-
"""Контракт-тест I1 «исход звена» (Task 0.1, слепой RED).

Четыре звена в паре «здоров / сломан». Тест читает ИМЕНОВАННЫЙ счётчик потерь
(не ``outcome_of``): у звеньев разные носители исхода (число, булево, ``None``,
статус), одним толкователем их не прочесть. Сломанное звено обязано быть не
принято, и именованный счётчик обязан вырасти на число из таблицы «Форма пробы»
(README «Исход звена»); здоровое — принято, счётчик не растёт.

Звенья: ``file_channel_enospc``, ``forward_dead_router``,
``logger_after_shutdown``, ``bridge_session_gone``.

Каждый параметр: свой ``tmp_path``, свой ``LoggerManager`` (``shutdown()`` в
``finally``), ``log_directory`` = ``tmp_path``. Сценарий идёт в daemon-потоке с
``join(5)``: зависший ``shutdown`` — красный тест, а не зависший прогон.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.channel_routing_module.observability import RecordForwardChannel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import SocketBridgeAdapter

_JOIN_DEADLINE_S = 5.0

_IDS = ["file_channel_enospc", "forward_dead_router", "logger_after_shutdown", "bridge_session_gone"]

# Литералы из таблицы «Форма пробы»: на сколько вырастает счётчик потерь у сломанного звена.
_LOSS_DELTA_BROKEN = {
    "file_channel_enospc": 4,  # две записи x два канала (console, system_file)
    "forward_dead_router": 1,
    "logger_after_shutdown": 1,
    "bridge_session_gone": 1,
}


# ---------------------------------------------------------------------------
# Фейки и пробы
# ---------------------------------------------------------------------------


class _EnospcStream:
    """Поток, бросающий «диск полон» на запись."""

    def write(self, data):
        raise OSError(28, "No space left on device")

    def flush(self):
        return None

    def tell(self):
        # RotatingFileHandler.shouldRollover спрашивает позицию до записи:
        # без tell() отказ случился бы не на OSError(28), а на AttributeError.
        return 0

    def seek(self, *args):
        return 0


class _ForwardRouter:
    """Синхронный фейк роутера для RecordForwardChannel."""

    def __init__(self, broken: bool):
        self._broken = broken

    def send_async(self, message, priority="normal"):
        if self._broken:
            raise ConnectionError("router dead")
        return None

    def send(self, message):
        if self._broken:
            raise ConnectionError("router dead")
        return {"status": "success"}


class _BridgeRouter:
    """Синхронный фейк роутера для SocketBridgeAdapter."""

    def __init__(self, broken: bool):
        self._broken = broken

    def request(self, msg, timeout=None):
        return {"success": True}

    def send(self, msg):
        if self._broken:
            return {"status": "error", "reason": "session not connected"}
        return {"status": "success"}


class _Probe(BaseManager, ObservableMixin):
    def __init__(self, lm):
        BaseManager.__init__(self, "probe")
        ObservableMixin.__init__(self, managers={"logger": lm}, config={"logger": True})

    def initialize(self):
        self.is_initialized = True
        return True

    def _on_shutdown(self):
        return True


# ---------------------------------------------------------------------------
# Сценарии: каждый возвращает (accepted, delta именованного счётчика, extras)
# ---------------------------------------------------------------------------


def _scenario_file_channel_enospc(tmp_path, broken):
    lm = LoggerManager(config={"log_directory": str(tmp_path)})
    try:
        if broken:
            patched = 0
            for ch in lm.get_all_channels():
                ch.handler.stream = _EnospcStream()
                patched += 1
            assert patched == 4, f"пропатчено каналов {patched}, ожидалось 4 (design.md §3)"
        before = lm.get_stats()
        lm.warning("w", module="probe")
        lm.error("e", module="probe")
        after = lm.get_stats()
        written = after["channel_written_records"] - before["channel_written_records"]
        loss = after["channel_refused_records"] - before["channel_refused_records"]
        return written == 4, loss, {"channel_written_records": written}
    finally:
        lm.shutdown()


def _scenario_forward_dead_router(tmp_path, broken):
    router = _ForwardRouter(broken)
    ch = RecordForwardChannel(router=router, subscriber="gui", sender="p")
    lm = LoggerManager(config={"log_directory": str(tmp_path)})
    try:
        lm.add_tap(ch, min_level="DEBUG")
        before = lm.get_stats()
        n = lm._emit_to_taps(
            {"timestamp": 1.0, "level": "ERROR", "message": "e", "module": "probe", "extra": {}},
            "ERROR",
        )
        after = lm.get_stats()
        loss = after["tap_write_errors"] - before["tap_write_errors"]
        return n > 0, loss, {"n": n}
    finally:
        lm.shutdown()


def _scenario_logger_after_shutdown(tmp_path, broken):
    lm = LoggerManager(config={"log_directory": str(tmp_path)})
    try:
        m = _Probe(lm)
        m.initialize()
        before = lm.get_stats()
        if broken:
            lm.shutdown()
        ok = m._log_warning("late")
        after = lm.get_stats()
        loss = after["channel_refused_records"] - before["channel_refused_records"]
        return ok is True, loss, {"ok": ok}
    finally:
        lm.shutdown()


def _scenario_bridge_session_gone(tmp_path, broken):
    # LoggerManager здесь не нужен: счётчик ведёт сам адаптер; tmp_path не используется.
    a = SocketBridgeAdapter(_BridgeRouter(broken), "ctl")
    before = a.get_stats()
    result = a.on_inbound(
        {
            "type": "command",
            "command": "introspect.handlers",
            "sender": "ctl",
            "targets": ["preprocessor"],
            "data": {},
            "request_id": "1",
        }
    )
    after = a.get_stats()
    loss = after["lost_responses"] - before["lost_responses"]
    # исход НЕ читается: on_inbound возвращает None; «принято» = счётчик не вырос
    return loss == 0, loss, {"returned": result}


_SCENARIOS = {
    "file_channel_enospc": _scenario_file_channel_enospc,
    "forward_dead_router": _scenario_forward_dead_router,
    "logger_after_shutdown": _scenario_logger_after_shutdown,
    "bridge_session_gone": _scenario_bridge_session_gone,
}


def _run_bounded(hop, tmp_path, broken):
    """Сценарий в daemon-потоке с дедлайном; исключение потока пробрасывается."""
    box: dict = {}

    def target():
        try:
            box["result"] = _SCENARIOS[hop](tmp_path, broken)
        except BaseException as exc:  # noqa: BLE001 - пробросить в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, name=f"probe-{hop}", daemon=True)
    thread.start()
    thread.join(_JOIN_DEADLINE_S)
    assert not thread.is_alive(), f"{hop}: сценарий завис дольше {_JOIN_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


# ---------------------------------------------------------------------------
# Контракт
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hop", _IDS)
def test_broken_hop_not_accepted(hop, tmp_path):
    accepted, loss_delta, extras = _run_bounded(hop, tmp_path, broken=True)
    assert not accepted, f"{hop}: сломанное звено принято (счётчик потерь +{loss_delta}; {extras})"
    assert loss_delta == _LOSS_DELTA_BROKEN[hop], (
        f"{hop}: счётчик потерь вырос на {loss_delta}, ожидалось {_LOSS_DELTA_BROKEN[hop]} ({extras})"
    )


@pytest.mark.parametrize("hop", _IDS)
def test_healthy_hop_accepted(hop, tmp_path):
    accepted, loss_delta, extras = _run_bounded(hop, tmp_path, broken=False)
    assert accepted, f"{hop}: здоровое звено не принято ({extras})"
    assert loss_delta == 0, f"{hop}: счётчик потерь вырос на {loss_delta} у здорового звена ({extras})"
