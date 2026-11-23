"""P4 скрипт α, чистая логика: REDS 1-7 (plans/word-layout/tasks/P4.md).

Приёмочные тесты слепого tester до кода: модуль ``scripts.alpha_sim.logic`` появляется в GREEN.
Ожидания — литералы Д3/Д4 и design.md §2.3-§2.6, не вычисленные кодом под тестом.
Импорт модуля — внутри тестов (``_L()``): до кода каждый тест красный сам, а не одной ошибкой сбора.

Предположение формата строки файла журнала обмена (в P4.md там многоточие «… robot_main: #579  disconnect»):
``#<n строки файла> <дата> <время,мс> [INFO] S.d.d.e.robot_main: #<seq> <side> <text>``
(реальный образец — T5.6 M4; ведущий #<n> — НЕ seq); у disconnect side пустой (два пробела).
"""

from __future__ import annotations

import dataclasses
import importlib
import re

import pytest


def _L():
    return importlib.import_module("scripts.alpha_sim.logic")


# --- литералы случаев (Д4, design.md §2.3-§2.6) --------------------------------------------------------------------


def _msg(letter: str, angle: float, decision: str) -> str:
    return f"WordLayoutPlugin: диск '{letter}' {angle:.1f}° → {decision}"


def _take(cell: int, y: str, r: str, k: int, n: int) -> str:
    return f"ячейка {cell}: взять(458.2,-343.0) → положить x320.0 y{y} z-132.0 r{r}° [{k}/{n}]"


def _skip(text: str) -> str:
    return f"пропуск: {text}"


_B_WORD_LINE = "WordLayoutPlugin: слово 'ПЕРЕМИРИЕ' (источник: регистр)"
_D_WORD_LINE = (
    "WordLayoutPlugin: смена слова 'ПЕРЕМИРИЕ' → 'МИР' (источник: регистр) — ячейки с нуля (было заполнено 9/9)"
)
_C_WORD_LINE = (
    "WordLayoutPlugin: смена слова 'МИР' → 'ПЕРЕМИРИЕ' (источник: регистр) — ячейки с нуля (было заполнено 3/3)"
)

_B_DISCS = [("Р", 0.0), ("А", 0.0), ("Е", 30.0), ("И", 60.0), ("Е", 90.0), ("Б", 0.0),
            ("Р", 300.0), ("Е", 330.0), ("И", 30.0), ("Е", 60.0), ("П", 90.0), ("М", 300.0)]  # fmt: skip
_B_DECISIONS = [
    _take(2, "-220.0", "0.0", 1, 9),
    _skip("нет в слове 'ПЕРЕМИРИЕ'"),
    _take(1, "-330.0", "-30.0", 2, 9),
    _take(5, "110.0", "-60.0", 3, 9),
    _take(3, "-110.0", "-90.0", 4, 9),
    _skip("нет в слове 'ПЕРЕМИРИЕ'"),
    _take(6, "220.0", "60.0", 5, 9),
    _take(8, "440.0", "30.0", 6, 9),
    _take(7, "330.0", "-30.0", 7, 9),
    _skip("ячейки 'Е' заняты (1, 3, 8)"),
    _take(0, "-440.0", "-90.0", 8, 9),
    _take(4, "0.0", "60.0", 9, 9),
]
_B_A7 = [63336, 62236, 1100, 64436, 2200, 4400, 3300, 61136, 0]
_B_A9 = [64536, 64236, 63936, 63636, 65136, 64836, 64236, 63636, 65136]
_B_REGS = {"target_word": "ПЕРЕМИРИЕ", "word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 9,
           "jobs_emitted": 9, "done": True}  # fmt: skip

_D_DISCS = [("П", 0.0), ("М", 30.0), ("Е", 0.0), ("И", 90.0), ("Р", 300.0)]
_D_DECISIONS = [
    _skip("нет в слове 'МИР'"),
    _take(0, "-440.0", "-30.0", 1, 3),
    _skip("нет в слове 'МИР'"),
    _take(1, "-330.0", "-90.0", 2, 3),
    _take(2, "-220.0", "60.0", 3, 3),
]
_D_A7 = [61136, 62236, 63336]
_D_A9 = [64236, 63636, 65136]
_D_REGS = {"target_word": "МИР", "word_norm": "МИР", "slots_total": 3, "slots_filled": 3,
           "jobs_emitted": 12, "done": True}  # fmt: skip

_C_DISCS = [("Е", 0.0), ("Е", 30.0), ("Е", 60.0), ("Е", 90.0)]
_C_DECISIONS = [
    _take(1, "-330.0", "0.0", 1, 9),
    _take(3, "-110.0", "-30.0", 2, 9),
    _take(8, "440.0", "-60.0", 3, 9),
    _skip("ячейки 'Е' заняты (1, 3, 8)"),
]
_C_A7 = [62236, 64436, 4400]
_C_A9 = [64536, 64236, 63936]
_C_REGS = {"target_word": "ПЕРЕМИРИЕ", "word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 3,
           "jobs_emitted": 15, "done": False}  # fmt: skip

_ARGS_FIXED = {0: 18178, 1: 0, 2: 4582, 3: 62106, 4: 64216, 5: 3, 6: 3200, 8: 64216}


def _job(a7: int, a9: int):
    return _L().CvtJob(args={**_ARGS_FIXED, 7: a7, 9: a9}, argc=10, res_status=1, res_errno=0)


def _inputs(word_line, discs, decisions, a7s, a9s, regs, before):
    lines = [_msg(letter, angle, dec) for (letter, angle), dec in zip(discs, decisions, strict=True)]
    return {
        "word_line": word_line,
        "lines": lines,
        "jobs": [_job(a7, a9) for a7, a9 in zip(a7s, a9s, strict=True)],
        "regs": dict(regs),
        "feed": list(discs),
        "before": before,
    }


