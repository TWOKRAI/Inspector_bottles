"""alpha_sim, Task A: сторож критерия «пропуск ниже порога» на уровне ``run()``.

Дыра, найденная break-injection I3: у B#12 сеть читает «И» вместо «М», и диск «не признан» уже по причинам
``letter``/``feed``; критерий «пропуск: уверенность ниже порога» в ``_unrecognized`` ни один тест ``run()`` не держал.
Здесь сеть отдаёт ВЕРНУЮ букву «М» (угол 300,0° тот же) с уверенностью ниже порога: единственное, что делает диск
не признанным, — текст пропуска. Ожидания — литералы задачи (plans/release-1.0/lane-tasks/alpha-hard-split.md).
Фейки и помощники — из приёмочного файла (``_Net``, ``_patch_cases``, ``_run``, ``_a2``, ``_read_hard``).
"""

from __future__ import annotations

import copy

import pytest

from scripts.alpha_sim.tests import test_alpha_split_acceptance as A
from scripts.alpha_sim.tests import test_p4_alpha_hazards as H
from scripts.alpha_sim.tests import test_p4_alpha_runner as T


@pytest.mark.parametrize(
    ("skip_text", "confidence", "conf_thr"),
    [
        pytest.param("уверенность ниже порога (М 0.43 < 0.50)", 0.43, 0.5, id="numeric_threshold"),
        pytest.param("уверенность ниже порога (М 0.31 < порог ml_inference)", 0.31, None, id="ml_inference_threshold"),
    ],
)
def test_right_letter_below_threshold_is_accuracy_and_hard(
    monkeypatch, tmp_path, skip_text, confidence, conf_thr
) -> None:
    A._patch_cases(monkeypatch, b_lost=True)  # диск B#12 не взят: 8 заданий, регистры 8, D и C с учётом потери
    net = {("B", A._pre("М", 300.0)): A._full(f"{A._pre('М', 300.0)} → пропуск: {skip_text}")}
    out_file = tmp_path / "hard.jsonl"
    rc, out = A._run(A._Net(rewrites=net), ["--hard-out", str(out_file)])
    cls, mech, acc, lines, _ = A._a2(out)
    assert rc == 1, out
    assert cls[0] == "класс B #12: ТОЧНОСТЬ"  # единственная причина «не признан» — текст пропуска (буква верная)
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
    assert lines[-1].startswith("итог: B=FAIL D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 1 ")
    assert A._read_hard(out_file) == [
        {
            "case": "B",
            "index": 12,
            "truth": {"class": "М", "angle_deg": 300.0},
            "pred": {"class": "М", "angle_deg": 300.0, "confidence": confidence, "below_threshold": True},
            "delta_angle_deg": 0.0,
            "hard": True,
            "hard_reasons": ["below_threshold"],
            "hard_reasons_ru": ["ниже порога"],
            "angle_thr": 5.0,
            "conf_thr": conf_thr,
        }
    ]


# --- Стадия 5, раунд 1: «объяснена» для r / ARGS[9] / progress (спека, редакция 3) ---------------------------------

_B_TAKEN = [1, 3, 4, 5, 7, 8, 9, 11, 12]  # диски B, взятые в ячейки (остальные — пропуски)
_ALL_B_MECH = "МЕХАНИЗМ: FAIL (" + ", ".join(f"B #{i}" for i in _B_TAKEN) + ")"
_ALL_B_CLASS = [f"класс B #{i}: МЕХАНИЗМ" for i in _B_TAKEN]


class _NoArg9(A._Net):
    """Задания B приходят без строки ``CMD_ARGS[9]`` при ``CMD_ARGC = 10`` (D и C — как обычно)."""

    def add_ex(self, text: str, side: str = "in") -> None:
        if self.cur == "B" and text.startswith("W* CMD_ARGS[9]"):
            return
        super().add_ex(text, side)


def _cases_b(monkeypatch, *, jobs=None, decisions=None) -> None:
    cases = copy.deepcopy(T._CASES)
    if jobs is not None:
        cases["B"]["jobs"] = jobs(cases["B"]["jobs"])
    for idx, text in (decisions or {}).items():
        cases["B"]["decisions"][idx] = text
    monkeypatch.setattr(T, "_CASES", cases)


def test_args9_missing_with_right_angle_is_mechanism() -> None:  # S1
    rc, out = A._run(_NoArg9())
    cls, mech, acc, lines, _ = A._a2(out)
    assert rc == 1, out
    assert cls == _ALL_B_CLASS
    assert mech == _ALL_B_MECH
    assert acc == "ТОЧНОСТЬ: 0 трудных"
    assert lines[-1].startswith("итог: B=FAIL D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 1 ")


