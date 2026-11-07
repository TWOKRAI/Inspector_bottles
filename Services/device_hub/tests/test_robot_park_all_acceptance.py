"""Слепая приёмка T5.3e.5a (бриф 5t-a): ``DeviceManager.robot_park_all`` — основная остановка всех роботов v2.

Purpose:
    Строки ``plans/robot-protocol-v2/tasks/T5.3e.5a.acceptance.md`` (раздел ACCEPTANCE 5a) уровня менеджера и
    докстроки заглушек INTERFACE (``robot_park_all``, ``park_wait``, ``park_current_seq``, ``wait_terminal``).
    Источник требований — приёмка и докстроки, не тела прод-кода. Уровень плагина (команда, исполнитель, хук,
    роутер) — ``Plugins/hub/device_hub/tests/test_robot_park_all_plugin_acceptance.py``. Стенд v2 (P4, P5) — позже.

    Две обвязки. «Живая»: настоящий ``RobotDriverV2`` над ``E2eRig`` (sim по TCP), часы драйвера — ``FakeClock``,
    тик гонит фоновый поток; менеджер собран так, как велит докстрока ``robot_park_all`` (``register_driver_factory``
    до ``initialize()``, затем ``upsert`` и ``connect``). «Сценарная»: поддельный драйвер ``Scripted`` с ответами
    ``park`` / ``park_wait`` по сценарию — для веток ответа, которые на sim не вызвать (``refused``, ``error``,
    ``failed`` с шагом, пропуски, порядок). Наблюдаемое — ответ команды, ``seq`` park у драйвера, вызовы
    поддельного робота, позиция sim; приватные имена драйвера не читаются.

Public API:
    Только тесты ``test_*``.

Stability: lite

Допущения теста (не из приёмки буквально):
    * Тесты стопа не гонят тик: park принят и «идёт» (итога нет) без гонки со скоростью sim; итог ``failed`` ставит
      ``request_stop`` драйвера.
    * «Робот вне дома» — одна команда ``jog_step`` ``dx = 80`` (x = 380); дом — x = 300 (``P_HOME``, как в
      ``test_robot_v2_park_acceptance.py``).
    * Срок «ответ ≤ 1,0 с» при стопе меряется от момента, когда ``should_stop()`` истинен И ``request_stop`` драйвера
      вернулся (оба условия выполнены), до возврата ``robot_park_all``.
    * Нижняя граница ожидания (``timeout_s + 1,5`` минус 0,1; стоп: 0,25 при докстроке 0,5 — запас на момент
      опроса) выведена из ``deadline = t0 + timeout_s + 1.5`` и ``min(deadline, now + 0.5)``.
    * Таймерные пороги чувствительны к нагрузке машины: под тяжёлой нагрузкой возможны ложные красные.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.manager import DeviceManager
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

pytestmark = pytest.mark.timeout(90)

# --------------------------------------------------------------------------------------------------
# Литералы приёмки
# --------------------------------------------------------------------------------------------------

TEXT_STOP_HUB = "идёт остановка хаба"
TEXT_BAD_TIMEOUT = "timeout_s: число от 1 до 32"
TEXT_PARKING = "идёт основная остановка робота"
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_NOT_DONE = "основная остановка не выполнена: "
DEFAULT_TIMEOUT_S = 30.0
ANSWER_KEYS_OK = {"status", "timeout_s", "elapsed_s", "robots"}
DONE_KEYS = {"result", "seq", "home", "elapsed_s"}
HOME_X_MM = 300.0
OFF_HOME_X_MM = 380.0

_CALL_S = 15.0
_CONNECT_S = 60.0
_SCOPE_BUDGET_S = 6.0

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2parkall", budget_s=_SCOPE_BUDGET_S)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


# --------------------------------------------------------------------------------------------------
# Обвязка
# --------------------------------------------------------------------------------------------------


class SpyRobot(RobotDriverV2):
    """Настоящий драйвер v2; ``call("park", args)`` пишется в ``park_args`` и в общий ``order`` (порядок отправки)."""

    def __init__(self, *args: Any, order: list[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dev_id = args[0].id
        self.pub = kwargs.get("publish")
        self.park_args: list[dict] = []
        self.order = order

    def call(self, op: str, args: dict) -> dict:
        if op == "park":
            self.park_args.append(dict(args))
            self.order.append(self.dev_id)
        return super().call(op, args)


class Scripted(BaseDeviceDriver):
    """Поддельный робот по сценарию. ``calls`` — все вызовы ``call`` (``(op, args)``); ``waits`` — ``park_wait``."""

    kind = "robot"

    def __init__(self, entry: Any, protocol: Any = None, *, order: list[str] | None = None) -> None:
        super().__init__(entry, protocol)
        self.order = order if order is not None else []
        self.up = False
        self.calls: list[tuple[str, dict]] = []
        self.waits: list[tuple[int, float]] = []
        self.park_reply: dict = {"status": "ok", "accepted": True, "seq": 1, "timeout_s": DEFAULT_TIMEOUT_S}
        self.raises: Exception | None = None
        self.send_gate: threading.Event | None = None  # задан — отправка park не возвращается, пока тест не откроет
        self.terminal: dict | None = None  # None — терминала нет: park_wait ждёт весь срок и возвращает None
        self.current_seq = 7

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def connect(self) -> bool:
        self.up = True
        return True

    def disconnect(self) -> None:
        self.up = False

    @property
    def is_connected(self) -> bool:
        return self.up

    def tick(self, stop_event: Any = None) -> None:
        return None

    def call(self, op: str, args: dict) -> dict:
        self.calls.append((op, dict(args)))
        if op == "park":
            self.order.append(self.entry.id)
            if self.raises is not None:
                raise self.raises
            if self.send_gate is not None:
                self.send_gate.wait(10.0)
            return dict(self.park_reply)
        return {"status": "ok"}

    def park_current_seq(self) -> int:
        return self.current_seq

    def park_wait(self, seq: int, timeout_s: float) -> dict | None:
        self.waits.append((seq, timeout_s))
        if self.terminal is not None:
            return dict(self.terminal)
        time.sleep(min(max(timeout_s, 0.0), 5.0))
        return None

    def park_calls(self) -> list[dict]:
        return [a for op, a in self.calls if op == "park"]


def done_terminal(seq: int = 1, home: str = "moved", elapsed_s: float = 0.5) -> dict:
    return {
        "seq": seq,
        "state": "done",
        "step": "servo",
        "home": home,
        "servo": False,
        "dropped": {"jobs": 0, "returns": 0},
        "reason": None,
        "elapsed_s": elapsed_s,
    }


class Rec:
    """``publish`` драйвера: ``(путь, значение)`` по порядку."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))

    def at(self, dev_id: str, leaf: str) -> list[Any]:
        path = f"devices.state.{dev_id}.{leaf}"
        with self._lock:
            return [p for k, p in self._items if k == path]


