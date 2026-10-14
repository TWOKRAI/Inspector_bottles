"""Тесты автора T5.1: опасные места ``RobotDriverV2`` — гонки jog, выход потока поводка, отключение при программе.

Purpose:
    Дополняют слепую приёмку (``test_robot_driver_v2_acceptance.py``) свойствами потоков: ``jog_hold``, заставший
    стоп в полёте, ждёт его и стартует новый ``JOG_CONT`` без NAK; исключение в потоке поводка снимает jog и не
    блокирует переподключение; ``disconnect`` во время программы прерывает её и дожидается потоков. Плюс разбор
    блока телеметрии на литералах. Эффекты проверяются в sim (строки событий, тики), не по именам методов.

Public API:
    Только тесты ``test_*``.

Stability: lite

Каждый блокирующий вызов — через ``bounded`` (daemon-поток + дедлайн): тест падает, набор не висит.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2, _parse_tlm
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

_JOG = {"dir": 1, "spd": 20}
_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0
_GATE_S = 2.0  # дедлайн ворот стопа release в гонке jog_hold (U2)
_CMD_JOG = re.compile(r"\[v2\] CMD seq=(\d+) op=JOG_CONT")
TEXT_JOG_LOST = "поводок jog прерван: нет связи с роботом"


class _Rec:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))

    def at(self, dev_id: str, leaf: str) -> list[Any]:
        path = f"devices.state.{dev_id}.{leaf}"
        with self._lock:
            return [payload for p, payload in self._items if p == path]


@contextmanager
def _driver(rec: _Rec, port: int, params: dict | None = None) -> Iterator[RobotDriverV2]:
    entry = DeviceEntry(
        id="rv2",
        name="rv2",
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        params=dict(params or {}),
    )
    drv = RobotDriverV2(entry, None, publish=rec)
    try:
        assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
        drv.desired_connected = True
        yield drv
    finally:
        try:
            bounded(drv.disconnect, _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
            pass


def _call(drv: RobotDriverV2, op: str, args: dict | None = None) -> dict:
    return bounded(lambda: drv.call(op, dict(args or {})), _CALL_DEADLINE_S)


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _hold(drv: RobotDriverV2, duration_s: float) -> None:
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        time.sleep(0.05)


def _jog_cmds(rig: E2eRig) -> list[int]:
    return [int(m.group(1)) for _, text in rig.core.events() if (m := _CMD_JOG.search(text))]


def _moving(rig: E2eRig) -> int:
    return rig.core.ticks()[-1].moving


# --------------------------------------------------------------------------------------------------
# Без sim: разбор блока телеметрии
# --------------------------------------------------------------------------------------------------


def test_parse_tlm_signed_pose_and_little_endian_encoder() -> None:
    from Services.robot_comm.core.protocol_v2 import REG

    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_X"] - base] = 0xF830  # -2000 -> -200.0 мм
    words[REG["TLM_RZ"] - base] = 905  # 90.5°
    words[REG["TLM_ENC"] - base] = 0xFFFE  # младшее слово первым
    words[REG["TLM_ENC"] - base + 1] = 0xFFFF  # -> s32 = -2
    words[REG["TLM_ACTIVITY"] - base] = 1
    words[REG["TLM_SERVO"] - base] = 1
    telemetry, free, encoder = _parse_tlm(words)
    assert telemetry["x_mm"] == -200.0
    assert telemetry["rz_deg"] == 90.5
    assert telemetry["servo"] is True
    assert telemetry["moving"] is False
    assert free is False
    assert encoder == -2


# --------------------------------------------------------------------------------------------------
# Гонка: jog_hold во время стопа в полёте
# --------------------------------------------------------------------------------------------------


def test_jog_hold_during_stop_in_flight_starts_new_jog_without_nak() -> None:
    """Стоп ``jog_release`` в полёте (задержан ДО записи); ``jog_hold`` в это окно. Новый jog обязан выжить.

    Порядок задан событиями, не сном. Шов — ТОЛЬКО стоп release: он ждёт ворота ``gate``, а ворота открывает
    возврат нового ``JOG_CONT``. Остальные вызовы ``stop`` идут без задержки (прежний шов задерживал КАЖДЫЙ
    ``stop`` одинаково, и запасной стоп ``jog_hold`` вставал в очередь за стопом release — тест не видел
    снятия замка, находка Ф1). С замком перехода ``jog_hold`` ждёт замок, стоп release уходит по дедлайну ворот,
    затем новый ``JOG_CONT``. Без замка ``jog_hold`` сам шлёт стоп (запасной путь), шлёт ``JOG_CONT``,
    ворота открываются, и запоздалый стоп release приходит ПОСЛЕ нового ``JOG_CONT`` и обрывает новый jog.

    Ждём в sim: новый ``JOG_CONT`` принят (строка CMD), для его seq нет строки ``ERR ... E_ABORTED``, робот
    движется, пока удержание подтверждается. Плюс: ``jog_hold`` вернулся не раньше стопа release.
    """
    rec = _Rec()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _hold(drv, 0.4)
        assert _moving(rig) == 1
        n_cmd = len(_jog_cmds(rig))

        client = drv._client
        real_stop = client.stop
        real_jog_cont = client.jog_cont
        entered = threading.Event()
        gate = threading.Event()
        first = threading.Lock()
        stamps: dict[str, float] = {}

        def gated_stop(level: int) -> Any:
            if not first.acquire(blocking=False):
                return real_stop(level)  # не стоп release (запасной стоп jog_hold и др.) — без задержки
            entered.set()
            # Стоп release «в полёте». С замком перехода ворота не откроются (JOG_CONT ждёт этот стоп) —
            # дедлайн отпускает стоп; исход от длины дедлайна не зависит. Без замка ворота открывает JOG_CONT.
            gate.wait(_GATE_S)
            result = real_stop(level)
            stamps["stop_returned"] = time.monotonic()
            return result

        def jog_cont_then_open(direction: int, speed: int) -> Any:
            result = real_jog_cont(direction, speed)
            gate.set()
            return result

        client.stop = gated_stop  # type: ignore[method-assign]
        client.jog_cont = jog_cont_then_open  # type: ignore[method-assign]
        try:
            box: dict[str, Any] = {}
            releaser = threading.Thread(target=lambda: box.setdefault("rel", drv.call("jog_release", {})), daemon=True)
            releaser.start()
            assert entered.wait(5.0), "стоп release не начался"
            hold = _call(drv, "jog_hold", _JOG)
            stamps["hold_returned"] = time.monotonic()
            releaser.join(_CALL_DEADLINE_S)
            assert not releaser.is_alive()
        finally:
            client.stop = real_stop  # type: ignore[method-assign]
            client.jog_cont = real_jog_cont  # type: ignore[method-assign]

        assert box["rel"] == {"status": "ok"}
        assert hold["status"] == "ok", hold
        assert len(_jog_cmds(rig)) == n_cmd + 1, "новый JOG_CONT не принят роботом"
        new_seq = hold["seq"]
        _hold(drv, 0.4)
        aborted = [text for _, text in rig.core.events() if f"[v2] ERR seq={new_seq} " in text]
        assert aborted == [], f"новый jog оборван запоздалым стопом release: {aborted}"
        assert _moving(rig) == 1, "новый jog не двигает робот"
        assert stamps["hold_returned"] >= stamps["stop_returned"], "JOG_CONT ушёл раньше, чем вернулся стоп"
        assert _call(drv, "jog_release")["status"] == "ok"


def test_jog_hold_during_expired_window_stop_in_flight_starts_new_jog() -> None:
    """Близнец U2 на пути истёкшего окна (Д3): стоп шлёт поток поводка, ``jog_hold`` застаёт его в полёте.

    Подтверждения удержания прекращены — окно истекает, поток поводка шлёт стоп под замком перехода. Шов — ТОЛЬКО
    стоп из потока поводка (имя потока ``rv2-lease-...``): он ждёт ворота, ворота открывает возврат нового
    ``JOG_CONT``. С замком ``jog_hold`` ждёт замок, стоп уходит по дедлайну ворот, затем ``JOG_CONT``. Без замка
    на стороне поводка ``jog_hold`` шлёт запасной стоп и ``JOG_CONT``, запоздалый стоп поводка обрывает новый jog,
    а тик публикует чужую ошибку обрыва (seq нового jog не в списке своих стопов).

    Ждём в sim: новый ``JOG_CONT`` принят, для его seq нет строки ``ERR``, робот движется; новых
    ``last_error`` за гонку нет; ``jog_hold`` вернулся не раньше стопа поводка.
    """
    rec = _Rec()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _hold(drv, 0.4)
        assert _moving(rig) == 1
        n_cmd = len(_jog_cmds(rig))
        n_err = len(rec.at("rv2", "last_error"))

        client = drv._client
        real_stop = client.stop
        real_jog_cont = client.jog_cont
        entered = threading.Event()
        gate = threading.Event()
        first = threading.Lock()
        stamps: dict[str, float] = {}

        def gated_stop(level: int) -> Any:
            if not threading.current_thread().name.startswith("rv2-lease-") or not first.acquire(blocking=False):
                return real_stop(level)  # не стоп потока поводка — без задержки
            entered.set()
            gate.wait(_GATE_S)  # с замком ворота не откроются (JOG_CONT ждёт этот стоп) — отпускает дедлайн
            result = real_stop(level)
            stamps["stop_returned"] = time.monotonic()
            return result

        def jog_cont_then_open(direction: int, speed: int) -> Any:
            result = real_jog_cont(direction, speed)
            gate.set()
            return result

        client.stop = gated_stop  # type: ignore[method-assign]
        client.jog_cont = jog_cont_then_open  # type: ignore[method-assign]
        try:
            # подтверждений нет: окно 0.2 с истекает, поток поводка сам шлёт стоп
            assert entered.wait(5.0), "стоп истёкшего окна не начался"
            hold = _call(drv, "jog_hold", _JOG)
            stamps["hold_returned"] = time.monotonic()
        finally:
            client.stop = real_stop  # type: ignore[method-assign]
            client.jog_cont = real_jog_cont  # type: ignore[method-assign]

        assert hold["status"] == "ok", hold
        assert len(_jog_cmds(rig)) == n_cmd + 1, "новый JOG_CONT не принят роботом"
        new_seq = hold["seq"]
        _hold(drv, 0.4)
        aborted = [text for _, text in rig.core.events() if f"[v2] ERR seq={new_seq} " in text]
        assert aborted == [], f"новый jog оборван запоздалым стопом окна: {aborted}"
        assert rec.at("rv2", "last_error")[n_err:] == [], "чужая ошибка обрыва в last_error"
        assert _moving(rig) == 1, "новый jog не двигает робот"
        assert stamps["hold_returned"] >= stamps["stop_returned"], "JOG_CONT ушёл раньше, чем вернулся стоп окна"
        assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# Д4: start_program во время перехода jog
# --------------------------------------------------------------------------------------------------


def test_start_program_during_jog_hold_transition_returns_busy_jog() -> None:
    """``start_program`` в окне ``jog_hold`` между проверкой флагов и записью ``self._jog`` (Д4).

    Шов: обёртка ``client.jog_cont`` зовёт ``start_program`` ДО настоящего ``JOG_CONT`` — ``jog_hold`` уже прошёл
    проверку ``_busy``, но свой jog ещё не записал. Ждём: ``start_program`` отказывает литералом «робот в режиме
    jog», в sim нет строки ``SC start`` (программа не запущена), новый jog принят и двигает робот.
    """
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    program = Program(name="race", steps=tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(4)))
    rec = _Rec()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        client = drv._client
        real_jog_cont = client.jog_cont
        box: dict[str, Any] = {}

        def jog_cont_with_program(direction: int, speed: int) -> Any:
            box["prog"] = drv.start_program(program, points, None, name="race")
            return real_jog_cont(direction, speed)

        client.jog_cont = jog_cont_with_program  # type: ignore[method-assign]
        try:
            n_cmd = len(_jog_cmds(rig))
            hold = _call(drv, "jog_hold", _JOG)
        finally:
            client.jog_cont = real_jog_cont  # type: ignore[method-assign]

        assert box["prog"] == {"status": "error", "message": "робот в режиме jog"}
        assert hold["status"] == "ok", hold
        _hold(drv, 0.4)
        assert [t for _, t in rig.core.events() if "[v2] SC start" in t] == [], "программа запущена во время jog"
        assert len(_jog_cmds(rig)) == n_cmd + 1
        assert _moving(rig) == 1
        assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# Предупреждение: интервал тика больше четверти таймаута сторожа
# --------------------------------------------------------------------------------------------------


def test_connect_warns_when_tick_interval_exceeds_quarter_watchdog() -> None:
    """Сторож по умолчанию 3000 мс -> четверть 0.75 с. Тик 1.0 с -> предупреждение; тик 0.1 с -> его нет."""
    text = "интервал тика больше четверти таймаута сторожа"
    with E2eRig() as rig:
        slow = _Rec()
        with _driver(slow, rig.port, {"poll_interval_s": 1.0}):
            pass
        fast = _Rec()
        with _driver(fast, rig.port, {"poll_interval_s": 0.1}):
            pass
    assert text in slow.at("rv2", "last_error")
    assert text not in fast.at("rv2", "last_error")


# --------------------------------------------------------------------------------------------------
# Выход потока поводка по исключению
# --------------------------------------------------------------------------------------------------


def test_lease_thread_exception_releases_jog_and_allows_reconnect() -> None:
    """Первая запись поводка бросает исключение (связь цела): поток выходит и снимает свой jog.

    Ждём: публикация ``"поводок jog прерван: нет связи с роботом"``; робот встаёт по сроку поводка прошивки;
    следующий ``jog_hold`` шлёт НОВЫЙ ``JOG_CONT`` (флаг jog снят в ``finally``); после обрыва транспорта тик
    переподключается (флаг без живого потока переподключение не держит) и jog снова работает.
    """
    rec = _Rec()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        client = drv._client
        real_lease = client.jog_lease
        fired = threading.Event()

        def failing_lease() -> None:
            if not fired.is_set():
                fired.set()
                raise ConnectionError("сбой записи поводка (инъекция теста)")
            real_lease()

        client.jog_lease = failing_lease  # type: ignore[method-assign]
        try:
            n_cmd = len(_jog_cmds(rig))
            assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
            assert fired.wait(5.0)
            _until(lambda: TEXT_JOG_LOST in rec.at("rv2", "last_error"), 5.0, "публикация обрыва поводка")
            # прошивка останавливает jog по сроку поводка (300 мс)
            _until(lambda: _moving(rig) == 0, 5.0, "робот встал по сроку поводка")
            time.sleep(0.2)
            assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
            _hold(drv, 0.4)
            assert len(_jog_cmds(rig)) == n_cmd + 2, "после выхода потока поводка jog_hold не начал новый JOG_CONT"
            assert _moving(rig) == 1
            assert _call(drv, "jog_release")["status"] == "ok"
            _until(lambda: _moving(rig) == 0, 5.0, "release остановил робот")
        finally:
            client.jog_lease = real_lease  # type: ignore[method-assign]

        # обрыв транспорта без активного jog: тик переподключается сам (НР-1)
        bounded(drv.transport.disconnect, _CALL_DEADLINE_S)
        _until(lambda: drv.is_connected, 10.0, "драйвер переподключился")
        n_cmd = len(_jog_cmds(rig))
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _hold(drv, 0.3)
        assert len(_jog_cmds(rig)) == n_cmd + 1
        assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# disconnect во время программы
# --------------------------------------------------------------------------------------------------


def test_disconnect_during_program_aborts_and_joins_threads() -> None:
    """``disconnect`` при идущей программе: стоп (прерывание), поток исполнителя дождан, итог ``aborted``.

    Ждём: ``disconnect`` вернулся за дедлайн; последняя публикация ``.program`` — ``aborted`` с ``done < total``;
    поток исполнителя мёртв к возврату ``disconnect``; робот стоит; новых публикаций ``.program`` после нет.
    """
    rec = _Rec()
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    program = Program(name="long", steps=tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(12)))
    with E2eRig() as rig:
        with _driver(rec, rig.port) as drv:
            with pulse(lambda: drv.tick(None), 0.1):
                res = bounded(lambda: drv.start_program(program, points, None, name="long"), _CALL_DEADLINE_S)
                assert res["status"] == "ok", res
                _until(
                    lambda: any(p["state"] == "running" and p["done"] >= 1 for p in rec.at("rv2", "program")),
                    10.0,
                    "программа идёт",
                )
            bounded(drv.disconnect, _CALL_DEADLINE_S)
            alive = [t.name for t in threading.enumerate() if t.name.startswith("rv2-prog-") and t.is_alive()]
            assert alive == [], "поток исполнителя жив после disconnect"
            final = rec.at("rv2", "program")[-1]
            assert final["state"] == "aborted", final
            assert final["done"] < final["total"]
            n_pub = len(rec.at("rv2", "program"))
            assert not drv.is_connected
        _until(lambda: rig.core.ticks()[-1].moving == 0, 5.0, "робот встал")
        time.sleep(0.3)
        assert len(rec.at("rv2", "program")) == n_pub


# ==================================================================================================
# T3.7: задания enqueue_job / return_job (тесты автора, plans/robot-protocol-v2/tasks/T3.7.reds.md)
# ==================================================================================================
#
# Без sim — поддельный клиент (граница драйвера: аргументы cvt_job, уровни stop, вызовы probe) и поддельный
# транспорт с блоком TLM «робот свободен». На sim — два теста захвата против jog (I11a барьером, I11b краем зоны).

_HARD = 2  # STOP_LEVEL HARD (protocol-spec §8)
_E_BUSY = 4  # ERR E_BUSY (protocol-spec §6)
_PICK = {"x_mm": 300.0, "y_mm": -250.0}
_BAD_JOB = {"status": "error", "message": "неверные аргументы задания", "queue_len": 0}
_BUSY_PROGRAM_LIT = {"status": "error", "message": "робот занят программой"}
_CMD_CVT = re.compile(r"\[v2\] CMD seq=\d+ op=CVT_JOB")
_DONE_CVT = re.compile(r"\[v2\] DONE seq=\d+ op=CVT_JOB")
_DONE_JOG = re.compile(r"\[v2\] DONE seq=\d+ op=JOG_CONT")


def _free_tlm() -> list[int]:
    """Блок TLM (32 слова от TLM_PROTO_VER): серво включено, захват свободен, метка параметров 1, энкодер 0."""
    from Services.robot_comm.core.protocol_v2 import REG

    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = 1
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class _FakeTransport:
    def __init__(self) -> None:
        self.is_connected = True
        self.closed = 0
        self.tlm = _free_tlm()

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.closed += 1
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        return list(self.tlm)


class _FakeClient:
    """Клиент v2 на границе драйвера: пишет вызовы, исход ``cvt_job`` / ``wait_done`` / ``run_chunks`` задаёт тест."""

    heartbeat_period_s = None
    jog_lease_period_s = None

    def __init__(self) -> None:
        self.cvt: list[tuple] = []
        self.stops: list[int] = []
        self.probes = 0
        self.heartbeats = 0
        self.cvt_raises: list[BaseException] = []  # по одному на вызов cvt_job, по порядку
        self.wait: Callable[[Callable[[Any], None] | None], None] = lambda _poll: None
        self.run: Callable[[], None] = lambda: None
        self.stopped = threading.Event()

    def probe(self) -> None:
        self.probes += 1

    def sync_params(self, _values: Any, _epoch: int) -> None:
        pass

    def kick_heartbeat(self) -> None:
        self.heartbeats += 1

    def poll_errors(self) -> list:
        return []

    def cvt_job(self, *args: Any) -> Any:
        self.cvt.append(args)
        if self.cvt_raises:
            raise self.cvt_raises.pop(0)
        return type("Res", (), {"seq": len(self.cvt)})()

    def wait_done(self, _seq: int, *, on_poll: Callable[[Any], None] | None = None) -> None:
        self.wait(on_poll)

    def stop(self, level: int) -> None:
        self.stops.append(level)
        self.stopped.set()

    def run_chunks(self, _scenario: Any, *, params: Any, on_progress: Any) -> None:
        self.run()


def _fake_driver(rec: _Rec, **params: Any) -> tuple[RobotDriverV2, _FakeClient, _FakeTransport]:
    entry = DeviceEntry(
        id="rv2",
        name="rv2",
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
        params=params,
    )
    transport = _FakeTransport()
    drv = RobotDriverV2(entry, None, transport=transport, publish=rec)
    client = _FakeClient()
    drv._client = client  # шов: клиент v2 без sim (транспорт внедряется публично, клиент — нет)
    assert drv.connect() is True
    transport.closed = 0  # первый connect закрывает «подключённый» сокет до probe — счёт закрытий с нуля после него
    drv.desired_connected = True
    return drv, client, transport


def _tick_in_thread(drv: RobotDriverV2, stop_event: Any = None) -> threading.Thread:
    thread = threading.Thread(target=lambda: drv.tick(stop_event), name="t37-author-tick", daemon=True)
    thread.start()
    return thread


def _blocking_wait(client: _FakeClient, entered: threading.Event) -> None:
    """wait_done держится, пока не придёт стоп; затем — обрыв, как у робота на стопе (E_ABORTED)."""
    from Services.robot_comm.errors import RobotAborted

    def wait(on_poll: Callable[[Any], None] | None) -> None:
        entered.set()
        while not client.stopped.wait(0.02):
            if on_poll is not None:
                on_poll(_free_tlm())
        raise RobotAborted(1, 13, "Прервано стопом")  # 13 — E_ABORTED (protocol-spec §6)

    client.wait = wait


def _count_ev(rig: E2eRig, rx: re.Pattern[str], start: int = 0) -> int:
    return sum(1 for _, text in rig.core.events()[start:] if rx.search(text))


def test_job_stop_event_during_wait_sends_hard_and_fails_job() -> None:
    """stop_event хаба во время wait_done: пульс шёл, затем стоп HARD (не SOFT), задание неудачно, связь цела."""
    rec = _Rec()
    drv, client, transport = _fake_driver(rec)
    stop_event = threading.Event()
    polls = {"n": 0}

    def wait(on_poll: Callable[[Any], None] | None) -> None:
        assert on_poll is not None, "wait_done без on_poll: пульса во время задания нет"
        while True:
            polls["n"] += 1
            if polls["n"] == 3:
                stop_event.set()
            on_poll(_free_tlm())
            time.sleep(0.01)

    client.wait = wait
    assert drv.call("enqueue_job", _PICK)["status"] == "ok"
    beats_before = client.heartbeats
    bounded(lambda: drv.tick(stop_event), 5.0)
    assert client.stops == [_HARD]
    assert client.heartbeats - beats_before == 1 + 2  # пульс тика + два опроса до стопа
    snap = drv.snapshot()
    assert (snap["jobs_sent"], snap["jobs_done"], snap["jobs_failed"]) == (1, 0, 1)
    assert transport.closed == 0 and drv.is_connected


def test_disconnect_during_job_sends_hard() -> None:
    """disconnect при задании в полёте: стоп HARD до закрытия транспорта; тик выходит, задание неудачно."""
    rec = _Rec()
    drv, client, transport = _fake_driver(rec)
    entered = threading.Event()
    _blocking_wait(client, entered)
    assert drv.call("enqueue_job", _PICK)["status"] == "ok"
    ticker = _tick_in_thread(drv)
    assert entered.wait(5.0), "тик не дошёл до wait_done"
    bounded(drv.disconnect, 5.0)
    assert client.stops == [_HARD]
    ticker.join(5.0)
    assert not ticker.is_alive()
    assert drv.snapshot()["jobs_failed"] == 1
    assert transport.closed >= 1


def test_connect_during_job_skips_probe_and_sync() -> None:
    """connect() при задании в полёте (супервизор хаба) не делает probe/sync_params, а отвечает is_connected (R9)."""
    rec = _Rec()
    drv, client, _transport = _fake_driver(rec)
    entered = threading.Event()
    _blocking_wait(client, entered)
    assert drv.call("enqueue_job", _PICK)["status"] == "ok"
    ticker = _tick_in_thread(drv)
    try:
        assert entered.wait(5.0)
        probes = client.probes
        assert bounded(drv.connect, 5.0) is True
        assert client.probes == probes, "connect посреди задания пошёл в probe"
    finally:
        client.stopped.set()
        ticker.join(5.0)
    # после задания путь connect снова идёт целиком
    assert bounded(drv.connect, 5.0) is True
    assert client.probes == probes + 1


def test_nak_busy_returns_job_to_queue_head_without_failure() -> None:
    """NAK E_BUSY на cvt_job: задание обратно в НАЧАЛО очереди, отказ не считается; следующий тик шлёт его же."""
    from Services.robot_comm.errors import RobotNak

    rec = _Rec()
    drv, client, _transport = _fake_driver(rec)
    client.cvt_raises = [RobotNak(_E_BUSY, None, "Робот занят", None, ())]
    assert drv.call("enqueue_job", {"x_mm": 300.0, "y_mm": -250.0})["queue_len"] == 1
    assert drv.call("enqueue_job", {"x_mm": 310.0, "y_mm": -250.0})["queue_len"] == 2
    drv.tick(None)
    snap = drv.snapshot()
    assert (snap["queue_len"], snap["jobs_sent"], snap["jobs_failed"]) == (2, 0, 0)
    drv.tick(None)
    assert [args[1] for args in client.cvt] == [300.0, 300.0]
    assert drv.snapshot()["jobs_done"] == 1


def test_flags_bits_and_place_rz_on_wire() -> None:
    """Бит0 — по z_mm (0 = умолчание P_PICK_Z), бит1 — по укладке; place_rz = P_PICK_RZ (-100°) + доворот."""
    rec = _Rec()
    drv, client, _transport = _fake_driver(rec)
    drv.call("enqueue_job", {**_PICK, "e_capture": 7})
    drv.call("enqueue_job", {**_PICK, "z_mm": -90.0, "e_capture": 7})
    drv.call("enqueue_job", {**_PICK, "e_capture": 7, "place_x": 450.0, "place_y": -300.0, "place_rz": 30.0})
    for _ in range(3):
        drv.tick(None)
    # (ecap, x, y, z, flags, px, py, pz, prz)
    assert client.cvt[0] == (7, 300.0, -250.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
    assert client.cvt[1] == (7, 300.0, -250.0, -90.0, 1, 0.0, 0.0, 0.0, 0.0)
    assert client.cvt[2] == (7, 300.0, -250.0, 0.0, 2, 450.0, -300.0, 0.0, -70.0)


def test_job_queue_maxlen_evicts_oldest_and_telemetry_reports_len() -> None:
    """job_queue_maxlen=2: третье задание вытесняет старейшее (паритет v1 H-1); get_telemetry.queue_len — длина."""
    rec = _Rec()
    drv, client, _transport = _fake_driver(rec, job_queue_maxlen=2)
    for x in (300.0, 310.0, 320.0):
        res = drv.call("enqueue_job", {"x_mm": x, "y_mm": -250.0})
    assert res == {"status": "ok", "queue_len": 2}
    assert drv.call("get_telemetry", {})["queue_len"] == 2
    drv.tick(None)
    assert client.cvt[0][1] == 310.0
    assert drv.call("get_telemetry", {})["queue_len"] == 1


def test_bad_job_args_constant_text_queue_untouched() -> None:
    """Недопустимые аргументы: ответ без входного значения, очередь не тронута, связь цела (R8)."""
    rec = _Rec()
    drv, client, transport = _fake_driver(rec)
    bad = [
        {"x_mm": "abc", "y_mm": -250.0},
        {"x_mm": float("nan"), "y_mm": -250.0},
        {"x_mm": 3300.0, "y_mm": -250.0},
        {"y_mm": -250.0},
        {**_PICK, "e_capture": 1.5},
        {**_PICK, "e_capture": "abc"},
        {**_PICK, "place_x": 450.0, "place_y": -300.0, "place_rz": -3200.0},  # -100 - 3200 = -3300° вне провода
    ]
    for args in bad:
        res = drv.call("enqueue_job", args)
        assert res == _BAD_JOB, args
        assert "abc" not in str(res) and "3300" not in str(res)
    res = drv.call("return_job", {"x_mm": "abc", "y_mm": -150.0})
    assert res == {"status": "error", "message": "неверные аргументы возврата", "return_queue_len": 0}
    drv.tick(None)
    assert client.cvt == []
    assert transport.closed == 0 and drv.is_connected


def test_value_error_from_cvt_job_fails_job_without_link_loss() -> None:
    """ValueError из cvt_job (аргумент вне провода) — задание неудачно, связь НЕ рвётся (R8, I15)."""
    rec = _Rec()
    drv, client, transport = _fake_driver(rec)
    client.cvt_raises = [ValueError("координата #0: вне диапазона W_MIN..W_MAX")]
    assert drv.call("enqueue_job", _PICK)["status"] == "ok"
    drv.tick(None)
    assert drv.snapshot()["jobs_failed"] == 1
    assert drv.is_connected is True
    assert transport.closed == 0
    assert rec.at("rv2", "last_error"), "ошибка задания не опубликована"


def test_belt_factor_param_drives_pick_lead() -> None:
    """pick_lead_mm пересчитывается через P_BELT_FACTOR (×1e-5 мм/имп), а не константу v1 0.144473 (R4, I13)."""
    rec = _Rec()
    # 10.0 мм при 0.1 мм/имп = 100 имп; константа v1 дала бы 69
    drv, client, _transport = _fake_driver(rec, pick_lead_mm=10.0, robot_params={"P_BELT_FACTOR": 10000})
    assert drv.call("enqueue_job", {**_PICK, "e_capture": 1000})["status"] == "ok"
    drv.tick(None)
    assert client.cvt[0][0] == 900


def test_busy_reply_on_launch_requeues_return_at_head() -> None:
    """Захват перехвачен между проверкой тика и запуском: возврат обратно в начало очереди, отказ не считается."""
    rec = _Rec()
    drv, _client, _transport = _fake_driver(rec)
    assert drv.call("return_job", {"x_mm": 350.0, "y_mm": -150.0, "z_mm": -90.0})["return_queue_len"] == 1
    real = drv.start_return
    drv.start_return = lambda slot, **kw: dict(_BUSY_PROGRAM_LIT)  # шов: гонка «программа взяла захват раньше»
    drv.tick(None)
    snap = drv.snapshot()
    assert (snap["return_queued"], snap["returns_failed"], snap["returns_done"]) == (1, 0, 0)
    drv.start_return = real
    drv.tick(None)
    _until(lambda: drv.snapshot()["returns_done"] == 1, 5.0, "возврат исполнен после повтора")
    assert drv.snapshot()["return_queued"] == 0


def test_failed_return_program_counts_returns_failed() -> None:
    """Программа возврата упала: returns_failed, не returns_done (I14)."""
    rec = _Rec()
    drv, client, _transport = _fake_driver(rec)

    def boom() -> None:
        raise RuntimeError("обрыв сценария")

    client.run = boom
    assert drv.call("return_job", {"x_mm": 350.0, "y_mm": -150.0, "z_mm": -90.0})["status"] == "ok"
    drv.tick(None)
    _until(lambda: drv.snapshot()["returns_failed"] == 1, 5.0, "отказ программы возврата посчитан")
    assert drv.snapshot()["returns_done"] == 0
    _until(lambda: rec.at("rv2", "program")[-1]["state"] == "failed", 5.0, "публикация failed")


# --------------------------------------------------------------------------------------------------
# На sim: захват против jog
# --------------------------------------------------------------------------------------------------


def test_tick_does_not_take_job_while_jog_is_starting() -> None:
    """I11a: jog_hold задержан на записи JOG_CONT (барьер, не сон) — тик в это окно не берёт задание.

    Без проверки ``_jog_starting`` тик взял бы задание (``queue_len`` 0) и встал бы на замке mailbox за
    задержанным JOG_CONT — тест видит оба признака.
    """
    from Services.robot_comm.core.protocol_v2 import OP
    from Services.robot_comm.core.protocol_v2 import REG as _REG

    rec = _Rec()
    entered, release = threading.Event(), threading.Event()
    with E2eRig() as rig, _driver(rec, rig.port) as drv:
        device = drv.transport
        original = device.transaction

        def transaction(ops: list[tuple]) -> bool:
            for kind, address, value in ops:
                if kind == "wm" and address == _REG["CMD_SEQ"] and len(value) > 1 and value[1] == OP["JOG_CONT"]:
                    entered.set()
                    release.wait(5.0)
                    break
            return original(ops)

        device.transaction = transaction
        assert _call(drv, "enqueue_job", _PICK)["queue_len"] == 1
        holder = threading.Thread(target=lambda: drv.call("jog_hold", dict(_JOG)), name="t37-hold", daemon=True)
        holder.start()
        try:
            assert entered.wait(5.0), "jog_hold не дошёл до записи JOG_CONT"
            ticker = _tick_in_thread(drv)
            ticker.join(2.0)
            assert not ticker.is_alive(), "тик встал: задание взято при переходе jog"
            assert drv.snapshot()["queue_len"] == 1
            assert _count_ev(rig, _CMD_CVT) == 0
        finally:
            release.set()
            holder.join(5.0)
        assert _call(drv, "jog_release")["status"] == "ok"


def test_job_waits_for_jog_release_stop_in_flight() -> None:
    """Ревью T3.7 р.1: окно jog_release между выходом потока поводка и возвратом стопа SOFT.

    Стоп release задержан барьером (Event, не сон) дольше трёх тиков; jog у края зоны, робот свободен. Пока стоп
    не вернулся, тик не берёт задание: иначе SOFT этого jog оборвал бы CVT_JOB (E_ABORTED, jobs_failed 1).
    """
    rec = _Rec()
    entered, release = threading.Event(), threading.Event()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        client = drv._client  # шов: стоп release — метод клиента драйвера
        original_stop = client.stop

        def stop(level: int) -> Any:
            entered.set()
            release.wait(5.0)
            return original_stop(level)

        hold_args = {"dir": 5, "spd": 50}
        assert _call(drv, "jog_hold", hold_args)["status"] == "ok"
        end = time.monotonic() + 15.0
        while not _count_ev(rig, _DONE_JOG):  # подтверждения из этого потока: стоп release — единственный стоп
            assert time.monotonic() < end, "jog не дошёл до края зоны за 15 с"
            assert _call(drv, "jog_hold", hold_args)["status"] == "ok"
            time.sleep(0.05)
        assert _call(drv, "enqueue_job", _PICK) == {"status": "ok", "queue_len": 1}
        assert _call(drv, "jog_hold", hold_args)["status"] == "ok"
        client.stop = stop
        mark = len(rig.core.events())
        releaser = threading.Thread(target=lambda: drv.call("jog_release", {}), name="t37-release", daemon=True)
        releaser.start()
        try:
            assert entered.wait(5.0), "jog_release не дошёл до стопа"
            assert not release.wait(0.4)  # окно дольше трёх тиков pulse 0.1 с
            assert _count_ev(rig, _CMD_CVT, mark) == 0, "задание ушло, пока стоп jog_release в полёте"
            assert drv.snapshot()["queue_len"] == 1
        finally:
            release.set()
            releaser.join(5.0)
        client.stop = original_stop
        assert not releaser.is_alive()
        _until(lambda: drv.snapshot()["jobs_done"] + drv.snapshot()["jobs_failed"] >= 1, 15.0, "исход задания")
        snap = drv.snapshot()
        assert (snap["jobs_done"], snap["jobs_failed"]) == (1, 0)


def test_job_waits_for_jog_at_zone_edge_while_robot_is_free() -> None:
    """I11b: jog дошёл до края зоны (DONE JOG_CONT, робот свободен), удержание продолжается — задание ждёт."""
    rec = _Rec()
    with E2eRig() as rig, _driver(rec, rig.port) as drv, pulse(lambda: drv.tick(None), 0.1):
        hold = threading.Event()
        hold.set()

        def confirm() -> None:
            while hold.is_set():
                try:
                    drv.call("jog_hold", {"dir": 5, "spd": 50})
                except Exception:  # noqa: BLE001 — подтверждения GUI не утверждают
                    pass
                time.sleep(0.05)

        assert _call(drv, "jog_hold", {"dir": 5, "spd": 50})["status"] == "ok"
        confirmer = threading.Thread(target=confirm, name="t37-edge-confirm", daemon=True)
        confirmer.start()
        try:
            rig.wait_event(_DONE_JOG.pattern, timeout_s=15.0)  # край зоны: робот свободен, jog драйвера жив
            mark = len(rig.core.events())
            res = _call(drv, "enqueue_job", _PICK)
            assert res == {"status": "ok", "queue_len": 1}
            time.sleep(0.6)
            assert _count_ev(rig, _CMD_CVT, mark) == 0, "задание ушло при удержании jog"
            assert drv.snapshot()["queue_len"] == 1
        finally:
            hold.clear()
            confirmer.join(2.0)
        assert _call(drv, "jog_release")["status"] == "ok"
        _until(lambda: _count_ev(rig, _DONE_CVT, mark) == 1, 15.0, "DONE op=CVT_JOB после jog_release")
