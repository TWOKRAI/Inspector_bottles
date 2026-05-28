# -*- coding: utf-8 -*-
"""
adapters/tests/test_catalogs.py — тесты для catalog адаптеров.

Покрываемые классы:
    - PluginCatalogFromRegistry  (plugin_catalog.py)
    - ServiceManagerFromRegistry (service_catalog.py) — read + lifecycle
    - ServiceCatalogFromRegistry — backward-compatible alias
    - DisplayCatalogFromRegistry (display_catalog.py)

Паттерн:
    Fake*Registry — plain Python classes (не MagicMock),
    в соответствии с decision Phase B (_fakes.py).
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginCatalog, PluginSpec
from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.service_catalog import ServiceCatalog, ServiceManager
from multiprocess_prototype.domain.protocols.display_catalog import DisplayCatalog

from multiprocess_prototype.adapters.catalogs import (
    PluginCatalogFromRegistry,
    ServiceCatalogFromRegistry,
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
    """Имитация DisplayRegistry с фиксированным набором дисплеев."""

    def __init__(self, entries: list[_FakeDisplayEntry]) -> None:
        self._entries = {e.id: e for e in entries}

    def list(self) -> list[_FakeDisplayEntry]:
        return list(self._entries.values())

    def get(self, display_id: str) -> _FakeDisplayEntry | None:
        return self._entries.get(display_id)


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
# Тесты ServiceCatalogFromRegistry
# ==============================================================================


class TestServiceCatalogFromRegistry:
    """Тесты для ServiceCatalogFromRegistry."""

    def _make_registry(self, entries: list[_FakeServiceEntry] | None = None) -> _FakeServiceRegistry:
        return _FakeServiceRegistry(entries or [])

    def _make_adapter(self, entries: list[_FakeServiceEntry] | None = None) -> ServiceCatalogFromRegistry:
        return ServiceCatalogFromRegistry(self._make_registry(entries))  # type: ignore[arg-type]

    def test_service_catalog_lists_known_services(self):
        """Фейковый реестр с 2 сервисами → list_services() возвращает 2 ServiceSpec."""
        entries = [
            _FakeServiceEntry("webcam_camera", "WebcamCameraService"),
            _FakeServiceEntry("hikvision", "HikvisionCameraService"),
        ]
        catalog = self._make_adapter(entries)
        result = catalog.list_services()

        assert len(result) == 2
        ids = {spec.service_id for spec in result}
        assert ids == {"webcam_camera", "hikvision"}

    def test_service_catalog_returns_tuple(self):
        """list_services() возвращает tuple (не list)."""
        entries = [_FakeServiceEntry("svc1", "Svc1")]
        catalog = self._make_adapter(entries)
        assert isinstance(catalog.list_services(), tuple)

    def test_service_catalog_resolve_known_service(self):
        """resolve() с известным service_id возвращает ServiceSpec."""
        entries = [_FakeServiceEntry("webcam_camera", "WebcamCameraService", meta={"vendor": "opencv"})]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("webcam_camera")

        assert spec is not None
        assert spec.service_id == "webcam_camera"

    def test_service_catalog_resolve_unknown_returns_none(self):
        """resolve() с неизвестным id возвращает None."""
        catalog = self._make_adapter([])
        assert catalog.resolve("no_such_service") is None

    def test_service_catalog_resolve_roundtrip(self):
        """Round-trip: entry.name == catalog.resolve(entry.name).service_id."""
        entry = _FakeServiceEntry("my_service", "MyService")
        catalog = self._make_adapter([entry])
        resolved = catalog.resolve(entry.name)
        assert resolved is not None
        assert entry.name == resolved.service_id

    def test_service_catalog_metadata_preserved(self):
        """Метаданные из entry.meta попадают в spec.metadata."""
        entries = [_FakeServiceEntry("svc", "Svc", meta={"vendor": "opencv", "version": "1.0"})]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("svc")

        assert spec is not None
        assert spec.metadata.get("vendor") == "opencv"
        assert spec.metadata.get("version") == "1.0"

    def test_service_catalog_with_empty_registry_returns_empty(self):
        """Пустой реестр → list_services() возвращает пустой tuple."""
        catalog = self._make_adapter([])
        assert catalog.list_services() == ()

    def test_service_catalog_satisfies_protocol(self):
        """Adapter удовлетворяет ServiceCatalog Protocol (assignment-проверка)."""
        catalog = self._make_adapter([])
        _protocol_check: ServiceCatalog = catalog  # type: ignore[assignment]
        assert _protocol_check is catalog

    def test_service_catalog_spec_is_frozen(self):
        """ServiceSpec заморожен — попытка изменить атрибут вызывает ошибку."""
        entries = [_FakeServiceEntry("svc", "Svc")]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("svc")
        assert spec is not None

        with pytest.raises((AttributeError, TypeError)):
            spec.service_id = "changed"  # type: ignore[misc]


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

    def test_service_catalog_alias_works(self):
        """Backward-compat: ServiceCatalogFromRegistry alias работает как ServiceManager."""
        entries = [_FakeServiceEntry("svc1", "Svc1")]
        registry = self._make_registry(entries)
        # Используем alias ServiceCatalogFromRegistry
        adapter = ServiceCatalogFromRegistry(registry)  # type: ignore[arg-type]
        assert adapter.list_services() is not None
        _protocol_check: ServiceCatalog = adapter  # type: ignore[assignment]
        assert _protocol_check is adapter

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

    def test_display_catalog_metadata_contains_dimensions(self):
        """Метаданные содержат width, height, format, fps_limit, ring_buffer_blocks."""
        entries = [
            _FakeDisplayEntry(
                "main", "Main", width=1280, height=720, format="BGR", fps_limit=30.0, ring_buffer_blocks=3
            )
        ]
        catalog = self._make_adapter(entries)
        spec = catalog.resolve("main")

        assert spec is not None
        assert spec.metadata["width"] == 1280
        assert spec.metadata["height"] == 720
        assert spec.metadata["format"] == "BGR"
        assert spec.metadata["fps_limit"] == 30.0
        assert spec.metadata["ring_buffer_blocks"] == 3

    def test_display_catalog_with_empty_registry_returns_empty(self):
        """Пустой реестр → list_displays() возвращает пустой tuple."""
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
