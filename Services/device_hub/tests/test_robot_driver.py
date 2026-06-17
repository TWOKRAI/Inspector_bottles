"""Тесты RobotDriver: enqueue->tick->доставка, manual_mode, reconnect, draw, телеметрия, mode."""

from __future__ import annotations

import threading

import pytest

from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock


@pytest.fixture
def robot_entry() -> DeviceEntry:
    return DeviceEntry(
        id="robot_main",
        name="Робот Delta",
        kind="robot",
        protocol="delta_universal3",
        transport={"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
        params={
            "word_order": "little",
            "feed_poll_s": 0.01,
            "telemetry_interval_s": 0.1,
            "accept_wait_s": 5.0,
            "job_wait_s": 10.0,
        },
    )


@pytest.fixture
def core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def transport(core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(core)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def driver(robot_entry, transport, clock) -> RobotDriver:
    """Подключённый RobotDriver поверх фейк-транспорта."""
    d = RobotDriver(
        robot_entry,
        protocol=None,
        transport=transport,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    d.connect()
    return d


class TestRobotDriverLifecycle:
    """Подключение, отключение."""

    def test_connect_disconnect(self, robot_entry, transport, clock) -> None:
        d = RobotDriver(robot_entry, transport=transport, clock=clock.clock, sleep=clock.sleep)
        assert not d.is_connected
        ok = d.connect()
        assert ok
        assert d.is_connected
        d.disconnect()
        assert not d.is_connected

    def test_mode_default_cvt(self, driver) -> None:
        assert driver.mode == "cvt"


class TestRobotDriverFeeder:
    """CVT feeder: enqueue -> tick -> доставка."""

    def test_enqueue_tick_deliver(self, driver, core, clock) -> None:
        """enqueue_job + tick -> задание доставлено, jobs_done растёт."""
        ok = driver.enqueue_job(100.0, 200.0)
        assert ok
        assert len(driver._job_queue) == 1

        # Прогнать tick (feeder): робот свободен -> deliver
        stop = threading.Event()
        snap = driver.tick(stop)
        assert snap is not None
        assert snap["quality"] == "good"

        # sim: accept_ticks=1, job_ticks=2 — нужно несколько tick'ов
        # (но deliver внутренне поллит через _wait_condition)
        # Проверяем что задание выполнено
        assert driver.jobs_sent >= 1

    def test_place_job_pc_converts_rz_to_absolute(self, driver, core, clock) -> None:
        """PC-side: доворот → абсолютный R = реальный R робота (опрос) + доворот; поза уходит роботу."""
        from Services.robot_comm.core.registers import (
            REG_PLACE_RZ,
            REG_PLACE_X,
            REG_PLACE_Y,
            REG_PLACE_Z,
        )

        # sim TLM_RZ = 0 (реальный R инструмента) → абсолютный R = 0 + доворот(45°)
        ok = driver.enqueue_job(100.0, 200.0, place=(300.0, -120.0, -90.0, 45.0))
        assert ok
        stop = threading.Event()
        for _ in range(5):
            driver.tick(stop)
        assert driver.jobs_sent >= 1
        assert core.regs[REG_PLACE_X] == 3000  # 300.0 ×10
        assert core.regs[REG_PLACE_Y] == (-1200) & 0xFFFF
        assert core.regs[REG_PLACE_Z] == (-900) & 0xFFFF
        assert core.regs[REG_PLACE_RZ] == 450  # (реальный R 0 + доворот 45) ×10

    def test_manual_mode_pauses_feeder(self, driver, clock) -> None:
        """manual_mode=True -> очередь не обрабатывается."""
        driver.manual_mode = True
        driver.enqueue_job(50.0, 50.0)
        stop = threading.Event()
        driver.tick(stop)
        # Задание осталось в очереди
        assert len(driver._job_queue) == 1
        assert driver.jobs_sent == 0


class TestRobotDrawSetPenPartial:
    """draw_set_pen: частичное обновление (дашборд-пульт: два независимых контрола)."""

    def test_both_then_partial(self, driver) -> None:
        driver._op_draw_set_pen({"down": -10.0, "up": 5.0})
        assert driver._pen_down_mm == -10.0
        assert driver._pen_up_mm == 5.0

        # только down — up сохраняется
        r = driver._op_draw_set_pen({"down": -20.0})
        assert driver._pen_down_mm == -20.0
        assert driver._pen_up_mm == 5.0
        assert r["up"] == 5.0

        # только up — down сохраняется
        driver._op_draw_set_pen({"up": 8.0})
        assert driver._pen_down_mm == -20.0
        assert driver._pen_up_mm == 8.0


class TestRobotDriverReconnect:
    """Throttled reconnect при недоступном транспорте."""

    def test_disconnected_reconnect_throttle(self, robot_entry, transport, clock) -> None:
        """При обрыве + desired=True: reconnect не чаще _RECONNECT_THROTTLE_SEC."""
        d = RobotDriver(
            robot_entry,
            transport=transport,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        d.desired_connected = True
        # Не подключаемся — tick пытается reconnect
        transport._connected = False
        stop = threading.Event()

        snap1 = d.tick(stop)
        assert snap1["quality"] == "bad"

        # Сразу второй tick — throttle, не пытается
        snap2 = d.tick(stop)
        assert snap2["quality"] == "bad"

        # Продвигаем часы на 3 сек
        clock.t += 3.0
        # Теперь reconnect — FakeRobotTransport.connect() вернёт True
        snap3 = d.tick(stop)
        assert snap3["quality"] == "good"
        assert d.is_connected

    def test_no_reconnect_when_desired_false(self, robot_entry, transport, clock) -> None:
        """НР-1: desired=False -> tick НЕ пытается реконнектиться."""
        d = RobotDriver(
            robot_entry,
            transport=transport,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        d.desired_connected = False
        transport._connected = False
        stop = threading.Event()

        # 5 тиков с прокруткой времени — connect НЕ вызывается
        for _ in range(5):
            snap = d.tick(stop)
            assert snap["quality"] == "bad"
            clock.t += 5.0

        assert not d.is_connected
        # reconnects = 0 (не было попыток)
        assert d.stats["reconnects"] == 0


class TestRobotDriverReconnectLimit:
    """Лимит попыток реконнекта: после N неудач драйвер «сдаётся»."""

    @staticmethod
    def _fail_connect(driver: RobotDriver) -> dict:
        """Подменить connect() на всегда-провал со счётчиком вызовов."""
        calls = {"n": 0}

        def fake_connect() -> bool:
            calls["n"] += 1
            return False

        driver.connect = fake_connect  # type: ignore[method-assign]
        return calls

    def test_gives_up_after_limit(self, robot_entry, transport, clock) -> None:
        """После max_reconnect_attempts неудач: desired=False, reconnect_exhausted=True, спам прекращается."""
        d = RobotDriver(robot_entry, transport=transport, clock=clock.clock, sleep=clock.sleep)
        assert d.max_reconnect_attempts == 3  # дефолт
        d.desired_connected = True
        transport._connected = False
        calls = self._fail_connect(d)
        stop = threading.Event()

        # 3 попытки (перед каждым тиком продвигаем часы > throttle 2.0)
        for _ in range(3):
            clock.t += 3.0
            d.tick(stop)
        assert calls["n"] == 3
        assert d.reconnect_exhausted is True
        assert d.desired_connected is False

        # Дальше connect НЕ зовётся (desired=False) — спама нет
        clock.t += 10.0
        d.tick(stop)
        assert calls["n"] == 3

    def test_manual_reset_reenables(self, robot_entry, transport, clock) -> None:
        """reset_reconnect (ручной «Подключить») даёт заново полный лимит попыток."""
        d = RobotDriver(robot_entry, transport=transport, clock=clock.clock, sleep=clock.sleep)
        d.desired_connected = True
        transport._connected = False
        calls = self._fail_connect(d)
        stop = threading.Event()
        for _ in range(3):
            clock.t += 3.0
            d.tick(stop)
        assert d.reconnect_exhausted is True

        # Ручной reconnect: сброс + desired=True снова
        d.reset_reconnect()
        d.desired_connected = True
        assert d.reconnect_exhausted is False
        clock.t += 3.0
        d.tick(stop)
        assert calls["n"] == 4  # снова пытается

    def test_zero_means_unlimited(self, transport, clock) -> None:
        """max_reconnect_attempts=0 — без лимита (прежнее бесконечное поведение)."""
        entry = DeviceEntry(
            id="robot_main",
            name="Робот",
            kind="robot",
            protocol="delta_universal3",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
            params={"max_reconnect_attempts": 0},
        )
        d = RobotDriver(entry, transport=transport, clock=clock.clock, sleep=clock.sleep)
        d.desired_connected = True
        transport._connected = False
        calls = self._fail_connect(d)
        stop = threading.Event()
        for _ in range(6):
            clock.t += 3.0
            d.tick(stop)
        assert calls["n"] == 6  # пытается каждый раз
        assert d.desired_connected is True
        assert d.reconnect_exhausted is False


class TestRobotDriverDraw:
    """Draw-очередь: draw_circle через call, abort."""

    def test_draw_circle_via_call(self, driver, core, clock) -> None:
        """draw_circle кладёт задание в очередь, tick исполняет."""
        result = driver.call("draw_circle", {"cx": 100, "cy": 100, "r": 50})
        assert result["status"] == "ok"
        assert result["queued"] == 1

        # tick исполняет draw
        stop = threading.Event()
        driver.tick(stop)
        # После draw_ticks=3 тиков sim — draw завершён
        assert driver.draws_done >= 1

    def test_draw_abort(self, driver) -> None:
        """draw_abort прерывает немедленно."""
        # Кладём задание
        driver.call("draw_polyline", {"points": [{"x_mm": 0, "y_mm": 0, "pen": 1}]})
        # Abort
        result = driver.call("draw_abort", {})
        assert result["status"] == "ok"

    def test_mode_exposed_in_snapshot(self, driver) -> None:
        """mode видно в snapshot."""
        snap = driver.snapshot()
        assert snap["mode"] == "cvt"


class TestRobotDriverReturn:
    """Возврат буквы на ленту: return_job через call, tick исполняет, режим cvt после."""

    def test_return_job_via_call_enqueues(self, driver) -> None:
        result = driver.call("return_job", {"x_mm": 120.0, "y_mm": -60.0, "z_mm": -90.0})
        assert result["status"] == "ok"
        assert result["return_queue_len"] == 1

    def test_return_executed_and_mode_restored(self, driver) -> None:
        driver.call("return_job", {"x_mm": 120.0, "y_mm": -60.0, "z_mm": -90.0})
        stop = threading.Event()
        # tick №1 — переключение в RETURN + исполнение одного возврата (sim завершает handshake).
        driver.tick(stop)
        assert driver.returns_done >= 1
        # tick №2 — очередь пуста → режим вернулся в cvt (иначе CVT-feeder заглушен).
        driver.tick(stop)
        assert driver.mode == "cvt"

    def test_return_counters_in_snapshot(self, driver) -> None:
        snap = driver.snapshot()
        assert snap["returns_done"] == 0
        assert snap["return_queued"] == 0


class TestRobotDriverTelemetry:
    """Телеметрия в snapshot."""

    def test_snapshot_has_stats(self, driver) -> None:
        snap = driver.snapshot()
        assert "stats" in snap
        assert "tx_ok" in snap["stats"]
        assert "quality" in snap
        assert "mode" in snap

    def test_get_telemetry_call(self, driver) -> None:
        """call get_telemetry возвращает данные."""
        result = driver.call("get_telemetry", {})
        assert result["status"] == "ok"
        assert "telemetry" in result
        assert "encoder" in result


class TestRobotDriverTickQuality:
    """н8: quality в snapshot tick'а отражает результат текущего тика."""

    def test_tick_good_on_success(self, driver) -> None:
        """Успешный tick (без IO-ошибок) -> quality=good."""
        stop = threading.Event()
        snap = driver.tick(stop)
        assert snap is not None
        assert snap["quality"] == "good"

    def test_tick_bad_on_telemetry_error(self, driver) -> None:
        """н8: если телеметрия падает в этом тике -> quality=bad, не good."""
        # Форсируем сброс интервала телеметрии, чтобы следующий tick точно её вызвал
        driver._last_telemetry = 0.0
        driver._telemetry_interval_s = 0.0

        import unittest.mock as mock

        # Заставляем read_telemetry бросить исключение
        with mock.patch.object(driver._client, "read_telemetry", side_effect=OSError("симулированная ошибка")):
            stop = threading.Event()
            snap = driver.tick(stop)

        assert snap is not None
        # tx_err вырос — качество должно быть bad (не good)
        assert snap["quality"] != "good", "tick с IO-ошибкой в этом тике должен возвращать quality != good"


class TestRobotDriverPickZ:
    """Проброс pick z_mm через _op_enqueue_job → enqueue_job → send_job → REG_JOB_Z."""

    def test_op_enqueue_job_forwards_z_mm(self, driver, core) -> None:
        """_op_enqueue_job пробрасывает z_mm в enqueue_job; регистр REG_JOB_Z записан."""
        from Services.robot_comm.core.registers import REG_JOB_Z

        result = driver.call(
            "enqueue_job",
            {
                "x_mm": 100.0,
                "y_mm": 200.0,
                "z_mm": -45.0,
            },
        )
        assert result["status"] == "ok"
        # Прогоняем tick чтобы deliver сработал
        stop = threading.Event()
        for _ in range(5):
            driver.tick(stop)
        assert driver.jobs_sent >= 1
        # REG_JOB_Z = -45.0 × 10 = -450 → s16 unsigned
        expected = (-450) & 0xFFFF
        assert core.regs[REG_JOB_Z] == expected

    def test_op_enqueue_job_z_mm_default_zero(self, driver, core) -> None:
        """Без z_mm → не пишем REG_JOB_Z (дефолт прошивки Z_PICK)."""
        from Services.robot_comm.core.registers import REG_JOB_Z

        # Сбросим регистр в специальное значение-маркер, чтобы убедиться что не трогали
        core.regs[REG_JOB_Z] = 0xBEEF
        result = driver.call("enqueue_job", {"x_mm": 10.0, "y_mm": 20.0})
        assert result["status"] == "ok"
        stop = threading.Event()
        for _ in range(5):
            driver.tick(stop)
        assert driver.jobs_sent >= 1
        # z_mm=0 → send_job НЕ пишет job_z → регистр остался маркером
        assert core.regs[REG_JOB_Z] == 0xBEEF


class TestRobotDriverCallOps:
    """Проверка таблицы операций."""

    def test_unknown_op(self, driver) -> None:
        result = driver.call("nonexistent_op", {})
        assert result["status"] == "error"

    def test_set_manual_mode(self, driver) -> None:
        result = driver.call("set_manual_mode", {"on": True})
        assert result["status"] == "ok"
        assert driver.manual_mode is True

    def test_jog_via_call(self, driver) -> None:
        result = driver.call("jog", {"dx": 12.0, "dy": -8.0, "spd": 40, "absolute": False})
        assert result["status"] == "ok"
        assert result["dx"] == 12.0 and result["dy"] == -8.0
        assert driver.mode == "manual"  # jog включает режим manual

    def test_jog_abort_via_call(self, driver) -> None:
        result = driver.call("jog_abort", {})
        assert result["status"] == "ok"

    def test_clear_queue(self, driver) -> None:
        driver.enqueue_job(1.0, 2.0)
        driver.enqueue_job(3.0, 4.0)
        result = driver.call("clear_queue", {})
        assert result["status"] == "ok"
        assert result["dropped"] == 2
        assert len(driver._job_queue) == 0

    def test_set_servo(self, driver) -> None:
        result = driver.call("set_servo", {"on": True})
        assert result["status"] == "ok"

    def test_read_echo(self, driver) -> None:
        result = driver.call("read_echo", {})
        assert result["status"] == "ok"
        assert "echo" in result
