"""C-29 — слепая приёмка: «Отключить» посреди подключения робота v2 (критерии A1-A15 из ``C-29.acceptance.md``).

Purpose:
    Обвязка: настоящий ``DeviceHubPlugin`` (``make_ctx``) + настоящий ``DeviceManager`` + настоящий драйвер v2.
    Фейки на границе драйвера: транспорт (``FakeTransport``) и клиент v2 (``FakeClient``), оба внедряются подклассом
    драйвера в фабрике менеджера (подмена ``robot_driver_v2.RobotDriverV2`` на время теста; фабрика менеджера, ``spawn``
    области плагина, ``publish`` и хранилище данных — настоящие). Приватных полей драйвера тест не трогает.
    Наблюдается только публичное: ответы команд плагина, канал ``ctx.state_proxy.set`` с путём
    ``devices.state.<id>.conn`` (повторы подряд схлопнуты), счётчики на фейке (STOP_REQ по уровням, SERVO, DO, probe,
    JOG_CONT, кадры jog, задания, программы), журнал (caplog), ``desired_connected`` и ``is_connected``.
    «Супервизор» — поток, который зовёт ``plugin._process_conn_queue()`` (как существующие тесты хаба); «тик» —
    настоящее тело per-device воркера плагина в своём потоке. Паузы — барьеры (``threading.Event``) в фейке или в
    ``state_proxy.set``, только в нужном потоке; любой блокирующий вызов — daemon-поток с join-дедлайном.

Public API:
    Только тесты ``test_a<N>_*``. Ожидаемые значения — литералы из критериев; одна «парная» проверка
    (достижимость окна / нормальный ход) идёт рядом с каждой проверкой «ничего не ушло».

Stability: lite
"""

from __future__ import annotations

import logging
import threading
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import Services.device_hub.drivers.robot_driver_v2 as v2pkg
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.robot_comm.core.client_v2 import SyncCancelled
from Services.robot_comm.core.protocol_v2 import REG

DEV = "rv2"
TEXT_DISCONNECTING = "идёт отключение робота"
TEXT_DROPPED = "при отключении сняты задания: 1, возвраты: 1"
SOFT = 1  # STOP_LEVEL["SOFT"] протокола v2: литерал

SUP = "c29-sup"  # имя потока «супервизора» (барьеры привязаны к имени потока)
TICK = "c29-tick"  # имя потока «тика»
HIT_S = 5.0  # ждать входа потока в окно
JOIN_S = 8.0  # дедлайн join рабочих потоков
RELEASE_S = 10.0  # барьер сам отпускает через это время (тест не виснет)
CMD_S = 5.0  # дедлайн команды плагина

_PROGRAM = {"name": "p1", "steps": [{"op": "move", "point": "a", "kind": "JOINT"}]}
_POINT_A = {"name": "a", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 1}


# --------------------------------------------------------------------------------------------------
# Потоки и барьеры
# --------------------------------------------------------------------------------------------------


class Worker:
    """Daemon-поток с результатом и ошибкой; ``join`` с дедлайном возвращает «ещё жив»."""

    def __init__(self, fn: Callable[[], Any], name: str) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self.done = threading.Event()

        def run() -> None:
            try:
                self.result = fn()
            except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, name=name, daemon=True)
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def join(self, deadline_s: float) -> bool:
        """True — поток вышел за срок."""
        self.thread.join(deadline_s)
        return not self.thread.is_alive()


class Gate:
    """Барьер: один раз, только в потоке с именем ``thread_name``; ``snapshot`` — счётчики событий в момент входа."""

    def __init__(self, rig: Rig, thread_name: str) -> None:
        self.rig = rig
        self.thread_name = thread_name
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fired = False
        self.snapshot: dict[str, int] = {}

    def hit(self) -> None:
        if self.fired or threading.current_thread().name != self.thread_name:
            return
        self.fired = True
        self.snapshot = self.rig.counts()
        self.entered.set()
        self.release.wait(RELEASE_S)


# --------------------------------------------------------------------------------------------------
# Фейки
# --------------------------------------------------------------------------------------------------


