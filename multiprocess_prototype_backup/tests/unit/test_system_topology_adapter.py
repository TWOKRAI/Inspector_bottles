"""Unit-тесты topology_adapter.py (Task 3.3 — Phase 3).

Проверяем:
- system_diff_fn: has_changes=False при пустом desired, True при добавлении камеры/процесса
- system_diff_fn: нет изменений при совпадающих current и desired
- system_diff_fn: has_changes=True при добавлении воркера
- system_commands_fn: process.create при добавлении процесса
- system_commands_fn: process.stop ПЕРЕД process.create при замене процесса
- system_commands_fn: camera lifecycle команды при добавлении камеры
- system_commands_fn: пустой список при has_changes=False
- configure_topology_manager: вызывает topology_manager.configure() с нужными аргументами
- Roundtrip: editor → to_dict() → system_diff_fn → system_commands_fn → не падает
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

# Корень проекта в sys.path (Inspector_bottles/) для полных импортов
_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.registers.system_topology.topology_adapter import (
    configure_topology_manager,
    system_commands_fn,
    system_diff_fn,
)
from multiprocess_prototype.registers.system_topology.schemas import SystemTopology


# ---------------------------------------------------------------------------
# Вспомогательные фабрики (Dict at Boundary)
# ---------------------------------------------------------------------------


def _make_process(name: str, class_path: str = "pkg.module.Proc") -> dict:
    """Создать dict-описание процесса для SystemTopology."""
    return {
        "name": name,
        "class_path": class_path,
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }


def _make_worker(
    process_ref: str,
    name: str = "main",
    protected: bool = True,
    interval: int = 0,
) -> dict:
    """Создать dict-описание воркера для SystemTopology."""
    return {
        "process_ref": process_ref,
        "name": name,
        "worker_type": "router_poll",
        "enabled": True,
        "protected": protected,
        "target_interval_ms": interval,
        "sort_order": 0,
    }


def _make_camera(camera_id: int) -> dict:
    """Создать минимальный dict CameraSourceConfig для тестов."""
    return {
        "camera_id": camera_id,
        "camera_type": "simulator",
        "process_name": f"camera_{camera_id}",
        "execution_mode": "process",
        "region_processing": "dedicated_processor",
        "region_processor_name": f"processor_{camera_id}",
    }


def _make_region(camera_ref: str) -> dict:
    """Создать минимальный dict RegionSourceConfig."""
    return {
        "camera_ref": camera_ref,
        "enabled": True,
        "is_main": True,
        "processing_enabled": True,
        "sort_order": 0,
    }


def _empty_topology() -> dict:
    """Пустая SystemTopology dict (все секции пусты)."""
    return {
        "processes": {},
        "workers": {},
        "cameras": {},
        "regions": {},
        "pipeline": {},
        "displays": {},
    }


# ---------------------------------------------------------------------------
# system_diff_fn — базовые случаи
# ---------------------------------------------------------------------------


class TestSystemDiffFnEmpty:
    """system_diff_fn: пустой desired → has_changes=False."""

    def test_none_current_empty_desired_no_changes(self):
        """current=None + пустой desired → has_changes=False."""
        result = system_diff_fn(None, _empty_topology())
        assert result["has_changes"] is False

    def test_empty_current_empty_desired_no_changes(self):
        """Оба пустые → has_changes=False."""
        empty = _empty_topology()
        result = system_diff_fn(empty, empty)
        assert result["has_changes"] is False

    def test_result_contains_all_sections(self):
        """Результат всегда содержит source_diff, process_diff, display_diff."""
        result = system_diff_fn(None, _empty_topology())
        assert "source_diff" in result
        assert "process_diff" in result
        assert "display_diff" in result


class TestSystemDiffFnWithCamera:
    """system_diff_fn: добавление камеры."""

    def test_add_camera_has_changes_true(self):
        """Добавление камеры → has_changes=True."""
        desired = _empty_topology()
        desired["cameras"]["camera_0"] = _make_camera(0)
        desired["regions"]["camera_0_main"] = _make_region("camera_0")

        result = system_diff_fn(None, desired)

        assert result["has_changes"] is True

    def test_add_camera_source_diff_contains_camera(self):
        """Добавление камеры → source_diff.to_create содержит camera_0."""
        desired = _empty_topology()
        desired["cameras"]["camera_0"] = _make_camera(0)

        result = system_diff_fn(None, desired)
        source_diff = result["source_diff"]

        assert "camera_0" in source_diff.to_create


class TestSystemDiffFnWithProcess:
    """system_diff_fn: добавление процесса."""

    def test_add_process_has_changes_true(self):
        """Добавление процесса → has_changes=True."""
        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")

        result = system_diff_fn(None, desired)

        assert result["has_changes"] is True

    def test_add_process_process_diff_contains_key(self):
        """Добавление процесса → process_diff.processes_added содержит ключ."""
        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")

        result = system_diff_fn(None, desired)
        process_diff = result["process_diff"]

        assert "cam" in process_diff["processes_added"]
        assert process_diff["has_changes"] is True

    def test_same_desired_no_changes(self):
        """current == desired → has_changes=False."""
        state = _empty_topology()
        state["processes"]["cam"] = _make_process("camera_0")
        state["workers"]["cam_main"] = _make_worker("cam")

        result = system_diff_fn(state, state)

        assert result["has_changes"] is False
        assert result["process_diff"]["has_changes"] is False


class TestSystemDiffFnWithWorker:
    """system_diff_fn: добавление/изменение воркера."""

    def test_add_worker_has_changes_true(self):
        """Добавление воркера → has_changes=True."""
        current = _empty_topology()
        current["processes"]["cam"] = _make_process("camera_0")

        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")
        desired["workers"]["cam_extra"] = _make_worker("cam", name="extra", protected=False)

        result = system_diff_fn(current, desired)

        assert result["has_changes"] is True
        assert "cam_extra" in result["process_diff"]["workers_added"]

    def test_modify_worker_interval_has_changes_true(self):
        """Изменение target_interval_ms → has_changes=True."""
        current = _empty_topology()
        current["processes"]["cam"] = _make_process("camera_0")
        current["workers"]["cam_main"] = _make_worker("cam", interval=0)

        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")
        desired["workers"]["cam_main"] = _make_worker("cam", interval=100)

        result = system_diff_fn(current, desired)

        assert result["has_changes"] is True
        assert "cam_main" in result["process_diff"]["workers_modified"]


# ---------------------------------------------------------------------------
# system_commands_fn — генерация команд
# ---------------------------------------------------------------------------


class TestSystemCommandsFnEmpty:
    """system_commands_fn: нет изменений → пустой список."""

    def test_no_changes_returns_empty_list(self):
        """has_changes=False → пустой список команд."""
        diff = {
            "has_changes": False,
            "source_diff": MagicMock(has_changes=False),
            "process_diff": {"has_changes": False},
            "display_diff": {"has_changes": False},
        }
        commands = system_commands_fn(diff, _empty_topology())
        assert commands == []

    def test_returns_list_type(self):
        """Результат всегда list."""
        diff = {"has_changes": False}
        result = system_commands_fn(diff, _empty_topology())
        assert isinstance(result, list)


class TestSystemCommandsFnAddProcess:
    """system_commands_fn: добавление процесса → process.create."""

    def test_add_process_generates_create_command(self):
        """Новый процесс → команда process.create в списке."""
        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")

        diff = system_diff_fn(None, desired)
        commands = system_commands_fn(diff, desired)

        cmd_types = [c["cmd"] for c in commands]
        assert "process.create" in cmd_types

    def test_create_command_has_process_name(self):
        """process.create содержит process_name."""
        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0", class_path="pkg.Cam")

        diff = system_diff_fn(None, desired)
        commands = system_commands_fn(diff, desired)

        create_cmds = [c for c in commands if c["cmd"] == "process.create"]
        assert len(create_cmds) == 1
        assert create_cmds[0]["process_name"] == "camera_0"


class TestSystemCommandsFnOrderStopBeforeCreate:
    """system_commands_fn: stop перед create (порядок критичен)."""

    def test_stop_before_create_on_replacement(self):
        """При замене процесса: process.stop идёт раньше process.create."""
        current = _empty_topology()
        current["processes"]["old"] = _make_process("old_proc")

        desired = _empty_topology()
        desired["processes"]["new"] = _make_process("new_proc")

        diff = system_diff_fn(current, desired)
        commands = system_commands_fn(diff, desired)

        cmd_types = [c["cmd"] for c in commands]
        assert "process.stop" in cmd_types
        assert "process.create" in cmd_types

        stop_idx = cmd_types.index("process.stop")
        create_idx = cmd_types.index("process.create")
        assert stop_idx < create_idx, (
            f"process.stop должен быть раньше process.create: "
            f"stop_idx={stop_idx}, create_idx={create_idx}"
        )

    def test_stop_command_has_correct_process_name(self):
        """process.stop содержит правильное имя процесса."""
        current = _empty_topology()
        current["processes"]["old"] = _make_process("old_proc")

        desired = _empty_topology()
        desired["processes"]["new"] = _make_process("new_proc")

        diff = system_diff_fn(current, desired)
        commands = system_commands_fn(diff, desired)

        stop_cmds = [c for c in commands if c["cmd"] == "process.stop"]
        assert len(stop_cmds) == 1
        # process_name = ключ old (используется как fallback в _build_process_commands)
        assert stop_cmds[0]["process_name"] == "old"


class TestSystemCommandsFnCamera:
    """system_commands_fn: camera lifecycle команды."""

    def test_add_camera_generates_camera_commands(self):
        """Добавление камеры → camera-related команды в списке (process.create для камеры)."""
        desired = _empty_topology()
        desired["cameras"]["camera_0"] = _make_camera(0)

        diff = system_diff_fn(None, desired)
        commands = system_commands_fn(diff, desired)

        # diff_to_commands генерирует process.create для новой камеры
        cmd_types = [c["cmd"] for c in commands]
        assert len(commands) > 0, "При добавлении камеры должны быть команды"
        # Хотя бы одна команда связана с камерой (process.create или register_update)
        assert any(ct in ("process.create", "register_update") for ct in cmd_types)

    def test_no_camera_change_no_camera_commands(self):
        """Без изменений в cameras → нет camera-lifecycle команд."""
        state = _empty_topology()
        state["cameras"]["camera_0"] = _make_camera(0)

        diff = system_diff_fn(state, state)
        commands = system_commands_fn(diff, state)

        assert commands == [], "Без изменений команд быть не должно"


class TestSystemCommandsFnWorkers:
    """system_commands_fn: worker команды."""

    def test_add_non_protected_worker_generates_create(self):
        """Добавление не-protected воркера → worker.create."""
        current = _empty_topology()
        current["processes"]["cam"] = _make_process("camera_0")

        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")
        desired["workers"]["cam_extra"] = _make_worker(
            "cam", name="extra_worker", protected=False, interval=50
        )

        diff = system_diff_fn(current, desired)
        commands = system_commands_fn(diff, desired)

        worker_creates = [c for c in commands if c["cmd"] == "worker.create"]
        assert len(worker_creates) == 1
        assert worker_creates[0]["worker_name"] == "extra_worker"

    def test_add_protected_worker_skipped(self):
        """Protected воркер не генерирует worker.create (управляется с процессом)."""
        current = _empty_topology()
        current["processes"]["cam"] = _make_process("camera_0")

        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")
        desired["workers"]["cam_main"] = _make_worker(
            "cam", name="main_worker", protected=True
        )

        diff = system_diff_fn(current, desired)
        commands = system_commands_fn(diff, desired)

        worker_creates = [c for c in commands if c["cmd"] == "worker.create"]
        assert worker_creates == [], "Protected воркер не должен генерировать worker.create"

    def test_modify_worker_interval_generates_set_interval(self):
        """Изменение target_interval_ms → worker.set_interval."""
        current = _empty_topology()
        current["processes"]["cam"] = _make_process("camera_0")
        current["workers"]["cam_main"] = _make_worker("cam", name="main", interval=0)

        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")
        desired["workers"]["cam_main"] = _make_worker("cam", name="main", interval=100)

        diff = system_diff_fn(current, desired)
        commands = system_commands_fn(diff, desired)

        set_interval_cmds = [c for c in commands if c["cmd"] == "worker.set_interval"]
        assert len(set_interval_cmds) == 1
        assert set_interval_cmds[0]["target_interval_ms"] == 100


# ---------------------------------------------------------------------------
# configure_topology_manager
# ---------------------------------------------------------------------------


class TestConfigureTopologyManager:
    """configure_topology_manager: вызывает topology_manager.configure() корректно."""

    def test_calls_configure_with_diff_fn_and_commands_fn(self):
        """configure_topology_manager вызывает topology_manager.configure() с нужными аргументами."""
        mock_tm = MagicMock()
        configure_topology_manager(mock_tm)

        mock_tm.configure.assert_called_once()
        _, kwargs = mock_tm.configure.call_args
        assert kwargs["diff_fn"] is system_diff_fn
        assert kwargs["commands_fn"] is system_commands_fn

    def test_does_not_modify_topology_state(self):
        """configure_topology_manager не вызывает apply/get/diff на topology_manager."""
        mock_tm = MagicMock()
        configure_topology_manager(mock_tm)

        mock_tm.apply.assert_not_called()
        mock_tm.get.assert_not_called()
        mock_tm.diff.assert_not_called()


# ---------------------------------------------------------------------------
# Roundtrip: editor → to_dict() → diff → commands
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """Полный roundtrip: SystemTopology → to_dict() → system_diff_fn → system_commands_fn."""

    def test_roundtrip_empty_topology_no_crash(self):
        """Пустая SystemTopology roundtrip не падает."""
        topology = SystemTopology()
        data = topology.model_dump()

        diff = system_diff_fn(None, data)
        commands = system_commands_fn(diff, data)

        assert isinstance(diff, dict)
        assert isinstance(commands, list)
        assert diff["has_changes"] is False
        assert commands == []

    def test_roundtrip_with_process_no_crash(self):
        """SystemTopology с процессом roundtrip не падает."""
        topology = SystemTopology()
        topology.processes["cam"] = _process_definition("camera_0")

        data = topology.model_dump()
        diff = system_diff_fn(None, data)
        commands = system_commands_fn(diff, data)

        assert isinstance(commands, list)
        assert diff["has_changes"] is True

    def test_roundtrip_with_camera_no_crash(self):
        """SystemTopology с камерой roundtrip не падает."""
        topology = SystemTopology()
        data = topology.model_dump()
        # Добавляем камеру вручную через dict (Dict at Boundary)
        data["cameras"]["camera_0"] = _make_camera(0)

        diff = system_diff_fn(None, data)
        commands = system_commands_fn(diff, data)

        assert isinstance(commands, list)
        assert diff["has_changes"] is True

    def test_roundtrip_idempotent_after_apply(self):
        """После применения topology — повторный diff не даёт изменений."""
        desired = _empty_topology()
        desired["processes"]["cam"] = _make_process("camera_0")

        # Первый apply: есть изменения
        diff1 = system_diff_fn(None, desired)
        assert diff1["has_changes"] is True

        # Второй apply с тем же desired как current: нет изменений
        diff2 = system_diff_fn(desired, desired)
        assert diff2["has_changes"] is False

    def test_roundtrip_all_sections_combined(self):
        """Roundtrip с заполненными процессами, камерами — не падает."""
        desired = {
            "processes": {"cam": _make_process("camera_0")},
            "workers": {"cam_main": _make_worker("cam")},
            "cameras": {"camera_0": _make_camera(0)},
            "regions": {"camera_0_main": _make_region("camera_0")},
            "pipeline": {},
            "displays": {},
        }

        diff = system_diff_fn(None, desired)
        commands = system_commands_fn(diff, desired)

        assert isinstance(diff, dict)
        assert isinstance(commands, list)
        # Должны быть хотя бы команды для процесса и камеры
        assert diff["has_changes"] is True
        assert len(commands) > 0


# ---------------------------------------------------------------------------
# Вспомогательные функции для Roundtrip-тестов
# ---------------------------------------------------------------------------


def _process_definition(name: str):
    """Создать ProcessDefinition объект для SystemTopology."""
    from multiprocess_prototype.registers.system_topology.schemas import ProcessDefinition

    return ProcessDefinition(
        name=name,
        class_path="pkg.module.CamProcess",
        priority="normal",
    )