def test_args9_shifted_for_all_jobs_with_right_angle_is_mechanism(monkeypatch) -> None:  # S2
    _cases_b(monkeypatch, jobs=lambda jobs: [(a7, a9 + 1000) for a7, a9 in jobs])
    rc, out = A._run(A._Net())
    cls, mech, acc, _, _ = A._a2(out)
    assert rc == 1, out
    assert cls == _ALL_B_CLASS
    assert mech == _ALL_B_MECH
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_r_sign_flipped_with_right_angle_is_mechanism(monkeypatch) -> None:  # S3
    _cases_b(monkeypatch, decisions={2: T._take(1, "-330.0", "30.0", 2, 9)})  # Е 30°: r должен быть -30.0
    rc, out = A._run(A._Net())
    cls, mech, acc, _, _ = A._a2(out)
    assert rc == 1, out
    assert cls == ["класс B #3: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B #3)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


@pytest.mark.parametrize("with_args9", [False, True], ids=["r_only", "r_and_args9"])
def test_r_and_args9_off_with_angle_misread_over_tolerance_is_accuracy(monkeypatch, with_args9) -> None:
    # контроль к S2/S3: сеть прочла Е 30° как 50° (Δ +20° > допуска 15°); r (-50.0) и ARGS[9] идут из этого угла
    if with_args9:
        _cases_b(monkeypatch, jobs=lambda jobs: [jobs[0], (jobs[1][0], jobs[1][1] + 1000), *jobs[2:]])
    net = {
        ("B", A._pre("Е", 30.0)): lambda m: m.replace("диск 'Е' 30.0°", "диск 'Е' 50.0°").replace("r-30.0°", "r-50.0°")
    }
    rc, out = A._run(A._Net(rewrites=net))
    cls, mech, acc, _, _ = A._a2(out)
    assert rc == 1, out
    assert cls == ["класс B #3: ТОЧНОСТЬ"]
    assert mech == "МЕХАНИЗМ: PASS"
    assert acc == "ТОЧНОСТЬ: 1 трудных (B #3)"


def test_progress_k_above_literal_is_mechanism_even_with_loss_before(monkeypatch) -> None:
    # D: диск №2 потерян, у И и Р progress на 1 меньше (каскад); у Р вместо [3/3] стоит [4/3] — k БОЛЬШЕ литерала
    A._patch_cases(monkeypatch, d_lost=True)
    T._CASES["D"]["decisions"][4] = T._take(2, "-220.0", "60.0", 4, 3)
    rc, out = A._run(A._Net(rewrites=A._D2_NET))
    cls, mech, acc, _, _ = A._a2(out)
    assert rc == 1, out
    assert cls[:3] == ["класс D #2: ТОЧНОСТЬ", "класс D #4: ТОЧНОСТЬ", "класс D #5: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (D #5)"
    assert acc == "ТОЧНОСТЬ: 1 трудных (D #2)"


# --- Стадия 5, раунд 1: метки прогона и код выхода ----------------------------------------------------------------


def _unverified_b(world, real, process, register, field, value, *, timeout=None):
    if value == "ПЕРЕМИРИЕ":
        return {"success": True, "verified": False, "found": True, "expected": value, "actual": ""}
    return NotImplemented


def test_word_set_fail_plus_park_exception_in_cleanup_keeps_exit_code_1() -> None:
    hooks = {("proto", "set_register_verified"): _unverified_b, ("proto", "send_command"): H._park_raises}
    rc, out = A._run(H._Hooked(hooks))
    cls, mech, acc, lines, _ = A._a2(out)
    assert rc == 1, out  # шаг уборки код 3 не ставит (как в main); метка и строка ДОМОЙ остаются
    assert cls == ["класс B word_set: МЕХАНИЗМ", "класс ДОМОЙ: МЕХАНИЗМ"]
    assert mech == "МЕХАНИЗМ: FAIL (B word_set, ДОМОЙ, ошибка ДОМОЙ/СТОП, не выполнены: D, C)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"
    assert lines[-1].startswith("итог: B=FAIL D=— C=— ДОМОЙ=FAIL СТОП=PASS → код 1 ")


def test_unexpected_exception_inside_case_is_error_label() -> None:
    def boom(world, real, target, command, args, **kw):
        if command == "scene.sequence" and "discs" in args:
            raise RuntimeError("бум")
        return NotImplemented

    rc, out = A._run(H._Hooked({("sim", "send_command"): boom}))
    cls, mech, acc, _, _ = A._a2(out)
    assert rc == 3, out
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (ошибка, не выполнены: B, D, C)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


def test_ctrl_c_in_normal_tail_is_interrupted_label() -> None:
    def interrupt(world, real, target, command, args, **kw):
        if command == "robot_park_all":
            raise KeyboardInterrupt
        return NotImplemented

    box, out = H._run_kw(H._Hooked({("proto", "send_command"): interrupt}))
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    cls, mech, acc, _, _ = A._a2(out)
    assert cls == []
    assert mech == "МЕХАНИЗМ: FAIL (прервано, не выполнены: ДОМОЙ, СТОП)"
    assert acc == "ТОЧНОСТЬ: 0 трудных"


# --- nit 6: пропуск «ниже порога» без скобок --------------------------------------------------------------------------


def test_below_threshold_skip_without_parentheses_still_flags_below_threshold(monkeypatch, tmp_path) -> None:
    A._patch_cases(monkeypatch, b_lost=True)
    net = {("B", A._pre("М", 300.0)): A._full(f"{A._pre('М', 300.0)} → пропуск: уверенность ниже порога")}
    out_file = tmp_path / "hard.jsonl"
    rc, out = A._run(A._Net(rewrites=net), ["--hard-out", str(out_file)])
    assert rc == 1, out
    assert A._read_hard(out_file) == [
        {
            "case": "B",
            "index": 12,
            "truth": {"class": "М", "angle_deg": 300.0},
            "pred": {"class": "М", "angle_deg": 300.0, "confidence": None, "below_threshold": True},
            "delta_angle_deg": 0.0,
            "hard": True,
            "hard_reasons": ["below_threshold"],
            "hard_reasons_ru": ["ниже порога"],
            "angle_thr": 5.0,
            "conf_thr": None,
        }
    ]