def _free_tlm(servo: int = 0) -> list[int]:
    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = servo
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class FakeTransport:
    """Транспорт: ``connect`` встаёт на барьер ``transport_connect`` ДО того, как связь считается поднятой."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.is_connected = False
        self.tlm = _free_tlm()
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.guard = threading.Lock()

    def connect(self) -> bool:
        self.connect_calls += 1
        self.rig.fire("transport_connect")
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False

    def drop(self) -> None:
        """Связь упала: транспорт закрыт, робот по сторожу выключил серво и DO (переподключение их пошлёт заново)."""
        self.is_connected = False
        self.set_word("TLM_SERVO", 0)
        self.set_word("TLM_DO_MASK", 0)

    def read_registers(self, _address: int, _count: int) -> list[int]:
        self.rig.fire("read")
        with self.guard:
            return list(self.tlm)

    def set_word(self, name: str, value: int) -> None:
        with self.guard:
            self.tlm[REG[name] - REG["TLM_PROTO_VER"]] = value

    def word(self, name: str) -> int:
        with self.guard:
            return self.tlm[REG[name] - REG["TLM_PROTO_VER"]]


class FakeClient:
    """Клиент v2: пишет события на ``rig``; ``servo`` и ``do_set`` меняют TLM транспорта (подтверждение)."""

    heartbeat_period_s = None
    jog_lease_period_s = None
    stop_generation = 0
    run_stop_base = 0

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.sync_duration_s = 0.0
        self.servo_confirms = True
        self.seq = 0

    def _next(self) -> SimpleNamespace:
        self.seq += 1
        return SimpleNamespace(seq=self.seq)

    def probe(self) -> None:
        self.rig.log("probe")
        self.rig.fire("probe")

    def sync_params(self, _values: Any, _epoch: int, *, cancelled: Callable[[], bool] | None = None) -> None:
        self.rig.log("sync")
        self.rig.fire("sync")
        steps = max(1, round(self.sync_duration_s / 0.01))
        for _ in range(steps):  # как настоящий клиент: предикат отмены — перед каждой записью
            if cancelled is not None and cancelled():
                raise SyncCancelled
            if self.sync_duration_s:
                time.sleep(0.01)

    def servo(self, on: bool) -> None:
        self.rig.log("servo", on)
        if self.servo_confirms:
            self.rig.transport.set_word("TLM_SERVO", 1 if on else 0)
        self.rig.fire("servo_done")

    def do_set(self, ch: int, on: bool) -> None:
        self.rig.log("do", (ch, on))
        mask = self.rig.transport.word("TLM_DO_MASK")
        bit = 1 << (ch - 1)
        self.rig.transport.set_word("TLM_DO_MASK", (mask | bit) if on else (mask & ~bit))

    def jog_cont(self, direction: int, speed: int) -> SimpleNamespace:
        self.rig.log("jog_cont", (direction, speed))
        return self._next()

    def jog_lease(self) -> None:
        pass

    def jog_step(self, dx: float, dy: float, dz: float, drz: float, speed: int) -> SimpleNamespace:
        self.rig.log("jog_step", (dx, dy, dz, drz, speed))
        return self._next()

    def cvt_job(self, *args: Any) -> SimpleNamespace:
        self.rig.log("cvt_job", args)
        return self._next()

    def wait_done(self, _seq: int, on_poll: Any = None) -> None:
        pass

    def run_chunks(self, _scenario: Any, *, params: Any, on_progress: Any) -> None:
        self.rig.log("run_chunks")

    def kick_heartbeat(self) -> None:
        pass

    def poll_errors(self) -> list:
        return []

    def issue_stop(self, level: int) -> int:
        self.rig.log("stop", level)
        return self.rig.count("stop") * 4 + level

    def stop(self, level: int) -> None:
        self.issue_stop(level)

    def await_stop_echo(self, _value: int, _level: int, *, deadline: float) -> None:
        pass


class Proxy:
    """``ctx.state_proxy``: пишет каждый ``set`` / ``merge``; ``hook`` вызывается в потоке вызывающего."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, str]] = []
        self.guard = threading.Lock()
        self.hook: Callable[[str, str, Any], None] | None = None

    def set(self, path: str, data: Any) -> None:
        self.record("set", path, data)

    def merge(self, path: str, data: Any) -> None:
        self.record("merge", path, data)

    def record(self, op: str, path: str, data: Any) -> None:
        with self.guard:
            self.calls.append((op, path, data, threading.current_thread().name))
        hook = self.hook
        if hook is not None:
            hook(op, path, data)

    def statuses(self, dev: str = DEV) -> list[str]:
        """Статусы ``conn`` канала ``set`` по порядку; повторы подряд схлопнуты."""
        path = f"devices.state.{dev}.conn"
        with self.guard:
            raw = [d["conn"] for op, p, d, _t in self.calls if op == "set" and p == path and isinstance(d, dict)]
        out: list[str] = []
        for status in raw:
            if not out or out[-1] != status:
                out.append(status)
        return out

    def texts(self, suffix: str) -> list[str]:
        with self.guard:
            return [str(d) for _op, p, d, _t in self.calls if p.endswith(suffix)]


