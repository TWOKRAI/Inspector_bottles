# -*- coding: utf-8 -*-
"""Тесты автора Task 1.14 (C-30): Save владеет только непротектед-процессами — крайние случаи правила.

Приёмка слепого тестера (A–J) лежит в ``test_save_protected_owner.py``. Здесь то, чего в ней нет:
аргумент ``topology`` не мутируется; ``protected`` — по truthy, а не по ``is True`` (``"yes"``/``1``);
топология без ключа ``processes`` ведёт себя как раньше. Старый ``devices`` без флага закрыт слепым J.

Дубль стора — в стиле ``test_save.py``: пишем в память, судим по тому, что ушло в ``save_raw``.
Ожидаемое — литералы.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe


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


def _raw(file_protected: Any = True) -> dict:
    """Файл: gui (protected), devices (форма файла, флаг ``file_protected``), a."""
    return {
        "name": "cup",
        "version": 3,
        "blueprint": {
            "processes": [
                {"process_name": "gui", "plugins": [], "protected": True},
                {"process_name": "devices", "plugins": [], "description": "file form", "protected": file_protected},
                {"process_name": "a", "plugins": []},
            ],
            "wires": [],
            "displays": [],
        },
    }


def _names(doc: dict) -> list[str]:
    return [p["process_name"] for p in doc["blueprint"]["processes"]]


def test_topology_argument_is_not_mutated() -> None:
    """Правило возвращает новый dict: переданная редактором топология после Save равна себе до Save."""
    topology = {
        "processes": [
            {"process_name": "devices", "plugins": [], "description": "session form", "protected": True},
            {"process_name": "gui", "plugins": [], "protected": True},
            {"process_name": "a", "plugins": []},
            {"process_name": "extra_protected", "plugins": [], "protected": True},
        ],
        "wires": [],
        "displays": [],
    }
    before = copy.deepcopy(topology)

    save_editor_topology_to_recipe(_Store(_raw()), "cup", topology)

    assert topology == before


@pytest.mark.parametrize("file_protected", ["yes", 1])
def test_file_process_with_truthy_protected_stays_when_editor_lacks_it(file_protected: Any) -> None:
    """protected файла — по truthy (``"yes"``/``1``), не ``is True``: devices редактору неизвестен, остаётся в файле."""
    store = _Store(_raw(file_protected))
    topology = {
        "processes": [{"process_name": "gui", "plugins": [], "protected": True}, {"process_name": "a", "plugins": []}],
        "wires": [],
        "displays": [],
    }

    save_editor_topology_to_recipe(store, "cup", topology)

    assert _names(store.saved[0]) == ["gui", "devices", "a"]
    assert store.saved[0]["blueprint"]["processes"][1]["description"] == "file form"


@pytest.mark.parametrize("editor_protected", ["yes", 1])
def test_editor_process_with_truthy_protected_absent_in_file_is_not_written(editor_protected: Any) -> None:
    """protected редактора — по truthy: процесс ``probe`` с ``"yes"``/``1``, которого нет в файле, в файл не пишется."""
    store = _Store(_raw())
    topology = {
        "processes": [
            {"process_name": "gui", "plugins": [], "protected": True},
            {"process_name": "probe", "plugins": [], "protected": editor_protected},
            {"process_name": "a", "plugins": []},
        ],
        "wires": [],
        "displays": [],
    }

    save_editor_topology_to_recipe(store, "cup", topology)

    assert _names(store.saved[0]) == ["gui", "devices", "a"]


def test_topology_without_processes_key_behaves_as_before() -> None:
    """Нет ключа ``processes`` -> правило топологию не трогает; ``Topology`` читает его как пустой, как до 1.14."""
    store = _Store(_raw())

    save_editor_topology_to_recipe(store, "cup", {"wires": [], "displays": []})

    assert store.saved[0]["blueprint"]["processes"] == []


@pytest.mark.parametrize("processes", ["x", None])
def test_processes_not_a_list_is_left_to_topology_validation(processes: Any) -> None:
    """``processes`` не список -> правило молчит, ошибку даёт ``Topology``: ``RecipeValidationError``, записи нет."""
    store = _Store(_raw())

    with pytest.raises(RecipeValidationError) as info:
        save_editor_topology_to_recipe(store, "cup", {"processes": processes})

    assert "processes" in str(info.value)
    assert store.saved == []