class Hub:
    """``DeviceManager`` без плагина: фабрика ``robot`` берёт драйвер по ``entry.id`` из ``builders``."""

    def __init__(self, stack: ExitStack) -> None:
        self.stack = stack
        self.order: list[str] = []
        self.rec = Rec()
        self.builders: dict[str, Callable[[Any], Any]] = {}
        self.rigs: dict[str, E2eRig] = {}
        self.mgr = DeviceManager(None, self.rec, spawn=_SCOPE.spawn)
        self.mgr.register_driver_factory("robot", lambda entry, _protocol: self.builders[entry.id](entry))
        assert self.mgr.initialize() is True

    def driver(self, dev_id: str) -> Any:
        return self.mgr.get_driver(dev_id)

    def add_real(self, dev_id: str, *, connect: bool = True) -> SpyRobot:
        """Робот v2 на sim: запись реестра + настоящий драйвер; подключён и с желаемым состоянием «подключён»."""
        rig = self.stack.enter_context(E2eRig())
        self.rigs[dev_id] = rig
        clock = FakeClock()

        def build(entry: Any) -> SpyRobot:
            return SpyRobot(
                entry,
                clock=clock.clock,
                sleep=clock.sleep,
                publish=self.rec,
                spawn=_SCOPE.spawn,
                order=self.order,
            )

        self.builders[dev_id] = build
        self.mgr.upsert(
            {
                "id": dev_id,
                "name": dev_id,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        if connect:
            assert bounded(lambda: self.mgr.connect(dev_id), _CONNECT_S) is True
            drv = self.driver(dev_id)
            drv.desired_connected = True
            self.stack.callback(self._disconnect, drv)
            return drv
        return self.builders[dev_id](self.mgr.get(dev_id))  # type: ignore[return-value]

    @staticmethod
    def _disconnect(drv: Any) -> None:
        try:
            bounded(drv.disconnect, _CALL_S)
        except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
            pass

    def add_scripted(
        self, dev_id: str, *, protocol: str = "delta_v2", connect: bool = True, kind: str = "robot"
    ) -> Scripted:
        """Поддельный робот (v2 по умолчанию; ``protocol="delta_universal3"`` — v1) в реестре и менеджере."""
        holder: dict[str, Scripted] = {}

        def build(entry: Any) -> Scripted:
            drv = Scripted(entry, order=self.order)
            holder["drv"] = drv
            return drv

        self.builders[dev_id] = build
        self.mgr.upsert(
            {
                "id": dev_id,
                "name": dev_id,
                "kind": kind,
                "protocol": protocol,
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
            }
        )
        if connect:
            assert bounded(lambda: self.mgr.connect(dev_id), _CALL_S) is True
            return holder["drv"]
        return holder.get("drv")  # type: ignore[return-value]

    def off_home(self, dev_id: str) -> None:
        """Робот вне дома, простой: одна команда ``jog_step`` (+80 мм по X)."""
        drv, rig = self.driver(dev_id), self.rigs[dev_id]
        answer = bounded(lambda: drv.call("jog_step", {"dx": 80, "dy": 0, "spd": 50}), _CALL_S)
        assert answer["status"] == "ok", answer
        until(
            lambda: abs(rig.pose_wire()[0] - OFF_HOME_X_MM) <= 0.05 and rig.read("TLM_MOVING") == [0],
            10,
            "x == 380, стоит",
        )

    @contextmanager
    def ticking(self, *dev_ids: str) -> Iterator[None]:
        """Тик драйверов каждые 0,05 с реального времени (часы драйверов стоят: срок park не истекает)."""
        with ExitStack() as stack:
            for dev_id in dev_ids:
                stack.enter_context(pulse(self.driver(dev_id).tick, 0.05))
            yield

    def park_all(
        self, args: dict | None = None, *, should_stop: Callable[[], bool] | None = None, deadline_s: float = 20.0
    ) -> tuple[dict, float]:
        """``robot_park_all`` в daemon-потоке; (ответ, секунды)."""
        t0 = time.monotonic()
        if should_stop is None:
            answer = bounded(lambda: self.mgr.robot_park_all(dict(args or {})), deadline_s)
        else:
            answer = bounded(lambda: self.mgr.robot_park_all(dict(args or {}), should_stop=should_stop), deadline_s)
        return answer, time.monotonic() - t0


@contextmanager
def hub() -> Iterator[Hub]:
    with ExitStack() as stack:
        yield Hub(stack)


def until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


class BackgroundCall:
    """``robot_park_all`` в daemon-потоке; ``wait`` даёт (ответ, момент возврата)."""

    def __init__(self, h: Hub, args: dict, should_stop: Callable[[], bool]) -> None:
        self.box: dict[str, Any] = {}

        def body() -> None:
            try:
                self.box["answer"] = h.mgr.robot_park_all(dict(args), should_stop=should_stop)
            except BaseException as exc:  # noqa: BLE001 — уходит в поток теста
                self.box["error"] = exc
            self.box["t_end"] = time.monotonic()

        self.thread = threading.Thread(target=body, name="park-all-call", daemon=True)
        self.thread.start()

    def until(self, pred: Callable[[], object], deadline_s: float, what: str) -> None:
        """Ждать условие; упала сама команда — поднять её исключение (причина красного видна, не таймаут)."""
        end = time.monotonic() + deadline_s
        while not pred():
            if "error" in self.box:
                raise self.box["error"]
            if time.monotonic() >= end:
                raise AssertionError(f"не дождались за {deadline_s} с: {what}")
            time.sleep(0.02)

    def wait(self, deadline_s: float = 10.0) -> tuple[dict, float]:
        self.thread.join(deadline_s)
        assert not self.thread.is_alive(), f"robot_park_all не вернулся за {deadline_s} с"
        if "error" in self.box:
            raise self.box["error"]
        return self.box["answer"], self.box["t_end"]


# --------------------------------------------------------------------------------------------------
# Контроль обвязки: зелёные на текущем коде (реализация не нужна)
# --------------------------------------------------------------------------------------------------


def test_harness_manager_with_real_robot_v2_connects() -> None:
    """Контроль: менеджер собран по докстроке, робот v2 подключён, драйвер — настоящий."""
    with hub() as h:
        drv = h.add_real("r1")
        assert isinstance(drv, RobotDriverV2)
        assert drv.is_connected is True
        assert h.mgr.get_driver("r1") is drv


def test_harness_operator_park_via_driver_call_returns_answer() -> None:
    """Контроль: park оператора ``drv.call("park", ...)`` отвечает литералом приёмки park (seq 1, 30.0)."""
    with hub() as h:
        drv = h.add_real("r1")
        reply = bounded(lambda: drv.call("park", {}), _CALL_S)
        assert reply == {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 30.0}


# --------------------------------------------------------------------------------------------------
# Все роботы дома; повтор
# --------------------------------------------------------------------------------------------------


def test_all_robots_done_moved_with_exact_answer_shape() -> None:
    """Два робота вне дома: ``ok``, ``timeout_s`` 30.0, у каждого ``done``/``seq 1``/``moved``; робот физически дома."""
    with hub() as h:
        h.add_real("ra")
        h.add_real("rb")
        h.off_home("ra")
        h.off_home("rb")
        with h.ticking("ra", "rb"):
            answer, _ = h.park_all({})
        assert set(answer) == ANSWER_KEYS_OK, answer
        assert answer["status"] == "ok", answer
        assert answer["timeout_s"] == 30.0 and type(answer["timeout_s"]) is float
        assert isinstance(answer["elapsed_s"], float), answer
        assert set(answer["robots"]) == {"ra", "rb"}, answer
        for dev_id in ("ra", "rb"):
            robot = answer["robots"][dev_id]
            assert set(robot) == DONE_KEYS, robot
            assert (robot["result"], robot["seq"], robot["home"]) == ("done", 1, "moved"), robot
            assert isinstance(robot["elapsed_s"], float), robot
            assert abs(h.rigs[dev_id].pose_wire()[0] - HOME_X_MM) <= 0.5, h.rigs[dev_id].pose_wire()


def test_empty_registry_ok_with_no_robots() -> None:
    """Роботов нет: ``ok``, ``robots: {}``, ``timeout_s`` 30.0 (умолчание)."""
    with hub() as h:
        answer, _ = h.park_all({})
        assert set(answer) == ANSWER_KEYS_OK, answer
        assert (answer["status"], answer["timeout_s"], answer["robots"]) == ("ok", 30.0, {})


def test_repeat_after_done_is_already_and_ok() -> None:
    """Повтор ``robot_park_all`` после ``done``: ``home "already"``, новый ``seq 2``, ``status "ok"``."""
    with hub() as h:
        h.add_real("r1")
        h.off_home("r1")
        with h.ticking("r1"):
            first, _ = h.park_all({})
            second, _ = h.park_all({})
        assert first["robots"]["r1"]["home"] == "moved", first
        robot = second["robots"]["r1"]
        assert second["status"] == "ok", second
        assert (robot["result"], robot["seq"], robot["home"]) == ("done", 2, "already"), robot


def test_park_sent_to_robots_in_ascending_id_order() -> None:
    """Порядок отправки — по возрастанию ``id``, хотя реестр заполнен в обратном порядке."""
    with hub() as h:
        for dev_id in ("rc", "ra", "rb"):
            drv = h.add_scripted(dev_id)
            drv.terminal = done_terminal()
        answer, _ = h.park_all({})
        assert h.order == ["ra", "rb", "rc"], h.order
        assert answer["status"] == "ok", answer
        assert list(answer["robots"]) == ["ra", "rb", "rc"] or set(answer["robots"]) == {"ra", "rb", "rc"}


def test_only_robot_kind_entries_are_listed() -> None:
    """Запись вида ``vfd`` в ``robots`` не попадает (по одному ``R`` на каждого робота реестра)."""
    with hub() as h:
        h.add_scripted("ra").terminal = done_terminal()
        h.add_scripted("vfd1", protocol="gd20_bridge", connect=False, kind="vfd")
        answer, _ = h.park_all({})
        assert set(answer["robots"]) == {"ra"}, answer


# --------------------------------------------------------------------------------------------------
# timeout_s
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0.5, 0.99, 32.01, 33, True, False, "30", None])
def test_bad_timeout_is_refused_and_robots_untouched(bad: Any) -> None:
    """``timeout_s`` вне [1, 32], не число, ``bool``, строка: постоянный текст; park не отправлен."""
    with hub() as h:
        robot = h.add_scripted("ra")
        robot.terminal = done_terminal()
        real = h.add_real("rb")
        answer, _ = h.park_all({"timeout_s": bad})
        assert answer == {"status": "error", "message": TEXT_BAD_TIMEOUT}, answer
        assert robot.calls == [], robot.calls
        assert real.park_args == [], real.park_args
        assert h.rec.at("rb", "park") == [], "у робота появилась публикация park"


