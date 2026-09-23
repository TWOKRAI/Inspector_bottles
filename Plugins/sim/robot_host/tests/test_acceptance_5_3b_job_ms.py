# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.3b — ручка ``job_ms`` в ``SimRobotHostPlugin`` (§4.2.3 контракта).

Независимый tester, worktree на коммите контракта лида (``bfe9edd4``), до реализации.
Контракт — ТОЛЬКО §4.2.3/§4.4 ``plans/line-sim/phase-5-contract-5.3.md``. Харнесс —
``PluginContext`` + реальный ``SimRobotServer`` на свободном порту, тот же приём, что
``Plugins/sim/robot_host/tests/test_belt_commands.py`` (прочитан в этом же коммите
для сигнатуры фикстур, не для контракта job_ms — там его ещё нет).

**Интерпретация тестера, названная явно:** контракт не даёт публичного способа
прочитать применённый ``job_ticks`` (нет команды/поля в ``cmd_status``) — публичный
Modbus-раунд-трип с ожиданием тиков ``free`` был бы намного тяжелее и всё равно
завязан на реализацию таймингов. Вместо этого ``RobotSimCore`` (импортированный В
МОДУЛЕ плагина под именем ``RobotSimCore``) подменяется шпионом, который делегирует
реальному классу и запоминает переданный ``job_ticks`` — это ровно то место
контракта §4.2.3, которое проверяется («конфиг -> job_ticks -> конструктор ядра»),
независимо от того, как модуль называет свои внутренние методы.

Сегодня ``job_ms`` в конфиге плагином не читается вовсе: и «job_ticks вычислен по
формуле», и «плохой job_ms -> ``_fail``» падают на РЕАЛЬНОМ, наблюдаемом поведении
(job_ticks остаётся дефолтным 2 / плагин остаётся ``running`` вместо ``error``) —
не на харнесс-ошибке (импорт/атрибут).
"""

from __future__ import annotations

import socket
import threading
from typing import Any

import pytest

import Plugins.sim.robot_host.plugin as robot_plugin_module
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.server.sim_core import TICK_INTERVAL_S

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом, перегенерировать"
    return port


def _make_plugin(port: int, **extra_cfg: Any) -> tuple[SimRobotHostPlugin, PluginContext]:
    services = MockProcessServices(name="robot")
    cfg = {"host": _HOST, "port": port, "unit_id": 2, "auto_start": True}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx


def _run_with_deadline(fn, *, timeout: float = 10.0) -> None:
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном (не висим,
    см. правило проекта: тест, который вешается вместо падения — хуже отсутствующего)."""
    exc: list[BaseException] = []

    def _target() -> None:
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 — пробрасываем наружу после join
            exc.append(e)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов не завершился за {timeout}с — похоже на зависание"
    if exc:
        raise exc[0]


@pytest.fixture
def job_ticks_spy(monkeypatch):
    """Шпион вокруг ``RobotSimCore`` в модуле плагина — см. докстринг файла.

    Делегирует реальному классу (сервер должен получить настоящее ядро), запоминает
    ``job_ticks`` каждого вызова конструктора.
    """
    real_cls = robot_plugin_module.RobotSimCore
    calls: list[int] = []

    class _Spy:
        def __new__(cls, *args, **kwargs):
            calls.append(kwargs.get("job_ticks", real_cls.__init__.__kwdefaults__.get("job_ticks")))
            return real_cls(*args, **kwargs)

    monkeypatch.setattr(robot_plugin_module, "RobotSimCore", _Spy)
    return calls


@pytest.mark.parametrize(
    "job_ms, expected_job_ticks",
    [
        (1000, 100),  # §4.2.3: job_ticks = round(job_ms / (TICK_INTERVAL_S*1000)) = round(1000/10)
        (None, 2),  # ключ отсутствует -> ядро как сейчас (job_ticks=2, дефолт RobotSimCore)
    ],
    ids=["job_ms=1000", "job_ms-absent"],
)
def test_job_ms_sets_job_ticks(job_ticks_spy, job_ms, expected_job_ticks):
    assert TICK_INTERVAL_S == 0.01, "формула теста считает от TICK_INTERVAL_S=0.01 (sim_core.py)"
    port = _free_port()
    extra_cfg = {} if job_ms is None else {"job_ms": job_ms}
    plugin, ctx = _make_plugin(port, **extra_cfg)
    try:
        _run_with_deadline(lambda: plugin._start_server(ctx))
        assert plugin.cmd_status()["state"] == "running", "сервер не поднялся — проверка ниже бессмысленна"
        assert job_ticks_spy, "RobotSimCore ни разу не сконструирован"
        assert job_ticks_spy[-1] == expected_job_ticks, (
            f"job_ms={job_ms!r}: ожидался job_ticks={expected_job_ticks}, "
            f"передано {job_ticks_spy[-1]} — §4.2.3 не реализован"
        )
    finally:
        plugin.shutdown(ctx)


@pytest.mark.parametrize("bad_job_ms", [0, -500, "abc"], ids=["zero", "negative", "not-a-number"])
def test_bad_job_ms_fails_plugin_not_process(bad_job_ms):
    """§4.2.3: ``job_ms <= 0`` или не число -> ошибка конфигурации через ``_fail``
    (``state == "error"``), процесс живёт (``cmd_status`` продолжает отвечать,
    исключение из ``_start_server`` наружу не летит)."""
    port = _free_port()
    plugin, ctx = _make_plugin(port, job_ms=bad_job_ms)

    _run_with_deadline(lambda: plugin._start_server(ctx))

    status = plugin.cmd_status()
    assert status["state"] == "error", (
        f"job_ms={bad_job_ms!r}: ожидалось state='error' (§4.2.3 валидация ещё не реализована), "
        f"получено {status['state']!r}"
    )
    # Процесс жив: команда статуса по-прежнему отвечает штатным dict, не бросает.
    assert isinstance(plugin.cmd_status(), dict)
    if plugin._server is not None:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# Лид, после break-injection 5.3b: инъекция J9 («bool принимается как число»)
# выживала. YAML `job_ms: true` — это `True`, а `True` — подкласс `int` (== 1).
# --------------------------------------------------------------------------- #


def test_bool_job_ms_is_rejected():
    port = _free_port()
    plugin, ctx = _make_plugin(port, job_ms=True)

    _run_with_deadline(lambda: plugin._start_server(ctx))

    status = plugin.cmd_status()
    assert status["state"] == "error", f"job_ms=True принят как число: state={status['state']!r}"
    if plugin._server is not None:
        plugin.shutdown(ctx)
