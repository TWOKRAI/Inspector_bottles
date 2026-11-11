"""C-86(a): авторские hazard-тесты строки «диск ниже порога / без предсказания».

Каждый тест привязан к инъекции (ломке кода), которую обязан поймать: см. docstring.
Приёмка контракта — ``test_c86a_silent_drop_acceptance.py`` (слепой тестер); здесь — порядок,
общий ключ, охранники хелпера ``_note_unconfident``. Харнес — как в ``test_p3_disk_journal.py``.
Слово «ПЕРЕМИРИЕ»: П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8; буквы кириллические (М = U+041C).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_BASE = {
    "target_word": "ПЕРЕМИРИЕ",
    "word_source": "",
    "settle_frames": 1,
    "require_pick": True,
    "first_x": 320.0,
    "first_y": -440.0,
    "place_z_mm": -132.0,
    "pick_z_mm": -132.0,
}
_PICK = {"x_mm": 458.2, "y_mm": -343.0}

_WEAK_M_TID = "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.30 < 0.50)"
_NO_PRED = "WordLayoutPlugin: диск '?' 0.0° → пропуск: нет предсказания"


def _make(cfg: dict | None = None) -> tuple[WordLayoutPlugin, MockProcessServices]:
    conf = dict(_BASE)
    conf.update(cfg or {})
    services = MockProcessServices(name="layout", config=conf)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services


def _disc(
    label: str,
    tid: object | None = 1,
    angle: float | None = 0.0,
    *,
    confidence: float = 0.9,
    below: bool | None = None,
) -> dict:
    pred: dict = {"label": label, "confidence": confidence, "angle_deg": angle, "angle_valid": True}
    if below is not None:
        pred["below_threshold"] = below
    item: dict = {"predictions": [pred], "pick_xy": dict(_PICK)}
    if tid is not None:
        item["sidecar"] = {"track_id": tid}
    return item


def _weak(tid: object | None = 1, *, label: str = "М", confidence: float = 0.3, angle: float = 300.0) -> dict:
    return _disc(label, tid, angle, confidence=confidence, below=True)


def _lines(services: MockProcessServices) -> list[str]:
    """Строки журнала диска (INFO «диск '...»), по порядку."""
    return [e["msg"] for e in services.logs if "диск '" in e["msg"]]


def _errors(services: MockProcessServices) -> list[str]:
    return [e["msg"] for e in services.logs if e["level"] == "ERROR"]


def _run(p: WordLayoutPlugin, item: dict) -> dict:
    return p.process([item])[0]


def test_h1_weak_then_confident_same_tid_two_lines_and_job() -> None:
    """H1 (I1/I2): слабый кадр, затем уверенный кадр ТОГО ЖЕ tid -> строка слабого, затем «ячейка», задание выдано.

    Задокументированная особенность многокадрового тракта: у такого диска две строки.
    """
    p, s = _make()
    out_weak = _run(p, _weak(5, label="Р", confidence=0.3, angle=0.0))
    out_ok = _run(p, _disc("Р", 5, 0.0, confidence=0.9, below=False))
    lines = _lines(s)
    assert len(lines) == 2
    assert lines[0] == "WordLayoutPlugin: диск 'Р' 0.0° → пропуск: уверенность ниже порога (Р 0.30 < 0.50)"
    assert "→ ячейка 2:" in lines[1]
    assert "robot_job" not in out_weak
    assert out_ok["robot_job"]["slot"] == 2
    assert p._reg.jobs_emitted == 1


def test_h2_skipped_not_in_word_then_weak_same_tid_no_extra_line() -> None:
    """H2 (I4): «А» tid 7 пропущен «нет в слове» (взят как решение), затем слабый кадр tid 7 -> новых строк нет."""
    p, s = _make()
    _run(p, _disc("А", 7, 10.0, confidence=0.9, below=False))
    before = _lines(s)
    assert len(before) == 1
    assert "→ пропуск: нет в слове 'ПЕРЕМИРИЕ'" in before[0]
    _run(p, _weak(7))
    assert _lines(s) == before


def test_h3_trigger_mode_weak_tid_no_weak_line() -> None:
    """H3 (I5): триггер-режим, слабый tid-item с сигналом -> строки слабого диска нет, задания нет."""
    p, s = _make({"use_trigger": True, "trigger_source": "trigger"})
    out = _run(p, {**_weak(3), "trigger": True})
    assert _lines(s) == []
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


def test_h4_weak_with_angle_none_one_error_no_line_no_job() -> None:
    """H4 (I6): below_threshold и angle_deg None -> ровно одна ERROR-строка, строки диска нет, решение прежнее."""
    p, s = _make()
    item = _disc("М", 1, None, confidence=0.3, below=True)
    out = _run(p, item)
    assert _errors(s) == ["WordLayoutPlugin: строка пропуска 'ниже порога' не записана: TypeError"]
    assert _lines(s) == []
    assert out is item
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0
    assert p._reg.slots_filled == 0


def test_h5_taken_tid_disc_then_weak_without_tid_no_line() -> None:
    """H5 (I7): диск с tid взят (_taken_track не None), затем слабый кадр БЕЗ track_id -> новых строк нет."""
    p, s = _make()
    _run(p, _disc("Р", 1, 0.0, confidence=0.9, below=False))
    before = _lines(s)
    assert len(before) == 1
    _run(p, _weak(None))
    assert _lines(s) == before


def test_h6_weak_tid_zero_one_line() -> None:
    """H6: id 0 допустим (проверка `is not None`, не по истинности) -> одна строка."""
    p, s = _make()
    _run(p, _weak(0))
    assert _lines(s) == [_WEAK_M_TID]


def test_h7_weak_then_empty_predictions_same_tid_one_line() -> None:
    """H7 (I2): слабый кадр, затем predictions == [] с тем же tid -> одна строка (общий ключ, первая побеждает)."""
    p, s = _make()
    _run(p, _weak(4))
    _run(p, {"predictions": [], "sidecar": {"track_id": 4}, "pick_xy": dict(_PICK)})
    assert _lines(s) == [_WEAK_M_TID]


def test_h8_nan_confidence_flag_false_line_with_nan() -> None:
    """H8: confidence NaN, below_threshold False -> строка «(М nan < 0.50)» (NaN не проходит как уверенный)."""
    p, s = _make()
    out = _run(p, _disc("М", 1, 300.0, confidence=float("nan"), below=False))
    assert _lines(s) == ["WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М nan < 0.50)"]
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


def test_no_prediction_line_literal_for_missing_key() -> None:
    """Нет ключа predictions вовсе, tid есть -> строка «нет предсказания» (ветка I3 без приёмки)."""
    p, s = _make()
    _run(p, {"sidecar": {"track_id": 9}, "pick_xy": dict(_PICK)})
    assert _lines(s) == [_NO_PRED]


def test_h9_threshold_text_follows_own_min_confidence() -> None:
    """H9: порог в скобках — свой min_confidence (0.70), а при conf == min_confidence с флагом — ml_inference."""
    p, s = _make({"min_confidence": 0.7})
    _run(p, _disc("М", 1, 300.0, confidence=0.6, below=False))
    _run(p, _disc("М", 2, 300.0, confidence=0.7, below=True))
    assert _lines(s) == [
        "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.60 < 0.70)",
        "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.70 < порог ml_inference)",
    ]


def test_h9_boundary_default_min_confidence_flag_true() -> None:
    """H9: min_confidence 0.5 по умолчанию, conf 0.50 с флагом -> «(М 0.50 < порог ml_inference)»."""
    p, s = _make()
    _run(p, _disc("М", 1, 300.0, confidence=0.5, below=True))
    assert _lines(s) == [
        "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.50 < порог ml_inference)"
    ]


def test_h10_weak_frame_does_not_disturb_settle_counter() -> None:
    """H10: settle_frames 2; слабый, уверенный, уверенный кадр одного tid -> задание только на 3-м кадре.

    Хелпер не трогает _settle/_cur_label: иначе счёт стабильности сбился бы."""
    p, _ = _make({"settle_frames": 2})
    outs = [
        _run(p, _weak(1)),
        _run(p, _disc("М", 1, 300.0, confidence=0.9, below=False)),
        _run(p, _disc("М", 1, 300.0, confidence=0.9, below=False)),
    ]
    assert ["robot_job" in o for o in outs] == [False, False, True]
    assert p._reg.jobs_emitted == 1


@pytest.mark.parametrize(
    "preds",
    [[{"confidence": 0.9}], [{"label": "", "confidence": 0.9}], ["x"], [None], "abc"],
    ids=["no-label", "empty-label", "str-top", "none-top", "str-preds"],
)
def test_h11_malformed_predictions_with_tid_no_prediction_line(preds: object) -> None:
    """H11: кривые predictions с tid -> строка «нет предсказания», ошибок в журнале нет."""
    p, s = _make()
    out = _run(p, {"predictions": preds, "sidecar": {"track_id": 1}, "pick_xy": dict(_PICK)})
    assert _lines(s) == [_NO_PRED]
    assert _errors(s) == []
    assert "robot_job" not in out


def test_h12_lowercase_label_printed_uppercase() -> None:
    """H12: метка «м» в нижнем регистре печатается как «М» (как в ячейках слова)."""
    p, s = _make()
    _run(p, _weak(1, label="м"))
    assert _lines(s) == [_WEAK_M_TID]
