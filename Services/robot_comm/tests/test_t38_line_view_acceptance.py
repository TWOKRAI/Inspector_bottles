# -*- coding: utf-8 -*-
"""Слепая приёмка T3.8 (RED до кода): вид робота рисует робота ЛИНИИ из ``sim.robot.state``.

Контракт — только публичный перечень брифа лида и ``plans/robot-protocol-v2/tasks/T3.8.reds.md``;
тела ``line_source.py``, ``build_window``/``attach_line``/``main``, ``_publish_once``/
``_robot_state_snapshot``/``configure`` до RED не читались (``line_source.py`` ещё не существует).
Тела ``build_window``/``main`` в ``sim_view.py`` на базе — прежние (демо), их увидел при поиске
образцов запуска; реализации T3.8 в дереве нет.

Хост для REDS 5, 6, 10 — НАСТОЯЩИЙ ``RouterManager`` + НАСТОЯЩИЙ ``StateStoreManager`` за дверью
``setup_backend_ctl_channel(router, host="127.0.0.1", port=0, env={"BACKEND_CTL": "1"})``. Команды
``state.*`` ведут в его ``handle_state_*`` через тонкую прокладку ``get_command_info``/
``handle_command`` (образец ``test_remote_state_proxy.py::_make_command_host``): настоящий
``CommandManager`` требует процесса. Снимок кладёт ``handle_state_set`` от источника ``robot``,
между снимками хост пишет ``sim.belt.encoder`` (revision идут с разрывами, как на линии).
Макет хоста (``_FakeLink``) — только REDS 9.

Ожидаемые значения — литералы из REDS; позы ядра — ``PTP_MOVE`` + тики до ``TLM_MOVING == 0``.
Всё, что может зависнуть, — в daemon-потоке с дедлайном или в подпроцессе с таймаутом.
"""

from __future__ import annotations

import importlib
import json
import re
import socket
import time
from pathlib import Path
from typing import Any, Callable

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy import RemoteStateProxy
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from Plugins.sim.robot_host.tests.host_harness import HOST, free_port, run_with_deadline
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.gui.sim_view import SimView, build_window
from Services.robot_comm.gui.z_view import TimeTape, ZScale
from Services.robot_comm.tests._t38_line_host import (
    _ROBOT_STATE,
    _LineHost,
    _RecordingStateProxy,
    _bare_plugin,
    _build_robot_host,
    _core_at,
    _health_errors,
    _run_main,
    _s16,
    _snapshot,
)


#: позы ядра (мм, мм, мм, град) — литералы REDS
POSE_A = (350.0, -150.0, -60.0, 10.0)
POSE_B = (400.0, -100.0, -90.0, -20.0)
POSE_C = (320.0, -180.0, -50.0, 0.0)
POSE_HOME = (300.0, -210.0, -40.0, -100.0)

_STATUS_A = "X=350.0  Y=-150.0  Z=-60.0  RZ=10.0"
_STATUS_B = "X=400.0  Y=-100.0  Z=-90.0  RZ=-20.0"
_STATUS_C = "X=320.0  Y=-180.0  Z=-50.0  RZ=0.0"

_TLM, _RES, _PMIR = 0x1040, 0x1010, 0x3000


# --------------------------------------------------------------------------- #
# Ядро в заданной позе и снимок                                               #
# --------------------------------------------------------------------------- #


def _line_source() -> Any:
    return importlib.import_module("Services.robot_comm.gui.line_source")


def _attach_line() -> Callable[..., Any]:
    from Services.robot_comm.gui import sim_view

    return sim_view.attach_line


