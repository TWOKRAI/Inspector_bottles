# -*- coding: utf-8 -*-
"""Тесты статического манифеста плагина (Ф4 Task 4.4).

Контур:
    plugins/manifest.py       — PluginCategory/canonicalize_category, check_requires,
                                 api_version_major_mismatch (юнит).
    plugins/registry.py       — канонизация category при register()/@register_plugin.
    plugins/base.py           — дефолты VERSION/API_VERSION/REQUIRES (back-compat).
    generic/plugin_orchestrator.py — boot-проверки (REQUIRES fail-fast, API_VERSION WARNING).
    commands/builtin_commands.py   — introspect.plugins.manifest обогащение.

Плюс сквозной прогон на 2 пилотных плагинах разных доменов (capture — manager:
command_manager, robot_io — manager:worker_manager) — регистрация → discovery →
introspect → boot-проверка requires, без моков framework-кода.
"""

from __future__ import annotations

import logging

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
    PluginOrchestrator,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.manifest import (
    PLUGIN_API_VERSION,
    api_version_major_mismatch,
    canonicalize_category,
    check_requires,
)
from multiprocess_framework.modules.process_module.plugins.registry import (
    PluginRegistry,
    register_plugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


# ---------------------------------------------------------------------------
# ProcessModulePlugin — дефолты манифеста (back-compat, 51 существующий плагин)
# ---------------------------------------------------------------------------


class _NoManifestPlugin(ProcessModulePlugin):
    """Плагин без объявленных манифест-полей — должен получить дефолты."""

    name = "no_manifest"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...


class TestManifestDefaults:
    def test_version_defaults_to_zero(self) -> None:
        assert _NoManifestPlugin.VERSION == "0.0.0"

    def test_api_version_defaults_to_current_contract(self) -> None:
        assert _NoManifestPlugin.API_VERSION == PLUGIN_API_VERSION

    def test_requires_defaults_to_empty_tuple(self) -> None:
        assert _NoManifestPlugin.REQUIRES == ()


# ---------------------------------------------------------------------------
# canonicalize_category — легаси-алиасы + неканоничное значение (WARNING, не отказ)
# ---------------------------------------------------------------------------


class TestCanonicalizeCategory:
    def test_canonical_value_passes_through(self) -> None:
        assert canonicalize_category("processing") == "processing"

    def test_legacy_rendering_maps_to_render(self) -> None:
        assert canonicalize_category("rendering") == "render"

    def test_legacy_output_maps_to_sink(self) -> None:
        assert canonicalize_category("output") == "sink"

    def test_empty_category_passes_through(self) -> None:
        assert canonicalize_category("") == ""

    def test_unknown_category_not_rejected(self) -> None:
        """Неканоничное значение НЕ отклоняется (Принцип №1) — возвращается как есть."""
        assert canonicalize_category("totally_unknown") == "totally_unknown"

    def test_unknown_category_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="multiprocess_framework.modules.process_module.plugins.manifest"):
            canonicalize_category("totally_unknown")
        assert any("totally_unknown" in r.getMessage() for r in caplog.records)


class TestRegistryCanonicalization:
    """Канонизация применяется В PluginRegistry.register()/@register_plugin."""

    def test_register_plugin_decorator_canonicalizes_legacy_category(self) -> None:
        @register_plugin("legacy_render_test", category="rendering")
        class _LegacyRenderPlugin(ProcessModulePlugin):
            name = "legacy_render_test"

            def configure(self, ctx: PluginContext) -> None: ...

        entry = PluginRegistry.get("legacy_render_test")
        assert entry is not None
        assert entry.category == "render"
        # cls.category синхронизирован с entry.category (не «сырой» декоратор-аргумент)
        assert _LegacyRenderPlugin.category == "render"

    def test_direct_register_call_canonicalizes_and_warns_on_unknown(self, caplog: pytest.LogCaptureFixture) -> None:
        class _DummyPlugin(ProcessModulePlugin):
            name = "dummy_unknown_cat"

            def configure(self, ctx: PluginContext) -> None: ...

        with caplog.at_level(logging.WARNING, logger="multiprocess_framework.modules.process_module.plugins.manifest"):
            entry = PluginRegistry.register("dummy_unknown_cat", _DummyPlugin, category="testing")

        assert entry.category == "testing"  # не отказ — сохранено как есть
        assert any("testing" in r.getMessage() for r in caplog.records)

    def test_direct_register_call_returns_entry(self) -> None:
        class _DummyPlugin(ProcessModulePlugin):
            name = "dummy_returns_entry"

            def configure(self, ctx: PluginContext) -> None: ...

        entry = PluginRegistry.register("dummy_returns_entry", _DummyPlugin, category="processing")
        assert entry is PluginRegistry.get("dummy_returns_entry")


