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
    XY_SCALE,
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
    """Один штрих длиннее буфера → куски ≤100, возобновление с подводом + overlap 1."""
    from Services.robot_comm.core.datatypes import split_draw_passes

    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 250)]  # 250 одним штрихом
    passes = split_draw_passes(pts, 100)
    assert [len(p) for p in passes] == [100, 100, 54]  # overlap: куски пере-включают точку стыка
    assert passes[1][0].pen == 0 and passes[2][0].pen == 0  # подвод в точку возобновления
    # Все исходные рисующие точки покрыты (с дублями граничных точек на стыках).
    drawn_xs = {p.x_mm for batch in passes for p in batch if p.pen == 1}
    assert drawn_xs == {float(i) for i in range(1, 250)}


def _drawn_segments(passes) -> set:
    """Множество нарисованных сегментов (координатные пары) по всем проходам.

    В проходе сегмент рисуется при переходе К точке pen=1 (move к pen=0 — переезд вверх).
    """
    segs = set()
    for batch in passes:
        for j in range(1, len(batch)):
            if batch[j].pen == 1:
                a, b = batch[j - 1], batch[j]
                segs.add(((a.x_mm, a.y_mm), (b.x_mm, b.y_mm)))
    return segs


def test_long_stroke_no_segment_gap() -> None:
    """Связность: длинный штрих, разбитый на проходы, рисует КАЖДЫЙ исходный сегмент.

    Регрессия: раньше на границе прохода терялся сегмент stroke[limit-1]→stroke[limit]
    (перо вверх между проходами). Overlap-возобновление чинит это — проверяем, что все
    смежные пары исходного штриха присутствуют как нарисованные сегменты.
    """
    from Services.robot_comm.core.datatypes import split_draw_passes

    stroke = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), float(i * 2), 1) for i in range(1, 90)]  # 90 точек
    passes = split_draw_passes(stroke, 20)  # мелкий буфер → много границ
    drawn = _drawn_segments(passes)
    # Каждый исходный сегмент (s[k], s[k+1]) обязан быть нарисован.
    for k in range(len(stroke) - 1):
        a, b = stroke[k], stroke[k + 1]
        seg = ((a.x_mm, a.y_mm), (b.x_mm, b.y_mm))
        assert seg in drawn, f"потерян сегмент {k}: {seg}"


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
    bot.set_draw_travel(80)  # скорость переезда → REG_DRAW_TRAVEL (0x1415)
    assert transport.transactions[-1][0] == ("w", 0x1415, 80)
    bot.set_draw_travel(0)  # клампится в 1
    assert transport.transactions[-1][0] == ("w", 0x1415, 1)
    bot.set_draw_accel(40000)  # ускорение → REG_DRAW_ACCEL (0x1416), клампится в 32000
    assert transport.transactions[-1][0] == ("w", 0x1416, 32000)
    bot.set_overlap(2.5)
    assert transport.transactions[-1][0] == ("w", 0x1413, 25)


def test_set_pass_size_clamps_config(bot: RobotClient) -> None:
    """set_pass_size меняет draw_pass_size в конфиге (клампится в [3, PTS_MAX])."""
    from Services.robot_comm.core.registers import PTS_MAX

    bot.set_pass_size(60)
    assert bot.config.draw_pass_size == 60
    bot.set_pass_size(999)  # > PTS_MAX
    assert bot.config.draw_pass_size == PTS_MAX
    bot.set_pass_size(1)  # < 3
    assert bot.config.draw_pass_size == 3


# --- A1/A2: точность точек (мелкие пачки + read-back ACK) и Стоп (flush/home) ---


def _make_client(transport: FakeRobotTransport, clock, **cfg) -> RobotClient:
    client = RobotClient(RobotConfig(**cfg), transport=transport, clock=clock.clock, sleep=clock.sleep)
    client.connect()
    return client


