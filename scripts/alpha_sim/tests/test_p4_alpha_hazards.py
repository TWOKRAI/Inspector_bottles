"""P4 скрипт α: сторожа разработчика Г1-Г8 (plans/word-layout/tasks/P4.md, Д8).

Фейковый мир берётся у слепого tester (``test_p4_alpha_runner``): формы ответов — по Д3. Здесь — то, что
тестер не ставил: цикл опроса выходит по сроку, склейка журнала обмена, ``dropped``, ``-0.0``, политика сбоя.
Всё, что может зависнуть, идёт в daemon-потоке с ``join(timeout)``.
"""

from __future__ import annotations

import argparse
import io
import math
import threading

import pytest

from scripts.alpha_sim import logic as L
from scripts.alpha_sim import run_alpha as RA
from scripts.alpha_sim.tests import fixture_p4_stand_dump as F
from scripts.alpha_sim.tests import test_p4_alpha_logic as TL
from scripts.alpha_sim.tests import test_p4_alpha_runner as T


def _within(fn, seconds: float = 30.0):
    """Вызов в daemon-потоке с дедлайном: зависание теста не вешает прогон."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест сообщает любое падение
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout=seconds)
    assert not th.is_alive(), "вызов не вышел за дедлайн (завис)"
    assert "exc" not in box, f"вызов бросил {box.get('exc')!r}"
    return box["value"]


class _Hooked(T.World):
    """Мир тестера + перехват вызовов драйверов: ``hooks[(роль, метод)]`` подменяет ответ/бросает."""

    def __init__(self, hooks: dict | None = None, **kw) -> None:
        super().__init__(**kw)
        self.hooks = hooks or {}

    def driver_factory(self, port: int):
        drv = super().driver_factory(port)
        world = self
        for method in ("send_command", "set_register_verified", "events_page"):
            real = getattr(drv, method)

            def wrapper(*a, _real=real, _method=method, _role=drv.role, **kw):
                hook = world.hooks.get((_role, _method))
                if hook is not None:
                    out = hook(world, _real, *a, **kw)
                    if out is not NotImplemented:
                        return out
                return _real(*a, **kw)

            setattr(drv, method, wrapper)
        return drv


def _called(world: T.World, role: str, command: str, args: dict | None = None) -> int:
    return world.count(role, "send_command", command, args)


# --- Г1: цикл опроса выходит по сроку --------------------------------------------------------------------------------


def test_g1_wait_until_exits_on_deadline_with_empty_answers() -> None:
    world = T.World()
    alpha = RA._Alpha(
        argparse.Namespace(tree="/stand", log_dir=None, proto_port=8765, sim_port=8766, dump=None),
        driver_factory=world.driver_factory,
        listeners=world.listeners,
        clock=world.clock,
        sleep=world.sleep,
        out=io.StringIO(),
        read_lines=world.read_lines,
    )
    polls: list[float] = []

    def never() -> bool:
        polls.append(world.clock())
        return False

    start = world.clock()
    result = _within(lambda: alpha.wait_until("пусто", 10.0, never), 5.0)
    assert result is False
    assert 10.0 <= world.clock() - start <= 10.0 + RA.STEP + 1e-9  # вышли по сроку, а не дальше
    assert len(polls) >= 10 / RA.STEP  # опрос шёл каждый шаг, не один раз

    # пара: условие, ставшее истинным, выходит сразу — срок не доедается
    start = world.clock()
    assert _within(lambda: alpha.wait_until("сразу", 10.0, lambda: True), 5.0) is True
    assert world.clock() == start


def test_g1_layout_reader_stops_on_endlessly_empty_pages() -> None:
    pages = []

    class Drv:
        def events_page(self, plane, *, cursor=None, limit=None):
            pages.append((plane, cursor, limit))
            return {"success": True, "items": [], "next_cursor": cursor, "dropped": 0}

    reader = RA._LayoutReader(Drv())
    assert _within(reader.drain, 5.0) == []
    assert pages == [("logs", None, 500)]  # одна пустая страница — конец, лимит ≤ 500


# --- Г2, Г7: склейка журнала обмена ----------------------------------------------------------------------------------


def _line(seq: int, text: str, n: int = 1) -> dict:
    return {"seq": seq, "t": 0.0, "side": "out", "text": text, "tag": "", "n": n, "ms": 0.0}


def test_g2_merged_noise_between_blocks_does_not_break_parse() -> None:
    block = T._cvt_texts(100, 63336, 64536)
    lines = [_line(i, text) for i, text in enumerate(block, 1)]
    lines.append(_line(len(lines) + 1, "W 0x1204 = 1", n=41))  # склейка опроса: одна строка с n=41
    lines += [_line(len(lines) + 1 + i, text) for i, text in enumerate(T._cvt_texts(102, 62236, 64236))]
    acc: dict[int, dict] = {}
    L.merge_exchange_lines(acc, lines)
    jobs = L.parse_cvt_jobs([acc[s]["text"] for s in sorted(acc)])
    assert [(j.args[7], j.args[9]) for j in jobs] == [(63336, 64536), (62236, 64236)]
    assert all(j.argc == 10 and j.res_status == 1 for j in jobs)


def test_g7_overlapping_gets_replace_by_seq_not_duplicate() -> None:
    first = [
        _line(0, "W* CMD_SEQ = 5"),
        _line(1, "W* CMD_OPCODE = 32 (CVT_JOB)"),
        _line(2, "W* CMD_ARGC = 10"),
        _line(3, "W 0x1204 = 1", n=1),
    ]
    second = [_line(3, "W 0x1204 = 1", n=3), _line(4, "R RES_SEQ..+12 RES_SEQ = 5, RES_STATUS = 1, RES_ERRNO = 0 (ОК)")]
    acc: dict[int, dict] = {}
    L.merge_exchange_lines(acc, first)
    L.merge_exchange_lines(acc, second)  # since_seq=3: перекрытие по seq 3, у неё n выросло 1 → 3
    assert sorted(acc) == [0, 1, 2, 3, 4]
    assert acc[3]["n"] == 3
    jobs = L.parse_cvt_jobs([acc[s]["text"] for s in sorted(acc)])
    assert len(jobs) == 1
    assert jobs[0].res_status == 1
    # без замены (дописывание) блок задвоился бы: пара, показывающая, что проверка не вхолостую
    naive = [ln["text"] for ln in (*first, *second)]
    assert len(L.parse_cvt_jobs(naive + naive[:2])) == 2


# --- Г3: dropped журнала layout — FAIL, не PASS ----------------------------------------------------------------------


def test_g3_layout_dropped_fails_layout_log() -> None:
    state = {"seen_set": False, "fired": False}

    def events_hook(world, real, *a, **kw):
        page = real(*a, **kw)
        if world.first("proto", "set_register_verified") is not None and not state["fired"]:
            state["fired"] = True
            page = dict(page, dropped=2)  # кольцо вытеснило события между курсором и страницей
        return page

    world = _Hooked({("proto", "events_page"): events_hook})
    rc, out = T._run(world)
    assert state["fired"]
    assert rc == 1, out
    assert any(ln.startswith("B layout_log") and "FAIL" in ln for ln in out.splitlines())
    assert "B случай: FAIL" in out

    # пара: без dropped тот же прогон — PASS (красный выше — от dropped, а не от мира)
    rc_ok, out_ok = T._run(T.World())
    assert rc_ok == 0, out_ok
    assert not any("layout_log" in ln for ln in out_ok.splitlines())


# --- Г4: -0.0 --------------------------------------------------------------------------------------------------------


def test_g4_negative_zero_angle_normalized() -> None:
    line = L.parse_layout_line("WordLayoutPlugin: диск 'И' -0.0° → пропуск: слово не задано")
    assert line is not None
    assert line.angle == 0.0
    assert math.copysign(1.0, line.angle) == 1.0
    assert str(line.angle) == "0.0"
    assert L.wrap180(-0.0) == 0.0 and math.copysign(1.0, L.wrap180(-0.0)) == 1.0
    take = (
        "WordLayoutPlugin: диск 'И' -0.0° → ячейка 5: взять(458.2,-343.0) → положить x320.0 y110.0 z-132.0 r-0.0° [1/9]"
    )
    parsed = L.parse_layout_line(take)
    assert parsed is not None and math.copysign(1.0, parsed.place[3]) == 1.0


# --- Г5: сбой P0-P3 — park и shutdown не зовутся ---------------------------------------------------------------------


def _busy_sim(world, real, target, command, args, **kw):
    if command == "scene.status":
        return {
            "result": {"active": 0, "sequence": {"mode": "list", "total": 5, "fed": 2, "skipped": 0, "remaining": 3}}
        }
    return NotImplemented


def _wrong_param(world, real, target, command, args, **kw):
    if command == "robot_param_get_all":
        return {"result": {"params": {"P_PICK_RZ": {"raw": -500}}}}
    return NotImplemented


def _not_connected(world, real, target, command, args, **kw):
    if command == "state.get" and args.get("path") == "devices.state.robot_main.conn":
        return {"result": {"status": "error", "request_id": "r"}}
    return NotImplemented


def test_g5_failure_before_cases_never_parks_or_stops() -> None:
    scenarios = {
        "P0_port": _Hooked(infos={8766: RA.ListenerInfo(8766, 1, "python apps/line_sim/run.py", "/other"), 8765: None}),
        "P1_sim_busy": _Hooked({("sim", "send_command"): _busy_sim}),
        "S1_params": _Hooked({("proto", "send_command"): _wrong_param}),
        "S0_not_connected": _Hooked({("proto", "send_command"): _not_connected}),
        "P3_no_recog": _Hooked(no_recog=True),
    }
    for name, world in scenarios.items():
        rc, out = T._run(world)
        assert rc == 3, (name, out)
        assert "предусловие" in out, name
        assert _called(world, "proto", "robot_park_all") == 0, name
        assert world.count("proto", "system_shutdown") == 0, name
        assert not any(ln.startswith("cleanup: ") for ln in out.splitlines()), name
        assert world.errors == [], name


# --- Г6, Г8: сбой на случае D / в cleanup ----------------------------------------------------------------------------


_ATTEMPTS: list[str] = []  # подмена обходит журнал фейка: попытки записываем сами


def _unverified_on_d(world, real, process, register, field, value, *, timeout=None):
    _ATTEMPTS.append(value)
    if value == "МИР":
        return {"success": True, "verified": False, "found": True, "expected": value, "actual": ""}
    return NotImplemented


def test_g6_word_not_verified_on_d_cleans_up_in_order() -> None:
    _ATTEMPTS.clear()
    world = _Hooked({("proto", "set_register_verified"): _unverified_on_d})
    rc, out = T._run(world)
    assert rc == 1, out
    assert "cleanup: " in out
    assert world.errors == []
    assert _called(world, "proto", "robot_park_all") == 1
    assert world.count("proto", "system_shutdown") == 1
    park = world.first("proto", "send_command", "robot_park_all")
    shutdown = world.first("proto", "system_shutdown")
    unpause_after = [
        c for c in world.calls if c.drv == "sim" and c.method == "send_command" and c.args[1] == "scene.pause"
        and c.args[2] == {"paused": False} and c.idx > shutdown.idx
    ]  # fmt: skip
    assert park.idx < shutdown.idx
    assert len(unpause_after) == 1  # пауза сима, поставленная для D, снята ПОСЛЕ shutdown, один раз
    assert world.count("sim", "send_command", "scene.sequence", {"discs": T._D_LIST}) == 0
    assert world.count("sim", "send_command", "scene.sequence", {"discs": T._C_LIST}) == 0
    assert _ATTEMPTS == ["ПЕРЕМИРИЕ", "МИР"]  # B и D; слово C не ставили
    last = out.rstrip("\n").splitlines()[-1]
    assert last.startswith("итог: B=PASS D=FAIL C=— ") and last.endswith(
        "→ код 1 (вердикт α — Task 1.2, не этот скрипт)"
    )


_PARK_ATTEMPTS: list[str] = []


def _park_raises(world, real, target, command, args, **kw):
    if command == "robot_park_all":
        _PARK_ATTEMPTS.append(command)
        raise RuntimeError("хаб не ответил")
    return NotImplemented


def test_g8_park_exception_in_cleanup_does_not_skip_shutdown_and_unpause() -> None:
    _PARK_ATTEMPTS.clear()
    world = _Hooked({("proto", "send_command"): _park_raises}, invalid_b=True)
    rc, out = T._run(world)
    assert rc == 3, out
    assert "cleanup: " in out
    assert "ошибка" in out
    assert "RuntimeError" in out
    assert _PARK_ATTEMPTS == ["robot_park_all"]
    assert world.count("proto", "system_shutdown") == 1
    assert world.count("sim", "send_command", "scene.pause", {"paused": False}) == 1
    shutdown = world.first("proto", "system_shutdown")
    unpause = world.first("sim", "send_command", "scene.pause", lambda c: c.args[2] == {"paused": False})
    assert shutdown.idx < unpause.idx
    last = out.rstrip("\n").splitlines()[-1]
    assert "ДОМОЙ=FAIL" in last and last.endswith("→ код 3 (вердикт α — Task 1.2, не этот скрипт)")


def test_g8b_shutdown_exception_still_unpauses() -> None:
    world = _Hooked(invalid_b=True)
    real_factory = world.driver_factory

    def factory(port):
        drv = real_factory(port)
        if drv.role == "proto":

            def boom(*, wait, wait_timeout):
                drv._enter("system_shutdown", wait=wait, wait_timeout=wait_timeout)
                raise RuntimeError("PM молчит")

            drv.system_shutdown = boom
        return drv

    world.driver_factory = factory
    rc, out = T._run(world)
    assert rc == 3, out
    assert any(ln.startswith("cleanup: СТОП → ошибка RuntimeError") for ln in out.splitlines())
    assert world.count("sim", "send_command", "scene.pause", {"paused": False}) == 1


# --- Г9: dropped журнала ОБМЕНА — FAIL случая, P5/P6 всё равно идут --------------------------------------------------


def _exchange_dropped_hook(dropped: int, fired: list):
    def hook(world, real, target, command, args, **kw):
        if (
            command != "robot_exchange_log_get"
            or fired
            or world.first("sim", "send_command", "scene.sequence", lambda c: "discs" in c.args[2]) is None
        ):
            return NotImplemented
        fired.append(dropped)  # первый get посреди случая B (список уже отправлен)
        reply = real(target, command, args, **kw)
        return {"result": dict(reply["result"], dropped=dropped)}

    return hook


def test_g9_exchange_dropped_fails_case_and_still_parks_and_stops() -> None:
    fired: list = []
    world = _Hooked({("proto", "send_command"): _exchange_dropped_hook(3, fired)})
    rc, out = T._run(world)
    assert fired == [3]
    assert rc == 1, out
    lines = out.splitlines()
    assert any(ln.startswith("B exchange:") and "→ FAIL: exchange dropped 3" in ln for ln in lines), out
    assert "B случай: FAIL" in lines
    assert _called(world, "proto", "robot_park_all") == 1
    assert world.count("proto", "system_shutdown") == 1
    assert lines[-1].startswith("итог: B=FAIL D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 1")
    assert world.errors == []


def test_g9_pair_same_scene_with_zero_dropped_passes() -> None:
    # достижимость: тот же хук сработал (get посреди случая достигнут), но dropped == 0 → PASS
    fired: list = []
    world = _Hooked({("proto", "send_command"): _exchange_dropped_hook(0, fired)})
    rc, out = T._run(world)
    assert fired == [0]
    assert rc == 0, out
    assert not any(ln.startswith("B exchange") for ln in out.splitlines())
    assert "B случай: PASS" in out.splitlines()


# --- Г10: слушатель — multiprocessing-потомок (spawn_main): команда берётся у корня запуска ---------------------------

_SPAWN = "/x/Python.app/Contents/MacOS/Python -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=5)"


def _fake_tools(monkeypatch, procs: dict[int, tuple[int, str]], listener: int = 100):
    """Подмена ``_run_tool``: ``procs[pid] = (ppid, команда)``; lsof отдаёт ``listener`` и cwd ``/stand``."""
    import subprocess

    def fake(cmd):
        def done(out: str, rc: int = 0):
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

        if cmd[0] == "lsof" and "-Fp" in cmd:
            return done(f"p{listener}\n")
        if cmd[0] == "lsof":
            return done("n/stand\n")
        pid = int(cmd[-1])
        if pid not in procs:
            return done("", 1)
        ppid, command = procs[pid]
        return done(f"{command}\n" if cmd[2] == "command=" else f"  {ppid}\n")

    monkeypatch.setattr(RA, "_run_tool", fake)


def test_g10_spawn_child_takes_root_command_one_level(monkeypatch) -> None:
    _fake_tools(monkeypatch, {100: (90, _SPAWN), 90: (1, "/x/Python apps/line_sim/run.py")})
    info = _within(lambda: RA.lsof_listeners(8766), 5.0)
    assert info == RA.ListenerInfo(8766, 100, "/x/Python apps/line_sim/run.py", "/stand")


def test_g10_two_level_chain(monkeypatch) -> None:
    root = "/x/Python multiprocess_prototype/run.py letter_robot_sim --headless"
    _fake_tools(monkeypatch, {100: (90, _SPAWN), 90: (80, _SPAWN + " --multiprocessing-fork"), 80: (1, root)})
    info = _within(lambda: RA.lsof_listeners(8765), 5.0)
    assert (info.pid, info.command, info.cwd) == (100, root, "/stand")


def test_g10_root_not_found_raises_with_chain(monkeypatch) -> None:
    # цепочка из spawn_main-процессов длиннее 5 уровней и упирается в PID 1
    procs = {100 + i: (101 + i, _SPAWN) for i in range(8)}
    _fake_tools(monkeypatch, procs)
    try:
        _within(lambda: RA.lsof_listeners(8765), 5.0)
    except AssertionError as exc:  # _within упаковывает исключение вызова
        text = str(exc)
        assert "ListenerProbeError" in text and "цепочка" in text and "100:" in text
    else:
        raise AssertionError("ожидался ListenerProbeError")
    # и цикл/PID 1: родитель — init
    _fake_tools(monkeypatch, {100: (1, _SPAWN)})
    try:
        _within(lambda: RA.lsof_listeners(8765), 5.0)
    except AssertionError as exc:
        assert "ListenerProbeError" in str(exc)
    else:
        raise AssertionError("ожидался ListenerProbeError")


def test_g10_pair_plain_process_does_not_climb(monkeypatch) -> None:
    # обычный процесс без spawn_main: команда своя, к родителю не поднимаемся (родитель — «ловушка» с другим скриптом)
    _fake_tools(monkeypatch, {100: (90, "/x/Python apps/line_sim/run.py"), 90: (1, "/bin/zsh -l")})
    info = _within(lambda: RA.lsof_listeners(8766), 5.0)
    assert info.command == "/x/Python apps/line_sim/run.py"


# --- Г11: правки судьи по итогам стенда (feed — буква, выравнивание по буквам, углы по сопоставленным) -------------


def _d_missing_m() -> dict:
    """Случай D: подано П, М, Е, И, Р; сеть не дала строки для М 30° (строки П, Е, И, Р, задания И, Р)."""
    inp = TL._d_inputs()
    del inp["lines"][1]
    del inp["jobs"][0]
    return inp


def test_g11a_feed_angle_noise_passes_but_wrong_letter_fails() -> None:
    inp = TL._b_inputs()
    TL._sub(2, "диск 'Е' 30.0°", "диск 'Е' 33.0°")(inp)  # сеть +3° от подачи
    TL._sub(2, "r-30.0°", "r-33.0°")(inp)  # r в окне −30 ± 5
    res = TL._judge("B", inp)
    assert res.ok is True, [r for r in res.rows if not r.ok]
    assert "Δугла +3.0°" in res.rows[2].observed
    # пара: подана другая буква — FAIL feed именно этой строки
    bad = TL._b_inputs()
    TL._feed(2, ("И", 30.0))(bad)
    res_bad = TL._judge("B", bad)
    assert [r.index for r in res_bad.rows if not r.ok] == [3]
    assert TL._has_reason(res_bad.rows[2], "feed")


def test_g11b_missing_line_aligns_by_letters() -> None:
    res = TL._judge("D", _d_missing_m())
    failed = [r for r in res.rows if not r.ok]
    assert [r.index for r in failed] == [2]  # ровно один FAIL — у М 30,0°
    assert failed[0].reasons == ("нет строки у диска №2 (вход М 30.0°)",)
    assert [r.index for r in res.rows] == [1, 2, 3, 4, 5]
    assert next(c for c in res.checks if c.check == "lines.count").ok is False
    # лишняя строка (буквы нет в подаче) — одна FAIL «лишняя строка», остальные сопоставлены
    extra = TL._b_inputs()
    extra["lines"].insert(3, TL._msg("Щ", 12.0, TL._skip("нет в слове 'ПЕРЕМИРИЕ'")))
    res_x = TL._judge("B", extra)
    assert [(r.index, r.reasons) for r in res_x.rows if not r.ok] == [(13, ("лишняя строка",))]
    # пара: все пять строк D — как раньше, всё PASS
    assert TL._judge("D", TL._d_inputs()).ok is True


def test_g11c_angle_pairs_only_matched_letters_and_stats() -> None:
    res = TL._judge("D", _d_missing_m())
    assert res.pairs == (("П", 0.0, 0.0), ("Е", 0.0, 0.0), ("И", 90.0, 90.0), ("Р", 300.0, 300.0))
    wrong = TL._b_inputs()
    TL._sub(3, "диск 'И'", "диск 'Й'")(wrong)  # буква сети ≠ подаче: диск в конвенцию не входит
    pairs = TL._judge("B", wrong).pairs
    assert len(pairs) == 11 and ("И", 60.0, 60.0) not in pairs
    rep = L.angle_report([("Е", 30, 30.4), ("И", 60, 59.0), ("Р", 300, 301.0), ("Р", 0, 5.0)])
    assert (len(rep.rows), rep.n_used) == (4, 3)  # диск с подачей 0° в расчёте не участвует
    assert rep.median_delta == pytest.approx(0.4)
    assert rep.max_abs_delta == pytest.approx(1.0)


def _judge_fixture(case_id: str, before: int):
    jobs = [L.CvtJob(a, ac, rs, er) for a, ac, rs, er in getattr(F, f"{case_id}_JOBS")]
    return L.judge_case(
        case_id,
        getattr(F, f"{case_id}_LAYOUT"),
        jobs,
        getattr(F, f"{case_id}_REGS"),
        getattr(F, f"{case_id}_FEED"),
        before,
    )


def _keys(reasons: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(r.split(" ", 1)[0] for r in reasons)


def test_g11d_real_stand_dump_b_and_d() -> None:
    # B: те же FAIL по окнам, что в alpha_run2.out (литералы со стенда), без «feed подано … сеть …» по углам
    res_b = _judge_fixture("B", 0)
    got = {r.index: _keys(r.reasons) for r in res_b.rows if not r.ok}
    assert got == {
        3: ("pick", "ARGS[3]"),
        4: ("pick", "ARGS[3]"),
        5: ("pick", "ARGS[3]"),
        7: ("r", "ARGS[9]"),
        8: ("pick", "r", "ARGS[3]", "ARGS[9]"),
        9: ("pick", "ARGS[3]"),
        11: ("pick", "r", "ARGS[2]", "ARGS[3]", "ARGS[9]"),
        12: ("pick", "r", "ARGS[3]", "ARGS[9]"),
    }
    assert not any("feed" in reason for r in res_b.rows for reason in r.reasons)
    assert all(c.ok for c in res_b.checks)
    assert len(res_b.pairs) == 12
    rep = L.angle_report(list(res_b.pairs))
    assert rep.verdict == "иное"  # шум сети до 12°: все |Δ| ≤ 5 не выполнено
    assert rep.n_used == 9  # Р0, А0, Б0 не участвуют
    assert rep.median_delta == pytest.approx(1.6, abs=0.05)
    assert rep.max_abs_delta == pytest.approx(11.9, abs=0.05)

    # D: сеть не дала строки для М 30° — одна «нет строки», остальные сопоставлены по буквам (не сдвинуты)
    res_d = _judge_fixture("D", 9)
    failed = {r.index: r for r in res_d.rows if not r.ok}
    assert failed[2].reasons == ("нет строки у диска №2 (вход М 30.0°)",)
    assert not any(_keys(r.reasons)[:1] == ("letter",) for r in res_d.rows)
    assert [r.index for r in res_d.rows if r.ok] == [1, 3]  # П и Е (пропуски) сопоставлены и PASS
    assert {c.check for c in res_d.checks if not c.ok} >= {"lines.count", "jobs.count"}
    assert [p[0] for p in res_d.pairs] == ["П", "Е", "И", "Р"]


def test_g11e_run_prints_angle_stats() -> None:
    rc, out = T._run(T.World())
    assert rc == 0, out
    line = next(ln for ln in out.splitlines() if ln.startswith("углы: "))
    assert line.startswith("углы: совпала (в расчёте ") and "медиана Δ +0.0°" in line and "макс |Δ| 0.0°)" in line


# --- Г12: подача сима возвращается в random (P3 и конец прогона) ----------------------------------------------------

_RANDOM = {"random": True}


class _StarvedSim(_Hooked):
    """Сим после прошлого прогона: список исчерпан, спавн стоит, пока не пришёл ``{"random": true}``."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.seq = {"mode": "list", "total": 5, "fed": 5, "skipped": 0, "remaining": 0}

    def tick(self) -> None:
        stream_was_on = self.stream_on
        self.stream_on = stream_was_on and self.seq["mode"] == "random"
        super().tick()
        self.stream_on = stream_was_on


