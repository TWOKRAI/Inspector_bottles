# -*- coding: utf-8 -*-
"""Contract-тесты build_recipe_v3_raw — единый сборщик v3-raw на запись (RS-1)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

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

    ``rev`` — отпечаток содержимого (как у настоящего стора): запись без изменений не меняет ``rev``,
    запись с правкой даёт новый. ``calls`` хранит ``(slug, data, expected_rev, layout)`` каждой записи.
    """

    def __init__(self, raw: dict) -> None:
        self._raw = raw
        self.saved: list[tuple[str, dict]] = []
        self.calls: list[tuple[str, dict, str | None, Any]] = []

    @staticmethod
    def _rev_of(doc: dict) -> str:
        return hashlib.sha1(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()[:8]

    def current_rev(self) -> str:
        return self._rev_of(self._raw)

    def read_canonical(self, slug: str) -> tuple[dict, str]:
        return copy.deepcopy(self._raw), self.current_rev()

    def save_raw(self, slug: str, data: dict, *, expected_rev: str | None = None, layout: Any = None) -> str:
        self.saved.append((slug, data))
        self.calls.append((slug, copy.deepcopy(data), expected_rev, copy.deepcopy(layout)))
        self._raw = {**self._raw, **copy.deepcopy(data)}
        return self.current_rev()


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


# ==============================================================================
# Task 1.2: возврат rev, раскладка из одной половины, expected_rev, не-mapping blueprint
# ==============================================================================


def _raw_with_layout() -> dict:
    return {
        "name": "cup",
        "version": 3,
        "blueprint": {
            "processes": [{"process_name": "producer", "plugins": []}],
            "wires": [],
            "metadata": {"gui_positions": {"producer": [1.0, 2.0]}, "locked_nodes": ["x"]},
        },
    }


def _topo_same_as_raw() -> dict:
    return {"processes": [{"process_name": "producer", "plugins": []}], "wires": [], "displays": []}


def test_return_value_is_the_rev_of_the_single_write() -> None:
    """С правкой — возвращён rev после записи (не rev чтения); без правок — прежний rev."""
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    store = _RecordingStore(_raw_with_layout())
    rev_before = store.current_rev()
    edited = {
        "processes": [{"process_name": "producer", "plugins": [], "protected": True}],
        "wires": [],
        "displays": [],
    }

    rev = save_editor_topology_to_recipe(store, "cup", edited)

    assert len(store.calls) == 1
    assert rev != rev_before
    assert rev == store.current_rev()

    unchanged = _RecordingStore(_raw_with_layout())
    rev_same = unchanged.current_rev()

    assert save_editor_topology_to_recipe(unchanged, "cup", _topo_same_as_raw()) == rev_same


def test_only_positions_given_keeps_locked_nodes_of_the_file() -> None:
    """Передана одна половина раскладки: вторая берётся из файла, а не обнуляется."""
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    store = _RecordingStore(_raw_with_layout())

    save_editor_topology_to_recipe(store, "cup", _topo_same_as_raw(), gui_positions={"producer": [5.0, 6.0]})

    assert store.calls[0][3] == ({"producer": [5.0, 6.0]}, ["x"])

    only_locked = _RecordingStore(_raw_with_layout())

    save_editor_topology_to_recipe(only_locked, "cup", _topo_same_as_raw(), locked_nodes=["y"])

    assert only_locked.calls[0][3] == ({"producer": [1.0, 2.0]}, ["y"])


def test_empty_expected_rev_reaches_save_raw_as_given() -> None:
    """``expected_rev=""`` — заданное значение: в ``save_raw`` уходит "", а не rev чтения."""
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    store = _RecordingStore(_raw_with_layout())
    save_editor_topology_to_recipe(store, "cup", _topo_same_as_raw(), expected_rev="")

    assert store.calls[0][2] == ""

    default = _RecordingStore(_raw_with_layout())
    save_editor_topology_to_recipe(default, "cup", _topo_same_as_raw())

    assert default.calls[0][2] == default.current_rev()


class _Engine:
    """Минимальный движок рецептов для настоящего RecipeManager (``recipes_dir`` + активный slug)."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir

    def get_active(self) -> str | None:
        return None

    def set_active(self, name: str) -> bool:
        return True

    def deactivate(self) -> None:
        return None

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.recipes_dir.glob("*.yaml"))

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        return []


def _real_store(recipes_dir: Path) -> Any:
    """Настоящие RecipeManager (с format_hook проекта) + RecipeStoreFromManager над ``recipes_dir``."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    manager = RecipeManager(
        engine=_Engine(recipes_dir), state_proxy=None, logger=None, format_hook=InspectorRecipeFormatHook()
    )
    return RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)


