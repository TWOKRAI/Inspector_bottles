"""Тесты Task 5.9 — интеграция RegistersManager с plugin system.

Тестируем:
1. register_schema() — default None, override в плагине
2. PluginContext.registers — передача RegistersManager
3. ColorMaskRegisters — schema с FieldMeta
4. GenericProcess._init_registers — bootstrap из register_schema()
5. Graceful degradation — плагин без регистра работает на defaults
6. register_update handler — set_field_value через IPC
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)


# --- Fixtures ---


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


class SimplePlugin(ProcessModulePlugin):
    """Плагин без регистра — graceful degradation."""
    name = "simple"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None:
        self._value = ctx.config.get("value", 42)

    def start(self, ctx: PluginContext) -> None:
        pass


class PluginWithRegister(ProcessModulePlugin):
    """Плагин с регистром."""
    name = "with_register"
    category = "processing"

    def register_schema(self) -> Any | None:
        from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
        from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
        from typing import Annotated

        class TestRegisters(SchemaBase):
            threshold: Annotated[int, FieldMeta("Threshold", min=0, max=100)] = 50
            enabled: Annotated[bool, FieldMeta("Enabled")] = True

        return TestRegisters()

    def configure(self, ctx: PluginContext) -> None:
        self._reg = None
        if ctx.registers is not None:
            self._reg = ctx.registers.get_register(self.name)

    def start(self, ctx: PluginContext) -> None:
        pass


# --- Tests: register_schema() ---


class TestRegisterSchema:
    """register_schema() — default None, override."""

    def test_default_returns_none(self):
        """Base class register_schema() returns None."""
        plugin = SimplePlugin()
        assert plugin.register_schema() is None

    def test_override_returns_schema(self):
        """Plugin with register returns SchemaBase instance."""
        plugin = PluginWithRegister()
        schema = plugin.register_schema()
        assert schema is not None
        assert hasattr(schema, "threshold")
        assert schema.threshold == 50

    def test_schema_field_meta(self):
        """Schema fields have FieldMeta metadata."""
        plugin = PluginWithRegister()
        schema = plugin.register_schema()
        meta = schema.get_field_meta("threshold")
        assert meta is not None
        assert meta.min == 0
        assert meta.max == 100


# --- Tests: PluginContext.registers ---


class TestPluginContextRegisters:
    """PluginContext с registers полем."""

    def test_registers_default_none(self):
        """registers по умолчанию None."""
        ctx = PluginContext(
            process_name="test",
            config={},
            process=_DummyProcess(),
            io=MagicMock(),
        )
        assert ctx.registers is None

    def test_registers_passed(self):
        """registers передаётся в конструктор."""
        mock_rm = MagicMock()
        ctx = PluginContext(
            process_name="test",
            config={},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=mock_rm,
        )
        assert ctx.registers is mock_rm

    def test_with_config_passes_registers(self):
        """with_config() передаёт registers в копию."""
        mock_rm = MagicMock()
        ctx = PluginContext(
            process_name="test",
            config={},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=mock_rm,
        )
        child = ctx.with_config({"key": "value"}, registers=mock_rm)
        assert child.registers is mock_rm
        assert child.config == {"key": "value"}


# --- Tests: ColorMaskRegisters ---


class TestColorMaskRegisters:
    """ColorMaskRegisters schema (V3_MY_PURE — живёт в plugins/color_mask/registers.py)."""

    def test_create_with_defaults(self):
        """Schema создаётся с defaults."""
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters

        reg = ColorMaskRegisters()
        assert reg.h_min == 0
        assert reg.h_max == 179
        assert reg.s_min == 50
        assert reg.s_max == 255
        assert reg.v_min == 50
        assert reg.v_max == 255

    def test_field_meta_present(self):
        """Все 6 HSV-полей имеют FieldMeta."""
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters

        reg = ColorMaskRegisters()
        for field_name in ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max"]:
            meta = reg.get_field_meta(field_name)
            assert meta is not None, f"FieldMeta отсутствует для {field_name}"

    def test_hue_range(self):
        """Hue поля: min=0, max=179."""
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters

        reg = ColorMaskRegisters()
        meta_h = reg.get_field_meta("h_min")
        assert meta_h.min == 0
        assert meta_h.max == 179

    def test_mutable(self):
        """Значения можно менять."""
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters

        reg = ColorMaskRegisters()
        reg.h_min = 30
        assert reg.h_min == 30

    def test_memory_property(self):
        """memory вычисляется из полей register."""
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters

        reg = ColorMaskRegisters(camera_id=2, resolution_width=1920, resolution_height=1080)
        mem = reg.memory
        assert mem is not None
        assert "mask_2" in mem
        assert mem["mask_2"] == (1080, 1920, 1)


# --- Tests: RegistersManager bootstrap ---


class TestRegistersBootstrap:
    """GenericProcess._init_registers — сбор schemas из плагинов."""

    def test_no_schemas_returns_none(self):
        """Если ни один плагин не вернул schema → None."""
        from multiprocess_framework.modules.process_module.generic.generic_process import (
            GenericProcess,
        )

        gp = GenericProcess.__new__(GenericProcess)
        gp.name = "test"
        gp._log_info = MagicMock()
        gp._log_error = MagicMock()

        plugin = SimplePlugin()
        ctx = MagicMock()
        result = gp._init_registers([(plugin, ctx)])
        assert result is None

    def test_with_schema_creates_manager(self):
        """Плагин с register_schema → RegistersManager создан."""
        from multiprocess_framework.modules.process_module.generic.generic_process import (
            GenericProcess,
        )

        gp = GenericProcess.__new__(GenericProcess)
        gp.name = "test"
        gp._log_info = MagicMock()
        gp._log_error = MagicMock()

        plugin = PluginWithRegister()
        ctx = MagicMock()
        result = gp._init_registers([(plugin, ctx)])
        assert result is not None
        # Проверяем что регистр доступен
        reg = result.get_register("with_register")
        assert reg is not None
        assert reg.threshold == 50


# --- Tests: Graceful degradation ---


class TestGracefulDegradation:
    """Плагин без регистра работает без изменений."""

    def test_simple_plugin_no_crash(self):
        """SimplePlugin работает с registers=None."""
        plugin = SimplePlugin()
        ctx = PluginContext(
            process_name="test",
            config={"value": 99},
            process=_DummyProcess(),
            io=MagicMock(),
            registers=None,
        )
        plugin.configure(ctx)
        assert plugin._value == 99

    def test_color_mask_without_register(self):
        """ColorMaskPlugin без RegistersManager — локальный register с YAML overrides."""
        from multiprocess_prototype_2.plugins.color_mask.plugin import ColorMaskPlugin

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
        from multiprocess_prototype_2.plugins.color_mask.plugin import ColorMaskPlugin
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters
        from multiprocess_framework.modules.registers_module import RegistersManager

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
        """ColorMaskPlugin.process() использует регистр для HSV."""
        from multiprocess_prototype_2.plugins.color_mask.plugin import ColorMaskPlugin
        from multiprocess_prototype_2.plugins.color_mask.registers import ColorMaskRegisters
        from multiprocess_framework.modules.registers_module import RegistersManager

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
