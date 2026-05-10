"""Тесты Tasks 2.1-2.5: wiring editor/bridge, CRUD, apply, cross-tab, subscribe.

Тесты без Qt — чистый pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.frontend.app_context import FrontendAppContext
from multiprocess_prototype.frontend.bridges.topology_bridge import TopologyBridge
from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_DISPLAYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd_handler():
    """Мок command_handler."""
    cmd = MagicMock()
    cmd.send.return_value = True
    return cmd


def _make_registers_manager():
    """Мок registers_manager."""
    rm = MagicMock()
    rm.set_field_value.return_value = (True, None)
    return rm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий SystemTopologyEditor."""
    return SystemTopologyEditor()


@pytest.fixture
def bridge_with_mocks(editor):
    """TopologyBridge с моками cmd и rm."""
    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm)
    return bridge, editor, cmd, rm


# ---------------------------------------------------------------------------
# 1. FrontendAppContext wiring (Task 2.1)
# ---------------------------------------------------------------------------


class TestFrontendAppContextWiring:
    """Task 2.1: поля topology_editor и topology_bridge в FrontendAppContext."""

    def test_context_creates_without_error(self):
        """FrontendAppContext создаётся без ошибок с минимальными аргументами."""
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx is not None

    def test_topology_editor_field_exists(self):
        """FrontendAppContext содержит поле topology_editor."""
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert hasattr(ctx, "topology_editor")

    def test_topology_bridge_field_exists(self):
        """FrontendAppContext содержит поле topology_bridge."""
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert hasattr(ctx, "topology_bridge")

    def test_topology_editor_default_none(self):
        """topology_editor по умолчанию None."""
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx.topology_editor is None

    def test_topology_bridge_default_none(self):
        """topology_bridge по умолчанию None."""
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx.topology_bridge is None

    def test_topology_editor_can_be_set(self):
        """topology_editor принимает SystemTopologyEditor."""
        editor = SystemTopologyEditor()
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
            topology_editor=editor,
        )
        assert ctx.topology_editor is editor

    def test_topology_bridge_can_be_set(self):
        """topology_bridge принимает TopologyBridge."""
        editor = SystemTopologyEditor()
        bridge = TopologyBridge(editor)
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
            topology_bridge=bridge,
        )
        assert ctx.topology_bridge is bridge


# ---------------------------------------------------------------------------
# 2. Editor + Bridge интеграция (Tasks 2.2-2.4)
# ---------------------------------------------------------------------------


class TestEditorBridgeIntegration:
    """Tasks 2.2-2.4: интеграция editor и bridge."""

    def test_editor_initially_not_dirty(self, editor):
        """Свежий editor: is_dirty(SECTION_PROCESSES) = False."""
        assert editor.is_dirty(SECTION_PROCESSES) is False

    def test_apply_processes_calls_cmd_send(self, bridge_with_mocks):
        """apply(SECTION_PROCESSES) с новым процессом → cmd.send() вызван."""
        bridge, editor, cmd, rm = bridge_with_mocks
        # Добавляем процесс с воркером (bridge._current = None → всё новое)
        editor._data["processes"]["proc1"] = {
            "name": "proc1",
            "class_path": "pkg.SomeProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
        }
        editor._data["workers"]["proc1_main"] = {
            "process_ref": "proc1",
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }
        result = bridge.apply(SECTION_PROCESSES)
        assert result is True
        assert cmd.send.called

    def test_apply_sources_calls_set_field_value(self, bridge_with_mocks):
        """apply(SECTION_SOURCES) → rm.set_field_value() вызван для 'sources'."""
        bridge, editor, cmd, rm = bridge_with_mocks
        editor._data["cameras"]["camera_0"] = {
            "camera_id": 0,
            "camera_type": "simulator",
            "process_name": "camera_0",
            "execution_mode": "process",
            "region_processing": "dedicated_processor",
            "region_processor_name": "processor_0",
        }
        bridge.apply(SECTION_SOURCES)
        assert rm.set_field_value.called
        # Проверяем что записывается в регистр 'sources'
        reg_names = [c.args[0] for c in rm.set_field_value.call_args_list]
        assert "sources" in reg_names

    def test_add_process_makes_dirty(self, editor):
        """После добавления процесса через processes.add_process() — editor dirty."""
        editor.processes.add_process("my_proc", "pkg.MyClass")
        assert editor.is_dirty(SECTION_PROCESSES) is True

    def test_apply_marks_clean(self, bridge_with_mocks):
        """После apply() секция становится чистой."""
        bridge, editor, cmd, rm = bridge_with_mocks
        # Делаем editor dirty (добавляем данные для прохождения валидации)
        editor._data["processes"]["p1"] = {
            "name": "p1",
            "class_path": "pkg.P1",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
        }
        editor._data["workers"]["p1_main"] = {
            "process_ref": "p1",
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }
        assert editor.is_dirty(SECTION_PROCESSES) is True
        bridge.apply(SECTION_PROCESSES)
        assert editor.is_dirty(SECTION_PROCESSES) is False


