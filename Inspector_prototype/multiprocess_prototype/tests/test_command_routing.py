# multiprocess_prototype/tests/test_command_routing.py
"""Маршрутизация GUI-команд и согласованность с каталогом GuiCommandHandler."""

import pytest

from multiprocess_prototype.registers.gui_command_catalog import GUI_COMMAND_CATALOG
from multiprocess_prototype.registers.command_routing import (
    COMMAND_TO_REGISTER_KEY,
    EXPLICIT_COMMAND_TARGETS,
    list_gui_command_ids,
    resolve_command_targets,
)


def test_resolve_processor_commands():
    assert resolve_command_targets("set_min_area") == ["processor"]
    assert resolve_command_targets("set_max_area") == ["processor"]
    assert resolve_command_targets("set_color_range") == ["processor"]


def test_resolve_renderer_commands():
    assert resolve_command_targets("set_show_original") == ["renderer"]
    assert resolve_command_targets("set_show_mask") == ["renderer"]
    assert resolve_command_targets("set_draw_contours") == ["renderer"]


def test_resolve_camera_commands():
    assert resolve_command_targets("start_capture") == ["camera"]
    assert resolve_command_targets("set_fps") == ["camera"]
    assert resolve_command_targets("set_camera_type") == ["camera"]


def test_resolve_system_shutdown():
    assert resolve_command_targets("system.shutdown") == ["ProcessManager"]


def test_unknown_command_raises():
    with pytest.raises(KeyError):
        resolve_command_targets("nonexistent_command")


def test_catalog_matches_routing():
    """Каждая команда из GUI_COMMAND_CATALOG должна быть в command_routing."""
    known = list_gui_command_ids()
    for cmd_id in GUI_COMMAND_CATALOG:
        assert cmd_id in known, f"Add {cmd_id!r} to COMMAND_TO_REGISTER_KEY"


def test_register_key_coverage():
    """Все зарегистрированные команды (кроме explicit) имеют ключ регистра."""
    for cmd in COMMAND_TO_REGISTER_KEY:
        targets = resolve_command_targets(cmd)
        assert len(targets) >= 1
    for cmd in EXPLICIT_COMMAND_TARGETS:
        targets = resolve_command_targets(cmd)
        assert len(targets) >= 1
