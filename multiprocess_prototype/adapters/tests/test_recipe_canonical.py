"""Адаптеры канона рецепта и хук v3 в GUI (Task 1.1g, design.md §10 п. 3, 5, §10.2).

22 рецепта ``multiprocess_prototype/recipes/*.yaml`` — только вход для чтения; запись идёт в копии под ``tmp_path``.
Ожидаемые значения — литералы, не выводятся из проверяемого кода.
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from multiprocess_framework.modules.display_module.registry import DisplayRegistry
from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    ProcessConfig,
    _restore_plugin_configs,
)
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_manager_module.topology.blueprint import Wire as BackendWire
from multiprocess_framework.modules.recipe.hook_contract import assert_format_hook_contract
from multiprocess_framework.modules.recipe.manager import RecipeManager
from multiprocess_prototype.adapters.recipe_canonical import (
    minimize,
    recipe_from_canonical,
    recipe_to_canonical,
    topology_to_canonical,
)
from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook
from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.entities.process import Process
from multiprocess_prototype.domain.entities.wire import Wire
from multiprocess_prototype.domain.entities.worker import WorkerSpec

PROTOTYPE_ROOT = Path(__file__).resolve().parents[2]
RECIPES_DIR = PROTOTYPE_ROOT / "recipes"
SLUGS = sorted(p.stem for p in RECIPES_DIR.glob("*.yaml"))
HOOK_FACTORY = "multiprocess_prototype.backend.recipe_format_hook:InspectorRecipeFormatHook"


# ---------------------------------------------------------------------------------------------------------
# Вход: 22 рецепта только на чтение
# ---------------------------------------------------------------------------------------------------------


def _raw(slug: str) -> dict:
    return yaml.safe_load((RECIPES_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _canonical_cached(slug: str) -> str:
    return json.dumps(InspectorRecipeFormatHook().normalize(_raw(slug)), ensure_ascii=False)


def _canonical(slug: str) -> dict:
    """``N(файл)``: новый dict на каждый вызов (тест вправе мутировать)."""
    return json.loads(_canonical_cached(slug))


def _same(a: Any, b: Any) -> bool:
    """Равенство с различением ``1`` / ``True`` / ``1.0`` и порядком ключей (как у движка дельты)."""
    return json.dumps(a, ensure_ascii=False, default=str) == json.dumps(b, ensure_ascii=False, default=str)


def _leaf_diff(a: Any, b: Any, path: tuple = ()) -> set[tuple]:
    """Пути листьев, чьё значение различается или есть только с одной стороны (лишний элемент списка — весь)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: set[tuple] = set()
        for key in a.keys() | b.keys():
            if key not in a or key not in b:
                out.add(path + (key,))
            else:
                out |= _leaf_diff(a[key], b[key], path + (key,))
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = set()
        for i, (x, y) in enumerate(zip(a, b)):
            out |= _leaf_diff(x, y, path + (i,))
        out |= {path + (i,) for i in range(min(len(a), len(b)), max(len(a), len(b)))}  # вставленный/удалённый элемент
        return out
    return set() if _same(a, b) else {path}


def _with_process_field(recipe: Any, idx: int, field: str, value: Any) -> Any:
    procs = list(recipe.blueprint.processes)
    procs[idx] = procs[idx].model_copy(update={field: value})
    return recipe.model_copy(update={"blueprint": recipe.blueprint.model_copy(update={"processes": tuple(procs)})})


def _with_display_field(recipe: Any, idx: int, field: str, value: Any) -> Any:
    defs = list(recipe.displays)
    defs[idx] = defs[idx].model_copy(update={field: value})
    return recipe.model_copy(update={"displays": tuple(defs)})


# ---------------------------------------------------------------------------------------------------------
# Хук v3: контракт фреймворка
# ---------------------------------------------------------------------------------------------------------


def test_v3_hook_passes_framework_contract_on_all_recipes() -> None:
    docs = [json.loads(json.dumps(_raw(slug), default=str)) for slug in SLUGS]
    assert docs, "в multiprocess_prototype/recipes нет ни одного рецепта"

    assert_format_hook_contract(HOOK_FACTORY, docs)


# ---------------------------------------------------------------------------------------------------------
# Круг: канон -> модель -> канон
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", SLUGS)
def test_recipe_round_trip_on_all_recipes(slug: str) -> None:
    doc = _canonical(slug)
    snapshot = copy.deepcopy(doc)

    out = recipe_to_canonical(recipe_from_canonical(doc), doc)

    assert _same(out, snapshot)
    assert _same(doc, snapshot), "база мутирована адаптером"


