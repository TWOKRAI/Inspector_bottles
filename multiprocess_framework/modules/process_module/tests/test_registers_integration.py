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

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.data_schema_module import SchemaBase
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


# --- Tests: контракт register_update (Ф1.6 verify-probe опирается на ack) ---


class TestRegisterUpdateHandler:
    """_on_register_update: канон data {register, field, value}, честный результат.

    Результат уезжает инициатору транспортным авто-reply (reply_to_request — no-op
    без request_id, GUI-путь остаётся fire-and-forget). Регресс: driver слал
    plugin_name — обработчик молча выходил, запись была no-op.
    """

    def _orchestrator_with_register(self):
        from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
            PluginOrchestrator,
        )

        services = _MockServices()
        orch = PluginOrchestrator(services=services)
        plugin = PluginWithRegister()
        orch._registers_manager = orch._init_registers([(plugin, MagicMock())])
        assert orch._registers_manager is not None
        return orch

    def test_success_returns_ack(self):
        orch = self._orchestrator_with_register()
        res = orch._on_register_update({"data": {"register": "with_register", "field": "threshold", "value": 70}})
        assert res == {"success": True, "register": "with_register", "field": "threshold", "value": 70}
        assert orch._registers_manager.get_register("with_register").threshold == 70

    def test_missing_canonical_keys_fail_loud(self):
        """Неверные ключи payload (исторический plugin_name) → error, не молчание."""
        orch = self._orchestrator_with_register()
        res = orch._on_register_update({"data": {"plugin_name": "with_register", "field": "threshold", "value": 70}})
        assert res["success"] is False
        assert "data.register" in res["error"]
        assert "plugin_name" in res["data_keys"]
        # значение не изменилось
        assert orch._registers_manager.get_register("with_register").threshold == 50

    def test_unknown_register_reports_error(self):
        orch = self._orchestrator_with_register()
        res = orch._on_register_update({"data": {"register": "no_such", "field": "threshold", "value": 70}})
        assert res["success"] is False
        assert res["register"] == "no_such"

    def test_no_registers_manager_reports_error(self):
        from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
            PluginOrchestrator,
        )

        orch = PluginOrchestrator(services=_MockServices())
        res = orch._on_register_update({"data": {"register": "x", "field": "y", "value": 1}})
        assert res["success"] is False
        assert "RegistersManager" in res["error"]


# --- Tests: Н-7 multi-register naming (задача 4.1) ---


class _RegA(SchemaBase):
    REGISTER_NAME = "reg_a"
    a: Annotated[int, FieldMeta("A", min=0, max=10)] = 1


class _RegB(SchemaBase):
    REGISTER_NAME = "reg_b"
    b: Annotated[int, FieldMeta("B", min=0, max=10)] = 2


class _RegNoName1(SchemaBase):
    x: Annotated[int, FieldMeta("X", min=0, max=10)] = 1


class _RegNoName2(SchemaBase):
    y: Annotated[int, FieldMeta("Y", min=0, max=10)] = 2


class _MultiNamed(ProcessModulePlugin):
    """Экземпляр с ДВУМЯ регистрами, у каждого свой register_name."""

    name = "multi_named"
    category = "processing"

    @classmethod
    def register_schema(cls) -> list:
        return [_RegA, _RegB]

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        pass


class _MultiUnnamed(ProcessModulePlugin):
    """Два регистра БЕЗ register_name → оба падают на plugin.name → коллизия."""

    name = "multi_unnamed"
    category = "processing"

    @classmethod
    def register_schema(cls) -> list:
        return [_RegNoName1, _RegNoName2]

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        pass


def _orch():
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
        PluginOrchestrator,
    )

    return PluginOrchestrator(services=_MockServices())


class TestMultiRegisterNamingH7:
    """Н-7: несколько регистров одного экземпляра + дубликаты plugin_name (4.1)."""

    def test_multi_register_both_alive(self):
        """Два регистра с distinct register_name — ОБА живы (был overwrite R6)."""
        orch = _orch()
        rm = orch._init_registers([(_MultiNamed(), MagicMock())])
        assert rm is not None
        assert rm.get_register("reg_a") is not None
        assert rm.get_register("reg_b") is not None
        assert rm.get_register("reg_a").a == 1
        assert rm.get_register("reg_b").b == 2

    def test_single_register_keeps_plugin_name(self):
        """Один регистр без register_name — конвенция register_name == plugin_name (compat)."""
        orch = _orch()
        rm = orch._init_registers([(PluginWithRegister(), MagicMock())])
        assert rm.get_register("with_register") is not None

    def test_register_name_override_wins(self):
        """Объявленный register_name перекрывает plugin_name даже для одного регистра."""
        orch = _orch()

        class _Named(ProcessModulePlugin):
            name = "plug_x"
            category = "processing"

            @classmethod
            def register_schema(cls) -> list:
                return [_RegA]  # register_name="reg_a"

            def configure(self, ctx):
                pass

            def start(self, ctx):
                pass

        rm = orch._init_registers([(_Named(), MagicMock())])
        assert rm.get_register("reg_a") is not None
        assert rm.get_register("plug_x") is None  # НЕ по plugin_name

    def test_unnamed_multi_collides_loud_first_wins(self):
        """Два регистра без имён коллизят под plugin.name: первый жив, второй пропущен + log_error."""
        orch = _orch()
        rm = orch._init_registers([(_MultiUnnamed(), MagicMock())])
        # Первый (_RegNoName1) жив под plugin.name, второй пропущен (не молча).
        reg = rm.get_register("multi_unnamed")
        assert reg is not None
        assert hasattr(reg, "x")  # это _RegNoName1, не _RegNoName2
        orch._services.log_error.assert_called()  # громкая коллизия (Н-7)

    def test_duplicate_plugin_name_collides_loud(self):
        """Два РАЗНЫХ экземпляра с одинаковым plugin_name — второй регистр коллизит + log_error."""
        orch = _orch()
        p1 = PluginWithRegister()
        p2 = PluginWithRegister()
        p2.name = "with_register"  # тот же plugin_name (дубль в топологии)
        rm = orch._init_registers([(p1, MagicMock()), (p2, MagicMock())])
        assert rm.get_register("with_register") is not None  # первый жив
        orch._services.log_error.assert_called()  # boot dup-check громкий
