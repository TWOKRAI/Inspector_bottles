"""Слепая приёмка Task 2.2a (run-state): ``DeviceHubPlugin.readiness`` и ``pause`` / ``resume`` (REDS 1-8).

Purpose:
    Контракт хуков ``readiness(ctx)`` / ``pause(ctx)`` / ``resume(ctx)`` плагина ``device_hub`` по DESIGN «2.2a»
    (``plans/2026-10-27_system-run-state/tasks/2.2.md``, П.1-П.6'). Написан до реализации, по DESIGN и REDS, без
    чтения кода плагина. Покрыты REDS 1-8; REDS 9-12 пишет автор.

    * REDS 1-3: ``readiness`` по снимку соединений (``plugin._publish_state(path, {"conn": ...})``), без замков.
    * REDS 4: настоящая проводка ``start`` + супервизор + tick-воркер на ``FakeDriver``.
    * REDS 5-7: ``pause`` останавливает, не паркует; ``resume`` ничего не запускает; сбой одного устройства.
    * REDS 8: симулятор v2 (``E2eRig`` над ``RobotSimCore``) — ФАКТ: после ``pause`` драйвер принимает новое
      движение, а поставленные в очередь задания продолжают уходить (стоп очередь не удерживает).

    Ожидаемые значения — литералы DESIGN (тексты причин, ``SOFT``, ``mode == 1``). Каждый вызов, который может
    повиснуть, идёт в daemon-потоке с join-дедлайном (``bounded``); ожидание состояния — опрос с дедлайном.

Public API:
    Только тесты ``test_*``.

Stability: lite

Приватные имена, на которые опирается файл (названы в DESIGN как контракт): ``_publish_state``, ``_workers_lock``,
``_manager`` (только подмена в тесте 3), ``_conn_snapshot`` и ``_desired_connected`` (только подмена в тесте
«сбой чтения»), ``_shutting_down``, ``_process_conn_queue``, ``_ensure_device_workers``.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_robot_v2_commands_acceptance import _v2_entry
from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import Calls, FakeDriver
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig

pytestmark = pytest.mark.timeout(120)

_JOIN_S = 2.0  # любой вызов хука readiness возвращается не позже
_CALL_S = 15.0  # потолок для pause и прочих вызовов, которые могут повиснуть
_POLL_S = 5.0  # потолок опроса состояния проводки
_CONNECT_S = 60.0  # connect v2 включает sync_params (58 записей PARAM_SET)

_NOT_CONNECTED = "{} не подключено"
_LINK_ERROR = "{}: ошибка связи"
_UNAVAILABLE = "device_hub: состояние устройств недоступно"
_PAUSE_FAILED = "pause: сбой останова устройств"


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


def bounded(fn: Callable[[], Any], join_s: float = _CALL_S) -> Any:
    """Вызов в daemon-потоке с join-дедлайном; ошибка потока поднимается в тесте, зависание — ``AssertionError``."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="readiness-pause-bounded")
    thread.start()
    thread.join(join_s)
    assert not thread.is_alive(), f"вызов завис дольше {join_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def until(pred: Callable[[], Any], deadline_s: float, what: str) -> None:
    """Опрос с дедлайном (без ``sleep`` на фиксированный срок)."""
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.01)


def _conn_path(dev_id: str) -> str:
    return f"devices.state.{dev_id}.conn"


def _failure(reason: str) -> dict:
    return {"severity": "failure", "reason": reason}


def _recipe_entry(dev_id: str, kind: str = "robot", protocol: str = "delta_universal3") -> dict:
    return {
        "id": dev_id,
        "name": dev_id,
        "kind": kind,
        "protocol": protocol,
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
    }


def make_hub(tmp_path: Path, recipe_ids: tuple[str, ...] = ()) -> tuple[DeviceHubPlugin, Any]:
    """Настоящий плагин на ``make_ctx`` после ``configure`` + ``start``; рецепт — ``recipe_ids`` (порядок сохранён).

    Очередь подключений не разбирается и воркеры не идут: подключения нет, снимок наполняет тест.
    """
    registry = tmp_path / "devices.yaml"
    recipe = [_recipe_entry(dev_id) for dev_id in recipe_ids]
    ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