def _src_pose(src: Any) -> tuple[float, float, float, float]:
    return tuple(_s16(src.read(REG[n], 1)[0]) / 10.0 for n in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ"))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Хост: настоящие RouterManager + StateStoreManager за дверью backend_ctl      #
# --------------------------------------------------------------------------- #


def _wait(predicate: Callable[[], bool], timeout: float, step: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def _pump(link: Any, predicate: Callable[[], bool], timeout: float) -> bool:
    """``tick()`` каждые 0.05 с (главный поток) до ``predicate`` или дедлайна."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        link.tick()
        if predicate():
            return True
        time.sleep(0.05)
    link.tick()
    return predicate()


# --------------------------------------------------------------------------- #
# Хост робота (плагин) с записывающим state_proxy                             #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 1. Паблишер кладёт sim.robot.state                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_publisher_puts_robot_state() -> None:
    rec = _RecordingStateProxy()
    plugin, ctx, _services, workers = _build_robot_host(rec, protocol="v2", robot_state_hz=20)
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        assert plugin._state == "running", f"хост не поднялся: {plugin._reason!r}"
        core = plugin._server.core
        time.sleep(1.0)
        states = rec.states()
        assert len(states) >= 5, f"за 1.0 с при robot_state_hz=20 записей sim.robot.state: {len(states)}"

        first = states[0]
        assert [first["pose"][k] for k in ("x_mm", "y_mm", "z_mm", "rz_deg")] == pytest.approx(POSE_HOME, abs=0.05)
        assert (len(first["regs"]["res"]), len(first["regs"]["tlm"]), len(first["regs"]["pmir"])) == (12, 32, 128)
        assert first["model"] == "ScaraModel"
        assert isinstance(first["joints"], list) and len(first["joints"]) == len(core.joints())

        # Тик встал -> блок tlm снимка равен тому, что отдаёт ядро.
        assert workers.stop_worker("sim_robot_ticker") is True
        time.sleep(0.2)
        mark = len(rec.states())
        assert _wait(lambda: len(rec.states()) >= mark + 2, 3.0), "после остановки тика записи не идут"
        frozen = core.read(_TLM, 32)
        time.sleep(0.1)
        assert core.read(_TLM, 32) == frozen, "предпосылка: тик не встал, tlm меняется"
        assert rec.states()[-1]["regs"]["tlm"] == frozen

        paths = [p for _m, p, _v in rec.snapshot()]
        assert paths, "хост вообще ничего не писал в state_proxy"
        assert all(p.startswith("sim.") for p in paths), f"путь не из sim.*: {sorted(set(paths))}"
        assert not [p for p in paths if p.startswith("devices.")]
    finally:
        plugin.shutdown(ctx)
        workers.stop_all()


# --------------------------------------------------------------------------- #
# 2. Ключ частоты                                                             #
# --------------------------------------------------------------------------- #


def _publish_100(*, protocol: str = "v2", **extra: Any) -> tuple[_RecordingStateProxy, str, int]:
    """Сервер поднят (без воркера паблишера), фейк-часы 0.05 с, 100 вызовов ``_publish_once``."""
    rec = _RecordingStateProxy()
    plugin, ctx, services, workers = _build_robot_host(rec, protocol=protocol, **extra)
    try:
        plugin._start_server(ctx)
        assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
        now = [0.0]
        plugin._clock = lambda: now[0]
        for i in range(100):
            now[0] = i * 0.05
            plugin._publish_once()
        return rec, plugin._state, _health_errors(services)  # состояние ДО shutdown
    finally:
        plugin.shutdown(ctx)
        workers.stop_all()


def test_rate_key() -> None:
    rec, _state, errors = _publish_100(robot_state_hz=0)
    assert rec.count(_ROBOT_STATE) == 0, "robot_state_hz=0 — публикация обязана быть выключена"
    assert rec.count("sim.belt.encoder") == 100, "контроль: энкодер пишется на каждый вызов"
    assert errors == 0

    rec, _state, errors = _publish_100()  # ключа нет вовсе
    assert rec.count(_ROBOT_STATE) == 0, "по умолчанию (ключа нет) публикация выключена"

    rec, _state, errors = _publish_100(robot_state_hz=4)
    assert rec.count(_ROBOT_STATE) == pytest.approx(20, abs=1), "hz=4 при шаге 0.05 с на 5 с -> 20 записей"
    assert rec.count("sim.belt.encoder") == 100
    assert errors == 0

    rec, _state, errors = _publish_100(robot_state_hz=20)
    assert rec.count(_ROBOT_STATE) == pytest.approx(100, abs=1), "hz=20 (предел при publish_ms=50) -> каждая публикация"
    assert errors == 0

    for bad in (-1, "abc", True, 21):
        rec, state, errors = _publish_100(robot_state_hz=bad)
        assert rec.count(_ROBOT_STATE) == 0, f"robot_state_hz={bad!r}: публикация обязана быть выключена"
        assert rec.count("sim.belt.encoder") == 100, f"robot_state_hz={bad!r}: энкодер обязан работать"
        assert state == "running", f"robot_state_hz={bad!r}: состояние {state!r}"
        assert errors == 1, f"robot_state_hz={bad!r}: ожидался ровно один отказ в health, их {errors}"

    rec, _state, _errors = _publish_100(protocol="v1", robot_state_hz=20)
    assert rec.count(_ROBOT_STATE) == 0, "v1 не публикует sim.robot.state"


# --------------------------------------------------------------------------- #
# 3. Источник читает так же, как ядро                                         #
# --------------------------------------------------------------------------- #


def test_source_read_matches_core() -> None:
    ls = _line_source()
    core = _core_at(POSE_A)
    snap = json.loads(json.dumps(_bare_plugin()._robot_state_snapshot(core)))
    src = ls.LineRobotState()
    src.update(snap)

    for base, count in ((_RES, 12), (_TLM, 32), (_PMIR, 128)):
        for address in range(base, base + count):
            assert src.read(address) == core.read(address, 1), f"слово 0x{address:04X}"
        assert src.read(base, count) == core.read(base, count), f"блок 0x{base:04X}"
    assert src.joints() == pytest.approx(list(core.joints()))
    ws_src, ws_core = src._workspace(), core._workspace()
    assert vars(ws_src) == vars(ws_core) if hasattr(ws_core, "__dict__") else ws_src == ws_core
    with pytest.raises(KeyError):
        src.read(0x2000)

    bad = dict(snap, model="OtherModel")
    with pytest.raises(ValueError) as info:
        ls.LineRobotState().update(bad)
    assert str(info.value) == "модель линии не поддерживается видом: нужна ScaraModel"
    assert "OtherModel" not in str(info.value)


# --------------------------------------------------------------------------- #
# 4. Три вида рисуют позу линии                                               #
# --------------------------------------------------------------------------- #


def test_views_draw_line_pose(qtbot) -> None:
    ls = _line_source()
    src = ls.LineRobotState()
    src.update(_snapshot(POSE_A))
    view, zscale, tape = SimView(src), ZScale(src), TimeTape(src)
    for w in (view, zscale, tape):
        qtbot.addWidget(w)
    assert view.status_text().startswith(_STATUS_A), view.status_text()
    assert zscale.z_value() == pytest.approx(-60.0, abs=0.05)
    assert tape.samples()[-1][1:] == pytest.approx((-60.0, 10.0), abs=0.05)

    src.update(_snapshot(POSE_B))
    view.refresh()
    zscale.refresh()
    tape.refresh()
    assert view.status_text().startswith(_STATUS_B), view.status_text()
    assert zscale.z_value() == pytest.approx(-90.0, abs=0.05)
    assert tape.samples()[-1][1:] == pytest.approx((-90.0, -20.0), abs=0.05)


# --------------------------------------------------------------------------- #
# 5. Поза по сокету (push | poll)                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_pose_over_socket(mode: str) -> None:
    ls = _line_source()
    snap_a, snap_b = _snapshot(POSE_A), _snapshot(POSE_B)
    host = _LineHost()
    second: SocketClient | None = None
    link = None
    try:
        host.put(snap_a)
        seen_by_second: list[tuple[str, Any]] = []
        if mode == "push":  # как backend_ctl лида: второй подписчик на то же дерево, соединение живёт весь тест
            second = SocketClient(HOST, host.port, sender="backend_ctl")
            second.connect()
            proxy = RemoteStateProxy(second, dispatch=lambda fn: fn())
            proxy.subscribe(
                _ROBOT_STATE + ".**",
                lambda deltas: seen_by_second.extend((d.path, d.new_value) for d in deltas),
                sync=False,
            )
        link = ls.LineLink(HOST, host.port, mode=mode, poll_ms=100)
        run_with_deadline(link.open, timeout=5.0, label="link.open")

        assert _pump(link, lambda: _src_pose(link.source) == pytest.approx(POSE_A, abs=0.05), 2.0), (
            f"поза А не дошла за 2.0 с: {_src_pose(link.source)}"
        )
        host.put(snap_b)
        assert _pump(link, lambda: _src_pose(link.source) == pytest.approx(POSE_B, abs=0.05), 2.0), (
            f"поза Б не дошла за 2.0 с: {_src_pose(link.source)}"
        )
        if mode == "poll":
            assert host.count("state.subscribe") == 0, "poll не должен подписываться"
            assert host.count("state.get_subtree") >= 1, "poll обязан читать state.get_subtree"
        else:

            def _second_sees_b() -> bool:
                return any(
                    (p == _ROBOT_STATE and isinstance(v, dict) and v.get("pose", {}).get("x_mm") == POSE_B[0])
                    or (p.endswith("pose.x_mm") and v == POSE_B[0])
                    for p, v in seen_by_second
                )

            assert _wait(_second_sees_b, 2.0), f"второй клиент не увидел позу Б: {seen_by_second[-3:]}"
        t0 = time.monotonic()
        run_with_deadline(link.close, timeout=2.0, label="link.close")
        assert time.monotonic() - t0 <= 2.0
        link = None
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        if second is not None:
            second.close()
        host.close()


# --------------------------------------------------------------------------- #
# 6-7. main без своего ядра; без линии — код 2                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_line_mode_constructs_no_core(tmp_path: Path, mode: str) -> None:
    snap_a = _snapshot(POSE_A)
    host = _LineHost()
    try:
        host.put(snap_a)
        proc = _run_main(
            tmp_path, ["--line", f"127.0.0.1:{host.port}", "--mode", mode, "--quit-after", "1.5"], timeout=60.0
        )
    finally:
        host.close()
    assert proc.returncode == 0, f"код {proc.returncode}; stderr: {proc.stderr[-600:]}"
    assert "CORES=0" in proc.stdout, f"в режиме --line создано ядро: {proc.stdout[-300:]}"
    lines = re.findall(
        r"^\[line-view\] .*x=350\.0 y=-150\.0 z=-60\.0 rz=10\.0 moving=0 link=ok$", proc.stdout, flags=re.MULTILINE
    )
    assert len(lines) >= 3, f"строк [line-view] с позой А: {len(lines)}; stdout: {proc.stdout[-500:]}"


def test_line_mode_without_endpoint_exits(tmp_path: Path) -> None:
    port = free_port()
    proc = _run_main(tmp_path, ["--line", f"127.0.0.1:{port}"], timeout=10.0)
    assert proc.returncode == 2, f"код {proc.returncode}; stderr: {proc.stderr[-400:]}"
    assert f"нет связи с линией 127.0.0.1:{port}" in proc.stderr, f"stderr: {proc.stderr[-400:]}"
    assert "CORES=0" in proc.stdout
    with socket.socket() as probe:
        probe.settimeout(1.0)
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "порт линии почему-то принимает соединения"


def test_demo_mode_constructs_one_core(tmp_path: Path) -> None:
    """Контроль (зелёный до кода): без --line демо строит ровно одно ядро."""
    proc = _run_main(tmp_path, ["--quit-after", "1"], timeout=60.0)
    assert proc.returncode == 0, f"код {proc.returncode}; stderr: {proc.stderr[-400:]}"
    assert "CORES=1" in proc.stdout, proc.stdout[-300:]


# --------------------------------------------------------------------------- #
# 8-10. Окно только для чтения, устаревшие данные, потеря и возврат связи     #
# --------------------------------------------------------------------------- #


def test_line_window_is_read_only(qtbot) -> None:
    ls = _line_source()
    host = _LineHost()
    link = None
    try:
        host.put(_snapshot(POSE_A))
        link = ls.LineLink(HOST, host.port, mode="push")
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        src = link.source
        window = build_window(src, writable=False)
        qtbot.addWidget(window)
        _attach_line()(window, link)
        window.show()
        qtbot.waitExposed(window)

        assert window.findChildren(QPushButton) == [], "в окне линии есть кнопки"
        assert not hasattr(src, "write"), "у источника линии есть write"
        view = window.findChild(SimView)
        assert view is not None
        res_before, tlm_before = src.read(_RES, 12), src.read(_TLM, 32)
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton)
        qtbot.wait(400)
        assert src.read(_RES, 12) == res_before and src.read(_TLM, 32) == tlm_before
        allowed = {"state.subscribe", "state.unsubscribe"}
        foreign = [c for c in host.commands() if c not in allowed and not c.startswith("state.get")]
        assert foreign == [], f"на хост ушли команды, кроме чтения: {foreign}"
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()


class _FakeLink:
    """Макет связи (REDS 9): данные подкладывает тест, ``tick`` ничего не делает."""

    lost = False
    last_error = None

    def __init__(self, source: Any) -> None:
        self.source = source

    def tick(self) -> None:
        pass


def test_stale_title(qtbot) -> None:
    ls = _line_source()
    attach_line = _attach_line()
    now = [100.0]
    clock = lambda: now[0]  # noqa: E731
    snap = _snapshot(POSE_A)

    src = ls.LineRobotState(clock=clock)
    src.update(snap)
    now[0] = 101.5  # данные 1.5 с назад
    window = build_window(src, writable=False)
    qtbot.addWidget(window)
    attach_line(window, _FakeLink(src), clock=clock)
    qtbot.waitUntil(lambda: "нет данных линии 1.5 с" in window.windowTitle(), timeout=3000)

    src.update(snap)  # свежий
    qtbot.waitUntil(lambda: "нет данных линии" not in window.windowTitle(), timeout=3000)

    # Хост без sim.robot.state: open() проходит, возраст неизвестен, заголовок честный.
    host = _LineHost()
    link = None
    try:
        link = ls.LineLink(HOST, host.port, mode="push")
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        assert link.source.age_s() is None
        empty = build_window(link.source, writable=False)
        qtbot.addWidget(empty)
        attach_line(empty, link)
        qtbot.waitUntil(lambda: "нет данных линии" in empty.windowTitle(), timeout=3000)
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_link_lost_and_resumed(qtbot, mode: str) -> None:
    ls = _line_source()
    host = _LineHost()
    host2 = None
    link = None
    try:
        host.put(_snapshot(POSE_A))
        port = host.port
        link = ls.LineLink(HOST, port, mode=mode, poll_ms=100, retry_ms=1000)
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        window = build_window(link.source, writable=False)
        qtbot.addWidget(window)
        _attach_line()(window, link)
        window.show()
        qtbot.waitExposed(window)
        view = window.findChild(SimView)
        assert view is not None
        qtbot.waitUntil(lambda: view.status_text().startswith(_STATUS_A), timeout=3000)
        assert "потеряна" not in window.windowTitle()

        host.close()  # дверь и роутер
        qtbot.waitUntil(lambda: "связь с линией потеряна" in window.windowTitle(), timeout=2000)
        assert view.status_text().startswith(_STATUS_A), "при потере связи вид обязан держать последнюю позу"
        assert window.isVisible()

        host2 = _LineHost(port=port)  # ТОТ ЖЕ порт, другое состояние
        host2.put(_snapshot(POSE_C))
        qtbot.waitUntil(
            lambda: view.status_text().startswith(_STATUS_C) and "потеряна" not in window.windowTitle(), timeout=3000
        )
        if mode == "push":
            assert host2.count("state.subscribe") >= 1, "после возврата связи push не подписался заново"
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()
        if host2 is not None:
            host2.close()
