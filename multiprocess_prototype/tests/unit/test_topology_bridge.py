"""Unit-тесты TopologyBridge (frontend/bridges/topology_bridge.py).

Проверяем:
- apply("processes") → cmd.send() вызван
- apply("sources") → rm.set_field_value() вызван
- apply("displays") → wm.create_window() вызван
- apply("processes") НЕ трогает registers
- apply("sources") НЕ вызывает cmd.send
- Guard _writing: _on_external_change игнорируется
- Guard dirty editor: _on_external_change не перезаписывает
- apply(None) вызывает все три транспорта
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.frontend.bridges.topology_bridge import TopologyBridge
from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_DISPLAYS,
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


def _make_window_manager():
    """Мок window_manager."""
    wm = MagicMock()
    wm.list_windows.return_value = []
    return wm


def _make_bridge_with_process():
    """Bridge с одним процессом в editor (новый, нет current state → create будет вызван)."""
    editor = SystemTopologyEditor()
    # Добавляем процесс напрямую для полного контроля
    editor._data["processes"]["cam"] = {
        "name": "camera_0",
        "class_path": "pkg.CameraProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
    }
    editor._data["workers"]["cam_main"] = {
        "process_ref": "cam",
        "name": "main",
        "worker_type": "router_poll",
        "enabled": True,
        "protected": True,
        "target_interval_ms": 0,
        "sort_order": 0,
    }
    # Оставляем dirty (не вызываем mark_clean) — это новые данные

    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    wm = _make_window_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)
    return bridge, editor, cmd, rm, wm


# ---------------------------------------------------------------------------
# Тест 1: apply("processes") → cmd.send() вызван
# ---------------------------------------------------------------------------


def test_apply_processes_sends_ipc():
    """apply(SECTION_PROCESSES) с новым процессом → cmd.send вызван с process.create."""
    bridge, editor, cmd, rm, wm = _make_bridge_with_process()
    # current = None → все процессы новые
    result = bridge.apply(SECTION_PROCESSES)
    assert result is True
    # cmd.send должен быть вызван хотя бы раз
    assert cmd.send.called
    # Проверяем что аргументы содержат process.create
    sent_data = [c.kwargs.get("data", {}) or (c.args[1] if len(c.args) > 1 else {})
                 for c in cmd.send.call_args_list]
    # Пробуем оба варианта вызова (positional и keyword)
    all_args = []
    for c in cmd.send.call_args_list:
        if c.args and len(c.args) > 1:
            all_args.append(c.args[1])
        if c.kwargs.get("data"):
            all_args.append(c.kwargs["data"])
    assert any(a.get("cmd") == "process.create" for a in all_args)


# ---------------------------------------------------------------------------
# Тест 2: apply("sources") → rm.set_field_value() вызван
# ---------------------------------------------------------------------------


def test_apply_sources_writes_register():
    """apply(SECTION_SOURCES) → rm.set_field_value вызван для cameras и regions."""
    editor = SystemTopologyEditor()
    editor._data["cameras"]["camera_0"] = {
        "camera_id": 0, "camera_type": "simulator",
        "process_name": "camera_0", "execution_mode": "process",
        "region_processing": "dedicated_processor", "region_processor_name": "processor_0",
    }
    editor._data["regions"]["camera_0_main"] = {
        "camera_ref": "camera_0", "enabled": True, "is_main": True,
        "processing_enabled": True, "sort_order": 0,
    }

    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    wm = _make_window_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)

    bridge.apply(SECTION_SOURCES)
    assert rm.set_field_value.called
    # Проверяем что вызывалось для "sources"
    calls_reg_names = [c.args[0] for c in rm.set_field_value.call_args_list]
    assert "sources" in calls_reg_names


# ---------------------------------------------------------------------------
# Тест 3: apply("displays") → wm.create_window() вызван
# ---------------------------------------------------------------------------


def test_apply_displays_creates_windows():
    """apply(SECTION_DISPLAYS) с новым display → wm.create_window вызван."""
    editor = SystemTopologyEditor()
    editor._data["displays"]["win_0"] = {
        "name": "Main", "source_ref": "camera_0", "fps_limit": 30,
    }

    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    wm = _make_window_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)
    # current = None → все displays новые

    bridge.apply(SECTION_DISPLAYS)
    assert wm.create_window.called


# ---------------------------------------------------------------------------
# Тест 4: apply("processes") НЕ трогает registers
# ---------------------------------------------------------------------------


def test_apply_processes_not_touches_registers():
    """apply(SECTION_PROCESSES) НЕ вызывает rm.set_field_value."""
    bridge, editor, cmd, rm, wm = _make_bridge_with_process()
    bridge.apply(SECTION_PROCESSES)
    assert not rm.set_field_value.called


# ---------------------------------------------------------------------------
# Тест 5: apply("sources") НЕ вызывает cmd.send
# ---------------------------------------------------------------------------


def test_apply_sources_not_touches_ipc():
    """apply(SECTION_SOURCES) НЕ вызывает cmd.send."""
    editor = SystemTopologyEditor()
    editor._data["cameras"]["camera_0"] = {
        "camera_id": 0, "camera_type": "simulator",
        "process_name": "camera_0", "execution_mode": "process",
        "region_processing": "dedicated_processor", "region_processor_name": "processor_0",
    }

    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    wm = _make_window_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)
    bridge.apply(SECTION_SOURCES)
    assert not cmd.send.called


# ---------------------------------------------------------------------------
# Тест 6: guard _writing — _on_external_change игнорируется
# ---------------------------------------------------------------------------


def test_guard_writing():
    """Во время _writing=True, _on_external_change не вызывает load_from_backend."""
    editor = SystemTopologyEditor()
    bridge = TopologyBridge(editor)
    bridge._writing = True
    bridge.load_from_backend = MagicMock()
    bridge._on_external_change("some_value")
    bridge.load_from_backend.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 7: guard dirty editor — _on_external_change не перезаписывает
# ---------------------------------------------------------------------------


def test_guard_dirty():
    """При dirty editor, _on_external_change не вызывает load_from_backend."""
    editor = SystemTopologyEditor()
    # Делаем editor dirty
    editor.update_item("processes", "tmp", {"name": "tmp"})
    assert editor.is_dirty() is True

    bridge = TopologyBridge(editor)
    bridge._writing = False
    bridge.load_from_backend = MagicMock()
    bridge._on_external_change("some_value")
    bridge.load_from_backend.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 8: full apply(None) вызывает все три транспорта
# ---------------------------------------------------------------------------


def test_full_apply_order():
    """apply(None) — вызывает все три транспорта (IPC, Register, Window)."""
    editor = SystemTopologyEditor()
    # Добавляем данные для каждого транспорта
    editor._data["processes"]["proc"] = {
        "name": "proc", "class_path": "pkg.Proc",
        "priority": "normal", "auto_start": True, "sort_order": 0,
    }
    editor._data["workers"]["proc_main"] = {
        "process_ref": "proc", "name": "main",
        "worker_type": "router_poll", "enabled": True,
        "protected": True, "target_interval_ms": 0, "sort_order": 0,
    }
    editor._data["cameras"]["camera_0"] = {
        "camera_id": 0, "camera_type": "simulator",
        "process_name": "camera_0", "execution_mode": "process",
        "region_processing": "dedicated_processor", "region_processor_name": "processor_0",
    }
    editor._data["displays"]["win_0"] = {
        "name": "Main", "source_ref": "camera_0", "fps_limit": 30,
    }

    cmd = _make_cmd_handler()
    rm = _make_registers_manager()
    wm = _make_window_manager()
    bridge = TopologyBridge(editor, command_handler=cmd, registers_manager=rm, window_manager=wm)

    result = bridge.apply(None)
    assert result is True
    # Все три транспорта должны были быть задействованы
    assert cmd.send.called       # IPC для processes
    assert rm.set_field_value.called  # Register для sources
    assert wm.create_window.called    # Window API для displays
