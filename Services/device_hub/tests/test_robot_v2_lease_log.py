"""Сторожа автора T5.3d2 (поправка D-L1): строка лога «jog остановлен поводком» в ``RobotDriverV2._lease_loop``.

Purpose:
    Стоп поводка (окно удержания истекло) пишет ОДНУ строку INFO с причиной, и только если запись ``STOP_REQ``
    сделал сам поток поводка. Строки нет при ``jog_release`` до истечения окна, при стопе процесса, который
    успел раньше (шов (а)), и когда запись поводка легла после сброса защёлки первым ``request_stop`` и покрыла
    стоп выключения (шов (б)). Записи ``STOP_REQ`` считаются на стороне робота: seq в старших битах регистра sim.
    Лог читается через ``caplog`` с запасного stdlib-логгера фасада (``mpf.Services.device_hub.drivers.base``).
    Окно удержания (0,2 с) меряют управляемые часы драйвера (``_ManualClock``, объект-зависимость ``clock=``, не
    глобальная подмена): тест сам решает, когда окно истекло, и не зависит от планировщика потоков.
    Блокирующие швы держатся в daemon-потоках с дедлайном ``join``; тест всегда отпускает шов в ``finally``.

Public API:
    Только тесты ``test_*``.

Stability: lite

Сторожа (а), (б) привязаны к приватным полям драйвера (``_jog``, ``_shutdown``, ``_jog_tx_lock``,
``_process_stop``): рефакторинг T5.3f их перепишет.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

_LOGGER = "mpf.Services.device_hub.drivers.base"
_JOG = {"dir": 1, "spd": 20}
_CONNECT_S = 60.0
_CALL_S = 15.0
_DEADLINE_S = 5.0
_STOP_REQ = REG["STOP_REQ"]
_SOFT_LEVEL = 1  # младшие 2 бита значения STOP_REQ (значение = stop_seq * 4 + уровень)
_MARK = "jog остановлен поводком"
_LINE_EXPIRED = "робот 'r1': jog остановлен поводком: окно удержания истекло"


@pytest.fixture
def scope() -> Iterator[Any]:
    sc = open_scope("leaselog", budget_s=6.0)
    try:
        yield sc
    finally:
        report = sc.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


class _ManualClock:
    """Часы драйвера под управлением теста: стоят, пока не позван ``advance``; безопасны между потоками.

    Начало отсчёта произвольное (1000,0): драйвер читает только разности. ``connect`` не зависит от хода часов:
    ожидание телеметрии выходит по предикату сразу (стенд уже включил серво), ``bounded`` держит дедлайн.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._t = 1000.0

    def now(self) -> float:
        with self._lock:
            return self._t

    def advance(self, dt_s: float) -> None:
        with self._lock:
            self._t += dt_s


#: Сдвиг часов, после которого окно удержания (0,2 с) точно истекло.
_PAST_WINDOW_S = 0.3


@contextmanager
def _driver(scope: Any) -> Iterator[tuple[RobotDriverV2, E2eRig, _ManualClock]]:
    """Подключённый драйвер v2 над ``E2eRig`` и его управляемые часы (тик драйвера не идёт: только поводок)."""
    with E2eRig() as rig:
        entry = DeviceEntry(
            id="r1",
            name="r1",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
        )
        clock = _ManualClock()
        drv = RobotDriverV2(entry, None, publish=lambda _path, _payload: None, spawn=scope.spawn, clock=clock.now)
        assert bounded(drv.connect, _CONNECT_S) is True
        drv.desired_connected = True
        try:
            yield drv, rig, clock
        finally:
            try:
                bounded(drv.disconnect, _CALL_S)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _stop_value(rig: E2eRig) -> int:
    return rig.core.regs[_STOP_REQ]


def _writes_since(rig: E2eRig, before_seq: int) -> int:
    """Число записей ``STOP_REQ`` после снимка ``before_seq`` (seq записи = старшие биты значения)."""
    return (_stop_value(rig) >> 2) - before_seq


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        assert time.monotonic() < end, what
        time.sleep(0.01)


def _lease_done(drv: RobotDriverV2) -> bool:
    run = drv._jog
    return run is not None and not run.active


def _lease_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [m for m in (r.getMessage() for r in caplog.records) if _MARK in m]


def _hold(drv: RobotDriverV2) -> None:
    assert bounded(lambda: drv.call("jog_hold", dict(_JOG)), _CALL_S)["status"] == "ok"