def publish(plugin: DeviceHubPlugin, dev_id: str, conn: str, **extra: Any) -> None:
    plugin._publish_state(_conn_path(dev_id), {"conn": conn, **extra})


def readiness(plugin: DeviceHubPlugin, ctx: Any) -> list[dict]:
    """``readiness`` под дедлайном."""
    return bounded(lambda: plugin.readiness(ctx), _JOIN_S)


# --------------------------------------------------------------------------------------------------
# RED 1 — причины по состоянию соединения
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("conn", "reason"),
    [
        pytest.param("disconnected", "robot_main не подключено", id="disconnected"),
        pytest.param("connecting", "robot_main не подключено", id="connecting"),
        pytest.param("disconnecting", "robot_main не подключено", id="disconnecting"),
        pytest.param("error", "robot_main: ошибка связи", id="error"),
        pytest.param("failed", "robot_main: ошибка связи", id="failed"),
    ],
)
def test_red1_reason_by_connection_state(tmp_path: Path, conn: str, reason: str) -> None:
    """RED 1: желаемое устройство рецепта не в ``connected`` -> один ``failure`` с литералом причины."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", conn)

    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": reason}]


def test_red1_snapshot_entry_with_ts_key_is_read(tmp_path: Path) -> None:
    """RED 1 (DESIGN: значение — ``{"conn": str[, "ts": int]}``): запись с ``ts`` читается так же, как без него."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "disconnected", ts=7)

    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main не подключено"}]


def test_red1_latest_publication_wins(tmp_path: Path) -> None:
    """RED 1: снимок хранит последнюю публикацию: ``error`` -> ``connected`` даёт ``[]``, обратно — причину."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "error")
    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main: ошибка связи"}]

    publish(plugin, "robot_main", "connected")
    assert readiness(plugin, ctx) == []

    publish(plugin, "robot_main", "failed")
    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main: ошибка связи"}]


def test_red1_each_device_gets_its_own_reason_in_recipe_order(tmp_path: Path) -> None:
    """RED 1: у каждого устройства своя причина; порядок — как в рецепте (не алфавитный)."""
    plugin, ctx = make_hub(tmp_path, ("vfd_belt", "robot_main", "cam_1"))
    publish(plugin, "vfd_belt", "error")
    publish(plugin, "robot_main", "disconnected")
    publish(plugin, "cam_1", "connected")

    assert readiness(plugin, ctx) == [
        {"severity": "failure", "reason": "vfd_belt: ошибка связи"},
        {"severity": "failure", "reason": "robot_main не подключено"},
    ]


# --------------------------------------------------------------------------------------------------
# RED 2 — «готово», желание оператора, state-plane, порядок
# --------------------------------------------------------------------------------------------------


def test_red2_all_desired_connected_is_empty(tmp_path: Path) -> None:
    """RED 2: все желаемые устройства ``connected`` -> ``[]``."""
    plugin, ctx = make_hub(tmp_path, ("robot_main", "vfd_belt"))
    publish(plugin, "robot_main", "connected")
    publish(plugin, "vfd_belt", "connected")

    assert readiness(plugin, ctx) == []


def test_red2_only_the_not_connected_device_is_listed(tmp_path: Path) -> None:
    """RED 2: подключённое устройство в причины не попадает, неподключённое сосед — попадает."""
    plugin, ctx = make_hub(tmp_path, ("robot_main", "vfd_belt"))
    publish(plugin, "robot_main", "connected")
    publish(plugin, "vfd_belt", "disconnected")

    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "vfd_belt не подключено"}]


def test_red2_operator_disconnected_device_is_not_listed(tmp_path: Path) -> None:
    """RED 2: устройство, отключённое оператором (``cmd_device_disconnect``), при ``disconnected`` не перечислено."""
    plugin, ctx = make_hub(tmp_path, ("robot_main", "vfd_belt"))
    publish(plugin, "robot_main", "connected")
    publish(plugin, "vfd_belt", "connected")

    res = plugin.cmd_device_disconnect({"device_id": "vfd_belt"})
    assert res["status"] == "ok", res
    publish(plugin, "vfd_belt", "disconnected")
    publish(plugin, "robot_main", "disconnected")  # контроль: желаемое устройство при том же состоянии перечислено

    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main не подключено"}]


def test_red2_snapshot_does_not_depend_on_state_plane(tmp_path: Path) -> None:
    """RED 2: при ``ctx.state_proxy = None`` публикация ``connected`` всё равно попадает в снимок."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    ctx.state_proxy = None

    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main не подключено"}]  # контроль
    publish(plugin, "robot_main", "connected")

    assert readiness(plugin, ctx) == []