@pytest.mark.parametrize("good", [1, 1.0, 32, 32.0, 5, 5.5])
def test_good_timeout_is_accepted_and_returned_as_float(good: Any) -> None:
    """Границы 1 и 32 включены; в ответе ``timeout_s`` — ``float`` (целое ``30`` -> ``30.0``)."""
    with hub() as h:
        answer, _ = h.park_all({"timeout_s": good})
        assert answer["status"] == "ok", answer
        assert answer["timeout_s"] == float(good) and type(answer["timeout_s"]) is float, answer


def test_timeout_is_forwarded_to_park_as_float_and_other_keys_ignored() -> None:
    """Целое ``5`` уходит в ``park`` как ``5.0``; без ключа — ``30.0``; лишние ключи игнорируются."""
    with hub() as h:
        robot = h.add_scripted("ra")
        robot.terminal = done_terminal()
        answer, _ = h.park_all({"timeout_s": 5, "extra": "x"})
        assert answer["status"] == "ok" and answer["timeout_s"] == 5.0, answer
        sent = robot.park_calls()
        assert sent == [{"timeout_s": 5.0}] and type(sent[0]["timeout_s"]) is float, sent
        h.park_all({})
        assert robot.park_calls()[-1] == {"timeout_s": 30.0}, robot.park_calls()


