# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.4 — ручки неисправностей симулятора робота
(``fault.drop``/``fault.delay_ms``/``fault.vfd_code``/``fault.clear``).

Независимый tester, worktree на коммите ДО реализации (``.claude/worktrees/line-sim-5.4``).
Контракт — ТОЛЬКО DESIGN лида из брифа задачи (Task 5.4 плана
``plans/line-sim/phase-5-ground-truth.md``), новых команд ``SimRobotHostPlugin.commands``
пока НЕТ (см. ``Plugins/sim/robot_host/plugin.py`` — читан ДО реализации, только как
образец харнесса и карты команд belt.*/sim_robot.*). Приём брифа не содержал буквального
заголовка ``MODE:``/``INTERFACE:``/``TASK:``, но сам протокол — явные FORBIDDEN-пути,
перечень REDS, требование «тесты ожидаемо RED, становятся спекой разработчика» — это тот
же RED-режим по сути (см. память tester,
``feedback_freeform_brief_without_mode_header.md``); поэтому файл собран как обычный
RED-харнесс, а не как ``MODE: regression`` (которая читала бы ``git diff`` — здесь такого
требования не было, и сравнивать не с чем, реализации ещё нет).

Харнесс скопирован с ``Plugins/sim/robot_host/tests/test_acceptance_5_1b.py``
(``_make_plugin``/``_call``/``_free_port``/``_run_with_deadline`` — тот же приём:
``MockProcessServices`` + реальный ``PluginContext`` + реальный ``SimRobotServer`` на
свободном порту). Добавлены только Modbus-раунд-трипы реальным ``pymodbus`` клиентом
(``_mb_read``/``_mb_write``/``_try_connect``) — по брифу критерий 2 (VFD-код после пульса)
обязан читаться через реальный клиент, не внутренние объекты.

Сегодня ``fault.*`` НЕТ в ``SimRobotHostPlugin.commands`` — ``_call(plugin, "fault.drop", ...)``
падает ``KeyError`` на строке ``plugin.commands[name]`` немедленно (не зависание). Для
``sim_robot.status`` команда ЕСТЬ, но ключа ``"faults"`` в ответе нет — там ожидаемый
провал ``KeyError`` при обращении ``resp["faults"]``. Оба — валидный RED по правилу
тестера («NotImplementedError/AttributeError-эквивалент», здесь — KeyError на отсутствующем
имени команды/ключе, не AssertionError и не зависание).
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
from Services.robot_comm.core.registers import REG_FREE, REG_PLACE_X

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_UNIT_ID = 2
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать

#: FAULT-поле зеркала ПЧ (Modbus TCP): база 0x1210 ("RUN, OUT_FREQ, CURRENT, DCBUS,
#: FAULT, STATUSW, HB, COMM_ERR", см. ``Services/robot_comm/server/sim_core.py``
#: ``_REG_VFD_ST_BASE`` + ``_handle_vfd``, ``st + 4``) + 4-е поле = 0x1214 — то же число,
#: что называет DESIGN брифа ("= 0x1210 + 4"). Константа не публична в sim_core.py
#: (``_REG_VFD_ST_BASE`` — приватная), поэтому продублирована здесь буквально с ссылкой.
_REG_VFD_FAULT = 0x1214


