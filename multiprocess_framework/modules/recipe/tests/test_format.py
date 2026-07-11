"""Contract-тесты format.normalize_recipe_v3_raw — единая сборка v3-raw на запись."""

from __future__ import annotations

from multiprocess_framework.modules.recipe.format import normalize_recipe_v3_raw


def test_sets_blueprint_and_keeps_top_level() -> None:
    # given raw с прочими top-level ключами
    raw = {"name": "cup", "version": 3, "description": "d"}
    bp = {"processes": [], "wires": [], "displays": []}

    # when нормализуем
    out = normalize_recipe_v3_raw(raw, bp)

    # then blueprint установлен, прочие ключи целы
    assert out["blueprint"] == bp
    assert out["name"] == "cup"
    assert out["version"] == 3
    assert out["description"] == "d"


def test_strips_legacy_envelope() -> None:
    # given raw с остаточным legacy data/meta (от старой порчи)
    raw = {"name": "cup", "data": {"cameras": {}}, "meta": {"version": 1}}

    # when нормализуем
    out = normalize_recipe_v3_raw(raw, {"processes": []})

    # then legacy-envelope удалён
    assert "data" not in out
    assert "meta" not in out


def test_gui_positions_written_only_when_nonempty() -> None:
    raw = {"name": "cup"}
    bp = {"processes": []}
    # пустые/None gui_positions не пишутся
    assert "gui_positions" not in normalize_recipe_v3_raw(raw, bp)
    assert "gui_positions" not in normalize_recipe_v3_raw(raw, bp, {})
    # непустые — пишутся
    out = normalize_recipe_v3_raw(raw, bp, {"n1": [1.0, 2.0]})
    assert out["gui_positions"] == {"n1": [1.0, 2.0]}


def test_does_not_mutate_input() -> None:
    raw = {"name": "cup", "data": {"x": 1}}
    normalize_recipe_v3_raw(raw, {"processes": []})
    # исходный raw не тронут
    assert raw == {"name": "cup", "data": {"x": 1}}
