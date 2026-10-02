# -*- coding: utf-8 -*-
# ruff: noqa: F811 - фикстура start_pult принимается тестами по имени
"""Хазарды автора Task 5.3, итерация 2: флаги «видим»/«заперт» против выбора и «Отмены».

Ревью итерации 1 нашло две дыры, обе - в местах, где выбор или имя слоя меняются мимо `presetSelectable`:
- 1а: «Отмена» возвращает в выбор слой, на котором стоит замок / снята видимость, и стрелки/Delete его трогают;
- 1б: новый слой с именем удалённого скрытого наследует флаг (призрачный флаг), рождается невидимым и выбранным;
- 2: переименование и «Отмена» несимметричны: флаг остаётся на имени, которого в пресете нет, и «приклеивается» к
  чужому слою, получившему это имя.
Каждый тест проверяет наблюдаемое: выбор, смещения в теле commit, пиксели канвы, `checked` чекбоксов.
Харнесс - `page_offline.mjs` без правок; фикстура слоёв и шаги - из слепой приёмки 5.3.
"""

from __future__ import annotations

import pytest

from Plugins.sim.pult_web.tests import test_acceptance_5_3_canvas_tools as t
from Plugins.sim.pult_web.tests.test_acceptance_1_3h_canvas import _NODE, _run, start_pult  # noqa: F401

CTRL_Z = {"op": "key_mod", "key": "z", "ctrl": True}
BTN_DOWN = {"op": "press_button", "id": "btnLayerDown"}


@pytest.fixture(autouse=True)
def _extra_sprites(monkeypatch):
    """Раскладка стенда строит картинку по ИМЕНИ слоя: новым именам (cap2, cap_2) даём красный спрайт cap."""
    monkeypatch.setitem(t._SPRITES, "cap2", t._SPRITES["cap"])
    monkeypatch.setitem(t._SPRITES, "cap_2", t._SPRITES["cap"])


def _rename(i: int, name: str) -> list[dict]:
    return [
        {"op": "set_field", "id": f"layer{i}_name", "value": name},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
    ]


@pytest.mark.parametrize(
    "kind, checked",
    [pytest.param("Lock", True, id="lock"), pytest.param("Vis", False, id="hidden")],
)
def test_undo_does_not_put_flagged_layer_back_into_selection(start_pult, kind: str, checked: bool) -> None:
    """1а: bolt выбран, «Ниже» (запись состава с выбором bolt), флаг на bolt (он стал строкой 1), Ctrl+Z.
    Флаг по имени остался, значит bolt не выбираем: выбор пуст, Shift+стрелка и Delete ничего не трогают
    (тело commit: три слоя в прежнем порядке, bolt на [-60,-60])."""
    steps = [
        t.WAIT, t._click(t.BOLT), BTN_DOWN, t.SETTLE, t._snap("down"),
        t._toggle(f"preset{kind}1", checked), t.SETTLE,
        CTRL_Z, t.SETTLE, t._snap("undo"),
        t._key("ArrowRight", shift=True), *t.QUIET, t._key("Delete"), t.SETTLE, t._snap("end"),
        t.SAVE, t.SETTLE,
    ]  # fmt: skip
    stand, out = t._go(start_pult, steps)
    assert t._names(out, "down") == ["plate", "bolt", "cap"], "precondition: «Ниже» переставила bolt на строку 1"
    assert t._names(out, "undo") == ["plate", "cap", "bolt"], "precondition: Ctrl+Z откатил «Ниже»"
    assert t._sel(out, "undo") == [], f"слой с флагом ({kind}) вернулся в выбор после «Отмены»: {t._sel(out, 'undo')}"
    rows = out["snaps"]["end"]["rows"]
    assert rows == ["plate", "cap", "bolt"], f"Delete тронул слой с флагом: {rows}"
    commits = stand.commits()
    assert len(commits) == 1, f"ожидался один commit: {commits!r}"
    got = [(ly["name"], ly["offset_px"]) for ly in commits[0]["preset"]["layers"]]
    assert got == [("plate", [0, 0]), ("cap", [20, 0]), ("bolt", [-60, -60])], f"стрелка сдвинула слой с флагом: {got}"


def _stand_with_sprite_list(start_pult):
    stand = t._stand(start_pult)
    tmpl = {"name": "", "mode": "static", "offset_px": [0, 0], "angle_deg": 0.0, "scale": 1.0}
    stand.layers.handlers["preset.sprites"] = lambda a: {
        "status": "ok", "dir": "sprites", "truncated": False,
        "files": [{"path": "sprites/cap.png", "sprite_source": "sprites/cap.png"}], "layer_template": tmpl,
    }  # fmt: skip
    return stand


