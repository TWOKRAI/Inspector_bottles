"""Integration-тесты ColorMask с framework RegistersManager.

Перенесено из multiprocess_framework/modules/process_module/tests/test_registers_integration.py
по плану docs/refactors/2026-05_arch_cleanup.md (Task 1.1) — framework-тесты не должны
импортировать прикладные плагины.

Тестируем:
1. ColorMaskRegisters — schema с FieldMeta (defaults, диапазоны, mutability)
2. ColorMaskPlugin — graceful degradation без RegistersManager
3. ColorMaskPlugin — работа с managed register через RegistersManager
4. ColorMaskPlugin.process() — использование регистра при HSV-маскировании
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.registers_module import RegistersManager

from multiprocess_prototype.plugins.color_mask.plugin import ColorMaskPlugin
from multiprocess_prototype.plugins.color_mask.registers import ColorMaskRegisters


class _DummyProcess:
    """Мок-процесс для PluginContext."""
    name = "test_process"
    worker_manager = MagicMock()
    command_manager = MagicMock()
    router_manager = MagicMock()
    memory_manager = MagicMock()
    _log_info = MagicMock()
    _log_error = MagicMock()
    send_message = MagicMock()
    receive_message = MagicMock()


# --- Tests: ColorMaskRegisters schema ---


class TestColorMaskRegisters:
    """ColorMaskRegisters schema (V3_MY_PURE — живёт в plugins/color_mask/registers.py)."""

    def test_create_with_defaults(self):
        """Schema создаётся с defaults."""
        reg = ColorMaskRegisters()
        assert reg.h_min == 0
        assert reg.h_max == 179
        assert reg.s_min == 50
        assert reg.s_max == 255
        assert reg.v_min == 50
        assert reg.v_max == 255

    def test_field_meta_present(self):
        """Все 6 HSV-полей имеют FieldMeta."""
        reg = ColorMaskRegisters()
        for field_name in ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max"]:
            meta = reg.get_field_meta(field_name)
            assert meta is not None, f"FieldMeta отсутствует для {field_name}"

    def test_hue_range(self):
        """Hue поля: min=0, max=179."""
        reg = ColorMaskRegisters()
        meta_h = reg.get_field_meta("h_min")
        assert meta_h.min == 0
        assert meta_h.max == 179

    def test_mutable(self):
        """Значения можно менять."""
        reg = ColorMaskRegisters()
        reg.h_min = 30
        assert reg.h_min == 30


# --- Tests: ColorMaskPlugin × RegistersManager integration ---


class TestColorMaskPluginIntegration:
    """Интеграция ColorMaskPlugin с RegistersManager (managed/unmanaged)."""

    def test_color_mask_without_register(self):
        """ColorMaskPlugin без RegistersManager — локальный register с YAML overrides."""
        plugin = ColorMaskPlugin()
        ctx = PluginContext(
            process_name="test",
            config={"h_min": 10, "h_max": 90},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=None,
        )
        plugin.configure(ctx)
        # V3_MY_PURE: _reg всегда существует (локальный ColorMaskRegisters)
        assert plugin._reg is not None
        assert plugin._reg.h_min == 10
        assert plugin._reg.h_max == 90

    def test_color_mask_with_register(self):
        """ColorMaskPlugin с managed регистром — читает пороги из него."""
        reg_instance = ColorMaskRegisters(h_min=20, h_max=100)
        rm = RegistersManager(registers={"color_mask": reg_instance})

        plugin = ColorMaskPlugin()
        ctx = PluginContext(
            process_name="test",
            config={},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=rm,
        )
        plugin.configure(ctx)
        assert plugin._reg is not None
        assert plugin._reg.h_min == 20
        assert plugin._reg.h_max == 100

    def test_color_mask_process_with_register(self):
        """ColorMaskPlugin.process() использует регистр для HSV-маски."""
        reg_instance = ColorMaskRegisters(h_min=0, h_max=179, s_min=0, s_max=255, v_min=0, v_max=255)
        rm = RegistersManager(registers={"color_mask": reg_instance})

        plugin = ColorMaskPlugin()
        ctx = PluginContext(
            process_name="test",
            config={},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=rm,
        )
        plugin.configure(ctx)

        # Белый кадр 2x2 — HSV [0,0,255], все пороги открыты → маска полная
        white_frame = np.ones((2, 2, 3), dtype=np.uint8) * 255
        items = [{"frame": white_frame, "camera_id": 0}]
        result = plugin.process(items)
        assert len(result) == 1
        assert result[0]["frame"] is not None