def _sim_sequence_calls(world: T.World) -> list[tuple[int, dict]]:
    return [(i, a) for i, c, a, _ in world.cmds("sim") if c == "scene.sequence"]


def test_g12_p3_sends_random_before_waiting_for_first_disk() -> None:
    world = _StarvedSim()
    rc, out = T._run(world)
    assert rc == 0, out
    first = _sim_sequence_calls(world)[0]
    assert first[1] == _RANDOM
    defect = world.first("sim", "send_command", "scene.defect_rate")
    vfd = world.first("proto", "send_command", "vfd_run")
    assert first[0] < defect.idx and first[0] < vfd.idx  # random — на входе P3, до ленты и до случая B

    # пара: тот же исчерпанный сим без random (ответ не ok) — P3 не проходит, ни park, ни shutdown
    def refuse(world, real, target, command, args, **kw):
        if command == "scene.sequence" and args == _RANDOM:
            return {"result": {"status": "error", "code": "invalid"}}
        return NotImplemented

    bad = _StarvedSim(hooks={("sim", "send_command"): refuse})
    rc_bad, out_bad = T._run(bad)
    assert rc_bad == 3, out_bad
    assert "предусловие" in out_bad and "random" in out_bad
    assert bad.count("proto", "system_shutdown") == 0 and _called(bad, "proto", "robot_park_all") == 0
    assert _called(bad, "proto", "vfd_run") == 0  # random идёт до ленты: лента не тронута
    assert "режим подачи → random" not in out_bad


