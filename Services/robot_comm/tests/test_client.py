"""Тесты RobotClient против FakeRobotTransport — полный цикл без сети.

Проверяются и байты на проводе (содержимое транзакций — контракт с Lua), и
поведение поверх семантики фейк-робота (accept/free/echo/draw).
"""

from __future__ import annotations

import pytest

from Services.modbus import RegisterTransport
from Services.modbus.sdk.errors import ModbusConnectionError

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.core.datatypes import DrawPoint
from Services.robot_comm.core.registers import (
    REG_DRAW_FLAG,
    REG_JOB_FLAG,
    REG_PTS_BASE,
    WRITE_CHUNK,
)
from Services.robot_comm.errors import RobotJobError
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


def _poll(bot: RobotClient, predicate, attempts: int = 20) -> bool:
    """Поллить условие: каждое чтение тикает фейк-робота."""
    return any(predicate() for _ in range(attempts))


# --- соединение / мост ---


def test_client_satisfies_register_transport(bot: RobotClient) -> None:
    """Клиент сам является RegisterTransport — мост для vfd_comm."""
    assert isinstance(bot, RegisterTransport)


def test_read_without_connect_raises(transport: FakeRobotTransport) -> None:
    client = RobotClient(RobotConfig(), transport=transport)
    with pytest.raises(ModbusConnectionError):
        client.read_encoder()


def test_get_status_includes_robot_address(bot: RobotClient) -> None:
    assert "robot" in bot.get_status()


# --- CVT: задание ---


