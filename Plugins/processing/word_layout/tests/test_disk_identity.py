"""C-32: word_layout различает диски по ``sidecar.track_id``; смена слова пишется в журнал.

Приёмочные тесты A1–A20 (plans/word-layout/tasks/C-32.md), написаны до правки кода.
Ячейки слова «ПЕРЕМИРИЕ»: П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8; «слот» = ``robot_job["slot"]`` или ``None``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_BASE = {"require_pick": False, "word_source": "", "settle_frames": 1, "target_word": "ПЕРЕМИРИЕ"}
_CHANGE_MARK = "смена слова"


def _make(cfg: dict | None = None) -> tuple[WordLayoutPlugin, MockProcessServices]:
    full = dict(_BASE)
    full.update(cfg or {})
    services = MockProcessServices(name="layout", config=full)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=full))
    return plugin, services


def _pred(label: str, angle: float = 0.0, conf: float = 0.9) -> dict:
    return {"label": label, "confidence": conf, "angle_deg": angle, "angle_valid": True}


def _disk(label: str, tid: object, angle: float = 0.0) -> dict:
    return {"predictions": [_pred(label, angle)], "sidecar": {"track_id": tid}}


def _slot(p: WordLayoutPlugin, item: dict) -> int | None:
    out = p.process([item])[0]
    job = out.get("robot_job")
    return job["slot"] if job else None


def _slots(p: WordLayoutPlugin, items: list[dict]) -> list[int | None]:
    return [_slot(p, it) for it in items]


def _changes(services: MockProcessServices) -> list[str]:
    return [e["msg"] for e in services.logs if _CHANGE_MARK in e["msg"]]


# --- A1–A5: новые красные ---------------------------------------------------


def test_two_same_letters_distinct_tracks() -> None:
    p, _ = _make()
    assert _slots(p, [_disk("Р", 1), _disk("Р", 2)]) == [2, 6]
    assert p._reg.slots_filled == 2


def test_track_id_zero_is_identity() -> None:
    p, _ = _make()
    items = [_disk("Р", 0), {"predictions": []}, _disk("Р", 0), _disk("Р", 1)]
    assert _slots(p, items) == [2, None, None, 6]


def test_word_with_adjacent_repeats() -> None:
    p, _ = _make()
    letters = ["Е", "Е", "Р", "Р", "И", "И", "П", "М", "Е"]
    items = [_disk(ch, i + 1) for i, ch in enumerate(letters)]
    assert _slots(p, items) == [1, 3, 2, 6, 5, 7, 0, 4, 8]
    assert p._reg.done is True
    assert p._reg.jobs_emitted == 9


def test_case_b_d_c_sequence() -> None:
    p, services = _make()

    # B: полное слово ПЕРЕМИРИЕ с шумом (А, Б вне слова), сквозные tid 1..12
    seq_b = [("Р", 0), ("А", 0), ("Е", 30), ("И", 60), ("Е", 90), ("Б", 0),
             ("Р", 300), ("Е", 330), ("И", 30), ("Е", 60), ("П", 90), ("М", 300)]  # fmt: skip
    got_b = _slots(p, [_disk(ch, i + 1, ang) for i, (ch, ang) in enumerate(seq_b)])
    assert got_b == [2, None, 1, 5, 3, None, 6, 8, 7, None, 0, 4]
    assert p._reg.slots_filled == 9
    assert p._reg.done is True
    assert p._reg.jobs_emitted == 9

    # D: смена слова на ходу на «МИР», tid 13..17
    ok, _ = p._reg.update_field("target_word", "МИР")
    assert ok is True
    seq_d = [("П", 0), ("М", 30), ("Е", 0), ("И", 90), ("Р", 300)]
    got_d = _slots(p, [_disk(ch, 13 + i, ang) for i, (ch, ang) in enumerate(seq_d)])
    assert got_d == [None, 0, None, 1, 2]
    assert p._reg.word_norm == "МИР"
    assert p._reg.slots_total == 3
    assert p._reg.slots_filled == 3
    assert p._reg.done is True
    assert p._reg.jobs_emitted == 12

    # C: обратно на «ПЕРЕМИРИЕ», Е под углами 0/30/60/90, tid 18..21
    ok, _ = p._reg.update_field("target_word", "ПЕРЕМИРИЕ")
    assert ok is True
    outs = [p.process([_disk("Е", 18 + i, ang)])[0] for i, ang in enumerate([0.0, 30.0, 60.0, 90.0])]
    jobs = [o.get("robot_job") for o in outs]
    assert [j["slot"] if j else None for j in jobs] == [1, 3, 8, None]
    assert [jobs[0]["place_rz_deg"], jobs[1]["place_rz_deg"], jobs[2]["place_rz_deg"]] == [0.0, -30.0, -60.0]
    assert p._reg.slots_filled == 3
    assert p._reg.done is False
    assert p._reg.jobs_emitted == 15

    # Журнал — ровно две смены слова, в порядке событий
    changes = _changes(services)
    assert len(changes) == 2
    assert "смена слова 'ПЕРЕМИРИЕ' → 'МИР'" in changes[0]
    assert "было заполнено 9/9" in changes[0]
    assert "смена слова 'МИР' → 'ПЕРЕМИРИЕ'" in changes[1]
    assert "было заполнено 3/3" in changes[1]


def test_word_change_via_port() -> None:
    p, services = _make({"word_source": "word", "target_word": ""})
    assert _slot(p, {"word": "ПЕРЕМИРИЕ"}) is None
    assert _slot(p, _disk("Р", 1)) == 2
    _slot(p, {"word": "МИР"})
    assert _slot(p, _disk("М", 2)) == 0
    assert len(_changes(services)) == 1
    _slot(p, {"word": "МИР"})
    assert len(_changes(services)) == 1


# --- A6–A8: стражи ----------------------------------------------------------


def test_first_build_logs_no_change() -> None:
    p, services = _make()
    assert _slot(p, _disk("Р", 1)) == 2
    assert _changes(services) == []


def test_same_track_three_items_one_cell() -> None:
    p, _ = _make()
    assert _slots(p, [_disk("Р", 7)] * 3) == [2, None, None]
    assert p._reg.slots_filled == 1


def test_no_track_three_items_one_cell() -> None:
    p, _ = _make()
    assert _slots(p, [{"predictions": [_pred("Р")]}] * 3) == [2, None, None]


# --- A9–A12 -----------------------------------------------------------------


def test_label_flicker_same_track_one_cell() -> None:
    p, _ = _make()
    assert _slots(p, [_disk("Р", 7), _disk("Е", 7)]) == [2, None]


def test_control_item_between_same_track() -> None:
    p, _ = _make()
    assert _slots(p, [_disk("Р", 7), {"predictions": []}, _disk("Р", 7)]) == [2, None, None]


def test_weak_then_confident_same_track() -> None:
    p, _ = _make()
    weak = {"predictions": [_pred("Р", conf=0.1)], "sidecar": {"track_id": 8}}
    assert _slots(p, [weak, _disk("Р", 8)]) == [None, 2]


def test_settle_two_with_tracks() -> None:
    p, _ = _make({"settle_frames": 2})
    items = [_disk("Р", 1), _disk("Р", 1), _disk("Р", 2), _disk("Р", 2)]
    assert _slots(p, items) == [None, 2, None, 6]


# --- A13, A14, A16: взятый tid переживает сброс / возврат / смену слова ------


def test_reset_keeps_taken_track() -> None:
    p, _ = _make()
    assert _slot(p, _disk("Р", 5)) == 2
    p.cmd_reset({})
    assert _slot(p, _disk("Р", 5)) is None
    assert _slot(p, _disk("Р", 6)) == 2


def test_return_keeps_taken_track() -> None:
    p, _ = _make()
    assert _slot(p, _disk("Р", 5)) == 2
    out = p.process([{"signal_1": 1}])[0]
    assert "robot_return_jobs" in out
    assert _slot(p, _disk("Р", 5)) is None
    assert _slot(p, _disk("Р", 6)) == 2


def test_word_change_keeps_taken_track() -> None:
    p, _ = _make()
    assert _slot(p, _disk("Р", 1)) == 2
    ok, _ = p._reg.update_field("target_word", "МИР")
    assert ok is True
    assert _slot(p, _disk("Р", 1)) is None
    assert _slot(p, _disk("Р", 2)) == 2


# --- A17–A20 ----------------------------------------------------------------


def test_new_track_resets_partial_settle() -> None:
    p, _ = _make({"settle_frames": 2})
    assert _slots(p, [_disk("Р", 1), _disk("Р", 2), _disk("Р", 2)]) == [None, None, 2]


def test_geometry_only_rebuild_no_log() -> None:
    p, services = _make()
    assert _slot(p, _disk("Р", 1)) == 2
    ok, _ = p._reg.update_field("first_y", -440.0)
    assert ok is True
    assert _slot(p, _disk("Р", 2)) == 2
    assert p._reg.slots_filled == 1
    assert _changes(services) == []


def test_sidecar_without_track_id_is_legacy() -> None:
    p, _ = _make()
    items = [
        {"predictions": [_pred("Р")], "sidecar": None},
        {"predictions": [_pred("Р")], "sidecar": "x"},
        {"predictions": [_pred("Р")], "sidecar": {"center_px": [1, 2]}},
    ]
    assert _slots(p, items) == [2, None, None]


def test_use_trigger_ignores_track() -> None:
    p, _ = _make({"use_trigger": True, "trigger_source": "trigger"})
    item = {"trigger": 1, **_disk("Р", 5)}
    assert _slots(p, [item, dict(item)]) == [2, 6]