# ---------------------------------------------------------------------------
# check_requires — manager:/service:/shm + неизвестный формат
# ---------------------------------------------------------------------------


class TestCheckRequires:
    def test_empty_requires_always_satisfied(self) -> None:
        services = MockProcessServices(name="test")
        ctx = PluginContext(services=services)
        assert check_requires(ctx, ()) == []

    def test_manager_present_satisfied(self) -> None:
        services = MockProcessServices(name="test")
        ctx = PluginContext(services=services)  # worker_manager есть по умолчанию (Mock)
        assert check_requires(ctx, ("manager:worker_manager",)) == []

    def test_manager_missing_reported(self) -> None:
        services = MockProcessServices(name="test", router_manager=None)
        ctx = PluginContext(services=services)
        missing = check_requires(ctx, ("manager:router_manager",))
        assert len(missing) == 1
        assert "manager:router_manager" in missing[0]

    def test_shm_missing_reported(self) -> None:
        services = MockProcessServices(name="test", memory_manager=None)
        ctx = PluginContext(services=services)
        missing = check_requires(ctx, ("shm",))
        assert len(missing) == 1
        assert "shm" in missing[0]

    def test_service_present_satisfied(self) -> None:
        services = MockProcessServices(name="test")
        services.sql_manager = object()  # плагин повесил менеджер в configure_managers()
        ctx = PluginContext(services=services)
        assert check_requires(ctx, ("service:sql_manager",)) == []

    def test_service_missing_reported(self) -> None:
        services = MockProcessServices(name="test")
        ctx = PluginContext(services=services)
        missing = check_requires(ctx, ("service:sql_manager",))
        assert len(missing) == 1
        assert "service:sql_manager" in missing[0]

    def test_unknown_requirement_format_reported(self) -> None:
        services = MockProcessServices(name="test")
        ctx = PluginContext(services=services)
        missing = check_requires(ctx, ("garbage",))
        assert len(missing) == 1

    def test_multiple_requirements_all_checked(self) -> None:
        services = MockProcessServices(name="test", memory_manager=None)
        ctx = PluginContext(services=services)
        missing = check_requires(ctx, ("manager:worker_manager", "shm"))
        assert len(missing) == 1  # worker_manager есть (Mock), shm отсутствует


# ---------------------------------------------------------------------------
# api_version_major_mismatch
# ---------------------------------------------------------------------------


class TestApiVersionMismatch:
    def test_same_major_no_mismatch(self) -> None:
        assert api_version_major_mismatch("1.5", framework_api_version="1.0") is False

    def test_different_major_is_mismatch(self) -> None:
        assert api_version_major_mismatch("2.0", framework_api_version="1.0") is True

    def test_defaults_to_current_framework_version(self) -> None:
        assert api_version_major_mismatch(PLUGIN_API_VERSION) is False


# ---------------------------------------------------------------------------
# PluginOrchestrator.boot() — REQUIRES fail-fast + API_VERSION WARNING
# ---------------------------------------------------------------------------

_MODULE = __name__