def test_non_mapping_blueprint_in_file_is_a_typed_refusal(tmp_path: Path) -> None:
    """``blueprint: [1]`` / ``hello`` / пустой (null) в файле — RecipeValidationError, байты файла прежние."""
    import pytest

    from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe

    store = _real_store(tmp_path)
    for tail in ("blueprint: [1]\n", "blueprint: hello\n", "blueprint:\n"):
        path = tmp_path / "r1.yaml"
        path.write_bytes(("name: r1\nversion: 3\n" + tail).encode("utf-8"))
        before = path.read_bytes()

        with pytest.raises(RecipeValidationError) as info:
            save_editor_topology_to_recipe(store, "r1", _topo_same_as_raw())

        assert info.value.errors == ["blueprint: ожидался mapping"], tail
        assert path.read_bytes() == before, tail


_SHORT_MARKER = "S3CR3T-7f3a"


def test_validation_error_does_not_echo_short_input_value() -> None:
    """Короткое входное значение, целиком видимое в ``str(ValidationError)``, не попадает в отказ."""
    import pytest
    from pydantic import ValidationError

    from multiprocess_prototype.domain.entities.topology import Topology
    from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe

    bad = {"processes": [{"process_name": "p", "plugins": _SHORT_MARKER}], "wires": [], "displays": []}
    with pytest.raises(ValidationError) as raw_exc:
        Topology.model_validate(bad)
    assert f"input_value='{_SHORT_MARKER}'" in str(raw_exc.value), "маркер не виден в str(exc): тест вакуумный"

    store = _RecordingStore(_raw_with_layout())
    with pytest.raises(RecipeValidationError) as info:
        save_editor_topology_to_recipe(store, "cup", bad)

    assert store.calls == []
    assert info.value.errors, "ошибки пусты"
    for text in [str(info.value), *info.value.errors]:
        assert _SHORT_MARKER not in text
        assert "input_value" not in text


def test_canonical_read_strips_legacy_top_level_gui_positions_no_edit_save_is_byte_identical(tmp_path: Path) -> None:
    """Файл с legacy top-level ``gui_positions`` (хук снимает его в каноне): Save без правок не меняет байты."""
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    path = tmp_path / "r1.yaml"
    original = (
        "name: r1\n"
        "version: 3\n"
        "gui_positions:\n"
        "  producer: [1.0, 2.0]\n"
        "blueprint:\n"
        "  processes:\n"
        "    - process_name: producer\n"
        "      plugins: []\n"
        "  wires: []\n"
        "  displays: []\n"
    ).encode("utf-8")
    path.write_bytes(original)
    store = _real_store(tmp_path)
    assert "gui_positions" not in store.read_canonical("r1")[0], "хук не снял legacy-ключ: тест вакуумный"
    assert "gui_positions" in store.read_raw_with_rev("r1")[0]

    sent: list[dict] = []
    real_save_raw = store.save_raw

    def spy(slug: str, data: dict, **kwargs: Any) -> str:
        sent.append(copy.deepcopy(data))
        return real_save_raw(slug, data, **kwargs)

    store.save_raw = spy  # type: ignore[method-assign]

    save_editor_topology_to_recipe(store, "r1", _topo_same_as_raw())

    assert path.read_bytes() == original
    # Байты одинаковы и при «сыром» чтении: save_raw канонизирует сам. Поэтому основа Save проверяется
    # на шве: в стор уходит канон (без legacy top-level ключа), а не сырой документ файла.
    assert len(sent) == 1 and "gui_positions" not in sent[0]
