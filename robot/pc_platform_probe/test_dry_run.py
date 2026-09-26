"""Сухой прогон пары probe.lua ↔ pc_probe.py: настоящий Lua (lupa, 5.1 и 5.4) и настоящий TCP.

Что доказывает: файл probe.lua грузится и исполняется в обеих версиях Lua, каждый тест
пробы отвечает по каналу 0x1400, ПК правильно разбирает ответы, защитные правила пробы
срабатывают на сценариях, которые нашло ревью 2026-09-27.
Что НЕ доказывает: поведение контроллера Delta — заглушки знают только факты v1 и мануала RL.
Ожидаемые значения — литералы поведения заглушек dry_run.FakeRobot.

Запуск (lupa не входит в зависимости проекта):
    uv run --no-project --with lupa --with pymodbus==3.15.0 --with pytest \\
        python -m pytest robot/pc_platform_probe -q -c /dev/null
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")
HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dry_run = _load("dry_run")
pc_probe = _load("pc_probe")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(**flags):
    run = dry_run.DryRun(port=_free_port(), **flags)
    run.start()
    p = pc_probe.Probe("127.0.0.1", run.port, dry_run.UNIT)
    p.connect()
    p.wait_alive()
    return run, p


@pytest.fixture(scope="module", params=["51", "54"])
def env(request):
    run, p = _start(lua=request.param)
    p.write(0x1000, 777)  # ненулевое исходное значение: проверка восстановления не пустая
    yield run, p
    p.close()
    run.stop()


@pytest.fixture(scope="module")
def safe(env):
    return pc_probe.run_safe(env[1])


@pytest.fixture(scope="module")
def motion(env):
    mp = pytest.MonkeyPatch()
    mp.setattr("builtins.input", lambda _prompt: "yes")
    try:
        return pc_probe.run_motion(env[1])
    finally:
        mp.undo()


# ---------------- набор без движения ----------------


def test_lua_version_and_api_dump(env, safe):
    assert f"Lua 5.{env[0].lua_version[1]}" in safe.data["lua_info"]
    names = safe.globals_text.splitlines()
    assert "MovL function" in names and "ReadPoint function" in names
    assert not safe.errors


def test_mirror_idle_and_boot_facts(safe):
    # Заглушка MultiTask зовёт Mirror только во время хода — как на контроллере v1.
    assert safe.data["loop"]["mirror_idle_hz"] == 0
    assert safe.data["boot"] == {"vfd_boot_stop": "подтверждён", "pose_ok": True}


def test_clock_verdicts(safe):
    clocks = safe.data["clocks"]
    assert clocks["TimerRead"]["verdict"] == "годны (миллисекунды)"
    # os.clock в Lua — процессорное время: во время DELAY стоит. Таймер на нём не сработает.
    assert clocks["os.clock"]["verdict"].startswith("НЕ реальное время")
    assert "шаг 1 с" in clocks["os.time"]["verdict"]


def test_clock_verdict_units():
    assert pc_probe.clock_verdict(2_010_000, 2.01) == "годны (микросекунды)"
    assert pc_probe.clock_verdict(201, 2.01) == "годны (1/100 с)"
    assert pc_probe.clock_verdict(0.01, 2.0).startswith("НЕ реальное время")


def test_addresses_full_access_restored_and_missing(env, safe):
    table = safe.data["addresses"]
    full = {"pc_read": True, "pc_write": True, "lua_sees_pc": True, "pc_sees_lua": True, "restored": True}
    assert table["0x1000"] == full and table["0x3FFF"] == full
    assert table["0x4000"] == {"pc_read": False, "ro": True}
    assert env[1].read(0x1000) == [777]


def test_blocks_dw_and_second_connection(safe):
    assert safe.data["blocks"]["pc_fc16"][123] is True
    assert safe.data["blocks"]["lua_multi"][125] is True
    assert safe.data["dw_order"] == "little [lo, hi]"
    assert safe.data["atomic_lua_write"]["torn"] == 0  # заглушка пишет срезом — атомарно
    assert safe.data["second_connection"]["accepted"] is True


def test_points_axes_and_runtime_setglobal(safe):
    axes = safe.data["axes"]
    assert "RZ: принято, ReadPoint RZ=12.5 → ЗАПИСАНО" in axes
    assert "R: ошибка" in axes  # по мануалу пункта «R» нет; v1 пишет именно его
    assert safe.data["setglobal_runtime"]["all_match"] is True
    assert safe.data["local_point"]["ok"] is False and "not established" in safe.data["local_point"]["text"]


def test_rsmaster_and_vfd_bridge(safe):
    assert safe.data["rsmaster"]["vals"] == [0x2100, 0x2101, 0x2102, 0x2103]
    assert safe.data["vfd_timing"]["ok"] == 20 and safe.data["vfd_timing"]["fail"] == 0
    # Эмулятор ПЧ отвечает на FC3 значением «адрес регистра»: ответ прошёл CRC и разбор Lua.
    assert safe.data["vfd_p14"] == [0x0E00, 0x0E01, 0x0E02, 0x0E03, 0x0E04, 0x0E05]
    assert safe.data["port_reopen"]["vfd_answers"] is True


def test_error_text_and_refusals(env):
    p = env[1]
    res = p.run(17, [0x0E00, 99], text=True)
    assert res.status == 5 and res.text == "qty 1..16"
    res = p.run(4, pc_probe.text_regs("NoSuchFunction"), text=True)
    assert res.status == 4 and res.text == "NoSuchFunction: nil"


def test_answer_marker_written_last(env):
    run, p = env
    p.run(9, [pc_probe.SCRATCH, 3, 5])
    last = {item: i for i, item in enumerate(run.robot.writes)}
    assert last[("M", pc_probe.VAL0)] < last[("W", pc_probe.RES_N)] < last[("W", pc_probe.RES_STATUS)]
    assert last[("W", pc_probe.RES_STATUS)] < last[("W", pc_probe.RES_SEQ)]


def test_repeated_seq_is_not_executed_twice(env):
    p = env[1]
    seq = p.send(8, [0x1700, 111])
    assert p.wait(seq, 5).status == 1
    p.write_many(pc_probe.ARG0, [0x1700, 222])
    p.write(pc_probe.CMD_FLAG, 1)  # тот же seq, другое значение
    time.sleep(0.3)
    assert p.read(0x1700) == [111]
    p.write(0x1700, 0)


def test_new_client_never_reuses_last_answered_seq(env, monkeypatch):
    # send() сначала увеличивает seq: опасен стартовый seq = last − 1 (первый отправленный = last).
    run, p = env
    last = p.read(pc_probe.RES_SEQ)[0]
    picks = iter([(last - 2) % 60000 + 1, 4242])
    monkeypatch.setattr(pc_probe.random, "randint", lambda a, b: next(picks))
    q = pc_probe.Probe("127.0.0.1", run.port, dry_run.UNIT)
    q.connect()
    assert q.seq == 4242
    assert q.wait(q.send(8, [0x1701, 5]), 5).status == 1 and q.read(0x1701) == [5]
    q.write(0x1701, 0)
    q.close()


def test_retain_marker_roundtrip(env, tmp_path, monkeypatch):
    monkeypatch.setattr(pc_probe, "REPORTS", tmp_path)
    p = env[1]
    assert pc_probe.retain(p, "retain-write") == 0
    assert pc_probe.retain(p, "retain-check") == 0


# ---------------- движение ----------------


def test_motion_stop_really_stops(motion):
    assert not motion.errors
    assert motion.data["stop"]["mirror_saw_stop"] is True
    assert motion.data["stop"]["moved_mm_of_45"] < 45  # робот ОСТАНОВИЛСЯ, а не доехал
    assert motion.data["stop_fast"]["decl_in_mirror"] == "DecL из Mirror ок"


def test_motion_override_shared_state_unwind(motion):
    assert motion.data["override_in_mirror"]["result"] == "ок"
    speeds = motion.data["override_in_mirror"]["speed_mm_s"]
    assert speeds["после"] > 3 * speeds["до"]  # 3 % → 20 %: скорость реально выросла
    assert motion.data["shared_state"] == {"local_seen": True, "global_seen": True}
    assert motion.data["unwind"] == {"caught": True, "move_after": True, "err": ""}


def test_motion_pass_chain_and_stop_inside(motion):
    assert all(isinstance(v, float) for v in motion.data["pass_chain_s"].values())
    assert motion.data["pass_stop"]["stop_seen"] is True
    assert motion.data["pass_stop"]["interrupted"] is True
    assert motion.data["pass_stop"]["stopped_off_start_mm"] > 0.5


def test_motion_axis4(motion):
    axis = motion.data["axis4"]
    assert axis["SetGlobalPoint"]["d_rz_deg"] == 5.0 and axis["SetGlobalPoint"]["rz_after_deg"] == 0.0
    assert axis["WritePoint RZ"]["d_rz_deg"] == 5.0 and axis["WritePoint RZ"]["back_ok"] is True
    assert axis["WritePoint R"]["status"] == "ошибка теста"


def test_motion_envelope_and_limits(env, motion):
    p = env[1]
    assert p.run(29).ok  # якорь в текущей позе
    assert pc_probe.move_rel(p, 400, spd=10).vals[:1] == [1]
    res = pc_probe.move_rel(p, 400, spd=10)  # цель +80 мм от якоря
    assert res.status == 5 and res.text == "цель дальше 50 мм от якоря"
    assert pc_probe.move_rel(p, -400, spd=10).vals[:1] == [1]
    res = pc_probe.move_rel(p, 10, spd=31)
    assert res.status == 5 and res.text == "скорость вне 1..30 %"


def test_override_above_limit_refused_in_mirror(env, motion):
    p = env[1]
    assert p.run(29).ok
    start = p.live()
    seq = p.send(30, [300, 0, 0, 3])
    res, _ = pc_probe.watch_move(p, seq, action_at=0.2, action=lambda: p.write(pc_probe.CTRL + 1, 100))
    assert res.ok
    assert p.read(pc_probe.CTRL + 4) == [3]  # «выше лимита»: Override не применён
    pc_probe.go_back(p, start)


# ---------------- варианты контроллера из ревью ----------------


def test_nil_pose_forbids_motion():
    run, p = _start(nil_pose=True)
    try:
        res = p.run(29, text=True)
        assert res.status == 5 and res.text == "поза не читается — якорь не поставлен"
        res = pc_probe.move_rel(p, 200)
        assert res.status == 5 and res.text.startswith("поза не читается")
    finally:
        p.close()
        run.stop()


def test_silent_writepoint_is_caught_by_readpoint():
    # WritePoint не падает, но и не пишет: без сверки ход ушёл бы в старые координаты точки.
    run, p = _start(drop_point_writes=True)
    try:
        assert p.run(29).ok
        res = pc_probe.move_rel(p, 200)
        assert res.status == 5 and res.text.startswith("точка GL_PROBE X=")
    finally:
        p.close()
        run.stop()


def test_tearing_controller_is_reported_not_atomic():
    run, p = _start(tearing=True)
    try:
        rep = pc_probe.Report()
        pc_probe.check_atomic(p, rep)
        assert rep.data["atomic_lua_write"]["torn"] > 0
    finally:
        p.close()
        run.stop()


# ---------------- ПК-сторона ----------------


def test_report_saved_when_a_check_fails(env, tmp_path, monkeypatch):
    run, _p = env
    monkeypatch.setattr(pc_probe, "REPORTS", tmp_path)

    def boom(*_a):
        raise pc_probe.ProbeError("имитация обрыва")

    monkeypatch.setattr(pc_probe, "check_blocks", boom)
    code = pc_probe.main(["--host", "127.0.0.1", "--port", str(run.port), "--unit", str(dry_run.UNIT), "safe"])
    assert code == 3
    md = next(tmp_path.glob("*_safe/report.md")).read_text(encoding="utf-8")
    assert "## Незавершённые проверки" in md and "блоки: ProbeError: имитация обрыва" in md


def test_call_denies_motion_and_outputs(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "yes")
    for name in ("RobotServoOn", "MovL", "DO", "CVT_VelIn", "MotionStop", "WriteModbus"):
        assert pc_probe.call_allowed(name) is not None
    assert pc_probe.call_allowed("os.clock") is None


def test_text_paging_joins_bytes_before_utf8_decode(monkeypatch):
    # Кириллица — 2 байта; граница страницы в 60 байт режет букву пополам.
    text = "Ф" + "ё" * 40 + " конец"
    data = text.encode("utf-8")
    pages = [data[i : i + pc_probe.PAGE_CHARS] for i in range(0, len(data), pc_probe.PAGE_CHARS)]
    p = pc_probe.Probe("127.0.0.1", 1, 1)
    calls = []

    def fake_send(test, args=None):
        calls.append(args[0])
        return args[0]

    def fake_wait(page, _timeout):
        chunk = pages[page] + b"\0" * (len(pages[page]) % 2)
        regs = [chunk[i] * 256 + chunk[i + 1] for i in range(0, len(chunk), 2)]
        return pc_probe.Result(1, [len(data) & 0xFFFF, len(data) >> 16] + regs)

    monkeypatch.setattr(p, "send", fake_send)
    monkeypatch.setattr(p, "wait", fake_wait)
    assert p.fetch_text() == text
    assert calls == [0, 1]


def test_rz_drift_forbids_motion():
    # Точки объявлены со стартовой RZ; ушёл RZ — ход повернул бы кисть обратно без спроса.
    run, p = _start()
    try:
        assert p.run(29).ok
        run.robot.pose["R"] = -90.0  # +10° от стартовых −100°
        res = pc_probe.move_rel(p, 100)
        assert res.status == 5 and res.text == "RZ ушёл от стартового больше чем на 1°"
    finally:
        p.close()
        run.stop()


def test_go_back_aborts_suite_when_return_fails(monkeypatch):
    class FakeProbe:
        def live_fresh(self):
            return {"x": 3200, "y": -2100, "z": -400, "rz": -1000}

    refused = pc_probe.Result(5, [], text="цель дальше 50 мм от якоря")
    monkeypatch.setattr(pc_probe, "move_rel", lambda *a, **k: refused)
    with pytest.raises(pc_probe.MotionAbort, match="возврат в исходную позу не выполнен"):
        pc_probe.go_back(FakeProbe(), {"x": 3000, "y": -2100, "z": -400, "rz": -1000})


def test_motion_suite_returns_robot_to_start(env, motion):
    # Каждый go_back обязан реально вернуть робота: устаревший LIVE пропускал возврат после PASS.
    run, p = env
    assert abs(run.robot.pose["X"] - 300.0) < 0.2 and abs(run.robot.pose["R"] - (-100.0)) < 0.2


def test_rotation_refused_when_point_not_written():
    # WritePoint не пишет, оператор отвёл руку на 80 мм от стартовой позы: поворот не должен
    # ехать в старые координаты точки (−80 мм мимо оболочки).
    run, p = _start(drop_point_writes=True)
    try:
        run.robot.pose["X"] = 380.0
        assert p.run(29).ok
        res = p.run(34, pc_probe.text_regs("RZ"), text=True)
        assert res.status == 5 and res.text.startswith("до хода: точка GL_PROBE X=")
        assert run.robot.pose["X"] == 380.0
    finally:
        p.close()
        run.stop()


def test_continuous_jog_and_timer_in_mirror(motion):
    jog = motion.data["jog_cont"]
    assert jog["started"] is True and jog["text"] == "остановлено: время"
    assert 7.0 < jog["dx_mm"] < 12.0 and jog["dy_mm"] == 0.0  # 15 мм/с × 0.6 с ≈ 9 мм
    assert motion.data["timer_in_mirror"] is True


def test_continuous_jog_limits(env, motion):
    p = env[1]
    assert p.run(29).ok
    cases = (
        ([1, 25, 500], "скорость 1..20 мм/с, время 50..1000 мс"),
        ([1, 10, 2000], "скорость 1..20 мм/с, время 50..1000 мс"),
        ([3, 10, 500], "направление 1 (X+) или 2 (X-)"),
    )
    for args, text in cases:
        res = p.run(35, args, text=True)
        assert res.status == 5 and res.text == text
