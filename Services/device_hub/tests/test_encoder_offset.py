"""Тесты подстройки энкодера (pick_lead_mm) и переключения инструмента (toolchange).

Задача A: компенсация задержки конвейера (CVT lead compensation).
Задача B: op_toolchange в RobotDriver через FakeRobotTransport (in-process, без TCP).
"""

from __future__ import annotations

import threading

import pytest

from Services.robot_comm.core.registers import REG_TOOL_CUR
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock

# Константа из прошивки (cvt_universal_full.lua:121)
FACTOR_MM = 0.144473


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


# ------------------------------------------------------------------ #
# Задача A: Компенсация задержки конвейера (pick_lead_mm)
# ------------------------------------------------------------------ #


class TestEncoderOffsetBasic:
    """Базовые тесты _apply_pick_lead и enqueue_job с offset."""

    def test_default_offset_zero(self, driver) -> None:
        """Дефолт: pick_lead_mm=0 → e_capture без изменений."""
        assert driver._pick_lead_mm == 0.0

    def test_apply_lead_zero_passthrough(self, driver) -> None:
        """Offset=0 → e_capture проходит без изменений."""
        e = 1000
        assert driver._apply_pick_lead(e) == 1000

    def test_apply_lead_positive_reduces_ecap(self, driver) -> None:
        """Положительный offset → уменьшает e_capture (целиться дальше).

        Lua: trav = (enc_now - job_enc) * FACTOR_MM; py = job_y + UY * trav.
        UY=1. Чтобы trav↑ (дальше), job_enc↓ → вычитаем offset_counts.
        """
        driver._pick_lead_mm = 14.4  # ~100 counts
        e = 1000
        result = driver._apply_pick_lead(e)
        expected_offset = round(14.4 / FACTOR_MM)  # 99 или 100
        assert result == e - expected_offset
        assert result < e  # компенсация уменьшает

    def test_apply_lead_negative_increases_ecap(self, driver) -> None:
        """Отрицательный offset → увеличивает e_capture (целиться ближе)."""
        driver._pick_lead_mm = -14.4
        e = 1000
        result = driver._apply_pick_lead(e)
        expected_offset = round(-14.4 / FACTOR_MM)  # -100
        assert result == e - expected_offset
        assert result > e  # отрицательная компенсация увеличивает

    def test_enqueue_applies_offset(self, driver) -> None:
        """enqueue_job применяет offset к e_capture перед помещением в очередь."""
        driver._pick_lead_mm = 14.4
        e_original = 5000
        ok = driver.enqueue_job(100.0, 200.0, e_capture=e_original)
        assert ok
        assert len(driver._job_queue) == 1
        _x, _y, _z, e_in_queue, _place = driver._job_queue[0]
        expected_offset = round(14.4 / FACTOR_MM)
        assert e_in_queue == e_original - expected_offset

    def test_enqueue_zero_offset_preserves_ecap(self, driver) -> None:
        """Offset=0: e_capture в очереди == оригинальное значение."""
        e_original = 5000
        ok = driver.enqueue_job(100.0, 200.0, e_capture=e_original)
        assert ok
        _x, _y, _z, e_in_queue, _place = driver._job_queue[0]
        assert e_in_queue == e_original

    def test_enqueue_offset_applied_to_read_encoder(self, driver) -> None:
        """Offset применяется и к read_encoder (когда e_capture=None)."""
        driver._pick_lead_mm = 7.2  # ~50 counts
        ok = driver.enqueue_job(100.0, 200.0)  # e_capture=None → read_encoder
        assert ok
        _x, _y, _z, e_in_queue, _place = driver._job_queue[0]
        # Значение должно быть: read_encoder() - offset_counts
        # FakeTransport: encoder тикает на каждом read (enc_rate=7, 1 tick → +7)
        # После read_encoder: encoder = 7 (один тик)
        expected_offset = round(7.2 / FACTOR_MM)  # ~50
        # read_encoder вернёт «живой» энкодер, к нему применяется offset
        assert e_in_queue < 100  # 7 - 50 < 0 → int32 wrap, ИЛИ если sim = 0+7=7, то 7-50 < 0
        # Проверяем что offset был применён (не равно raw read)
        raw_enc_value = 7  # один тик sim, enc_rate=7
        assert e_in_queue == raw_enc_value - expected_offset