def test_red2_no_publication_lists_every_desired_device_in_recipe_order(tmp_path: Path) -> None:
    """RED 2: ни одной публикации -> перечислены все желаемые, порядок рецепта (не алфавит, не порядок ``set``)."""
    ids = ("vfd_belt", "robot_main", "cam_9", "plc_2", "cam_1", "robot_aux")
    plugin, ctx = make_hub(tmp_path, ids)

    assert readiness(plugin, ctx) == [
        {"severity": "failure", "reason": "vfd_belt не подключено"},
        {"severity": "failure", "reason": "robot_main не подключено"},
        {"severity": "failure", "reason": "cam_9 не подключено"},
        {"severity": "failure", "reason": "plc_2 не подключено"},
        {"severity": "failure", "reason": "cam_1 не подключено"},
        {"severity": "failure", "reason": "robot_aux не подключено"},
    ]


def test_red2_empty_recipe_is_ready(tmp_path: Path) -> None:
    """RED 2 (DESIGN П.1): рецепт без устройств -> ``readiness == []``."""
    plugin, ctx = make_hub(tmp_path, ())

    assert readiness(plugin, ctx) == []


def test_red2_publications_that_are_not_a_conn_value_leave_snapshot_alone(tmp_path: Path) -> None:
    """RED 2 (DESIGN П.1): снимок меняют только ``….conn`` с dict, где есть строка ``conn``; прочее — не трогает."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "connected")

    plugin._publish_state("devices.state.robot_main.last_error", "boom")
    plugin._publish_state("devices.state.robot_main.status", {"conn": "error"})
    plugin._publish_state(_conn_path("robot_main"), {"ts": 5})
    plugin._publish_state("devices.state.robot_main", {})

    assert readiness(plugin, ctx) == []


# --------------------------------------------------------------------------------------------------
# RED 3 — readiness не блокируется и не бросает
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lock_name", ["plugin_workers_lock", "manager_registry_lock"])
def test_red3_readiness_returns_while_another_thread_holds_a_lock(tmp_path: Path, lock_name: str) -> None:
    """RED 3: пока другой поток держит ``_workers_lock`` (или замок реестра менеджера), ``readiness`` возвращается."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "error")
    lock = plugin._workers_lock if lock_name == "plugin_workers_lock" else plugin._manager._registry_lock

    holder_ready, release = threading.Event(), threading.Event()

    def hold() -> None:
        with lock:
            holder_ready.set()
            release.wait(10.0)

    holder = threading.Thread(target=hold, daemon=True, name="red3-lock-holder")
    holder.start()
    try:
        assert holder_ready.wait(2.0), "обвязка: замок не взят"
        result = readiness(plugin, ctx)  # bounded: зависание -> AssertionError «вызов завис»
        assert result == [{"severity": "failure", "reason": "robot_main: ошибка связи"}]
    finally:
        release.set()
        holder.join(3.0)
    assert not holder.is_alive()


class _Boom:
    """Объект, бросающий при любом доступе (атрибут, индекс, итерация, ``len``, ``in``)."""

    def __getattribute__(self, name: str) -> Any:
        raise RuntimeError(f"доступ запрещён: {name}")

    def __getitem__(self, key: Any) -> Any:
        raise RuntimeError("доступ запрещён: __getitem__")

    def __iter__(self) -> Any:
        raise RuntimeError("доступ запрещён: __iter__")

    def __len__(self) -> int:
        raise RuntimeError("доступ запрещён: __len__")

    def __contains__(self, item: Any) -> bool:
        raise RuntimeError("доступ запрещён: __contains__")


