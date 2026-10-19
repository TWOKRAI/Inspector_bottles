"""Слепая приёмка T5.3c часть c3: путь остановки драйвера — текст «нет окна эха» и ``disconnect()`` простого робота.

Purpose:
    RED 18: три исхода текста «стоп без подтверждения» при выключении плагина с подключённым простым роботом
    (health ``report_error`` и ``devices.state.r1.last_error``). RED 19: отдельный ``disconnect()`` подключённого
    простого робота — только запись SOFT, без ожидания эха. Источник истины — бриф ``tasks/T5.3c3.md``
    (DESIGN 9-10, REDS 18-19) и ADR-DH-009, не код драйвера. Стенд — как ``test_t53r2_stop_hazards.py``: двойник
    робота ``_Rig`` над ``E2eRig`` (``go_silent`` — эхо ``TLM_STOP_ACK`` заморожено; ``journal`` считает записи
    ``STOP_REQ`` НА СТОРОНЕ РОБОТА, ``fail_stops`` отклоняет ближайшие записи).

Public API:
    Только тесты ``test_*``.

Stability: lite

Правила файла: ожидаемые значения — литералы брифа; блокирующий вызов — в daemon-потоке с дедлайном; «нет окна»
задаётся ``transport.timeout_sec`` / ``retries`` (окно эха = срок 2,5 с минус ``timeout_sec * (retries + 1)``), не
``sleep``. Случаи а, б далеки от границы окна (бюджет записи 2,5 с и 4,0 с против срока 2,5 с); случай в (окно
0,5 с) зависит от скорости записи: запись дольше 0,5 с под нагрузкой даст «нет окна» вместо «не подтверждён».
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_t53r2_stop_hazards import (
    _CALL_S,
    _CONNECT_S,
    _SETTLE_S,
    _SOFT_LEVEL,
    _moving,
    _quiet,
    _Rec,
    _Rig,
    _scope,
    _stop_req_level,
    _transport,
)
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.tests.e2e_rig_v2 import bounded

TEXT_NO_WINDOW = "эхо не читалось (нет окна)"
TEXT_UNCONFIRMED = "стоп не подтверждён роботом"
_CONTEXT = "device_hub.stop_echo"
_LAST_ERROR = "devices.state.r1.last_error"
_DISCONNECT_S = 0.5  # бриф RED 19: возврат disconnect() простого робота; до правки 1,997-2,016 с


def _last_error_texts(ctx: Any) -> list[str]:
    return [str(c.args[1]) for c in ctx.state_proxy.merge.call_args_list if c.args and c.args[0] == _LAST_ERROR]


def _stop_echo_reports(ctx: Any) -> list[tuple[Any, Any]]:
    return [
        (c.args[0], c.kwargs.get("device_id"))
        for c in ctx.health.report_error.call_args_list
        if c.kwargs.get("context") == _CONTEXT
    ]


@pytest.mark.parametrize(
    ("timeout_sec", "retries", "silent", "fail_writes", "expected"),
    [
        pytest.param(1.25, 1, False, 0, TEXT_NO_WINDOW, id="а"),
        pytest.param(2.0, 1, False, 0, TEXT_NO_WINDOW, id="б"),
        pytest.param(None, None, True, 0, TEXT_UNCONFIRMED, id="в"),
        pytest.param(None, None, False, 0, None, id="г"),
        pytest.param(1.25, 1, False, 2, TEXT_UNCONFIRMED, id="д"),
    ],
)
def test_echo_text_by_window(
    tmp_path: Path,
    timeout_sec: float | None,
    retries: int | None,
    silent: bool,
    fail_writes: int,
    expected: str | None,
) -> None:
    """Плагин ``shutdown`` с подключённым простым ``r1``: текст health и ``last_error`` по трём исходам."""
    with _Rig() as rig:
        transport = _transport(rig.port)
        if timeout_sec is not None:
            transport["timeout_sec"] = timeout_sec
            transport["retries"] = retries
        registry = tmp_path / "devices.yaml"
        recipe = [{"id": "r1", "name": "r1", "kind": "robot", "protocol": "delta_v2", "transport": transport}]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        assert plugin._manager.connected_ids() == ["r1"]
        assert _moving(rig) == 0  # простой подключённый робот: пустой зелени нет
        if silent:
            rig.core.go_silent()
        rig.journal.fail_stops = fail_writes
        last_error_before = len(_last_error_texts(ctx))
        t0 = time.perf_counter()
        bounded(lambda: plugin.shutdown(ctx), 10.0)
        time.sleep(_SETTLE_S)

        reports = _stop_echo_reports(ctx)
        published = _last_error_texts(ctx)[last_error_before:]
        if expected is None:
            # эхо пришло в окне: ни health, ни last_error
            assert reports == [], reports
            assert published == [], published
        else:
            assert [(str(exc), dev) for exc, dev in reports] == [(expected, "r1")], reports
            assert all(isinstance(exc, RuntimeError) for exc, _ in reports), reports
            assert published, "last_error не публиковался"
            assert published[-1] == expected, published
        if not fail_writes:
            assert rig.journal.count(t0) == 1, rig.journal.stamps()  # ровно один стоп (правило владельца)


def _entry(rig: _Rig) -> DeviceEntry:
    return DeviceEntry(id="r1", name="r1", kind="robot", protocol="delta_v2", transport=_transport(rig.port))


def _timed_disconnect(drv: RobotDriverV2) -> float:
    """``drv.disconnect()`` в daemon-потоке с дедлайном; возвращает длительность вызова, с."""
    box: dict[str, float] = {}

    def body() -> None:
        t = time.perf_counter()
        drv.disconnect()
        box["s"] = time.perf_counter() - t

    th = threading.Thread(target=body, daemon=True)
    th.start()
    th.join(_CALL_S)
    assert not th.is_alive(), "disconnect() не вернулся за дедлайн"
    return box["s"]


def _connected(rig: _Rig, rec: _Rec, spawn: Any) -> RobotDriverV2:
    drv = RobotDriverV2(_entry(rig), None, publish=rec, spawn=spawn)
    assert bounded(drv.connect, _CONNECT_S) is True
    drv.desired_connected = True
    assert _moving(rig) == 0
    return drv


def test_idle_disconnect_writes_only() -> None:
    """Подключённый простой ``r1``: ``disconnect()`` — одна запись SOFT и возврат без ожидания эха."""
    rec = _Rec()
    with _Rig() as silent_rig, _Rig() as live_rig, _Rig() as idle_rig, _scope() as scope:
        # Эхо молчит: возврат <= 0,5 с, ровно одна запись SOFT, last_error не появляется
        drv = _connected(silent_rig, rec, scope.spawn)
        try:
            silent_rig.core.go_silent()
            errors_before = len(rec.at(_LAST_ERROR))
            t0 = time.perf_counter()
            elapsed = _timed_disconnect(drv)
            time.sleep(_SETTLE_S)
            assert silent_rig.journal.count(t0) == 1, silent_rig.journal.stamps()
            assert _stop_req_level(silent_rig) == _SOFT_LEVEL
            assert len(rec.at(_LAST_ERROR)) == errors_before, rec.at(_LAST_ERROR)
            assert elapsed <= _DISCONNECT_S, elapsed
        finally:
            _quiet(drv.disconnect)

        # Контроль: эхо живое — тоже одна запись SOFT и <= 0,5 с
        drv = _connected(live_rig, rec, scope.spawn)
        try:
            t0 = time.perf_counter()
            elapsed = _timed_disconnect(drv)
            time.sleep(_SETTLE_S)
            assert live_rig.journal.count(t0) == 1, live_rig.journal.stamps()
            assert _stop_req_level(live_rig) == _SOFT_LEVEL
            assert elapsed <= _DISCONNECT_S, elapsed
        finally:
            _quiet(drv.disconnect)

        # Неподключённый: записей нет
        drv = RobotDriverV2(_entry(idle_rig), None, publish=rec, spawn=scope.spawn)
        try:
            t0 = time.perf_counter()
            bounded(drv.disconnect, _CALL_S)
            time.sleep(_SETTLE_S)
            assert idle_rig.journal.count(t0) == 0, idle_rig.journal.stamps()
        finally:
            _quiet(drv.disconnect)
