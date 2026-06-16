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
    REG_DRAW_BUSY,
    REG_DRAW_FLAG,
    REG_DRAW_HOME,
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


def test_send_job_with_place_wire_format(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """place=(x,y,z,rz) → place_x/y/z/rz (s16*10) + place_flag=1; маркер job_flag — ПОСЛЕДНИМ."""
    bot.send_job(150.5, -200.3, 1234567, place=(300.0, -100.0, -90.0, 45.0))
    ops = transport.transactions[-1]
    by_addr = {op[1]: op for op in ops}
    assert by_addr[0x1140] == ("w", 0x1140, 3000)  # place_x ×10
    assert by_addr[0x1141] == ("w", 0x1141, (-1000) & 0xFFFF)  # place_y
    assert by_addr[0x1142] == ("w", 0x1142, (-900) & 0xFFFF)  # place_z
    assert by_addr[0x1143] == ("w", 0x1143, 450)  # place_rz — абсолютный R ×10
    assert by_addr[0x1144] == ("w", 0x1144, 1)  # place_flag
    assert ops[-1] == ("w", REG_JOB_FLAG, 1)  # маркер последним


def test_send_job_without_place_omits_place_regs(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Обратная совместимость: без place — place-регистры НЕ пишутся (старое поведение)."""
    bot.send_job(10.0, 20.0, 1)
    addrs = {op[1] for op in transport.transactions[-1]}
    assert 0x1144 not in addrs  # place_flag не тронут
    assert 0x1140 not in addrs


def test_send_job_rejects_place_out_of_limit(bot: RobotClient) -> None:
    with pytest.raises(RobotJobError, match="укладки"):
        bot.send_job(0.0, 0.0, 0, place=(5000.0, 0.0, 0.0, 0.0))


def test_place_job_lifecycle(bot: RobotClient, core: RobotSimCore) -> None:
    """Полный цикл place-задания: робот «кладёт» в позу укладки (x,y,z)."""
    bot.send_job(100.0, -50.0, 42, place=(250.0, -120.0, -90.0, 30.0))
    assert _poll(bot, bot.job_accepted)
    assert _poll(bot, bot.is_free)
    pos = bot.read_position()
    assert pos.x_mm == pytest.approx(250.0)  # лёг В МЕСТО укладки, не в точку съёма
    assert pos.y_mm == pytest.approx(-120.0)
    assert pos.z_mm == pytest.approx(-90.0)


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
    assert bot.set_mode("manual")
    with pytest.raises(ValueError):
        bot.set_mode("fly")


def test_set_mode_toolchange(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Режим смены инструмента пишет MODE_TOOLCHANGE (4) в регистр mode (0x1109)."""
    bot.set_mode("toolchange")
    assert transport.transactions[-1][-1] == ("w", 0x1109, 4)


# --- MANUAL: ручной jog ---


def test_jog_wire_format_marker_last(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Контракт с Lua: mode=MANUAL, abs, dX/dY (s16*10), spd, маркер man_flag — ПОСЛЕДНИМ."""
    bot.jog(15.0, -20.0, 30, absolute=False)
    ops = transport.transactions[-1]
    assert ops[0] == ("w", 0x1109, 2)  # mode = MANUAL
    assert ops[1] == ("w", 0x1346, 0)  # man_abs = относительно
    assert ops[2] == ("w", 0x1341, 150)  # dX ×10
    assert ops[3] == ("w", 0x1342, (-200) & 0xFFFF)  # dY ×10 (s16)
    assert ops[4] == ("w", 0x1343, 30)  # spd
    assert ops[-1] == ("w", 0x1340, 1)  # man_flag — маркер последним


def test_jog_absolute_flag(bot: RobotClient, transport: FakeRobotTransport) -> None:
    bot.jog(100.0, 50.0, absolute=True)
    ops = transport.transactions[-1]
    assert ("w", 0x1346, 1) in ops  # man_abs = абсолют


def test_jog_rejects_out_of_limit(bot: RobotClient) -> None:
    with pytest.raises(RobotJobError, match="вне"):
        bot.jog(5000.0, 0.0, 30)


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
    """Путь >100 точек одним длинным штрихом → несколько проходов ≤100, все завершаются."""
    progress: list[dict] = []
    bot._on_progress = progress.append
    pts = [DrawPoint(float(i % 50), 0.0, 1) for i in range(101)]
    assert bot.draw(pts)
    batches = [p for p in progress if p.get("stage") == "batch"]
    assert len(batches) == 2
    assert all(b["size"] <= 100 for b in batches)  # ни один проход не превышает буфер


def test_draw_splits_on_stroke_boundary() -> None:
    """Проходы режутся на границах штрихов: штрих не рвётся, проход начинается с подвода."""
    from Services.robot_comm.core.datatypes import split_draw_passes

    pts: list[DrawPoint] = []
    for s in range(3):  # три штриха по 60 точек (подвод pen=0 + 59 рисующих)
        pts.append(DrawPoint(float(s), 0.0, 0))
        pts += [DrawPoint(float(s), float(i), 1) for i in range(1, 60)]
    passes = split_draw_passes(pts, 100)
    # Два штриха по 60 = 120 > 100 → каждый проход = один штрих (60), а не обрезок.
    assert [len(p) for p in passes] == [60, 60, 60]
    assert all(p[0].pen == 0 for p in passes)  # проход стартует с поднятого пера


def test_draw_long_single_stroke_resumes_with_pen_up() -> None:
    """Один штрих длиннее буфера → куски ≤100, возобновление с подводом (линия не теряется)."""
    from Services.robot_comm.core.datatypes import split_draw_passes

    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 250)]  # 250 одним штрихом
    passes = split_draw_passes(pts, 100)
    assert [len(p) for p in passes] == [100, 100, 52]
    assert passes[1][0].pen == 0 and passes[2][0].pen == 0  # подвод в точку возобновления
    # Все исходные рисующие точки сохранены (250 = 100 + 99 + 51 оригинальных).
    drawn_xs = [p.x_mm for batch in passes for p in batch if p.pen == 1]
    assert drawn_xs == [float(i) for i in range(1, 250)]


def test_wait_draw_done_waits_for_slow_busy_rise(clock) -> None:
    """Регрессия: медленный старт прохода (подготовка пула >1с) НЕ считается завершением.

    Прежний _wait_draw_done ждал подъём busy лишь 1с и при медленном старте ложно
    возвращал True — клиент заливал следующий проход в буфер на лету (робот рисовал
    мешанину старого и нового пути). Теперь — приём (draw_flag→0) + реальный цикл busy 1→0.
    """

    class _SlowStart:
        """Сценарий: приём сразу, busy=0 первые ``prep`` чтений (подготовка), затем 1, затем 0."""

        def __init__(self, prep: int, draw: int) -> None:
            self.prep, self.draw = prep, draw
            self.busy_reads = 0
            self.saw_busy_high = False

        @property
        def is_connected(self) -> bool:
            return True

        def connect(self) -> bool:
            return True

        def disconnect(self) -> None: ...

        def get_status(self) -> dict:
            return {}

        def transaction(self, ops: list) -> bool:
            return True

        def read_registers(self, address: int, count: int = 1) -> list[int]:
            if address == REG_DRAW_FLAG:
                return [0]  # прошивка приняла задание
            if address == REG_DRAW_BUSY:
                i = self.busy_reads
                self.busy_reads += 1
                if i < self.prep:
                    return [0]  # подготовка пула — busy ещё не поднят
                if i < self.prep + self.draw:
                    self.saw_busy_high = True
                    return [1]  # идёт проход
                return [0]  # завершён (перо вверх + домой позади)
            return [0] * count

    # prep=150 чтений > старого окна (1с / _POLL_FAST_S=0.01 = 100) — на нём старый код ломался.
    tr = _SlowStart(prep=150, draw=5)
    bot = RobotClient(RobotConfig(), transport=tr, clock=clock.clock, sleep=clock.sleep)
    bot.connect()
    assert bot._wait_draw_done(timeout=60.0) is True
    assert tr.saw_busy_high  # дождались реального старта прохода, а не ложного завершения
    assert tr.busy_reads >= tr.prep + 1  # прошли всю фазу подготовки до подъёма busy


def test_draw_sets_home_only_on_last_pass(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """draw_home=1 только на последнем проходе (домой + серво OFF в конце); 0 — между проходами.

    Между проходами робот ждёт на месте (перо вверх), а не едет домой — заезд домой и
    серво OFF происходят один раз, по завершении всего рисунка.
    """
    pts: list[DrawPoint] = []
    for s in range(3):  # три штриха по 60 → три прохода (60,60,60)
        pts.append(DrawPoint(float(s), 0.0, 0))
        pts += [DrawPoint(float(s), float(i), 1) for i in range(1, 60)]
    assert bot.draw(pts)
    markers = [ops for ops in transport.transactions if ("w", REG_DRAW_FLAG, 1) in ops]
    assert len(markers) == 3  # три прохода
    homes = [v for ops in markers for (_k, a, v) in ops if a == REG_DRAW_HOME]
    assert homes == [0, 0, 1]  # домой только в конце рисунка


def test_draw_aborts_between_passes(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """should_abort=True между проходами → оставшиеся проходы НЕ уходят роботу (кнопка «Стоп»)."""
    pts: list[DrawPoint] = []
    for s in range(3):  # три штриха по 60 → три прохода
        pts.append(DrawPoint(float(s), 0.0, 0))
        pts += [DrawPoint(float(s), float(i), 1) for i in range(1, 60)]
    calls = {"n": 0}

    def should_abort() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # пропустить проверку перед 1-м проходом, оборвать перед 2-м

    assert bot.draw(pts, should_abort=should_abort) is False
    markers = [ops for ops in transport.transactions if ("w", REG_DRAW_FLAG, 1) in ops]
    assert len(markers) == 1  # ушёл только первый проход, остальные оборваны


def test_draw_circle_homes_after(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Круг — единственный проход → draw_home=1 (домой + серво OFF в конце)."""
    assert bot.draw_circle(10.0, 20.0, 5.0)
    marker = next(ops for ops in transport.transactions if ("w", REG_DRAW_FLAG, 1) in ops)
    assert ("w", REG_DRAW_HOME, 1) in marker


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


# --- RETURN: возврат буквы на ленту ---


def test_set_mode_return(bot: RobotClient, transport: FakeRobotTransport) -> None:
    bot.set_mode("return")
    assert transport.transactions[-1][-1] == ("w", 0x1109, 3)  # MODE_RETURN


def test_do_return_wire_format_marker_last(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Контракт с Lua: ret_x, ret_y, ret_z (s16*10), маркер ret_flag — ПОСЛЕДНИМ."""
    bot.do_return(100.0, -50.0, -90.0)
    ops = transport.transactions[-1]
    assert ops[0] == ("w", 0x1351, 1000)  # ret_x ×10
    assert ops[1] == ("w", 0x1352, (-500) & 0xFFFF)  # ret_y ×10
    assert ops[2] == ("w", 0x1353, (-900) & 0xFFFF)  # ret_z ×10
    assert ops[3] == ("w", 0x1350, 1)  # маркер ret_flag последним


def test_do_return_handshake_completes(bot: RobotClient, core: RobotSimCore) -> None:
    """do_return проходит handshake (ret_flag→0 → ret_busy↑ → ret_busy↓) и возвращает True."""
    assert bot.do_return(120.0, -60.0, -90.0) is True
    pos = bot.read_position()  # sim: позиция = координата слота забора
    assert pos.x_mm == pytest.approx(120.0)
    assert pos.y_mm == pytest.approx(-60.0)


def test_do_return_rejects_out_of_limit(bot: RobotClient) -> None:
    with pytest.raises(RobotJobError, match="возврата вне"):
        bot.do_return(5000.0, 0.0, -90.0)
