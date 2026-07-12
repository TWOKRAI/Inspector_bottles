# -*- coding: utf-8 -*-
"""Тесты normalize_recipe_v3_raw — единая сборка v3-raw на запись (one source of truth)."""

from __future__ import annotations

from multiprocess_prototype.recipes.format import normalize_recipe_v3_raw


def test_sets_top_level_blueprint_and_preserves_other_keys():
    raw = {"name": "demo", "version": 3, "description": "d", "active_services": ["s"]}
    bp = {"processes": [{"process_name": "p1"}], "wires": [], "displays": []}

    out = normalize_recipe_v3_raw(raw, bp)

    assert out["blueprint"] == bp
    assert out["name"] == "demo"  # прочие ключи сохранены
    assert out["active_services"] == ["s"]


def test_strips_legacy_data_and_meta():
    raw = {
        "name": "demo",
        "version": 3,
        "blueprint": {"processes": []},
        "data": {"blueprint": {"processes": []}},  # legacy-мусор от старой порчи
        "meta": {"migrated_from_v1": True},
    }
    out = normalize_recipe_v3_raw(raw, {"processes": [], "wires": [], "displays": []})

    assert "data" not in out
    assert "meta" not in out


def test_top_level_gui_positions_never_written():
    # AU-1: top-level gui_positions не попадает в возвращаемый dict (в т.ч. legacy из raw).
    # Про диск-эффект (writer не удаляет отсутствующие ключи) — см. recipe/tests/test_yaml_io.
    raw = {"name": "demo", "gui_positions": {"old": [9.0, 9.0]}}
    bp = {"processes": [], "wires": [], "displays": []}

    out = normalize_recipe_v3_raw(raw, bp)
    assert "gui_positions" not in out


def test_does_not_mutate_input_raw():
    raw = {"name": "demo", "data": {"x": 1}}
    normalize_recipe_v3_raw(raw, {"processes": []})
    assert "data" in raw  # вход не мутирован