def test_g12_cleanup_and_normal_end_return_random_as_last_sim_step() -> None:
    # abort на случае B (неизвестная буква): cleanup → park → shutdown → снять паузу → random последним шагом сима
    world = T.World(invalid_b=True)
    rc, out = T._run(world)
    assert rc == 3, out
    calls = _sim_sequence_calls(world)
    assert [a for _, a in calls].count(_RANDOM) == 2  # P3 и cleanup
    last_sim = max(i for i, *_ in world.cmds("sim"))
    assert calls[-1] == (last_sim, _RANDOM)
    unpause = world.first("sim", "send_command", "scene.pause", lambda c: c.args[2] == {"paused": False})
    assert unpause.idx < last_sim
    assert any(ln.startswith("cleanup: режим подачи сима") for ln in out.splitlines())
    # нормальный конец: random тоже последний вызов сима, строка «изменено» называет режим подачи
    ok_world = T.World()
    rc_ok, out_ok = T._run(ok_world)
    assert rc_ok == 0, out_ok
    ok_calls = _sim_sequence_calls(ok_world)
    assert [a for _, a in ok_calls].count(_RANDOM) == 2
    assert ok_calls[-1][0] == max(i for i, *_ in ok_world.cmds("sim"))
    changed = next(ln for ln in out_ok.splitlines() if ln.startswith("изменено в симе/на стенде: "))
    assert "режим подачи → random" in changed and "defect_rate 0.0" in changed