@pytest.mark.parametrize("slug", SLUGS)
def test_topology_round_trip_on_all_recipes(slug: str) -> None:
    doc = _canonical(slug)
    snapshot = copy.deepcopy(doc)

    out = topology_to_canonical(doc["blueprint"], doc)

    assert _same(out, snapshot)
    assert _same(doc, snapshot), "база мутирована адаптером"


# ---------------------------------------------------------------------------------------------------------
# Вставка: без умолчаний модели
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", SLUGS)
def test_inserted_process_has_no_model_defaults(slug: str) -> None:
    doc = _canonical(slug)
    recipe = recipe_from_canonical(doc)
    topo = recipe.blueprint.model_copy(
        update={"processes": (*recipe.blueprint.processes, Process(process_name="zz_inserted"))}
    )

    out = recipe_to_canonical(recipe.model_copy(update={"blueprint": topo}), doc)

    assert out["blueprint"]["processes"][-1] == {"process_name": "zz_inserted"}
    assert _same(out["blueprint"]["processes"][:-1], doc["blueprint"]["processes"])
    assert _leaf_diff(doc, out) == {("blueprint", "processes", len(doc["blueprint"]["processes"]))}


@pytest.mark.parametrize("where", ["new_process", "existing_process"])
def test_inserted_plugin_entry_has_no_model_defaults(where: str) -> None:
    """Запись плагина без ``plugin_class: null``, ``category: null``, ``config: {}``; заданное значение остаётся."""
    doc = _canonical("color_inspect")
    recipe = recipe_from_canonical(doc)
    plugin = PluginInstance(plugin_name="zz_plugin", category="processing")
    if where == "new_process":
        proc = Process(process_name="zz_inserted", plugins=(plugin,))
        topo = recipe.blueprint.model_copy(update={"processes": (*recipe.blueprint.processes, proc)})
        edited = recipe.model_copy(update={"blueprint": topo})
    else:
        edited = _with_process_field(recipe, 0, "plugins", (*recipe.blueprint.processes[0].plugins, plugin))

    out = recipe_to_canonical(edited, doc)

    expected = {"plugin_name": "zz_plugin", "category": "processing"}
    if where == "new_process":
        assert out["blueprint"]["processes"][-1] == {"process_name": "zz_inserted", "plugins": [expected]}
    else:
        assert out["blueprint"]["processes"][0]["plugins"][-1] == expected


@pytest.mark.parametrize("slug", SLUGS)
def test_worker_inserted_into_existing_process_is_minimal(slug: str) -> None:
    doc = _canonical(slug)
    recipe = recipe_from_canonical(doc)
    workers = (*recipe.blueprint.processes[0].workers, WorkerSpec(worker_name="zz_w"))

    out = recipe_to_canonical(_with_process_field(recipe, 0, "workers", workers), doc)

    assert out["blueprint"]["processes"][0]["workers"][-1] == {"worker_name": "zz_w"}


@pytest.mark.parametrize("slug", ["color_inspect", "bridge_synth"])
def test_inserted_wire_and_display_definition_have_no_model_defaults(slug: str) -> None:
    doc = _canonical(slug)
    recipe = recipe_from_canonical(doc)
    topo = recipe.blueprint.model_copy(
        update={"wires": (*recipe.blueprint.wires, Wire(source="zz_a.p.out", target="zz_b.q.inp"))}
    )
    edited = recipe.model_copy(
        update={"blueprint": topo, "displays": (*recipe.displays, DisplayDefinition(id="zz_disp"))}
    )

    out = recipe_to_canonical(edited, doc)

    assert out["blueprint"]["wires"][-1] == {"source": "zz_a.p.out", "target": "zz_b.q.inp"}
    assert out["displays"][-1] == {"id": "zz_disp"}


def test_topology_insert_process_is_minimal() -> None:
    doc = _canonical("color_inspect")
    topology = copy.deepcopy(doc["blueprint"])
    topology["processes"].append({"process_name": "zz_inserted"})

    out = topology_to_canonical(topology, doc)

    assert out["blueprint"]["processes"][-1] == {"process_name": "zz_inserted"}
    assert _leaf_diff(doc, out) == {("blueprint", "processes", len(doc["blueprint"]["processes"]))}


# ---------------------------------------------------------------------------------------------------------
# Правка: на умолчание пишется явно; правка поля меняет только свой путь
# ---------------------------------------------------------------------------------------------------------


