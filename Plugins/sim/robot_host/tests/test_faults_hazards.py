# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 5.4 — ручки неисправностей (fault.*).

Харнесс скопирован с ``test_acceptance_5_4_faults.py`` (``_make_plugin``/``_call``/
``_free_port``/``_run_with_deadline``) — тот же приём: ``MockProcessServices`` +
реальный ``PluginContext`` + реальный ``SimRobotServer`` на свободном порту.

Каждый тест целит РОВНО ту опасность конкретного устройства, которую называет
DESIGN п.6 брифа задачи (гонка останова/рестарта слушателя вокруг
``fault.drop``/``fault.clear``/``shutdown``) — не повтор приёмки тестера.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import REG_PLACE_X

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_UNIT_ID = 2
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать


# --------------------------------------------------------------------------- #
# Харнесс (копия test_acceptance_5_4_faults.py)                               #
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом, перегенерировать"
    return port


def _make_plugin(port: int, **extra_cfg: Any) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    services = MockProcessServices(name="robot")
    cfg = {"host": _HOST, "port": port, "unit_id": _UNIT_ID, "auto_start": True}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _call(plugin: SimRobotHostPlugin, name: str, data: dict | None = None) -> dict:
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _run_with_deadline(fn, *, timeout: float, label: str):
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном
    (project-rules: зависание хуже отсутствующего теста)."""
    result: dict = {}
    error: dict = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            error["exc"] = exc

    thread = threading.Thread(target=_target, name=f"deadline-{label}", daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise AssertionError(f"{label} не вернулась за {timeout} с — похоже на зависание")
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def _try_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    def _attempt() -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    return bool(_run_with_deadline(_attempt, timeout=timeout + 1.0, label="tcp-connect"))


@pytest.fixture
def running_plugin():
    port = _free_port()
    plugin, ctx, services = _make_plugin(port)
    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    try:
        yield plugin, ctx, port
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")


# --------------------------------------------------------------------------- #
# (a) shutdown во время активного drop — слушатель не должен воскреснуть      #
# --------------------------------------------------------------------------- #


def test_shutdown_during_drop_does_not_resurrect_listener() -> None:
    """Гонка DESIGN п.4/6d: ``shutdown()`` посреди ``fault.drop{seconds:5}``.

    Если бы ``shutdown()`` звал ``self._server.stop()`` НЕ дождавшись отмены
    фонового потока :meth:`_run_drop`, тот мог бы позвать ``start_listener()``
    ПОСЛЕ того, как порт уже закрыт ``stop_listener()`` изнутри ``server.stop()``
    — слушатель воскрес бы за спиной у остановленного процесса. Порт должен
    остаться закрытым и после дедлайна ``seconds``, и поток drop — мёртв."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"

    t_cmd = time.monotonic()
    resp = _call(plugin, "fault.drop", {"seconds": 5})
    assert resp["ok"] is True

    _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")

    drop_thread = plugin._drop_thread
    if drop_thread is not None:
        assert not drop_thread.is_alive(), "поток fault.drop должен быть мёртв после shutdown()"

    # Ждём дольше исходного seconds=5 (с запасом на дедлайн команды) — порт
    # обязан оставаться закрытым, а не "открыться сам" по истечении seconds.
    while time.monotonic() - t_cmd < 5.5:
        assert not _try_connect(_HOST, port, timeout=0.3), (
            "listener воскрес после shutdown() — гонка stop_listener()/start_listener()"
        )
        time.sleep(0.2)


# --------------------------------------------------------------------------- #
# (b) drop сам исчезает из status["faults"] без явного fault.clear            #
# --------------------------------------------------------------------------- #