# --- Г13: файл журнала обмена дописывается между запусками — судим последнюю инкарнацию ------------------------------

from scripts.alpha_sim.tests import fixture_p4_stand_exchange_file as FX  # noqa: E402


def _stop_line(n: int, seq: int, text: str) -> str:
    return f"#{n} 2026-11-10 10:44:42,434 [INFO] S.d.d.e.robot_main: #{seq} {text}"


def test_g13_two_incarnations_only_last_is_judged() -> None:
    lines = [*FX.BOUNDARY, *FX.TAIL_STOP]  # прошлый запуск: STOP_REQ=5, #625; новый: STOP_REQ=9, #174
    row = L.judge_stop(lines, 168)
    assert row.ok is True, row
    assert row.observed.startswith("STOP_REQ [9]")
    assert "стоп сделал свой park" in row.observed
    # пара: две STOP_REQ уже в ПОСЛЕДНЕЙ инкарнации — по-прежнему FAIL
    twice = [
        *FX.BOUNDARY,
        *FX.TAIL_STOP[:6],
        _stop_line(268, 175, "in W STOP_REQ = 13"),
        _stop_line(273, 176, " disconnect"),
    ]
    assert L.judge_stop(twice, 168).ok is False
    # одна инкарнация — как раньше
    assert L.judge_stop(FX.TAIL_STOP, 168).ok is True
    # равный seq подряд (сжатая строка «… ×62» того же seq) — не новая инкарнация
    squeezed = [_stop_line(1, 600, "in W STOP_REQ = 9"), _stop_line(2, 600, "… ×3"), _stop_line(3, 601, " disconnect")]
    assert L.judge_stop(squeezed, 590).ok is True
    # старый STOP_REQ из прошлого запуска не засчитывается и тогда, когда новых строк нет
    assert L.judge_stop([*FX.BOUNDARY], 168).ok is False


