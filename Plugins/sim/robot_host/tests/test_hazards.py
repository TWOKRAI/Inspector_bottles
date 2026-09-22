# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ``SimRobotHostPlugin`` (Task 1.1 плана ``line-sim``).

Что здесь проверяется — четыре опасных места механизма, названные в докстринге
``plugin.py``: (a) занятый порт обнаруживается СВОИМ пробным bind'ом и не роняет
процесс; (b) повторный ``start`` при живом сервере — no-op; (c) ``shutdown``
закрывает порт достаточно быстро; (d) наблюдатель ``_on_write`` считает только
записи, а не чтения. Харнесс — ``MockProcessServices`` + реальный конструктор
``PluginContext`` (тот же приём, что у ``Plugins/io/otel_export/tests``):
границу процесса (командный менеджер, stats) подделываем, ``PluginContext`` и
плагин — настоящие.

Тесты (b)/(c)/(d) поднимают РЕАЛЬНЫЙ ``SimRobotServer`` (нужен ``pymodbus`` —
``pytest.mark.skipif(not ROBOT_AVAILABLE, ...)``, тот же флаг, что у
``Services/robot_comm/tests/test_sim_e2e.py``); тест (a) — нет, порт занят
проверяется ДО обращения к ``pymodbus`` (см. докстринг ``plugin.py`` про
асинхронный bind фонового потока).
"""

from __future__ import annotations

import socket
import threading
import time
import types
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.server.sim_core import VFD_CMD_ADDR, RobotSimCore

pytestmark = pytest.mark.timeout(30)


def _free_port() -> int:
    """Свободный TCP-порт (см. Services/robot_comm/tests/test_sim_e2e.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_plugin(
    port: int, *, unit_id: int = 2, auto_start: bool = True, **extra_cfg: Any
) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    """Собрать плагин + PluginContext на MockProcessServices с реальным MockStatsManager."""
    stats = MockStatsManager()
    services = MockProcessServices(name="robot", stats_manager=stats)
    cfg = {"host": "127.0.0.1", "port": port, "unit_id": unit_id, "auto_start": auto_start}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _make_bare_plugin(**extra_cfg: Any) -> tuple[SimRobotHostPlugin, RobotSimCore]:
    """Плагин + «голое» ``RobotSimCore`` без реального ``SimRobotServer`` (не
    нужен ``pymodbus`` — тот же приём, что в ревьюерских скриптах q2/q5):
    для проверок ``belt.*`` и сторожа хватает `core`, сетевой части не
    требуется."""
    cfg = {"auto_start": False}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=MockProcessServices(name="robot"), config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    core = RobotSimCore()
    plugin._server = types.SimpleNamespace(core=core)
    return plugin, core


# --------------------------------------------------------------------------- #
# (a) Порт занят -> report_error, состояние error, процесс живёт (не бросает) #
# --------------------------------------------------------------------------- #


def test_port_busy_reports_error_not_crash() -> None:
    """Порт занят СВОИМ сокетом -> ``_start_server`` не бросает, health получил ошибку."""
    port = _free_port()
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", port))
    occupied.listen(1)
    try:
        plugin, ctx, services = _make_plugin(port)

        # Не должно бросить — вызывающий (start()) не оборачивает в try/except.
        plugin.start(ctx)

        assert plugin._state == "error", f"ожидали state='error', получили {plugin._state!r}"
        assert plugin._server is None, "сервер не должен быть создан при занятом порту"

        health_state = getattr(services, "_health_state", None)
        assert health_state is not None, "ctx.health.report_error должен был создать HealthState на services"
        assert health_state.error_count >= 1, f"report_error не учтён: error_count={health_state.error_count}"
    finally:
        occupied.close()


# --------------------------------------------------------------------------- #
# (b) Повторный start при живом сервере — no-op                               #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_double_start_is_noop() -> None:
    """Второй вызов ``start`` не пересоздаёт сервер (тот же объект)."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    try:
        plugin.start(ctx)
        assert plugin._state == "running", (
            f"первый start не поднял сервер: state={plugin._state!r}, reason={plugin._reason!r}"
        )
        first_server = plugin._server
        assert first_server is not None

        plugin.start(ctx)
        assert plugin._server is first_server, "повторный start пересоздал сервер — должен быть no-op"
        assert plugin._state == "running"
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (c) shutdown закрывает порт                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_shutdown_closes_port() -> None:
    """После ``shutdown`` порт освобождается за разумное время (TRAPS lead'а, п.4)."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    plugin.start(ctx)
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"

    # Дать серверу реально начать слушать порт перед остановом.
    deadline = time.monotonic() + 5.0
    listening = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                listening = True
                break
        except OSError:
            time.sleep(0.1)
    assert listening, f"SimRobotServer не начал слушать {port} за 5с"

    plugin.shutdown(ctx)
    assert plugin._server is None

    deadline = time.monotonic() + 5.0
    closed = False
    while time.monotonic() < deadline:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", port))
            probe.close()
            closed = True
            break
        except OSError:
            time.sleep(0.1)
    assert closed, f"порт {port} не освободился за 5с после shutdown()"


# --------------------------------------------------------------------------- #
# (d) _on_write считает только записи, публикует метрику дельтой              #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_on_write_counts_only_writes() -> None:
    """Чтение (values=None) не считается; запись — считается и уходит в record_metric."""
    port = _free_port()
    plugin, ctx, services = _make_plugin(port)

    # Чтение: fc=3 (read holding registers), values=None — не должно посчитаться.
    plugin._on_write(3, 0x1112, None)
    assert plugin._writes_seen == 0, "чтение (values=None) не должно увеличивать writes_seen"

    # Запись: fc=16 (write multiple registers), values — список.
    plugin._on_write(16, 0x1000, [1, 2])
    assert plugin._writes_seen == 1, "запись должна увеличить writes_seen ровно на 1"

    status = plugin.cmd_status()
    assert status["writes_seen"] == 1, status

    stats: MockStatsManager = services.stats_manager
    counter_records = [r for r in stats.records if r[0] == "counter" and r[1] == "sim_robot.writes"]
    assert counter_records, f"ctx.record_metric('sim_robot.writes', ...) не был вызван: {stats.records!r}"
    assert counter_records[-1][2] == 1, f"дельта метрики должна быть 1: {counter_records!r}"

    # Ещё одна запись + повторный status — метрика уходит ВТОРОЙ дельтой (не абсолютом).
    plugin._on_write(16, 0x1000, [3])
    status2 = plugin.cmd_status()
    assert status2["writes_seen"] == 2
    counter_records2 = [r for r in stats.records if r[0] == "counter" and r[1] == "sim_robot.writes"]
    assert len(counter_records2) == 2, f"второй cmd_status должен добавить ровно одну дельту: {counter_records2!r}"
    assert counter_records2[-1][2] == 1, f"вторая дельта должна быть 1 (не 2): {counter_records2!r}"

    plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (e) Паблишер уровней работает БЕЗ state_proxy (ревью Task 2.2, находка №2)  #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_publish_once_reports_metrics_without_state_proxy() -> None:
    """RED до ревью: ``_publish_once`` возвращалась ДО ``ctx.publish_metric``,
    если ``ctx.state_proxy is None`` — на процессе без Task 2.0 (мир не влит)
    уровни ``encoder``/``belt_mm_s``/``writes_seen`` молчали НАВСЕГДА, хотя
    наблюдать за ними можно и без общего мира. Публикация уровней и запись в
    мир — РАЗНЫЕ дороги: без мира падает только вторая (``ctx.state_proxy.set``
    просто не вызывается, без исключения)."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    assert ctx.state_proxy is None, "MockProcessServices по умолчанию не даёт state_proxy — тот самый случай"
    plugin.start(ctx)
    try:
        assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
        # Вторая половина находки: воркер паблишера поднимается и БЕЗ мира
        # (ревью итерация 2 — инъекция «старая ветка start» проходила зелёной).
        workers = _services.worker_manager.calls["create_worker"]
        assert workers and workers[0][0] == "sim_robot_world_publisher", f"воркер паблишера не создан: {workers!r}"

        published: list[tuple[str, object]] = []
        ctx.publish_metric = lambda name, value: published.append((name, value))  # noqa: E731

        plugin._publish_once()

        names = [name for name, _ in published]
        assert names == ["encoder", "belt_mm_s", "writes_seen"], (
            f"без state_proxy паблишер обязан отдать все три уровня, получено: {published!r}"
        )
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (f) Ревью Task 2.3a — сторож jog под замком, боевой dead-man, строгие типы  #
# --------------------------------------------------------------------------- #


def test_watchdog_holds_lock_across_mailbox_read_and_stop() -> None:
    """Гонка сторожа jog (найдено ревью): без ``self._lock``, удерживаемого на
    ВСЁМ пути ``_check_jog_watchdog`` (дедлайн + чтение mailbox + сравнение +
    ``command_vfd``), ``belt.run`` из другого потока мог записать mailbox
    МЕЖДУ чтением сторожа и его стопом — сторож гасил уже НОВУЮ команду, а не
    свой jog (воспроизведено стохастически 3/20000 без форсинга). Здесь —
    детерминированный форсинг (приём ``_PausingLast`` из
    ``Services/robot_comm/tests/test_belt_drive.py``, только на ``core.read``):
    сторож ставится на паузу СРАЗУ ПОСЛЕ чтения mailbox (уже внутри
    ``self._lock`` — с фиксом), из другого потока запускается ``belt.run``,
    после освобождения паузы проверяем итог.

    С фиксом: ``belt.run`` ждёт освобождения замка сторожем (не завершается
    за 0.2с), а финальный mailbox отражает ``belt.run`` (RUN=1, mm_s≈50.57) —
    он пишет ПОСЛЕДНИМ, уже после того как сторож (используя УСТАРЕВШЕЕ
    прочитанное значение) успел записать стоп внутри своего замка. Без фикса
    ``belt.run`` не блокируется НИЧЕМ (не завершается позже 0.2с — сторож
    ничем его не держит) и завершается ДО того, как сторож выходит из паузы;
    когда сторож возобновляется, он безусловно перетирает mailbox стопом
    (``current == regs`` — сравнение на устаревших данных, прочитанных ДО
    ``belt.run``) — итоговый mailbox остаётся остановленным."""
    plugin, core = _make_bare_plugin(jog_timeout_ms=50)

    status = plugin.cmd_belt_jog({"direction": 1, "freq_hz": 10})
    assert status["ok"] is True
    core.tick()
    time.sleep(0.06)  # дедлайн jog (50 мс) гарантированно прошёл

    real_read = core.read
    entered = threading.Event()
    release = threading.Event()

    def read_pausing(addr: int, count: int = 1) -> list[int]:
        value = real_read(addr, count)
        if threading.current_thread().name == "watchdog":
            entered.set()
            assert release.wait(timeout=2.0), "release не был выставлен — тест завис бы без таймаута"
        return value

    core.read = read_pausing
    watchdog_t = threading.Thread(target=plugin._check_jog_watchdog, name="watchdog", daemon=True)
    watchdog_t.start()
    assert entered.wait(timeout=2.0), "сторож не дошёл до чтения mailbox за 2с"

    run_result: dict = {}

    def _run_belt() -> None:
        run_result["value"] = plugin.cmd_belt_run({"freq_hz": 25})

    cmd_t = threading.Thread(target=_run_belt, name="cmd", daemon=True)
    cmd_t.start()
    cmd_t.join(timeout=0.2)
    assert cmd_t.is_alive(), (
        "belt.run не должен пройти, пока сторож держит self._lock на паузе внутри чтения mailbox "
        "(без фикса — command_vfd ничем не заблокирован и завершается сразу)"
    )

    release.set()
    watchdog_t.join(timeout=2.0)
    cmd_t.join(timeout=2.0)
    core.read = real_read
    assert not watchdog_t.is_alive(), "сторож завис — дедлок под self._lock"
    assert not cmd_t.is_alive(), "belt.run завис — дедлок под self._lock"
    assert run_result["value"]["ok"] is True

    core.tick()
    final = core.read(VFD_CMD_ADDR, 3)
    assert final[0] == 1, f"финальный mailbox: RUN должен быть 1 (belt.run — последний писавший), получено {final!r}"
    assert core.belt_mm_s == pytest.approx(50.5656, abs=0.5), f"mm_s={core.belt_mm_s!r}: лента должна ехать 25 Гц"


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_publish_loop_dead_man_stops_belt_for_real() -> None:
    """Боевой dead-man путь (ревью Task 2.3a): ``MockWorkerManager.create_worker``
    — no-op запись вызова (``testing.py``), ни один REDS-тест до этого не
    гонял ``_publish_loop`` НА САМОМ ДЕЛЕ. Здесь — реальный
    ``plugin._publish_loop`` в daemon-потоке, ``belt.status`` НИ РАЗУ не
    опрашивается (единственный тик — сам паблишер), ``core.belt_mm_s``
    читается НАПРЯМУЮ, а не через ``_belt_status()`` — чтобы проверить именно
    путь (1) из README (тик ``_publish_loop``), а не опортунистический путь
    (2) через статус."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port, publish_ms=50, jog_timeout_ms=500)
    plugin.start(ctx)
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    core = plugin._server.core

    stop_event = threading.Event()
    pause_event = threading.Event()
    loop_thread = threading.Thread(
        target=plugin._publish_loop, args=(stop_event, pause_event), name="publish_loop", daemon=True
    )
    loop_thread.start()
    try:
        result = plugin.cmd_belt_jog({"direction": 1, "freq_hz": 10})
        assert result["ok"] is True

        t0 = time.monotonic()
        deadline = t0 + 1.2
        stopped = False
        while time.monotonic() < deadline:
            if core.belt_mm_s == 0.0:
                stopped = True
                break
            time.sleep(0.02)
        elapsed = time.monotonic() - t0
        assert stopped, f"боевой _publish_loop не остановил ленту за 1.2с: core.belt_mm_s={core.belt_mm_s!r}"
        assert 0.5 <= elapsed <= 1.0, f"остановка вне окна dead-man [0.5, 1.0]с: elapsed={elapsed:.3f}с"
    finally:
        stop_event.set()
        loop_thread.join(timeout=2.0)
        assert not loop_thread.is_alive(), "publish_loop не остановился за 2с после stop_event"
        plugin.shutdown(ctx)


def test_publish_loop_dead_man_while_paused() -> None:
    """Пауза паблишера (ревью Task 2.3a, п.6): без вызова сторожа В ВЕТКЕ
    ПАУЗЫ ``belt.jog`` остался бы живым сколь угодно долго, пока процесс
    стоит на паузе и никто не опрашивает ``belt.status`` (единственный
    другой путь к сторожу). ``pause_event`` взведён ДО старта луп-потока —
    ``_publish_once`` не зовётся вовсе, единственный тик — сторож в ветке
    паузы. Голый ``RobotSimCore`` без ``SimRobotServer``/тикера — тикаем
    вручную из теста, синхронно с ожиданием (без гонки за ``core.regs`` — тик
    и сторож в этом тесте не работают одновременно на одних данных дольше,
    чем занимает ``core.tick()``)."""
    plugin, core = _make_bare_plugin(jog_timeout_ms=300, publish_ms=50)

    status = plugin.cmd_belt_jog({"direction": 1, "freq_hz": 10})
    assert status["ok"] is True
    core.tick()
    assert core.belt_mm_s != 0.0, "лента должна тронуться сразу после тика jog"

    stop_event = threading.Event()
    pause_event = threading.Event()
    pause_event.set()
    loop_thread = threading.Thread(
        target=plugin._publish_loop, args=(stop_event, pause_event), name="publish_loop_paused", daemon=True
    )
    loop_thread.start()
    try:
        deadline = time.monotonic() + 1.0
        stopped = False
        while time.monotonic() < deadline:
            core.tick()
            if core.belt_mm_s == 0.0:
                stopped = True
                break
            time.sleep(0.02)
        assert stopped, f"сторож не сработал на паузе за 1.0с: core.belt_mm_s={core.belt_mm_s!r}"
    finally:
        stop_event.set()
        loop_thread.join(timeout=2.0)
        assert not loop_thread.is_alive(), "publish_loop (пауза) не остановился за 2с после stop_event"


def test_belt_run_rejects_non_bool_reverse() -> None:
    """``reverse`` обязан быть НАСТОЯЩИМ ``bool`` (ревью Task 2.3a, п.5):
    ``bool("false") is True`` в Python — старая проверка ``bool(data.get(...))``
    принимала за истину любую непустую строку. mailbox не должен трогаться
    при ``bad_args``."""
    plugin, core = _make_bare_plugin()
    before = core.read(VFD_CMD_ADDR, 3)

    result = plugin.cmd_belt_run({"freq_hz": 25, "reverse": "false"})

    assert result["ok"] is False
    assert result["error"].startswith("bad_args"), result
    assert core.read(VFD_CMD_ADDR, 3) == before, "mailbox не должен трогаться при bad_args"


def test_belt_jog_rejects_bool_direction() -> None:
    """``direction`` обязан быть НАСТОЯЩИМ ``int`` ``+-1`` (ревью Task 2.3a,
    п.5): ``bool`` — подкласс ``int`` в Python, ``True in (1, -1)`` истинно,
    старая проверка принимала ``direction=True`` за ``+1``."""
    plugin, _core = _make_bare_plugin()

    result = plugin.cmd_belt_jog({"direction": True, "freq_hz": 10})

    assert result["ok"] is False
    assert result["error"].startswith("bad_args"), result
