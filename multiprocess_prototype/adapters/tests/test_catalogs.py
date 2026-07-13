# -*- coding: utf-8 -*-
"""
adapters/tests/test_catalogs.py — тесты для catalog адаптеров.

Покрываемые классы:
    - PluginCatalogFromRegistry  (plugin_catalog.py)
    - ServiceManagerFromRegistry (service_catalog.py) — read + lifecycle
    - DisplayCatalogFromRegistry (display_catalog.py)

Паттерн:
    Fake*Registry — plain Python classes (не MagicMock),
    в соответствии с decision Phase B (_fakes.py).
"""

from __future__ import annotations

import logging

import pytest

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginCatalog, PluginSpec
from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.service_catalog import ServiceManager
from multiprocess_prototype.domain.protocols.display_catalog import DisplayCatalog

from multiprocess_prototype.adapters.catalogs import (
    PluginCatalogFromRegistry,
    ServiceManagerFromRegistry,
    DisplayCatalogFromRegistry,
)


# ==============================================================================
# Fake-классы для изоляции (не MagicMock)
# ==============================================================================


class _FakePort:
    """Минимальный объект, имитирующий Port (name + dtype + optional + shape).

    Обновлён в Task C.1.5: добавлены optional и shape для lossless маппинга.
    """

    def __init__(self, name: str, dtype: str = "any", optional: bool = False, shape: str = "") -> None:
        self.name = name
        self.dtype = dtype
        self.optional = optional
        self.shape = shape