# --- Г14: красный случай (сеть потеряла диск) не прячет следующие: хвост ждёт ФАКТИЧЕСКИ выданные задания -----


def _lossy_cases(monkeypatch) -> None:
    """B теряет диск М 300°: строк 11, заданий 8, регистры 8; D и C — суммы с учётом потери (11 и 14)."""
    import copy

    cases = copy.deepcopy(T._CASES)
    b = cases["B"]
    b["discs"], b["decisions"] = b["discs"][:-1], b["decisions"][:-1]
    b["jobs"] = b["jobs"][:-1]
    b["regs"].update(slots_filled=8, jobs_emitted=8, done=False)
    cases["D"]["regs"]["jobs_emitted"] = 11
    cases["C"]["regs"]["jobs_emitted"] = 14
    monkeypatch.setattr(T, "_CASES", cases)


class _LossyWorld(T.World):
    """Сим подал все 12 дисков B (fed 12), но сеть дала 11 строк: итог подачи — total 12 / fed 12.

    ``robot_loses_job`` — восьмое задание не доходит до робота: его строк нет в журнале обмена.
    """

    robot_loses_job = False
    _cmd_blocks = 0
    _skipping = False

    def add_ex(self, text: str, side: str = "in") -> None:
        if text.startswith("W* CMD_SEQ ="):
            self._cmd_blocks += 1
            self._skipping = self.robot_loses_job and self._cmd_blocks == 8
        if not self._skipping:
            super().add_ex(text, side)

    def release(self, case: str) -> None:
        super().release(case)
        if case == "B" and self.sched:
            last = self.sched[-1][1]

            def finish() -> None:
                last()
                self.seq = {"mode": "list", "total": 12, "fed": 12, "skipped": 0, "remaining": 0}

            self.sched[-1] = (self.sched[-1][0], finish)


