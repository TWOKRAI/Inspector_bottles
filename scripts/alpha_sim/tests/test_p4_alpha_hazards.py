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

from scripts.alpha_sim import logic as L
from scripts.alpha_sim import run_alpha as RA
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
    first = [_line(1, "W* CMD_OPCODE = 32 (CVT_JOB)"), _line(2, "W* CMD_ARGC = 10"), _line(3, "W 0x1204 = 1", n=1)]
    second = [_line(3, "W 0x1204 = 1", n=3), _line(4, "R RES_SEQ..+12 RES_SEQ = 5, RES_STATUS = 1, RES_ERRNO = 0 (ОК)")]
    acc: dict[int, dict] = {}
    L.merge_exchange_lines(acc, first)
    L.merge_exchange_lines(acc, second)  # since_seq=3: перекрытие по seq 3, у неё n выросло 1 → 3
    assert sorted(acc) == [1, 2, 3, 4]
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
        if command != "robot_exchange_log_get" or fired or world.first("sim", "send_command", "scene.sequence") is None:
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