# --------------------------------------------------------------------------------------------------
# Робот без итога
# --------------------------------------------------------------------------------------------------


def test_robot_without_terminal_times_out_within_bounds() -> None:
    """Park без тика (итога нет), ``timeout_s 1.0``: ответ в [2,4; 2,9] с, ``timeout``, ``error``, текст с id."""
    with hub() as h:
        drv = h.add_real("r1")
        answer, took = h.park_all({"timeout_s": 1.0})
        assert took <= 2.9, took
        assert took >= 2.4, f"ответ раньше срока timeout_s + 1,5 с: {took}"
        assert answer["status"] == "error", answer
        assert answer["message"] == TEXT_NOT_DONE + "r1", answer
        assert answer["timeout_s"] == 1.0, answer
        assert answer["robots"]["r1"] == {"result": "timeout", "seq": 1}, answer
        assert drv.park_args == [{"timeout_s": 1.0}], drv.park_args


def test_several_failures_listed_ascending_and_mapped_per_result_kind() -> None:
    """Ветки ``failed`` / ``refused`` / ``error`` / ``timeout``: форма ``R``; ``message`` — id по возрастанию."""
    with hub() as h:
        h.add_scripted("a_ok").terminal = done_terminal(home="already")
        failed = h.add_scripted("b_failed")
        failed.terminal = {
            **done_terminal(),
            "state": "failed",
            "step": "home",
            "home": None,
            "servo": None,
            "reason": "срок вышел",
            "elapsed_s": None,
        }
        refused = h.add_scripted("c_refused")
        refused.park_reply = {"status": "error", "message": "идёт отключение робота"}
        broken = h.add_scripted("d_error")
        broken.raises = RuntimeError("boom")
        h.add_scripted("e_ok").terminal = done_terminal()
        h.add_scripted("z_timeout")  # итога нет: ждёт весь срок
        answer, took = h.park_all({"timeout_s": 1.0})
        robots = answer["robots"]
        assert answer["status"] == "error", answer
        assert answer["message"] == TEXT_NOT_DONE + "b_failed, c_refused, d_error, z_timeout", answer
        assert robots["a_ok"]["result"] == "done" and robots["a_ok"]["home"] == "already", robots
        assert robots["b_failed"] == {"result": "failed", "seq": 1, "step": "home", "reason": "срок вышел"}, robots
        assert robots["c_refused"] == {"result": "refused", "message": "идёт отключение робота"}, robots
        assert robots["d_error"] == {"result": "error", "message": "RuntimeError: boom"}, robots
        assert robots["e_ok"]["result"] == "done", robots
        assert robots["z_timeout"] == {"result": "timeout", "seq": 1}, robots
        assert took <= 2.9, took