def test_red3_readiness_does_not_raise_when_manager_raises_on_any_access(tmp_path: Path) -> None:
    """RED 3: подмена ``_manager`` на объект, бросающий при любом доступе, — ``readiness`` не бросает."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "disconnected")
    real_manager = plugin._manager
    plugin._manager = _Boom()
    try:
        result = readiness(plugin, ctx)
    finally:
        plugin._manager = real_manager  # shutdown плагина в уборке фикстуры идёт через настоящий менеджер

    assert isinstance(result, list)
    assert all(isinstance(item, dict) for item in result)


def test_red3_readiness_before_configure_does_not_raise(tmp_path: Path) -> None:
    """RED 3: ``readiness`` на только что созданном плагине (до ``configure``) не бросает; готово — ``[]``."""
    plugin = DeviceHubPlugin()
    ctx = make_ctx({"registry_path": str(tmp_path / "devices.yaml")})

    assert readiness(plugin, ctx) == []


@pytest.mark.parametrize("broken", ["_conn_snapshot", "_desired_connected"])
def test_red3_unreadable_state_gives_the_literal_fallback(tmp_path: Path, broken: str) -> None:
    """RED 3 (DESIGN П.2): сбой чтения состояния -> ровно один ``failure`` «состояние устройств недоступно»."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    publish(plugin, "robot_main", "connected")
    original = getattr(plugin, broken, {})  # умолчание — чтобы красный был по assertion, а не по AttributeError
    setattr(plugin, broken, _Boom())
    try:
        result = readiness(plugin, ctx)
    finally:
        setattr(plugin, broken, original)

    assert result == [{"severity": "failure", "reason": "device_hub: состояние устройств недоступно"}]


# --------------------------------------------------------------------------------------------------
# RED 4 — реальная проводка: start + супервизор + tick-воркер
# --------------------------------------------------------------------------------------------------


def test_red4_wiring_supervisor_and_tick_worker_feed_the_snapshot(tmp_path: Path) -> None:
    """RED 4: ``start`` -> «не подключено»; супервизор подключил -> ``[]``; обрыв (``up = False``) -> «не подключено».

    Супервизор и tick-воркер ходят вручную (``FakeWorkerManager`` воркеры не запускает): ``_process_conn_queue``,
    ``_ensure_device_workers`` и ``fn(stop_evt, pause_evt)`` в daemon-потоке.
    """
    registry = tmp_path / "devices.yaml"
    recipe = [_recipe_entry("robot_main")]
    ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    drivers: dict[str, FakeDriver] = {}

    def build(entry: Any, proto: Any) -> FakeDriver:
        drivers[entry.id] = FakeDriver(entry, proto)
        return drivers[entry.id]

    plugin._manager.register_driver_factory("robot", build)
    plugin.start(ctx)

    # до подключения: желание есть (рецепт), записи «connected» нет
    assert readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main не подключено"}]

    bounded(plugin._process_conn_queue, _CONNECT_S)
    assert drivers["robot_main"].is_connected, "обвязка: супервизор не подключил драйвер"
    until(lambda: readiness(plugin, ctx) == [], _POLL_S, "после подключения readiness == []")

    plugin._ensure_device_workers()
    worker = ctx.worker_manager.workers["dev_robot_main"]["fn"]
    stop_evt, pause_evt = threading.Event(), threading.Event()
    thread = threading.Thread(target=worker, args=(stop_evt, pause_evt), daemon=True, name="red4-tick-worker")
    thread.start()
    try:
        # воркер крутится на подключённом драйвере, готовность не теряется
        time.sleep(0.2)
        assert readiness(plugin, ctx) == []

        drivers["robot_main"].up = False  # обрыв; желание «подключать» остаётся True
        until(
            lambda: readiness(plugin, ctx) == [{"severity": "failure", "reason": "robot_main не подключено"}],
            _POLL_S,
            "после обрыва и хода воркера readiness == [«robot_main не подключено»]",
        )
    finally:
        stop_evt.set()
        thread.join(3.0)
    assert not thread.is_alive()


# --------------------------------------------------------------------------------------------------
# Стенд pause: плагин + FakeDriver всех видов (REDS 5-7)
# --------------------------------------------------------------------------------------------------


class RaisingDriver(FakeDriver):
    """``call`` пишет вызов и бросает."""

    def call(self, op: str, args: dict) -> dict:
        self.calls.add(self.entry.id, op, args)
        raise RuntimeError("драйвер упал")