def test_edit_to_default_value_is_written_as_leaf() -> None:
    doc = _canonical("color_inspect")
    doc["displays"][0]["scale"] = 150
    doc["blueprint"]["processes"][0]["priority"] = "high"
    recipe = recipe_from_canonical(doc)

    edited = _with_display_field(recipe, 0, "scale", 100)  # умолчание модели
    edited = _with_process_field(edited, 0, "priority", None)  # умолчание модели
    out = recipe_to_canonical(edited, doc)

    assert out["displays"][0]["scale"] == 100
    assert out["blueprint"]["processes"][0]["priority"] is None
    assert _leaf_diff(doc, out) == {("displays", 0, "scale"), ("blueprint", "processes", 0, "priority")}


@pytest.mark.parametrize("slug", SLUGS)
def test_unedited_default_is_not_created_for_missing_key(slug: str) -> None:
    """Ключ-умолчание, которого нет в файле, при неизменной модели не появляется (программа умолчаний не пишет)."""
    doc = _canonical(slug)

    out = recipe_to_canonical(recipe_from_canonical(doc), doc)

    assert _leaf_diff(doc, out) == set()


_EDIT_KINDS = ("recipe_description", "process_priority", "process_description", "display_scale", "display_name")


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    slug=st.sampled_from(SLUGS),
    kind=st.sampled_from(_EDIT_KINDS),
    pick=st.integers(min_value=0, max_value=50),
    text=st.text(min_size=1, max_size=20),
    priority=st.sampled_from(["high", "low", "realtime", "normal"]),
    scale=st.integers(min_value=10, max_value=1000),
)
def test_property_model_edit_changes_only_edited_paths(
    slug: str, kind: str, pick: int, text: str, priority: str, scale: int
) -> None:
    doc = _canonical(slug)
    recipe = recipe_from_canonical(doc)
    procs, defs = recipe.blueprint.processes, recipe.displays
    i = 0
    if kind.startswith("process"):
        i = pick % len(procs)
    elif kind.startswith("display"):
        assume(len(defs) > 0)
        i = pick % len(defs)

    if kind == "recipe_description":
        assume(text != recipe.meta.description)
        meta = recipe.meta.model_copy(update={"description": text})
        edited, expected = recipe.model_copy(update={"meta": meta}), ("description",)
    elif kind == "process_priority":
        assume(priority != procs[i].priority)
        edited = _with_process_field(recipe, i, "priority", priority)
        expected = ("blueprint", "processes", i, "priority")
    elif kind == "process_description":
        assume(text != procs[i].description)
        edited = _with_process_field(recipe, i, "description", text)
        expected = ("blueprint", "processes", i, "description")
    elif kind == "display_scale":
        assume(scale != defs[i].scale)
        edited, expected = _with_display_field(recipe, i, "scale", scale), ("displays", i, "scale")
    else:
        assume(text != defs[i].name)
        edited, expected = _with_display_field(recipe, i, "name", text), ("displays", i, "name")

    out = recipe_to_canonical(edited, doc)

    assert _leaf_diff(doc, out) == {expected}


# ---------------------------------------------------------------------------------------------------------
# Один класс хука в GUI и в хабе
# ---------------------------------------------------------------------------------------------------------