# ---------------------------------------------------------------------------
# 3. CRUD через section views
# ---------------------------------------------------------------------------


class TestSectionViewCRUD:
    """CRUD через ProcessesSectionView, SourcesSectionView, DisplaysSectionView."""

    def test_add_process_stores_in_data(self, editor):
        """editor.processes.add_process() → процесс появляется в _data."""
        key = editor.processes.add_process("proc1", "some.Class")
        assert key in editor._data["processes"]
        assert editor._data["processes"][key]["class_path"] == "some.Class"

    def test_remove_process_deletes_from_data(self, editor):
        """editor.processes.remove_process(key) → процесс удалён."""
        key = editor.processes.add_process("proc_to_del", "some.Class")
        assert key in editor._data["processes"]
        editor.processes.remove_process(key)
        assert key not in editor._data["processes"]

    def test_remove_process_cascade_deletes_workers(self, editor):
        """remove_process() удаляет все воркеры процесса."""
        key = editor.processes.add_process("proc_cascade", "some.Class")
        # main worker автоматически создан
        worker_key = f"{key}_main"
        assert worker_key in editor._data["workers"]
        editor.processes.remove_process(key)
        assert worker_key not in editor._data["workers"]

    def test_add_camera_stores_in_data(self, editor):
        """editor.sources.add_camera() → камера появляется в _data."""
        cam_key, reg_key = editor.sources.add_camera("simulator")
        assert cam_key in editor._data["cameras"]
        assert editor._data["cameras"][cam_key]["camera_type"] == "simulator"

    def test_add_camera_creates_main_region(self, editor):
        """add_camera() автоматически создаёт main-регион."""
        cam_key, reg_key = editor.sources.add_camera("simulator")
        assert reg_key in editor._data["regions"]
        region = editor._data["regions"][reg_key]
        assert region["is_main"] is True
        assert region["camera_ref"] == cam_key

    def test_reorder_cameras_changes_sort_order(self, editor):
        """reorder_cameras(key, -1) меняет sort_order камеры."""
        # Добавляем две камеры
        cam0, _ = editor.sources.add_camera("simulator")
        cam1, _ = editor.sources.add_camera("simulator")
        # Проверяем начальный sort_order
        order_cam1_before = editor._data["cameras"][cam1].get("sort_order", 0)
        # Перемещаем cam1 вверх
        editor.sources.reorder_cameras(cam1, -1)
        order_cam1_after = editor._data["cameras"][cam1].get("sort_order", 0)
        assert order_cam1_after != order_cam1_before or order_cam1_before == 0

    def test_add_display_stores_in_data(self, editor):
        """editor.displays.add_display() → display появляется в _data."""
        display_key = editor.displays.add_display("Main Display", "camera_0", fps_limit=30)
        assert display_key in editor._data["displays"]
        display = editor._data["displays"][display_key]
        assert display["name"] == "Main Display"
        assert display["source_ref"] == "camera_0"
        assert display["fps_limit"] == 30


# ---------------------------------------------------------------------------
# 4. Cross-tab queries
# ---------------------------------------------------------------------------


class TestCrossTabQueries:
    """Проверяем cross-tab queries: process_names(), camera_keys()."""

    def test_process_names_contains_added_name(self, editor):
        """После add_process() → process_names() содержит имя процесса."""
        editor.processes.add_process("my_cam_process", "pkg.CamProcess")
        names = editor.process_names()
        assert "my_cam_process" in names

    def test_process_names_empty_initially(self, editor):
        """Свежий editor: process_names() = пустой список."""
        assert editor.process_names() == []

    def test_camera_keys_contains_added_key(self, editor):
        """После add_camera() → camera_keys() содержит ключ."""
        cam_key, _ = editor.sources.add_camera("simulator")
        keys = editor.camera_keys()
        assert cam_key in keys

    def test_camera_keys_empty_initially(self, editor):
        """Свежий editor: camera_keys() = пустой список."""
        assert editor.camera_keys() == []

    def test_process_names_returns_sorted_by_sort_order(self, editor):
        """process_names() возвращает имена в порядке sort_order."""
        editor.processes.add_process("alpha", "pkg.Alpha")
        editor.processes.add_process("beta", "pkg.Beta")
        names = editor.process_names()
        assert names == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# 5. Subscribe / cross-tab notifications
# ---------------------------------------------------------------------------