# --------------------------------------------------------------------------------------------------
# Стенд
# --------------------------------------------------------------------------------------------------


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[tuple[str, Any]] = []
        self.guard = threading.Lock()
        self.gates: dict[str, Gate] = {}
        self.workers: list[Worker] = []
        self.tick_stop = threading.Event()
        self.transport = FakeTransport(self)
        self.client = FakeClient(self)
        self.proxy = Proxy()

        rig = self

        class V2(RobotDriverV2):
            """Драйвер v2 с внедрёнными фейками; ``connect`` / ``disconnect`` пишут события (публичные методы)."""

            def __init__(self, entry: Any, protocol: Any = None, **kw: Any) -> None:
                super().__init__(
                    entry, protocol, transport=rig.transport, client_factory=lambda _t, _c: rig.client, **kw
                )
                self.connect_results: list[bool] = []
                self.desired_at_connect_exit: list[bool] = []

            def connect(self) -> bool:
                rig.log("connect_enter")
                result = super().connect()
                self.connect_results.append(result)
                self.desired_at_connect_exit.append(self.desired_connected)
                rig.log("connect_exit", result)
                return result

            def disconnect(self) -> None:
                rig.log("disconnect_enter", self.desired_connected)
                super().disconnect()
                rig.log("disconnect_exit")

        monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
        monkeypatch.setattr(v2pkg, "RobotDriverV2", V2)
        registry = tmp_path / "devices.yaml"
        self.ctx = make_ctx({"registry_path": str(registry)}, state_proxy=self.proxy, tmp_registry=registry)
        self.plugin = DeviceHubPlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)
        self.teardown_errors: list[str] = []

    # --- события ---

    def log(self, kind: str, detail: Any = None) -> None:
        with self.guard:
            self.events.append((kind, detail))

    def mark(self) -> int:
        with self.guard:
            return len(self.events)

    def count(self, kind: str, since: int = 0) -> int:
        with self.guard:
            return sum(1 for k, _d in self.events[since:] if k == kind)

    def counts(self) -> dict[str, int]:
        with self.guard:
            out: dict[str, int] = {}
            for kind, _d in self.events:
                out[kind] = out.get(kind, 0) + 1
            return out

    def soft_count(self, since: int = 0) -> int:
        with self.guard:
            return sum(1 for k, d in self.events[since:] if k == "stop" and d == SOFT)

    def index_of(self, kind: str) -> int:
        with self.guard:
            for i, (k, _d) in enumerate(self.events):
                if k == kind:
                    return i
        return -1

    def wait_event(self, kind: str, n: int, deadline_s: float) -> bool:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            if self.count(kind) >= n:
                return True
            time.sleep(0.005)
        return False

    # --- барьеры ---

    def arm(self, name: str, thread_name: str) -> Gate:
        gate = Gate(self, thread_name)
        self.gates[name] = gate
        return gate

    def fire(self, name: str) -> None:
        gate = self.gates.get(name)
        if gate is not None:
            gate.hit()

    # --- потоки ---

    def start(self, fn: Callable[[], Any], name: str) -> Worker:
        worker = Worker(fn, name)
        self.workers.append(worker)
        return worker

    def supervisor(self, name: str = SUP) -> Worker:
        """Поток «супервизора»: разбор очереди connect / disconnect до пустой."""
        return self.start(self.plugin._process_conn_queue, name)

    def drain(self, deadline_s: float = JOIN_S) -> None:
        worker = self.supervisor("c29-drain")
        assert worker.join(deadline_s), f"очередь connect/disconnect не разобрана за {deadline_s} с"
        if worker.error is not None:
            raise worker.error

    def start_tick(self) -> Worker:
        """Настоящее тело per-device воркера плагина в своём потоке (имя ``TICK``)."""
        self.plugin._ensure_device_workers()
        fn = self.ctx.worker_manager.workers[f"dev_{DEV}"]["fn"]
        return self.start(lambda: fn(self.tick_stop, threading.Event()), TICK)

    # --- команды ---

    def cmd(self, name: str, data: dict | None = None, deadline_s: float = CMD_S) -> dict:
        payload = {"device_id": DEV, **(data or {})}
        worker = Worker(lambda: getattr(self.plugin, f"cmd_{name}")(payload), f"c29-cmd-{name}")
        self.workers.append(worker)
        assert worker.join(deadline_s), f"команда {name} не вернулась за {deadline_s} с"
        if worker.error is not None:
            raise worker.error
        return worker.result

    def upsert(self, *, do: bool = True, extra: dict | None = None) -> None:
        params: dict[str, Any] = {
            "poll_interval_s": 0.05,
            "on_connect": {"servo": True, "do": {"3": True} if do else {}},
            **(extra or {}),
        }
        entry = {
            "id": DEV,
            "name": DEV,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
            "params": params,
        }
        res = self.cmd("device_upsert", entry)
        assert res["status"] == "ok", res

    def driver(self) -> Any:
        drv = self.plugin._manager.get_driver(DEV)
        assert drv is not None, "драйвер ещё не создан"
        return drv

    def connect_ready(self) -> Any:
        """Нормальное «Подключить»: команда + разбор очереди; робот подключён."""
        assert self.cmd("device_connect")["status"] == "ok"
        self.drain()
        drv = self.driver()
        assert drv.is_connected, "настройка теста: робот не подключился"
        return drv

    def save_program(self) -> None:
        rev = self.cmd("robot_point_list")["rev"]
        res = self.cmd("robot_point_save", {"point": _POINT_A, "base_rev": rev})
        assert res["status"] == "ok", res
        res = self.cmd("robot_program_save", {"program": _PROGRAM, "base_rev": None})
        assert res["status"] == "ok", res

    # --- завершение ---

    def close(self) -> None:
        for gate in self.gates.values():
            gate.release.set()
        self.tick_stop.set()
        for worker in self.workers:
            worker.join(3.0)
        down = Worker(lambda: self.plugin.shutdown(self.ctx), "c29-shutdown")
        if not down.join(10.0):
            warnings.warn("plugin.shutdown не вернулся за 10 с (стенд C-29)", stacklevel=2)
        elif down.error is not None:
            warnings.warn(f"plugin.shutdown бросил {down.error!r} (стенд C-29)", stacklevel=2)


