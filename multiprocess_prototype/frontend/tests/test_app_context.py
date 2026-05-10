"""Тесты для AppContext и build_app_context."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.app_context import AppContext, build_app_context
from multiprocess_prototype.frontend.bridge.command_sender import CommandSender


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


def _make_mock_process(has_bridge: bool = True) -> MagicMock:
    """Создать mock GuiProcess."""
    process = MagicMock()
    process.name = "gui_process"
    if has_bridge:
        process._bridge = MagicMock()  # DataReceiverBridge mock
    else:
        # Симулируем отсутствие атрибута _bridge
        del process._bridge
    return process


# ---------------------------------------------------------------------------
# Тесты AppContext
# ---------------------------------------------------------------------------


class TestAppContext:
    """Тесты dataclass AppContext."""

    def test_creation_with_all_fields(self):
        """AppContext создаётся с обязательными и опциональными полями."""
        process = _make_mock_process()
        command_sender = CommandSender(process)
        bridge = process._bridge

        ctx = AppContext(
            process=process,
            command_sender=command_sender,
            bridge=bridge,
            config={"key": "value"},
            extras={"extra_key": 42},
        )

        assert ctx.process is process
        assert ctx.command_sender is command_sender
        assert ctx.bridge is bridge
        assert ctx.config == {"key": "value"}
        assert ctx.extras == {"extra_key": 42}

    def test_default_config_and_extras_are_empty_dicts(self):
        """По умолчанию config и extras — пустые dict."""
        process = _make_mock_process()
        command_sender = CommandSender(process)
        bridge = process._bridge

        ctx = AppContext(
            process=process,
            command_sender=command_sender,
            bridge=bridge,
        )

        assert ctx.config == {}
        assert ctx.extras == {}

    def test_default_factories_are_independent(self):
        """Два экземпляра AppContext не разделяют одни и те же dict-объекты."""
        process = _make_mock_process()
        command_sender = CommandSender(process)
        bridge = process._bridge

        ctx1 = AppContext(process=process, command_sender=command_sender, bridge=bridge)
        ctx2 = AppContext(process=process, command_sender=command_sender, bridge=bridge)

        assert ctx1.extras is not ctx2.extras
        assert ctx1.config is not ctx2.config

    def test_get_returns_value_from_extras(self):
        """get() возвращает значение из extras по ключу."""
        process = _make_mock_process()
        command_sender = CommandSender(process)

        ctx = AppContext(
            process=process,
            command_sender=command_sender,
            bridge=process._bridge,
            extras={"camera_id": "cam_0"},
        )

        assert ctx.get("camera_id") == "cam_0"

    def test_get_returns_default_for_missing_key(self):
        """get() возвращает default если ключ отсутствует."""
        process = _make_mock_process()
        ctx = AppContext(
            process=process,
            command_sender=CommandSender(process),
            bridge=process._bridge,
        )

        assert ctx.get("missing_key") is None
        assert ctx.get("missing_key", "fallback") == "fallback"

    def test_extras_can_be_mutated(self):
        """extras можно дополнять после создания."""
        process = _make_mock_process()
        ctx = AppContext(
            process=process,
            command_sender=CommandSender(process),
            bridge=process._bridge,
        )

        ctx.extras["new_key"] = "new_value"
        assert ctx.get("new_key") == "new_value"


# ---------------------------------------------------------------------------
# Тесты build_app_context
# ---------------------------------------------------------------------------


class TestBuildAppContext:
    """Тесты фабричной функции build_app_context."""

    def test_builds_context_from_process_with_bridge(self):
        """build_app_context создаёт AppContext если _bridge инициализирован."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        assert isinstance(ctx, AppContext)
        assert ctx.process is process
        assert ctx.bridge is process._bridge

    def test_command_sender_wraps_process(self):
        """CommandSender в контексте ссылается на тот же process."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        assert isinstance(ctx.command_sender, CommandSender)
        # CommandSender хранит process внутри
        assert ctx.command_sender._process is process

    def test_config_is_passed_through(self):
        """Переданный config попадает в AppContext."""
        process = _make_mock_process(has_bridge=True)
        cfg = {"fps": 30, "resolution": "1080p"}

        ctx = build_app_context(process, config=cfg)

        assert ctx.config == cfg

    def test_config_defaults_to_empty_dict(self):
        """Если config не передан — используется пустой dict."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        assert ctx.config == {}

    def test_extras_starts_empty(self):
        """extras после build_app_context всегда пустой dict."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        assert ctx.extras == {}

    def test_raises_if_bridge_is_none(self):
        """build_app_context выбрасывает AttributeError если _bridge не задан."""
        process = MagicMock()
        process.name = "gui_process"
        # _bridge явно None (атрибут существует, но равен None)
        process._bridge = None

        with pytest.raises(AttributeError, match="_bridge не инициализирован"):
            build_app_context(process)

    def test_raises_if_bridge_attribute_missing(self):
        """build_app_context выбрасывает AttributeError если _bridge отсутствует."""
        process = _make_mock_process(has_bridge=False)

        with pytest.raises(AttributeError, match="_bridge не инициализирован"):
            build_app_context(process)

    def test_two_contexts_have_different_command_senders(self):
        """Каждый вызов build_app_context создаёт новый CommandSender."""
        process = _make_mock_process(has_bridge=True)

        ctx1 = build_app_context(process)
        ctx2 = build_app_context(process)

        assert ctx1.command_sender is not ctx2.command_sender


# ---------------------------------------------------------------------------
# Тесты расширения AppContext: plugin_registry / registers_manager (Task 10A.1)
# ---------------------------------------------------------------------------


class TestAppContextExtras:
    """Тесты методов-аксессоров и kwargs plugin_registry/registers_manager."""

    def test_registers_manager_stored_in_extras(self):
        """build_app_context сохраняет registers_manager в extras["registers_manager"]."""
        process = _make_mock_process(has_bridge=True)
        mock_rm = MagicMock(name="RegistersManagerV2")

        ctx = build_app_context(process, registers_manager=mock_rm)

        assert ctx.extras.get("registers_manager") is mock_rm

    def test_plugin_registry_stored_in_extras(self):
        """build_app_context сохраняет plugin_registry в extras["plugin_registry"]."""
        process = _make_mock_process(has_bridge=True)
        mock_registry = MagicMock(name="PluginRegistry")

        ctx = build_app_context(process, plugin_registry=mock_registry)

        assert ctx.extras.get("plugin_registry") is mock_registry

    def test_accessor_returns_none_when_absent(self):
        """registers_manager() и plugin_registry() возвращают None если не переданы."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        assert ctx.registers_manager() is None
        assert ctx.plugin_registry() is None

    def test_accessor_returns_instance_when_present(self):
        """registers_manager() и plugin_registry() возвращают переданные объекты."""
        process = _make_mock_process(has_bridge=True)
        mock_rm = MagicMock(name="RegistersManagerV2")
        mock_registry = MagicMock(name="PluginRegistry")

        ctx = build_app_context(
            process,
            plugin_registry=mock_registry,
            registers_manager=mock_rm,
        )

        assert ctx.registers_manager() is mock_rm
        assert ctx.plugin_registry() is mock_registry

    def test_extras_extra_kwargs_optional(self):
        """build_app_context без новых kwargs сохраняет BC — extras пустой."""
        process = _make_mock_process(has_bridge=True)

        ctx = build_app_context(process)

        # extras пуст: новые ключи не появились
        assert "registers_manager" not in ctx.extras
        assert "plugin_registry" not in ctx.extras

    def test_two_contexts_independent_extras(self):
        """Два AppContext с разными kwargs имеют независимые extras."""
        process = _make_mock_process(has_bridge=True)
        mock_rm_1 = MagicMock(name="RegistersManagerV2_1")
        mock_rm_2 = MagicMock(name="RegistersManagerV2_2")

        ctx1 = build_app_context(process, registers_manager=mock_rm_1)
        ctx2 = build_app_context(process, registers_manager=mock_rm_2)

        assert ctx1.registers_manager() is mock_rm_1
        assert ctx2.registers_manager() is mock_rm_2
        assert ctx1.registers_manager() is not ctx2.registers_manager()
        # extras — разные объекты
        assert ctx1.extras is not ctx2.extras