def _b_inputs():
    return _inputs(_B_WORD_LINE, _B_DISCS, _B_DECISIONS, _B_A7, _B_A9, _B_REGS, 0)


def _d_inputs():
    return _inputs(_D_WORD_LINE, _D_DISCS, _D_DECISIONS, _D_A7, _D_A9, _D_REGS, 9)


def _c_inputs():
    return _inputs(_C_WORD_LINE, _C_DISCS, _C_DECISIONS, _C_A7, _C_A9, _C_REGS, 12)


def _judge(case_id: str, inp: dict):
    """Журнал layout как в проде: посторонние строки вокруг и между строками диска, строка слова — до первого диска."""
    msgs = ["WordLayoutPlugin: configured (word='')"]
    if inp["word_line"]:
        msgs.append(inp["word_line"])
    for i, line in enumerate(inp["lines"]):
        msgs.append(line)
        if i == 2:
            msgs.append("RobotIoPlugin: задание принято в очередь")
    return _L().judge_case(case_id, msgs, inp["jobs"], inp["regs"], inp["feed"], inp["before"])


def _cvt_block(seq: int, a7: int, a9: int, *, with_res: bool = True, res=(1, 0)) -> list[str]:
    texts = [
        f"W* CMD_SEQ = {seq}",
        "W* CMD_OPCODE = 32 (CVT_JOB)",
        "W* CMD_ARGC = 10",
        "W* CMD_ARGS[0] = 18178",
        "W* CMD_ARGS[1] = 0",
        "W* CMD_ARGS[2] = 4582",
        "W* CMD_ARGS[3] = 62106",
        "W* CMD_ARGS[4] = 64216",
        "W* CMD_ARGS[5] = 3",
        "W* CMD_ARGS[6] = 3200",
        f"W* CMD_ARGS[7] = {a7}",
        "W* CMD_ARGS[8] = 64216",
        f"W* CMD_ARGS[9] = {a9}",
        "W CMD_FLAG = 1",
    ]
    if with_res:
        texts.append(f"R RES_SEQ..+12 RES_SEQ = {seq}, RES_STATUS = {res[0]}, RES_ERRNO = {res[1]} (ОК)")
    return texts


def _has_reason(row, key: str) -> bool:
    """Причина начинается ключом поля (не префиксом другого: «r» ≠ «res_status»)."""
    return any(re.match(re.escape(key) + r"(?!\w)", reason) for reason in row.reasons)


# --- RED 1 ---------------------------------------------------------------------------------------------------------


def test_parse_disk_lines_literals() -> None:
    L = _L()
    taken = (
        "WordLayoutPlugin: диск 'Е' 30.0° → ячейка 1: взять(458.2,-343.0) → положить "
        "x320.0 y-330.0 z-132.0 r-30.0° [1/9]"
    )
    assert L.parse_layout_line(taken) == L.DiskLine(
        "Е", 30.0, 1, (458.2, -343.0), (320.0, -330.0, -132.0, -30.0), (1, 9), None
    )

    skips = [
        ("А", 0.0, "нет в слове 'ПЕРЕМИРИЕ'"),
        ("Е", 90.0, "ячейки 'Е' заняты (1, 3, 8)"),
        ("Е", 0.0, "слово готово"),
        ("П", 0.0, "нет координаты забора"),
        ("Р", 0.0, "слово не задано"),
    ]
    for letter, angle, text in skips:
        got = L.parse_layout_line(_msg(letter, angle, f"пропуск: {text}"))
        assert got == L.DiskLine(letter, angle, None, None, None, None, text), text

    # взятый диск без координаты забора (require_pick False): pick None, остальное разобрано
    no_pick = "WordLayoutPlugin: диск 'П' 0.0° → ячейка 0: положить x320.0 y-440.0 z-132.0 r0.0° [1/9]"
    assert L.parse_layout_line(no_pick) == L.DiskLine("П", 0.0, 0, None, (320.0, -440.0, -132.0, 0.0), (1, 9), None)

    # не строка диска → None (пара к строкам выше: разбор не «ловит всё»)
    assert L.parse_layout_line("WordLayoutPlugin: configured (word='')") is None
    assert L.parse_layout_line(_B_WORD_LINE) is None
    assert L.parse_layout_line("RobotIoPlugin: задание принято в очередь") is None

    assert L.parse_word_line(_D_WORD_LINE) == ("МИР", "ПЕРЕМИРИЕ", 9, 9)
    assert L.parse_word_line(_C_WORD_LINE) == ("ПЕРЕМИРИЕ", "МИР", 3, 3)
    assert L.parse_word_line(_B_WORD_LINE) == ("ПЕРЕМИРИЕ", None, None, None)
    assert L.parse_word_line(taken) is None
    assert L.parse_word_line("WordLayoutPlugin: configured (word='')") is None


# --- RED 2 ---------------------------------------------------------------------------------------------------------