def test_send_longer_than_deadline_marks_next_robot_no_time() -> None:
    """Отправка первому дольше срока (``timeout_s 1.0`` -> 2,5 с): второму ``skipped/no_time``, park ему не уходит."""
    with hub() as h:
        first = h.add_scripted("ra")
        first.send_gate = threading.Event()
        second = h.add_scripted("rb")
        second.terminal = done_terminal()
        call = BackgroundCall(h, {"timeout_s": 1.0}, lambda: False)
        try:
            call.until(lambda: len(first.park_calls()) == 1, 5, "хаб послал park первому")
            time.sleep(2.7)  # срок t0 + 1,0 + 1,5 вышел, отправка первому всё ещё идёт
        finally:
            first.send_gate.set()
        answer, _ = call.wait()
        assert answer["robots"]["rb"] == {"result": "skipped", "reason": "no_time"}, answer
        assert second.calls == [], second.calls
        assert answer["robots"]["ra"] == {"result": "timeout", "seq": 1}, answer
        assert answer["status"] == "error", answer
        assert answer["message"] == TEXT_NOT_DONE + "ra, rb", answer


# --------------------------------------------------------------------------------------------------
# Пропуски: v1, нет связи
# --------------------------------------------------------------------------------------------------


def test_v1_robot_connected_or_not_is_skipped_not_v2_and_untouched() -> None:
    """Робот v1 (подключённый и нет) -> ``skipped/not_v2``, вызовов нет, ``status "ok"``."""
    with hub() as h:
        up = h.add_scripted("v1_up", protocol="delta_universal3")
        down = h.add_scripted("v1_down", protocol="delta_universal3", connect=False)
        answer, _ = h.park_all({})
        assert answer["status"] == "ok", answer
        assert answer["robots"] == {
            "v1_down": {"result": "skipped", "reason": "not_v2"},
            "v1_up": {"result": "skipped", "reason": "not_v2"},
        }, answer
        assert up.calls == [] and up.waits == [], up.calls
        assert down is None or down.calls == []


