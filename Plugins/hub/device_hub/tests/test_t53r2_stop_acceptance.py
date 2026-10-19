"""Слепая приёмка T5.3 круг 2: процессная остановка роботов в хабе устройств (критерии A1-A7).

Purpose:
    ``DeviceHubPlugin.shutdown(ctx)`` с роботами протокола ``delta_v2`` на симуляторах ``E2eRig``. Наблюдается
    только СТОРОНА РОБОТА: двойник робота пишет в журнал каждый Modbus-запрос записи, затрагивающий регистр
    ``STOP_REQ``, со штампом ``perf_counter``; двойник умеет НИКОГДА не подтверждать стоп (``TLM_STOP_ACK``
    остаётся прежним) и умеет отвечать исключением Modbus на ПЕРВУЮ запись ``STOP_REQ``. Плюс стенные часы вокруг
    ``shutdown``. Внутренности хаба (драйвер, менеджер, клиент робота) не патчатся и не шпионятся: двойник — это
    сервер на другом конце провода.

Public API:
    Только тесты ``test_*``.

Stability: lite

Как устроены двойники (всё на стороне робота):
    * Счёт записей: ``_ObservedServer._make_device`` оборачивает action-хук pymodbus-сервера. Хук зовётся на
      КАЖДЫЙ запрос (FC6/FC16) ДО применения, значит видит и запись, которую двойник отклонит. Запись в журнал =
      запрос, пришедший по проводу в сервер, который ``E2eRig`` поднимает штатно (тот же путь, что у любого
      клиента), а не вызов метода клиента.
    * «Никогда не подтверждает»: ``_StopCore.tick`` после каждого тика возвращает ``TLM_STOP_ACK`` к значению,
      снятому в момент ``arm_never_confirm()``. Робот при этом ОБРЫВАЕТ движение (ядро ``_handle_stop`` работает
      штатно) — потеряно только эхо. Окно гонки: между записью эха внутри тика и возвратом в конце того же тика
      (десятки микросекунд, поллер должен попасть именно туда) — см. отчёт, «ненадёжно».
    * Сбой первой записи: хук возвращает ``ExcCodes.DEVICE_FAILURE`` на первую запись ``STOP_REQ``; регистр не
      меняется, последующие записи проходят.

Правила файла: ожидаемые значения — литералы брифа (2.5, 0.1, 1, 2, 0); блокирующий вызов — в daemon-потоке с
дедлайном (``bounded``); порты — ``free_port`` через ``E2eRig``; записи ДО ``shutdown`` отсечены штампом старта.
Сценарий считается один раз на тест-сессию и кэшируется: критерии одного сценария — отдельные тесты.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pymodbus.constants import ExcCodes

from multiprocess_framework.modules.base_manager import unclosed_roots
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, RecordingCore, bounded

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

_SHUTDOWN_BUDGET_S = 2.5  # A1-A4, A6
_PEER_GAP_S = 0.1  # A2: запись r2 не позже, чем через 0.1 с после записи r1
_HELD_REPLY_S = 3.0  # A2b: ответ r1 на запись STOP_REQ держится 3 с (бриф лида: >= 1.5 с)
_RETRY_MIN_GAP_S = 0.9  # A2b: повтор записи только после таймаута прежней, не сразу
_ONE_WRITE = 1
_TWO_WRITES = 2
_SOFT_LEVEL = 1  # младшие 2 бита значения STOP_REQ (значение = stop_seq * 4 + уровень): SOFT = 1

_JOG = {"dir": 1, "spd": 20}
_HOLD_PERIOD_S = 0.05
_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params
_SHUTDOWN_HARD_DEADLINE_S = 10.0  # зависший shutdown не вешает набор: elapsed фиксируется как 10 с
_SETTLE_S = 0.3  # запись, пришедшая уже ПОСЛЕ возврата shutdown, тоже считается (утечка потока)
_MOVING_DEADLINE_S = 5.0
_STOPPED_DEADLINE_S = 1.0
_PLUGIN_ROOT = "device_hub"
_THREAD_PREFIXES = ("device_hub/", "rv2-")

_STOP_REQ_ADDR = REG["STOP_REQ"]
_TLM_STOP_ACK_ADDR = REG["TLM_STOP_ACK"]
_WRITE_FCS = frozenset({6, 16})


# --------------------------------------------------------------------------------------------------
# Двойник робота: журнал записей STOP_REQ + «не подтверждаю»
# --------------------------------------------------------------------------------------------------


class StopJournal:
    """Штампы запросов записи ``STOP_REQ`` (``perf_counter``), пришедших в сервер. Потокобезопасно."""

    def __init__(self, *, fail_first_write: bool = False, hold_reply_s: float = 0.0) -> None:
        self.hold_reply_s = hold_reply_s
        self._lock = threading.Lock()
        self._stamps: list[float] = []
        self._fail_first = fail_first_write
        self._failed = 0

    def hit(self) -> bool:
        """Записать запрос; True — его надо отклонить (сбой первой записи)."""
        with self._lock:
            self._stamps.append(time.perf_counter())
            if self._fail_first and self._failed == 0:
                self._failed = 1
                return True
            return False

    def since(self, t0: float) -> list[float]:
        with self._lock:
            return [t for t in self._stamps if t >= t0]

    def total(self) -> int:
        with self._lock:
            return len(self._stamps)


class _StopCore(RecordingCore):
    """``RecordingCore`` с режимом «эхо стопа не приходит»: ``TLM_STOP_ACK`` заморожен после ``arm``."""

    def __init__(self) -> None:
        self._never_confirm = False
        self._frozen_ack = 0
        super().__init__()

    def arm_never_confirm(self) -> None:
        self._frozen_ack = self.regs[_TLM_STOP_ACK_ADDR]
        self._never_confirm = True

    def tick(self, dt_s: float | None = None) -> None:
        super().tick(dt_s)
        if self._never_confirm:
            self.regs[_TLM_STOP_ACK_ADDR] = self._frozen_ack


class _ObservedServer(SimRobotServer):
    """``SimRobotServer``, чей action-хук ведёт журнал записей ``STOP_REQ`` и может отклонить первую."""

    def __init__(self, *args: Any, journal: StopJournal, **kwargs: Any) -> None:
        self._journal = journal
        super().__init__(*args, **kwargs)

    def _make_device(self):  # noqa: ANN202 — тип SimDevice внутренний для pymodbus
        device = super()._make_device()
        inner = device.action
        journal = self._journal

        async def action(fc, start, addr, count, registers, values):  # noqa: ANN001, ANN202
            result = await inner(fc, start, addr, count, registers, values)  # привязка хранилища ядра
            if (
                int(fc) in _WRITE_FCS
                and values is not None
                and addr <= _STOP_REQ_ADDR < addr + max(int(count), len(values))
            ):
                if journal.hit():
                    return ExcCodes.DEVICE_FAILURE
                if journal.hold_reply_s > 0:
                    # Запись применяется сразу (робот стоп «слышит»), ОТВЕТ клиенту задерживается: pymodbus
                    # повторно применит те же значения и ответит только после возврата хука.
                    offset = addr - start
                    registers[offset : offset + len(values)] = values
                    await asyncio.sleep(journal.hold_reply_s)
            return result

        device.action = action
        return device


class _ObservedRig(E2eRig):
    """``E2eRig`` с сервером ``_ObservedServer``; остальное (клиент, порт, уборка) штатное."""

    def __init__(self, journal: StopJournal, core: _StopCore) -> None:
        super().__init__(core=core)
        self.journal = journal

    def _start_server(self) -> None:
        from Services.robot_comm.tests.e2e_rig_v2 import _HOST, free_port  # noqa: PLC0415

        last: Exception | None = None
        for _ in range(3):
            self.port = free_port()
            server = _ObservedServer(_HOST, self.port, ROBOT_UNIT_ID, core=self.core, journal=self.journal)
            try:
                bounded(server.start, 10.0)
            except (RuntimeError, TimeoutError) as exc:
                bounded(server.stop, 5.0)
                last = exc
                continue
            self.server = server
            return
        assert last is not None
        raise last


# --------------------------------------------------------------------------------------------------
# Сценарий
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RobotSpec:
    motion: str  # "jog" | "program" | "idle"
    confirm: bool = True
    fail_first_write: bool = False
    hold_reply_s: float = 0.0  # ответ на запись STOP_REQ задержан на столько секунд


@dataclass
class Observed:
    elapsed_s: float = 0.0
    shutdown_hung: bool = False
    moving_before: dict[str, int] = field(default_factory=dict)
    moving_after: dict[str, int] = field(default_factory=dict)
    writes: dict[str, list[float]] = field(default_factory=dict)  # штампы ПОСЛЕ старта shutdown
    pre_writes: dict[str, int] = field(default_factory=dict)  # записей ДО старта (диагностика)
    stop_req_last: dict[str, int] = field(default_factory=dict)  # регистр STOP_REQ на роботе после shutdown (A5)
    leaked_threads: list[str] = field(default_factory=list)
    leaked_roots: list[str] = field(default_factory=list)


SCENARIOS: dict[str, dict[str, RobotSpec]] = {
    "a1_jog": {"r1": RobotSpec("jog", confirm=False)},
    "a1_program": {"r1": RobotSpec("program", confirm=False)},
    "a2": {"r1": RobotSpec("program", confirm=False), "r2": RobotSpec("jog")},
    "a2b": {"r1": RobotSpec("program", confirm=False, hold_reply_s=_HELD_REPLY_S), "r2": RobotSpec("jog")},
    "a3": {"r1": RobotSpec("program", confirm=False), "r2": RobotSpec("jog", confirm=False)},
    "a4": {"r1": RobotSpec("program"), "r2": RobotSpec("jog")},
    "a5": {"r1": RobotSpec("idle")},
    "a6": {"r1": RobotSpec("jog", fail_first_write=True)},
}

_CACHE: dict[str, Observed | BaseException] = {}


def _thread_names() -> list[str]:
    return sorted(t.name for t in threading.enumerate() if t.name.startswith(_THREAD_PREFIXES))


def _root_paths() -> list[str]:
    return sorted(r["path"] for r in unclosed_roots())


def _new_items(now: list[str], before: list[str]) -> list[str]:
    return sorted((Counter(now) - Counter(before)).elements())


def _legs_program(legs: int) -> tuple[Program, dict[str, Point]]:
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name="long", steps=steps), points


def _moving(core: RecordingCore) -> int:
    ticks = core.ticks()
    return ticks[-1].moving if ticks else -1


def _until(pred: Callable[[], object], deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.01)


def _plugin_with_robots(tmp_path: Path, ports: dict[str, int]) -> tuple[DeviceHubPlugin, Any]:
    registry_file = tmp_path / "devices.yaml"
    recipe = [
        {
            "id": dev_id,
            "name": dev_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        }
        for dev_id, port in ports.items()
    ]
    ctx = make_ctx({"registry_path": str(registry_file), "recipe_devices": recipe}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    for dev_id in ports:
        assert plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
    bounded(plugin._process_conn_queue, _CONNECT_DEADLINE_S)
    assert sorted(plugin._manager.connected_ids()) == sorted(ports), "роботы не подключились через очередь плагина"
    return plugin, ctx


def _run_scenario(name: str, tmp_path: Path) -> Observed:
    specs = SCENARIOS[name]
    obs = Observed()
    threads_before = _thread_names()
    roots_before = _root_paths()
    stop_holders = threading.Event()
    holders: list[threading.Thread] = []
    plugin: DeviceHubPlugin | None = None
    ctx: Any = None
    try:
        with ExitStack() as stack:
            rigs: dict[str, _ObservedRig] = {}
            for dev_id, spec in specs.items():
                rig = _ObservedRig(
                    StopJournal(fail_first_write=spec.fail_first_write, hold_reply_s=spec.hold_reply_s), _StopCore()
                )
                rigs[dev_id] = stack.enter_context(rig)
            plugin, ctx = _plugin_with_robots(tmp_path, {dev_id: rig.port for dev_id, rig in rigs.items()})

            # --- довести роботов до движения ---
            for dev_id, spec in specs.items():
                manager = plugin._manager
                if spec.motion == "jog":
                    reply = bounded(lambda d=dev_id: manager.call(d, "jog_hold", dict(_JOG)), _CALL_DEADLINE_S)
                    assert reply["status"] == "ok", f"{dev_id}: jog_hold не принят: {reply}"

                    def hold(d: str = dev_id) -> None:
                        while not stop_holders.is_set():
                            try:
                                manager.call(d, "jog_hold", dict(_JOG))
                            except BaseException:  # noqa: BLE001 — менеджер закрывается, ответ не важен
                                pass
                            stop_holders.wait(_HOLD_PERIOD_S)

                    holder = threading.Thread(target=hold, name=f"t53r2-holder-{dev_id}", daemon=True)
                    holder.start()
                    holders.append(holder)
                elif spec.motion == "program":
                    program, points = _legs_program(20)  # ~5.4 с sim: к shutdown остаётся >= 3 с
                    reply = bounded(
                        lambda d=dev_id: manager.get_driver(d).start_program(program, points, None, name="long"),
                        _CALL_DEADLINE_S,
                    )
                    assert reply["status"] == "ok", f"{dev_id}: start_program не принят: {reply}"
            for dev_id, spec in specs.items():
                core = rigs[dev_id].core
                if spec.motion != "idle":
                    assert _until(lambda c=core: _moving(c) == 1, _MOVING_DEADLINE_S), (
                        f"{dev_id}: робот не дошёл до движения за {_MOVING_DEADLINE_S} с (motion={spec.motion})"
                    )
            time.sleep(0.5)  # движение устоялось
            for dev_id in specs:
                obs.moving_before[dev_id] = _moving(rigs[dev_id].core)
                assert obs.moving_before[dev_id] == (0 if specs[dev_id].motion == "idle" else 1), (
                    f"{dev_id}: перед shutdown TLM_MOVING={obs.moving_before[dev_id]}, motion={specs[dev_id].motion}"
                )

            # --- процессная остановка ---
            for dev_id, spec in specs.items():
                if not spec.confirm:
                    rigs[dev_id].core.arm_never_confirm()
                obs.pre_writes[dev_id] = rigs[dev_id].journal.total()
            t_start = time.perf_counter()
            try:
                bounded(lambda: plugin.shutdown(ctx), _SHUTDOWN_HARD_DEADLINE_S)
            except TimeoutError:
                obs.shutdown_hung = True
            obs.elapsed_s = time.perf_counter() - t_start
            time.sleep(_SETTLE_S)

            for dev_id in specs:
                obs.writes[dev_id] = [t - t_start for t in rigs[dev_id].journal.since(t_start)]
            for dev_id in specs:
                obs.stop_req_last[dev_id] = int(rigs[dev_id].core.regs[_STOP_REQ_ADDR])
            for dev_id in specs:
                core = rigs[dev_id].core
                _until(lambda c=core: _moving(c) == 0, _STOPPED_DEADLINE_S)
                obs.moving_after[dev_id] = _moving(core)
            obs.leaked_threads = _new_items(_thread_names(), threads_before)
            obs.leaked_roots = _new_items(_root_paths(), roots_before)
            stop_holders.set()
    finally:
        stop_holders.set()
        for holder in holders:
            holder.join(2.0)
        if plugin is not None:
            try:
                bounded(lambda: plugin.shutdown(ctx), _SHUTDOWN_HARD_DEADLINE_S)  # повтор безвреден
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение сценария
                pass
    return obs


@pytest.fixture
def scenario(tmp_path: Path) -> Callable[[str], Observed]:
    def get(name: str) -> Observed:
        if name not in _CACHE:
            try:
                _CACHE[name] = _run_scenario(name, tmp_path)
            except BaseException as exc:  # noqa: BLE001 — исключение сценария предъявляется каждому его тесту
                _CACHE[name] = exc
        cached = _CACHE[name]
        if isinstance(cached, BaseException):
            raise cached
        return cached

    return get


def _fmt(obs: Observed) -> str:
    stamps = {k: [round(t, 3) for t in v] for k, v in obs.writes.items()}
    return (
        f"elapsed={obs.elapsed_s:.2f}s hung={obs.shutdown_hung} writes_after_start={stamps} "
        f"pre_writes={obs.pre_writes} moving_before={obs.moving_before}"
    )


def _assert_moving_reached(obs: Observed, specs: dict[str, RobotSpec]) -> None:
    """Защита от пустой зелени: каждый робот перед shutdown был в нужном состоянии (движется / простаивает)."""
    for dev_id, spec in specs.items():
        expected = 0 if spec.motion == "idle" else 1
        assert obs.moving_before[dev_id] == expected, f"{dev_id}: moving_before={obs.moving_before[dev_id]}"


# --------------------------------------------------------------------------------------------------
# A1: один робот в движении, стоп не подтверждается
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a1_jog", "a1_program"])
def test_a1_one_robot_never_confirms_shutdown_within_budget(scenario, name: str) -> None:
    obs = scenario(name)
    _assert_moving_reached(obs, SCENARIOS[name])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"{name}: shutdown не уложился в 2.5 с: {_fmt(obs)}"


@pytest.mark.parametrize("name", ["a1_jog", "a1_program"])
def test_a1_one_robot_never_confirms_exactly_one_stop_write(scenario, name: str) -> None:
    obs = scenario(name)
    _assert_moving_reached(obs, SCENARIOS[name])
    assert len(obs.writes["r1"]) == _ONE_WRITE, f"{name}: записей STOP_REQ у r1 не 1: {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A2 (A2a): два в движении, r1 не подтверждает эхо (ответ на запись приходит), r2 штатный
# --------------------------------------------------------------------------------------------------


def test_a2_peer_unconfirmed_shutdown_within_budget(scenario) -> None:
    obs = scenario("a2")
    _assert_moving_reached(obs, SCENARIOS["a2"])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"a2: shutdown не уложился в 2.5 с: {_fmt(obs)}"


def test_a2_peer_unconfirmed_exactly_one_write_per_robot(scenario) -> None:
    obs = scenario("a2")
    _assert_moving_reached(obs, SCENARIOS["a2"])
    counts = {dev_id: len(stamps) for dev_id, stamps in obs.writes.items()}
    assert counts == {"r1": _ONE_WRITE, "r2": _ONE_WRITE}, f"a2: записей STOP_REQ на робота: {counts}; {_fmt(obs)}"


def test_a2_second_robot_stop_is_not_held_behind_first(scenario) -> None:
    obs = scenario("a2")
    _assert_moving_reached(obs, SCENARIOS["a2"])
    assert obs.writes["r1"], f"a2: r1 не получил ни одной записи STOP_REQ: {_fmt(obs)}"
    assert obs.writes["r2"], f"a2: r2 не получил ни одной записи STOP_REQ: {_fmt(obs)}"
    gap = abs(obs.writes["r2"][0] - obs.writes["r1"][0])
    assert gap <= _PEER_GAP_S, f"a2: запись r2 отстоит от записи r1 на {gap:.3f} с (> 0.1): {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A2b: r1 ещё и не отвечает на запись STOP_REQ (ответ держится 3 с); r2 штатный
# --------------------------------------------------------------------------------------------------


def test_a2b_peer_reply_held_shutdown_within_budget(scenario) -> None:
    obs = scenario("a2b")
    _assert_moving_reached(obs, SCENARIOS["a2b"])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"a2b: shutdown не уложился в 2.5 с: {_fmt(obs)}"


def test_a2b_peer_reply_held_write_counts_one_retry_for_r1_one_for_r2(scenario) -> None:
    # Ответ r1 держится 3 с: запись клиента истекает по таймауту = неудачная запись, дизайн даёт ровно один повтор.
    obs = scenario("a2b")
    _assert_moving_reached(obs, SCENARIOS["a2b"])
    counts = {dev_id: len(stamps) for dev_id, stamps in obs.writes.items()}
    assert counts == {"r1": _TWO_WRITES, "r2": _ONE_WRITE}, f"a2b: записей STOP_REQ на робота: {counts}; {_fmt(obs)}"


def test_a2b_peer_reply_held_retry_only_after_timed_out_write(scenario) -> None:
    obs = scenario("a2b")
    _assert_moving_reached(obs, SCENARIOS["a2b"])
    assert len(obs.writes["r1"]) >= _TWO_WRITES, f"a2b: у r1 нет повтора записи STOP_REQ: {_fmt(obs)}"
    spacing = obs.writes["r1"][1] - obs.writes["r1"][0]
    assert spacing >= _RETRY_MIN_GAP_S, f"a2b: повтор r1 пришёл через {spacing:.3f} с (< 0.9): {_fmt(obs)}"


def test_a2b_second_robot_write_arrives_within_gap_of_first_arrival(scenario) -> None:
    obs = scenario("a2b")
    _assert_moving_reached(obs, SCENARIOS["a2b"])
    assert obs.writes["r1"], f"a2b: r1 не получил ни одной записи STOP_REQ: {_fmt(obs)}"
    assert obs.writes["r2"], f"a2b: r2 не получил ни одной записи STOP_REQ: {_fmt(obs)}"
    gap = abs(obs.writes["r2"][0] - obs.writes["r1"][0])  # штампы — момент ПРИХОДА запроса в сервер
    assert gap <= _PEER_GAP_S, f"a2b: запись r2 пришла через {gap:.3f} с после прихода записи r1 (> 0.1): {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A3: оба не подтверждают
# --------------------------------------------------------------------------------------------------


def test_a3_both_unconfirmed_shutdown_within_budget(scenario) -> None:
    obs = scenario("a3")
    _assert_moving_reached(obs, SCENARIOS["a3"])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"a3: shutdown не уложился в 2.5 с: {_fmt(obs)}"


def test_a3_both_unconfirmed_exactly_one_write_per_robot(scenario) -> None:
    obs = scenario("a3")
    _assert_moving_reached(obs, SCENARIOS["a3"])
    counts = {dev_id: len(stamps) for dev_id, stamps in obs.writes.items()}
    assert counts == {"r1": _ONE_WRITE, "r2": _ONE_WRITE}, f"a3: записей STOP_REQ на робота: {counts}; {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A4: оба подтверждают штатно
# --------------------------------------------------------------------------------------------------


def test_a4_both_confirm_shutdown_within_budget(scenario) -> None:
    obs = scenario("a4")
    _assert_moving_reached(obs, SCENARIOS["a4"])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"a4: shutdown не уложился в 2.5 с: {_fmt(obs)}"


def test_a4_both_confirm_exactly_one_write_per_robot(scenario) -> None:
    obs = scenario("a4")
    _assert_moving_reached(obs, SCENARIOS["a4"])
    counts = {dev_id: len(stamps) for dev_id, stamps in obs.writes.items()}
    assert counts == {"r1": _ONE_WRITE, "r2": _ONE_WRITE}, f"a4: записей STOP_REQ на робота: {counts}; {_fmt(obs)}"


def test_a4_both_confirm_robots_end_not_moving(scenario) -> None:
    obs = scenario("a4")
    _assert_moving_reached(obs, SCENARIOS["a4"])
    assert obs.moving_after == {"r1": 0, "r2": 0}, f"a4: TLM_MOVING после shutdown: {obs.moving_after}; {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A5: подключённый простаивающий робот при остановке процесса — одна запись STOP_REQ уровня SOFT
# --------------------------------------------------------------------------------------------------


def test_a5_idle_robot_gets_one_soft_stop_write(scenario) -> None:
    # решение владельца 2026-10-19: выключаемый робот получает стоп и в покое
    obs = scenario("a5")
    _assert_moving_reached(obs, SCENARIOS["a5"])  # подключён (проверено сборкой сценария) и не движется
    assert len(obs.writes["r1"]) == _ONE_WRITE, f"a5: записей STOP_REQ у простаивающего r1 не 1: {_fmt(obs)}"
    last = obs.stop_req_last["r1"]
    assert last & 3 == _SOFT_LEVEL, f"a5: уровень записи STOP_REQ не SOFT (1): регистр={last}; {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A6: первая запись STOP_REQ отклонена исключением Modbus — ровно один повтор
# --------------------------------------------------------------------------------------------------


def test_a6_first_write_fails_exactly_one_retry(scenario) -> None:
    obs = scenario("a6")
    _assert_moving_reached(obs, SCENARIOS["a6"])
    assert len(obs.writes["r1"]) == _TWO_WRITES, f"a6: записей STOP_REQ не 2 (отказ + один повтор): {_fmt(obs)}"


def test_a6_first_write_fails_shutdown_within_budget(scenario) -> None:
    obs = scenario("a6")
    _assert_moving_reached(obs, SCENARIOS["a6"])
    assert obs.elapsed_s <= _SHUTDOWN_BUDGET_S, f"a6: shutdown не уложился в 2.5 с: {_fmt(obs)}"


# --------------------------------------------------------------------------------------------------
# A7: после каждого сценария — ни потоков хаба, ни незакрытых корней
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a7_no_leaked_threads_or_roots_after_scenario(scenario, name: str) -> None:
    obs = scenario(name)
    _assert_moving_reached(obs, SCENARIOS[name])
    assert obs.leaked_threads == [], f"{name}: после shutdown живы потоки {obs.leaked_threads}; {_fmt(obs)}"
    assert obs.leaked_roots == [], f"{name}: после shutdown не закрыты корни {obs.leaked_roots}; {_fmt(obs)}"