def test_window_expiry_logs_one_line_and_writes_one_soft_stop(scope: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Один ``jog_hold`` и молчание дольше окна: ровно одна строка «окно удержания истекло», один стоп SOFT."""
    with caplog.at_level(logging.INFO, logger=_LOGGER), _driver(scope) as (drv, rig, clock):
        before = _stop_value(rig) >> 2
        _hold(drv)
        clock.advance(_PAST_WINDOW_S)  # молчание дольше окна
        _until(lambda: _lease_done(drv), _DEADLINE_S, "поток поводка не вышел после окна удержания")
        assert _lease_lines(caplog) == [_LINE_EXPIRED]
        assert _writes_since(rig, before) == 1
        assert _stop_value(rig) & 3 == _SOFT_LEVEL


def test_release_before_expiry_writes_stop_without_lease_line(scope: Any, caplog: pytest.LogCaptureFixture) -> None:
    """``jog_release`` до истечения окна: стоп пишет release (одна запись), строки поводка нет."""
    with caplog.at_level(logging.INFO, logger=_LOGGER), _driver(scope) as (drv, rig, clock):
        before = _stop_value(rig) >> 2
        _hold(drv)
        time.sleep(_PAST_WINDOW_S)  # настенное время дольше окна, но часы драйвера стоят: окно не истекает
        assert bounded(lambda: drv.call("jog_release", {}), _CALL_S)["status"] == "ok"
        _until(lambda: _lease_done(drv), _DEADLINE_S, "поток поводка не вышел после release")
        assert _lease_lines(caplog) == []
        assert _writes_since(rig, before) == 1


def test_process_stop_before_lease_write_means_no_lease_line(scope: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Шов (а): поток поводка решил стоп, но стоит на ``_jog_tx_lock``; стоп процесса записал раньше — строки нет.

    Поток поводка после замка видит ``stop_sent`` и не пишет (``wrote`` False): записей ``STOP_REQ`` +1, строки нет.
    """
    with caplog.at_level(logging.INFO, logger=_LOGGER), _driver(scope) as (drv, rig, clock):
        before = _stop_value(rig) >> 2
        _hold(drv)
        drv._jog_tx_lock.acquire()
        held = True
        try:
            if drv._jog is not None and drv._jog.stop_sent:
                pytest.fail("ТЕСТ ИНВАЛИДЕН: поводок записал стоп до шва")
            clock.advance(_PAST_WINDOW_S)  # окно истекает только теперь, когда замок у теста
            _until(
                lambda: drv._jog is not None and drv._jog.stop_requested is True,
                2.0,
                "поток поводка не принял решение о стопе",
            )
            bounded(lambda: drv._process_stop(time.monotonic() + 2.5), _CALL_S)  # сам замок не берёт
            drv._jog_tx_lock.release()
            held = False
            _until(lambda: _lease_done(drv), _DEADLINE_S, "поток поводка не вышел после отпускания замка")
        finally:
            if held:
                drv._jog_tx_lock.release()
        assert _lease_lines(caplog) == []
        assert _writes_since(rig, before) == 1


def test_latch_race_lease_write_covers_shutdown_stop_with_one_line(
    scope: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Шов (б): запись поводка идёт в момент ``request_stop`` и ложится после сброса защёлки.

    Рандеву в ``issue_stop`` на потоке поводка (только первый вызов): запись держится, второй поток зовёт
    ``request_stop`` (встаёт на ``_jog_tx_lock``), тест ждёт ``_shutdown`` (сброс защёлки прошёл) и отпускает запись
    раньше 2,5 с (иначе стоп без замка, В1). Защёлка засчитывает запись поводка: ровно одна запись ``STOP_REQ`` и
    одна строка «окно удержания истекло».
    """
    entered, go = threading.Event(), threading.Event()
    claim = threading.Lock()
    claimed: list[bool] = []

    with caplog.at_level(logging.INFO, logger=_LOGGER), _driver(scope) as (drv, rig, clock):
        client = drv._client
        real = client.issue_stop

        def issue_stop(level: int) -> int:
            with claim:
                first = not claimed
                claimed.append(True)
            if first:  # первый вызов — поток поводка (до request_stop стопов нет)
                entered.set()
                assert go.wait(_DEADLINE_S), "рандеву: запись не отпущена"
            return real(level)

        client.issue_stop = issue_stop
        stopper = threading.Thread(target=lambda: drv.request_stop(time.monotonic() + 2.5), daemon=True)
        try:
            before = _stop_value(rig) >> 2
            _hold(drv)
            clock.advance(_PAST_WINDOW_S)  # молчание дольше окна: поток поводка идёт на запись стопа
            assert entered.wait(_DEADLINE_S), "поток поводка не дошёл до записи стопа"
            stopper.start()
            _until(lambda: drv._shutdown is True, 2.0, "request_stop не сбросил защёлку")
            go.set()
            stopper.join(_CALL_S)
            assert not stopper.is_alive(), "request_stop не вернулся"
            _until(lambda: _lease_done(drv), _DEADLINE_S, "поток поводка не вышел")
        finally:
            go.set()
            client.issue_stop = real
            if stopper.is_alive():
                stopper.join(_CALL_S)
        assert _lease_lines(caplog) == [_LINE_EXPIRED]
        assert _writes_since(rig, before) == 1