class TestEncoderOffsetRoundtrip:
    """Полный roundtrip: offset → enqueue → tick → sim принимает скорректированный e_capture."""

    def test_offset_reaches_simulator(self, driver, core, clock) -> None:
        """Скорректированный e_capture доходит до sim_core._job_ecap."""
        driver._pick_lead_mm = 14.4
        e_original = 10000
        driver.enqueue_job(100.0, 200.0, e_capture=e_original)

        stop = threading.Event()
        # Прогнать tick'и до доставки + приёма
        for _ in range(5):
            driver.tick(stop)

        assert driver.jobs_sent >= 1
        # sim_core запомнил скорректированный e_capture
        expected_offset = round(14.4 / FACTOR_MM)
        expected_ecap = e_original - expected_offset
        # sim_core._job_ecap хранит LO-word (для little word_order),
        # но для небольших значений (< 0xFFFF) это и есть полное значение
        assert core._job_ecap == expected_ecap & 0xFFFF

    def test_zero_offset_preserves_ecap_in_sim(self, driver, core, clock) -> None:
        """Без offset: e_capture доходит до sim без изменений."""
        e_original = 500
        driver.enqueue_job(100.0, 200.0, e_capture=e_original)

        stop = threading.Event()
        for _ in range(5):
            driver.tick(stop)

        assert driver.jobs_sent >= 1
        assert core._job_ecap == e_original


class TestSetEncoderOffsetOp:
    """Операция set_encoder_offset: live-tuning через call()."""

    def test_set_via_call(self, driver) -> None:
        """call('set_encoder_offset') меняет pick_lead_mm."""
        result = driver.call("set_encoder_offset", {"lead_mm": 15.0})
        assert result["status"] == "ok"
        assert result["pick_lead_mm"] == 15.0
        assert result["offset_counts"] == round(15.0 / FACTOR_MM)
        assert driver._pick_lead_mm == 15.0

    def test_set_zero_resets(self, driver) -> None:
        """Установка 0 сбрасывает компенсацию."""
        driver._pick_lead_mm = 10.0
        result = driver.call("set_encoder_offset", {"lead_mm": 0.0})
        assert result["status"] == "ok"
        assert result["pick_lead_mm"] == 0.0
        assert result["offset_counts"] == 0
        assert driver._pick_lead_mm == 0.0

    def test_set_negative(self, driver) -> None:
        """Отрицательное значение: целиться ближе."""
        result = driver.call("set_encoder_offset", {"lead_mm": -5.0})
        assert result["status"] == "ok"
        assert result["pick_lead_mm"] == -5.0

    def test_set_then_enqueue_uses_new_offset(self, driver) -> None:
        """После set_encoder_offset следующие enqueue используют новый offset."""
        driver.call("set_encoder_offset", {"lead_mm": 14.4})
        e = 1000
        driver.enqueue_job(100.0, 200.0, e_capture=e)
        _x, _y, _z, e_in_queue, _place = driver._job_queue[0]
        expected_offset = round(14.4 / FACTOR_MM)
        assert e_in_queue == e - expected_offset


class TestEncoderOffsetSnapshot:
    """pick_lead_mm виден в snapshot (для дашборда/телеметрии)."""

    def test_snapshot_contains_pick_lead(self, driver) -> None:
        snap = driver.snapshot()
        assert "pick_lead_mm" in snap
        assert snap["pick_lead_mm"] == 0.0

    def test_snapshot_reflects_set(self, driver) -> None:
        driver.call("set_encoder_offset", {"lead_mm": 12.5})
        snap = driver.snapshot()
        assert snap["pick_lead_mm"] == 12.5