class _RequiresWorkerManagerPlugin(ProcessModulePlugin):
    name = "requires_worker_manager"
    category = "processing"
    REQUIRES: tuple[str, ...] = ("manager:worker_manager",)

    def configure(self, ctx: PluginContext) -> None:
        self.configured = True


class _RequiresMissingManagerPlugin(ProcessModulePlugin):
    name = "requires_missing_manager"
    category = "processing"
    REQUIRES: tuple[str, ...] = ("manager:router_manager",)

    def configure(self, ctx: PluginContext) -> None:
        self.configured = True  # не должно быть вызвано — router_manager отсутствует в Mock


class _OldApiVersionPlugin(ProcessModulePlugin):
    name = "old_api_version"
    category = "processing"
    API_VERSION = "0.5"  # major=0, текущий контракт major=1 -> mismatch

    def configure(self, ctx: PluginContext) -> None:
        self.configured = True


class TestBootManifestChecks:
    def test_satisfied_requires_configures_normally(self) -> None:
        services = MockProcessServices(name="test")
        orch = PluginOrchestrator(services=services)
        orch.load_and_configure_managers(
            [{"plugin_class": f"{_MODULE}._RequiresWorkerManagerPlugin", "plugin_name": "p"}]
        )
        orch.boot()
        assert len(orch.plugins) == 1
        assert getattr(orch.plugins[0], "configured", False) is True

    def test_missing_requires_skips_plugin_and_logs_error(self) -> None:
        services = MockProcessServices(name="test", router_manager=None)
        orch = PluginOrchestrator(services=services)
        orch.load_and_configure_managers(
            [
                {
                    "plugin_class": f"{_MODULE}._RequiresMissingManagerPlugin",
                    "plugin_name": "requires_missing_manager",
                }
            ]
        )
        orch.boot()

        # Плагин пропущен: не в orch.plugins, configure() НЕ вызван — skip/loud,
        # процесс жив (та же строгость, что провал самого configure()).
        assert orch.plugins == []
        errors = [e["msg"] for e in services.logs if e["level"] == "ERROR"]
        assert any("requires_missing_manager" in msg and "manager:router_manager" in msg for msg in errors)

    def test_api_version_mismatch_warns_but_does_not_skip(self) -> None:
        services = MockProcessServices(name="test")
        orch = PluginOrchestrator(services=services)
        orch.load_and_configure_managers(
            [{"plugin_class": f"{_MODULE}._OldApiVersionPlugin", "plugin_name": "old_api_version"}]
        )
        orch.boot()

        # Плагин НЕ пропущен (WARNING — не отказ), configure() выполнен.
        assert len(orch.plugins) == 1
        assert getattr(orch.plugins[0], "configured", False) is True
        warnings = [e["msg"] for e in services.logs if e["level"] == "WARNING"]
        assert any("old_api_version" in msg and "API_VERSION" in msg for msg in warnings)


# ---------------------------------------------------------------------------
# introspect.plugins — манифест-поля (Ф4.4 п.4)
# ---------------------------------------------------------------------------


class TestIntrospectPluginsManifest:
    def test_manifest_field_present_alongside_legacy_plugins_field(self) -> None:
        class _ManifestPlugin(ProcessModulePlugin):
            name = "manifest_probe"
            VERSION = "3.2.1"
            REQUIRES: tuple[str, ...] = ("shm",)

            def configure(self, ctx: PluginContext) -> None: ...

        PluginRegistry.register("manifest_probe", _ManifestPlugin, category="processing")

        services = MockProcessServices(name="preprocessor")
        cm = BuiltinCommands(services)
        result = cm._cmd_introspect_plugins()

        # Легаси-поле НЕ тронуто (back-compat, ADR-PM-013).
        assert result["plugins"] == {"manifest_probe": "processing"}
        # Новое поле — аддитивное обогащение.
        assert result["manifest"]["manifest_probe"] == {
            "category": "processing",
            "version": "3.2.1",
            "api_version": PLUGIN_API_VERSION,
            "requires": ["shm"],
        }


