# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.3-tw — TIME_WAIT переживается, реально занятый порт нет.

Независимый прогон (tester, RED-режим): контракт берётся ТОЛЬКО из докстринга
``Plugins/sim/robot_host/plugin.py`` (наблюдаемое поведение — ``sim_robot.status``
и реальный TCP-коннект), внутренние имена (``_probe_port_free``, ``setsockopt``,
``bind``) не шпионятся ни разу.

AC1 (был RED на 6e21843d, до фикса): сервер-сторона TIME_WAIT на 127.0.0.1:<порт> —
плагин обязан подняться и слушать в пределах 5 с. На 6e21843d ``_probe_port_free``
биндил БЕЗ ``SO_REUSEADDR`` — пробный bind на TIME_WAIT-порту падал ``EADDRINUSE``
без обращения к pymodbus, и плагин уходил в ``state == "error"`` вместо ``"running"``.
Фикс — ``SO_REUSEADDR`` на пробном сокете (POSIX), стенд Task 1.3.

AC2 (был GREEN и до фикса — контроль регрессии): порт занят ЖИВЫМ чужим
listener'ом — плагин обязан красиво отказать: ``state == "error"``, непустая
причина, ровно один инцидент в health, чужой listener продолжает жить.

Каждый тест — свой свежий порт (bind на 0, см. AC3 докстринга задачи):
TIME_WAIT на macOS живёт ~30 с (2×MSL), и общий порт между тестами дал бы
ложный RED/GREEN от соседа. Порты 5021/8765/8766/8091 не трогаем — там живой
стенд.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.health import HealthState
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin

_HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091}  # живой стенд — не трогать


def _free_port() -> int:
    """Свободный порт от ОС (bind на 0), с проверкой против списка живого стенда."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом, перегенерировать"
    return port


def _run_with_deadline(fn, *, timeout: float, label: str):
    """Любой потенциально блокирующий вызов — в daemon-потоке с join-дедлайном.

    Регрессия обязана УПАСТЬ, а не повесить прогон: если ``fn`` не вернулась за
    ``timeout`` секунд, тест проваливается явным AssertionError, а не зависает
    вместе с pytest.
    """
    result: dict = {}
    error: dict = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — хотим увидеть любую причину
            error["exc"] = exc

    thread = threading.Thread(target=_target, name=f"deadline-{label}", daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise AssertionError(f"{label} не вернулась за {timeout} с — похоже на зависание, не на штатный отказ")
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def _make_ctx(port: int) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    services = MockProcessServices(name="sim_robot_host_test")
    ctx = PluginContext(
        services=services,
        config={"host": _HOST, "port": port, "unit_id": 2, "auto_start": True},
        plugin_name="sim_robot_host",
    )
    plugin = SimRobotHostPlugin()
    return plugin, ctx, services


def _shutdown(plugin: SimRobotHostPlugin, ctx: PluginContext) -> None:
    """Полный configure->start->shutdown уже пройден — просто дожимаем shutdown."""
    _run_with_deadline(lambda: plugin._do_shutdown(ctx), timeout=5.0, label="shutdown")


def _wait_until(predicate, *, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _tcp_connect_ok(port: int, *, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((_HOST, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Установка TIME_WAIT на стороне сервера
# --------------------------------------------------------------------------- #


def _put_port_into_server_side_time_wait(port: int) -> None:
    """Server-side TIME_WAIT: accepted-конец закрывается ПЕРВЫМ (активный close).

    Порядок закрытия (сервер -> клиент -> listener) — ровно тот, что кладёт
    TIME_WAIT на локальный адрес ``(host, port)``, которым потом хочет
    забиндиться плагин: TIME_WAIT остаётся за стороной, что закрылась первой.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((_HOST, port))
    listener.listen(1)

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((_HOST, port))
    server_conn, _addr = listener.accept()

    server_conn.close()  # 1) сервер закрывается первым -> TIME_WAIT на его стороне
    client.close()  # 2) клиент
    listener.close()  # 3) listener


# --------------------------------------------------------------------------- #
# AC1 — TIME_WAIT переживается
# --------------------------------------------------------------------------- #