@pytest.fixture
def make_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rigs: list[Rig] = []

    def new(sub: str = "main") -> Rig:
        rig = Rig(tmp_path / sub, monkeypatch)
        rigs.append(rig)
        return rig

    yield new
    for rig in reversed(rigs):
        rig.close()


@pytest.fixture
def rig(make_rig: Callable[..., Rig]) -> Rig:
    return make_rig()


def _interrupt_at(rig: Rig, window: str) -> tuple[Gate, Worker]:
    """«Подключить» (команда); супервизор в потоке ``SUP`` встаёт на барьер ``window``; ждём входа."""
    gate = rig.arm(window, SUP)
    assert rig.cmd("device_connect")["status"] == "ok"
    sup = rig.supervisor()
    assert gate.entered.wait(HIT_S), f"окно {window} недостижимо: супервизор не дошёл до барьера"
    assert sup.alive(), "супервизор не стоит в connect"
    return gate, sup


def _finish(rig: Rig, gate: Gate, sup: Worker) -> None:
    """Отпустить барьер, дождаться супервизора и добрать очередь."""
    gate.release.set()
    assert sup.join(JOIN_S), "супервизор не вышел после отпускания барьера"
    rig.drain()


# --------------------------------------------------------------------------------------------------
# A1 — команда посреди connect возвращается быстро
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("window", ["transport_connect", "probe", "sync"])
def test_a1_command_returns_within_1s_while_connect_stands(rig: Rig, window: str) -> None:
    rig.upsert()
    gate, sup = _interrupt_at(rig, window)
    t0 = time.monotonic()
    res = rig.cmd("device_disconnect", deadline_s=1.0)
    elapsed = time.monotonic() - t0
    assert res["status"] == "ok", res
    assert elapsed < 1.0, f"A1[{window}]: команда вернулась за {elapsed:.2f} с"
    assert sup.alive(), f"A1[{window}]: окно недостижимо — connect уже не стоит"
    _finish(rig, gate, sup)


# --------------------------------------------------------------------------------------------------
# A2 — после подъёма связи: SERVO 0 / DO 0 после команды, connect() False, SOFT 1, транспорт закрыт
# --------------------------------------------------------------------------------------------------

# окно -> (барьер, ожидаемые счётчики в момент входа в окно: достижимость)
_A2_WINDOWS = {
    "probe": ("probe", {"probe": 1, "servo": 0, "do": 0}),
    "sync_params": ("sync", {"sync": 1, "servo": 0, "do": 0}),
    "before_servo": ("read", {"sync": 1, "servo": 0, "do": 0}),
    "before_do": ("servo_done", {"servo": 1, "do": 0}),
}


@pytest.mark.parametrize("window", list(_A2_WINDOWS))
def test_a2_link_up_no_servo_no_do_after_command(rig: Rig, window: str) -> None:
    barrier, reached = _A2_WINDOWS[window]
    rig.upsert()
    gate, sup = _interrupt_at(rig, barrier)
    for kind, expected in reached.items():
        assert gate.snapshot.get(kind, 0) == expected, f"A2[{window}]: окно не то, {kind}={gate.snapshot}"
    mark = rig.mark()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    _finish(rig, gate, sup)
    drv = rig.driver()
    observed = {
        "servo_after": rig.count("servo", mark),
        "do_after": rig.count("do", mark),
        "connect": drv.connect_results,
        "soft": rig.soft_count(),
        "transport_closed": not rig.transport.is_connected,
    }
    expected_final = {"servo_after": 0, "do_after": 0, "connect": [False], "soft": 1, "transport_closed": True}
    assert observed == expected_final, f"A2[{window}]: {observed}"


# --------------------------------------------------------------------------------------------------
# A3 — до подъёма связи (внутри transport.connect()): ничего не ушло
# --------------------------------------------------------------------------------------------------


