"""Тесты TopologyDiffEngine — вычисление diff между topology dict.

Pure Python, без Qt и внешних зависимостей.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.bridge.diff_engine import (
    TopologyDiff,
    compute_diff,
)


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def make_process(name: str, **kwargs) -> dict:
    """Создать минимальный dict процесса."""
    return {"process_name": name, "plugins": [], **kwargs}


def make_wire(source: str, target: str, **kwargs) -> dict:
    """Создать минимальный dict wire."""
    return {"source": source, "target": target, **kwargs}


# ---------------------------------------------------------------------------
# Базовые случаи
# ---------------------------------------------------------------------------


class TestBasicCases:

    def test_empty_diff(self) -> None:
        """Оба topology пустые → has_changes=False."""
        diff = compute_diff({}, {})
        assert diff.has_changes is False
        assert diff.processes == []
        assert diff.wires == []

    def test_identical_topologies(self) -> None:
        """Одинаковые topology → has_changes=False."""
        topology = {
            "processes": [make_process("camera_0"), make_process("proc_0")],
            "wires": [make_wire("camera_0", "proc_0")],
        }
        diff = compute_diff(topology, topology)
        assert diff.has_changes is False


# ---------------------------------------------------------------------------
# Diff процессов
# ---------------------------------------------------------------------------


class TestProcessDiff:

    def test_process_added(self) -> None:
        """Новый процесс в new → ProcessDiff kind=added."""
        old = {"processes": [make_process("camera_0")]}
        new = {"processes": [make_process("camera_0"), make_process("proc_0")]}

        diff = compute_diff(old, new)

        assert len(diff.added_processes) == 1
        added = diff.added_processes[0]
        assert added.process_name == "proc_0"
        assert added.kind == "added"
        assert added.old_config is None
        assert added.new_config is not None

    def test_process_removed(self) -> None:
        """Процесс удалён из new → ProcessDiff kind=removed."""
        old = {"processes": [make_process("camera_0"), make_process("proc_0")]}
        new = {"processes": [make_process("camera_0")]}

        diff = compute_diff(old, new)

        assert len(diff.removed_processes) == 1
        removed = diff.removed_processes[0]
        assert removed.process_name == "proc_0"
        assert removed.kind == "removed"
        assert removed.new_config is None
        assert removed.old_config is not None

    def test_process_modified(self) -> None:
        """Config процесса изменён → changed_fields содержит изменённые ключи."""
        old_proc = {"process_name": "camera_0", "plugins": [], "workers": 2}
        new_proc = {"process_name": "camera_0", "plugins": [], "workers": 4}

        diff = compute_diff(
            {"processes": [old_proc]},
            {"processes": [new_proc]},
        )

        assert len(diff.modified_processes) == 1
        mod = diff.modified_processes[0]
        assert mod.process_name == "camera_0"
        assert mod.kind == "modified"
        assert "workers" in mod.changed_fields
        assert mod.old_config == old_proc
        assert mod.new_config == new_proc

    def test_process_mixed(self) -> None:
        """added + removed + modified одновременно."""
        old = {
            "processes": [
                make_process("to_remove"),
                {"process_name": "to_modify", "plugins": [], "x": 1},
            ]
        }
        new = {
            "processes": [
                make_process("to_add"),
                {"process_name": "to_modify", "plugins": [], "x": 2},
            ]
        }

        diff = compute_diff(old, new)

        assert len(diff.added_processes) == 1
        assert diff.added_processes[0].process_name == "to_add"

        assert len(diff.removed_processes) == 1
        assert diff.removed_processes[0].process_name == "to_remove"

        assert len(diff.modified_processes) == 1
        assert diff.modified_processes[0].process_name == "to_modify"
        assert "x" in diff.modified_processes[0].changed_fields


# ---------------------------------------------------------------------------
# Diff wire
# ---------------------------------------------------------------------------


class TestWireDiff:

    def test_wire_added(self) -> None:
        """Новый wire → WireDiff kind=added."""
        old = {"wires": []}
        new = {"wires": [make_wire("camera_0", "proc_0")]}

        diff = compute_diff(old, new)

        assert len(diff.added_wires) == 1
        added = diff.added_wires[0]
        assert added.wire_key == "camera_0|proc_0"
        assert added.kind == "added"
        assert added.old_config is None
        assert added.new_config is not None

    def test_wire_removed(self) -> None:
        """Wire удалён → WireDiff kind=removed."""
        old = {"wires": [make_wire("camera_0", "proc_0")]}
        new = {"wires": []}

        diff = compute_diff(old, new)

        assert len(diff.removed_wires) == 1
        removed = diff.removed_wires[0]
        assert removed.wire_key == "camera_0|proc_0"
        assert removed.kind == "removed"
        assert removed.new_config is None

    def test_wire_modified(self) -> None:
        """Wire с другим transport → WireDiff kind=modified."""
        old = {"wires": [{"source": "a", "target": "b", "transport": "shm"}]}
        new = {"wires": [{"source": "a", "target": "b", "transport": "queue"}]}

        diff = compute_diff(old, new)

        assert len(diff.wires) == 1
        mod = diff.wires[0]
        assert mod.wire_key == "a|b"
        assert mod.kind == "modified"
        assert mod.old_config["transport"] == "shm"
        assert mod.new_config["transport"] == "queue"


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------


class TestSummary:

    def test_empty_summary(self) -> None:
        """Пустой diff → 'Нет изменений'."""
        diff = compute_diff({}, {})
        assert diff.summary() == "Нет изменений"

    def test_summary_format(self) -> None:
        """summary() содержит правильные символы и части."""
        old = {
            "processes": [
                make_process("remove_me"),
                {"process_name": "modify_me", "x": 1},
            ],
            "wires": [],
        }
        new = {
            "processes": [
                make_process("add_me_1"),
                make_process("add_me_2"),
                {"process_name": "modify_me", "x": 2},
            ],
            "wires": [make_wire("a", "b")],
        }

        diff = compute_diff(old, new)
        s = diff.summary()

        # Проверяем наличие всех частей
        assert "+2 процессов" in s
        assert "-1 процессов" in s
        assert "~1 процессов" in s
        assert "+1 wire'ов" in s

    def test_summary_only_added(self) -> None:
        """Только добавленные → только '+N процессов'."""
        diff = compute_diff({}, {"processes": [make_process("p")]})
        assert diff.summary() == "+1 процессов"


# ---------------------------------------------------------------------------
# Convenience properties
# ---------------------------------------------------------------------------


class TestConvenienceProperties:

    def test_added_processes_property(self) -> None:
        """added_processes возвращает только added."""
        old = {"processes": []}
        new = {"processes": [make_process("p1"), make_process("p2")]}
        diff = compute_diff(old, new)
        assert len(diff.added_processes) == 2
        assert all(p.kind == "added" for p in diff.added_processes)

    def test_removed_processes_property(self) -> None:
        """removed_processes возвращает только removed."""
        old = {"processes": [make_process("p1"), make_process("p2")]}
        new = {"processes": []}
        diff = compute_diff(old, new)
        assert len(diff.removed_processes) == 2
        assert all(p.kind == "removed" for p in diff.removed_processes)

    def test_modified_processes_property(self) -> None:
        """modified_processes возвращает только modified."""
        old = {"processes": [{"process_name": "p", "v": 1}]}
        new = {"processes": [{"process_name": "p", "v": 2}]}
        diff = compute_diff(old, new)
        assert len(diff.modified_processes) == 1
        assert diff.modified_processes[0].kind == "modified"

    def test_added_wires_property(self) -> None:
        """added_wires возвращает только added wire."""
        diff = compute_diff({}, {"wires": [make_wire("x", "y")]})
        assert len(diff.added_wires) == 1
        assert diff.added_wires[0].kind == "added"

    def test_removed_wires_property(self) -> None:
        """removed_wires возвращает только removed wire."""
        diff = compute_diff({"wires": [make_wire("x", "y")]}, {})
        assert len(diff.removed_wires) == 1
        assert diff.removed_wires[0].kind == "removed"


# ---------------------------------------------------------------------------
# Edge cases: отсутствующие секции
# ---------------------------------------------------------------------------


class TestMissingSections:

    def test_missing_processes_in_both(self) -> None:
        """Нет 'processes' ни в old ни в new → пустой diff."""
        diff = compute_diff({"wires": []}, {"wires": []})
        assert diff.processes == []
        assert diff.has_changes is False

    def test_missing_wires_in_both(self) -> None:
        """Нет 'wires' ни в old ни в new → пустой diff wire."""
        diff = compute_diff({"processes": []}, {"processes": []})
        assert diff.wires == []

    def test_missing_processes_in_old(self) -> None:
        """'processes' только в new → все считаются added."""
        diff = compute_diff({}, {"processes": [make_process("p")]})
        assert len(diff.added_processes) == 1

    def test_missing_wires_in_new(self) -> None:
        """'wires' только в old → все считаются removed."""
        diff = compute_diff({"wires": [make_wire("a", "b")]}, {})
        assert len(diff.removed_wires) == 1

    def test_none_processes_value(self) -> None:
        """'processes': None → обрабатывается как пустой список."""
        diff = compute_diff({"processes": None}, {"processes": None})
        assert diff.has_changes is False