def test_drop_disappears_from_status_without_clear(running_plugin) -> None:
    """DESIGN §status: ``drop`` числится в ``faults`` РОВНО пока жив поток
    :meth:`_run_drop` (не по таймеру/сроку, снятому вручную) — как только
    ``start_listener()`` восстановил связь и поток завершился, запись обязана
    пропасть САМА, без вызова ``fault.clear``."""
    plugin, _ctx, _port = running_plugin

    resp = _call(plugin, "fault.drop", {"seconds": 1})
    assert resp["ok"] is True

    status = _call(plugin, "sim_robot.status")
    assert any(f["kind"] == "drop" for f in status["faults"]), "drop должен быть в faults сразу после команды"

    deadline = time.monotonic() + 3.0
    disappeared = False
    while time.monotonic() < deadline:
        status = _call(plugin, "sim_robot.status")
        if not any(f["kind"] == "drop" for f in status["faults"]):
            disappeared = True
            break
        time.sleep(0.1)
    assert disappeared, f"drop не пропал из faults сам за 3с (seconds=1): {status['faults']!r}"
    # ...и без единого вызова fault.clear в этом тесте.


# --------------------------------------------------------------------------- #
# (c) два drop подряд (второй — после завершения первого) оба работают        #
# --------------------------------------------------------------------------- #


def test_two_consecutive_drops_both_work_state_survives(running_plugin) -> None:
    """DESIGN п.1: НЕ «второй drop поверх первого» (это критерий приёмки —
    busy), а два ПОСЛЕДОВАТЕЛЬНЫХ drop — состояние (REG_PLACE_X) обязано
    пережить ОБА рестарта слушателя подряд, не только один."""
    from pymodbus.client import ModbusTcpClient

    plugin, _ctx, port = running_plugin

    client = ModbusTcpClient(host=_HOST, port=port, timeout=3)
    ok = _run_with_deadline(client.connect, timeout=3.0, label="connect")
    assert ok, "client.connect() вернул False"
    try:
        _run_with_deadline(
            lambda: client.write_register(REG_PLACE_X, 1234, device_id=_UNIT_ID), timeout=3.0, label="write"
        )
    finally:
        client.close()

    for seconds in (1, 1):
        resp = _call(plugin, "fault.drop", {"seconds": seconds})
        assert resp["ok"] is True, f"drop({seconds}) должен пройти: {resp!r}"

        deadline = time.monotonic() + 4.0
        reconnected = False
        while time.monotonic() < deadline:
            if _try_connect(_HOST, port, timeout=0.4):
                reconnected = True
                break
            time.sleep(0.1)
        assert reconnected, f"listener не восстановился после drop({seconds})"

    client2 = ModbusTcpClient(host=_HOST, port=port, timeout=3)
    ok2 = _run_with_deadline(client2.connect, timeout=3.0, label="connect2")
    assert ok2, "второй client.connect() вернул False"
    try:
        rr = _run_with_deadline(
            lambda: client2.read_holding_registers(REG_PLACE_X, count=1, device_id=_UNIT_ID),
            timeout=3.0,
            label="read",
        )
    finally:
        client2.close()
    assert rr is not None and not rr.isError(), f"чтение после двух drop подряд провалилось: {rr!r}"
    assert list(rr.registers) == [1234], f"REG_PLACE_X не пережил ДВА drop подряд: {rr.registers!r}"


# --------------------------------------------------------------------------- #
# (d) shutdown сразу после fault.clear (листенер только что рестартовал)      #
# --------------------------------------------------------------------------- #


