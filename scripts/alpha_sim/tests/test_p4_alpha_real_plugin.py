"""P4 скрипт α, RED 8: журнал настоящего WordLayoutPlugin судится ``judge_journal`` (B, D, C).

Настоящие объекты: плагин, рецепт ``letter_robot_sim.yaml``, ``MockProcessServices``. Помощники ``_make``,
``_recipe_cfg``, ``_disc``, ``_set_word`` и константы скопированы из
``Plugins/processing/word_layout/tests/test_p3_disk_journal.py`` (в тестовом модуле, не в conftest).
Сообщения журнала — ``services.logs[i]["msg"]``. Модуль ``scripts.alpha_sim.logic`` импортируется внутри теста.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_ROOT = Path(__file__).resolve().parents[3]
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


def _disc(label: str, tid: object | None = 1, angle: float = 0.0, *, pick: bool = True, **extra: object) -> dict:
    pred = {"label": label, "confidence": 0.9, "angle_deg": angle, "angle_valid": True}
    pred.update(extra)
    item: dict = {"predictions": [pred]}
    if tid is not None:
        item["sidecar"] = {"track_id": tid}
    if pick:
        item["pick_xy"] = dict(_PICK)
    return item


def _set_word(p: WordLayoutPlugin, word: str) -> None:
    ok, _ = p._reg.update_field("target_word", word)
    assert ok is True


# --- диски случаев (design.md §2.4-§2.6), tid сквозные ----------------------------------------------------------------

_B_DISCS = [("Р", 0.0), ("А", 0.0), ("Е", 30.0), ("И", 60.0), ("Е", 90.0), ("Б", 0.0),
            ("Р", 300.0), ("Е", 330.0), ("И", 30.0), ("Е", 60.0), ("П", 90.0), ("М", 300.0)]  # fmt: skip
_D_DISCS = [("П", 0.0), ("М", 30.0), ("Е", 0.0), ("И", 90.0), ("Р", 300.0)]
_C_DISCS = [("Е", 0.0), ("Е", 30.0), ("Е", 60.0), ("Е", 90.0)]


def _L():
    return importlib.import_module("scripts.alpha_sim.logic")


def _feed(p: WordLayoutPlugin, discs: list[tuple[str, float]], first_tid: int) -> None:
    for tid, (letter, angle) in enumerate(discs, start=first_tid):
        p.process([_disc(letter, tid, angle)])


def _msgs(s: MockProcessServices, start: int = 0) -> list[str]:
    return [e["msg"] for e in s.logs[start:]]


def _disk_count(msgs: list[str]) -> int:
    return len([m for m in msgs if "диск '" in m])


def _regs_literal(p: WordLayoutPlugin, case) -> None:
    for key in ("word_norm", "slots_total", "slots_filled", "jobs_emitted", "done"):
        assert getattr(p._reg, key) == case.regs[key], (case.case_id, key)


def test_real_plugin_lines_judged_b_d_c() -> None:
    L = _L()
    p, s = _make(full=_recipe_cfg(word_source=""))
    assert p._reg.target_word == "", "рецепт как есть: слово пусто"

    # B
    _set_word(p, "ПЕРЕМИРИЕ")
    _feed(p, _B_DISCS, 1)
    msgs_b = _msgs(s)
    assert _disk_count(msgs_b) == 12
    res_b = L.judge_journal("B", msgs_b)
    assert res_b.ok is True, [r for r in (*res_b.rows, *res_b.checks) if not r.ok]
    assert [r.index for r in res_b.rows] == list(range(1, 13))
    assert len([m for m in msgs_b if "→ ячейка" in m]) == 9 == L.CASES["B"].jobs
    _regs_literal(p, L.CASES["B"])

    # D: смена слова на ходу
    n0 = len(s.logs)
    _set_word(p, "МИР")
    _feed(p, _D_DISCS, 13)
    msgs_d = _msgs(s, n0)
    assert _disk_count(msgs_d) == 5
    res_d = L.judge_journal("D", msgs_d)
    assert res_d.ok is True, [r for r in (*res_d.rows, *res_d.checks) if not r.ok]
    assert len([m for m in msgs_d if "→ ячейка" in m]) == 3 == L.CASES["D"].jobs
    _regs_literal(p, L.CASES["D"])

    # C: одинаковые диски подряд
    n0 = len(s.logs)
    _set_word(p, "ПЕРЕМИРИЕ")
    _feed(p, _C_DISCS, 18)
    msgs_c = _msgs(s, n0)
    assert _disk_count(msgs_c) == 4
    res_c = L.judge_journal("C", msgs_c)
    assert res_c.ok is True, [r for r in (*res_c.rows, *res_c.checks) if not r.ok]
    assert len([m for m in msgs_c if "→ ячейка" in m]) == 3 == L.CASES["C"].jobs
    _regs_literal(p, L.CASES["C"])

    # пара: чужой журнал не проходит чужое судейство (B-журнал против D)
    assert L.judge_journal("D", msgs_b).ok is False


def test_real_plugin_typo_word_fails_control() -> None:
    """Контроль: слово «ПЕРЕМИРЕИ» (буквы те же, порядок другой) с теми же дисками B → FAIL."""
    L = _L()
    p, s = _make(full=_recipe_cfg(word_source=""))
    _set_word(p, "ПЕРЕМИРЕИ")
    _feed(p, _B_DISCS, 1)
    msgs = _msgs(s)
    assert _disk_count(msgs) == 12
    res = L.judge_journal("B", msgs)
    assert res.ok is False
    assert any(not r.ok for r in res.rows), "слово-опечатка должно дать другие ячейки хотя бы у одного диска"
    assert any(c.check == "word_line" and not c.ok for c in res.checks)
