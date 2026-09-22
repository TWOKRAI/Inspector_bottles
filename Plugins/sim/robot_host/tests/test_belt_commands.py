# -*- coding: utf-8 -*-
"""RED-приёмка Task 2.3a — командная поверхность ленты в ``SimRobotHostPlugin``
(line-sim Ф2 «правда ленты»: ``belt.run``/``belt.stop``/``belt.jog``/
``belt.calibrate``/``belt.status``).

Независимый tester, worktree на коммите ДО реализации (``4aa2a8c3``). Контракт —
ТОЛЬКО из блока REDS Task 2.3a плана (``plans/line-sim/phase-2-belt-truth.md``).
Ни одна из пяти команд сегодня не зарегистрирована в ``SimRobotHostPlugin.commands``
— ожидаемый провал ``KeyError``/``AttributeError`` на диспетче.

Харнесс — ``MockProcessServices`` + реальный ``PluginContext`` + реальный
``SimRobotServer`` на свободном порту (тот же приём, что у
``Plugins/sim/robot_host/tests/test_hazards.py``), команды диспетчируются через
публичный контракт ``plugin.commands["<имя>"]`` -> ``getattr(plugin, method)`` —
без угадывания внутренних имён методов.
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

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать


def _free_port() -> int:
    """Свободный TCP-порт от ОС (bind на 0), с проверкой против портов живого стенда."""
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
    cfg = {"host": _HOST, "port": port, "unit_id": 2, "auto_start": True}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _call(plugin: SimRobotHostPlugin, name: str, data: dict | None = None) -> dict:
    """Вызвать команду через публичный контракт ``commands`` (см. докстринг файла)."""
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _wait_until(predicate, *, timeout: float, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _run_with_deadline(fn, *, timeout: float, label: str):
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном (не висим)."""
    result: dict = {}
    error: dict = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — хотим видеть любую причину
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
        yield plugin, ctx, services
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")


def test_run_25hz_default_calibration(running_plugin) -> None:
    """REDS 4: belt.run{freq_hz:25} + один тик -> mm_s ~= 50.5656 (калибровка по
    умолчанию 101.1311 мм/с на максимальной частоте 50 Гц), run True, freq_hz 25.0."""
    plugin, _ctx, _services = running_plugin
    core = plugin._server.core

    status = _call(plugin, "belt.run", {"freq_hz": 25})
    assert status["ok"] is True
    core.tick()

    status = _call(plugin, "belt.status")
    assert status["mm_s"] == pytest.approx(50.5656, abs=0.5)
    assert status["run"] is True
    assert status["freq_hz"] == 25.0


def test_command_goes_through_mailbox(running_plugin) -> None:
    """REDS 5: belt.run{freq_hz:25, reverse:true} пишет mailbox ДО тика (RUN/DIR/FREQ
    + FLAG последним), после тика FLAG гасится и зеркало обновляется."""
    plugin, _ctx, _services = running_plugin
    core = plugin._server.core

    _call(plugin, "belt.run", {"freq_hz": 25, "reverse": True})

    assert core.read(0x1200, 3) == [1, 1, 2500]
    assert core.read(0x1204, 1) == [1]

    core.tick()

    assert core.read(0x1204, 1) == [0]
    assert core.read(0x1210, 1) == [1]
    assert core.read(0x1211, 1) == [2500]


def test_stop_writes_only_run(running_plugin) -> None:
    """REDS 6: belt.stop пишет только RUN=0 — CMD_FREQ (0x1202) не трогается."""
    plugin, _ctx, _services = running_plugin
    core = plugin._server.core

    _call(plugin, "belt.run", {"freq_hz": 30})
    core.tick()
    _call(plugin, "belt.stop")
    core.tick()

    status = _call(plugin, "belt.status")
    assert status["mm_s"] == pytest.approx(0.0)
    assert core.read(0x1202, 1) == [3000]


def test_calibrate_200_then_run_50(running_plugin) -> None:
    """REDS 7: belt.calibrate{200} + belt.run{freq_hz:50} + тик -> mm_s == 200.0,
    mm_s_at_max_freq == 200.0."""
    plugin, _ctx, _services = running_plugin
    core = plugin._server.core

    calib = _call(plugin, "belt.calibrate", {"mm_s_at_max_freq": 200})
    assert calib["ok"] is True
    _call(plugin, "belt.run", {"freq_hz": 50})
    core.tick()

    status = _call(plugin, "belt.status")
    assert status["mm_s"] == pytest.approx(200.0)
    assert status["mm_s_at_max_freq"] == pytest.approx(200.0)