class ErrorReplyDriver(FakeDriver):
    """``call`` пишет вызов и отвечает ``{"status": "error"}``."""

    def call(self, op: str, args: dict) -> dict:
        self.calls.add(self.entry.id, op, args)
        return {"status": "error", "message": "отказ"}


class PauseHub:
    """Плагин без рецепта + журнал ``Calls`` всех драйверов; устройства добавляются и подключаются публично."""

    def __init__(self, tmp_path: Path) -> None:
        registry = tmp_path / "devices.yaml"
        self.ctx = make_ctx({"registry_path": str(registry), "recipe_devices": []}, tmp_registry=registry)
        self.plugin = DeviceHubPlugin()
        self.plugin.configure(self.ctx)
        self.calls = Calls()
        self.driver_cls: dict[str, type[FakeDriver]] = {}
        self.drivers: dict[str, FakeDriver] = {}
        for kind in ("robot", "vfd"):
            self.plugin._manager.register_driver_factory(kind, self._build)
        self.plugin.start(self.ctx)

    def _build(self, entry: Any, proto: Any) -> FakeDriver:
        driver = self.driver_cls.get(entry.id, FakeDriver)(entry, proto, calls=self.calls)
        self.drivers[entry.id] = driver
        return driver

    def add(
        self,
        dev_id: str,
        kind: str,
        protocol: str,
        *,
        connect: bool = True,
        driver_cls: type[FakeDriver] = FakeDriver,
    ) -> None:
        self.driver_cls[dev_id] = driver_cls
        entry = _recipe_entry(dev_id, kind, protocol)
        res = self.plugin.cmd_device_upsert(entry)
        assert res["status"] == "ok", res
        if connect:
            assert bounded(lambda: self.plugin._manager.connect(dev_id), _CALL_S) is True, dev_id
            assert self.drivers[dev_id].is_connected, f"обвязка: {dev_id} не подключён"

    def pause(self) -> None:
        bounded(lambda: self.plugin.pause(self.ctx), _CALL_S)

    def resume(self) -> None:
        bounded(lambda: self.plugin.resume(self.ctx), _CALL_S)

    def ops(self) -> list[tuple[str, str, dict]]:
        with self.calls.guard:
            return list(self.calls.items)


@pytest.fixture
def pause_hub(tmp_path: Path) -> PauseHub:
    return PauseHub(tmp_path)


# --------------------------------------------------------------------------------------------------
# RED 5 — delta_v2: stop SOFT, не park, _shutting_down не ставится
# --------------------------------------------------------------------------------------------------


def test_red5_pause_v2_robot_gets_stop_soft_and_no_park(pause_hub: PauseHub) -> None:
    """RED 5: драйвер ``delta_v2`` получил ``stop`` с ``level == "SOFT"`` и ни одного ``park``."""
    pause_hub.add("r2", "robot", "delta_v2")

    pause_hub.pause()

    ops = pause_hub.ops()
    assert ops == [("r2", "stop", {"level": "SOFT"})], ops
    assert all(op != "park" for _dev, op, _args in ops)


def test_red5_pause_does_not_latch_shutdown(pause_hub: PauseHub) -> None:
    """RED 5: после ``pause`` ``_shutting_down`` остаётся ``False`` (пауза — не выключение процесса)."""
    pause_hub.add("r2", "robot", "delta_v2")

    pause_hub.pause()

    assert pause_hub.ops() == [("r2", "stop", {"level": "SOFT"})]  # ``pause`` действительно отработал
    assert pause_hub.plugin._shutting_down is False


# --------------------------------------------------------------------------------------------------
# RED 6 — vfd, робот v1, resume
# --------------------------------------------------------------------------------------------------


def test_red6_pause_vfd_gets_stop(pause_hub: PauseHub) -> None:
    """RED 6: подключённый ``vfd`` получает ``stop`` с пустыми аргументами."""
    pause_hub.add("v1", "vfd", "gd20_bridge")

    pause_hub.pause()

    assert pause_hub.ops() == [("v1", "stop", {})]


def test_red6_pause_v1_robot_gets_abort_mode_1(pause_hub: PauseHub) -> None:
    """RED 6: подключённый робот v1 получает ``abort`` с ``mode == 1`` (и ничего больше)."""
    pause_hub.add("r1", "robot", "delta_universal3")

    pause_hub.pause()

    ops = pause_hub.ops()
    assert ops == [("r1", "abort", {"mode": 1})], ops
    assert isinstance(ops[0][2]["mode"], int)