def test_g14_lost_disk_in_b_does_not_hide_d_and_c(monkeypatch) -> None:
    _lossy_cases(monkeypatch)
    world = _LossyWorld()
    rc, out = T._run(world)
    lines = out.splitlines()
    assert world.errors == []
    assert "хвост по факту: 8 из 9 (случай B красный)" in lines
    assert "B случай: FAIL" in lines
    assert "D случай: PASS" in lines and "C случай: PASS" in lines  # D и C стартовали и измерены
    assert world.count("sim", "send_command", "scene.sequence", {"discs": T._D_LIST}) == 1
    assert world.count("sim", "send_command", "scene.sequence", {"discs": T._C_LIST}) == 1
    assert any(ln.startswith("B lines.count") and "FAIL" in ln for ln in lines)
    # jobs_emitted_before — факт регистра (8), не литерал B (9): D (прирост 3) без ложного FAIL regs.jobs_emitted
    assert "D regs.jobs_emitted: 11 (каскад от прошлого случая: литерал 12) → PASS" in lines
    assert not any(ln.startswith(("D regs.jobs_emitted", "C regs.jobs_emitted")) and "FAIL" in ln for ln in lines)
    assert rc == 1, out
    assert lines[-1].startswith("итог: B=FAIL D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 1")


def test_g14_pair_full_b_has_no_fact_line() -> None:
    rc, out = T._run(T.World())
    assert rc == 0, out
    assert "хвост по факту" not in out