def test_shutdown_right_after_clear_leaves_port_free() -> None:
    """TRAPS брифа Task 5.4: ``pymodbus.ModbusBaseServer.active_server``
    выставляется ВНУТРИ потока сервера — ``ServerStop()`` до этого момента
    бросает «not running» и НЕ останавливает реально запущенный listener.
    ``fault.clear`` только что позвал ``start_listener()`` (см.
    :meth:`SimRobotServer.start_listener` — ждёт готовности, но не бесконечно);
    ``shutdown()`` СРАЗУ следом не должен оставить порт открытым.

    Фикс-раунд ревью (K5) — старая версия (одна итерация, проверка СРАЗУ после
    shutdown, чем занят одноразовый ``running_plugin``) не ловила свою же
    гонку: воскресший листенер биндится с ЗАДЕРЖКОЙ (новый поток должен
    успеть дойти до ``bind()``/``listen()`` уже ПОСЛЕ того, как
    ``server.stop()`` вернул управление), поэтому коннект СРАЗУ после
    shutdown() мог пройти отказом чисто по времени, даже когда гонка
    реально произошла и порт откроется чуть позже. Перебор (5 итераций,
    свежий плагин+порт на каждой — переиспользованный ``running_plugin``
    маскировал бы вторую гонку состоянием первой) + ОДНА проверка через
    1.0с (не цикл — цикл с ранним успешным отказом опять маскирует позднее
    открытие) ловит запаздывающий бинд. Сам факт того, что тест ловит СВОЙ
    хазард, а не просто "зелёный по умолчанию", проверен вручную (см.
    докстринг развёртывания в отчёте ревью): временный ``return`` перед
    циклом готовности в ``start_listener()`` красит этот тест."""
    for _ in range(5):
        port = _free_port()
        plugin, ctx, _services = _make_plugin(port)
        _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
        assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"

        drop_resp = _call(plugin, "fault.drop", {"seconds": 1})
        assert drop_resp["ok"] is True
        clear_resp = _call(plugin, "fault.clear")
        assert clear_resp["ok"] is True

        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")

        time.sleep(1.0)
        assert not _try_connect(_HOST, port, timeout=0.3), (
            "порт всё ещё принимает соединения через 1.0с после shutdown() сразу за fault.clear()"
        )


# --------------------------------------------------------------------------- #
# (R1, MAJOR) — задержка ПЕРВОЙ в биндере: обрыв во время delay_ms не должен  #
# ложно засчитаться журналом как отдельное задание                            #
# --------------------------------------------------------------------------- #


def test_delay_then_drop_does_not_double_count_journal(running_plugin) -> None:
    """Повтор репро ревьюера: ``fault.delay_ms{ms:1500}``, запись
    ``write_registers(REG_JOB_FLAG, [1,100,200,0,5,0])`` (полный кадр задания —
    JOB_FLAG, X, Y, ECAP(2 слова), PLACE_FLAG), 0.3с внутрь этой ЕЩЁ висящей
    (задержанной) записи — ``fault.drop{seconds:0.3}`` рвёт соединение.
    Клиент не получил ответ -> переподключается ПОСЛЕ восстановления и шлёт
    ТУ ЖЕ запись повторно (эмулируем клиентский retry — в тесте просто вторая
    запись тем же кадром). Журнал обязан увидеть РОВНО ОДНО успешное задание
    (jobs=1, dups=0), а не два (jobs=2, dups=1) — старый порядок (delay ПОСЛЕ
    attach/on_write) считал ``on_write`` ДО того, как pymodbus успевал
    применить саму запись, а обрыв соединения отменял зависшую в sleep
    корутину уже ПОСЛЕ этого фиктивного счёта. Тест обязан УМЕРЕТЬ при старом
    порядке (delay последней) — проверено вручную (см. отчёт ревью)."""
    from pymodbus.client import ModbusTcpClient

    from Services.robot_comm.core.registers import REG_JOB_FLAG

    plugin, _ctx, port = running_plugin

    delay_resp = _call(plugin, "fault.delay_ms", {"ms": 1500})
    assert delay_resp["ok"] is True

    job_frame = [1, 100, 200, 0, 5, 0]  # JOB_FLAG,X,Y,ECAP_HI,ECAP_LO,PLACE_FLAG

    write_error: dict[str, BaseException] = {}

    def _write_delayed() -> None:
        client = ModbusTcpClient(host=_HOST, port=port, timeout=3)
        try:
            ok = client.connect()
            if not ok:
                write_error["exc"] = RuntimeError("connect() вернул False")
                return
            client.write_registers(REG_JOB_FLAG, job_frame, device_id=_UNIT_ID)
        except Exception as exc:  # noqa: BLE001 — обрыв соединения, тип не гарантирован
            write_error["exc"] = exc
        finally:
            client.close()

    writer_thread = threading.Thread(target=_write_delayed, name="delayed-write", daemon=True)
    writer_thread.start()

    time.sleep(0.3)  # запись всё ещё висит внутри asyncio.sleep(1.5) биндера
    drop_resp = _call(plugin, "fault.drop", {"seconds": 0.3})
    assert drop_resp["ok"] is True

    writer_thread.join(timeout=5.0)
    assert not writer_thread.is_alive(), "поток отложенной записи не завершился за 5с — похоже на зависание"

    clear_resp = _call(plugin, "fault.clear")
    assert clear_resp["ok"] is True

    deadline = time.monotonic() + 5.0
    reconnected = False
    while time.monotonic() < deadline:
        if _try_connect(_HOST, port, timeout=0.5):
            reconnected = True
            break
        time.sleep(0.1)
    assert reconnected, "listener не восстановился после drop"

    # Клиентский retry — ТА ЖЕ запись тем же кадром после восстановления связи.
    client2 = ModbusTcpClient(host=_HOST, port=port, timeout=3)
    ok2 = _run_with_deadline(client2.connect, timeout=3.0, label="connect2")
    assert ok2, "client2.connect() вернул False"
    try:
        rr = _run_with_deadline(
            lambda: client2.write_registers(REG_JOB_FLAG, job_frame, device_id=_UNIT_ID),
            timeout=3.0,
            label="retry-write",
        )
        assert rr is not None and not rr.isError(), f"повторная запись провалилась: {rr!r}"
    finally:
        client2.close()

    time.sleep(0.5)  # дать журналу такт паблишера/приёма
    status = _call(plugin, "sim_robot.journal")
    assert status["status"] == "ok", status
    counters = status["counters"]
    assert counters["jobs"] == 1, f"ложный лишний job из прерванной задержанной записи: {counters!r}"
    assert counters["dups"] == 0, f"ложный dup из прерванной задержанной записи: {counters!r}"