# ---------------------------------------------------------------------------
# Сквозной контур на пилотных плагинах: регистрация -> discovery(import) ->
# introspect -> boot-проверка requires (acceptance Ф4.4).
# ---------------------------------------------------------------------------


def _reimport_and_register(module_dotted: str):
    """import-или-reload с гарантированно чистым слотом имени в PluginRegistry.

    Модуль плагина может уже быть в ``sys.modules`` (импортирован другим
    тестовым файлом раньше в прогоне) — plain re-import тогда no-op и НЕ
    восстановит запись, снесённую автouse ``PluginRegistry.clear()`` этого
    файла (тот же класс гонки, что у 7 доэкзистентных test-order flake
    реестра). А если это, наоборот, ПЕРВЫЙ импорт модуля в процессе — plain
    import сам зарегистрирует плагин, и последующий ``reload()`` столкнётся
    с уже занятым именем (другой class-объект — `register()` ValueError).
    Решение: импортировать, затем принудительно очистить реестр И ТОЛЬКО
    ПОТОМ reload — не зависит от того, был импорт кэширован или нет.
    """
    import importlib

    module = importlib.import_module(module_dotted)
    PluginRegistry.clear()
    return importlib.reload(module)


class TestPilotPluginsManifestContour:
    """capture (source, manager:command_manager) + robot_io (io, manager:worker_manager).

    crop покрыт отдельно (`Plugins/processing/crop/tests`) — здесь фокус на
    REQUIRES-несущих пилотах, т.к. именно они гоняют boot fail-fast путь.
    """

    def test_capture_manifest_registered_after_import(self) -> None:
        _reimport_and_register("Plugins.sources.capture.plugin")

        entry = PluginRegistry.get("capture")
        assert entry is not None
        assert entry.version == "1.0.0"
        assert entry.requires == ("manager:command_manager",)
        assert entry.category == "source"

    def test_robot_io_manifest_registered_after_import(self) -> None:
        _reimport_and_register("Plugins.io.robot_io.plugin")

        entry = PluginRegistry.get("robot_io")
        assert entry is not None
        assert entry.version == "2.0.0"
        assert entry.requires == ("manager:worker_manager",)
        assert entry.category == "io"

    def test_capture_boots_successfully_with_command_manager(self) -> None:
        capture_plugin = _reimport_and_register("Plugins.sources.capture.plugin")

        services = MockProcessServices(name="preprocessor")
        orch = PluginOrchestrator(services=services)
        orch.load_and_configure_managers(
            [{"plugin_class": capture_plugin.CapturePlugin.__module__ + ".CapturePlugin", "plugin_name": "capture"}]
        )
        orch.boot()
        assert len(orch.plugins) == 1

    def test_capture_skipped_without_command_manager(self) -> None:
        capture_plugin = _reimport_and_register("Plugins.sources.capture.plugin")

        services = MockProcessServices(name="preprocessor")
        services.command_manager = None  # симулируем процесс без CommandManager
        orch = PluginOrchestrator(services=services)
        orch.load_and_configure_managers(
            [{"plugin_class": capture_plugin.CapturePlugin.__module__ + ".CapturePlugin", "plugin_name": "capture"}]
        )
        orch.boot()
        assert orch.plugins == []
        errors = [e["msg"] for e in services.logs if e["level"] == "ERROR"]
        assert any("capture" in msg and "manager:command_manager" in msg for msg in errors)

    def test_introspect_plugins_exposes_pilot_manifest(self) -> None:
        _reimport_and_register("Plugins.io.robot_io.plugin")

        services = MockProcessServices(name="devices")
        cm = BuiltinCommands(services)
        result = cm._cmd_introspect_plugins()

        assert result["manifest"]["robot_io"]["version"] == "2.0.0"
        assert result["manifest"]["robot_io"]["requires"] == ["manager:worker_manager"]
        assert result["manifest"]["robot_io"]["category"] == "io"