def test_parse_cvt_jobs_blocks() -> None:
    L = _L()
    noise = ["W 0x1204 = 1"]

    one = noise + _cvt_block(33258, 63336, 64236) + noise
    jobs = L.parse_cvt_jobs(one)
    assert len(jobs) == 1
    assert jobs[0].args[7] == 63336
    assert jobs[0].args[9] == 64236
    assert jobs[0].args[0] == 18178
    assert jobs[0].argc == 10
    assert jobs[0].res_status == 1
    assert jobs[0].res_errno == 0

    two = _cvt_block(33258, 63336, 64236) + noise + _cvt_block(33260, 62236, 63636)
    jobs = L.parse_cvt_jobs(two)
    assert [(j.args[7], j.args[9]) for j in jobs] == [(63336, 64236), (62236, 63636)]

    no_res = L.parse_cvt_jobs(_cvt_block(33258, 63336, 64236, with_res=False))
    assert len(no_res) == 1
    assert no_res[0].res_status is None
    assert no_res[0].args[7] == 63336

    # ответ привязан к своему заданию, а не к соседнему
    mixed = _cvt_block(33258, 63336, 64236, res=(0, 3)) + _cvt_block(33260, 62236, 63636)
    jobs = L.parse_cvt_jobs(mixed)
    assert [(j.res_status, j.res_errno) for j in jobs] == [(0, 3), (1, 0)]

    sc_run = [
        "W* CMD_SEQ = 33259",
        "W* CMD_OPCODE = 48 (SC_RUN)",
        "W* CMD_ARGC = 1",
        "W* CMD_ARGS[0] = 1",
        "W CMD_FLAG = 1",
        "R RES_SEQ..+12 RES_SEQ = 33259, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    ]
    assert L.parse_cvt_jobs(sc_run) == []
    # пара: SC_RUN между двумя CVT_JOB не прячет соседей и не подмешивает свои аргументы
    around = _cvt_block(33258, 63336, 64236) + sc_run + _cvt_block(33260, 62236, 63636)
    jobs = L.parse_cvt_jobs(around)
    assert [(j.args[7], j.args[9], j.argc, j.res_status) for j in jobs] == [
        (63336, 64236, 10, 1),
        (62236, 63636, 10, 1),
    ]


# --- RED 3 ---------------------------------------------------------------------------------------------------------


def test_case_b_all_pass() -> None:
    res = _judge("B", _b_inputs())
    assert res.case_id == "B"
    assert res.ok is True
    assert [r.index for r in res.rows] == list(range(1, 13))
    assert all(r.check == "disk" for r in res.rows)
    assert all(r.ok and r.reasons == () for r in res.rows), [r for r in res.rows if not r.ok]
    assert all(c.ok for c in res.checks), [c for c in res.checks if not c.ok]
    names = {c.check for c in res.checks}
    assert {"regs.word_norm", "regs.slots_total", "regs.slots_filled", "regs.jobs_emitted", "regs.done"} <= names

    assert res.rows[0].given == "Р 0.0°"
    assert res.rows[0].observed == (
        "диск 'Р' 0.0° → ячейка 2: взять(458.2,-343.0) → положить x320.0 y-220.0 z-132.0 r0.0° [1/9]"
        " | CVT_JOB ARGS[7]=63336 ARGS[9]=64536 RES=1"
    )
    assert res.rows[1].observed == "диск 'А' 0.0° → пропуск: нет в слове 'ПЕРЕМИРИЕ'"
    assert res.rows[2].given == "Е 30.0°"
    assert res.rows[11].observed == (
        "диск 'М' 300.0° → ячейка 4: взять(458.2,-343.0) → положить x320.0 y0.0 z-132.0 r60.0° [9/9]"
        " | CVT_JOB ARGS[7]=0 ARGS[9]=65136 RES=1"
    )


# --- RED 4 ---------------------------------------------------------------------------------------------------------


def _sub(i: int, old: str, new: str):
    def mut(inp: dict) -> None:
        assert old in inp["lines"][i], (old, inp["lines"][i])
        inp["lines"][i] = inp["lines"][i].replace(old, new)

    return mut


def _arg(i: int, key: int, val: int):
    def mut(inp: dict) -> None:
        job = inp["jobs"][i]
        inp["jobs"][i] = dataclasses.replace(job, args={**job.args, key: val})

    return mut


def _jobf(i: int, name: str, val: int):
    def mut(inp: dict) -> None:
        inp["jobs"][i] = dataclasses.replace(inp["jobs"][i], **{name: val})

    return mut


def _regs(key: str, val: object):
    def mut(inp: dict) -> None:
        inp["regs"][key] = val

    return mut


def _feed(i: int, val: tuple[str, float]):
    def mut(inp: dict) -> None:
        inp["feed"][i] = val

    return mut


def _drop_last(inp: dict) -> None:
    del inp["lines"][-1]


def _extra_line(inp: dict) -> None:
    inp["lines"].append(_msg("А", 0.0, _skip("нет в слове 'ПЕРЕМИРИЕ'")))


def _no_word_line(inp: dict) -> None:
    inp["word_line"] = ""


_BREAKS = [
    pytest.param(
        _sub(9, "ячейки 'Е' заняты (1, 3, 8)", "ячейки 'Е' заняты (1, 3)"), ("row", 10, "decision"), id="skip_text_10"
    ),
    pytest.param(_arg(4, 7, 4400), ("row", 7, "ARGS[7]"), id="args7_job5"),
    pytest.param(_arg(4, 9, 64536), ("row", 7, "ARGS[9]"), id="args9_job5"),
    pytest.param(_sub(6, "r60.0°", "r40.0°"), ("row", 7, "r"), id="r_line7"),
    pytest.param(_arg(0, 6, 3300), ("row", 1, "ARGS[6]"), id="args6_job1"),
    pytest.param(_jobf(0, "argc", 9), ("row", 1, "argc"), id="argc_job1"),
    pytest.param(_jobf(0, "res_status", 0), ("row", 1, "res_status"), id="res_status_job1"),
    pytest.param(_jobf(0, "res_errno", 3), ("row", 1, "res_errno"), id="res_errno_job1"),
    pytest.param(_arg(0, 2, 4700), ("row", 1, "ARGS[2]"), id="args2_job1"),
    pytest.param(_sub(0, "взять(458.2,-343.0)", "взять(458.2,-350.0)"), ("row", 1, "pick"), id="pick_line1"),
    pytest.param(_feed(2, ("И", 30.0)), ("row", 3, "feed"), id="feed_letter_disk3"),
    pytest.param(_sub(3, "→ ячейка 5:", "→ ячейка 4:"), ("row", 4, "cell"), id="cell_line4"),
    pytest.param(_sub(3, "[3/9]", "[4/9]"), ("row", 4, "progress"), id="progress_line4"),
    pytest.param(_sub(3, "y110.0", "y100.0"), ("row", 4, "place"), id="place_line4"),
    pytest.param(_sub(3, "диск 'И'", "диск 'Й'"), ("row", 4, "letter"), id="letter_line4"),
    pytest.param(_drop_last, ("check", "lines.count"), id="lines_11"),
    pytest.param(_extra_line, ("check", "lines.count"), id="lines_13"),
    pytest.param(_regs("jobs_emitted", 8), ("check", "regs.jobs_emitted"), id="regs_jobs_emitted"),
    pytest.param(_regs("done", False), ("check", "regs.done"), id="regs_done"),
    pytest.param(_regs("word_norm", "ПЕРЕМИРИ"), ("check", "regs.word_norm"), id="regs_word_norm"),
    pytest.param(_regs("slots_filled", 8), ("check", "regs.slots_filled"), id="regs_slots_filled"),
    pytest.param(_regs("slots_total", 8), ("check", "regs.slots_total"), id="regs_slots_total"),
    pytest.param(_no_word_line, ("check", "word_line"), id="no_word_line"),
]


def _assert_broken(res, target: tuple) -> None:
    assert res.ok is False
    if target[0] == "row":
        _, idx, key = target
        failed = [r.index for r in res.rows if not r.ok]
        assert failed == [idx], f"упала не только строка #{idx}: {failed}"
        row = next(r for r in res.rows if r.index == idx)
        assert _has_reason(row, key), (key, row.reasons)
    else:
        found = [c for c in res.checks if c.check == target[1]]
        assert found, f"нет проверки {target[1]} среди {[c.check for c in res.checks]}"
        assert any(not c.ok for c in found)


@pytest.mark.parametrize(("mutate", "target"), _BREAKS)
def test_case_b_each_break_fails(mutate, target) -> None:
    # пара: без поломки тот же вход проходит (RED 3), так что красный — от поломки, а не от входа
    assert _judge("B", _b_inputs()).ok is True
    inp = _b_inputs()
    mutate(inp)
    _assert_broken(_judge("B", inp), target)


def test_case_b_word_line_after_first_disk_fails() -> None:
    inp = _b_inputs()
    msgs = ["WordLayoutPlugin: configured (word='')", inp["lines"][0], inp["word_line"], *inp["lines"][1:]]
    res = _L().judge_case("B", msgs, inp["jobs"], inp["regs"], inp["feed"], inp["before"])
    assert res.ok is False
    assert any(c.check == "word_line" and not c.ok for c in res.checks)


def test_case_b_feed_checks_letter_only_not_angle() -> None:
    # решение лида после стенда: угол сети читается с шумом (до ±12°) — feed судит только БУКВУ;
    # угол держат окна r и ARGS[9]. Подача с углом дальше 0,5° от сети — PASS, Δ выводится в observed.
    for feed_angle, delta in [(30.4, None), (30.6, "-0.6"), (33.0, "-3.0"), (27.0, "+3.0")]:
        inp = _b_inputs()
        _feed(2, ("Е", feed_angle))(inp)
        res = _judge("B", inp)
        assert res.rows[2].ok is True, feed_angle
        assert res.ok is True, feed_angle
        if delta is not None:
            assert f"Δугла {delta}°" in res.rows[2].observed, res.rows[2].observed


_EDGES = [
    # окно забора (design.md §2.8, запись 23): px ∈ [454.9, 461.5], py ∈ [−344.0, −342.0]
    pytest.param(_sub(0, "взять(458.2,", "взять(454.9,"), True, "pick", id="pick_x_lo_in"),
    pytest.param(_sub(0, "взять(458.2,", "взять(454.8,"), False, "pick", id="pick_x_lo_out"),
    pytest.param(_sub(0, "взять(458.2,", "взять(461.5,"), True, "pick", id="pick_x_hi_in"),
    pytest.param(_sub(0, "взять(458.2,", "взять(461.6,"), False, "pick", id="pick_x_hi_out"),
    pytest.param(_sub(0, "-343.0)", "-344.0)"), True, "pick", id="pick_y_lo_in"),
    pytest.param(_sub(0, "-343.0)", "-344.1)"), False, "pick", id="pick_y_lo_out"),
    pytest.param(_sub(0, "-343.0)", "-342.0)"), True, "pick", id="pick_y_hi_in"),
    pytest.param(_sub(0, "-343.0)", "-341.9)"), False, "pick", id="pick_y_hi_out"),
    # r ∈ wrap180(0 − подача) ± 15,0 (временно); диск 1 — подача 0°
    pytest.param(_sub(0, "r0.0°", "r15.0°"), True, "r", id="r_hi_in"),
    pytest.param(_sub(0, "r0.0°", "r-15.0°"), True, "r", id="r_lo_in"),
    pytest.param(_sub(0, "r0.0°", "r15.1°"), False, "r", id="r_hi_out"),
    pytest.param(_sub(0, "r0.0°", "r-15.1°"), False, "r", id="r_lo_out"),
    # ARGS[2] ∈ 4549…4615, ARGS[3] ∈ 62096…62116 (design.md §2.8, запись 23)
    pytest.param(_arg(0, 2, 4549), True, "ARGS[2]", id="args2_lo_in"),
    pytest.param(_arg(0, 2, 4548), False, "ARGS[2]", id="args2_lo_out"),
    pytest.param(_arg(0, 2, 4615), True, "ARGS[2]", id="args2_hi_in"),
    pytest.param(_arg(0, 2, 4616), False, "ARGS[2]", id="args2_hi_out"),
    pytest.param(_arg(0, 3, 62096), True, "ARGS[3]", id="args3_lo_in"),
    pytest.param(_arg(0, 3, 62095), False, "ARGS[3]", id="args3_lo_out"),
    pytest.param(_arg(0, 3, 62116), True, "ARGS[3]", id="args3_hi_in"),
    pytest.param(_arg(0, 3, 62117), False, "ARGS[3]", id="args3_hi_out"),
    # ARGS[9] для 0°: 64386…64686 включительно (временно, ±150)
    pytest.param(_arg(0, 9, 64386), True, "ARGS[9]", id="args9_lo_in"),
    pytest.param(_arg(0, 9, 64385), False, "ARGS[9]", id="args9_lo_out"),
    pytest.param(_arg(0, 9, 64686), True, "ARGS[9]", id="args9_hi_in"),
    pytest.param(_arg(0, 9, 64687), False, "ARGS[9]", id="args9_hi_out"),
]


@pytest.mark.parametrize(("mutate", "expect_ok", "key"), _EDGES)
def test_case_b_window_edges(mutate, expect_ok, key) -> None:
    inp = _b_inputs()
    mutate(inp)
    res = _judge("B", inp)
    row = res.rows[0]
    assert row.ok is expect_ok, row
    assert res.ok is expect_ok
    if not expect_ok:
        assert _has_reason(row, key), (key, row.reasons)
        assert [r.index for r in res.rows if not r.ok] == [1]


# --- RED 5 ---------------------------------------------------------------------------------------------------------


def test_cases_d_c_literals() -> None:
    res_d = _judge("D", _d_inputs())
    assert res_d.ok is True, [r for r in (*res_d.rows, *res_d.checks) if not r.ok]
    assert [r.index for r in res_d.rows] == [1, 2, 3, 4, 5]
    assert res_d.rows[0].observed == "диск 'П' 0.0° → пропуск: нет в слове 'МИР'"
    assert res_d.rows[1].observed == (
        "диск 'М' 30.0° → ячейка 0: взять(458.2,-343.0) → положить x320.0 y-440.0 z-132.0 r-30.0° [1/3]"
        " | CVT_JOB ARGS[7]=61136 ARGS[9]=64236 RES=1"
    )

    res_c = _judge("C", _c_inputs())
    assert res_c.ok is True, [r for r in (*res_c.rows, *res_c.checks) if not r.ok]
    assert [r.index for r in res_c.rows] == [1, 2, 3, 4]
    assert res_c.rows[3].observed == "диск 'Е' 90.0° → пропуск: ячейки 'Е' заняты (1, 3, 8)"
    assert all("каскад" not in c.observed for c in res_c.checks)

    # C по старому прогнозу design.md:151: одно задание, jobs_emitted 13 — теперь красный
    old = _c_inputs()
    old["jobs"] = old["jobs"][:1]
    old["regs"]["jobs_emitted"] = 13
    res_old = _judge("C", old)
    assert res_old.ok is False
    assert any(c.check == "jobs.count" and not c.ok for c in res_old.checks)

    # каскад от прошлого случая: счёт сдвинут на 1 до начала случая, прирост верный — PASS с пометкой
    cascade = _c_inputs()
    cascade["before"] = 11
    cascade["regs"]["jobs_emitted"] = 14
    res_cas = _judge("C", cascade)
    chk = next(c for c in res_cas.checks if c.check == "regs.jobs_emitted")
    assert chk.ok is True
    assert "каскад от прошлого случая: литерал 15" in chk.observed
    assert res_cas.ok is True

    # пара: прирост неверный (14 при before 12 → прирост 2 ≠ 3) — FAIL
    bad = _c_inputs()
    bad["regs"]["jobs_emitted"] = 14
    res_bad = _judge("C", bad)
    assert any(c.check == "regs.jobs_emitted" and not c.ok for c in res_bad.checks)


# --- таблица CASES (Д4) --------------------------------------------------------------------------------------------

_A7 = {0: 61136, 1: 62236, 2: 63336, 3: 64436, 4: 0, 5: 1100, 6: 2200, 7: 3300, 8: 4400}
_WIN = {0: (64386, 64686), 30: (64086, 64386), 60: (63786, 64086), 90: (63486, 63786),
        300: (64986, 65286), 330: (64686, 64986)}  # fmt: skip


def _expects(spec):
    out = []
    for letter, angle, cell, progress, skip in spec:
        taken = cell is not None
        out.append(
            _L().Expect(
                letter=letter,
                angle=angle,
                cell=cell,
                progress=progress,
                skip=skip,
                args7=_A7[cell] if taken else None,
                args9=_WIN[int(angle)] if taken else None,
            )  # fmt: skip
        )
    return tuple(out)


_B_SKIP_NOT_IN = "нет в слове 'ПЕРЕМИРИЕ'"
_B_SKIP_FULL = "ячейки 'Е' заняты (1, 3, 8)"
_B_EXPECT = [
    ("Р", 0.0, 2, (1, 9), None), ("А", 0.0, None, None, _B_SKIP_NOT_IN), ("Е", 30.0, 1, (2, 9), None),
    ("И", 60.0, 5, (3, 9), None), ("Е", 90.0, 3, (4, 9), None), ("Б", 0.0, None, None, _B_SKIP_NOT_IN),
    ("Р", 300.0, 6, (5, 9), None), ("Е", 330.0, 8, (6, 9), None), ("И", 30.0, 7, (7, 9), None),
    ("Е", 60.0, None, None, _B_SKIP_FULL), ("П", 90.0, 0, (8, 9), None), ("М", 300.0, 4, (9, 9), None),
]  # fmt: skip
_D_EXPECT = [
    ("П", 0.0, None, None, "нет в слове 'МИР'"), ("М", 30.0, 0, (1, 3), None),
    ("Е", 0.0, None, None, "нет в слове 'МИР'"), ("И", 90.0, 1, (2, 3), None), ("Р", 300.0, 2, (3, 3), None),
]  # fmt: skip
_C_EXPECT = [
    ("Е", 0.0, 1, (1, 9), None), ("Е", 30.0, 3, (2, 9), None), ("Е", 60.0, 8, (3, 9), None),
    ("Е", 90.0, None, None, _B_SKIP_FULL),
]  # fmt: skip


@pytest.mark.parametrize(
    ("case_id", "word", "discs", "expect", "word_line", "jobs", "regs"),
    [
        ("B", "ПЕРЕМИРИЕ", _B_DISCS, _B_EXPECT, _B_WORD_LINE, 9,
         {"word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 9, "jobs_emitted": 9, "done": True}),
        ("D", "МИР", _D_DISCS, _D_EXPECT, _D_WORD_LINE, 3,
         {"word_norm": "МИР", "slots_total": 3, "slots_filled": 3, "jobs_emitted": 12, "done": True}),
        ("C", "ПЕРЕМИРИЕ", _C_DISCS, _C_EXPECT, _C_WORD_LINE, 3,
         {"word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 3, "jobs_emitted": 15, "done": False}),
    ],
)  # fmt: skip
def test_cases_table_literals(case_id, word, discs, expect, word_line, jobs, regs) -> None:
    case = _L().CASES[case_id]
    assert case.case_id == case_id
    assert case.word == word
    assert tuple((letter, float(angle)) for letter, angle in case.discs) == tuple(discs)
    assert case.expects == _expects(expect)
    assert case.word_line == word_line
    assert case.jobs == jobs
    assert case.regs == regs
    assert set(_L().CASES) == {"B", "D", "C"}


# --- RED 6 ---------------------------------------------------------------------------------------------------------


def test_angle_report_verdicts() -> None:
    L = _L()
    rep = L.angle_report([("Е", 30, 30.4), ("И", 60, 59.0), ("Р", 300, 301.0)])
    assert rep.verdict == "совпала"
    assert [r.delta for r in rep.rows] == pytest.approx([0.4, -1.0, 1.0])
    assert rep.rows[0].letter == "Е"
    assert rep.rows[0].fed == 30
    assert rep.rows[0].net == pytest.approx(30.4)
    assert rep.rows[0].delta_inv == pytest.approx(60.4)
    assert rep.rows[2].delta_inv == pytest.approx(-119.0)
    assert rep.median_delta == pytest.approx(0.4)

    inv = L.angle_report([("Е", 30, 330.0), ("И", 60, 300.0), ("Р", 300, 60.0)])
    assert inv.verdict == "инвертирована"
    assert [r.delta_inv for r in inv.rows] == pytest.approx([0.0, 0.0, 0.0])

    assert L.angle_report([("Е", 30, 120.0), ("И", 60, 150.0)]).verdict == "иное"
    assert L.angle_report([("Р", 0, 0.0), ("Б", 0, 1.0)]).verdict == "не определить"
    assert len(L.angle_report([("Р", 0, 0.0), ("Б", 0, 1.0)]).rows) == 2
    empty = L.angle_report([])
    assert empty.verdict == "не измерено"
    assert empty.median_delta is None

    assert L.wrap180(180.0) == 180.0
    assert L.wrap180(-180.0) == 180.0
    assert L.wrap180(359.6) == pytest.approx(-0.4)
    assert L.wrap180(-0.4) == pytest.approx(-0.4)
    assert L.wrap180(190.0) == pytest.approx(-170.0)
    assert L.wrap180(0.0) == 0.0


def test_angle_report_ignores_zero_and_straight_discs_and_edge() -> None:
    L = _L()
    # диски с подачей 0° и 180° в вердикте не участвуют: Р0 с мусорным углом сети не портит «совпала»
    assert L.angle_report([("Р", 0, 100.0), ("Е", 30, 30.4)]).verdict == "совпала"
    assert L.angle_report([("Р", 180, 10.0), ("Е", 30, 30.4)]).verdict == "совпала"
    # граница |Δ| ≤ 15,0 (временно): 5,1 и 15,0 — «совпала», 15,1 — «иное»
    assert L.angle_report([("Е", 30, 35.1)]).verdict == "совпала"
    assert L.angle_report([("Е", 30, 45.0)]).verdict == "совпала"
    assert L.angle_report([("Е", 30, 45.1)]).verdict == "иное"
    assert L.angle_report([("Е", 30, 30.4), ("И", 60, 74.0)]).verdict == "совпала"
    # одна пара не из совпавших ломает вердикт «все»
    assert L.angle_report([("Е", 30, 30.4), ("И", 60, 80.0)]).verdict == "иное"


# --- RED 7 ---------------------------------------------------------------------------------------------------------


def _row(ok: bool, check: str = "home"):
    return _L().Row(None, check, "", "", ok, () if ok else ("причина",))


def _case_result(ok: bool):
    return _L().CaseResult("B", (), (), ok)


def test_exit_code() -> None:
    L = _L()
    assert L.exit_code([_case_result(True), _row(True)]) == 0
    assert L.exit_code([_case_result(True), _row(False)]) == 1
    assert L.exit_code([_case_result(False), _row(True)]) == 1
    assert L.exit_code([_case_result(True), _row(True)], precondition_error=True) == 3
    assert L.exit_code([_case_result(False)], precondition_error=True) == 3


_PARK_REPLY = {"result": {"status": "ok", "robots": {"robot_main": {"result": "done", "seq": 4, "home": "moved"}}}}
_PARK_STATE = {"seq": 4, "state": "done"}
_HOME_TEXTS = ["W* CMD_OPCODE = 48 (SC_RUN)", "W* CMD_OPCODE = 65 (SERVO)", "W* CMD_ARGS[0] = 0"]


def _reply(**over):
    robot = {"result": "done", "seq": 4, "home": "moved"}
    robot.update(over.pop("robot", {}))
    result = {"status": "ok", "robots": {"robot_main": robot}}
    result.update(over)
    return {"result": result}


def test_judge_home() -> None:
    L = _L()
    row = L.judge_home(_PARK_REPLY, _PARK_STATE, _HOME_TEXTS)
    assert row.check == "home"
    assert row.index is None
    assert row.ok is True, row
    assert L.judge_home(_PARK_REPLY, _PARK_STATE, ["W* CMD_OPCODE = 48 (SC_RUN)"]).ok is False  # без SERVO

    already = _reply(robot={"home": "already"})
    servo_only = ["W* CMD_OPCODE = 65 (SERVO)", "W* CMD_ARGS[0] = 0"]
    assert L.judge_home(already, _PARK_STATE, servo_only).ok is True  # «уже дома» — SC_RUN не нужен
    assert L.judge_home(_PARK_REPLY, _PARK_STATE, servo_only).ok is False  # «moved» без SC_RUN — FAIL

    wrong_order = ["W* CMD_OPCODE = 65 (SERVO)", "W* CMD_OPCODE = 48 (SC_RUN)", "W* CMD_ARGS[0] = 0"]
    assert L.judge_home(_PARK_REPLY, _PARK_STATE, wrong_order).ok is False  # SC_RUN после SERVO
    args_first = ["W* CMD_OPCODE = 48 (SC_RUN)", "W* CMD_ARGS[0] = 0", "W* CMD_OPCODE = 65 (SERVO)"]
    assert L.judge_home(_PARK_REPLY, _PARK_STATE, args_first).ok is False  # ARGS[0] = 0 не после SERVO

    assert L.judge_home(_PARK_REPLY, _PARK_STATE, [*_HOME_TEXTS, "W STOP_REQ = 9"]).ok is False
    assert L.judge_home(_PARK_REPLY, {"seq": 3, "state": "done"}, _HOME_TEXTS).ok is False  # устаревший снимок
    assert L.judge_home(_PARK_REPLY, {"seq": 4, "state": "running"}, _HOME_TEXTS).ok is False
    assert L.judge_home(_PARK_REPLY, None, _HOME_TEXTS).ok is False
    assert L.judge_home(_reply(status="error"), _PARK_STATE, _HOME_TEXTS).ok is False
    assert L.judge_home(_reply(robot={"result": "timeout"}), _PARK_STATE, _HOME_TEXTS).ok is False
    assert L.judge_home(_reply(robot={"home": "unknown"}), _PARK_STATE, _HOME_TEXTS).ok is False


def _fl(seq: int, text: str, side: str = "in") -> str:
    return f"#{seq + 100} 2026-11-10 12:30:00,123 [INFO] S.d.d.e.robot_main: #{seq} {side} {text}"


def _fl_disc(seq: int) -> str:
    return f"#{seq + 100} 2026-11-10 12:30:00,456 [INFO] S.d.d.e.robot_main: #{seq}  disconnect"


def test_parse_exchange_file_line() -> None:
    L = _L()
    assert L.parse_exchange_file_line(_fl_disc(579)) == (579, "disconnect")
    assert L.parse_exchange_file_line(_fl(12, "W STOP_REQ = 5")) == (12, "W STOP_REQ = 5")
    assert L.parse_exchange_file_line("просто мусор без номера") is None


def test_judge_stop() -> None:
    L = _L()
    base = [_fl(600, "W STOP_REQ = 9"), _fl_disc(601)]
    row = L.judge_stop(base, 590)
    assert row.check == "stop"
    assert row.ok is True, row
    assert "стоп сделал свой park" not in row.observed

    with_park = [_fl(595, "W* CMD_OPCODE = 65 (SERVO)"), _fl(596, "W* CMD_ARGS[0] = 0"), *base]
    row = L.judge_stop(with_park, 590)
    assert row.ok is True, row
    assert "стоп сделал свой park" in row.observed

    assert L.judge_stop([_fl(600, "W STOP_REQ = 5"), _fl_disc(601)], 590).ok is True  # 5 % 4 == 1
    assert L.judge_stop([_fl(600, "W STOP_REQ = 13"), _fl_disc(601)], 590).ok is True  # 13 % 4 == 1
    two_soft = [_fl(600, "W STOP_REQ = 9"), _fl(601, "W STOP_REQ = 13"), _fl_disc(602)]
    assert L.judge_stop(two_soft, 590).ok is False
    assert L.judge_stop([_fl(600, "W STOP_REQ = 10"), _fl_disc(601)], 590).ok is False
    assert L.judge_stop([], 590).ok is False
    assert L.judge_stop([_fl(600, "W STOP_REQ = 9")], 590).ok is False  # нет disconnect после STOP_REQ
    assert L.judge_stop([_fl_disc(599), _fl(600, "W STOP_REQ = 9")], 590).ok is False  # disconnect раньше STOP_REQ

    # граница after_seq: строки с seq ≤ after_seq не считаются, seq = after_seq + 1 — считается
    assert L.judge_stop([_fl(590, "W STOP_REQ = 9"), _fl_disc(591)], 590).ok is False
    assert L.judge_stop([_fl(591, "W STOP_REQ = 9"), _fl_disc(592)], 590).ok is True
    # старый STOP_REQ из прошлого запуска (seq ≤ after_seq) вместе с новым — это одна строка, не две
    old_and_new = [_fl(3, "W STOP_REQ = 5"), _fl_disc(4), *base]
    assert L.judge_stop(old_and_new, 590).ok is True


def _shutdown(**over):
    reply = {"accepted": True, "mode": "graceful", "elapsed_s": 1.0, "timed_out": False, "unconfirmed": [],
             "pm_gone": True, "outcomes": {"layout": "exited"}}  # fmt: skip
    reply.update(over)
    return reply


_NOTE = "итог детей не виден (предел драйвера)"


def test_judge_shutdown() -> None:
    L = _L()
    row = L.judge_shutdown(_shutdown(), True)
    assert row.check == "shutdown"
    assert row.ok is True, row
    assert "layout" in row.observed
    assert "exited" in row.observed
    assert _NOTE not in row.observed
    assert L.judge_shutdown(_shutdown(unconfirmed=None), True).ok is True

    row = L.judge_shutdown(_shutdown(unconfirmed=["devices"]), True)
    assert row.ok is True, row
    assert _NOTE in row.observed
    assert "devices" in row.observed

    row = L.judge_shutdown(_shutdown(accepted=None), True)
    assert row.ok is True, row
    assert _NOTE in row.observed

    assert L.judge_shutdown(_shutdown(unconfirmed=["devices"], pm_gone=False), True).ok is False
    assert L.judge_shutdown(_shutdown(accepted=None, pm_gone=False), True).ok is False
    assert L.judge_shutdown(_shutdown(), False).ok is False  # порт не освободился
    assert L.judge_shutdown(_shutdown(timed_out=True), True).ok is False
    assert L.judge_shutdown(_shutdown(accepted=False), True).ok is False
    # FAIL сильнее пометки «итог детей не виден»
    assert L.judge_shutdown(_shutdown(accepted=False, pm_gone=True, unconfirmed=["devices"]), True).ok is False
    assert L.judge_shutdown(_shutdown(timed_out=True, pm_gone=True, unconfirmed=["devices"]), True).ok is False
    assert L.judge_shutdown(_shutdown(accepted=None, pm_gone=True), False).ok is False


def test_format_summary_and_rows() -> None:
    L = _L()
    statuses = {"B": "PASS", "D": "FAIL", "C": "PASS", "ДОМОЙ": "PASS", "СТОП": None}
    assert L.format_summary(statuses, 1) == (
        "итог: B=PASS D=FAIL C=PASS ДОМОЙ=PASS СТОП=— → код 1 (вердикт α — Task 1.2, не этот скрипт)"
    )
    all_pass = {"B": "PASS", "D": "PASS", "C": "PASS", "ДОМОЙ": "PASS", "СТОП": "PASS"}
    assert L.format_summary(all_pass, 0) == (
        "итог: B=PASS D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 0 (вердикт α — Task 1.2, не этот скрипт)"
    )

    ok_row = L.Row(3, "disk", "Е 30.0°", "диск 'Е' 30.0° → ячейка 1", True, ())
    assert L.format_row("B", ok_row) == "B #3 вход Е 30.0° → наблюдение: диск 'Е' 30.0° → ячейка 1 → PASS"
    bad_row = dataclasses.replace(ok_row, ok=False, reasons=("ARGS[7] 4400 ≠ 62236", "r вне окна"))
    assert L.format_row("B", bad_row).endswith("→ FAIL: ARGS[7] 4400 ≠ 62236; r вне окна")
    assert L.format_row("B", bad_row).startswith("B #3 вход Е 30.0° → наблюдение: ")

    check_ok = L.Row(None, "jobs.count", "", "9", True, ())
    assert L.format_row("B", check_ok) == "B jobs.count: 9 → PASS"
    check_bad = L.Row(None, "regs.done", "", "False", False, ("done False ≠ True",))
    assert L.format_row("D", check_bad) == "D regs.done: False → FAIL: done False ≠ True"


def test_regs_from_introspect() -> None:
    L = _L()
    envelope = {
        "result": {
            "success": True,
            "process": "layout",
            "registers": {"word_layout": {"target_word": "", "jobs_emitted": 0}},
        }
    }
    assert L.regs_from_introspect(envelope) == {"target_word": "", "jobs_emitted": 0}

    double = {
        "result": {
            "success": True,
            "result": {"success": True, "process": "layout", "registers": {"word_layout": {"target_word": ""}}},
        }
    }
    assert L.regs_from_introspect(double) == {"target_word": ""}

    triple = {"result": {"result": {"result": {"registers": {"word_layout": {"done": True}}}}}}
    assert L.regs_from_introspect(triple) == {"done": True}

    assert L.regs_from_introspect({}) == {}
    assert L.regs_from_introspect({"result": {"success": False}}) == {}
    assert L.regs_from_introspect({"result": {"registers": {"other": {"x": 1}}}}) == {}