def test_red6_pause_covers_every_connected_robot_and_vfd(pause_hub: PauseHub) -> None:
    """RED 6: на трёх устройствах разных видов каждое остановлено своей операцией, по одному разу."""
    pause_hub.add("r2", "robot", "delta_v2")
    pause_hub.add("r1", "robot", "delta_universal3")
    pause_hub.add("v1", "vfd", "gd20_bridge")

    pause_hub.pause()

    assert sorted(pause_hub.ops(), key=lambda item: item[0]) == [
        ("r1", "abort", {"mode": 1}),
        ("r2", "stop", {"level": "SOFT"}),
        ("v1", "stop", {}),
    ]


def test_red6_resume_after_pause_sends_no_commands(pause_hub: PauseHub) -> None:
    """RED 6: ``resume`` после ``pause`` — никаких команд устройствам (лента и движение не запускаются)."""
    pause_hub.add("r2", "robot", "delta_v2")
    pause_hub.add("v1", "vfd", "gd20_bridge")
    pause_hub.pause()
    after_pause = pause_hub.ops()
    assert sorted(after_pause) == [("r2", "stop", {"level": "SOFT"}), ("v1", "stop", {})], after_pause

    pause_hub.resume()

    assert pause_hub.ops() == after_pause


# --------------------------------------------------------------------------------------------------
# RED 7 — сбой одного устройства, неподключённые
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failing_cls", [ErrorReplyDriver, RaisingDriver], ids=["error_reply", "raises"])
@pytest.mark.parametrize("failing", ["r_a", "r_b", "v_c"])
def test_red7_failure_of_one_device_stops_the_rest_then_raises(
    pause_hub: PauseHub, failing: str, failing_cls: type[FakeDriver]
) -> None:
    """RED 7: у одного из трёх ``call`` отвечает ``{"status": "error"}`` или бросает — остальные остановлены, потом
    ``pause`` бросает ``RuntimeError`` с литералом без значений."""
    pause_hub.add("r_a", "robot", "delta_v2", driver_cls=failing_cls if failing == "r_a" else FakeDriver)
    pause_hub.add("r_b", "robot", "delta_universal3", driver_cls=failing_cls if failing == "r_b" else FakeDriver)
    pause_hub.add("v_c", "vfd", "gd20_bridge", driver_cls=failing_cls if failing == "v_c" else FakeDriver)

    with pytest.raises(RuntimeError) as excinfo:
        pause_hub.pause()

    assert str(excinfo.value) == "pause: сбой останова устройств"
    assert sorted(pause_hub.ops(), key=lambda item: item[0]) == [
        ("r_a", "stop", {"level": "SOFT"}),
        ("r_b", "abort", {"mode": 1}),
        ("v_c", "stop", {}),
    ], "каждое устройство, включая отказавшее и стоящие после него, получило свою команду"


@pytest.mark.parametrize("never_connected", [True, False], ids=["no_driver", "driver_down"])
def test_red7_not_connected_device_is_skipped_silently(pause_hub: PauseHub, never_connected: bool) -> None:
    """RED 7: неподключённое устройство (нет драйвера / ``is_connected`` ложно) пропущено, без исключения."""
    pause_hub.add("r_up", "robot", "delta_v2")
    pause_hub.add("r_down", "robot", "delta_v2", connect=not never_connected)
    if not never_connected:
        pause_hub.drivers["r_down"].up = False  # обрыв после подключения

    pause_hub.pause()  # не бросает

    assert pause_hub.ops() == [("r_up", "stop", {"level": "SOFT"})]


# --------------------------------------------------------------------------------------------------
# RED 8 — симулятор v2: факт о стоп-защёлке и очереди (П.5)
# --------------------------------------------------------------------------------------------------

_CVT_JOB_CMD = re.compile(r"\[v2\] CMD seq=\d+ op=CVT_JOB")


