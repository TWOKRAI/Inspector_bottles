"""P3 word-layout: журнал каждого диска, 9 ячеек в досягаемости сима, смена слова на ходу.

Приёмочные тесты REDS 1-14 (plans/word-layout/tasks/P3.md), написаны слепым тестером до правки
кода. Публичный путь: ``configure`` / ``process`` / ``_reg.update_field``; наблюдаемое —
``services.logs[i]["msg"]``, ``robot_job``, регистры. Ожидаемые значения — литералы из REDS.

Ячейки слова «ПЕРЕМИРИЕ» (база): П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Services.robot_comm.core.protocol_v2 import OP, REG
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

_ROOT = Path(__file__).resolve().parents[4]
_RECIPE = _ROOT / "multiprocess_prototype" / "recipes" / "letter_robot_sim.yaml"

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
_WORD = "ПЕРЕМИРИЕ"


# --- харнес ------------------------------------------------------------------


def _make(cfg: dict | None = None, *, full: dict | None = None) -> tuple[WordLayoutPlugin, MockProcessServices]:
    conf = dict(full) if full is not None else dict(_BASE)
    conf.update(cfg or {})
    services = MockProcessServices(name="layout", config=conf)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services


def _find_layout(node: object) -> dict | None:
    if isinstance(node, dict):
        if node.get("process_name") == "layout":
            return node
        for v in node.values():
            r = _find_layout(v)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_layout(v)
            if r is not None:
                return r
    return None


def _recipe_cfg(**over: object) -> dict:
    """Конфиг плагина word_layout из рецепта letter_robot_sim.yaml, как есть; поверх — over."""
    proc = _find_layout(yaml.safe_load(_RECIPE.read_text(encoding="utf-8")))
    assert proc is not None, "в рецепте нет процесса layout"
    plug = next(p for p in proc["plugins"] if p["plugin_name"] == "word_layout")
    conf = dict(plug["config"])
    conf.update(over)
    return conf


def _make_recipe(**over: object) -> tuple[WordLayoutPlugin, MockProcessServices]:
    return _make(full=_recipe_cfg(**over))


def _disc(label: str, tid: object | None = 1, angle: float = 0.0, *, pick: bool = True, **extra: object) -> dict:
    pred = {"label": label, "confidence": 0.9, "angle_deg": angle, "angle_valid": True}
    pred.update(extra)
    item: dict = {"predictions": [pred]}
    if tid is not None:
        item["sidecar"] = {"track_id": tid}
    if pick:
        item["pick_xy"] = dict(_PICK)
    return item


def _lines(services: MockProcessServices) -> list[str]:
    """Строки журнала «диск '<буква>' ...» (по одной на диск)."""
    return [e["msg"] for e in services.logs if "диск '" in e["msg"]]


def _with(services: MockProcessServices, needle: str) -> list[str]:
    return [e["msg"] for e in services.logs if needle in e["msg"]]


def _job(p: WordLayoutPlugin, item: dict) -> dict | None:
    return p.process([item])[0].get("robot_job")


def _slot(p: WordLayoutPlugin, item: dict) -> int | None:
    job = _job(p, item)
    return job["slot"] if job else None


def _set_word(p: WordLayoutPlugin, word: str) -> None:
    ok, _ = p._reg.update_field("target_word", word)
    assert ok is True


# --- RED 1 -------------------------------------------------------------------


def test_taken_disk_line_literal() -> None:
    p, s = _make()
    item = _disc("Е", 1, 30.0)
    assert _slot(p, item) == 1
    assert _lines(s) == [
        "WordLayoutPlugin: диск 'Е' 30.0° → ячейка 1: взять(458.2,-343.0) → положить "
        "x320.0 y-330.0 z-132.0 r-30.0° [1/9]"
    ]
    _job(p, item)
    _job(p, item)
    assert len(_lines(s)) == 1, "тот же item x3 — строка одна"

    _job(p, _disc("Р", 2, 0.04))
    line_r = _lines(s)[1]
    assert "диск 'Р' 0.0°" in line_r
    assert "r0.0°" in line_r
    assert "r-0.0°" not in line_r

    _job(p, _disc("И", 3, -0.04))
    assert "диск 'И' 0.0°" in _lines(s)[2]


# --- RED 2 -------------------------------------------------------------------


def test_skip_not_in_word_line() -> None:
    p, s = _make()
    assert _job(p, _disc("А", 1, 0.0)) is None
    assert _lines(s) == ["WordLayoutPlugin: диск 'А' 0.0° → пропуск: нет в слове 'ПЕРЕМИРИЕ'"]
    assert _job(p, _disc("П", 2, 0.0)) is not None


# --- RED 3 -------------------------------------------------------------------


def test_skip_cells_occupied_line() -> None:
    p, s = _make()
    for tid, ang in enumerate([0.0, 30.0, 60.0, 90.0], start=1):
        _job(p, _disc("Е", tid, ang))
    lines = _lines(s)
    assert len(lines) == 4
    assert lines[3] == "WordLayoutPlugin: диск 'Е' 90.0° → пропуск: ячейки 'Е' заняты (1, 3, 8)"


# --- RED 4 -------------------------------------------------------------------


def test_skip_word_done_line() -> None:
    letters = ["П", "Е", "Р", "Е", "М", "И", "Р", "И", "Е"]

    # с track_id: 9-й диск подан x3 кадра тем же tid
    p, s = _make()
    for i, ch in enumerate(letters[:-1], start=1):
        _job(p, _disc(ch, i))
    for _ in range(3):
        _job(p, _disc(letters[-1], 9))
    assert p._reg.done is True
    assert _with(s, "слово готово") == []

    for _ in range(3):
        _job(p, _disc("Е", 10, 0.0))
    assert _with(s, "слово готово") == ["WordLayoutPlugin: диск 'Е' 0.0° → пропуск: слово готово"]
    assert p._reg.jobs_emitted == 9

    # без track_id: 9-я буква x3 кадра — по метке
    p2, s2 = _make()
    for ch in letters[:-1]:
        _job(p2, _disc(ch, None))
    for _ in range(3):
        _job(p2, _disc(letters[-1], None))
    assert p2._reg.done is True
    assert _with(s2, "слово готово") == []


# --- RED 5 -------------------------------------------------------------------


def test_recipe_default_empty_word_says_so() -> None:
    p, s = _make_recipe(word_source="")
    assert p._reg.target_word == "", "рецепт как есть: target_word ''"
    for _ in range(3):
        assert _job(p, _disc("Р", 1, 0.0)) is None
    assert _lines(s) == ["WordLayoutPlugin: диск 'Р' 0.0° → пропуск: слово не задано"]

    _set_word(p, "ПЕРЕМИРИЕ")
    assert _slot(p, _disc("Р", 2, 0.0)) == 2


# --- RED 6 -------------------------------------------------------------------


def test_skip_no_pick_line() -> None:
    p, s = _make()
    assert _job(p, _disc("П", 1, 0.0, pick=False)) is None
    assert _lines(s) == ["WordLayoutPlugin: диск 'П' 0.0° → пропуск: нет координаты забора"]
    assert p._reg.slots_filled == 0
    assert _slot(p, _disc("П", 2, 0.0)) == 0

    p2, s2 = _make({"require_pick": False})
    _job(p2, _disc("П", 1, 0.0, pick=False))
    assert _lines(s2) == ["WordLayoutPlugin: диск 'П' 0.0° → ячейка 0: положить x320.0 y-440.0 z-132.0 r0.0° [1/9]"]


# --- RED 7 -------------------------------------------------------------------

_CASE_B = [("Р", 0), ("А", 0), ("Е", 30), ("И", 60), ("Е", 90), ("Б", 0),
           ("Р", 300), ("Е", 330), ("И", 30), ("Е", 60), ("П", 90), ("М", 300)]  # fmt: skip
_CASE_B_DECISIONS = [
    "→ ячейка 2:",
    "→ пропуск: нет в слове 'ПЕРЕМИРИЕ'",
    "→ ячейка 1:",
    "→ ячейка 5:",
    "→ ячейка 3:",
    "→ пропуск: нет в слове 'ПЕРЕМИРИЕ'",
    "→ ячейка 6:",
    "→ ячейка 8:",
    "→ ячейка 7:",
    "→ пропуск: ячейки 'Е' заняты (1, 3, 8)",
    "→ ячейка 0:",
    "→ ячейка 4:",
]


def test_case_b_twelve_lines_in_order() -> None:
    p, s = _make()
    for i, (ch, ang) in enumerate(_CASE_B, start=1):
        _job(p, _disc(ch, i, float(ang)))
    lines = _lines(s)
    assert len(lines) == 12
    for i, ((ch, _), decision) in enumerate(zip(_CASE_B, _CASE_B_DECISIONS, strict=True), start=1):
        assert f"диск '{ch}'" in lines[i - 1], f"диск {i}: буква"
        assert decision in lines[i - 1], f"диск {i}: решение, строка {lines[i - 1]!r}"
    assert "r60.0°" in lines[6]
    assert "r30.0°" in lines[7]


# --- RED 8 -------------------------------------------------------------------


def test_word_change_midword_cells_from_zero() -> None:
    p, s = _make()
    assert [_slot(p, _disc(ch, i)) for i, ch in enumerate("РЕИ", start=1)] == [2, 1, 5]
    for line, cell in zip(_lines(s), (2, 1, 5), strict=True):
        assert f"→ ячейка {cell}:" in line

    _set_word(p, "МИР")
    assert [_slot(p, _disc(ch, i)) for i, ch in enumerate("МИР", start=4)] == [0, 1, 2]
    for line, cell in zip(_lines(s)[3:], (0, 1, 2), strict=True):
        assert f"→ ячейка {cell}:" in line
    assert p._reg.slots_filled == 3
    assert p._reg.slots_total == 3
    assert p._reg.done is True
    assert p._reg.jobs_emitted == 6
    change = _with(s, "смена слова")
    assert len(change) == 1
    assert "смена слова 'ПЕРЕМИРИЕ' → 'МИР'" in change[0]
    assert "было заполнено 3/9" in change[0]

    _set_word(p, "ПЕРЕМИРИЕ")
    assert _slot(p, _disc("Р", 7)) == 2
    last = _lines(s)[-1]
    assert "→ ячейка 2:" in last
    assert "[1/9]" in last


# --- RED 9 -------------------------------------------------------------------


def _recipe_places() -> list[tuple[float, float]]:
    p, _ = _make_recipe(target_word=_WORD, word_source="")
    out = []
    for i, ch in enumerate("ПЕРЕМИРИЕ", start=1):
        job = _job(p, _disc(ch, i))
        assert job is not None, f"диск {i} '{ch}' не взят"
        out.append((job["place_x_mm"], job["place_y_mm"]))
    return out


def test_recipe_nine_cells_literal_coords() -> None:
    places = _recipe_places()
    expected = [
        (320.0, -440.0),
        (320.0, -330.0),
        (320.0, -220.0),
        (320.0, -110.0),
        (320.0, 0.0),
        (320.0, 110.0),
        (320.0, 220.0),
        (320.0, 330.0),
        (320.0, 440.0),
    ]
    assert len(places) == len(expected)
    # cos/sin от line_angle_deg дают шум ~1e-13 мм: сравниваем с допуском, не точным ==
    for (x, y), (ex, ey) in zip(places, expected, strict=True):
        assert (x, y) == (pytest.approx(ex, abs=1e-6), pytest.approx(ey, abs=1e-6))
    for x, y in places:
        assert math.hypot(x, y) <= 600.0


# --- RED 10 ------------------------------------------------------------------

_TICK_S = 0.01
_ACK = 1


def _mm(v: float) -> int:
    return round(v * 10) & 0xFFFF


def _sim_cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> int:
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick(_TICK_S)
    return core.read(REG["RES_STATUS"])[0]


def _run_idle(core: RobotSimCoreV2, cap: int = 3000) -> None:
    for _ in range(cap):
        if core.read(REG["TLM_ACTIVITY"])[0] == 0:
            return
        core.tick(_TICK_S)
    raise AssertionError("активность сима не закончилась")


def _cvt_place(core: RobotSimCoreV2, seq: int, x: float, y: float, r: float) -> int:
    status = _sim_cmd(
        core, seq, OP["CVT_JOB"], 0, 0, _mm(300.0), _mm(-200.0), 0, 2, _mm(x), _mm(y), _mm(-132.0), _mm(-100.0 + r)
    )
    _run_idle(core)
    return status


def test_recipe_cells_accepted_by_sim_cvt_job() -> None:
    places = _recipe_places()
    result: dict = {}

    def run() -> None:
        try:
            core = RobotSimCoreV2(fw_build=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
            statuses = []
            seq = 0
            for x, y in places:
                for r in (-179.9, 0.0, 180.0):
                    seq += 1
                    statuses.append(_cvt_place(core, seq, x, y, r))
            result["statuses"] = statuses
            result["control"] = _cvt_place(core, seq + 1, 320.0, 570.0, 0.0)
        except BaseException as exc:  # noqa: BLE001 - отдать в основной поток
            result["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(60.0)
    assert not t.is_alive(), "прогон сима завис"
    if "exc" in result:
        raise result["exc"]
    assert result["statuses"] == [_ACK] * 27
    assert result["control"] != _ACK


# --- RED 11 ------------------------------------------------------------------


def test_skipped_disk_taken_after_word_set_same_tid() -> None:
    # «слово не задано» → задали слово → тот же tid берётся
    p, s = _make({"target_word": ""})
    assert _job(p, _disc("Р", 1, 0.0)) is None
    assert len(_with(s, "слово не задано")) == 1
    _set_word(p, "ПЕРЕМИРИЕ")
    assert _slot(p, _disc("Р", 1, 0.0)) == 2

    # «слово готово» → новое слово → тот же tid: пропуск по новой причине, один раз
    p2, s2 = _make()
    for i, ch in enumerate("ПЕРЕМИРИЕ", start=1):
        assert _job(p2, _disc(ch, i)) is not None
    assert p2._reg.done is True
    assert _job(p2, _disc("Е", 10, 0.0)) is None
    assert len(_with(s2, "слово готово")) == 1
    _set_word(p2, "МИР")
    assert _job(p2, _disc("Е", 10, 0.0)) is None
    assert len(_with(s2, "пропуск: нет в слове 'МИР'")) == 1
    _job(p2, _disc("Е", 10, 0.0))
    assert len(_with(s2, "пропуск: нет в слове 'МИР'")) == 1, "тот же диск — один раз"


# --- RED 12 ------------------------------------------------------------------


def test_no_track_id_mode() -> None:
    p, s = _make()
    for _ in range(5):
        _job(p, _disc("Р", None, 0.0))
    assert len(_lines(s)) == 1
    assert "→ ячейка 2:" in _lines(s)[0]

    _job(p, {"predictions": []})
    _job(p, _disc("Р", None, 0.0))
    lines = _lines(s)
    assert len(lines) == 2
    assert "→ ячейка 6:" in lines[1]

    _job(p, _disc("Е", None, 0.0, below_threshold=True))
    assert len(_lines(s)) == 2, "кадр ниже порога — не диск"


# --- RED 13 ------------------------------------------------------------------


def test_trigger_mode() -> None:
    p, s = _make({"use_trigger": True, "trigger_source": "trigger"})
    for _ in range(3):
        _job(p, _disc("Р", 1, 0.0))
    assert _lines(s) == []
    _job(p, {**_disc("Р", 1, 0.0), "trigger": True})
    assert len(_lines(s)) == 1
    assert "→ ячейка 2:" in _lines(s)[0]

    # довести слово до готового: остальные буквы по одному сигналу
    for i, ch in enumerate("ПЕЕМИРИЕ", start=2):
        _job(p, {**_disc(ch, i, 0.0), "trigger": True})
    assert p._reg.done is True
    assert _with(s, "слово готово") == []

    for _ in range(2):
        _job(p, _disc("Е", 100, 0.0))
    assert _with(s, "слово готово") == []
    _job(p, {**_disc("Е", 100, 0.0), "trigger": True})
    assert _with(s, "слово готово") == ["WordLayoutPlugin: диск 'Е' 0.0° → пропуск: слово готово"]

    for _ in range(2):
        _job(p, {**_disc("Е", 100, 0.0), "trigger": True})
    assert len(_with(s, "слово готово")) == 3


# --- RED 14 ------------------------------------------------------------------


def test_angle_invalid_line() -> None:
    p, s = _make({"target_word": "ОКО"})
    item = _disc("О", 1, 45.0)
    item["predictions"][0]["angle_valid"] = False
    assert _job(p, item) is not None
    lines = _lines(s)
    assert len(lines) == 1
    assert "диск 'О' 45.0°" in lines[0]
    assert "r0.0°" in lines[0]
