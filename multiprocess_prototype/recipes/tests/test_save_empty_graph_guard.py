# -*- coding: utf-8 -*-
"""Task 1.16 (C-30, D2): Save не пишет пустой граф редактора, если ревизия файла, с которой он строился, неизвестна.

Сбой захвата базы при старте даёт редактору пустой граф и ``expected_rev=None``. Раньше Save тогда стирал
процессы рецепта (кроме фундамента файла). Теперь ``save_editor_topology_to_recipe`` отказывает
``RecipeValidationError`` и не трогает файл. Отказ ставится ДО правила владения: фундамент не «наполняет» пустой граф.

Цепочка настоящая (``RecipeManager`` + ``RecipeStoreFromManager`` + ``InspectorRecipeFormatHook``) на tmp-копиях;
рецепт репо берётся только из ``fixtures/bridge_synth_head.yaml`` (байты ``git show HEAD:`` — рабочий файл может быть
грязным). Ожидаемое — литералы.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype.recipes.save import RecipeValidationError, save_editor_topology_to_recipe
from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SLUG = "bridge_synth"
_FOUNDATION = frozenset({"devices"})
_REFUSAL = "граф редактора пуст, а ревизия файла, с которой он строился, неизвестна: Save отменён, файл не тронут"
_EMPTY_PROCESSES_FILE = (
    "name: empty_file\n"
    "version: 3\n"
    "description: ''\n"
    "blueprint:\n"
    "  name: default\n"
    "  description: ''\n"
    "  processes: []\n"
    "  wires: []\n"
    "  displays: []\n"
    "created_at: ''\n"
    "active_services: []\n"
    "display_bindings: []\n"
).encode("utf-8")


def _head_bytes() -> bytes:
    """Копия ``bridge_synth.yaml`` с HEAD (LF): процессы ``synthetic_source`` и ``gui``."""
    return (_FIXTURES / "bridge_synth_head.yaml").read_bytes().replace(b"\r\n", b"\n")


def _names(raw: bytes) -> list[str]:
    return [p["process_name"] for p in yaml.safe_load(raw.decode("utf-8"))["blueprint"]["processes"]]


def _save(store: Any, topology: dict, **kwargs: Any) -> str:
    return save_editor_topology_to_recipe(store, _SLUG, topology, foundation=_FOUNDATION, **kwargs)


def test_empty_graph_without_base_refuses_file_intact(tmp_path: Path) -> None:
    """Пустой граф, ``expected_rev=None``, в файле 2 процесса -> отказ с текстом, байты и mtime прежние."""
    src = _head_bytes()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    assert _names(src) == ["synthetic_source", "gui"]
    mtime_before = path.stat().st_mtime_ns

    with pytest.raises(RecipeValidationError) as info:
        _save(store, {"processes": [], "wires": []}, expected_rev=None)

    assert info.value.errors == [_REFUSAL]
    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == mtime_before


def test_foundation_only_graph_without_base_refuses(tmp_path: Path) -> None:
    """Граф из одного фундамента (``devices``) тоже пуст: отказ, байты прежние."""
    src = _head_bytes()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)

    with pytest.raises(RecipeValidationError) as info:
        _save(store, {"processes": [{"process_name": "devices"}]}, expected_rev=None)

    assert info.value.errors == [_REFUSAL]
    assert path.read_bytes() == src


def test_empty_graph_with_base_writes_as_before(tmp_path: Path) -> None:
    """База захвачена (``expected_rev`` = rev чтения): пустой граф — осознанная очистка, пишется."""
    path = _put(tmp_path, _SLUG, _head_bytes())
    store = build_chain(tmp_path, _SLUG)
    rev = store.read_raw_with_rev(_SLUG)[1]

    _save(store, {"processes": [], "wires": []}, expected_rev=rev)

    assert yaml.safe_load(path.read_bytes().decode("utf-8"))["blueprint"]["processes"] == []


def test_nonempty_graph_without_base_writes_as_before(tmp_path: Path) -> None:
    """Непустой граф при ``expected_rev=None`` пишется: защита только от пустого графа."""
    path = _put(tmp_path, _SLUG, _head_bytes())
    store = build_chain(tmp_path, _SLUG)
    topology = {
        "processes": [
            {"process_name": "alpha", "plugins": []},
            {"process_name": "beta", "plugins": []},
        ],
        "wires": [],
    }

    _save(store, topology, expected_rev=None)

    assert _names(path.read_bytes()) == ["alpha", "beta"]


def test_empty_graph_over_empty_file_processes_writes_as_before(tmp_path: Path) -> None:
    """В файле процессов нет: пустой граф при ``expected_rev=None`` ничего не стирает, Save проходит."""
    path = _put(tmp_path, _SLUG, _EMPTY_PROCESSES_FILE)
    store = build_chain(tmp_path, _SLUG)

    _save(store, {"processes": [], "wires": []}, expected_rev=None)

    assert yaml.safe_load(path.read_bytes().decode("utf-8"))["blueprint"]["processes"] == []
