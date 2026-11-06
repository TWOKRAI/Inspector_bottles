# -*- coding: utf-8 -*-
"""Тесты автора Task 1.14 / 1.14b (C-30): Save не пишет фундамент (процессы ``manifest.base``) — по именам.

Приёмка слепого тестера (A–J) лежит в ``test_save_protected_owner.py``. Здесь то, чего в ней нет:

* аргумент ``topology`` не мутируется; нет ключа ``processes`` / не список — как до правила;
* флаг ``protected`` правило не читает (1.14b): фундамент — только имена из ``foundation``;
* нехешируемый ``process_name`` не даёт ``TypeError`` (F1 ревью 1.14);
* F2: «Сохранить» живого графа в рецепт без ``gui`` проходит и не пишет ``devices``;
* S1/S2: Save живого графа в тот же рецепт без правок — ``+0/−0``, с базой и без.

Часть 1 — дубль стора в памяти (судим по тому, что ушло в ``save_raw``). Часть 2 — настоящая цепочка
``RecipeStoreFromManager`` + ``RecipeManager`` + ``InspectorRecipeFormatHook`` на tmp-копиях рецептов репо.
Рецепты репо берутся только из копий ``fixtures/<slug>_head.yaml`` (сняты ``git show HEAD:`` — рабочее дерево
может быть грязным; subprocess ``git`` в тесте не нужен). Фундамент живого графа — настоящий ``base.yaml``.
Ожидаемое — литералы.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe
from multiprocess_prototype.recipes.tests.test_save_noise_store import _diff, _put, _within, build_chain

_FOUNDATION = frozenset({"devices"})
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_BASE_YAML = Path(__file__).resolve().parents[2] / "backend" / "topology" / "base.yaml"


# ---------------------------------------------------------------------------
# Часть 1: дубль стора в памяти
# ---------------------------------------------------------------------------


class _Store:
    """Дубль RecipeStore: ``read_canonical`` отдаёт копию, ``save_raw`` запоминает записанное."""

    def __init__(self, raw: dict) -> None:
        self._raw = raw
        self.saved: list[dict] = []

    def read_canonical(self, slug: str) -> tuple[dict, str]:
        return copy.deepcopy(self._raw), "rev0"

    def save_raw(self, slug: str, data: dict, *, expected_rev: str | None = None, layout: Any = None) -> str:
        self.saved.append(copy.deepcopy(data))
        return "rev1"


def _raw(devices_flag: bool = False) -> dict:
    """Файл: gui, devices (форма файла), a. Флаг ``protected`` у devices — по параметру."""
    devices: dict = {"process_name": "devices", "plugins": [], "description": "file form"}
    if devices_flag:
        devices["protected"] = True
    return {
        "name": "cup",
        "version": 3,
        "blueprint": {
            "processes": [{"process_name": "gui", "plugins": []}, devices, {"process_name": "a", "plugins": []}],
            "wires": [],
            "displays": [],
        },
    }


def _names(doc: dict) -> list[str]:
    return [p["process_name"] for p in doc["blueprint"]["processes"]]


def _topology(*processes: dict) -> dict:
    return {"processes": list(processes), "wires": [], "displays": []}


def test_topology_argument_is_not_mutated() -> None:
    """Правило возвращает новый dict: переданная редактором топология после Save равна себе до Save."""
    topology = _topology(
        {"process_name": "devices", "plugins": [], "description": "session form"},
        {"process_name": "gui", "plugins": []},
        {"process_name": "a", "plugins": []},
    )
    before = copy.deepcopy(topology)

    save_editor_topology_to_recipe(_Store(_raw()), "cup", topology, foundation=_FOUNDATION)

    assert topology == before


def test_foundation_process_stays_in_file_and_editor_copy_is_not_written() -> None:
    """Фундамент определяется именем: devices без флага в файле остаётся формой файла, сессионный — не пишется."""
    store = _Store(_raw())
    topology = _topology(
        {"process_name": "devices", "plugins": [], "description": "session form"},
        {"process_name": "gui", "plugins": []},
        {"process_name": "a", "plugins": []},
    )

    save_editor_topology_to_recipe(store, "cup", topology, foundation=_FOUNDATION)

    assert _names(store.saved[0]) == ["gui", "devices", "a"]
    assert store.saved[0]["blueprint"]["processes"][1]["description"] == "file form"


def test_file_foundation_process_stays_when_editor_lacks_it() -> None:
    """devices есть в файле (без флага), редактору он неизвестен: остаётся на месте, как в файле."""
    store = _Store(_raw())
    topology = _topology({"process_name": "gui", "plugins": []}, {"process_name": "a", "plugins": []})

    save_editor_topology_to_recipe(store, "cup", topology, foundation=_FOUNDATION)

    assert _names(store.saved[0]) == ["gui", "devices", "a"]


@pytest.mark.parametrize("devices_flag", [False, True])
def test_protected_flag_is_not_read_by_the_rule(devices_flag: bool) -> None:
    """Флаг ``protected`` правило не читает: процесс редактора с флагом, не из foundation, пишется как обычный.

    ``foundation`` непуст: при пустом правило no-op и тест не отличил бы чтение флага от его отсутствия
    (K2 инъекций 1.14b). Файловый ``devices`` — фундамент по имени (с флагом или без), встаёт после ``gui``.
    """
    store = _Store(_raw(devices_flag))
    topology = _topology(
        {"process_name": "gui", "plugins": [], "protected": True},
        {"process_name": "probe", "plugins": [], "protected": True},
        {"process_name": "a", "plugins": []},
    )

    save_editor_topology_to_recipe(store, "cup", topology, foundation=_FOUNDATION)

    assert _names(store.saved[0]) == ["gui", "devices", "probe", "a"]


def test_empty_foundation_leaves_topology_untouched() -> None:
    """Пустой ``foundation`` -> правило no-op: devices редактора пишется (процесса с таким именем в файле нет)."""
    store = _Store(_raw())
    topology = _topology({"process_name": "devices", "plugins": [], "description": "session form"})

    save_editor_topology_to_recipe(store, "cup", topology)

    assert _names(store.saved[0]) == ["devices"]
    assert store.saved[0]["blueprint"]["processes"][0]["description"] == "session form"


def test_topology_without_processes_key_behaves_as_before() -> None:
    """Нет ключа ``processes`` -> правило топологию не трогает; ``Topology`` читает его как пустой, как до 1.14."""
    store = _Store(_raw())

    save_editor_topology_to_recipe(store, "cup", {"wires": [], "displays": []}, foundation=_FOUNDATION)

    assert store.saved[0]["blueprint"]["processes"] == []


@pytest.mark.parametrize("processes", ["x", None])
def test_processes_not_a_list_is_left_to_topology_validation(processes: Any) -> None:
    """``processes`` не список -> правило молчит, ошибку даёт ``Topology``: ``RecipeValidationError``, записи нет."""
    store = _Store(_raw())

    with pytest.raises(RecipeValidationError) as info:
        save_editor_topology_to_recipe(store, "cup", {"processes": processes}, foundation=_FOUNDATION)

    assert "processes" in str(info.value)
    assert store.saved == []


def test_unhashable_editor_process_name_is_a_validation_error_not_type_error() -> None:
    """F1: ``process_name`` процесса редактора — список: нет ``TypeError``, отказ даёт валидация, записи нет."""
    store = _Store(_raw())
    topology = _topology({"process_name": ["a"], "plugins": []}, {"process_name": "gui", "plugins": []})

    with pytest.raises(RecipeValidationError):
        save_editor_topology_to_recipe(store, "cup", topology, foundation=_FOUNDATION)

    assert store.saved == []


def test_unhashable_file_process_name_is_a_validation_error_not_type_error() -> None:
    """F1: ``process_name`` процесса в файле — список: нет ``TypeError``, отказ даёт валидация, записи нет."""
    raw = _raw()
    raw["blueprint"]["processes"].append({"process_name": ["b"], "plugins": []})
    store = _Store(raw)
    topology = _topology({"process_name": "gui", "plugins": []}, {"process_name": "a", "plugins": []})

    with pytest.raises(RecipeValidationError):
        save_editor_topology_to_recipe(store, "cup", topology, foundation=_FOUNDATION)

    assert store.saved == []


# ---------------------------------------------------------------------------
# Часть 2: настоящая цепочка на копиях рецептов репо
# ---------------------------------------------------------------------------


def _recipe_bytes(slug: str) -> bytes:
    """Копия рецепта репо с HEAD (LF)."""
    return (_FIXTURES / f"{slug}_head.yaml").read_bytes().replace(b"\r\n", b"\n")


def _live_topology(slug: str) -> dict:
    """Живой граф GUI: фундамент ``base.yaml`` ⊕ рецепт ``slug`` (``merge_topologies``), как отдаёт редактор."""
    from multiprocess_prototype.backend.launch import merge_topologies, unwrap_recipe
    from multiprocess_prototype.domain.entities import Topology

    base = unwrap_recipe(yaml.safe_load(_BASE_YAML.read_text(encoding="utf-8")))
    recipe = unwrap_recipe(yaml.safe_load(_recipe_bytes(slug).decode("utf-8")))
    return Topology.from_dict(merge_topologies(base, recipe)).to_dict()


def _process_names(raw: bytes) -> list[str]:
    return [p["process_name"] for p in yaml.safe_load(raw.decode("utf-8"))["blueprint"]["processes"]]


def _save_live(store: Any, target: str, live: dict, **kwargs: Any) -> Any:
    return _within(60, save_editor_topology_to_recipe, store, target, live, foundation=_FOUNDATION, **kwargs)


@pytest.mark.parametrize("target", ["dualcam_synth", "g1_perf_probe"])
def test_recipes_save_live_graph_into_recipe_without_gui(tmp_path: Path, target: str) -> None:
    """F2: граф bridge_synth («Сохранить» вкладки Recipes) -> рецепт без ``gui``: ок, ``devices`` в цели нет."""
    _put(tmp_path, "bridge_synth", _recipe_bytes("bridge_synth"))
    path = _put(tmp_path, target, _recipe_bytes(target))
    store = build_chain(tmp_path, "bridge_synth")
    live = _live_topology("bridge_synth")
    assert [p["process_name"] for p in live["processes"]] == ["devices", "synthetic_source", "gui"]

    _save_live(store, target, live, expected_rev=None)

    assert _process_names(path.read_bytes()) == ["synthetic_source", "gui"]
    assert store.read(target) is not None


def test_same_slug_no_edit_is_byte_identical_with_and_without_base_bridge_synth(tmp_path: Path) -> None:
    """S1: bridge_synth в тот же slug без правок: ``+0/−0`` и mtime прежний — с базой и с ``expected_rev=None``."""
    src = _recipe_bytes("bridge_synth")
    path = _put(tmp_path, "bridge_synth", src)
    store = build_chain(tmp_path, "bridge_synth")
    live = _live_topology("bridge_synth")
    rev = store.read_raw_with_rev("bridge_synth")[1]
    mtime_before = path.stat().st_mtime_ns

    _save_live(store, "bridge_synth", live, expected_rev=rev)
    with_base = path.read_bytes()
    _save_live(store, "bridge_synth", live, expected_rev=None)

    assert _diff(src, with_base) == []
    assert _diff(src, path.read_bytes()) == []
    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == mtime_before


def test_same_slug_no_edit_is_byte_identical_with_and_without_base_webcam_sketch(tmp_path: Path) -> None:
    """S2: webcam_sketch (devices авторский) в тот же slug без правок: ``+0/−0`` в обоих режимах, mtime прежний."""
    src = _recipe_bytes("webcam_sketch")
    path = _put(tmp_path, "webcam_sketch", src)
    store = build_chain(tmp_path, "webcam_sketch")
    live = _live_topology("webcam_sketch")
    rev = store.read_raw_with_rev("webcam_sketch")[1]
    mtime_before = path.stat().st_mtime_ns

    _save_live(store, "webcam_sketch", live, expected_rev=rev)
    with_base = path.read_bytes()
    _save_live(store, "webcam_sketch", live, expected_rev=None)

    assert _diff(src, with_base) == []
    assert _diff(src, path.read_bytes()) == []
    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == mtime_before