def _kwarg_class(source: Path, callee: str, kwarg: str) -> list[type | None]:
    """Классы, переданные ``kwarg=Class()`` во всех вызовах ``callee(...)`` файла (``None`` — kwarg не передан)."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{node.module}:{alias.name}"
    found: list[type | None] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == callee):
            continue
        value = next((kw.value for kw in node.keywords if kw.arg == kwarg), None)
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in imports):
            found.append(None)
            continue
        module, name = imports[value.func.id].split(":")
        found.append(getattr(importlib.import_module(module), name))
    return found


def test_gui_and_hub_use_same_hook_class() -> None:
    gui = _kwarg_class(PROTOTYPE_ROOT / "frontend" / "app.py", "RecipeManager", "format_hook")
    hub = _kwarg_class(PROTOTYPE_ROOT / "orchestrator.py", "RecipeService", "hook")

    assert gui == [InspectorRecipeFormatHook]
    assert hub == [InspectorRecipeFormatHook]


# ---------------------------------------------------------------------------------------------------------
# minimize: файл читает backend-модель (В-П2)
# ---------------------------------------------------------------------------------------------------------


def _full_entities(kind: str) -> list[tuple[str, tuple, dict]]:
    """``(slug, путь в канонической форме, полная форма сущности)`` по всем рецептам."""
    out: list[tuple[str, tuple, dict]] = []
    for slug in SLUGS:
        recipe = recipe_from_canonical(_canonical(slug))
        if kind == "process":
            items = [(("blueprint", "processes", i), p) for i, p in enumerate(recipe.blueprint.processes)]
        elif kind == "wire":
            items = [(("blueprint", "wires", i), w) for i, w in enumerate(recipe.blueprint.wires)]
        else:
            items = [(("displays", i), d) for i, d in enumerate(recipe.displays)]
        out.extend((slug, path, entity.model_dump(mode="json")) for path, entity in items)
    return out


def _backend_load(kind: str, entity: dict) -> Any:
    """Что backend строит из записи: процесс — поля ``ProcessConfig``, ``as_generic_config``, восстановленные конфиги
    плагинов (``_restore_plugin_configs``) и плоский конфиг каждого плагина; провод — ``Wire``; дисплей — реестр."""
    if kind == "process":
        cfg = ProcessConfig.model_validate(entity)
        fields = cfg.model_dump()
        generic = cfg.as_generic_config().model_dump()
        # сырые dict плагинов сравниваются поведением ниже, не набором ключей
        fields.pop("plugins"), generic.pop("plugins")
        # пустой ``config`` у восстановленного конфига — инертный extra (поля плагина плоские, ``config`` читает только
        # ``_extract_plugin_config`` ниже); поведение конфига — его поля и ``memory``
        restored = [
            ({k: v for k, v in c.model_dump().items() if not (k == "config" and v == {})}, c.memory)
            for c in _restore_plugin_configs(cfg.plugins)
        ]
        flat = [PluginOrchestrator._extract_plugin_config(p) for p in cfg.plugins]
        names = [(p.get("plugin_class") or "", p.get("plugin_name", "unknown")) for p in cfg.plugins]
        return fields, generic, restored, flat, names
    if kind == "wire":
        return BackendWire.model_validate(entity)
    registry = DisplayRegistry()
    registry.reload([entity])
    return registry.list()


@pytest.mark.parametrize("kind", ["process", "wire", "display"])
def test_minimized_and_full_load_equal_in_backend_model(kind: str, clean_display_registry: None) -> None:
    samples = _full_entities(kind)
    assert samples, f"в 22 рецептах нет сущностей вида {kind}"

    for slug, path, full in samples:
        minimized = minimize(path, copy.deepcopy(full))
        assert _backend_load(kind, minimized) == _backend_load(kind, full), f"{slug} {path}: {minimized} vs {full}"


def test_minimized_process_keeps_extras_over_typed_default() -> None:
    """Минимальная форма не затеняет ``extras.chain_targets`` явным пустым typed-полем (``_pick``)."""
    proc = Process(process_name="p", extras={"chain_targets": ["a"]})

    minimized = minimize(("blueprint", "processes", 0), proc.model_dump(mode="json"))

    assert ProcessConfig.model_validate(minimized).as_generic_config().chain_targets == ["a"]


# ---------------------------------------------------------------------------------------------------------
# Конверт snapshot проходит насквозь (В-П3); запись собственного тела — no-op
# ---------------------------------------------------------------------------------------------------------

_ENVELOPES = {
    "empty_data": {
        "meta": {"name": "snap", "created_at": "2026-10-27T00:00:00+00:00", "description": "", "version": 1},
        "data": {},
    },
    "nested_data": {
        "meta": {"name": "snap", "created_at": "2026-10-27T00:00:00+00:00", "description": "d", "version": 1},
        "data": {"cameras": {"0": {"regions": [1, 2]}}, "blueprint": {"processes": []}},
    },
}


@pytest.mark.parametrize("name", sorted(_ENVELOPES))
def test_v3_hook_is_identity_on_snapshot_envelope(name: str) -> None:
    envelope = _ENVELOPES[name]

    out = InspectorRecipeFormatHook().normalize(copy.deepcopy(envelope))

    assert _same(out, envelope)


@pytest.mark.parametrize("slug", SLUGS)
def test_all_recipes_patch_with_own_body_is_noop(slug: str, tmp_path: Path) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    path = recipes_dir / f"{slug}.yaml"
    path.write_bytes((RECIPES_DIR / f"{slug}.yaml").read_bytes())
    before = path.read_bytes()
    manager = RecipeManager(engine=SimpleNamespace(recipes_dir=recipes_dir), format_hook=InspectorRecipeFormatHook())

    doc, rev = manager.read_canonical(slug)
    new_rev = manager.patch_recipe(slug, doc, expected_rev=rev)

    assert new_rev == rev
    assert path.read_bytes() == before