def test_a3_before_link_up_nothing_sent(rig: Rig) -> None:
    rig.upsert()
    gate, sup = _interrupt_at(rig, "transport_connect")
    assert gate.snapshot.get("probe", 0) == 0, "A3: окно не то — probe уже был"
    assert rig.cmd("device_disconnect")["status"] == "ok"
    _finish(rig, gate, sup)
    drv = rig.driver()
    observed = {
        "probe": rig.count("probe"),
        "servo": rig.count("servo"),
        "stop_req": rig.count("stop"),
        "connect": drv.connect_results,
    }
    assert observed == {"probe": 0, "servo": 0, "stop_req": 0, "connect": [False]}, f"A3: {observed}"


def test_a3_pair_without_command_link_comes_up(rig: Rig) -> None:
    """Парная к A3: без команды тот же connect доходит до probe и SERVO (окно A3 — именно «до связи»)."""
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    rig.drain()
    drv = rig.driver()
    observed = {"probe": rig.count("probe"), "servo": rig.count("servo"), "connect": drv.connect_results}
    assert observed == {"probe": 1, "servo": 1, "connect": [True]}, f"A3-пара: {observed}"


# --------------------------------------------------------------------------------------------------
# A4 — быстрая реакция: долгая синхронизация 2,0 с / ожидание TLM после неподтверждённого SERVO
# --------------------------------------------------------------------------------------------------


def _reaction_s(rig: Rig, sup: Worker) -> float:
    """От вызова команды до входа в ``disconnect`` драйвера (любым потоком)."""
    assert sup.alive(), "A4: окно недостижимо — connect уже не стоит"
    t0 = time.monotonic()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    assert rig.wait_event("disconnect_enter", 1, 5.0), "A4: disconnect драйвера не вызван за 5 с"
    return time.monotonic() - t0


def test_a4_long_sync_reaction_under_half_second(rig: Rig) -> None:
    rig.client.sync_duration_s = 2.0
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    sup = rig.supervisor()
    assert rig.wait_event("sync", 1, HIT_S), "A4: окно недостижимо — sync_params не начат"
    time.sleep(0.2)
    reaction = _reaction_s(rig, sup)
    assert sup.join(JOIN_S)
    rig.drain()
    assert reaction < 0.5, f"A4(sync): реакция {reaction:.2f} с, хотим < 0,5"
    assert rig.soft_count() == 1, f"A4(sync): SOFT {rig.soft_count()}, хотим 1"


def test_a4_tlm_wait_after_unconfirmed_servo_reaction_under_half_second(rig: Rig) -> None:
    rig.client.servo_confirms = False
    rig.upsert(do=False)
    assert rig.cmd("device_connect")["status"] == "ok"
    sup = rig.supervisor()
    assert rig.wait_event("servo", 1, HIT_S), "A4: окно недостижимо — SERVO не послан"
    time.sleep(0.2)
    reaction = _reaction_s(rig, sup)
    assert sup.join(JOIN_S)
    rig.drain()
    assert reaction < 0.5, f"A4(TLM): реакция {reaction:.2f} с, хотим < 0,5"
    assert rig.soft_count() == 1, f"A4(TLM): SOFT {rig.soft_count()}, хотим 1"


# --------------------------------------------------------------------------------------------------
# A5 — статусы прерванного connect (робот до этого не был подключён)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("window", ["transport_connect", "probe", "sync"])
def test_a5_interrupted_connect_statuses(rig: Rig, window: str) -> None:
    rig.upsert()
    gate, sup = _interrupt_at(rig, window)
    assert rig.cmd("device_disconnect")["status"] == "ok"
    _finish(rig, gate, sup)
    drv = rig.driver()
    observed = {
        "statuses": rig.proxy.statuses(),
        "desired": drv.desired_connected,
        "desired_at_connect_exit": drv.desired_at_connect_exit,
    }
    expected = {
        "statuses": ["connecting", "disconnecting", "disconnected"],
        "desired": False,
        "desired_at_connect_exit": [False],
    }
    assert observed == expected, f"A5[{window}]: {observed}"


def test_a5_pair_connect_without_command_statuses(rig: Rig) -> None:
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    rig.drain()
    assert rig.proxy.statuses() == ["connecting", "connected"], rig.proxy.statuses()
    assert rig.driver().desired_connected is True


# --------------------------------------------------------------------------------------------------
# A6 — «Подключить» -> команда -> «Подключить»
# --------------------------------------------------------------------------------------------------