# --------------------------------------------------------------------------- #
# Харнесс (копия test_acceptance_5_1b.py)                                     #
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
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном (project-rules:
    зависание хуже отсутствующего теста, любой блокирующий вызов обязан ловиться так)."""
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
# Новые хелперы — реальный pymodbus клиент + TCP-проба                        #
# --------------------------------------------------------------------------- #


def _mb_client(timeout: float = 3.0):
    """Ленивый импорт — модуль коллектируется даже без pymodbus (skipif — на тестах,
    не на импорте файла); ``ROBOT_AVAILABLE`` уже гарантирует наличие pymodbus здесь."""
    from pymodbus.client import ModbusTcpClient

    return ModbusTcpClient  # тип, не инстанс — конструируется у каждого вызывающего


def _try_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    """True — TCP-коннект удался за ``timeout`` с. В daemon-потоке с join-дедлайном —
    сам ``socket.create_connection`` тоже может зависнуть дольше своего timeout
    (например DNS), а мы обязаны не повесить прогон."""

    def _attempt() -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    return bool(_run_with_deadline(_attempt, timeout=timeout + 1.0, label="tcp-connect"))


def _mb_read(client, address: int, count: int = 1, *, timeout: float = 3.0) -> list[int]:
    def _attempt() -> list[int]:
        rr = client.read_holding_registers(address, count=count, device_id=_UNIT_ID)
        if rr is None or rr.isError():
            raise AssertionError(f"read_holding_registers(0x{address:04X}) вернул ошибку: {rr!r}")
        return list(rr.registers)

    return _run_with_deadline(_attempt, timeout=timeout, label=f"modbus-read-0x{address:04X}")


def _mb_write(client, address: int, value: int, *, timeout: float = 3.0) -> None:
    def _attempt() -> None:
        rr = client.write_register(address, value, device_id=_UNIT_ID)
        if rr is None or rr.isError():
            raise AssertionError(f"write_register(0x{address:04X}, {value}) вернул ошибку: {rr!r}")

    _run_with_deadline(_attempt, timeout=timeout, label=f"modbus-write-0x{address:04X}")


def _mb_connect(client, timeout: float = 3.0) -> None:
    ok = _run_with_deadline(client.connect, timeout=timeout, label="modbus-connect")
    assert ok, "client.connect() вернул False"


# --------------------------------------------------------------------------- #
# Критерий 1 — fault.drop: коммуникационный обрыв, не перезагрузка            #
# --------------------------------------------------------------------------- #


def test_drop_refuses_then_recovers(running_plugin) -> None:
    """DESIGN п.1: после ``fault.drop{seconds:3}`` коннект отказан <=1с и снова
    проходит не позже 5с после команды."""
    plugin, _ctx, port = running_plugin

    t_cmd = time.monotonic()
    resp = _call(plugin, "fault.drop", {"seconds": 3})
    assert resp["ok"] is True, f"fault.drop должен вернуть ok=True: {resp!r}"

    assert not _try_connect(_HOST, port, timeout=1.0), "коннект во время drop должен быть отказан за <=1с"

    deadline = t_cmd + 5.0
    reconnected = False
    while time.monotonic() < deadline:
        if _try_connect(_HOST, port, timeout=0.5):
            reconnected = True
            break
        time.sleep(0.1)
    assert reconnected, "listener не восстановился за 5с после fault.drop{seconds:3}"


def test_drop_command_does_not_block(running_plugin) -> None:
    """DESIGN п.1: команда возвращается немедленно (<1с), не ждёт истечения ``seconds``."""
    plugin, _ctx, _port = running_plugin

    t0 = time.monotonic()
    resp = _run_with_deadline(lambda: _call(plugin, "fault.drop", {"seconds": 3}), timeout=1.5, label="fault.drop")
    elapsed = time.monotonic() - t0
    assert resp["ok"] is True
    assert elapsed < 1.0, f"fault.drop заблокировала вызывающий поток на {elapsed:.3f}с"
    _call(plugin, "fault.clear")


def test_drop_breaks_open_connection(running_plugin) -> None:
    """DESIGN п.1: УЖЕ открытое соединение тоже рвётся, не только новые попытки."""
    plugin, _ctx, port = running_plugin
    client = _mb_client()(host=_HOST, port=port, timeout=2)
    _mb_connect(client)
    try:
        before = _mb_read(client, REG_FREE, 1)
        assert before == [1], f"REG_FREE должен быть 1 в idle до drop: {before!r}"

        drop_resp = _call(plugin, "fault.drop", {"seconds": 3})
        assert drop_resp["ok"] is True

        def _attempt_read():
            try:
                rr = client.read_holding_registers(REG_FREE, count=1, device_id=_UNIT_ID)
            except Exception as exc:  # noqa: BLE001 — обрыв соединения, конкретный тип не гарантирован
                return ("raised", exc)
            if rr is None or rr.isError():
                return ("error", rr)
            return ("ok", list(rr.registers))

        outcome = _run_with_deadline(_attempt_read, timeout=3.0, label="read-during-drop")
        assert outcome[0] != "ok", (
            f"чтение по уже открытому соединению должно провалиться во время drop, получено: {outcome!r}"
        )
    finally:
        client.close()
        _call(plugin, "fault.clear")


def test_drop_keeps_robot_state(running_plugin) -> None:
    """DESIGN п.1: регистры/энкодер переживают drop — это обрыв связи, не ребут ядра."""
    plugin, _ctx, port = running_plugin

    client = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client)
    try:
        # REG_PLACE_X — чистое хранилище: sim читает/использует его ТОЛЬКО по пульсу
        # REG_PLACE_FLAG (см. Services/robot_comm/server/sim_core.py:_handle_job,
        # job_has_place читается из REG_PLACE_FLAG), которого мы НЕ шлём — значит
        # регистр не может "случайно" пережить drop, симулятор сам его не трогает.
        _mb_write(client, REG_PLACE_X, 4242)
    finally:
        client.close()

    belt_resp = _call(plugin, "belt.run", {"freq_hz": 20.0})
    assert belt_resp["ok"] is True
    time.sleep(0.2)  # дать тикеру (10мс/тик) продвинуть энкодер до снятия базовой точки
    encoder_before = _call(plugin, "belt.status")["encoder"]

    drop_resp = _call(plugin, "fault.drop", {"seconds": 2})
    assert drop_resp["ok"] is True

    deadline = time.monotonic() + 5.0
    reconnected = False
    while time.monotonic() < deadline:
        if _try_connect(_HOST, port, timeout=0.5):
            reconnected = True
            break
        time.sleep(0.1)
    assert reconnected, "listener не восстановился за 5с после fault.drop{seconds:2}"

    client2 = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client2)
    try:
        value = _mb_read(client2, REG_PLACE_X, 1)
    finally:
        client2.close()
    assert value == [4242], f"REG_PLACE_X не пережил drop: {value!r}"

    encoder_after = _call(plugin, "belt.status")["encoder"]
    assert encoder_after >= encoder_before, (
        f"энкодер должен продолжать расти во время drop (лента бежит на тикере, "
        f"не на сети): before={encoder_before}, after={encoder_after}"
    )


def test_clear_ends_drop_early(running_plugin) -> None:
    """DESIGN п.4: ``fault.clear`` 0.5с внутрь 3с-дропа — коннект снова проходит
    не позже 1с после clear."""
    plugin, _ctx, port = running_plugin

    resp = _call(plugin, "fault.drop", {"seconds": 3})
    assert resp["ok"] is True
    time.sleep(0.5)

    clear_resp = _call(plugin, "fault.clear")
    assert clear_resp["ok"] is True
    assert clear_resp["faults"] == [], f"после clear faults должен быть пуст: {clear_resp!r}"

    connected = _try_connect(_HOST, port, timeout=1.0)
    assert connected, "коннект после fault.clear должен пройти за <=1с"


# --------------------------------------------------------------------------- #
# Критерий 2 — fault.vfd_code: FAULT-зеркало после пульса                     #
# --------------------------------------------------------------------------- #


def test_vfd_code_after_pulse_then_clear(running_plugin) -> None:
    """DESIGN п.3: 0x1214 принимает код ПОСЛЕ следующего пульса ПЧ (не сразу), и
    возвращается к 0 после clear+пульс. Пульс — команда ``belt.run`` (запись
    VFD_FLAG=0x1204 плагином, см. RobotSimCore.command_vfd), читаем через реальный
    pymodbus-клиент — по брифу критерий 2 не годится проверять на внутренних объектах."""
    plugin, _ctx, port = running_plugin

    resp = _call(plugin, "fault.vfd_code", {"code": 7})
    assert resp["ok"] is True

    belt_resp = _call(plugin, "belt.run", {"freq_hz": 10.0})  # пульс VFD_FLAG
    assert belt_resp["ok"] is True
    time.sleep(0.1)  # тик ядра — 10мс, дать обработать пульс

    client = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client)
    try:
        regs = _mb_read(client, _REG_VFD_FAULT, 1)
    finally:
        client.close()
    assert regs == [7], f"0x1214 должен стать 7 после пульса fault.vfd_code{{code:7}}: {regs!r}"

    clear_resp = _call(plugin, "fault.clear")
    assert clear_resp["ok"] is True

    belt_resp2 = _call(plugin, "belt.stop")  # тоже пульс VFD_FLAG (RUN=0)
    assert belt_resp2["ok"] is True
    time.sleep(0.1)

    client2 = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client2)
    try:
        regs2 = _mb_read(client2, _REG_VFD_FAULT, 1)
    finally:
        client2.close()
    assert regs2 == [0], f"0x1214 должен вернуться к 0 после clear+пульс: {regs2!r}"


# --------------------------------------------------------------------------- #
# Критерий 3 — sim_robot.status["faults"]                                     #
# --------------------------------------------------------------------------- #


def test_status_lists_faults_and_clear_empties(running_plugin) -> None:
    plugin, _ctx, _port = running_plugin

    resp = _call(plugin, "sim_robot.status")
    assert resp["faults"] == [], f"без активных faults список должен быть пуст: {resp!r}"

    delay_resp = _call(plugin, "fault.delay_ms", {"ms": 50})
    assert delay_resp["ok"] is True
    vfd_resp = _call(plugin, "fault.vfd_code", {"code": 9})
    assert vfd_resp["ok"] is True

    resp = _call(plugin, "sim_robot.status")
    by_kind = {f["kind"]: f for f in resp["faults"]}
    assert by_kind["delay_ms"]["ms"] == 50, f"delay_ms не отражён в status: {resp['faults']!r}"
    assert by_kind["vfd_code"]["code"] == 9, f"vfd_code не отражён в status: {resp['faults']!r}"

    drop_resp = _call(plugin, "fault.drop", {"seconds": 2})
    assert drop_resp["ok"] is True
    resp = _call(plugin, "sim_robot.status")
    kinds = {f["kind"] for f in resp["faults"]}
    assert "drop" in kinds, f"активный drop должен быть в faults: {resp['faults']!r}"

    clear_resp = _call(plugin, "fault.clear")
    assert clear_resp["ok"] is True
    resp = _call(plugin, "sim_robot.status")
    assert resp["faults"] == [], f"после clear faults должен быть пуст: {resp!r}"


# --------------------------------------------------------------------------- #
# fault.delay_ms — задержка без блокировки цикла сервера                      #
# --------------------------------------------------------------------------- #


def test_delay_ms_delays_and_does_not_serialize(running_plugin) -> None:
    plugin, _ctx, port = running_plugin

    resp = _call(plugin, "fault.delay_ms", {"ms": 300})
    assert resp["ok"] is True

    client = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client)
    try:
        t0 = time.monotonic()
        _mb_read(client, REG_FREE, 1)
        elapsed_single = time.monotonic() - t0
    finally:
        client.close()
    assert elapsed_single >= 0.3, f"единичное чтение должно быть задержано >=0.3с: {elapsed_single:.3f}с"

    clients = [_mb_client()(host=_HOST, port=port, timeout=3) for _ in range(2)]
    for c in clients:
        _mb_connect(c)
    results: dict[int, list[int]] = {}
    errors: dict[int, BaseException] = {}

    def _worker(idx: int, c) -> None:
        try:
            results[idx] = _mb_read(c, REG_FREE, 1, timeout=2.0)
        except BaseException as exc:  # noqa: BLE001
            errors[idx] = exc

    t0 = time.monotonic()
    threads = [threading.Thread(target=_worker, args=(i, c), daemon=True) for i, c in enumerate(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    elapsed_concurrent = time.monotonic() - t0
    for c in clients:
        c.close()
    assert all(not t.is_alive() for t in threads), "конкурентное чтение зависло дольше join-дедлайна"
    assert not errors, f"конкурентное чтение упало: {errors!r}"
    assert elapsed_concurrent < 0.55, (
        f"похоже на сериализацию двух клиентов: {elapsed_concurrent:.3f}с "
        f"(параллельно должно уложиться в ~0.3-0.4с, serialized было бы >=0.6с)"
    )

    clear_resp = _call(plugin, "fault.clear")
    assert clear_resp["ok"] is True

    client2 = _mb_client()(host=_HOST, port=port, timeout=3)
    _mb_connect(client2)
    try:
        t0 = time.monotonic()
        _mb_read(client2, REG_FREE, 1)
        elapsed_after_clear = time.monotonic() - t0
    finally:
        client2.close()
    assert elapsed_after_clear < 0.1, f"после clear чтение всё ещё задержано: {elapsed_after_clear:.3f}с"


# --------------------------------------------------------------------------- #
# Ошибки: bad_args, server_not_running, повторный drop                        #
# --------------------------------------------------------------------------- #


def test_bad_args_and_no_server() -> None:
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port, auto_start=False)

    no_server_resp = _call(plugin, "fault.drop", {"seconds": 1})
    assert no_server_resp == {"ok": False, "error": "server_not_running"}, (
        f"fault.drop без сервера должен отдать server_not_running: {no_server_resp!r}"
    )

    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    try:
        bad_cases: list[tuple[str, dict]] = [
            ("fault.drop", {"seconds": 0}),
            ("fault.drop", {"seconds": -1}),
            ("fault.drop", {"seconds": "3"}),
            ("fault.drop", {"seconds": True}),
            ("fault.drop", {}),
            ("fault.delay_ms", {"ms": 0}),
            ("fault.delay_ms", {"ms": 10001}),
            ("fault.delay_ms", {"ms": -5}),
            ("fault.delay_ms", {"ms": True}),
            ("fault.delay_ms", {}),
            ("fault.vfd_code", {"code": -1}),
            ("fault.vfd_code", {"code": 65536}),
            ("fault.vfd_code", {"code": 1.5}),
            ("fault.vfd_code", {"code": True}),
            ("fault.vfd_code", {}),
        ]
        for name, data in bad_cases:
            resp = _call(plugin, name, data)
            assert resp["ok"] is False, f"{name}{data} должен отказать: {resp!r}"
            assert resp["error"].startswith("bad_args"), f"{name}{data}: {resp!r}"

        first = _call(plugin, "fault.drop", {"seconds": 2})
        assert first["ok"] is True
        second = _call(plugin, "fault.drop", {"seconds": 2})
        assert second["ok"] is False, f"второй drop поверх первого должен быть отклонён: {second!r}"
        # первый drop не должен быть сброшен вторым отказанным вызовом
        assert not _try_connect(_HOST, port, timeout=0.5), "второй drop не должен был сбросить первый"
        clear_resp = _call(plugin, "fault.clear")
        assert clear_resp["ok"] is True
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")
