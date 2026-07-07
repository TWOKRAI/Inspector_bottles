# -*- coding: utf-8 -*-
"""Юнит-тесты чистой логики селекторов инспектора (F.6) — БЕЗ Qt.

selectors_data вынесен из NodeInspectorPanel: чистые функции над services-
протоколами тестируются на fake-store без QApplication.
"""

from __future__ import annotations

from types import SimpleNamespace

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.selectors_data import (
    DisplayEntry,
    display_entries,
    process_names_from_recipe,
    worker_label,
    workers_for_process,
)


# ------------------------------------------------------------------ #
#  worker_label                                                        #
# ------------------------------------------------------------------ #


def test_worker_label_source():
    assert worker_label("source", "capture", 0, 0) == "source_producer_capture · свой поток (параллельно)"


def test_worker_label_processing_multi_step():
    label = worker_label("processing", "resize", 2, 3)
    assert "pipeline_executor" in label
    assert "шаг 2/3" in label


def test_worker_label_processing_single():
    assert worker_label("processing", "resize", 1, 1) == "pipeline_executor · последовательно"


# ------------------------------------------------------------------ #
#  process_names_from_recipe                                          #
# ------------------------------------------------------------------ #


class _FakeRecipes:
    def __init__(self, active, raw):
        self._active = active
        self._raw = raw

    def get_active(self):
        return self._active

    def read_raw(self, slug):
        return self._raw.get(slug)


def test_process_names_none_store():
    assert process_names_from_recipe(None) == []


def test_process_names_no_active():
    assert process_names_from_recipe(_FakeRecipes(None, {})) == []


def test_process_names_happy_path():
    raw = {"r": {"blueprint": {"processes": [{"process_name": "a"}, {"process_name": "b"}]}}}
    assert process_names_from_recipe(_FakeRecipes("r", raw)) == ["a", "b"]


def test_process_names_blueprint_not_dict():
    raw = {"r": {"blueprint": "oops"}}
    assert process_names_from_recipe(_FakeRecipes("r", raw)) == []


def test_process_names_recipe_not_dict():
    raw = {"r": ["not", "a", "dict"]}
    assert process_names_from_recipe(_FakeRecipes("r", raw)) == []


def test_process_names_objects_instead_of_dicts():
    procs = [SimpleNamespace(process_name="x"), SimpleNamespace(process_name="")]
    raw = {"r": {"blueprint": {"processes": procs}}}
    # Объекты с process_name поддержаны; пустое имя пропущено.
    assert process_names_from_recipe(_FakeRecipes("r", raw)) == ["x"]


def test_process_names_read_raw_raises():
    class _Boom:
        def get_active(self):
            return "r"

        def read_raw(self, slug):
            raise RuntimeError("io")

    assert process_names_from_recipe(_Boom()) == []


# ------------------------------------------------------------------ #
#  display_entries                                                     #
# ------------------------------------------------------------------ #


def test_display_entries_none():
    assert display_entries(None) == []


def test_display_entries_maps_spec_fields():
    specs = [
        SimpleNamespace(display_id="main", display_name="Основной"),
        SimpleNamespace(display_id="dbg", display_name="Отладка"),
    ]
    displays = SimpleNamespace(list_displays=lambda: specs)
    result = display_entries(displays)
    assert result == [DisplayEntry("main", "Основной"), DisplayEntry("dbg", "Отладка")]
    assert result[0].id == "main"
    assert result[0].name == "Основной"


def test_display_entries_raises():
    def _boom():
        raise RuntimeError("io")

    assert display_entries(SimpleNamespace(list_displays=_boom)) == []


# ------------------------------------------------------------------ #
#  workers_for_process                                                 #
# ------------------------------------------------------------------ #


class _FakeTopo:
    def __init__(self, workers_by_proc):
        self._map = workers_by_proc

    def load(self):
        return self

    def find_process(self, name):
        if name not in self._map:
            return None
        workers = [SimpleNamespace(worker_name=w) for w in self._map[name]]
        return SimpleNamespace(workers=workers)


def test_workers_none_topology():
    assert workers_for_process(None, "proc") == ["message_processor"]


def test_workers_empty_process_name():
    assert workers_for_process(_FakeTopo({}), "") == ["message_processor"]


def test_workers_inserts_message_processor():
    workers = workers_for_process(_FakeTopo({"proc": ["grabber", "encoder"]}), "proc")
    assert workers[0] == "message_processor"
    assert workers[1:] == ["grabber", "encoder"]


def test_workers_does_not_duplicate_message_processor():
    workers = workers_for_process(_FakeTopo({"proc": ["message_processor", "grabber"]}), "proc")
    assert workers.count("message_processor") == 1
    assert workers == ["message_processor", "grabber"]


def test_workers_process_not_found():
    assert workers_for_process(_FakeTopo({}), "ghost") == ["message_processor"]
