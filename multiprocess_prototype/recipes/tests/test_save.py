# -*- coding: utf-8 -*-
"""Contract-тесты build_recipe_v3_raw — единый сборщик v3-raw на запись (RS-1)."""

from __future__ import annotations

from multiprocess_prototype.recipes.save import build_recipe_v3_raw


def _topo() -> dict:
    return {
        "processes": [{"process_name": "p1", "plugins": []}],
        "wires": [{"source": "p1.a.out", "target": "p2.b.in"}],
        "displays": [{"node_id": "p1.a.out", "display_id": "main"}],
    }


def test_builds_top_level_blueprint_with_displays_inside() -> None:
    """processes/wires/displays собираются в top-level blueprint (displays ВНУТРИ)."""
    raw = {"name": "cup", "version": 3, "blueprint": {"processes": [], "wires": []}}
    out = build_recipe_v3_raw(raw, _topo())
    bp = out["blueprint"]
    assert bp["processes"][0]["process_name"] == "p1"
    assert bp["wires"][0]["source"] == "p1.a.out"
    assert bp["displays"][0]["display_id"] == "main"


def test_preserves_author_name_description() -> None:
    """LP-1: авторские blueprint.name/description сохраняются, не затираются."""
    raw = {
        "version": 3,
        "blueprint": {"name": "Имя", "description": "Опис", "processes": [], "wires": []},
    }
    bp = build_recipe_v3_raw(raw, _topo())["blueprint"]
    assert bp["name"] == "Имя"
    assert bp["description"] == "Опис"


def test_absent_name_description_not_fabricated() -> None:
    """LP-1: если в raw['blueprint'] нет name/description — они НЕ пишутся (не 'default'/'')."""
    raw = {"version": 3, "blueprint": {"processes": [], "wires": []}}
    bp = build_recipe_v3_raw(raw, _topo())["blueprint"]
    assert "name" not in bp
    assert "description" not in bp


def test_gui_positions_override_written_into_metadata() -> None:
    """Override позиций/фиксации (Pipeline-путь) пишется в blueprint.metadata."""
    raw = {"version": 3, "blueprint": {"processes": [], "wires": []}}
    out = build_recipe_v3_raw(raw, _topo(), gui_positions={"p1": [1.0, 2.0]}, locked_nodes=["p1"])
    meta = out["blueprint"]["metadata"]
    assert meta["gui_positions"] == {"p1": [1.0, 2.0]}
    assert meta["locked_nodes"] == ["p1"]


def test_existing_gui_positions_preserved_without_override() -> None:
    """RS-1 (c): без override существующие metadata.gui_positions сохраняются (не стираются)."""
    raw = {
        "version": 3,
        "blueprint": {
            "processes": [],
            "wires": [],
            "metadata": {"gui_positions": {"p1": [7.0, 8.0]}, "locked_nodes": ["p1"]},
        },
    }
    meta = build_recipe_v3_raw(raw, _topo())["blueprint"]["metadata"]
    assert meta["gui_positions"] == {"p1": [7.0, 8.0]}
    assert meta["locked_nodes"] == ["p1"]


def test_no_metadata_when_empty() -> None:
    """Пустой layout и нет override → blueprint.metadata не пишется (без мусора)."""
    raw = {"version": 3, "blueprint": {"processes": [], "wires": []}}
    bp = build_recipe_v3_raw(raw, _topo())["blueprint"]
    assert "metadata" not in bp


def test_strips_legacy_and_top_level_gui_positions() -> None:
    """Делегирование normalize: legacy data/meta и top-level gui_positions в результат не идут."""
    raw = {
        "version": 3,
        "data": {"legacy": True},
        "meta": {"legacy": True},
        "gui_positions": {"p1": [0.0, 0.0]},
        "blueprint": {"processes": [], "wires": []},
    }
    out = build_recipe_v3_raw(raw, _topo())
    assert "data" not in out
    assert "meta" not in out
    assert "gui_positions" not in out  # top-level дубль не воссоздан (AU-1)
    assert out["version"] == 3  # прочие top-level ключи целы


def test_raw_not_mutated() -> None:
    """Pre: raw не мутируется (копируется)."""
    raw = {"version": 3, "blueprint": {"name": "x", "processes": [], "wires": []}}
    original = {"version": 3, "blueprint": {"name": "x", "processes": [], "wires": []}}
    build_recipe_v3_raw(raw, _topo())
    assert raw == original


# ==============================================================================
# Задача 4.3 (Н-13): адрес в никуда не доезжает до диска
# ==============================================================================


class _RecordingStore:
    """Дубль RecipeStore, который ЗАПОМИНАЕТ факт записи.

    Судится наблюдаемое — попал ли рецепт на диск, — а не только тип исключения:
    валидатор, который поднял ошибку ПОСЛЕ ``save_raw``, дал бы тот же тип и то же
    сообщение при уже испорченном файле.
    """

    def __init__(self, raw: dict) -> None:
        self._raw = raw
        self.saved: list[tuple[str, dict]] = []

    def read_raw(self, slug: str) -> dict:
        return self._raw

    def save_raw(self, slug: str, raw: dict) -> None:
        self.saved.append((slug, raw))


def _raw() -> dict:
    return {"name": "cup", "version": 3, "blueprint": {"processes": [], "wires": []}}


def _topo_with_dangling_target() -> dict:
    """Граф, где producer адресует процесс, которого в рецепте нет."""
    return {
        "processes": [
            {"process_name": "producer", "plugins": [], "chain_targets": ["ghost"]},
        ],
        "wires": [],
        "displays": [],
    }


def test_saving_a_dangling_address_is_refused_and_nothing_is_written() -> None:
    """Сохранение рецепта с адресом в никуда — отказ, файл не тронут.

    До 4.3 гейт записи (``check_structure``) знал только про дубли имён и циклы,
    а страж адресуемости стоял на boot-валидации. Правка сохранялась молча, и
    цена приходила позже и в другом месте: отказ доставки на каждый кадр
    (замер плана D8 — 1418 отказов за 30 с) вместо отказа в момент правки.
    """
    import pytest

    from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe

    store = _RecordingStore(_raw())

    with pytest.raises(RecipeValidationError) as exc:
        save_editor_topology_to_recipe(store, "cup", _topo_with_dangling_target())

    assert store.saved == [], "рецепт с висящим адресом попал на диск"
    text = str(exc.value)
    assert "producer" in text and "ghost" in text, f"отказ не назвал адрес: {text}"


def test_a_healthy_graph_still_saves() -> None:
    """Пара к предыдущему: ужесточение не начало отвергать здоровые рецепты.

    Замер перед правкой: все 14 живых рецептов репозитория чисты. Без этой
    половины «отказ» было бы неотличимо от «сохранение сломано вообще».
    """
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    store = _RecordingStore(_raw())
    topo = {
        "processes": [
            {"process_name": "producer", "plugins": [], "chain_targets": ["consumer"]},
            {"process_name": "consumer", "plugins": []},
        ],
        "wires": [],
        "displays": [],
    }

    save_editor_topology_to_recipe(store, "cup", topo)

    assert len(store.saved) == 1
    assert store.saved[0][0] == "cup"