class TestEncoderOffsetFromParams:
    """pick_lead_mm из entry.params (конфиг рецепта)."""

    def test_params_initial(self, transport, clock) -> None:
        """pick_lead_mm задаётся через params при создании драйвера."""
        entry = DeviceEntry(
            id="robot_main",
            name="Робот",
            kind="robot",
            protocol="delta_universal3",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
            params={"word_order": "little", "pick_lead_mm": 10.0},
        )
        d = RobotDriver(entry, transport=transport, clock=clock.clock, sleep=clock.sleep)
        assert d._pick_lead_mm == 10.0


class TestEncoderOffsetEdgeCases:
    """Граничные случаи: int32 wrap, большие значения."""

    def test_large_positive_offset(self, driver) -> None:
        """Большой offset при маленьком e_capture → отрицательное int32 (wrap)."""
        driver._pick_lead_mm = 100.0  # ~692 counts
        e = 100  # маленький
        result = driver._apply_pick_lead(e)
        expected_offset = round(100.0 / FACTOR_MM)
        # 100 - 692 = -592 → корректный signed int32
        assert result == 100 - expected_offset
        assert result < 0  # signed int32 отрицательный — допустимо


# ------------------------------------------------------------------ #
# Задача B: Переключение инструмента (toolchange)
# ------------------------------------------------------------------ #


class TestToolchangeOp:
    """_op_toolchange: смена инструмента через call()."""

    def test_toolchange_via_call(self, driver, core) -> None:
        """call('toolchange', {target: 1}) меняет инструмент, возвращает tool_current."""
        result = driver.call("toolchange", {"target": 1})
        assert result["status"] == "ok"
        assert result["tool_current"] == 1
        assert core.regs[REG_TOOL_CUR] == 1

    def test_toolchange_same_tool_returns_error(self, driver, core) -> None:
        """Смена на текущий инструмент: Lua мгновенно сбрасывает flag+busy=0,
        но client.do_toolchange ждёт busy↑ (которого нет) → timeout → error.
        tool_current остаётся корректным (инструмент не менялся)."""
        # tool_cur=0 дефолт, target=0 → «инструмент уже стоит»
        result = driver.call("toolchange", {"target": 0})
        # Handshake: tool_flag→0 OK, но tool_busy никогда не станет 1 → timeout
        assert result["status"] == "error"
        assert result["tool_current"] == 0  # инструмент не менялся

    def test_toolchange_to_2(self, driver, core) -> None:
        """Смена на инструмент 2."""
        result = driver.call("toolchange", {"target": 2})
        assert result["status"] == "ok"
        assert result["tool_current"] == 2
        assert core.regs[REG_TOOL_CUR] == 2

    def test_toolchange_mode_restored_to_cvt(self, driver) -> None:
        """После toolchange режим возвращается в cvt."""
        driver.call("toolchange", {"target": 1})
        assert driver.mode == "cvt"

    def test_toolchange_sequential(self, driver, core) -> None:
        """Последовательная смена: 0 → 1 → 2 → 0."""
        for target in [1, 2, 0]:
            result = driver.call("toolchange", {"target": target})
            assert result["status"] == "ok"
            assert result["tool_current"] == target

    def test_toolchange_invalid_target_error(self, driver) -> None:
        """Невалидный target (>2) → ошибка ValueError."""
        result = driver.call("toolchange", {"target": 5})
        assert result["status"] == "error"


# ------------------------------------------------------------------ #
# Задача C: очередь без лимита (HIGH) — проверка что deque maxlen не ломает
# ------------------------------------------------------------------ #


class TestQueueBehavior:
    """Базовая проверка поведения очередей."""

    def test_multiple_enqueue(self, driver) -> None:
        """Множественные enqueue работают."""
        for i in range(10):
            ok = driver.enqueue_job(float(i), float(i))
            assert ok
        assert len(driver._job_queue) == 10
