"""alpha_sim, Task A: сторож критерия «пропуск ниже порога» на уровне ``run()``.

Дыра, найденная break-injection I3: у B#12 сеть читает «И» вместо «М», и диск «не признан» уже по причинам
``letter``/``feed``; критерий «пропуск: уверенность ниже порога» в ``_unrecognized`` ни один тест ``run()`` не держал.
Здесь сеть отдаёт ВЕРНУЮ букву «М» (угол 300,0° тот же) с уверенностью ниже порога: единственное, что делает диск
не признанным, — текст пропуска. Ожидания — литералы задачи (plans/release-1.0/lane-tasks/alpha-hard-split.md).
Фейки и помощники — из приёмочного файла (``_Net``, ``_patch_cases``, ``_run``, ``_a2``, ``_read_hard``).
"""

from __future__ import annotations

import pytest

from scripts.alpha_sim.tests import test_alpha_split_acceptance as A


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
