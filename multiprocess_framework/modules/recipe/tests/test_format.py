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


def test_top_level_gui_positions_never_written() -> None:
    # AU-1: top-level gui_positions больше не пишется — позиции живут только
    # в blueprint.metadata (их кладёт вызывающий).
    raw = {"name": "cup"}
    bp = {"processes": [], "metadata": {"gui_positions": {"n1": [1.0, 2.0]}}}
    out = normalize_recipe_v3_raw(raw, bp)
    assert "gui_positions" not in out
    # канонические позиции внутри blueprint.metadata не тронуты
    assert out["blueprint"]["metadata"]["gui_positions"] == {"n1": [1.0, 2.0]}


def test_legacy_top_level_gui_positions_absent_from_result() -> None:
    # AU-1: legacy top-level дубль из raw НЕ попадает в возвращаемый dict (pure-функция).
    # Это НЕ значит удаление ключа с диска — реальный writer (update_yaml_preserving)
    # отсутствующие ключи не трёт, см. test_yaml_io. Гарантия — «Save не создаёт дубль».
    raw = {"name": "cup", "gui_positions": {"n1": [9.0, 9.0]}}
    out = normalize_recipe_v3_raw(raw, {"processes": []})
    assert "gui_positions" not in out


def test_does_not_mutate_input() -> None:
    raw = {"name": "cup", "data": {"x": 1}}
    normalize_recipe_v3_raw(raw, {"processes": []})
    # исходный raw не тронут
    assert raw == {"name": "cup", "data": {"x": 1}}