def test_v2_without_link_is_skipped_not_connected_and_untouched() -> None:
    """Робот v2 без драйвера и робот v2 с отключённым драйвером -> ``skipped/not_connected``; ``status "ok"``."""
    with hub() as h:
        never = h.add_scripted("r_never", connect=False)
        gone = h.add_scripted("r_gone")
        h.mgr.disconnect("r_gone")
        assert gone.is_connected is False
        answer, _ = h.park_all({})
        assert answer["status"] == "ok", answer
        assert answer["robots"] == {
            "r_gone": {"result": "skipped", "reason": "not_connected"},
            "r_never": {"result": "skipped", "reason": "not_connected"},
        }, answer
        assert gone.calls == [], gone.calls
        assert never is None or never.calls == []


def test_skipped_robots_do_not_block_connected_one() -> None:
    """Рядом с пропущенными подключённый v2 доходит до ``done``; ``status "ok"``."""
    with hub() as h:
        h.add_scripted("a_v1", protocol="delta_universal3")
        h.add_scripted("b_down", connect=False)
        h.add_scripted("c_up").terminal = done_terminal()
        answer, _ = h.park_all({})
        assert answer["status"] == "ok", answer
        assert answer["robots"]["c_up"]["result"] == "done", answer
        assert answer["robots"]["a_v1"]["reason"] == "not_v2", answer
        assert answer["robots"]["b_down"]["reason"] == "not_connected", answer