def test_precondition_plain_bind_on_time_wait_port_raises_eaddrinuse() -> None:
    """Сначала доказываем, что сценарий вообще воспроизводит TIME_WAIT.

    Без этой проверки AC1 мог бы пройти ВПУСТУЮ — если порт после закрытий
    почему-то оказался свободным (ОС не поставила TIME_WAIT), тест ниже
    проверял бы уже не то, что заявлено.
    """
    port = _free_port()
    _put_port_into_server_side_time_wait(port)

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError) as exc_info:
            probe.bind((_HOST, port))
        assert exc_info.value.errno == 48 or "Address already in use" in str(exc_info.value)
    finally:
        probe.close()


def test_plugin_survives_time_wait_and_reports_running() -> None:
    """AC1 (был RED до фикса): плагин обязан подняться поверх TIME_WAIT."""
    port = _free_port()
    _put_port_into_server_side_time_wait(port)

    plugin, ctx, _services = _make_ctx(port)
    try:
        _run_with_deadline(lambda: plugin._do_configure(ctx), timeout=5.0, label="configure")
        _run_with_deadline(lambda: plugin._do_start(ctx), timeout=5.0, label="start")

        status_ok = _wait_until(
            lambda: plugin.cmd_status()["state"] == "running",
            timeout=5.0,
        )
        status = plugin.cmd_status()
        assert status_ok, f"плагин не поднялся за 5с поверх TIME_WAIT, статус: {status}"
        assert status["running"] is True

        connect_ok = _wait_until(lambda: _tcp_connect_ok(port), timeout=5.0)
        assert connect_ok, f"TCP-коннект к порту {port} не удался за 5с после старта плагина"
    finally:
        _shutdown(plugin, ctx)


# --------------------------------------------------------------------------- #
# AC2 — реально занятый порт (регрессионный контроль, ожидание GREEN сейчас)
# --------------------------------------------------------------------------- #


def test_plugin_reports_error_on_genuinely_busy_port() -> None:
    """AC2: чужой listener жив на порту -> плагин отказывает мирно, не роняя процесс."""
    port = _free_port()
    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    foreign.bind((_HOST, port))
    foreign.listen(1)

    plugin, ctx, services = _make_ctx(port)
    try:
        _run_with_deadline(lambda: plugin._do_configure(ctx), timeout=5.0, label="configure")

        # start() не имеет права бросить исключение наружу (докстринг plugin.py).
        _run_with_deadline(lambda: plugin._do_start(ctx), timeout=5.0, label="start")

        status = plugin.cmd_status()
        assert status["state"] == "error"
        # ``reason`` не входит в контракт cmd_status() (см. plugin.py) — причина
        # проверяется по внутреннему полю, которое докстринг называет явно.
        assert plugin._reason != "", "внутренняя причина отказа обязана быть непустой"

        state = services._health_state
        assert isinstance(state, HealthState)
        assert state.error_count == 1, f"ожидался РОВНО один инцидент health, получено {state.error_count}"

        # Чужой listener не пострадал — всё ещё принимает соединения.
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(1.0)
        try:
            client.connect((_HOST, port))
            foreign_conn, _addr = foreign.accept()
            foreign_conn.close()
        finally:
            client.close()
    finally:
        _shutdown(plugin, ctx)
        foreign.close()


def test_plugin_start_does_not_raise_on_busy_port() -> None:
    """AC2, отдельно: start() как таковой не бросает исключение (докстринг plugin.py)."""
    port = _free_port()
    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    foreign.bind((_HOST, port))
    foreign.listen(1)

    plugin, ctx, _services = _make_ctx(port)
    try:
        _run_with_deadline(lambda: plugin._do_configure(ctx), timeout=5.0, label="configure")
        # Если start() бросит — _run_with_deadline перевыбросит исключение сюда,
        # и pytest покажет его как провал именно ЭТОГО теста.
        _run_with_deadline(lambda: plugin._do_start(ctx), timeout=5.0, label="start")
    finally:
        _shutdown(plugin, ctx)
        foreign.close()
