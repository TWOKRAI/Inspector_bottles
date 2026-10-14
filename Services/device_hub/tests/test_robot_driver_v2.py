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