def test_a6_connect_command_connect(rig: Rig) -> None:
    rig.upsert()
    gate, sup = _interrupt_at(rig, "probe")
    assert rig.cmd("device_disconnect")["status"] == "ok"
    assert rig.cmd("device_connect")["status"] == "ok"
    _finish(rig, gate, sup)
    drv = rig.driver()
    first_servo = rig.index_of("servo")
    first_disconnect = rig.index_of("disconnect_enter")
    observed = {
        "connect": drv.connect_results,
        "servo": rig.count("servo"),
        "servo_after_disconnect": first_disconnect != -1 and first_servo > first_disconnect,
        "soft": rig.soft_count(),
        "is_connected": drv.is_connected,
        "desired": drv.desired_connected,
    }
    expected = {
        "connect": [False, True],
        "servo": 1,
        "servo_after_disconnect": True,
        "soft": 1,
        "is_connected": True,
        "desired": True,
    }
    assert observed == expected, f"A6: {observed}"


# --------------------------------------------------------------------------------------------------
# A7 — тик переподключает, команда внутри probe тика
# --------------------------------------------------------------------------------------------------


def test_a7_tick_reconnect_interrupted_in_probe(rig: Rig) -> None:
    rig.upsert()
    drv = rig.connect_ready()
    gate = rig.arm("probe", TICK)
    rig.transport.drop()  # связь упала: тик пойдёт переподключать
    tick = rig.start_tick()
    assert gate.entered.wait(HIT_S), "A7: окно недостижимо — тик не дошёл до probe"
    assert gate.snapshot["probe"] == 2, f"A7: окно не то (probe при входе: {gate.snapshot.get('probe')})"
    mark = rig.mark()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    gate.release.set()
    rig.tick_stop.set()
    assert tick.join(JOIN_S), "A7: поток тика не вышел"
    rig.drain()
    observed = {
        "servo_after": rig.count("servo", mark),
        "do_after": rig.count("do", mark),
        "is_connected": drv.is_connected,
        "soft": rig.soft_count(),
        "transport_closed": not rig.transport.is_connected,
    }
    expected = {"servo_after": 0, "do_after": 0, "is_connected": False, "soft": 1, "transport_closed": True}
    assert observed == expected, f"A7: {observed}"


# --------------------------------------------------------------------------------------------------
# A8 — команда до того, как супервизор взял connect (драйвер ещё не создан)
# --------------------------------------------------------------------------------------------------


def test_a8_command_before_supervisor_took_connect(rig: Rig) -> None:
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    assert rig.cmd("device_disconnect")["status"] == "ok"
    rig.drain()
    observed = {"probe": rig.count("probe"), "servo": rig.count("servo"), "stop_req": rig.count("stop")}
    assert observed == {"probe": 0, "servo": 0, "stop_req": 0}, f"A8: {observed}"


def test_a8_pair_without_command_connect_reaches_robot(rig: Rig) -> None:
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    rig.drain()
    observed = {"probe": rig.count("probe"), "servo": rig.count("servo"), "stop_req": rig.count("stop")}
    assert observed == {"probe": 1, "servo": 1, "stop_req": 0}, f"A8-пара: {observed}"


# --------------------------------------------------------------------------------------------------
# A9 — ручной connect ждёт замок за переподключающимся тиком, затем команда
# --------------------------------------------------------------------------------------------------


def test_a9_manual_connect_waits_for_tick_lock_then_command(rig: Rig) -> None:
    rig.upsert()
    rig.connect_ready()
    gate = rig.arm("probe", TICK)
    rig.transport.drop()
    tick = rig.start_tick()
    assert gate.entered.wait(HIT_S), "A9: окно недостижимо — тик не дошёл до probe"
    assert rig.cmd("device_connect")["status"] == "ok"  # ручное «Подключить»
    sup = rig.supervisor()
    assert rig.wait_event("connect_enter", 2, HIT_S), "A9: ручной connect не вошёл в драйвер"
    time.sleep(0.2)
    assert sup.alive(), "A9: окно недостижимо — ручной connect не ждёт замок"
    mark = rig.mark()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    gate.release.set()
    rig.tick_stop.set()
    assert tick.join(JOIN_S), "A9: поток тика не вышел"
    assert sup.join(JOIN_S), "A9: ручной connect не вышел"
    rig.drain()
    observed = {
        "probe_after": rig.count("probe", mark),
        "servo_after": rig.count("servo", mark),
        "soft": rig.soft_count(),
    }
    assert observed == {"probe_after": 0, "servo_after": 0, "soft": 1}, f"A9: {observed}"


# --------------------------------------------------------------------------------------------------
# A10 / A11 / A14 — окно «команда пришла, очередь супервизора ещё не разобрана»
# --------------------------------------------------------------------------------------------------

_JOG_HOLD = {"dir": 1, "spd": 20}
_JOG_STEP = {"dx": 1.0, "dy": 0.0, "spd": 20}
_JOB = {"x_mm": 100.0, "y_mm": 50.0}
_REFUSED = {"status": "error", "message": TEXT_DISCONNECTING}