def _uploaded_points(transport: FakeRobotTransport) -> list[tuple[int, int, int]]:
    """Реконструировать ВСЕ точки, залитые в буфер робота (по wm-записям REG_PTS_BASE)."""
    pts: list[tuple[int, int, int]] = []
    # Группируем по проходам: каждый проход — серия wm в REG_PTS_BASE+offset, затем маркер draw_flag.
    pass_regs: dict[int, int] = {}
    for ops in transport.transactions:
        wm = [op for op in ops if op[0] == "wm" and op[1] >= REG_PTS_BASE and op[1] < REG_PTS_BASE + 300]
        if wm:
            for _k, addr, vals in wm:
                base = addr - REG_PTS_BASE
                for j, v in enumerate(vals):
                    pass_regs[base + j] = v
        if ("w", REG_DRAW_FLAG, 1) in ops and pass_regs:
            n = (max(pass_regs) + 1) // 3
            for i in range(n):
                x, y, pen = pass_regs.get(i * 3, 0), pass_regs.get(i * 3 + 1, 0), pass_regs.get(i * 3 + 2, 0)
                pts.append((x, y, pen))
            pass_regs = {}
    return pts


def test_many_points_no_drawing_point_lost(transport: FakeRobotTransport, clock) -> None:
    """ГЛАВНОЕ: 2000 точек (мелкие пачки + verify) → НИ ОДНА рисующая точка не теряется.

    Реконструируем всё, что реально залито роботу по всем проходам, и сверяем с входом:
    каждая исходная рисующая точка (pen=1) обязана присутствовать у робота. Это прямой
    тест на опасение владельца «теряется при большом количестве».
    """
    bot = _make_client(transport, clock, draw_pass_size=30, draw_verify=True)
    # 40 штрихов по 50 точек = 2000 точек (подвод pen=0 + 49 рисующих на штрих).
    path: list[DrawPoint] = []
    for s in range(40):
        path.append(DrawPoint(float(s), 0.0, 0))
        path += [DrawPoint(float(s), float(i), 1) for i in range(1, 50)]
    assert len(path) == 40 * 50
    assert bot.draw(path)  # все проходы прошли и верифицированы

    uploaded = _uploaded_points(transport)
    # Все исходные рисующие точки (в формате регистров x*10,y*10) присутствуют у робота, по порядку.
    want_draw = [(round(p.x_mm * XY_SCALE) & 0xFFFF, round(p.y_mm * XY_SCALE) & 0xFFFF) for p in path if p.pen == 1]
    got_draw = [(x, y) for (x, y, pen) in uploaded if pen == 1]
    # Overlap-возобновление длинного штриха пере-включает точку стыка (подряд идущий дубль) —
    # схлопываем, чтобы сверить с исходной последовательностью рисующих точек.
    collapsed = [p for k, p in enumerate(got_draw) if k == 0 or p != got_draw[k - 1]]
    assert collapsed == want_draw, f"потеряны рисующие точки: got {len(collapsed)} vs want {len(want_draw)}"


def test_draw_pass_size_makes_more_passes(transport: FakeRobotTransport, clock) -> None:
    """draw_pass_size=10 на 25-точечном штрихе → 3 прохода (overlap-возобновление), все верифицированы."""
    bot = _make_client(transport, clock, draw_pass_size=10)
    progress: list[dict] = []
    bot._on_progress = progress.append
    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 25)]  # 25 одним штрихом
    assert bot.draw(pts)
    batches = [p for p in progress if p.get("stage") == "batch"]
    assert [b["size"] for b in batches] == [10, 10, 9]  # 25 + overlap-дубли на стыках (1+9, 1+8)
    assert not any(p.get("stage") in ("verify_mismatch", "verify_failed") for p in progress)


def test_draw_pass_size_clamped_to_pts_max(transport: FakeRobotTransport, clock) -> None:
    """draw_pass_size выше PTS_MAX зажимается до буфера прошивки (проход ≤ PTS_MAX)."""
    from Services.robot_comm.core.registers import PTS_MAX

    bot = _make_client(transport, clock, draw_pass_size=10_000)
    progress: list[dict] = []
    bot._on_progress = progress.append
    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 150)]  # 150 одним штрихом
    assert bot.draw(pts)
    batches = [p for p in progress if p.get("stage") == "batch"]
    assert batches and all(b["size"] <= PTS_MAX for b in batches)