def test_g14_pair_job_not_reached_robot_stops_before_d(monkeypatch) -> None:
    _lossy_cases(monkeypatch)  # выдано 8, до робота дошло 7
    world = _LossyWorld()
    world.robot_loses_job = True
    rc, out = T._run(world)
    assert rc == 3, out
    assert "хвост случая B: CVT_JOB 7 из 8 выданных" in out
    assert world.count("sim", "send_command", "scene.sequence", {"discs": T._D_LIST}) == 0  # D не стартовал
    assert not any(c.args[3] == "МИР" for c in world.calls if c.method == "set_register_verified")
    assert "cleanup: " in out


# --- Г15-Г20: находки ревью стадии 5 --------------------------------------------------------------------------------


def _run_kw(world: T.World, argv: list[str] | None = None, **extra):
    """Как ``T._run``, но с дополнительными именованными зависимостями ``run`` и приёмом BaseException."""
    out = io.StringIO()
    box: dict = {}

    def target() -> None:
        try:
            box["rc"] = RA.run(
                argv if argv is not None else ["--tree", T._TREE],
                driver_factory=world.driver_factory,
                listeners=world.listeners,
                clock=world.clock,
                sleep=world.sleep,
                out=out,
                read_lines=world.read_lines,
                **extra,
            )
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout=30)
    assert not th.is_alive(), "run не вышел за 30 с (завис)"
    return box, out.getvalue()


def _old_file(seq_stop: int = 282) -> list[str]:
    """Файл ПРОШЛЫХ запусков: последняя инкарнация старая, STOP_REQ и disconnect с seq > after_seq текущего прогона."""

    def fl(seq: int, text: str, n: int) -> str:
        return f"#{n} 2026-11-09 10:00:00,000 [INFO] S.d.d.e.robot_main: #{seq} {text}"

    lines = [fl(i, "in W 0x1204 = 1", 1000 + i) for i in range(1, seq_stop)]
    return [*lines, fl(seq_stop, "in W STOP_REQ = 21", 1282), fl(seq_stop + 1, " disconnect", 1283)]


def test_g15_stop_file_must_belong_to_this_run_by_mtime() -> None:
    old = _old_file()
    # без привязки (старый вызов) старый файл давал ложный PASS — теперь тот же вход при старом mtime FAIL
    stale = L.judge_stop(old, 279, file_mtime=4000.0, shutdown_at=5000.0, source="/x/robot_exchange.log")
    assert stale.ok is False
    assert stale.reasons[0].startswith("stop файл журнала не от этого запуска")
    assert "/x/robot_exchange.log" in stale.reasons[0] and "4000" in stale.reasons[0] and "5000" in stale.reasons[0]
    # пара: свежий файл (mtime ≥ shutdown − 2 с) — PASS как раньше; граница допуска 2,0 с
    assert L.judge_stop(old, 279, file_mtime=5000.5, shutdown_at=5000.0).ok is True
    assert L.judge_stop(old, 279, file_mtime=4998.0, shutdown_at=5000.0).ok is True
    assert L.judge_stop(old, 279, file_mtime=4997.9, shutdown_at=5000.0).ok is False
    assert L.judge_stop(old, 279).ok is True  # без аргументов привязки поведение прежнее