def test_a10_jog_refused_while_disconnecting(rig: Rig) -> None:
    rig.upsert()
    rig.connect_ready()
    mark = rig.mark()
    assert rig.cmd("device_disconnect")["status"] == "ok"  # очередь не разобрана
    hold = rig.cmd("robot_jog_hold", _JOG_HOLD)
    step = rig.cmd("robot_jog_step", _JOG_STEP)
    observed = {
        "hold": hold,
        "step": step,
        "jog_cont": rig.count("jog_cont", mark),
        "jog_step": rig.count("jog_step", mark),
    }
    assert observed == {"hold": _REFUSED, "step": _REFUSED, "jog_cont": 0, "jog_step": 0}, f"A10: {observed}"


def test_a10_pair_without_command_jog_reaches_robot(rig: Rig) -> None:
    rig.upsert()
    rig.connect_ready()
    mark = rig.mark()
    step = rig.cmd("robot_jog_step", _JOG_STEP)
    hold = rig.cmd("robot_jog_hold", _JOG_HOLD)
    assert step["status"] == "ok" and hold["status"] == "ok", (step, hold)
    assert rig.count("jog_cont", mark) == 1, f"A10-пара: JOG_CONT {rig.count('jog_cont', mark)}, хотим 1"
    assert rig.count("jog_step", mark) == 1, f"A10-пара: кадров jog {rig.count('jog_step', mark)}, хотим 1"
    assert rig.cmd("robot_jog_release")["status"] == "ok"


def test_a11_enqueue_job_refused_while_disconnecting(rig: Rig) -> None:
    rig.upsert()
    rig.connect_ready()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    res = rig.cmd("robot_enqueue_job", _JOB)
    assert res["status"] == "error" and res["message"] == TEXT_DISCONNECTING, f"A11: {res}"


def test_a11_pair_without_command_enqueue_ok(rig: Rig) -> None:
    rig.upsert()
    rig.connect_ready()
    res = rig.cmd("robot_enqueue_job", _JOB)
    assert res == {"status": "ok", "queue_len": 1}, f"A11-пара: {res}"


def test_a14_program_and_return_refused_while_disconnecting(rig: Rig) -> None:
    rig.upsert()
    rig.save_program()
    rig.connect_ready()
    mark = rig.mark()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    run = rig.cmd("robot_program_run", {"name": "p1"})
    ret = rig.cmd("robot_return_job", {"x_mm": 10.0, "y_mm": 20.0})
    time.sleep(0.3)  # поток программы, если бы запустился, успел бы дойти до run_chunks
    assert run["status"] == "error" and run["message"] == TEXT_DISCONNECTING, f"A14: program_run {run}"
    assert ret["status"] == "error" and ret["message"] == TEXT_DISCONNECTING, f"A14: return_job {ret}"
    assert rig.count("run_chunks", mark) == 0, "A14: программа дошла до робота"


def test_a14_pair_without_command_program_runs_and_return_queued(rig: Rig) -> None:
    rig.upsert()
    rig.save_program()
    rig.connect_ready()
    mark = rig.mark()
    run = rig.cmd("robot_program_run", {"name": "p1"})
    assert run["status"] == "ok", f"A14-пара: program_run {run}"
    assert rig.wait_event("run_chunks", 1, HIT_S), "A14-пара: программа не дошла до робота"
    ret = rig.cmd("robot_return_job", {"x_mm": 10.0, "y_mm": 20.0})
    assert ret == {"status": "ok", "return_queue_len": 1}, f"A14-пара: return_job {ret}"
    assert rig.count("run_chunks", mark) >= 1


# --------------------------------------------------------------------------------------------------
# A13 — В6: задания и возвраты, снятые при отключении
# --------------------------------------------------------------------------------------------------


def test_a13_queued_jobs_and_returns_dropped_on_disconnect(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.upsert()
    drv = rig.connect_ready()
    assert rig.cmd("robot_enqueue_job", _JOB) == {"status": "ok", "queue_len": 1}
    assert rig.cmd("robot_return_job", {"x_mm": 10.0, "y_mm": 20.0}) == {"status": "ok", "return_queue_len": 1}
    mark = rig.mark()
    with caplog.at_level(logging.WARNING):
        assert rig.cmd("device_disconnect")["status"] == "ok"
        rig.drain()
    time.sleep(0.2)
    warn = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and TEXT_DROPPED in r.getMessage()]
    last_error = [t for t in rig.proxy.texts(f"devices.state.{DEV}.last_error") if TEXT_DROPPED in t]
    observed = {
        "cvt_job_after": rig.count("cvt_job", mark),
        "run_chunks_after": rig.count("run_chunks", mark),
        "warning_logged": bool(warn),
        "last_error_has_text": bool(last_error),
    }
    expected = {"cvt_job_after": 0, "run_chunks_after": 0, "warning_logged": True, "last_error_has_text": True}
    assert observed == expected, f"A13: {observed}"
    # после «Подключить» очередь пуста: новое задание — первое
    assert rig.cmd("device_connect")["status"] == "ok"
    rig.drain()
    assert drv.is_connected
    assert rig.cmd("robot_enqueue_job", _JOB) == {"status": "ok", "queue_len": 1}