def test_send_job_wire_format_marker_last(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Контракт с Lua: X, Y (s16*10), ECAP (DW little), маркер — ПОСЛЕДНИМ."""
    bot.send_job(150.5, -200.3, 1234567)
    ops = transport.transactions[-1]
    assert ops[0] == ("w", 0x1101, 1505)
    assert ops[1] == ("w", 0x1102, (-2003) & 0xFFFF)
    assert ops[2] == ("wm", 0x1104, [0xD687, 0x0012])  # little: lo, hi
    assert ops[3] == ("w", REG_JOB_FLAG, 1)  # маркер последним


def test_send_job_rejects_out_of_limit(bot: RobotClient) -> None:
    with pytest.raises(RobotJobError, match="вне"):
        bot.send_job(5000.0, 0.0, 0)


def test_job_lifecycle_accept_then_free(bot: RobotClient, core: RobotSimCore) -> None:
    """Полный цикл: занят -> принял (flag->0) -> выполнил (free->1), эхо совпадает."""
    assert bot.is_free()
    bot.send_job(100.0, -50.0, 42)
    assert _poll(bot, bot.job_accepted)
    assert _poll(bot, bot.is_free)
    echo = bot.read_echo()
    assert echo.job_x == pytest.approx(100.0)
    assert echo.job_y == pytest.approx(-50.0)
    # после выполнения позиция = задание
    pos = bot.read_position()
    assert pos.x_mm == pytest.approx(100.0)
    assert pos.y_mm == pytest.approx(-50.0)


def test_stop_frees_robot(bot: RobotClient) -> None:
    bot.send_job(10.0, 10.0, 1)
    bot.stop(1)
    assert _poll(bot, bot.is_free)


def test_stop_rejects_bad_mode(bot: RobotClient) -> None:
    with pytest.raises(ValueError):
        bot.stop(9)


def test_servo_toggle_reflected_in_telemetry(bot: RobotClient) -> None:
    bot.set_servo(False)
    assert _poll(bot, lambda: bot.read_telemetry().servo is False)
    bot.set_servo(True)
    assert _poll(bot, lambda: bot.read_telemetry().servo is True)


# --- энкодер / word order ---


def test_encoder_monotonic(bot: RobotClient) -> None:
    first = bot.read_encoder()
    second = bot.read_encoder()
    assert second > first


def test_encoder_word_order_big(clock) -> None:
    """Клиент и sim с word_order=big согласованы (проверка симметрии кодеков)."""
    core = RobotSimCore(word_order="big")
    transport = FakeRobotTransport(core)
    client = RobotClient(RobotConfig(word_order="big"), transport=transport, clock=clock.clock, sleep=clock.sleep)
    client.connect()
    assert client.read_encoder() == core.encoder


def test_enc_raw_two_words(bot: RobotClient) -> None:
    assert len(bot.read_enc_raw()) == 2


# --- режим ---


def test_set_mode_validates(bot: RobotClient) -> None:
    assert bot.set_mode("draw")
    with pytest.raises(ValueError):
        bot.set_mode("fly")


# --- конфиг: read-modify-write ---


def test_set_config_rmw_preserves_other_fields(bot: RobotClient) -> None:
    bot.set_config(speed=70, home_x=-12.5)
    cfg = bot.get_config()
    assert cfg["speed"] == 70
    assert cfg["home_x"] == pytest.approx(-12.5)
    bot.set_config(grip_ms=400)
    cfg2 = bot.get_config()
    assert cfg2["speed"] == 70  # не затёрто
    assert cfg2["grip_ms"] == 400


def test_set_config_marker_last(bot: RobotClient, transport: FakeRobotTransport) -> None:
    bot.set_config(speed=55)
    ops = transport.transactions[-1]
    assert ops[-1] == ("w", 0x1300, 1)  # cfg_flag — последним


def test_set_config_unknown_field(bot: RobotClient) -> None:
    with pytest.raises(KeyError, match="Неизвестный параметр"):
        bot.set_config(warp_speed=9)


def test_config_helpers(bot: RobotClient) -> None:
    bot.set_speed(45)
    bot.set_home(1.0, 2.0, 3.0)
    bot.set_place(-4.0, 5.5, 6.0)
    bot.set_pick_z(-7.5)
    bot.set_zone(300.0, 50.0)
    bot.set_grip_time(0.25)
    cfg = bot.get_config()
    assert cfg["speed"] == 45
    assert cfg["place_y"] == pytest.approx(5.5)
    assert cfg["pick_z"] == pytest.approx(-7.5)
    assert cfg["zone_min"] == pytest.approx(50.0)
    assert cfg["grip_ms"] == 250


def test_set_speed_range(bot: RobotClient) -> None:
    with pytest.raises(ValueError):
        bot.set_speed(0)


# --- рисование ---


def test_draw_circle_completes(bot: RobotClient, transport: FakeRobotTransport) -> None:
    assert bot.draw_circle(10.0, 20.0, 5.0)
    ops = transport.transactions[-1]
    assert ops[-1] == ("w", REG_DRAW_FLAG, 1)  # маркер последним
    assert ("w", 0x1406, 100) in ops  # cx*10


def test_draw_polyline_chunked_upload(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """15 точек = 45 регистров -> чанки 30+15; затем запуск прохода."""
    pts = [DrawPoint(float(i), float(-i), 1) for i in range(15)]
    assert bot.draw(pts)
    uploads = [ops for ops in transport.transactions if ops[0][0] == "wm" and ops[0][1] >= REG_PTS_BASE]
    sizes = [len(ops[0][2]) for ops in uploads]
    assert sizes == [WRITE_CHUNK, 15]  # 45 регистров: 30 + 15
    assert uploads[1][0][1] == REG_PTS_BASE + WRITE_CHUNK  # смещение второго чанка


def test_draw_batches_over_pts_max(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """101 точка -> два прохода (PTS_MAX=100), оба завершаются."""
    progress: list[dict] = []
    bot._on_progress = progress.append
    pts = [DrawPoint(float(i % 50), 0.0, 1) for i in range(101)]
    assert bot.draw(pts)
    batches = [p for p in progress if p.get("stage") == "batch"]
    assert len(batches) == 2
    assert batches[1]["done"] == 101


def test_draw_empty_raises(bot: RobotClient) -> None:
    with pytest.raises(RobotJobError, match="Пустой"):
        bot.draw([])


def test_draw_abort_clears_busy(bot: RobotClient, core: RobotSimCore) -> None:
    core.write(REG_DRAW_FLAG, [1])  # запустить «рисование» напрямую
    assert _poll(bot, bot.draw_busy)
    bot.draw_abort()
    assert _poll(bot, lambda: bot.draw_busy() is False)


def test_pen_and_draw_params(bot: RobotClient, transport: FakeRobotTransport) -> None:
    bot.set_pen(-5.0, 5.0)
    ops = transport.transactions[-1]
    assert ops[0] == ("w", 0x1410, (-50) & 0xFFFF)
    assert ops[1] == ("w", 0x1411, 50)
    bot.set_draw_speed(150)  # клампится в 100
    assert transport.transactions[-1][0] == ("w", 0x1412, 100)
    bot.set_overlap(2.5)
    assert transport.transactions[-1][0] == ("w", 0x1413, 25)