def test_g15_runner_stale_file_fails_stop_fresh_passes() -> None:
    stale_world = T.World()
    stale_world.file_lines = _old_file()
    # мир пишет в файл свои строки при shutdown — для «старого файла» подменяем чтение
    stale_world.read_lines = lambda path: _old_file()
    box, out = _run_kw(stale_world, wall_clock=lambda: 5000.0, file_mtime=lambda path: 4000.0)
    assert box.get("rc") == 1, out
    assert any(ln.startswith("СТОП stop:") and "не от этого запуска" in ln for ln in out.splitlines()), out
    fresh_world = T.World()
    box, out = _run_kw(fresh_world, wall_clock=lambda: 5000.0, file_mtime=lambda path: 5000.2)
    assert box.get("rc") == 0, out
    assert out.rstrip("\n").splitlines()[-1] == T._SUMMARY_OK


# --- Г16: пауза применена симом, а ответ потерян --------------------------------------------------------------------


def test_g16_lost_pause_reply_still_unpaused_by_cleanup() -> None:
    fired: list = []

    def lost_reply(world, real, target, command, args, **kw):
        if command == "scene.pause" and args == {"paused": True} and not fired:
            fired.append(1)
            real(target, command, args, **kw)  # сим применил паузу
            return {"result": {"status": "error", "code": "timeout"}}  # а ответ дошёл как ошибка
        return NotImplemented

    world = _Hooked({("sim", "send_command"): lost_reply})
    rc, out = T._run(world)
    assert fired and rc == 3, out
    assert world.paused is False  # cleanup снял паузу, которую сим мог применить
    assert "cleanup: пауза сима → пауза снята" in out.splitlines()


# --- Г17: Ctrl-C -----------------------------------------------------------------------------------------------------


def test_g17_keyboard_interrupt_cleans_up_and_reraises() -> None:
    fired: list = []

    def interrupt(world, real, target, command, args, **kw):
        if command == "scene.status" and world.paused and not fired:
            fired.append(1)
            raise KeyboardInterrupt
        return NotImplemented

    world = _Hooked({("sim", "send_command"): interrupt})
    box, out = _run_kw(world)
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    assert world.paused is False  # Ctrl-C на паузе не оставляет сим на паузе
    assert _called(world, "proto", "robot_park_all") == 1 and world.count("proto", "system_shutdown") == 1
    assert "cleanup: " in out


# --- Г18: незакрытая кавычка в командной строке слушателя -------------------------------------------------------------


def test_g18_unbalanced_quote_in_listener_command_is_precondition_not_traceback() -> None:
    world = T.World(infos={8766: RA.ListenerInfo(8766, 7, "node it's.js", T._TREE), 8765: None})
    box, out = _run_kw(world)
    assert box.get("rc") == 3, box
    assert [o for o in world.order if o[0] == "factory"] == []
    assert "предусловие" in out and "8766" in out


# --- Г19: ответ R относится к своему CMD_SEQ -------------------------------------------------------------------------


def _job_texts(seq: int, rs: list[tuple[int, int, int]]) -> list[str]:
    block = T._cvt_texts(seq, 63336, 64536)[:-1]  # без штатного R
    return [*block, *[f"R RES_SEQ..+12 RES_SEQ = {s}, RES_STATUS = {st}, RES_ERRNO = {er} (x)" for s, st, er in rs]]


def test_g19_response_bound_to_its_cmd_seq() -> None:
    # устаревший R (seq 99) перед ответом своего задания (seq 100: STATUS 0, ERRNO 3)
    job = L.parse_cvt_jobs(_job_texts(100, [(99, 1, 0), (100, 0, 3)]))[0]
    assert (job.res_status, job.res_errno) == (0, 3)
    # ответа своего задания нет, есть только чужой — поле отсутствует, FAIL с названной причиной
    lone = L.parse_cvt_jobs(_job_texts(100, [(99, 1, 0)]))[0]
    assert lone.res_status is None and lone.res_errno is None
    reasons = L._judge_job(L.CASES["B"].expects[0], lone)
    assert any(r.startswith("res_status") for r in reasons)
    # пара: свой ответ сразу — как раньше
    ok = L.parse_cvt_jobs(_job_texts(100, [(100, 1, 0)]))[0]
    assert (ok.res_status, ok.res_errno) == (1, 0)


# --- Г20: поздняя строка диска ---------------------------------------------------------------------------------------


class _LateLineWorld(T.World):
    def release(self, case: str) -> None:
        super().release(case)
        if case == "D":
            msg = "WordLayoutPlugin: диск 'Е' 61.0° → пропуск: слово готово"
            self.sched.append((self.t + 6.0, lambda: self.emit(msg)))


def test_g20_late_disk_line_is_printed_and_dumped(tmp_path) -> None:
    dump = tmp_path / "dump.json"
    world = _LateLineWorld()
    box, out = _run_kw(world, ["--tree", T._TREE, "--dump", str(dump)])
    assert box.get("rc") == 0, out  # на код выхода не влияет
    assert "INFO поздняя строка диска после случая D: WordLayoutPlugin: диск 'Е' 61.0° → пропуск: слово готово" in out
    import json

    data = json.loads(dump.read_text(encoding="utf-8"))
    assert data["late_disk_lines"] == [
        {"after": "D", "message": "WordLayoutPlugin: диск 'Е' 61.0° → пропуск: слово готово"}
    ]
    # пара: без поздней строки такой строки нет
    _, out_ok = _run_kw(T.World())
    assert "поздняя строка" not in out_ok