def test_readded_layer_does_not_inherit_flag_of_deleted_namesake(start_pult) -> None:
    """1б: добавили cap_2 (строка 3), сняли presetVis3, Ctrl+Z (слой исчез), добавили снова - имя то же cap_2.
    Флаг прежнего cap_2 не наследуется: новый слой нарисован (красный cap на (90,100)), presetVis3 отмечен,
    выбран cap_2."""
    stand = _stand_with_sprite_list(start_pult)
    point = (90, 100)  # внутри cap_2 (80..120) и plate (70..130): красный, если cap_2 виден, иначе синий plate
    steps = [
        t.WAIT, t.SETTLE,
        {"op": "select_option", "id": "presetSpriteSelect", "value": "sprites/cap.png"},
        {"op": "press_button", "id": "btnLayerAdd"}, t.SETTLE, t._snap("added"), t._px("added", point),
        t._toggle("presetVis3", False), t.SETTLE, t._px("hidden", point),
        CTRL_Z, t.SETTLE, t._snap("undone"),
        {"op": "press_button", "id": "btnLayerAdd"}, t.SETTLE, t._snap("readded"), t._px("readded", point),
        t._ui("u", ["presetVis3"]),
    ]  # fmt: skip
    assert _NODE is not None, "node недоступен в PATH"
    out = _run(stand.port, "canvas_script", steps)
    assert out["aborted"] is None and all(w["ok"] for w in out["waits"]), f"сценарий прерван: {out['aborted']}"
    assert t._names(out, "added") == ["plate", "cap", "bolt", "cap_2"], "precondition: слой добавлен"
    assert out["pixels"]["added"] == t.RED and out["pixels"]["hidden"] == t.BLUE, "precondition: флаг скрывает cap_2"
    assert t._names(out, "undone") == ["plate", "cap", "bolt"], "precondition: Ctrl+Z убрал cap_2"
    assert t._names(out, "readded") == ["plate", "cap", "bolt", "cap_2"], "precondition: слой добавлен снова"
    px = out["pixels"]["readded"]
    assert px == t.RED, f"новый cap_2 родился скрытым (унаследовал флаг): {px}"
    assert out["ui"]["u"]["checked"]["presetVis3"] is True, "чекбокс «видим» нового слоя должен быть отмечен"
    assert t._sel(out, "readded") == ["cap_2"], f"новый слой выбран: {t._sel(out, 'readded')}"


def test_rename_then_undo_keeps_flag_on_the_layers_own_name(start_pult) -> None:
    """2а: скрыли cap, переименовали cap -> cap2 (флаг переехал на cap2), Ctrl+Z (имя снова cap).
    Флаг должен переехать обратно: cap скрыт (серый base на (135,100)), presetVis1 снят."""
    steps = [
        t.WAIT, t._toggle("presetVis1", False), t.SETTLE, t._px("hidden", t.CAP_ONLY),
        *_rename(1, "cap2"), t.SETTLE, t._px("renamed", t.CAP_ONLY),
        CTRL_Z, t.SETTLE, t._sleep(150), t._snap("undone"), t._px("undone", t.CAP_ONLY),
        t._ui("u", ["presetVis1"]),
    ]  # fmt: skip
    _stand_, out = t._go(start_pult, steps)
    assert out["pixels"]["hidden"] == t.GRAY and out["pixels"]["renamed"] == t.GRAY, (
        f"precondition: скрытый cap остаётся скрытым и под именем cap2: {out['pixels']}"
    )
    assert t._names(out, "undone") == ["plate", "cap", "bolt"], "precondition: Ctrl+Z вернул имя"
    px = out["pixels"]["undone"]
    assert px == t.GRAY, f"после «Отмены» cap снова виден (флаг остался на cap2): {px}"
    assert out["ui"]["u"]["checked"]["presetVis1"] is False, "чекбокс «видим» строки cap должен остаться снятым"


def test_no_ghost_flag_sticks_to_layer_renamed_into_old_name(start_pult) -> None:
    """2б: после цепочки «скрыть cap, переименовать в cap2, Ctrl+Z» флага на несуществующем cap2 быть не должно:
    bolt, переименованный в cap2, остаётся видимым (красный спрайт cap2 на (-60,-60) -> объект (40,40)),
    presetVis2 отмечен."""
    steps = [
        t.WAIT, t._toggle("presetVis1", False), t.SETTLE,
        *_rename(1, "cap2"), t.SETTLE,
        CTRL_Z, t.SETTLE, t._sleep(150),
        *_rename(2, "cap2"), t.SETTLE, t._sleep(150), t._px("bolt", t.BOLT), t._snap("end"),
        t._ui("u", ["presetVis2"]),
    ]  # fmt: skip
    _stand_, out = t._go(start_pult, steps)
    assert t._names(out, "end") == ["plate", "cap", "bolt"], "precondition: Ctrl+Z вернул имена"
    assert out["ui"]["u"]["checked"]["presetVis2"] is True, "чекбокс «видим» строки 2 отмечен (флага этой строки нет)"
    assert out["pixels"]["bolt"] == t.RED, (
        f"слой, получивший имя cap2, исчез с канвы (призрачный флаг), пиксель: {out['pixels']['bolt']}"
    )