def test_draw_verify_mismatch_retries_then_fails(clock) -> None:
    """Прошивка рапортует на 1 точку меньше (тихое усечение) → повтор draw_retry раз → False.

    Ловит главный путь потери: execute_path молча уменьшает count при коротком чтении буфера.
    Клиент сверяет draw_done_n с размером пачки, повторяет проход и при стойком расхождении
    прерывает рисунок (точки НЕ теряются молча).
    """
    from Services.robot_comm.core.registers import REG_DRAW_BUSY, REG_DRAW_COUNT, REG_DRAW_DONE_N

    class _ShortAckSim(RobotSimCore):
        """Sim, занижающий эхо выполненных точек на 1 при завершении прохода."""

        def _handle_draw(self) -> None:
            was_busy = self.regs[REG_DRAW_BUSY]
            super()._handle_draw()
            if was_busy == 1 and self.regs[REG_DRAW_BUSY] == 0:  # busy 1→0: проход завершён
                self.regs[REG_DRAW_DONE_N] = max(0, self.regs[REG_DRAW_COUNT] - 1)

    transport = FakeRobotTransport(_ShortAckSim())
    bot = _make_client(transport, clock, draw_retry=1)
    progress: list[dict] = []
    bot._on_progress = progress.append
    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 5)]  # 5 точек, один проход
    assert bot.draw(pts) is False
    assert sum(1 for p in progress if p.get("stage") == "verify_mismatch") == 2  # попытка + повтор
    assert any(p.get("stage") == "verify_failed" for p in progress)


def test_draw_verify_off_skips_readback(transport: FakeRobotTransport, clock) -> None:
    """draw_verify=False → проход завершается без сверки draw_done_n (старое поведение)."""
    bot = _make_client(transport, clock, draw_verify=False)
    pts = [DrawPoint(0.0, 0.0, 0)] + [DrawPoint(float(i), 0.0, 1) for i in range(1, 5)]
    assert bot.draw(pts)


def test_draw_flush_clears_control_registers(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """draw_flush обнуляет flag/count/prog/done_n, НЕ трогая draw_abort (его потребит прошивка)."""
    from Services.robot_comm.core.registers import (
        REG_DRAW_ABORT,
        REG_DRAW_COUNT,
        REG_DRAW_DONE_N,
        REG_DRAW_PROG,
    )

    assert bot.draw_flush()
    written = {a: v for (_k, a, v) in transport.transactions[-1]}
    assert written[REG_DRAW_FLAG] == 0
    assert written[REG_DRAW_COUNT] == 0
    assert written[REG_DRAW_PROG] == 0
    assert written[REG_DRAW_DONE_N] == 0
    assert REG_DRAW_ABORT not in written  # аборт остаётся вызывающему/прошивке


def test_draw_home_after_sets_flag(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """draw_home_after(True) ставит draw_home=1 (взвод заезда домой для Стопа)."""
    assert bot.draw_home_after(True)
    assert ("w", REG_DRAW_HOME, 1) in transport.transactions[-1]


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


# --- TOOLCHANGE: смена инструмента ---


def test_do_toolchange_wire_format_marker_last(bot: RobotClient, transport: FakeRobotTransport) -> None:
    """Контракт с Lua: tool_target, маркер tool_flag — ПОСЛЕДНИМ."""
    bot.do_toolchange(2)
    ops = transport.transactions[-1]
    assert ops[0] == ("w", 0x1361, 2)  # tool_target
    assert ops[1] == ("w", 0x1360, 1)  # маркер tool_flag последним


def test_do_toolchange_handshake_completes(bot: RobotClient, core: RobotSimCore) -> None:
    """do_toolchange проходит handshake (tool_flag->0 -> tool_busy 1->0) и возвращает True."""
    assert bot.do_toolchange(1) is True
    assert bot.tool_current() == 1  # sim: текущий инструмент = целевой


def test_do_toolchange_rejects_bad_target(bot: RobotClient) -> None:
    with pytest.raises(ValueError, match="toolchange target"):
        bot.do_toolchange(5)


def test_do_toolchange_updates_tool_cur(bot: RobotClient, core: RobotSimCore) -> None:
    """Последовательная смена: cur обновляется каждый раз."""
    assert bot.do_toolchange(1) is True
    assert bot.tool_current() == 1
    assert bot.do_toolchange(0) is True
    assert bot.tool_current() == 0
    assert bot.do_toolchange(2) is True
    assert bot.tool_current() == 2
