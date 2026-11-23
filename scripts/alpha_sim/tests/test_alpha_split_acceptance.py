"""alpha_sim, Task A (расщепление α): слепые приёмочные тесты REDS п.1-3.

Задача: plans/release-1.0/lane-tasks/alpha-hard-split.md.

Написаны по разделам DESIGN / REDS / ACCEPTANCE задачи, без чтения ``logic.py`` и ``run_alpha.py``.
Фейки берутся из существующих тестов: ``test_p4_alpha_runner`` (мир), ``test_p4_alpha_hazards`` (``_Hooked``,
``_run_kw``, ``_busy_sim``, ``_park_raises``, ``_old_file``), ``test_p4_alpha_logic`` (входы ``judge_case``).
Ожидаемые значения - литералы из задачи. Любой прогон ``run`` идёт в daemon-потоке с дедлайном 30 с (``_run_kw``).

Допущения теста (не контракт, см. отчёт):
- текст пропуска ниже порога: ``пропуск: уверенность ниже порога (И 0.43 < 0.50)`` /
  ``(Е 0.31 < порог ml_inference)``; формат берётся из ``C-86a`` (``<label> <confidence> < <порог>``);
- строка «нет предсказания»: ``диск '?' 0.0° → пропуск: нет предсказания`` (буква ``?`` и угол 0.0 - из задачи);
- у записи ``CaseResult.hard`` читаются только ключи ``index`` и ``hard_reasons``; полная форма записи
  проверяется по файлу ``--hard-out``.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from scripts.alpha_sim import logic as L
from scripts.alpha_sim.tests import test_p4_alpha_hazards as H
from scripts.alpha_sim.tests import test_p4_alpha_logic as TL
from scripts.alpha_sim.tests import test_p4_alpha_runner as T

MECH = "МЕХАНИЗМ"
ACC = "ТОЧНОСТЬ"
_SUMMARY_TAIL = "(вердикт α — Task 1.2, не этот скрипт)"
_BELOW = "уверенность ниже порога (И 0.43 < 0.50)"


# =====================================================================================================================
# judge_case: входы и разбор результата
# =====================================================================================================================


def _judge(case_id: str, inp: dict, **kw):
    """Как ``TL._judge`` (посторонние строки вокруг строк диска), но с новыми именованными параметрами."""
    msgs = ["WordLayoutPlugin: configured (word='')"]
    if inp["word_line"]:
        msgs.append(inp["word_line"])
    for i, line in enumerate(inp["lines"]):
        msgs.append(line)
        if i == 2:
            msgs.append("RobotIoPlugin: задание принято в очередь")
    return L.judge_case(case_id, msgs, inp["jobs"], inp["regs"], inp["feed"], inp["before"], **kw)


def _apply(inp: dict, *muts) -> dict:
    for mut in muts:
        mut(inp)
    return inp


def _row(res, idx: int):
    return next(r for r in res.rows if r.index == idx)


def _chk(res, name: str):
    return next(c for c in res.checks if c.check == name)


def _row_klass(res) -> dict[int, str | None]:
    return {r.index: r.klass for r in res.rows if not r.ok}


def _chk_klass(res) -> dict[str, str | None]:
    return {c.check: c.klass for c in res.checks if not c.ok}


def _hard(res) -> list[tuple[int, list[str]]]:
    return [(h["index"], list(h["hard_reasons"])) for h in res.hard]


def _b_lost_last() -> dict:
    """B: диск 12 (М 300°) сеть прочла как «И» 125,8°, уверенность 0,43 < 0,50: пропуск «ниже порога» (B#12 стенда)."""
    inp = TL._b_inputs()
    inp["lines"][11] = TL._msg("И", 125.8, TL._skip(_BELOW))
    inp["jobs"] = inp["jobs"][:-1]
    inp["regs"].update(slots_filled=8, jobs_emitted=8, done=False)
    return inp


def _d_lost_mid() -> dict:
    """D: диск №2 («М» 30°) без предсказания; И и Р берут ячейки 1 и 2 с progress на 1 меньше ([1/3], [2/3])."""
    inp = TL._d_inputs()
    inp["lines"][1] = TL._msg("?", 0.0, TL._skip("нет предсказания"))
    inp["lines"][3] = TL._msg("И", 90.0, TL._take(1, "-330.0", "-90.0", 1, 3))
    inp["lines"][4] = TL._msg("Р", 300.0, TL._take(2, "-220.0", "60.0", 2, 3))
    inp["jobs"] = inp["jobs"][1:]
    inp["regs"].update(slots_filled=2, jobs_emitted=11, done=False)
    return inp


# =====================================================================================================================
# REDS п.1. A1: каскад word_line (judge_case, prev_filled)
# =====================================================================================================================

_D_LINE_8 = TL._D_WORD_LINE.replace("9/9", "8/9")


def _d_with_line(line: str) -> dict:
    inp = TL._d_inputs()
    inp["word_line"] = line
    return inp


def test_a1_d_line_with_filled_8_passes_when_prev_filled_8() -> None:
    res = _judge("D", _d_with_line(_D_LINE_8), prev_filled=8)
    assert _chk(res, "word_line").ok is True
    assert res.ok is True, [r for r in (*res.rows, *res.checks) if not r.ok]
    # пара: то же без prev_filled (None) - литерал «9/9», строка «8/9» красная
    res_none = _judge("D", _d_with_line(_D_LINE_8), prev_filled=None)
    assert _chk(res_none, "word_line").ok is False
    assert res_none.ok is False


def test_a1_none_means_literal_as_today() -> None:
    res = _judge("D", TL._d_inputs(), prev_filled=None)  # литерал «9/9»
    assert res.ok is True, [r for r in (*res.rows, *res.checks) if not r.ok]
    # пара: prev_filled=8, а строка с литералом 9/9 - красная
    assert _chk(_judge("D", TL._d_inputs(), prev_filled=8), "word_line").ok is False


@pytest.mark.parametrize("prev_filled", [None, 8, 9])
def test_a1_other_word_change_fails_for_any_prev_filled(prev_filled) -> None:
    same = (
        "WordLayoutPlugin: смена слова 'ПЕРЕМИРИЕ' → 'ПЕРЕМИРИЕ' (источник: регистр) — "
        "ячейки с нуля (было заполнено 8/9)"
    )
    assert _chk(_judge("D", _d_with_line(same), prev_filled=prev_filled), "word_line").ok is False


def test_a1_c_line_for_case_d_fails_even_if_k_matches() -> None:
    # строка смены «МИР → ПЕРЕМИРИЕ» (с k=3 = prev_filled) у случая D - другая смена слова
    res = _judge("D", _d_with_line(TL._C_WORD_LINE), prev_filled=3)
    assert _chk(res, "word_line").ok is False


def test_a1_n_is_literal_not_taken_from_prev_filled() -> None:
    bad_n = TL._D_WORD_LINE.replace("9/9", "8/8")
    assert _chk(_judge("D", _d_with_line(bad_n), prev_filled=8), "word_line").ok is False


def test_a1_k9_with_prev_filled_8_fails() -> None:
    assert _chk(_judge("D", TL._d_inputs(), prev_filled=8), "word_line").ok is False  # k=9 в строке, 8 в регистре
    # пара: prev_filled=9 - та же строка проходит
    assert _chk(_judge("D", TL._d_inputs(), prev_filled=9), "word_line").ok is True


def test_a1_case_c_follows_prev_filled_of_d() -> None:
    c2 = TL._C_WORD_LINE.replace("3/3", "2/3")
    inp_2 = TL._c_inputs()
    inp_2["word_line"] = c2
    assert _chk(_judge("C", inp_2, prev_filled=2), "word_line").ok is True
    assert _chk(_judge("C", inp_2, prev_filled=None), "word_line").ok is False  # литерал 3/3
    assert _chk(_judge("C", inp_2, prev_filled=3), "word_line").ok is False  # k=2 ≠ 3
    # литерал с prev_filled=2 - красный; с None - зелёный
    assert _chk(_judge("C", TL._c_inputs(), prev_filled=2), "word_line").ok is False
    assert _chk(_judge("C", TL._c_inputs(), prev_filled=None), "word_line").ok is True


def test_a1_case_b_ignores_prev_filled() -> None:
    for prev in (None, 5, 9):
        res = _judge("B", TL._b_inputs(), prev_filled=prev)
        assert _chk(res, "word_line").ok is True, prev
        assert res.ok is True, prev


# =====================================================================================================================
# REDS п.2. A2 на judge_case: класс строк и проверок
# =====================================================================================================================


def test_a2_pass_has_no_klass_and_unrecognized_zero() -> None:
    res = _judge("B", TL._b_inputs())
    assert res.ok is True
    assert all(r.klass is None for r in (*res.rows, *res.checks))
    assert res.unrecognized == 0
    assert tuple(res.hard) == ()


def test_a2_unrecognized_last_disc_below_threshold_is_accuracy_with_cascade_checks() -> None:
    res = _judge("B", _b_lost_last())
    assert res.unrecognized == 1
    assert _row_klass(res) == {12: ACC}
    assert _chk_klass(res) == {
        "jobs.count": ACC,
        "regs.slots_filled": ACC,
        "regs.jobs_emitted": ACC,
        "regs.done": ACC,
    }
    # PASS-строки и PASS-проверки без класса
    assert all(r.klass is None for r in (*res.rows, *res.checks) if r.ok)
    assert _hard(res) == [(12, ["class_mismatch", "below_threshold", "angle"])]


def test_a2_unrecognized_by_letter_key_and_by_feed_key() -> None:
    # причина с ключом letter: сеть прочла «Й» вместо «И» (диск 4)
    res_l = _judge("B", _apply(TL._b_inputs(), TL._sub(3, "диск 'И'", "диск 'Й'")))
    assert _row_klass(res_l) == {4: ACC}
    assert res_l.unrecognized == 0  # ячейка взята, как в литерале: счёт не сдвинут (редакция 4)
    # причина с ключом feed: подана другая буква (диск 3)
    res_f = _judge("B", _apply(TL._b_inputs(), TL._feed(2, ("И", 30.0))))
    assert _row_klass(res_f) == {3: ACC}
    assert res_f.unrecognized == 0  # то же: решение «взят» совпало (редакция 4)
    # пара: без этих причин - ни непризнанных, ни FAIL-строк
    assert _judge("B", TL._b_inputs()).unrecognized == 0


def test_a2_unrecognized_without_prediction_whole_row_accuracy_even_with_other_reasons() -> None:
    res = _judge("D", _d_lost_mid())
    assert res.unrecognized == 1
    assert _row_klass(res) == {2: ACC, 4: ACC, 5: ACC}  # №4 и №5 - каскад progress
    assert _chk_klass(res) == {
        "jobs.count": ACC,
        "regs.slots_filled": ACC,
        "regs.jobs_emitted": ACC,
        "regs.done": ACC,
    }
    assert _hard(res) == [(2, ["no_prediction"])]


def test_a2_progress_cascade_limited_by_unrecognized_before() -> None:
    # progress на 2 меньше при одном непризнанном раньше - МЕХАНИЗМ, а на 1 меньше - ТОЧНОСТЬ
    inp = _d_lost_mid()
    inp["lines"][4] = TL._msg("Р", 300.0, TL._take(2, "-220.0", "60.0", 1, 3))  # [1/3] вместо [3/3]
    res = _judge("D", inp)
    assert _row_klass(res)[5] == MECH
    assert _row_klass(res)[4] == ACC
    assert _row_klass(res)[2] == ACC


def test_a2_progress_cascade_requires_equal_n() -> None:
    inp = _d_lost_mid()
    inp["lines"][3] = TL._msg("И", 90.0, TL._take(1, "-330.0", "-90.0", 1, 4))  # n=4 вместо 3
    assert _row_klass(_judge("D", inp))[4] == MECH


def test_a2_progress_off_by_one_without_unrecognized_before_is_mechanism() -> None:
    inp = TL._d_inputs()
    inp["lines"][3] = TL._msg("И", 90.0, TL._take(1, "-330.0", "-90.0", 1, 3))  # [1/3] вместо [2/3], потерь раньше нет
    res = _judge("D", inp)
    assert res.unrecognized == 0
    assert _row_klass(res) == {4: MECH}


@pytest.mark.parametrize(
    ("muts", "idx", "expected"),
    [
        pytest.param((TL._sub(0, "взять(458.2,-343.0)", "взять(458.2,-350.0)"),), 1, MECH, id="pick_right_letter"),
        pytest.param((TL._sub(3, "→ ячейка 5:", "→ ячейка 4:"),), 4, MECH, id="cell"),
        pytest.param((TL._sub(3, "y110.0", "y100.0"),), 4, MECH, id="place"),
        pytest.param((TL._sub(9, "ячейки 'Е' заняты (1, 3, 8)", "ячейки 'Е' заняты (1, 3)"),), 10, MECH, id="decision"),
        pytest.param((TL._arg(4, 7, 4400),), 7, MECH, id="ARGS7"),
        pytest.param((TL._arg(0, 2, 4700),), 1, MECH, id="ARGS2"),
        pytest.param((TL._arg(0, 3, 62000),), 1, MECH, id="ARGS3"),
        pytest.param((TL._jobf(0, "res_status", 0),), 1, MECH, id="res_status"),
        pytest.param((TL._sub(3, "[3/9]", "[4/9]"),), 4, MECH, id="progress_without_losses"),
        pytest.param((TL._sub(6, "r60.0°", "r40.0°"),), 7, MECH, id="only_r"),
        pytest.param((TL._arg(4, 9, 64536),), 7, MECH, id="only_ARGS9"),
        pytest.param((TL._sub(6, "r60.0°", "r40.0°"), TL._arg(4, 9, 64536)), 7, MECH, id="r_and_ARGS9"),
        pytest.param(
            (TL._sub(0, "r0.0°", "r40.0°"), TL._sub(0, "взять(458.2,-343.0)", "взять(458.2,-350.0)")),
            1,
            MECH,
            id="r_plus_pick",
        ),
    ],
)
def test_a2_row_reasons_decide_klass(muts, idx, expected) -> None:
    res = _judge("B", _apply(TL._b_inputs(), *muts))
    assert _row_klass(res) == {idx: expected}
    assert res.unrecognized == 0
    assert tuple(res.hard) == ()


def test_a2_missing_line_is_mechanism_and_not_hard_and_not_unrecognized() -> None:
    inp = TL._d_inputs()
    del inp["lines"][1]
    del inp["jobs"][0]
    res = _judge("D", inp)
    assert _row_klass(res)[2] == MECH
    assert res.unrecognized == 0
    assert 2 not in [i for i, _ in _hard(res)]
    assert _chk_klass(res)["lines.count"] == MECH  # и при U = 0 проверки случая - механизм


def test_a2_extra_line_is_mechanism_not_hard_not_unrecognized() -> None:
    inp = TL._b_inputs()
    inp["lines"].insert(3, TL._msg("Щ", 12.0, TL._skip("нет в слове 'ПЕРЕМИРИЕ'")))
    res = _judge("B", inp)
    assert _row_klass(res) == {13: MECH}
    assert res.unrecognized == 0
    assert tuple(res.hard) == ()


@pytest.mark.parametrize(
    ("regs_over", "jobs_cut", "expected_check"),
    [
        pytest.param({}, 1, "jobs.count", id="jobs_count"),
        pytest.param({"slots_filled": 8}, 0, "regs.slots_filled", id="slots_filled"),
        pytest.param({"jobs_emitted": 8}, 0, "regs.jobs_emitted", id="jobs_emitted"),
        pytest.param({"done": False}, 0, "regs.done", id="done"),
    ],
)
def test_a2_checks_are_mechanism_when_nothing_unrecognized(regs_over, jobs_cut, expected_check) -> None:
    inp = TL._b_inputs()
    inp["regs"].update(regs_over)
    inp["jobs"] = inp["jobs"][: len(inp["jobs"]) - jobs_cut]
    res = _judge("B", inp)
    assert res.unrecognized == 0
    assert _chk_klass(res)[expected_check] == MECH


def test_a2_checks_off_by_two_with_one_unrecognized_are_mechanism() -> None:
    inp = _b_lost_last()
    inp["jobs"] = inp["jobs"][:-1]  # заданий 7 при литерале 9: расхождение 2 при U = 1
    inp["regs"].update(slots_filled=7, jobs_emitted=7)
    res = _judge("B", inp)
    assert res.unrecognized == 1
    k = _chk_klass(res)
    assert k["jobs.count"] == MECH
    assert k["regs.slots_filled"] == MECH
    assert k["regs.jobs_emitted"] == MECH


def test_a2_jobs_emitted_uses_growth_over_before() -> None:
    # D: before = 8 (каскад B), прирост 3 - верен; расхождение считается по приросту, а не по абсолюту
    inp = TL._d_inputs()
    inp["before"] = 8
    inp["regs"]["jobs_emitted"] = 11
    assert _chk(_judge("D", inp, prev_filled=None), "regs.jobs_emitted").ok is True
    # прирост на 1 меньше при U = 1 - ТОЧНОСТЬ, при U = 0 - МЕХАНИЗМ
    short = _d_lost_mid()
    short["before"] = 9
    assert _chk_klass(_judge("D", short))["regs.jobs_emitted"] == ACC  # 11 - 9 = 2 против 3
    plain = TL._d_inputs()
    plain["regs"]["jobs_emitted"] = 11  # before 9: прирост 2 против 3, потерь нет
    assert _chk_klass(_judge("D", plain))["regs.jobs_emitted"] == MECH


@pytest.mark.parametrize(
    "mut",
    [
        pytest.param(TL._regs("word_norm", "ПЕРЕМИРИ"), id="word_norm"),
        pytest.param(TL._regs("slots_total", 8), id="slots_total"),
        pytest.param(TL._no_word_line, id="word_line"),
    ],
)
def test_a2_other_checks_are_mechanism_even_with_unrecognized(mut) -> None:
    inp = _apply(_b_lost_last(), mut)
    res = _judge("B", inp)
    assert res.unrecognized == 1
    # среди FAIL-проверок, кроме четырёх «каскадных», ровно одна «прочая» - и она МЕХАНИЗМ
    others = {
        k: v
        for k, v in _chk_klass(res).items()
        if k not in {"jobs.count", "regs.slots_filled", "regs.jobs_emitted", "regs.done"}
    }
    assert len(others) == 1 and set(others.values()) == {MECH}


def test_a2_lines_count_is_mechanism_even_with_unrecognized() -> None:
    inp = _b_lost_last()
    inp["lines"].append(TL._msg("А", 0.0, TL._skip("нет в слове 'ПЕРЕМИРИЕ'")))  # 13 строк при 12 дисках
    res = _judge("B", inp)
    assert _chk_klass(res)["lines.count"] == MECH


def test_a2_unreliable_alignment_all_mechanism_no_u_no_hard() -> None:
    # без feed и число строк ≠ числу дисков: сдвиг после потерянного диска похож на ошибки букв
    inp = TL._b_inputs()
    inp["feed"] = None
    del inp["lines"][3]  # одна строка потеряна: 11 строк при 12 дисках
    res = _judge("B", inp)
    failed = _row_klass(res)
    assert failed, "сдвиг должен дать FAIL-строки"
    assert set(failed.values()) == {MECH}
    assert res.unrecognized == 0
    assert tuple(res.hard) == ()
    # пара: число строк = числу дисков (feed всё ещё нет) - выравнивание надёжно, непризнанный диск считается
    ok_align = _b_lost_last()
    ok_align["feed"] = None
    res_ok = _judge("B", ok_align)
    assert res_ok.unrecognized == 1
    assert _row_klass(res_ok) == {12: ACC}
    assert _hard(res_ok) == [(12, ["class_mismatch", "below_threshold", "angle"])]


# =====================================================================================================================
# REDS п.3. A3 на judge_case: причины «трудности», порог угла, истина
# =====================================================================================================================


def _b_line_angle(idx0: int, letter: str, angle: float) -> dict:
    """B с заменой угла/буквы в строке диска idx0 (остальное в строке прежнее)."""
    inp = TL._b_inputs()
    old = re.match(r"WordLayoutPlugin: диск '(.)' (-?\d+\.\d)°", inp["lines"][idx0])
    assert old is not None
    inp["lines"][idx0] = inp["lines"][idx0].replace(old.group(0), f"WordLayoutPlugin: диск '{letter}' {angle:.1f}°", 1)
    return inp


def test_a3_angle_over_threshold_is_hard_and_threshold_is_a_parameter() -> None:
    inp = _b_line_angle(2, "Е", 35.8)  # Δ +5.8° при подаче Е 30°
    res = _judge("B", inp)
    assert res.ok is True  # в окне ±15° строка PASS, а «трудный» - да: N записей ≠ числу FAIL-строк
    assert _hard(res) == [(3, ["angle"])]
    assert _hard(_judge("B", inp, hard_angle_thr=5.0)) == [(3, ["angle"])]
    assert _hard(_judge("B", inp, hard_angle_thr=6.0)) == []


@pytest.mark.parametrize(
    ("line_angle", "feed_angle", "hard"),
    [
        pytest.param(35.0, 30.0, False, id="delta_exactly_5_0"),
        pytest.param(35.1, 30.0, True, id="delta_5_1"),
        pytest.param(24.2, 30.0, True, id="delta_minus_5_8"),
        pytest.param(35.0, 29.96, False, id="delta_5_04_rounds_to_5_0"),
        pytest.param(35.0, 29.94, True, id="delta_5_06_rounds_to_5_1"),
    ],
)
def test_a3_angle_boundary_is_strict_and_rounded_to_tenth(line_angle, feed_angle, hard) -> None:
    inp = _b_line_angle(2, "Е", line_angle)
    inp["feed"][2] = ("Е", feed_angle)
    assert (_hard(_judge("B", inp)) == [(3, ["angle"])]) is hard
    if not hard:
        assert _hard(_judge("B", inp)) == []


def test_a3_angle_difference_wraps_around_360() -> None:
    inp = _b_line_angle(2, "Е", 3.8)
    inp["feed"][2] = ("Е", 358.0)  # Δ = wrap180(3.8 − 358.0) = +5.8, а не −354.2
    assert _hard(_judge("B", inp, hard_angle_thr=5.0)) == [(3, ["angle"])]
    assert _hard(_judge("B", inp, hard_angle_thr=6.0)) == []


def test_a3_truth_comes_from_feed_when_given_else_from_literal() -> None:
    line_35_8 = _b_line_angle(2, "Е", 35.8)
    with_feed = copy.deepcopy(line_35_8)
    with_feed["feed"][2] = ("Е", 35.8)  # сим подал именно 35,8°: Δ = 0
    assert _hard(_judge("B", with_feed)) == []
    no_feed = copy.deepcopy(line_35_8)
    no_feed["feed"] = None  # литерал случая: Е 30° → Δ +5.8°
    assert _hard(_judge("B", no_feed)) == [(3, ["angle"])]


def test_a3_class_mismatch_and_angle_are_independent_reasons() -> None:
    inp = _b_line_angle(3, "Й", 125.8)  # подан «И» 60°
    assert _hard(_judge("B", inp)) == [(4, ["class_mismatch", "angle"])]
    same_angle = TL._b_inputs()
    TL._sub(3, "диск 'И'", "диск 'Й'")(same_angle)  # буква другая, угол тот же
    assert _hard(_judge("B", same_angle)) == [(4, ["class_mismatch"])]


def test_a3_below_threshold_alone_when_class_and_angle_match() -> None:
    inp = TL._b_inputs()
    inp["lines"][2] = TL._msg("Е", 30.0, TL._skip("уверенность ниже порога (Е 0.31 < 0.50)"))
    res = _judge("B", inp)
    assert _hard(res) == [(3, ["below_threshold"])]
    assert _row(res, 3).klass == ACC  # не признан сетью (пропуск «ниже порога»)
    assert res.unrecognized == 1


def test_a3_no_prediction_skips_class_and_angle_reasons() -> None:
    inp = TL._b_inputs()
    inp["lines"][2] = TL._msg("?", 0.0, TL._skip("нет предсказания"))  # подано Е 30°: ни класс, ни угол не сравниваются
    assert _hard(_judge("B", inp)) == [(3, ["no_prediction"])]


def test_a3_not_in_word_skip_counts_like_taken_disc() -> None:
    inp = TL._b_inputs()
    inp["lines"][1] = TL._msg("А", 7.0, TL._skip("нет в слове 'ПЕРЕМИРИЕ'"))  # подано А 0°, сеть 7,0°
    res = _judge("B", inp)
    assert res.ok is True
    assert _hard(res) == [(2, ["angle"])]


def test_a3_hard_records_ordered_by_index_and_only_for_discs_with_reasons() -> None:
    inp = _b_lost_last()
    TL._sub(2, "диск 'Е' 30.0°", "диск 'Е' 36.0°")(inp)
    got = _hard(_judge("B", inp))
    assert [i for i, _ in got] == [3, 12]
    assert got[0] == (3, ["angle"])


# =====================================================================================================================
# run(): фейковый мир с подменой того, что «прочла сеть», и «поздним» регистром
# =====================================================================================================================

_NOFLIP = object()
_MISSING = object()


def _pre(letter: str, angle: float) -> str:
    return f"WordLayoutPlugin: диск '{letter}' {angle:.1f}°"


def _full(new: str):
    return lambda _m: new


def _angle(letter: str, old: float, new: float):
    return lambda m: m.replace(f"диск '{letter}' {old:.1f}°", f"диск '{letter}' {new:.1f}°", 1)


def _replace(old: str, new: str):
    return lambda m: m.replace(old, new, 1)


def _drop(_m: str):
    return None


class _Net(H._Hooked):
    """Мир тестера, где строка диска, дошедшая до журнала, может отличаться от подачи (``rewrites``), а регистр
    ``slots_filled`` меняется ПОСЛЕ снимка конца B и ДО чтения перед D (``flip``): поздний диск B в плагине."""

    def __init__(self, hooks: dict | None = None, *, rewrites: dict | None = None, flip=_NOFLIP, **kw) -> None:
        super().__init__(hooks, **kw)
        self.rewrites = rewrites or {}
        self.flip = flip
        self.cur: str | None = None

    def release(self, case: str) -> None:
        self.cur = case
        super().release(case)
        if case == "B" and self.flip is not _NOFLIP:
            t_last = self.sched[-1][0]  # приход последнего диска B; снимок после B - в этот же момент

            def do_flip() -> None:
                if self.flip is _MISSING:
                    self.regs.pop("slots_filled", None)
                else:
                    self.regs["slots_filled"] = self.flip

            self.sched.append((t_last + 2.0, do_flip))  # до чтения регистров перед D (T + 3,5 с)

    def emit(self, msg: str) -> None:
        for (case, prefix), fn in self.rewrites.items():
            if case == self.cur and msg.startswith(prefix):
                new = fn(msg)
                if new is None:
                    return
                msg = new
                break
        super().emit(msg)


def _patch_cases(monkeypatch, *, b_lost: bool = False, d_lost: bool = False, d_prev: int | None = None) -> None:
    cases = copy.deepcopy(T._CASES)
    if b_lost:  # диск 12 B не взят (непризнан); регистры и суммы D, C - с учётом потери
        b = cases["B"]
        b["decisions"][-1] = "пропуск: " + _BELOW
        b["jobs"] = b["jobs"][:-1]
        b["regs"].update(slots_filled=8, jobs_emitted=8, done=False)
        cases["D"]["word_line"] = cases["D"]["word_line"].replace("9/9", "8/9")
        cases["D"]["regs"]["jobs_emitted"] = 11
        cases["C"]["regs"]["jobs_emitted"] = 14
    if d_lost:  # диск 2 D без предсказания; И, Р - [1/3], [2/3]; D заполнил 2, C видит «было 2/3»
        d = cases["D"]
        d["decisions"][1] = "пропуск: нет предсказания"
        d["decisions"][3] = T._take(1, "-330.0", "-90.0", 1, 3)
        d["decisions"][4] = T._take(2, "-220.0", "60.0", 2, 3)
        d["jobs"] = d["jobs"][1:]
        d["regs"].update(slots_filled=2, jobs_emitted=11, done=False)
        cases["C"]["word_line"] = cases["C"]["word_line"].replace("3/3", "2/3")
        cases["C"]["regs"]["jobs_emitted"] = 14
    if d_prev is not None:
        cases["D"]["word_line"] = T._CASES["D"]["word_line"].replace("9/9", f"{d_prev}/9")
    monkeypatch.setattr(T, "_CASES", cases)


_B12_NET = {("B", _pre("М", 300.0)): _full(f"{_pre('И', 125.8)} → пропуск: {_BELOW}")}
_D2_NET = {("D", _pre("М", 30.0)): _full(f"{_pre('?', 0.0)} → пропуск: нет предсказания")}


def _run(world, extra: list[str] | None = None, **kw) -> tuple[int, str]:
    box, out = H._run_kw(world, ["--tree", T._TREE, *(extra or [])], **kw)
    assert "exc" not in box, f"run бросил {box.get('exc')!r}\n{out}"
    return box["rc"], out


def _a2(out: str) -> tuple[list[str], str, str, list[str], int]:
    """Хвост вывода: [строки «класс …»], строка МЕХАНИЗМ, строка ТОЧНОСТЬ; ``итог:`` - последняя строка."""
    lines = out.rstrip("\n").splitlines()
    assert lines[-1].startswith("итог: "), lines[-4:]
    acc, mech = lines[-2], lines[-3]
    assert acc.startswith("ТОЧНОСТЬ: "), acc
    assert mech.startswith("МЕХАНИЗМ: "), mech
    j = len(lines) - 3
    cls: list[str] = []
    while j > 0 and lines[j - 1].startswith("класс "):
        j -= 1
        cls.insert(0, lines[j])
    return cls, mech, acc, lines, j


def _read_hard(path: Path) -> list[dict]:
    raw = path.read_bytes().decode("utf-8")
    assert raw == "" or raw.endswith("\n")
    return [json.loads(ln) for ln in raw.splitlines()]


# --- REDS п.1 через run(): prev_filled из регистра, прочитанного ПЕРЕД случаем ---------------------------------------


def test_a1_run_expected_d_line_carries_register_value_at_start_of_d_not_snapshot_after_b(monkeypatch) -> None:
    _patch_cases(monkeypatch, d_prev=8)  # плагин напечатает у D «было заполнено 8/9»
    world = _Net(flip=8)  # регистр после снимка B стал 8 (поздний диск B); к началу D он 8
    rc, out = _run(world)
    lines = out.splitlines()
    assert any(ln.startswith("D word_line:") and ln.endswith("→ PASS") for ln in lines), out
    assert "D случай: PASS" in lines
    assert rc == 0, out
    assert lines[-1] == T._SUMMARY_OK


def test_a1_run_snapshot_after_b_would_be_wrong_pair(monkeypatch) -> None:
    # пара «до, а не после»: плагин напечатал 9/9, регистр на начало D = 8, снимок после B = 9
    _patch_cases(monkeypatch)
    world = _Net(flip=8)
    rc, out = _run(world)
    lines = out.splitlines()
    assert any(ln.startswith("D word_line:") and "→ FAIL" in ln for ln in lines), out  # k=9 ≠ 8
    assert "D случай: FAIL" in lines
    assert rc == 1, out


@pytest.mark.parametrize("flip", [_MISSING, "8"], ids=["no_key", "not_int"])
def test_a1_run_missing_or_non_int_register_falls_back_to_literal(monkeypatch, flip) -> None:
    _patch_cases(monkeypatch)  # плагин печатает литерал 9/9
    rc, out = _run(_Net(flip=flip))
    assert any(ln.startswith("D word_line:") and ln.endswith("→ PASS") for ln in out.splitlines()), out
    assert rc == 0, out


def test_a1_run_without_flip_literal_still_passes_control() -> None:
    rc, out = _run(_Net())
    assert rc == 0, out
    assert out.rstrip("\n").splitlines()[-1] == T._SUMMARY_OK


def test_a1_run_c_gets_prev_filled_from_d_register(monkeypatch) -> None:
    _patch_cases(monkeypatch, d_lost=True)  # D заполнил 2 → C печатает «было 2/3»
    rc, out = _run(_Net(rewrites=_D2_NET))
    lines = out.splitlines()
    assert any(ln.startswith("C word_line:") and ln.endswith("→ PASS") for ln in lines), out
    assert "C случай: PASS" in lines
    assert rc == 1, out  # строки D красные (ТОЧНОСТЬ): код 1


# --- REDS п.2 через run(): печать блока A2 ---------------------------------------------------------------------------


def test_a2_run_all_green_prints_clean_block_before_summary() -> None:
    rc, out = _run(T.World())
    assert rc == 0, out
    lines = out.rstrip("\n").splitlines()
    assert lines[-3:] == ["МЕХАНИЗМ: PASS", "ТОЧНОСТЬ: 0 трудных", T._SUMMARY_OK]
    assert not any(ln.startswith("класс ") for ln in lines)


def test_a2_run_unrecognized_last_disc_of_b_block_and_exit_code(monkeypatch) -> None:
    _patch_cases(monkeypatch, b_lost=True)
    rc, out = _run(_Net(rewrites=_B12_NET))
    cls, mech, acc, lines, start = _a2(out)
    assert rc == 1, out
    assert cls[0] == "класс B #12: ТОЧНОСТЬ"  # диски - перед прочими проверками
    assert set(cls) == {
        "класс B #12: ТОЧНОСТЬ",
        "класс B jobs.count: ТОЧНОСТЬ",
        "класс B regs.slots_filled: ТОЧНОСТЬ",
        "класс B regs.jobs_emitted: ТОЧНОСТЬ",
        "класс B regs.done: ТОЧНОСТЬ",
        "класс B feed: ТОЧНОСТЬ",
    }
    assert len(cls) == 6
    assert mech == "МЕХАНИЗМ: PASS"
    assert acc == "ТОЧНОСТЬ: 1 трудных (B #12)"
    assert lines[start - 1].startswith("изменено в симе/на стенде: ")  # блок - между «изменено» и «итог»
    assert lines[-1].startswith("итог: B=FAIL D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 1 ")
    assert "D случай: PASS" in lines and "C случай: PASS" in lines  # каскад word_line учтён


def test_a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy(monkeypatch) -> None:
    _patch_cases(monkeypatch, d_lost=True)
    rc, out = _run(_Net(rewrites=_D2_NET))
    cls, mech, acc, lines, _ = _a2(out)
    assert rc == 1, out
    assert cls[:3] == ["класс D #2: ТОЧНОСТЬ", "класс D #4: ТОЧНОСТЬ", "класс D #5: ТОЧНОСТЬ"]
    assert set(cls[3:]) == {
        "класс D jobs.count: ТОЧНОСТЬ",
        "класс D regs.slots_filled: ТОЧНОСТЬ",
        "класс D regs.jobs_emitted: ТОЧНОСТЬ",
        "класс D regs.done: ТОЧНОСТЬ",
        "класс D feed: ТОЧНОСТЬ",
    }
    assert len(cls) == 8
    assert mech == "МЕХАНИЗМ: PASS"
    assert acc == "ТОЧНОСТЬ: 1 трудных (D #2)"
    assert lines[-1].startswith("итог: B=PASS D=FAIL C=PASS ДОМОЙ=PASS СТОП=PASS → код 1 ")


def test_a2_run_mechanism_list_follows_case_order_word_line_then_discs(monkeypatch) -> None:
    _patch_cases(monkeypatch, d_prev=5)  # плагин D печатает 5/9, регистр до D = 9
    rewrites = {
        ("B", _pre("Е", 30.0)): _replace("взять(458.2,-343.0)", "взять(458.2,-350.0)"),  # B #3: pick вне окна
        ("D", _pre("П", 0.0)): _replace("нет в слове 'МИР'", "нет в слове 'МИ'"),  # D #1: decision
    }
    rc, out = _run(_Net(rewrites=rewrites))
    cls, mech, acc, lines, _ = _a2(out)
    assert rc == 1, out
    assert cls == ["класс B #3: МЕХАНИЗМ", "класс D word_line: МЕХАНИЗМ", "класс D #1: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B #3, D word_line, D #1)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"
    assert lines[-1].startswith("итог: B=FAIL D=FAIL C=PASS ")


def test_a2_run_stop_fail_is_mechanism() -> None:
    world = T.World()
    world.read_lines = lambda _path: H._old_file()  # файл журнала обмена - от прошлых запусков
    box, out = H._run_kw(world, wall_clock=lambda: 5000.0, file_mtime=lambda _path: 4000.0)
    assert box.get("rc") == 1, out
    cls, mech, acc, lines, _ = _a2(out)
    assert cls == ["класс СТОП stop: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (СТОП stop)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"
    assert lines[-1].startswith("итог: B=PASS D=PASS C=PASS ДОМОЙ=PASS СТОП=FAIL → код 1 ")


def test_a2_run_p0_failure_labels_precondition_and_not_run_statuses() -> None:
    rc, out = _run(T.World(infos={8766: None, 8765: None}))  # listeners → None
    cls, mech, acc, _, _ = _a2(out)
    assert rc == 3, out
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (предусловие, не выполнены: B, D, C, ДОМОЙ, СТОП)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_a2_run_p1_p3_precondition_has_no_cleanup_and_all_not_run() -> None:
    rc, out = _run(H._Hooked({("sim", "send_command"): H._busy_sim}))  # P1: сим занят
    assert rc == 3, out
    assert _a2(out)[1] == "МЕХАНИЗМ: FAIL (предусловие, не выполнены: B, D, C, ДОМОЙ, СТОП)"
    rc3, out3 = _run(T.World(no_recog=True))  # P3: распознавания нет
    assert rc3 == 3, out3
    assert _a2(out3)[1] == "МЕХАНИЗМ: FAIL (предусловие, не выполнены: B, D, C, ДОМОЙ, СТОП)"


def test_a2_run_unexpected_exception_in_p1_is_error_label() -> None:
    def boom(world, real, target, command, args, **kw):
        if command == "scene.status":
            raise RuntimeError("бум")
        return NotImplemented

    rc, out = _run(H._Hooked({("sim", "send_command"): boom}))
    assert rc == 3, out
    cls, mech, acc, _, _ = _a2(out)
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (ошибка, не выполнены: B, D, C, ДОМОЙ, СТОП)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_a2_run_word_set_fail_in_b_runs_cleanup_so_only_d_c_not_run() -> None:
    def unverified(world, real, process, register, field, value, *, timeout=None):
        if value == "ПЕРЕМИРИЕ":
            return {"success": True, "verified": False, "found": True, "expected": value, "actual": ""}
        return NotImplemented

    rc, out = _run(H._Hooked({("proto", "set_register_verified"): unverified}))
    cls, mech, _, _, _ = _a2(out)
    assert rc == 1, out
    assert cls == ["класс B word_set: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B word_set, не выполнены: D, C)"


def test_a2_run_precondition_in_middle_of_b_leaves_b_d_c_not_run() -> None:
    rc, out = _run(T.World(invalid_b=True))  # сим не знает букву: Precondition посреди B, затем уборка
    assert rc == 3, out
    cls, mech, _, _, _ = _a2(out)
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (предусловие, не выполнены: B, D, C)"


def test_a2_run_ctrl_c_in_case_is_interrupted_label() -> None:
    fired: list = []

    def interrupt(world, real, target, command, args, **kw):
        if command == "scene.status" and world.paused and not fired:
            fired.append(1)
            raise KeyboardInterrupt
        return NotImplemented

    box, out = H._run_kw(H._Hooked({("sim", "send_command"): interrupt}))
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    cls, mech, acc, _, _ = _a2(out)
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (прервано, не выполнены: B, D, C)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_a2_run_home_exception_in_tail_is_home_error_label() -> None:
    rc, out = _run(H._Hooked({("proto", "send_command"): H._park_raises}))
    cls, mech, _, _, _ = _a2(out)
    assert rc == 3, out
    assert cls == ["класс ДОМОЙ: МЕХАНИЗМ"]  # Row.check совпадает с префиксом - ключ опущен
    assert mech == "МЕХАНИЗМ: FAIL (ДОМОЙ, ошибка ДОМОЙ/СТОП)"


# --- REDS п.3 через run(): файл --hard-out ---------------------------------------------------------------------------

_B12_RECORD = {
    "case": "B",
    "index": 12,
    "truth": {"class": "М", "angle_deg": 300.0},
    "pred": {"class": "И", "angle_deg": 125.8, "confidence": 0.43, "below_threshold": True},
    "delta_angle_deg": -174.2,
    "hard": True,
    "hard_reasons": ["class_mismatch", "below_threshold", "angle"],
    "hard_reasons_ru": ["класс не совпал", "ниже порога", "угол > порога"],
    "angle_thr": 5.0,
    "conf_thr": 0.5,
}
_TOP_KEYS = [
    "case", "index", "truth", "pred", "delta_angle_deg", "hard", "hard_reasons", "hard_reasons_ru", "angle_thr",
    "conf_thr",
]  # fmt: skip


def test_a3_run_b12_record_literal_and_key_order(monkeypatch, tmp_path) -> None:
    _patch_cases(monkeypatch, b_lost=True)
    out_file = tmp_path / "hard.jsonl"
    rc, _ = _run(_Net(rewrites=_B12_NET), ["--hard-out", str(out_file)])
    assert rc == 1
    raw = out_file.read_bytes().decode("utf-8")
    assert raw.endswith("\n") and raw.count("\n") == 1
    assert "\\u" not in raw and "М" in raw  # кириллица не экранирована
    assert json.loads(raw) == _B12_RECORD
    pairs = json.loads(raw, object_pairs_hook=list)
    assert [k for k, _v in pairs] == _TOP_KEYS
    sub = dict(pairs)
    assert [k for k, _v in sub["truth"]] == ["class", "angle_deg"]
    assert [k for k, _v in sub["pred"]] == ["class", "angle_deg", "confidence", "below_threshold"]


def test_a3_run_no_prediction_record(monkeypatch, tmp_path) -> None:
    _patch_cases(monkeypatch, d_lost=True)
    out_file = tmp_path / "hard.jsonl"
    _run(_Net(rewrites=_D2_NET), ["--hard-out", str(out_file)])
    assert _read_hard(out_file) == [
        {
            "case": "D",
            "index": 2,
            "truth": {"class": "М", "angle_deg": 30.0},
            "pred": None,
            "delta_angle_deg": None,
            "hard": True,
            "hard_reasons": ["no_prediction"],
            "hard_reasons_ru": ["нет ответа"],
            "angle_thr": 5.0,
            "conf_thr": None,
        }
    ]


def test_a3_run_angle_reason_threshold_flag_and_boundary(tmp_path) -> None:
    net = {("B", _pre("Е", 30.0)): _angle("Е", 30.0, 35.8)}  # верная буква, Δ +5.8°
    f_default = tmp_path / "default.jsonl"
    rc, out = _run(_Net(rewrites=net), ["--hard-out", str(f_default)])
    assert rc == 0, out  # в окне ±15° все строки PASS
    rec = _read_hard(f_default)
    assert len(rec) == 1
    assert rec[0]["case"] == "B" and rec[0]["index"] == 3
    assert rec[0]["hard_reasons"] == ["angle"] and rec[0]["hard_reasons_ru"] == ["угол > порога"]
    assert rec[0]["delta_angle_deg"] == 5.8 and rec[0]["angle_thr"] == 5.0
    assert rec[0]["pred"] == {"class": "Е", "angle_deg": 35.8, "confidence": None, "below_threshold": False}
    assert rec[0]["conf_thr"] is None
    assert _a2(out)[2] == "ТОЧНОСТЬ: 1 трудных (B #3)"
    # --hard-angle-thr 6.0: файл создан и пуст, счёт «0 трудных»
    f_six = tmp_path / "six.jsonl"
    rc6, out6 = _run(_Net(rewrites=net), ["--hard-out", str(f_six), "--hard-angle-thr", "6.0"])
    assert rc6 == 0, out6
    assert f_six.exists() and f_six.read_bytes() == b""
    assert _a2(out6)[2] == "ТОЧНОСТЬ: 0 трудных"
    # Δ ровно 5.0° - не трудный
    f_edge = tmp_path / "edge.jsonl"
    _run(_Net(rewrites={("B", _pre("Е", 30.0)): _angle("Е", 30.0, 35.0)}), ["--hard-out", str(f_edge)])
    assert f_edge.exists() and f_edge.read_bytes() == b""


def test_a3_run_below_threshold_with_ml_inference_threshold_text(tmp_path) -> None:
    net = {
        ("B", _pre("Е", 30.0)): _full(
            f"{_pre('Е', 30.0)} → пропуск: уверенность ниже порога (Е 0.31 < порог ml_inference)"
        )
    }
    f = tmp_path / "hard.jsonl"
    _run(_Net(rewrites=net), ["--hard-out", str(f)])
    rec = [r for r in _read_hard(f) if r["index"] == 3]
    assert len(rec) == 1
    assert rec[0]["hard_reasons"] == ["below_threshold"] and rec[0]["hard_reasons_ru"] == ["ниже порога"]
    assert rec[0]["pred"]["confidence"] == 0.31 and rec[0]["pred"]["below_threshold"] is True
    assert rec[0]["conf_thr"] is None and rec[0]["delta_angle_deg"] == 0.0


def test_a3_run_records_ordered_b_d_c_then_index_and_count_matches(monkeypatch, tmp_path) -> None:
    _patch_cases(monkeypatch, b_lost=True)
    rewrites = {
        **_B12_NET,
        ("B", _pre("Е", 30.0)): _angle("Е", 30.0, 35.8),
        ("D", _pre("Р", 300.0)): _angle("Р", 300.0, 306.5),
        ("C", _pre("Е", 30.0)): _angle("Е", 30.0, 36.0),
    }
    f = tmp_path / "hard.jsonl"
    rc, out = _run(_Net(rewrites=rewrites), ["--hard-out", str(f)])
    assert rc == 1, out
    assert [(r["case"], r["index"]) for r in _read_hard(f)] == [("B", 3), ("B", 12), ("D", 5), ("C", 2)]
    assert _a2(out)[2] == "ТОЧНОСТЬ: 4 трудных (B #3, B #12, D #5, C #2)"


def test_a3_run_disc_without_journal_line_is_not_in_file_pair(tmp_path) -> None:
    # пара: подмена строки B#3 неверной буквой - запись есть; строка вовсе не пришла - записи нет
    f_bad = tmp_path / "bad.jsonl"
    _run(_Net(rewrites={("B", _pre("Е", 30.0)): _replace("диск 'Е'", "диск 'Й'")}), ["--hard-out", str(f_bad)])
    assert [r["index"] for r in _read_hard(f_bad)] == [3]
    f_gone = tmp_path / "gone.jsonl"
    _run(_Net(rewrites={("B", _pre("Е", 30.0)): _drop}), ["--hard-out", str(f_gone)])
    assert f_gone.exists()
    assert 3 not in [r["index"] for r in _read_hard(f_gone)]


def test_a3_run_file_created_empty_when_nothing_is_hard(tmp_path) -> None:
    f = tmp_path / "hard.jsonl"
    rc, out = _run(T.World(), ["--hard-out", str(f)])
    assert rc == 0, out
    assert f.exists() and f.stat().st_size == 0


def test_a3_run_file_created_on_p0_failure(tmp_path) -> None:
    f = tmp_path / "hard.jsonl"
    rc, out = _run(T.World(infos={8766: None, 8765: None}), ["--hard-out", str(f)])
    assert rc == 3, out
    assert f.exists() and f.stat().st_size == 0


def test_a3_run_file_created_on_precondition_in_p1(tmp_path) -> None:
    f = tmp_path / "hard.jsonl"
    rc, out = _run(H._Hooked({("sim", "send_command"): H._busy_sim}), ["--hard-out", str(f)])
    assert rc == 3, out
    assert f.exists() and f.stat().st_size == 0


def test_a3_run_file_created_on_ctrl_c(tmp_path) -> None:
    fired: list = []

    def interrupt(world, real, target, command, args, **kw):
        if command == "scene.status" and world.paused and not fired:
            fired.append(1)
            raise KeyboardInterrupt
        return NotImplemented

    f = tmp_path / "hard.jsonl"
    box, _ = H._run_kw(H._Hooked({("sim", "send_command"): interrupt}), ["--tree", T._TREE, "--hard-out", str(f)])
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    assert f.exists() and f.stat().st_size == 0


def test_a3_run_empty_flag_value_means_not_set(monkeypatch, tmp_path) -> None:
    _patch_cases(monkeypatch, b_lost=True)
    rc_flag, out_flag = _run(_Net(rewrites=_B12_NET), ["--hard-out", ""])
    rc_none, out_none = _run(_Net(rewrites=_B12_NET))
    assert rc_flag == rc_none == 1
    assert "hard-out:" not in out_flag
    assert _a2(out_flag)[2] == _a2(out_none)[2] == "ТОЧНОСТЬ: 1 трудных (B #12)"  # счёт - и без флага
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["no_dir", "dir_instead_of_file"])
def test_a3_run_write_error_prints_line_before_a2_and_keeps_exit_code(monkeypatch, tmp_path, kind) -> None:
    _patch_cases(monkeypatch, b_lost=True)
    target = tmp_path / "нет_каталога" / "hard.jsonl" if kind == "no_dir" else tmp_path
    rc, out = _run(_Net(rewrites=_B12_NET), ["--hard-out", str(target)])
    assert rc == 1, out  # код выхода тот же, что без флага
    cls, _mech, acc, lines, start = _a2(out)
    errs = [i for i, ln in enumerate(lines) if ln.startswith("hard-out: ошибка")]
    assert len(errs) == 1 and errs[0] < start
    assert acc == "ТОЧНОСТЬ: 1 трудных (B #12)"
    assert lines[-1].startswith("итог: ")
    assert cls[0] == "класс B #12: ТОЧНОСТЬ"


def test_a2_run_exchange_dropped_is_mechanism() -> None:
    fired: list = []
    rc, out = _run(H._Hooked({("proto", "send_command"): H._exchange_dropped_hook(3, fired)}))
    assert fired == [3]
    cls, mech, acc, _, _ = _a2(out)
    assert rc == 1, out
    assert cls == ["класс B exchange: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B exchange)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_a2_run_layout_log_dropped_is_mechanism() -> None:
    state = {"fired": False}

    def events_hook(world, real, *a, **kw):
        page = real(*a, **kw)
        if world.first("proto", "set_register_verified") is not None and not state["fired"]:
            state["fired"] = True
            page = dict(page, dropped=2)  # кольцо вытеснило события между курсором и страницей
        return page

    rc, out = _run(H._Hooked({("proto", "events_page"): events_hook}))
    assert state["fired"]
    cls, mech, _, _, _ = _a2(out)
    assert rc == 1, out
    assert cls == ["класс B layout_log: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B layout_log)"