# --------------------------------------------------------------------------------------------------
# Присоединение к park оператора
# --------------------------------------------------------------------------------------------------


def test_joined_to_operator_park_live() -> None:
    """Park оператора идёт: ответ несёт его ``seq`` и ``"joined": True``; новый park не начат; итог ``done``."""
    with hub() as h:
        drv = h.add_real("r1")
        h.off_home("r1")
        operator = bounded(lambda: drv.call("park", {}), _CALL_S)
        assert operator["accepted"] is True and operator["seq"] == 1, operator
        call = BackgroundCall(h, {}, lambda: False)
        call.until(lambda: drv.park_args[1:] == [{"timeout_s": 30.0}], 5, "хаб послал park")
        with h.ticking("r1"):
            answer, _ = call.wait()
        robot = answer["robots"]["r1"]
        assert answer["status"] == "ok", answer
        assert (robot["result"], robot["seq"], robot["home"], robot["joined"]) == ("done", 1, "moved", True), robot
        assert {p["seq"] for p in h.rec.at("r1", "park")} == {1}, "хаб начал новый park вместо присоединения"


def test_joined_uses_current_seq_of_running_operator_park() -> None:
    """Отказ «идёт основная остановка робота» -> хаб ждёт ``park_current_seq()`` (7); в ``R`` ``joined: True``."""
    with hub() as h:
        robot = h.add_scripted("r1")
        robot.park_reply = {"status": "error", "message": TEXT_PARKING}
        robot.current_seq = 7
        robot.terminal = done_terminal(seq=7, home="already")
        answer, _ = h.park_all({})
        assert answer["status"] == "ok", answer
        got = answer["robots"]["r1"]
        assert (got["result"], got["seq"], got["home"], got["joined"]) == ("done", 7, "already", True), got
        assert [seq for seq, _ in robot.waits][-1] == 7, robot.waits


def test_other_refusal_is_refused_not_joined() -> None:
    """Любой иной отказ ``park`` — ``refused`` с текстом отказа, без ``joined``; ``status "error"``."""
    with hub() as h:
        robot = h.add_scripted("r1")
        robot.park_reply = {"status": "error", "message": "идёт отключение робота"}
        answer, _ = h.park_all({})
        assert answer["status"] == "error", answer
        assert answer["robots"]["r1"] == {"result": "refused", "message": "идёт отключение робота"}, answer
        assert answer["message"] == TEXT_NOT_DONE + "r1", answer
        assert robot.waits == [], robot.waits


# --------------------------------------------------------------------------------------------------
# Стоп процесса
# --------------------------------------------------------------------------------------------------


def test_should_stop_on_entry_refuses_whole_command_before_timeout_check() -> None:
    """``should_stop()`` истинен на входе: «идёт остановка хаба» (раньше проверки ``timeout_s``); роботы не тронуты."""
    with hub() as h:
        robot = h.add_scripted("ra")
        real = h.add_real("rb")
        answer, took = h.park_all({"timeout_s": 99}, should_stop=lambda: True)
        assert answer == {"status": "error", "message": TEXT_STOP_HUB}, answer
        assert robot.calls == [] and real.park_args == [], (robot.calls, real.park_args)
        assert took < 1.0, took