def test_a13_pair_without_command_tick_executes_job(rig: Rig) -> None:
    rig.upsert()
    drv = rig.connect_ready()
    assert rig.cmd("robot_enqueue_job", _JOB) == {"status": "ok", "queue_len": 1}
    mark = rig.mark()
    tick = rig.start(lambda: drv.tick(threading.Event()), "c29-tick-once")
    assert tick.join(JOIN_S), "A13-пара: тик не вернулся"
    assert rig.count("cvt_job", mark) == 1, f"A13-пара: заданий на фейке {rig.count('cvt_job', mark)}, хотим 1"


# --------------------------------------------------------------------------------------------------
# A15 — окно супервизора после connect против команды
# --------------------------------------------------------------------------------------------------


def _supervisor_connected_publications(make_rig: Callable[..., Rig]) -> int:
    """Нормальное подключение без команды: сколько раз супервизор (поток ``SUP``) публикует ``connected``."""
    rig = make_rig("dry")
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    sup = rig.supervisor()
    assert sup.join(JOIN_S)
    path = f"devices.state.{DEV}.conn"
    return sum(
        1
        for op, p, d, thread in rig.proxy.calls
        if op == "set" and p == path and isinstance(d, dict) and d.get("conn") == "connected" and thread == SUP
    )


def test_a15_command_returns_fast_while_supervisor_stands_before_publication(make_rig: Callable[..., Rig]) -> None:
    last = _supervisor_connected_publications(make_rig)
    assert last >= 1, "A15: супервизор не публикует connected — окно недостижимо"
    rig = make_rig("real")
    gate = Gate(rig, SUP)
    seen = [0]
    path = f"devices.state.{DEV}.conn"

    def hook(op: str, p: str, data: Any) -> None:
        if op == "set" and p == path and isinstance(data, dict) and data.get("conn") == "connected":
            if threading.current_thread().name == SUP:
                seen[0] += 1
                if seen[0] == last:  # последняя публикация статуса супервизором: connect уже завершён
                    gate.hit()

    rig.proxy.hook = hook
    rig.upsert()
    assert rig.cmd("device_connect")["status"] == "ok"
    sup = rig.supervisor()
    assert gate.entered.wait(HIT_S), "A15: окно недостижимо — супервизор не дошёл до публикации"
    assert sup.alive(), "A15: супервизор не стоит перед публикацией"
    t0 = time.monotonic()
    res = rig.cmd("device_disconnect", deadline_s=1.0)
    elapsed = time.monotonic() - t0
    desired_after_command = rig.driver().desired_connected
    gate.release.set()
    assert sup.join(JOIN_S)
    rig.drain()
    statuses = rig.proxy.statuses()
    observed = {
        "reply_status": res.get("status"),
        "fast": elapsed < 1.0,
        "desired_after_command": desired_after_command,
        "desired_final": rig.driver().desired_connected,
        "last_status": statuses[-1] if statuses else None,
        "soft": rig.soft_count(),
    }
    expected = {
        "reply_status": "ok",
        "fast": True,
        "desired_after_command": False,
        "desired_final": False,
        "last_status": "disconnected",
        "soft": 1,
    }
    assert observed == expected, f"A15: {observed}; statuses={statuses}"


# --------------------------------------------------------------------------------------------------
# A12 — регресс: простой подключённый робот
# --------------------------------------------------------------------------------------------------


def test_a12_regression_idle_connected_robot(rig: Rig) -> None:
    rig.upsert()
    drv = rig.connect_ready()
    mark = rig.mark()
    t0 = time.monotonic()
    assert rig.cmd("device_disconnect")["status"] == "ok"
    sup = rig.supervisor()
    assert rig.wait_event("disconnect_exit", 1, 1.0), "A12: disconnect драйвера не завершён за 1,0 с"
    elapsed = time.monotonic() - t0
    assert sup.join(JOIN_S)
    assert elapsed < 1.0, f"A12: disconnect за {elapsed:.2f} с"
    assert rig.soft_count(mark) == 1, f"A12: SOFT {rig.soft_count(mark)}, хотим 1"
    assert rig.cmd("device_connect")["status"] == "ok"
    rig.drain()
    assert drv.connect_results[-1] is True and drv.is_connected, f"A12: connect {drv.connect_results}"
    mark2 = rig.mark()
    hold = rig.cmd("robot_jog_hold", _JOG_HOLD)
    assert hold["status"] == "ok", f"A12: jog_hold {hold}"
    assert rig.count("jog_cont", mark2) == 1, "A12: jog_hold не дошёл до робота"
    assert rig.cmd("robot_jog_release")["status"] == "ok"