class _V2Stand:
    """Плагин ``device_hub`` с настоящим ``RobotDriverV2`` на симуляторе; ``call`` драйвера пишется в журнал."""

    def __init__(self, tmp_path: Path, rig: Any) -> None:
        registry = tmp_path / "devices.yaml"
        self.ctx = make_ctx({"registry_path": str(registry), "recipe_devices": []}, tmp_registry=registry)
        self.plugin = DeviceHubPlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)
        self.rig = rig
        res = self.plugin.cmd_device_upsert(_v2_entry("r1", rig.port))
        assert res["status"] == "ok", res
        assert self.plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(self.plugin._process_conn_queue, _CONNECT_S)
        driver = self.plugin._manager.get_driver("r1")
        assert driver is not None and driver.is_connected, "обвязка: робот v2 не подключён"
        self.journal: list[tuple[str, dict]] = []
        self._real_call = driver.call
        driver.call = self._recorded_call  # type: ignore[method-assign]

    def _recorded_call(self, op: str, args: dict) -> dict:
        self.journal.append((op, dict(args)))
        return self._real_call(op, args)

    def cmd(self, name: str, data: dict) -> dict:
        return bounded(lambda: getattr(self.plugin, f"cmd_{name}")({"device_id": "r1", **data}), _CALL_S)

    def stops(self) -> list[dict]:
        return [args for op, args in self.journal if op == "stop"]

    def cvt_jobs_sent(self) -> int:
        return sum(1 for _t, text in self.rig.core.events() if _CVT_JOB_CMD.search(text))

    def close(self) -> None:
        try:
            bounded(lambda: self.plugin.shutdown(self.ctx), _CALL_S)
        except BaseException:  # noqa: BLE001 — уборка не подменяет провал теста
            pass


def test_red8_after_pause_the_driver_accepts_new_jog_and_job(tmp_path: Path) -> None:
    """RED 8 / П.5: ``pause`` пишет ``stop`` SOFT, но защёлка не блокирует: следующие ``jog_hold`` и постановка
    задания принимаются (ФАКТ, не пожелание)."""
    with E2eRig() as rig:
        stand = _V2Stand(tmp_path, rig)
        try:
            bounded(lambda: stand.plugin.pause(stand.ctx), _CALL_S)

            assert stand.stops() == [{"level": "SOFT"}], stand.journal
            assert all(op != "park" for op, _args in stand.journal), stand.journal

            jog = bounded(lambda: stand.plugin._manager.call("r1", "jog_hold", {"dir": 1, "spd": 20}), _CALL_S)
            assert jog["status"] == "ok", jog
            bounded(lambda: stand.plugin._manager.call("r1", "jog_release", {}), _CALL_S)
            queued = stand.cmd("robot_enqueue_job", {"x_mm": 330, "y_mm": -120})
            assert queued["status"] == "ok", queued
        finally:
            stand.close()


def test_red8_queued_jobs_keep_going_after_pause(tmp_path: Path) -> None:
    """RED 8 / П.5: два задания в очереди драйвера, ``pause``, ход драйвера -> оба задания уходят на робота.

    Фиксируется ФАКТ (очередь после ``stop`` не удерживается); обратного («стоп удерживает») тест не утверждает.
    """
    with E2eRig() as rig:
        stand = _V2Stand(tmp_path, rig)
        stop_evt, pause_evt = threading.Event(), threading.Event()
        thread: threading.Thread | None = None
        try:
            assert stand.cmd("robot_enqueue_job", {"x_mm": 300, "y_mm": -150})["queue_len"] == 1
            assert stand.cmd("robot_enqueue_job", {"x_mm": 310, "y_mm": -140})["queue_len"] == 2

            bounded(lambda: stand.plugin.pause(stand.ctx), _CALL_S)
            assert stand.stops() == [{"level": "SOFT"}], stand.journal  # пауза состоялась до хода драйвера

            stand.plugin._ensure_device_workers()
            worker = stand.ctx.worker_manager.workers["dev_r1"]["fn"]
            thread = threading.Thread(target=worker, args=(stop_evt, pause_evt), daemon=True, name="red8-tick")
            thread.start()

            until(lambda: stand.cvt_jobs_sent() >= 2, 20.0, "оба задания очереди ушли на робота после pause")
            assert stand.cvt_jobs_sent() == 2
        finally:
            stop_evt.set()
            if thread is not None:
                thread.join(5.0)
            stand.close()