def test_stop_during_first_send_skips_next_robots_as_stopping() -> None:
    """Стоп во время отправки первому: следующим ``skipped/stopping``, park им не отправлен, ``error``."""
    with hub() as h:
        first = h.add_scripted("ra")
        first.send_gate = threading.Event()
        first.terminal = done_terminal()
        second = h.add_scripted("rb")
        third = h.add_scripted("rc")
        stop = threading.Event()
        call = BackgroundCall(h, {}, stop.is_set)
        try:
            call.until(lambda: len(first.park_calls()) == 1, 5, "хаб послал park первому")
            stop.set()  # процесс останавливается, пока идёт отправка первому
        finally:
            first.send_gate.set()
        answer, _ = call.wait()
        assert len(first.park_calls()) == 1, first.calls
        assert answer["robots"]["rb"] == {"result": "skipped", "reason": "stopping"}, answer
        assert answer["robots"]["rc"] == {"result": "skipped", "reason": "stopping"}, answer
        assert second.calls == [] and third.calls == [], (second.calls, third.calls)
        assert answer["status"] == "error", answer
        assert answer["message"].startswith(TEXT_NOT_DONE) and answer["message"].endswith("rb, rc"), answer


@pytest.mark.parametrize("request_stop_delay_s", [0.0, 0.25])
def test_stop_during_wait_gives_failed_by_driver_stop_within_one_second(request_stop_delay_s: float) -> None:
    """Стоп в ожидании (записан ≤ 0,5 с): ответ ≤ 1,0 с, ``failed``, ``reason "драйвер робота останавливается"``."""
    with hub() as h:
        drv = h.add_real("r1")
        stop = threading.Event()
        with h.ticking():  # тика нет: park принят и идёт, итога нет — состояние не зависит от скорости sim
            call = BackgroundCall(h, {}, stop.is_set)
            call.until(lambda: drv.park_args == [{"timeout_s": 30.0}], 5, "хаб послал park")
            time.sleep(0.3)  # хаб в ожидании итога, отправки нет
            stop.set()
            time.sleep(request_stop_delay_s)
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), _CALL_S)
            t_stop = time.monotonic()
            answer, t_end = call.wait()
        assert t_end - t_stop <= 1.0, t_end - t_stop
        robot = answer["robots"]["r1"]
        assert answer["status"] == "error", answer
        assert (robot["result"], robot["seq"], robot["reason"]) == ("failed", 1, TEXT_STOPPING), robot
        assert isinstance(robot["step"], str), robot
        assert answer["message"] == TEXT_NOT_DONE + "r1", answer


def test_stop_written_late_gives_timeout_within_one_second_of_the_flag() -> None:
    """Стоп записан позже: ``timeout``, ``status "error"``; ответ в [0,25; 1,0] с от момента, когда стоп истинен."""
    with hub() as h:
        drv = h.add_real("r1")
        stop = threading.Event()
        with h.ticking():  # тика нет: park принят и идёт, итога нет — состояние не зависит от скорости sim
            call = BackgroundCall(h, {}, stop.is_set)
            call.until(lambda: drv.park_args == [{"timeout_s": 30.0}], 5, "хаб послал park")
            time.sleep(0.3)
            stop.set()
            t_stop = time.monotonic()
            answer, t_end = call.wait()
            # park робота идёт дальше: уборка стенда его остановит
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), _CALL_S)
        assert t_end - t_stop <= 1.0, t_end - t_stop
        assert t_end - t_stop >= 0.25, f"ответ раньше, чем через ~0,5 с после стопа: {t_end - t_stop}"
        assert answer["status"] == "error", answer
        assert answer["robots"]["r1"] == {"result": "timeout", "seq": 1}, answer
        assert answer["message"] == TEXT_NOT_DONE + "r1", answer