def test_jog_without_refresh_stops_in_window() -> None:
    """REDS 8: belt.jog{direction:-1, freq_hz:10} при jog_timeout_ms=500 (дефолт),
    реальный тикер и реальный паблишер (publish_ms=50) — лента едет сразу после
    команды и останавливается сама в окне [0.5, 1.0] с; с подкачкой каждые 200 мс
    едет не меньше 1.5 с."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port, publish_ms=50)
    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    try:
        t0 = time.monotonic()  # окно dead-man [0.5, 1.0] с отсчитывается от команды
        status = _call(plugin, "belt.jog", {"direction": -1, "freq_hz": 10})
        assert status["ok"] is True

        # Арбитраж ведущего 2026-09-22: команда пишет mailbox, применяет её следующий тик
        # тикера (≤ ~12 мс) — «сразу» значит «за один-два тика», а не синхронно в том же
        # вызове (так и сказано в спеке 2.3a). Ждём с дедлайном 0.2 с.
        moving = _wait_until(lambda: _call(plugin, "belt.status")["mm_s"] < 0, timeout=0.2, interval=0.005)
        assert moving, f"лента не тронулась за 0.2 с: {_call(plugin, 'belt.status')!r}"

        stopped = _wait_until(lambda: _call(plugin, "belt.status")["mm_s"] == 0.0, timeout=1.2, interval=0.05)
        elapsed = time.monotonic() - t0
        assert stopped, "лента не остановилась сама (dead-man watchdog не сработал)"
        assert 0.5 <= elapsed <= 1.0, f"остановка вне окна dead-man: elapsed={elapsed:.3f} с"

        # Подкачка каждые 200 мс держит ленту не меньше 1.5 с суммарно.
        _call(plugin, "belt.run", {"freq_hz": 0})  # сброс перед вторым прогоном
        _call(plugin, "belt.jog", {"direction": -1, "freq_hz": 10})
        t1 = time.monotonic()
        while time.monotonic() - t1 < 1.5:
            time.sleep(0.2)
            _call(plugin, "belt.jog", {"direction": -1, "freq_hz": 10})
        still_moving = _call(plugin, "belt.status")["mm_s"]
        assert still_moving < 0, f"с подкачкой лента должна ехать ещё >= 1.5 с: mm_s={still_moving!r}"
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")


def test_modbus_write_overrides_jog(running_plugin) -> None:
    """REDS 9: belt.jog{direction:1}, затем прямая запись mailbox как Modbus-мастер
    (RUN=1,DIR=0,FREQ=4000 + FLAG) побеждает — по прошествии 1.0 с лента едет на
    новой команде (mm_s ~= 80.905, калибровка по умолчанию 101.1311), jogging False."""
    plugin, _ctx, _services = running_plugin
    core = plugin._server.core

    _call(plugin, "belt.jog", {"direction": 1})

    core.write(0x1200, [1, 0, 4000])
    core.write(0x1204, [1])

    time.sleep(1.0)

    status = _call(plugin, "belt.status")
    assert status["mm_s"] == pytest.approx(80.905, abs=0.5)
    assert status["jogging"] is False
    # Ревью Task 2.3a, инъекция A8 (не поймана предыдущей версией теста):
    # эффективное состояние ленты должно отражать Modbus-мастера, а не jog.
    assert status["run"] is True
    assert status["freq_hz"] == 40.0
    assert status["reverse"] is False
    # Эффект, а не снимок в том же вызове (ведущий, 2026-09-22, инъекция A5): стоп
    # сторожа применился бы только следующим тиком, и статус выше его ещё не видит.
    # Mailbox остаётся записью Modbus-мастера, лента едет и через 0.1 с.
    time.sleep(0.1)
    assert core.read(0x1200, 3) == [1, 0, 4000], "сторож jog перетёр команду Modbus-мастера"
    assert _call(plugin, "belt.status")["mm_s"] == pytest.approx(80.905, abs=0.5)


def test_bad_args_and_no_server(running_plugin) -> None:
    """REDS 10: freq_hz вне [0, freq_max_hz] и direction != +-1 -> ok False,
    error начинается с 'bad_args'; сервер не поднят -> 'server_not_running'."""
    plugin, _ctx, _services = running_plugin

    bad_run = _call(plugin, "belt.run", {"freq_hz": 60})
    assert bad_run["ok"] is False
    assert bad_run["error"].startswith("bad_args"), bad_run

    bad_jog = _call(plugin, "belt.jog", {"direction": 0})
    assert bad_jog["ok"] is False
    assert bad_jog["error"].startswith("bad_args"), bad_jog

    port2 = _free_port()
    plugin2, ctx2, _services2 = _make_plugin(port2, auto_start=False)
    try:
        status = _call(plugin2, "belt.status")
        assert status["ok"] is False
        assert status["error"] == "server_not_running", status
    finally:
        _run_with_deadline(lambda: plugin2.shutdown(ctx2), timeout=5.0, label="shutdown2")
