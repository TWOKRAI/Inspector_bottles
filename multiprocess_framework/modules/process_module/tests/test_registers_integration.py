"""Framework-тесты Task 5.9 — интеграция RegistersManager с plugin system.

Тестируем только framework-уровень (без зависимости от прикладных плагинов):
1. register_schema() — default None, override в плагине
2. PluginContext.registers — передача RegistersManager
3. PluginOrchestrator._init_registers — bootstrap из register_schema()
4. Graceful degradation — плагин без регистра работает на defaults

ColorMask-specific интеграция вынесена в
Plugins/color_mask/tests/test_registers_integration.py
по плану docs/refactors/2026-05_arch_cleanup.md (Task 1.1).
"""

from __future__ import annotations

from typing import Annotated
from unittest.mock import MagicMock

from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


# --- Fixtures ---


class SimplePlugin(ProcessModulePlugin):
    """Плагин без регистра — graceful degradation."""
    name = "simple"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None:
        self._value = ctx.config.get("value", 42)

    def start(self, ctx: PluginContext) -> None:
        pass


class _WithRegisterRegisters(SchemaBase):
    """Register-класс для тестового плагина."""
    threshold: Annotated[int, FieldMeta("Threshold", min=0, max=100)] = 50
    enabled: Annotated[bool, FieldMeta("Enabled")] = True


class PluginWithRegister(ProcessModulePlugin):
    """Плагин с регистром (V3_MY_PURE)."""
    name = "with_register"
    category = "processing"

    @classmethod
    def register_schema(cls) -> list:
        return [_WithRegisterRegisters]

    def configure(self, ctx: PluginContext) -> None:
        self._reg = None
        if ctx.registers is not None:
            self._reg = ctx.registers.get_register(self.name)

    def start(self, ctx: PluginContext) -> None:
        pass


# --- Tests: register_schema() ---


class TestRegisterSchema:
    """register_schema() — classmethod, возвращает list[type[SchemaBase]]."""

    def test_default_returns_empty_list(self):
        """Base class register_schema() returns []."""
        assert SimplePlugin.register_schema() == []

    def test_override_returns_classes(self):
        """Plugin with register returns list of SchemaBase classes."""
        classes = PluginWithRegister.register_schema()
        assert len(classes) == 1
        assert classes[0] is _WithRegisterRegisters

    def test_schema_instantiation(self):
        """Register class can be instantiated with defaults."""
        classes = PluginWithRegister.register_schema()
        instance = classes[0]()
        assert instance.threshold == 50
        assert instance.enabled is True

    def test_schema_field_meta(self):
        """Schema fields have FieldMeta metadata."""
        classes = PluginWithRegister.register_schema()
        instance = classes[0]()
        meta = instance.get_field_meta("threshold")
        assert meta is not None
        assert meta.min == 0
        assert meta.max == 100


# --- Tests: PluginContext.registers ---


class TestPluginContextRegisters:
    """PluginContext с registers полем."""

    def test_registers_default_none(self):
        """registers по умолчанию None."""
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
        )
        assert ctx.registers is None

    def test_registers_passed(self):
        """registers передаётся в конструктор."""
        mock_rm = MagicMock()
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
            registers=mock_rm,
        )
        assert ctx.registers is mock_rm

    def test_with_config_passes_registers(self):
        """with_config() передаёт registers в копию."""
        mock_rm = MagicMock()
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
            registers=mock_rm,
        )
        child = ctx.with_config({"key": "value"}, registers=mock_rm)
        assert child.registers is mock_rm
        assert child.config == {"key": "value"}


# --- Tests: RegistersManager bootstrap ---


class _MockServices:
    """Мок-сервисы для PluginOrchestrator."""
    name = "test"
    worker_manager = None
    command_manager = None
    router_manager = None
    memory_manager = None

    def __init__(self):
        self.log_info = MagicMock()
        self.log_error = MagicMock()
        self.send_message = MagicMock()
        self.receive_message = MagicMock()

    def get_config(self, key, default=None):
        return default


class TestRegistersBootstrap:
    """PluginOrchestrator._init_registers — сбор schemas из плагинов."""

    def test_no_schemas_returns_none(self):
        """Если ни один плагин не вернул schema -> None."""
        from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
            PluginOrchestrator,
        )

        services = _MockServices()
        orch = PluginOrchestrator(services=services)

        plugin = SimplePlugin()
        ctx = MagicMock()
        result = orch._init_registers([(plugin, ctx)])
        assert result is None

    def test_with_schema_creates_manager(self):
        """Плагин с register_schema -> RegistersManager создан."""
        from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
            PluginOrchestrator,
        )

        services = _MockServices()
        orch = PluginOrchestrator(services=services)

        plugin = PluginWithRegister()
        ctx = MagicMock()
        result = orch._init_registers([(plugin, ctx)])
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
            services=MockProcessServices(name="test"),
            config={"value": 99},
            io=MagicMock(),
            registers=None,
        )
        plugin.configure(ctx)
        assert plugin._value == 99
