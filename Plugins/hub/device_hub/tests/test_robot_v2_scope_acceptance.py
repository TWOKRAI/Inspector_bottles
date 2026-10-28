"""Слепая приёмка T5.3a (M1): потоки RobotDriverV2 живут в заданной области (tasks/T5.3a.md).

Purpose:
    Восемь приёмочных тестов «REDS 1–8» брифа. Стенд — ``E2eRig`` из ``Services.robot_comm.tests.e2e_rig_v2``
    (sim v2 на свободном порту); драйвер собирается через ``DeviceManager(store=None, publish_cb=rec,
    spawn=scope.spawn)`` либо через ``DeviceHubPlugin`` на ``make_ctx`` (``FakeWorkerManager`` воркеров не
    запускает, тики не идут). Проверяется наблюдаемый эффект: имена потоков в ``threading.enumerate()``,
    ``unclosed_roots()``, публикации ``devices.state.<id>.*``, строки событий и тики sim, время вызова.
    Спая на имя метода нигде нет.

Public API:
    Только тесты ``test_*``.

Stability: lite

Правила файла: ожидаемые значения — литералы брифа; блокирующий вызов идёт в daemon-потоке с дедлайном
(``bounded``); каждая область и каждый стенд закрываются в ``finally``. Корни и потоки сравниваются с тем, что
было ДО теста (``unclosed_roots`` допускает несколько корней с одним путём, чужой незакрытый корень не должен
краснить этот файл). Уточнения тестера к брифу помечены ``ДОПОЛНЕНИЕ ТЕСТЕРА`` — лид может их убрать.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope, unclosed_roots
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub import DeviceHubError
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, RecordingCore, bounded

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

_SCOPE_PATH = "t53a"
_SCOPE_BUDGET_S = 2.5  # тот же бюджет, что у корня плагина (О8)
_PLUGIN_ROOT = "device_hub"
_SCOPE_CONTEXT = "device_hub.scope"
_JOG = {"dir": 1, "spd": 20}
_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (58 записей PARAM_SET)
_HOLD_PERIOD_S = 0.05
_CMD_JOG = re.compile(r"\[v2\] CMD seq=(\d+) op=JOG_CONT")


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


class Rec:
    """``publish_cb``: копит ``(path, payload)`` под замком."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._items)

    def at(self, dev_id: str, leaf: str) -> list[Any]:
        path = f"devices.state.{dev_id}.{leaf}"
        return [payload for p, payload in self.items() if p == path]

    def program_states(self, dev_id: str) -> list[str]:
        return [p["state"] for p in self.at(dev_id, "program") if isinstance(p, dict) and "state" in p]


def _thread_names(prefix: str) -> list[str]:
    return sorted(t.name for t in threading.enumerate() if t.name.startswith(prefix))


def _new_threads(prefix: str, before: list[str]) -> list[str]:
    """Имена потоков с ``prefix``, которых не было в ``before`` (чужие живые потоки не краснят тест)."""
    return sorted((Counter(_thread_names(prefix)) - Counter(before)).elements())


def _roots(path: str) -> list[dict]:
    return [r for r in unclosed_roots() if r["path"] == path]


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _timed(fn: Callable[[], object], deadline_s: float) -> float:
    """``fn()`` в daemon-потоке (``bounded``); вернуть длительность вызова, с. Не уложился — ``TimeoutError``."""

    def body() -> float:
        started = time.monotonic()
        fn()
        return time.monotonic() - started

    return bounded(body, deadline_s)


def _confirm(fn: Callable[[], object], duration_s: float) -> None:
    """Звать ``fn()`` каждые 0.05 с в течение ``duration_s`` (подтверждения удержания GUI), под дедлайном."""
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        started = time.monotonic()
        bounded(fn, _CALL_DEADLINE_S)
        time.sleep(max(0.0, _HOLD_PERIOD_S - (time.monotonic() - started)))