# --------------------------------------------------------------------------- #
# (K4) — fault.vfd_code не пишет 0x1214 сразу, только на пульсе               #
# --------------------------------------------------------------------------- #


def test_vfd_code_command_alone_does_not_write_register(running_plugin) -> None:
    """DESIGN п.3, буквально: команда ``fault.vfd_code{code:7}`` БЕЗ пульса
    VFD_FLAG не должна тронуть 0x1214 вообще — если плагин по ошибке пишет
    регистр сразу (мимо ``RobotSimCore._handle_vfd``), этот тест обязан
    умереть на первом чтении (0 ожидается, не 7)."""
    from pymodbus.client import ModbusTcpClient

    plugin, _ctx, port = running_plugin
    _REG_VFD_FAULT = 0x1214

    resp = _call(plugin, "fault.vfd_code", {"code": 7})
    assert resp["ok"] is True

    client = ModbusTcpClient(host=_HOST, port=port, timeout=3)
    ok = _run_with_deadline(client.connect, timeout=3.0, label="connect")
    assert ok, "client.connect() вернул False"
    try:
        regs_before = _run_with_deadline(
            lambda: client.read_holding_registers(_REG_VFD_FAULT, count=1, device_id=_UNIT_ID),
            timeout=3.0,
            label="read-before-pulse",
        )
        assert regs_before is not None and not regs_before.isError(), f"чтение провалилось: {regs_before!r}"
        assert list(regs_before.registers) == [0], (
            f"0x1214 не должен получить код ДО пульса VFD_FLAG: {regs_before.registers!r}"
        )

        belt_resp = _call(plugin, "belt.run", {"freq_hz": 10.0})  # пульс VFD_FLAG
        assert belt_resp["ok"] is True
        time.sleep(0.1)

        regs_after = _run_with_deadline(
            lambda: client.read_holding_registers(_REG_VFD_FAULT, count=1, device_id=_UNIT_ID),
            timeout=3.0,
            label="read-after-pulse",
        )
        assert regs_after is not None and not regs_after.isError(), f"чтение провалилось: {regs_after!r}"
        assert list(regs_after.registers) == [7], f"0x1214 должен стать 7 ПОСЛЕ пульса: {regs_after.registers!r}"
    finally:
        client.close()
        _call(plugin, "fault.clear")