class TestSubscribeNotifications:
    """Проверяем систему подписок editor."""

    def test_subscribe_processes_callback_called_on_process_change(self, editor):
        """subscribe(SECTION_PROCESSES, cb) → cb вызывается при добавлении процесса."""
        called = []
        editor.subscribe(SECTION_PROCESSES, lambda: called.append(1))
        editor.processes.add_process("notified_proc", "pkg.Class")
        assert len(called) >= 1

    def test_subscribe_sources_not_called_on_process_change(self, editor):
        """subscribe(SECTION_SOURCES, cb) НЕ вызывается при изменении процессов."""
        sources_called = []
        editor.subscribe(SECTION_SOURCES, lambda: sources_called.append(1))
        editor.processes.add_process("proc_other", "pkg.Class")
        assert len(sources_called) == 0

    def test_subscribe_processes_not_called_on_sources_change(self, editor):
        """subscribe(SECTION_PROCESSES, cb) НЕ вызывается при изменении источников."""
        proc_called = []
        editor.subscribe(SECTION_PROCESSES, lambda: proc_called.append(1))
        editor.sources.add_camera("simulator")
        assert len(proc_called) == 0

    def test_subscribe_sources_callback_called_on_camera_add(self, editor):
        """subscribe(SECTION_SOURCES, cb) → cb вызывается при добавлении камеры."""
        called = []
        editor.subscribe(SECTION_SOURCES, lambda: called.append(1))
        editor.sources.add_camera("simulator")
        assert len(called) >= 1

    def test_unsubscribe_stops_notifications(self, editor):
        """После unsubscribe() callback больше не вызывается."""
        called = []
        cb = lambda: called.append(1)
        editor.subscribe(SECTION_PROCESSES, cb)
        editor.processes.add_process("proc_before", "pkg.Class")
        count_before = len(called)

        editor.unsubscribe(SECTION_PROCESSES, cb)
        editor.processes.add_process("proc_after", "pkg.Class")
        # После отписки количество не увеличилось
        assert len(called) == count_before

    def test_subscribe_all_called_on_any_section_change(self, editor):
        """subscribe_all(cb) → cb вызывается при изменении любой секции."""
        global_called = []
        editor.subscribe_all(lambda: global_called.append(1))

        editor.processes.add_process("any_proc", "pkg.Class")
        assert len(global_called) >= 1

        editor.sources.add_camera("simulator")
        assert len(global_called) >= 2

    def test_multiple_subscribers_all_notified(self, editor):
        """Несколько подписчиков одной секции — все получают уведомление."""
        called1 = []
        called2 = []
        editor.subscribe(SECTION_PROCESSES, lambda: called1.append(1))
        editor.subscribe(SECTION_PROCESSES, lambda: called2.append(1))
        editor.processes.add_process("multi_proc", "pkg.Class")
        assert len(called1) >= 1
        assert len(called2) >= 1


# ---------------------------------------------------------------------------
# 6. Validate — FK-валидация
# ---------------------------------------------------------------------------


class TestValidation:
    """FK-валидация через editor.validate()."""

    def test_valid_worker_with_existing_process_ref(self, editor):
        """Воркер с существующим process_ref → validate() без ошибок."""
        editor.processes.add_process("valid_proc", "pkg.Class")
        # add_process создаёт protected main-воркер, который ссылается на valid_proc
        errors = editor.validate()
        # Ошибок, связанных с FK workers→processes, быть не должно
        fk_errors = [e for e in errors if "process_ref" in e]
        assert fk_errors == []

    def test_worker_with_nonexistent_process_ref_fails_validate(self, editor):
        """Воркер с несуществующим process_ref → validate() возвращает ошибку."""
        # Добавляем воркер с неверным process_ref напрямую
        editor._data["workers"]["orphan_worker"] = {
            "process_ref": "nonexistent_process",
            "name": "orphan",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": False,
            "target_interval_ms": 0,
            "sort_order": 0,
        }
        errors = editor.validate()
        assert any("orphan_worker" in e or "nonexistent_process" in e for e in errors)

    def test_validate_processes_requires_name(self, editor):
        """Процесс без имени → validate(SECTION_PROCESSES) возвращает ошибку."""
        editor._data["processes"]["no_name_proc"] = {
            "name": "",
            "class_path": "pkg.Class",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
        }
        errors = editor.validate(SECTION_PROCESSES)
        assert any("no_name_proc" in e for e in errors)

    def test_validate_processes_requires_class_path(self, editor):
        """Процесс без class_path → validate(SECTION_PROCESSES) возвращает ошибку."""
        editor._data["processes"]["no_class_proc"] = {
            "name": "some_proc",
            "class_path": "",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
        }
        errors = editor.validate(SECTION_PROCESSES)
        assert any("no_class_proc" in e for e in errors)

    def test_validate_duplicate_camera_id_fails(self, editor):
        """Две камеры с одинаковым camera_id → validate(SECTION_SOURCES) возвращает ошибку."""
        editor._data["cameras"]["cam_a"] = {
            "camera_id": 0,
            "camera_type": "simulator",
            "process_name": "camera_0",
            "execution_mode": "process",
            "region_processing": "dedicated_processor",
            "region_processor_name": "processor_0",
        }
        editor._data["cameras"]["cam_b"] = {
            "camera_id": 0,  # дубликат!
            "camera_type": "simulator",
            "process_name": "camera_0b",
            "execution_mode": "process",
            "region_processing": "dedicated_processor",
            "region_processor_name": "processor_0b",
        }
        errors = editor.validate(SECTION_SOURCES)
        assert len(errors) > 0
        assert any("camera_id=0" in e for e in errors)

    def test_empty_editor_validates_ok(self, editor):
        """Пустой editor проходит полную валидацию без ошибок."""
        errors = editor.validate()
        assert errors == []