@contextmanager
def _holding(fn: Callable[[], object]) -> Iterator[None]:
    """Подтверждения ``fn()`` каждые 0.05 с в daemon-потоке, пока идёт блок; исключения вызова глотаются.

    Подтверждения НЕ останавливаются сами: иначе окно Д3 (200 мс) остановило бы jog и без события области.
    """
    stop = threading.Event()

    def body() -> None:
        while not stop.is_set():
            try:
                fn()
            except BaseException:  # noqa: BLE001 — область/менеджер закрываются, ответ не важен
                pass
            stop.wait(_HOLD_PERIOD_S)

    thread = threading.Thread(target=body, name="holder-thread", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(2.0)


@contextmanager
def _scope() -> Iterator[Any]:
    """Область ``t53a`` с бюджетом корня плагина; закрывается в ``finally`` (повторное закрытие допустимо)."""
    scope = open_scope(_SCOPE_PATH, budget_s=_SCOPE_BUDGET_S)
    try:
        yield scope
    finally:
        try:
            bounded(scope.close, _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
            pass


def _transport(port: int) -> dict:
    return {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID}


def _upsert(mgr: DeviceManager, dev_id: str, port: int) -> None:
    mgr.upsert({"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(port)})


def _connect(mgr: DeviceManager, dev_id: str) -> Any:
    assert bounded(lambda: mgr.connect(dev_id), _CONNECT_DEADLINE_S) is True, f"connect({dev_id}) не вернул True"
    drv = mgr.get_driver(dev_id)
    drv.desired_connected = True
    return drv


def _disconnect_quietly(mgr: DeviceManager, ids: tuple[str, ...]) -> None:
    for dev_id in ids:
        try:
            bounded(lambda d=dev_id: mgr.disconnect(d), _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка
            pass


def _legs_program(name: str, legs: int) -> tuple[Program, dict[str, Point]]:
    """``legs`` ходов JOINT между двумя точками; одна нога ~0.27 с sim (8 ног ~2.2 с, 20 ног ~5.4 с)."""
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name=name, steps=steps), points


def _start(drv: Any, legs: int, name: str) -> dict:
    program, points = _legs_program(name, legs)
    return bounded(lambda: drv.start_program(program, points, None, name=name), _CALL_DEADLINE_S)


def _wait_running(rec: Rec, dev_id: str) -> None:
    _until(lambda: "running" in rec.program_states(dev_id), 10.0, f"{dev_id}.program перешла в running")


def _moving(core: RecordingCore) -> int:
    return core.ticks()[-1].moving


def _wait_stopped(core: RecordingCore, deadline_s: float = 1.0) -> None:
    _until(lambda: _moving(core) == 0, deadline_s, "sim: TLM_MOVING == 0")


def _jog_cmd_seqs(core: RecordingCore) -> list[int]:
    return [int(m.group(1)) for _, text in core.events() if (m := _CMD_JOG.search(text))]


def _scope_reports(ctx: Any) -> list[Any]:
    """Вызовы ``ctx.health.report_error(..., context="device_hub.scope")``."""
    return [c for c in ctx.health.report_error.call_args_list if c.kwargs.get("context") == _SCOPE_CONTEXT]


def _recipe(ports: dict[str, int]) -> list[dict]:
    return [
        {"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(port)}
        for dev_id, port in ports.items()
    ]


def _plugin_with_robots(tmp_path: Path, ports: dict[str, int]) -> tuple[DeviceHubPlugin, Any]:
    """Плагин на ``make_ctx``: реестр во ``tmp_path``, роботы в ``recipe_devices``, подключение — разбор очереди."""
    registry_file = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry_file), "recipe_devices": _recipe(ports)}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    for dev_id in ports:
        assert plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
    bounded(plugin._process_conn_queue, _CONNECT_DEADLINE_S)
    assert sorted(plugin._manager.connected_ids()) == sorted(ports), "роботы не подключились через очередь плагина"
    return plugin, ctx


def _shutdown_quietly(plugin: DeviceHubPlugin, ctx: Any) -> None:
    try:
        bounded(lambda: plugin.shutdown(ctx), 10.0)
    except Exception:  # noqa: BLE001 — уборка; повторный shutdown обязан быть безвредным
        pass


# --------------------------------------------------------------------------------------------------
# REDS 1
# --------------------------------------------------------------------------------------------------


def test_driver_threads_belong_to_given_scope() -> None:
    rec = Rec()
    rv2_before = _thread_names("rv2-")
    with E2eRig() as rig, _scope() as scope:
        mgr = DeviceManager(store=None, publish_cb=rec, spawn=scope.spawn)
        _upsert(mgr, "r1", rig.port)
        try:
            drv = _connect(mgr, "r1")

            # --- во время удержания jog ---
            assert bounded(lambda: mgr.call("r1", "jog_hold", dict(_JOG)), _CALL_DEADLINE_S)["status"] == "ok"
            _confirm(lambda: mgr.call("r1", "jog_hold", dict(_JOG)), 0.3)
            jog_names = _thread_names("t53a/")
            assert jog_names, "поток поводка не в области t53a: имён с префиксом 't53a/' нет"
            assert any(n.startswith("t53a/r1-lease-") for n in jog_names), jog_names
            assert _new_threads("rv2-", rv2_before) == [], "поток драйвера живёт вне заданной области"
            assert _moving(rig.core) == 1

            assert mgr.call("r1", "jog_release")["status"] == "ok"

            # --- во время программы (>= 1 с) ---
            assert _start(drv, 8, "p1")["status"] == "ok"
            _wait_running(rec, "r1")
            time.sleep(0.3)
            prog_names = _thread_names("t53a/")
            assert any(n.startswith("t53a/r1-prog-") for n in prog_names), prog_names
            assert _new_threads("rv2-", rv2_before) == [], "поток исполнителя живёт вне заданной области"
        finally:
            _disconnect_quietly(mgr, ("r1",))


# --------------------------------------------------------------------------------------------------
# REDS 2
# --------------------------------------------------------------------------------------------------


def test_scope_close_stops_jog_and_leaves_no_threads() -> None:
    rec = Rec()
    roots_before = len(_roots(_SCOPE_PATH))
    names_before = _thread_names("t53a/")
    with E2eRig() as rig, _scope() as scope:
        mgr = DeviceManager(store=None, publish_cb=rec, spawn=scope.spawn)
        _upsert(mgr, "r1", rig.port)
        try:
            _connect(mgr, "r1")
            core = rig.core

            def confirm() -> object:
                return mgr.call("r1", "jog_hold", dict(_JOG))

            assert bounded(confirm, _CALL_DEADLINE_S)["status"] == "ok"
            with _holding(confirm):
                time.sleep(0.5)
                assert _moving(core) == 1, "после 0.5 с удержания робот не движется: поводок не писался"
                seqs = _jog_cmd_seqs(core)
                assert len(seqs) == 1, seqs
                seq = seqs[0]
                mark = len(core.ticks())
                # подтверждения идут до возврата close(): стоп даёт событие области, не окно Д3
                report = bounded(scope.close, _CALL_DEADLINE_S)

            assert list(report.survivors) == []
            assert report.elapsed_s < 1.0
            _until(
                lambda: any(tk.moving == 0 for tk in core.ticks()[mark:]),
                1.0,
                "первый тик sim после закрытия области: moving == 0",
            )
            assert any(f"[v2] ERR seq={seq} errno=13" in text for _, text in core.events()), (
                "стоп не оборвал JOG_CONT: строки '[v2] ERR seq=<seq> errno=13' нет"
            )
            assert _new_threads("t53a/", names_before) == []
            assert len(_roots(_SCOPE_PATH)) == roots_before
        finally:
            _disconnect_quietly(mgr, ("r1",))


# --------------------------------------------------------------------------------------------------
# REDS 3
# --------------------------------------------------------------------------------------------------


def test_manager_shutdown_stops_program_and_joins() -> None:
    rec = Rec()
    roots_before = len(_roots(_SCOPE_PATH))
    names_before = _thread_names("t53a/")
    with E2eRig() as rig, _scope() as scope:
        mgr = DeviceManager(store=None, publish_cb=rec, spawn=scope.spawn)
        _upsert(mgr, "r1", rig.port)
        try:
            drv = _connect(mgr, "r1")
            assert _start(drv, 20, "long")["status"] == "ok"  # ~5.4 с sim, остаётся >= 3 с
            _wait_running(rec, "r1")
            time.sleep(0.5)
            assert rec.program_states("r1")[-1] == "running"

            elapsed = _timed(mgr.shutdown, 10.0)

            assert elapsed <= 2.0, f"manager.shutdown() занял {elapsed:.2f} с"
            assert rec.program_states("r1")[-1] == "aborted"
            assert _new_threads("t53a/", names_before) == []
            bounded(scope.close, _CALL_DEADLINE_S)
            assert len(_roots(_SCOPE_PATH)) == roots_before
        finally:
            _disconnect_quietly(mgr, ("r1",))


# --------------------------------------------------------------------------------------------------
# REDS 4
# --------------------------------------------------------------------------------------------------


def test_plugin_shutdown_leaves_no_driver_threads(tmp_path: Path) -> None:
    roots_before = len(_roots(_PLUGIN_ROOT))
    names_before = _thread_names(f"{_PLUGIN_ROOT}/")
    plugin = ctx = None
    try:
        with E2eRig() as rig:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig.port})
            core = rig.core

            def confirm() -> object:
                return plugin._manager.call("r1", "jog_hold", dict(_JOG))

            assert bounded(confirm, _CALL_DEADLINE_S)["status"] == "ok"
            with _holding(confirm):
                time.sleep(0.5)
                assert _moving(core) == 1, "после 0.5 с удержания робот не движется"
                # ДОПОЛНЕНИЕ ТЕСТЕРА: «потоков нет» после shutdown пусто и до реализации (потоки носят имя
                # 'rv2-lease-r1'), поэтому сначала положительный контроль — поток поводка в корне плагина.
                assert any(n.startswith(f"{_PLUGIN_ROOT}/r1-lease-") for n in _thread_names(f"{_PLUGIN_ROOT}/"))
                assert len(_roots(_PLUGIN_ROOT)) == roots_before + 1, "плагин не открыл корень 'device_hub'"
                _timed(lambda: plugin.shutdown(ctx), 10.0)

            assert _new_threads(f"{_PLUGIN_ROOT}/", names_before) == []
            _wait_stopped(core)
            assert len(_roots(_PLUGIN_ROOT)) == roots_before
    finally:
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# REDS 5
# --------------------------------------------------------------------------------------------------


def test_spawnless_driver_keeps_working() -> None:
    """REDS 5 (T5.3 круг 2, решение владельца): робот ``delta_v2`` без ``spawn`` не создаётся фабрикой
    (``RuntimeError``); драйвер, собранный без ``spawn``, на jog и запуск программы отвечает ``RuntimeError`` /
    отказом без записи ``JOG_CONT`` и без нового корня."""
    rec = Rec()
    with E2eRig() as rig:
        mgr = DeviceManager(store=None, publish_cb=rec)
        _upsert(mgr, "r1", rig.port)
        with pytest.raises(RuntimeError):
            mgr.connect("r1")

        roots_before = len(unclosed_roots())
        entry = DeviceEntry(
            id="r1", name="r1", kind="robot", protocol="delta_v2", transport=_transport(rig.port), params={}
        )
        drv = RobotDriverV2(entry, None, publish=rec)
        try:
            assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
            core = rig.core
            reply = bounded(lambda: drv.call("jog_hold", dict(_JOG)), _CALL_DEADLINE_S)
            assert reply == {"status": "error", "message": "RobotDriverV2 без spawn не запускает потоки"}
            assert _jog_cmd_seqs(core) == []
            program, points = _legs_program("p_nospawn", 2)
            with pytest.raises(RuntimeError, match="без spawn"):
                drv.start_program(program, points, name="p_nospawn")
            assert len(unclosed_roots()) == roots_before
        finally:
            try:
                bounded(drv.disconnect, _CALL_DEADLINE_S)
            except Exception:  # noqa: BLE001 — уборка не должна подменять исключение теста
                pass


# --------------------------------------------------------------------------------------------------
# REDS 6
# --------------------------------------------------------------------------------------------------


def test_two_robots_share_scope() -> None:
    rec = Rec()
    with E2eRig() as rig_a, E2eRig() as rig_b, _scope() as scope:
        mgr = DeviceManager(store=None, publish_cb=rec, spawn=scope.spawn)
        _upsert(mgr, "r1", rig_a.port)
        _upsert(mgr, "r2", rig_b.port)
        try:
            drv_a = _connect(mgr, "r1")
            drv_b = _connect(mgr, "r2")
            res_a = _start(drv_a, 8, "p_a")  # ~2.2 с sim каждая, идут одновременно
            res_b = _start(drv_b, 8, "p_b")
            assert res_a["status"] == "ok"
            assert res_b["status"] == "ok"
            _wait_running(rec, "r1")
            _wait_running(rec, "r2")
            names = _thread_names("t53a/")
            assert any(n.startswith("t53a/r1-prog-") for n in names), names
            assert any(n.startswith("t53a/r2-prog-") for n in names), names
        finally:
            _disconnect_quietly(mgr, ("r1", "r2"))


# --------------------------------------------------------------------------------------------------
# REDS 7
# --------------------------------------------------------------------------------------------------


def test_configure_failure_closes_scope(tmp_path: Path) -> None:
    roots_before = len(_roots(_PLUGIN_ROOT))
    registry_file = tmp_path / "devices.yaml"
    registry_file.write_text("- 1\n", encoding="utf-8")  # не словарь -> DeviceHubError
    ctx = make_ctx({}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()

    with pytest.raises(DeviceHubError):
        bounded(lambda: plugin.configure(ctx), 10.0)
    assert len(_roots(_PLUGIN_ROOT)) == roots_before, "configure() бросил, а корень 'device_hub' остался незакрытым"

    reports_before = len(ctx.health.report_error.call_args_list)
    bounded(lambda: plugin.shutdown(ctx), 10.0)  # фреймворк зовёт shutdown() и после упавшего configure (Ф10)
    assert len(ctx.health.report_error.call_args_list) == reports_before, (
        "shutdown после упавшего configure писал в health"
    )
    assert len(_roots(_PLUGIN_ROOT)) == roots_before


# --------------------------------------------------------------------------------------------------
# REDS 8
# --------------------------------------------------------------------------------------------------


def test_plugin_shutdown_two_robots_within_window(tmp_path: Path) -> None:
    roots_before = len(_roots(_PLUGIN_ROOT))
    names_before = _thread_names(f"{_PLUGIN_ROOT}/")
    plugin = ctx = None
    try:
        with E2eRig() as rig_a, E2eRig() as rig_b:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig_a.port, "r2": rig_b.port})
            drv_a = plugin._manager.get_driver("r1")

            def confirm() -> object:
                return plugin._manager.call("r2", "jog_hold", dict(_JOG))

            assert _start(drv_a, 20, "long")["status"] == "ok"  # ~5.4 с sim, остаётся >= 3 с
            assert bounded(confirm, _CALL_DEADLINE_S)["status"] == "ok"
            with _holding(confirm):
                time.sleep(0.5)
                assert _moving(rig_b.core) == 1, "r2: после 0.5 с удержания робот не движется"
                assert drv_a.is_connected
                # ДОПОЛНЕНИЕ ТЕСТЕРА: положительный контроль (см. REDS 4) — оба потока живут в корне плагина.
                names = _thread_names(f"{_PLUGIN_ROOT}/")
                assert any(n.startswith(f"{_PLUGIN_ROOT}/r1-prog-") for n in names), names
                assert any(n.startswith(f"{_PLUGIN_ROOT}/r2-lease-") for n in names), names
                elapsed = _timed(lambda: plugin.shutdown(ctx), 4.0)

            assert elapsed <= 3.0, f"plugin.shutdown() с двумя роботами в движении занял {elapsed:.2f} с (окно 3.0 с)"
            assert _new_threads(f"{_PLUGIN_ROOT}/", names_before) == []
            _wait_stopped(rig_a.core)
            _wait_stopped(rig_b.core)
            assert _scope_reports(ctx) == [], (
                "в отчёте закрытия корня были выжившие: report_error(context='device_hub.scope')"
            )
            assert len(_roots(_PLUGIN_ROOT)) == roots_before
    finally:
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)