class _FakePluginEntry:
    """Имитация PluginEntry из _PluginRegistry.

    Обновлён в Task C.1.5: добавлен description для lossless маппинга.
    """

    def __init__(
        self,
        name: str,
        category: str = "",
        description: str = "",
        inputs: list | None = None,
        outputs: list | None = None,
        register_classes: list | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.description = description
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.register_classes = register_classes or []


class _FakePluginRegistry:
    """Имитация _PluginRegistry с фиксированным набором плагинов."""

    def __init__(self, entries: list[_FakePluginEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def list(self) -> list[_FakePluginEntry]:
        return list(self._entries.values())

    def get(self, name: str) -> _FakePluginEntry | None:
        return self._entries.get(name)


class _FakeService:
    """Минимальная имитация IService для lifecycle тестов."""

    def __init__(self, *, start_ok: bool = True, stop_ok: bool = True) -> None:
        self._start_ok = start_ok
        self._stop_ok = stop_ok
        self.started = False
        self.stopped = False

    def start(self, config: dict) -> bool:
        self.started = True
        return self._start_ok

    def stop(self) -> bool:
        self.stopped = True
        return self._stop_ok

    def get_status(self) -> dict:
        return {"status": "ok"}


def _make_service_cls(display_name: str = "Svc", *, start_ok: bool = True, stop_ok: bool = True) -> type:
    """Создать фейковый класс сервиса с настраиваемым поведением start/stop."""

    class _Svc:
        name: str = display_name

        def __init__(self) -> None:
            self._start_ok = start_ok
            self._stop_ok = stop_ok

        def start(self, config: dict) -> bool:
            return self._start_ok

        def stop(self) -> bool:
            return self._stop_ok

        def get_status(self) -> dict:
            return {"name": self.name, "status": "ok"}

    _Svc.__name__ = display_name
    _Svc.__qualname__ = display_name
    return _Svc


class _FakeServiceEntry:
    """Имитация ServiceEntry из ServiceRegistry.

    Обновлён в Task C.1.6: lifecycle + cls с start/stop методами.
    """

    def __init__(
        self,
        name: str,
        display_name: str = "",
        meta: dict | None = None,
        lifecycle: "ServiceLifecycle | None" = None,
        *,
        start_ok: bool = True,
        stop_ok: bool = True,
    ) -> None:
        self.name = name
        # cls — тип класса с start/stop для lifecycle тестов
        self.cls = _make_service_cls(display_name, start_ok=start_ok, stop_ok=stop_ok)
        self.meta = meta or {}
        self.lifecycle = lifecycle if lifecycle is not None else ServiceLifecycle.READY


class _FakeServiceRegistry:
    """Имитация ServiceRegistry с фиксированным набором сервисов."""

    def __init__(self, entries: list[_FakeServiceEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def list(self) -> list[_FakeServiceEntry]:
        return list(self._entries.values())

    def get(self, name: str) -> _FakeServiceEntry | None:
        return self._entries.get(name)


class _FakeDisplayEntry:
    """Имитация DisplayEntry из DisplayRegistry."""

    def __init__(
        self,
        id: str,
        name: str,
        width: int = 640,
        height: int = 480,
        format: str = "BGR",
        fps_limit: float = 30.0,
        ring_buffer_blocks: int = 3,
    ) -> None:
        self.id = id
        self.name = name
        self.width = width
        self.height = height
        self.format = format
        self.fps_limit = fps_limit
        self.ring_buffer_blocks = ring_buffer_blocks


class _FakeDisplayRegistry:
    """Имитация DisplayRegistry с CRUD-операциями (Phase F).

    Поддерживает list/get/register/unregister/__contains__/persist.
    persist() запоминает последний вызванный path для тест-проверки.
    """

    def __init__(self, entries: list[_FakeDisplayEntry] | None = None) -> None:
        self._entries = {e.id: e for e in (entries or [])}
        self.last_persist_path: object = None

    def list(self) -> list[_FakeDisplayEntry]:
        return list(self._entries.values())

    def get(self, display_id: str) -> _FakeDisplayEntry | None:
        return self._entries.get(display_id)

    def register(self, entry: _FakeDisplayEntry) -> None:
        if entry.id in self._entries:
            raise ValueError(f"Display '{entry.id}' already registered")
        self._entries[entry.id] = entry

    def unregister(self, display_id: str) -> bool:
        return self._entries.pop(display_id, None) is not None

    def __contains__(self, display_id: str) -> bool:
        return display_id in self._entries

    def persist(self, path: object) -> None:
        self.last_persist_path = path


# ==============================================================================
# Тесты PluginCatalogFromRegistry
# ==============================================================================


class TestPluginCatalogFromRegistry:
    """Тесты для PluginCatalogFromRegistry."""

    def _make_registry(self, entries: list[_FakePluginEntry] | None = None) -> _FakePluginRegistry:
        return _FakePluginRegistry(entries or [])

    def _make_adapter(self, entries: list[_FakePluginEntry] | None = None) -> PluginCatalogFromRegistry:
        return PluginCatalogFromRegistry(self._make_registry(entries))  # type: ignore[arg-type]

    def test_plugin_catalog_lists_known_plugins(self):
        """Фейковый реестр с 2 плагинами → list_plugins() возвращает 2 PluginSpec."""
        entries = [
            _FakePluginEntry("grayscale", category="processing"),
            _FakePluginEntry("blur", category="processing"),
        ]
        catalog = self._make_adapter(entries)
        result = catalog.list_plugins()

        assert len(result) == 2
        names = {spec.name for spec in result}
        assert names == {"grayscale", "blur"}

    def test_plugin_catalog_returns_tuple(self):
        """list_plugins() возвращает tuple (не list)."""
        entries = [_FakePluginEntry("flip", category="processing")]
        catalog = self._make_adapter(entries)
        result = catalog.list_plugins()
        assert isinstance(result, tuple)

    def test_plugin_catalog_resolve_known_plugin(self):
        """resolve() с известным именем возвращает PluginSpec."""
        entries = [_FakePluginEntry("grayscale", category="processing")]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("grayscale")

        assert spec is not None
        assert spec.name == "grayscale"
        assert spec.category == "processing"

    def test_plugin_catalog_resolve_unknown_returns_none(self):
        """resolve() с неизвестным именем возвращает None."""
        catalog = self._make_adapter([])
        assert catalog.resolve("nonexistent_plugin") is None

    def test_plugin_catalog_resolve_roundtrip(self):
        """Round-trip: entry.name == catalog.resolve(entry.name).name."""
        entry = _FakePluginEntry("color_mask", category="processing")
        catalog = self._make_adapter([entry])
        resolved = catalog.resolve(entry.name)
        assert resolved is not None
        assert entry.name == resolved.name

    def test_plugin_catalog_categories_dedup(self):
        """categories() возвращает уникальные категории (dedup)."""
        entries = [
            _FakePluginEntry("grayscale", category="processing"),
            _FakePluginEntry("blur", category="processing"),
            _FakePluginEntry("webcam", category="source"),
        ]
        catalog = self._make_adapter(entries)
        cats = catalog.categories()

        assert isinstance(cats, tuple)
        assert len(cats) == len(set(cats)), "дублирующиеся категории не допускаются"
        assert set(cats) == {"processing", "source"}

    def test_plugin_catalog_categories_sorted(self):
        """categories() возвращает отсортированный tuple."""
        entries = [
            _FakePluginEntry("z_plugin", category="zzz"),
            _FakePluginEntry("a_plugin", category="aaa"),
        ]
        catalog = self._make_adapter(entries)
        cats = catalog.categories()
        assert list(cats) == sorted(cats)

    def test_plugin_catalog_with_empty_registry_returns_empty(self):
        """Пустой реестр → list_plugins() возвращает пустой tuple."""
        catalog = self._make_adapter([])
        assert catalog.list_plugins() == ()

    def test_plugin_catalog_categories_empty_registry(self):
        """Пустой реестр → categories() возвращает пустой tuple."""
        catalog = self._make_adapter([])
        assert catalog.categories() == ()

    def test_plugin_catalog_ports_mapping(self):
        """inputs + outputs маппятся в ports PluginSpec."""
        entry = _FakePluginEntry(
            "bgr",
            category="processing",
            inputs=[_FakePort("frame", "image/bgr")],
            outputs=[_FakePort("out", "image/gray")],
        )
        catalog = self._make_adapter([entry])
        spec = catalog.resolve("bgr")

        assert spec is not None
        assert len(spec.ports) == 2
        port_names = {p.name for p in spec.ports}
        assert "frame" in port_names
        assert "out" in port_names

    def test_plugin_catalog_ports_direction(self):
        """inputs получают direction='input', outputs — direction='output'."""
        entry = _FakePluginEntry(
            "split",
            category="processing",
            inputs=[_FakePort("frame", "image/bgr")],
            outputs=[_FakePort("mask", "image/gray"), _FakePort("preview", "image/bgr")],
        )
        catalog = self._make_adapter([entry])
        spec = catalog.resolve("split")

        assert spec is not None
        assert len(spec.ports) == 3

        input_port = next(p for p in spec.ports if p.name == "frame")
        assert input_port.direction == "input"

        mask_port = next(p for p in spec.ports if p.name == "mask")
        assert mask_port.direction == "output"

        preview_port = next(p for p in spec.ports if p.name == "preview")
        assert preview_port.direction == "output"

    def test_plugin_catalog_satisfies_protocol(self):
        """Adapter удовлетворяет PluginCatalog Protocol (assignment-проверка)."""
        catalog = self._make_adapter([])
        _protocol_check: PluginCatalog = catalog  # type: ignore[assignment]
        assert _protocol_check is catalog

    def test_plugin_catalog_spec_is_frozen(self):
        """PluginSpec заморожен — попытка изменить атрибут вызывает ошибку."""
        entries = [_FakePluginEntry("flip", category="processing")]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("flip")
        assert spec is not None

        with pytest.raises((AttributeError, TypeError)):
            spec.name = "changed"  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Task C.1.5 — тесты новых полей description / optional / shape
    # ------------------------------------------------------------------

    def test_plugin_spec_has_description(self):
        """entry с description='Test plugin' → spec.description == 'Test plugin'."""
        entry = _FakePluginEntry("edge_detect", category="processing", description="Test plugin")
        catalog = self._make_adapter([entry])
        spec = catalog.resolve("edge_detect")

        assert spec is not None
        assert spec.description == "Test plugin"

    def test_plugin_spec_description_defaults_empty(self):
        """entry без атрибута description (getattr fallback) → spec.description == ''."""

        class _LegacyEntry:
            """Имитация legacy entry без атрибута description."""

            def __init__(self) -> None:
                self.name = "legacy_plugin"
                self.category = "legacy"
                self.inputs: list = []
                self.outputs: list = []
                self.register_classes: list = []

            # Намеренно: атрибут description отсутствует

        class _LegacyRegistry:
            def list(self):
                return [_LegacyEntry()]

            def get(self, name: str):
                if name == "legacy_plugin":
                    return _LegacyEntry()
                return None

        from multiprocess_prototype.adapters.catalogs.plugin_catalog import PluginCatalogFromRegistry

        catalog = PluginCatalogFromRegistry(_LegacyRegistry())  # type: ignore[arg-type]
        spec = catalog.resolve("legacy_plugin")

        assert spec is not None
        assert spec.description == "", f"Ожидался пустой description, получен: {spec.description!r}"

    def test_port_spec_has_optional_and_shape(self):
        """port с optional=True, shape='(3,4)' → PortSpec.optional=True, shape='(3,4)'."""
        entry = _FakePluginEntry(
            "transform",
            category="processing",
            inputs=[_FakePort("frame", "image/bgr", optional=True, shape="(3,4)")],
            outputs=[_FakePort("out", "image/gray", optional=False, shape="(H, W, 1)")],
        )
        catalog = self._make_adapter([entry])
        spec = catalog.resolve("transform")

        assert spec is not None
        assert len(spec.ports) == 2

        input_port = next(p for p in spec.ports if p.name == "frame")
        assert input_port.optional is True
        assert input_port.shape == "(3,4)"

        output_port = next(p for p in spec.ports if p.name == "out")
        assert output_port.optional is False
        assert output_port.shape == "(H, W, 1)"

    def test_port_spec_optional_defaults_false(self):
        """port без явных optional/shape атрибутов → PortSpec defaults (optional=False, shape='')."""

        class _MinimalPort:
            """Порт только с name и dtype (нет optional/shape)."""

            def __init__(self, name: str, dtype: str) -> None:
                self.name = name
                self.dtype = dtype

            # Намеренно: optional и shape отсутствуют

        entry = _FakePluginEntry(
            "minimal_plugin",
            category="processing",
            inputs=[_MinimalPort("in", "any")],
        )
        # Подменяем inputs на minimal port без optional/shape
        catalog = self._make_adapter([entry])
        spec = catalog.resolve("minimal_plugin")

        assert spec is not None
        assert len(spec.ports) == 1
        port = spec.ports[0]
        assert port.optional is False, f"Ожидался optional=False, получен: {port.optional}"
        assert port.shape == "", f"Ожидался shape='', получен: {port.shape!r}"


# ==============================================================================
# Тесты ServiceManagerFromRegistry (lifecycle — Task C.1.6)
# ==============================================================================


class TestServiceManagerFromRegistry:
    """Lifecycle-тесты для ServiceManagerFromRegistry (Phase C.1.6)."""

    def _make_registry(self, entries: list[_FakeServiceEntry] | None = None) -> _FakeServiceRegistry:
        return _FakeServiceRegistry(entries or [])

    def _make_adapter(self, entries: list[_FakeServiceEntry] | None = None) -> ServiceManagerFromRegistry:
        return ServiceManagerFromRegistry(self._make_registry(entries))  # type: ignore[arg-type]

    def test_service_manager_satisfies_protocol(self):
        """Adapter удовлетворяет ServiceManager Protocol (assignment-проверка)."""
        manager = self._make_adapter([])
        _protocol_check: ServiceManager = manager  # type: ignore[assignment]
        assert _protocol_check is manager

    def test_start_changes_lifecycle_to_running(self):
        """start() меняет lifecycle на RUNNING."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.READY)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        manager.start("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.RUNNING

    def test_start_idempotent_if_already_running(self):
        """start() на уже RUNNING сервисе — idempotent no-op."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.RUNNING)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        manager.start("cam")  # не бросает

        assert registry.get("cam").lifecycle == ServiceLifecycle.RUNNING

    def test_start_unknown_service_raises_domain_error(self):
        """start() с неизвестным service_id бросает DomainError."""
        manager = self._make_adapter([])

        with pytest.raises(DomainError, match="Unknown service"):
            manager.start("nonexistent")

    def test_stop_changes_lifecycle_to_stopped(self):
        """stop() меняет lifecycle на STOPPED."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.RUNNING)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]
        # Нужно закэшировать instance для корректного stop
        manager._instances["cam"] = entries[0].cls()

        manager.stop("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.STOPPED

    def test_stop_idempotent_if_already_stopped(self):
        """stop() на уже STOPPED сервисе — idempotent no-op."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.STOPPED)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        manager.stop("cam")  # не бросает

        assert registry.get("cam").lifecycle == ServiceLifecycle.STOPPED

    def test_stop_without_instance_syncs_lifecycle(self):
        """stop() без instance в кэше — синхронизирует lifecycle → STOPPED."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.RUNNING)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]
        # Instance не в кэше — stop() просто синхронизирует lifecycle

        manager.stop("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.STOPPED

    def test_stop_unknown_service_raises_domain_error(self):
        """stop() с неизвестным service_id бросает DomainError."""
        manager = self._make_adapter([])

        with pytest.raises(DomainError, match="Unknown service"):
            manager.stop("nonexistent")

    def test_restart_stops_then_starts(self):
        """restart() вызывает stop() → start()."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.RUNNING)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]
        # Кэшируем instance для корректного stop
        manager._instances["cam"] = entries[0].cls()

        manager.restart("cam")

        # После restart — lifecycle RUNNING
        assert registry.get("cam").lifecycle == ServiceLifecycle.RUNNING

    def test_restart_unknown_service_raises_domain_error(self):
        """restart() с неизвестным service_id бросает DomainError."""
        manager = self._make_adapter([])

        with pytest.raises(DomainError, match="Unknown service"):
            manager.restart("nonexistent")

    def test_get_lifecycle_known_service_returns_status(self):
        """get_lifecycle() для известного сервиса возвращает его lifecycle."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.READY)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        result = manager.get_lifecycle("cam")

        assert result == ServiceLifecycle.READY

    def test_get_lifecycle_after_start(self):
        """get_lifecycle() после start() возвращает RUNNING."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.READY)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        manager.start("cam")

        assert manager.get_lifecycle("cam") == ServiceLifecycle.RUNNING

    def test_get_lifecycle_unknown_service_raises_domain_error(self):
        """get_lifecycle() с неизвестным service_id бросает DomainError."""
        manager = self._make_adapter([])

        with pytest.raises(DomainError, match="Unknown service"):
            manager.get_lifecycle("nonexistent")

    def test_start_cls_raises_sets_error_lifecycle(self):
        """Если cls() бросает исключение — lifecycle = ERROR + DomainError."""

        class _BadCls:
            __name__ = "BadService"

            def __init__(self) -> None:
                raise RuntimeError("Cannot instantiate")

        entry = _FakeServiceEntry("bad", "BadService", lifecycle=ServiceLifecycle.READY)
        entry.cls = _BadCls  # type: ignore[assignment]
        registry = self._make_registry([entry])
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        with pytest.raises(DomainError, match="Failed to instantiate"):
            manager.start("bad")

        assert registry.get("bad").lifecycle == ServiceLifecycle.ERROR

    def test_start_returns_false_sets_error_lifecycle(self):
        """Если instance.start() возвращает False — lifecycle = ERROR + DomainError."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.READY, start_ok=False)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        with pytest.raises(DomainError, match="returned False"):
            manager.start("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.ERROR

    def test_stop_returns_false_sets_error_lifecycle(self):
        """instance.stop() возвращает False → lifecycle = ERROR + DomainError."""
        entries = [_FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.RUNNING, stop_ok=False)]
        registry = self._make_registry(entries)
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]
        # Кэшируем instance с stop_ok=False (имитация: start() ранее создал)
        manager._instances["cam"] = entries[0].cls()

        with pytest.raises(DomainError, match="returned False"):
            manager.stop("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.ERROR

    def test_start_instance_raises_sets_error_lifecycle(self):
        """instance.start({}) бросает exception → lifecycle = ERROR + DomainError."""

        class _RaisingOnStart:
            """cls() работает нормально, но instance.start() бросает."""

            __name__ = "RaisingService"

            def start(self, config: dict) -> bool:
                raise RuntimeError("boom from instance.start")

            def stop(self) -> bool:
                return True

        entry = _FakeServiceEntry("cam", "Camera", lifecycle=ServiceLifecycle.READY)
        entry.cls = _RaisingOnStart  # type: ignore[assignment]
        registry = self._make_registry([entry])
        manager = ServiceManagerFromRegistry(registry)  # type: ignore[arg-type]

        with pytest.raises(DomainError, match="start\\(\\) failed"):
            manager.start("cam")

        assert registry.get("cam").lifecycle == ServiceLifecycle.ERROR

    def test_read_only_methods_still_work(self):
        """ServiceManagerFromRegistry сохраняет read-only функциональность C.1."""
        entries = [_FakeServiceEntry("svc1", "Svc1", meta={"vendor": "test"})]
        manager = self._make_adapter(entries)

        result = manager.list_services()
        assert len(result) == 1
        assert result[0].service_id == "svc1"

        spec = manager.resolve("svc1")
        assert spec is not None
        assert spec.metadata.get("vendor") == "test"

        assert manager.resolve("unknown") is None


# ==============================================================================
# Тесты DisplayCatalogFromRegistry
# ==============================================================================


class TestDisplayCatalogFromRegistry:
    """Тесты для DisplayCatalogFromRegistry."""

    def _make_registry(self, entries: list[_FakeDisplayEntry] | None = None) -> _FakeDisplayRegistry:
        return _FakeDisplayRegistry(entries or [])

    def _make_adapter(self, entries: list[_FakeDisplayEntry] | None = None) -> DisplayCatalogFromRegistry:
        return DisplayCatalogFromRegistry(self._make_registry(entries))  # type: ignore[arg-type]

    def test_display_catalog_lists_known_displays(self):
        """Фейковый реестр с 2 дисплеями → list_displays() возвращает 2 DisplaySpec."""
        entries = [
            _FakeDisplayEntry("main", "Основной дисплей"),
            _FakeDisplayEntry("debug", "Отладочный дисплей"),
        ]
        catalog = self._make_adapter(entries)
        result = catalog.list_displays()

        assert len(result) == 2
        ids = {spec.display_id for spec in result}
        assert ids == {"main", "debug"}

    def test_display_catalog_returns_tuple(self):
        """list_displays() возвращает tuple (не list)."""
        entries = [_FakeDisplayEntry("d1", "Display 1")]
        catalog = self._make_adapter(entries)
        assert isinstance(catalog.list_displays(), tuple)

    def test_display_catalog_resolve_known_display(self):
        """resolve() с известным display_id возвращает DisplaySpec."""
        entries = [_FakeDisplayEntry("main", "Основной")]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("main")

        assert spec is not None
        assert spec.display_id == "main"
        assert spec.display_name == "Основной"

    def test_display_catalog_resolve_unknown_returns_none(self):
        """resolve() с неизвестным id возвращает None."""
        catalog = self._make_adapter([])
        assert catalog.resolve("no_such_display") is None

    def test_display_catalog_resolve_roundtrip(self):
        """Round-trip: entry.id == catalog.resolve(entry.id).display_id."""
        entry = _FakeDisplayEntry("preview", "Preview")
        catalog = self._make_adapter([entry])
        resolved = catalog.resolve(entry.id)
        assert resolved is not None
        assert entry.id == resolved.display_id

    def test_display_catalog_first_class_fields(self):
        """DisplaySpec содержит first-class поля width/height/format/fps_limit/ring_buffer_blocks."""
        entries = [
            _FakeDisplayEntry(
                "main", "Main", width=1280, height=720, format="BGR", fps_limit=30.0, ring_buffer_blocks=3
            )
        ]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("main")

        assert spec is not None
        assert spec.width == 1280
        assert spec.height == 720
        assert spec.format == "BGR"
        assert spec.fps_limit == 30.0
        assert spec.ring_buffer_blocks == 3

    def test_display_catalog_with_empty_registry_returns_empty(self):
        """Пустой реестр -> list_displays() возвращает пустой tuple."""
        catalog = self._make_adapter([])
        assert catalog.list_displays() == ()

    def test_display_catalog_satisfies_protocol(self):
        """Adapter удовлетворяет DisplayCatalog Protocol (assignment-проверка)."""
        catalog = self._make_adapter([])
        _protocol_check: DisplayCatalog = catalog  # type: ignore[assignment]
        assert _protocol_check is catalog

    def test_display_catalog_spec_is_frozen(self):
        """DisplaySpec заморожен — попытка изменить атрибут вызывает ошибку."""
        entries = [_FakeDisplayEntry("d1", "Display 1")]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("d1")
        assert spec is not None

        with pytest.raises((AttributeError, TypeError)):
            spec.display_id = "changed"  # type: ignore[misc]

    # ------------------------------------------------------------------ #
    #  Phase F: write-методы (register/unregister/has/persist)             #
    # ------------------------------------------------------------------ #

    def test_display_catalog_register(self):
        """register(spec) добавляет дисплей в registry."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        catalog = self._make_adapter([])
        spec = DisplaySpec(display_id="new", display_name="New Display", width=800, height=600)
        catalog.register(spec)

        resolved = catalog.resolve("new")
        assert resolved is not None
        assert resolved.display_id == "new"
        assert resolved.width == 800

    def test_display_catalog_register_duplicate_raises(self):
        """register() с дубликатом id бросает ValueError."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        catalog = self._make_adapter([_FakeDisplayEntry("existing", "Existing")])
        spec = DisplaySpec(display_id="existing", display_name="Duplicate")

        with pytest.raises(ValueError, match="already registered"):
            catalog.register(spec)

    def test_display_catalog_unregister(self):
        """unregister() удаляет дисплей, возвращает True."""
        catalog = self._make_adapter([_FakeDisplayEntry("d1", "Display 1")])

        result = catalog.unregister("d1")
        assert result is True
        assert catalog.resolve("d1") is None

    def test_display_catalog_unregister_unknown_returns_false(self):
        """unregister() с неизвестным id возвращает False."""
        catalog = self._make_adapter([])
        assert catalog.unregister("unknown") is False

    def test_display_catalog_has(self):
        """has() возвращает True для существующего, False для нет."""
        catalog = self._make_adapter([_FakeDisplayEntry("d1", "Display 1")])
        assert catalog.has("d1") is True
        assert catalog.has("unknown") is False

    def test_display_catalog_persist(self):
        """persist() делегирует registry.persist(yaml_path)."""
        from pathlib import Path

        registry = self._make_registry([_FakeDisplayEntry("d1", "D1")])
        yaml_path = Path("/tmp/test_displays.yaml")
        catalog = DisplayCatalogFromRegistry(registry, yaml_path=yaml_path)  # type: ignore[arg-type]
        catalog.persist()

        assert registry.last_persist_path == yaml_path

    def test_display_catalog_spec_to_entry_roundtrip(self):
        """Round-trip: spec -> entry -> spec сохраняет все поля."""
        from multiprocess_prototype.adapters.catalogs.display_catalog import (
            _entry_to_spec,
            _spec_to_entry,
        )
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        original = DisplaySpec(
            display_id="rt",
            display_name="Round-trip",
            width=1920,
            height=1080,
            format="RGB",
            fps_limit=60.0,
            ring_buffer_blocks=5,
        )
        entry = _spec_to_entry(original)
        back = _entry_to_spec(entry)

        assert back.display_id == original.display_id
        assert back.display_name == original.display_name
        assert back.width == original.width
        assert back.height == original.height
        assert back.format == original.format
        assert back.fps_limit == original.fps_limit
        assert back.ring_buffer_blocks == original.ring_buffer_blocks


# ==============================================================================
# Smoke-тест на реальном PluginRegistry
# ==============================================================================


class TestRealPluginRegistrySmoke:
    """Smoke-тест: реальный PluginRegistry + PluginCatalogFromRegistry."""

    def test_real_plugin_registry_smoke(self):
        """
        Реальный PluginRegistry подключается, adapter возвращает список.

        Если в среде нет зарегистрированных плагинов — test пропускается
        (okружение dev может не иметь плагинов заранее).
        Тест проверяет что adapter корректно оборачивает реестр:
        все возвращённые объекты являются PluginSpec.
        """
        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

        catalog = PluginCatalogFromRegistry(PluginRegistry)
        result = catalog.list_plugins()

        # Всегда tuple
        assert isinstance(result, tuple)

        # Все элементы — PluginSpec
        for spec in result:
            assert isinstance(spec, PluginSpec), f"Ожидался PluginSpec, получен {type(spec)}"
            assert isinstance(spec.name, str)
            assert isinstance(spec.category, str)

        # Если плагины есть — проверяем round-trip
        if result:
            first = result[0]
            resolved = catalog.resolve(first.name)
            assert resolved is not None
            assert resolved.name == first.name
        else:
            pytest.skip("Нет зарегистрированных плагинов в PluginRegistry в текущей среде")

    def test_real_plugin_registry_discover_smoke(self):
        """
        Smoke: discover_plugins из Plugins/ → adapter список не пустой.

        Используем PluginRegistry.discover() для сканирования директории Plugins/.
        """
        import sys
        from pathlib import Path

        from multiprocess_framework.modules.process_module.plugins.registry import (
            _PluginRegistry,
        )

        # Используем изолированный реестр чтобы не загрязнять глобальный
        isolated_registry = _PluginRegistry()

        # Путь к директории Plugins/ относительно корня проекта
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        plugins_dir = project_root / "Plugins"

        if not plugins_dir.exists():
            pytest.skip(f"Директория Plugins/ не найдена: {plugins_dir}")

        # Добавляем корень проекта в sys.path если не добавлен
        project_root_str = str(project_root)
        sys_path_added = False
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
            sys_path_added = True

        try:
            count = isolated_registry.discover(str(plugins_dir))
        finally:
            if sys_path_added and project_root_str in sys.path:
                sys.path.remove(project_root_str)

        catalog = PluginCatalogFromRegistry(isolated_registry)
        result = catalog.list_plugins()

        if count == 0:
            pytest.skip("Plugins/ найдена, но плагины не загрузились (возможно нет зависимостей)")

        assert isinstance(result, tuple)
        assert len(result) > 0, "discover() нашёл плагины, но list_plugins() вернул пустой tuple"

        # Проверяем round-trip для первого плагина
        first = result[0]
        resolved = catalog.resolve(first.name)
        assert resolved is not None
        assert resolved.name == first.name


# ==============================================================================
# Тесты DisplayCatalogFromRecipe (Task 5.1 — recipe-scoped)
# ==============================================================================


class _FakeRecipeStoreForCatalog:
    """Минимальный fake RecipeStore для тестов DisplayCatalogFromRecipe.

    Хранит рецепты in-memory по slug. Поддерживает read/write/get_active.
    """

    def __init__(
        self,
        recipes: dict[str, object] | None = None,
        active_slug: str | None = None,
    ) -> None:
        from multiprocess_prototype.domain.entities.recipe import Recipe

        self._recipes: dict[str, Recipe] = {}
        if recipes:
            for slug, data in recipes.items():
                if isinstance(data, dict):
                    self._recipes[slug] = Recipe.from_dict(data)
                else:
                    self._recipes[slug] = data
        self._active = active_slug

    def read(self, slug: str):
        return self._recipes.get(slug)

    def write(self, slug: str, recipe) -> None:
        self._recipes[slug] = recipe

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str | None) -> bool:
        self._active = slug
        return True


class _FakeRecipeStoreLazyValidate:
    """Fake RecipeStore, валидирующий ``Recipe.from_dict()`` ЛЕНИВО внутри ``read()``.

    В отличие от ``_FakeRecipeStoreForCatalog`` (валидирует на конструкции fixture),
    этот фейк хранит raw dict и парсит его в ``Recipe`` только при вызове ``read()`` —
    как реальный ``RecipeStoreFromManager.read()``. Нужен, чтобы смоделировать
    легаси-рецепт, падающий ``ValidationError`` именно на ``read()`` (RS-5, A-7).
    """

    def __init__(self, raw_by_slug: dict[str, dict], active_slug: str | None = None) -> None:
        self._raw = dict(raw_by_slug)
        self._active = active_slug

    def read(self, slug: str):
        from multiprocess_prototype.domain.entities.recipe import Recipe

        raw = self._raw.get(slug)
        if raw is None:
            return None
        return Recipe.from_dict(raw)

    def write(self, slug: str, recipe) -> None:
        self._raw[slug] = recipe.to_dict()

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str | None) -> bool:
        self._active = slug
        return True


class TestDisplayCatalogFromRecipe:
    """Тесты для DisplayCatalogFromRecipe (Task 5.1 — recipe-scoped persist)."""

    def _make_recipe_data(
        self,
        name: str = "test_recipe",
        displays: list[dict] | None = None,
    ) -> dict:
        """Сформировать минимальный dict рецепта с секцией displays."""
        return {
            "name": name,
            "version": 3,
            "displays": displays or [],
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }

    def _make_catalog(
        self,
        recipe_data: dict | None = None,
        slug: str = "test",
        active: bool = True,
    ):
        """Создать DisplayCatalogFromRecipe с fake store."""
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )

        recipes = {}
        if recipe_data is not None:
            recipes[slug] = recipe_data
        active_slug = slug if active else None
        store = _FakeRecipeStoreForCatalog(recipes=recipes, active_slug=active_slug)
        return DisplayCatalogFromRecipe(
            recipe_store=store,  # type: ignore[arg-type]
            get_active_slug=store.get_active,
        ), store

    # ------------------------------------------------------------------ #
    #  list_displays: из активного рецепта                                 #
    # ------------------------------------------------------------------ #

    def test_list_displays_from_active_recipe(self):
        """list_displays() возвращает дисплеи из активного рецепта."""
        data = self._make_recipe_data(
            displays=[
                {"id": "main", "name": "Основной", "width": 1920, "height": 1080},
                {"id": "debug", "name": "Отладочный"},
            ]
        )
        catalog, _ = self._make_catalog(data)
        result = catalog.list_displays()

        assert len(result) == 2
        ids = {spec.display_id for spec in result}
        assert ids == {"main", "debug"}

    def test_list_displays_no_active_recipe_returns_empty(self):
        """Нет активного рецепта → list_displays() пуст."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data, active=False)
        assert catalog.list_displays() == ()

    def test_list_displays_legacy_recipe_degrades_gracefully(self, caplog):
        """RS-5 (A-7): легаси-рецепт (top-level data:/meta:) не роняет list_displays().

        ``Recipe.from_dict()`` (extra='forbid') бросает ``ValidationError`` на
        рецепте со старыми ключами. Раньше это всплывало необработанным до
        Qt-слота ``DisplaysPresenter.load()`` и ронял вкладку Дисплеи. Теперь —
        мягкая деградация: пустой список + предупреждение в лог модуля.
        """
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "meta": {"legacy_field": "x"},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        with caplog.at_level(logging.WARNING):
            result = catalog.list_displays()

        assert result == ()
        assert any("легаси" in rec.message.lower() for rec in caplog.records)

    def test_resolve_legacy_recipe_degrades_gracefully(self):
        """resolve() тоже деградирует (общий _get_active_displays), не падает."""
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        assert catalog.resolve("main") is None

    def test_list_displays_recipe_without_displays_section(self):
        """Рецепт без displays → пустой tuple."""
        data = self._make_recipe_data(displays=[])
        catalog, _ = self._make_catalog(data)
        assert catalog.list_displays() == ()

    # ------------------------------------------------------------------ #
    #  list_displays: render-поля сохраняются                             #
    # ------------------------------------------------------------------ #

    def test_list_displays_contains_render_fields(self):
        """list_displays() возвращает DisplaySpec с render-полями из определений."""
        data = self._make_recipe_data(
            displays=[
                {
                    "id": "cam1",
                    "name": "Камера 1",
                    "width": 1280,
                    "height": 720,
                    "fit": "cover",
                    "scale": 150,
                    "rotate": 90,
                    "flip": "horizontal",
                    "position": {"x": 100, "y": 200},
                    "crop": {"x": 10, "y": 20, "w": 640, "h": 480},
                }
            ]
        )
        catalog, _ = self._make_catalog(data)
        result = catalog.list_displays()

        assert len(result) == 1
        spec = result[0]
        assert spec.display_id == "cam1"
        assert spec.fit == "cover"
        assert spec.scale == 150
        assert spec.rotate == 90
        assert spec.flip == "horizontal"
        assert spec.position == {"x": 100, "y": 200}
        assert spec.crop == {"x": 10, "y": 20, "w": 640, "h": 480}

    # ------------------------------------------------------------------ #
    #  resolve: из активного рецепта                                      #
    # ------------------------------------------------------------------ #

    def test_resolve_known_display(self):
        """resolve() возвращает DisplaySpec для известного id."""
        data = self._make_recipe_data(
            displays=[
                {"id": "main", "name": "Main", "width": 800},
            ]
        )
        catalog, _ = self._make_catalog(data)
        spec = catalog.resolve("main")

        assert spec is not None
        assert spec.display_id == "main"
        assert spec.display_name == "Main"
        assert spec.width == 800

    def test_resolve_unknown_returns_none(self):
        """resolve() с неизвестным id → None."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data)
        assert catalog.resolve("unknown") is None

    def test_resolve_no_active_recipe_returns_none(self):
        """resolve() без активного рецепта → None."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data, active=False)
        assert catalog.resolve("x") is None

    # ------------------------------------------------------------------ #
    #  register: мутирует активный рецепт                                 #
    # ------------------------------------------------------------------ #

    def test_register_adds_to_recipe_displays(self):
        """register(spec) добавляет DisplayDefinition в recipe.displays и сохраняет."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        data = self._make_recipe_data(displays=[])
        catalog, store = self._make_catalog(data)

        spec = DisplaySpec(
            display_id="new_disp",
            display_name="Новый дисплей",
            width=800,
            height=600,
            fit="stretch",
            scale=200,
            rotate=180,
            flip="both",
            position={"x": 50, "y": 75},
            crop={"x": 0, "y": 0, "w": 400, "h": 300},
        )
        catalog.register(spec)

        # Проверяем, что рецепт обновлён
        recipe = store.read("test")
        assert recipe is not None
        assert len(recipe.displays) == 1
        defn = recipe.displays[0]
        assert defn.id == "new_disp"
        assert defn.name == "Новый дисплей"
        assert defn.width == 800
        assert defn.fit == "stretch"
        assert defn.scale == 200
        assert defn.rotate == 180
        assert defn.flip == "both"
        assert defn.position.x == 50
        assert defn.position.y == 75
        assert defn.crop is not None
        assert defn.crop.w == 400

    def test_register_preserves_existing_displays(self):
        """register() не теряет существующие дисплеи."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        data = self._make_recipe_data(
            displays=[
                {"id": "existing", "name": "Existing"},
            ]
        )
        catalog, store = self._make_catalog(data)

        catalog.register(DisplaySpec(display_id="new", display_name="New"))

        recipe = store.read("test")
        assert recipe is not None
        assert len(recipe.displays) == 2
        ids = {d.id for d in recipe.displays}
        assert ids == {"existing", "new"}

    def test_register_duplicate_raises(self):
        """register() с дубликатом id → ValueError."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        data = self._make_recipe_data(displays=[{"id": "dup", "name": "Dup"}])
        catalog, _ = self._make_catalog(data)

        with pytest.raises(ValueError, match="already registered"):
            catalog.register(DisplaySpec(display_id="dup", display_name="Another"))

    def test_register_no_active_recipe_raises(self):
        """register() без активного рецепта → ValueError."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        data = self._make_recipe_data(displays=[])
        catalog, _ = self._make_catalog(data, active=False)

        with pytest.raises(ValueError, match="Нет активного рецепта"):
            catalog.register(DisplaySpec(display_id="x", display_name="X"))

    def test_register_legacy_recipe_raises_controlled_error(self):
        """RS-5 (A-7, ревью-находка 3): register() на легаси-рецепте не крашит
        необработанным ValidationError — контролируемый ValueError, presenter
        (on_create/on_duplicate) уже ловит ValueError и показывает show_error.
        """
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="не найден или невалиден"):
            catalog.register(DisplaySpec(display_id="x", display_name="X"))

    def test_update_legacy_recipe_returns_false(self):
        """RS-5 (A-7): update() на легаси-рецепте деградирует до False, не падает."""
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        assert catalog.update(DisplaySpec(display_id="x", display_name="X")) is False

    def test_unregister_legacy_recipe_returns_false(self):
        """RS-5 (A-7): unregister() на легаси-рецепте деградирует до False, не падает."""
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        assert catalog.unregister("x") is False

    def test_persist_legacy_recipe_logs_and_noops(self, caplog):
        """RS-5 (A-7): persist() на легаси-рецепте — no-op с warning, не падает."""
        from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import (
            DisplayCatalogFromRecipe,
        )

        legacy_raw = {
            "name": "legacy_recipe",
            "version": 2,
            "data": {"legacy": True},
            "blueprint": {"processes": [], "wires": [], "displays": []},
        }
        store = _FakeRecipeStoreLazyValidate({"legacy_recipe": legacy_raw}, active_slug="legacy_recipe")
        catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=store.get_active)  # type: ignore[arg-type]

        with caplog.at_level(logging.WARNING):
            catalog.persist()  # не должно бросить исключение

        assert any("невалиден" in rec.message.lower() for rec in caplog.records)

    # ------------------------------------------------------------------ #
    #  unregister: удаляет из рецепта                                     #
    # ------------------------------------------------------------------ #

    def test_unregister_removes_from_recipe(self):
        """unregister() удаляет дисплей из recipe.displays."""
        data = self._make_recipe_data(
            displays=[
                {"id": "a", "name": "A"},
                {"id": "b", "name": "B"},
            ]
        )
        catalog, store = self._make_catalog(data)

        result = catalog.unregister("a")
        assert result is True

        recipe = store.read("test")
        assert recipe is not None
        assert len(recipe.displays) == 1
        assert recipe.displays[0].id == "b"

    def test_unregister_unknown_returns_false(self):
        """unregister() с неизвестным id → False."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data)
        assert catalog.unregister("nonexistent") is False

    def test_unregister_no_active_recipe_returns_false(self):
        """unregister() без активного рецепта → False."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data, active=False)
        assert catalog.unregister("x") is False

    # ------------------------------------------------------------------ #
    #  has: проверка наличия                                              #
    # ------------------------------------------------------------------ #

    def test_has_returns_true_for_existing(self):
        """has() → True для существующего дисплея в рецепте."""
        data = self._make_recipe_data(displays=[{"id": "main", "name": "Main"}])
        catalog, _ = self._make_catalog(data)
        assert catalog.has("main") is True

    def test_has_returns_false_for_unknown(self):
        """has() → False для несуществующего."""
        data = self._make_recipe_data(displays=[{"id": "main", "name": "Main"}])
        catalog, _ = self._make_catalog(data)
        assert catalog.has("unknown") is False

    def test_has_no_active_recipe_returns_false(self):
        """has() без активного рецепта → False."""
        data = self._make_recipe_data(displays=[{"id": "x", "name": "X"}])
        catalog, _ = self._make_catalog(data, active=False)
        assert catalog.has("x") is False

    # ------------------------------------------------------------------ #
    #  persist: пишет в файл рецепта, НЕ в displays.yaml                 #
    # ------------------------------------------------------------------ #

    def test_persist_writes_to_recipe_not_yaml(self):
        """persist() вызывает store.write() с текущим рецептом (recipe-scoped)."""
        data = self._make_recipe_data(
            displays=[
                {"id": "d1", "name": "D1", "scale": 120, "fit": "stretch"},
            ]
        )
        catalog, store = self._make_catalog(data)
        catalog.persist()

        # Рецепт на месте и не потерял данные
        recipe = store.read("test")
        assert recipe is not None
        assert len(recipe.displays) == 1
        assert recipe.displays[0].id == "d1"
        assert recipe.displays[0].scale == 120

    def test_persist_no_active_recipe_is_noop(self):
        """persist() без активного рецепта — no-op (не бросает)."""
        data = self._make_recipe_data(displays=[])
        catalog, _ = self._make_catalog(data, active=False)
        # Не бросает исключение
        catalog.persist()

    # ------------------------------------------------------------------ #
    #  DisplaySpec ↔ DisplayDefinition round-trip                         #
    # ------------------------------------------------------------------ #

    def test_spec_to_definition_roundtrip(self):
        """DisplaySpec → dict → DisplayDefinition → DisplaySpec (round-trip render-полей)."""
        from multiprocess_prototype.domain.entities.display import DisplayDefinition
        from multiprocess_prototype.domain.protocols.display_catalog import (
            DisplaySpec,
            definition_to_spec,
            spec_to_definition_dict,
        )

        original = DisplaySpec(
            display_id="rt",
            display_name="Round-trip",
            width=1920,
            height=1080,
            format="RGB",
            fps_limit=60.0,
            ring_buffer_blocks=5,
            position={"x": 42, "y": 99},
            fit="cover",
            scale=200,
            rotate=270,
            flip="vertical",
            crop={"x": 10, "y": 20, "w": 100, "h": 50},
        )

        # Spec → dict → Definition
        d = spec_to_definition_dict(original)
        defn = DisplayDefinition.from_dict(d)

        assert defn.id == "rt"
        assert defn.name == "Round-trip"
        assert defn.width == 1920
        assert defn.fit == "cover"
        assert defn.scale == 200
        assert defn.rotate == 270
        assert defn.flip == "vertical"
        assert defn.position.x == 42
        assert defn.position.y == 99
        assert defn.crop is not None
        assert defn.crop.w == 100

        # Definition → Spec
        back = definition_to_spec(defn)
        assert back.display_id == original.display_id
        assert back.display_name == original.display_name
        assert back.width == original.width
        assert back.format == original.format
        assert back.fit == original.fit
        assert back.scale == original.scale
        assert back.rotate == original.rotate
        assert back.flip == original.flip
        assert back.position == original.position
        assert back.crop == original.crop
        assert back.fps_limit == original.fps_limit
        assert back.ring_buffer_blocks == original.ring_buffer_blocks

    def test_spec_with_crop_none_roundtrip(self):
        """Round-trip с crop=None."""
        from multiprocess_prototype.domain.entities.display import DisplayDefinition
        from multiprocess_prototype.domain.protocols.display_catalog import (
            DisplaySpec,
            definition_to_spec,
            spec_to_definition_dict,
        )

        spec = DisplaySpec(display_id="nocrop", display_name="No Crop", crop=None)
        d = spec_to_definition_dict(spec)
        defn = DisplayDefinition.from_dict(d)
        assert defn.crop is None

        back = definition_to_spec(defn)
        assert back.crop is None

    def test_spec_with_default_position_roundtrip(self):
        """Round-trip с position по умолчанию."""
        from multiprocess_prototype.domain.entities.display import DisplayDefinition
        from multiprocess_prototype.domain.protocols.display_catalog import (
            DisplaySpec,
            definition_to_spec,
            spec_to_definition_dict,
        )

        spec = DisplaySpec(display_id="def", display_name="Defaults")
        d = spec_to_definition_dict(spec)
        defn = DisplayDefinition.from_dict(d)
        assert defn.position.x == 0
        assert defn.position.y == 0
        assert defn.fit == "contain"
        assert defn.scale == 100
        assert defn.rotate == 0
        assert defn.flip == "none"

        back = definition_to_spec(defn)
        assert back.position == {"x": 0, "y": 0}
        assert back.fit == "contain"

    # ------------------------------------------------------------------ #
    #  Protocol compliance                                                #
    # ------------------------------------------------------------------ #

    def test_satisfies_display_catalog_protocol(self):
        """DisplayCatalogFromRecipe удовлетворяет DisplayCatalog Protocol."""

        data = self._make_recipe_data()
        catalog, _ = self._make_catalog(data)
        _check: DisplayCatalog = catalog  # type: ignore[assignment]
        assert _check is catalog
