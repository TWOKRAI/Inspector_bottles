"""Тесты для ServicesTab (Task 3.6 — ServiceRegistry-based; Task 3.7 — lifecycle actions)."""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_prototype.frontend.widgets.tabs.services.presenter import ServicesPresenter
from multiprocess_prototype.frontend.widgets.tabs.services.tab import ServicesTab


# ---------------------------------------------------------------------------
# Вспомогательные классы-заглушки
# ---------------------------------------------------------------------------


class _MockServiceEntry:
    """Минимальный mock для ServiceEntry."""

    def __init__(self, name: str, title: str | None = None, cls: type | None = None):
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        self.name = name
        self.lifecycle = ServiceLifecycle.READY
        self.meta = {"title": title} if title else {}
        # cls используется presenter'ом для инстанцирования
        self.cls = cls


class _MockServiceRegistry:
    """Mock ServiceRegistry с фиксированным списком сервисов."""

    def __init__(self, entries: list[_MockServiceEntry]) -> None:
        self._entries = entries

    def list(self) -> list[_MockServiceEntry]:
        return list(self._entries)

    def get(self, name: str) -> _MockServiceEntry | None:
        return next((e for e in self._entries if e.name == name), None)


def _make_mock_ctx(
    service_entries: list[_MockServiceEntry] | None = None,
    registry_is_none: bool = False,
) -> MagicMock:
    """Собрать mock AppContext для тестов ServicesTab."""
    ctx = MagicMock()
    ctx.config = {}
    ctx.extras = {}
    ctx.bindings.return_value = None
    ctx.action_bus.return_value = None
    ctx.form_context.return_value = None

    if registry_is_none:
        ctx.service_registry.return_value = None
    else:
        entries = service_entries or []
        ctx.service_registry.return_value = _MockServiceRegistry(entries)

    return ctx


# ---------------------------------------------------------------------------
# Тесты ServicesPresenter
# ---------------------------------------------------------------------------


class TestServicesPresenter:
    def test_list_services_returns_tuples(self):
        """list_services() возвращает список (name, title, lifecycle)."""
        entries = [
            _MockServiceEntry("sql", "База данных"),
            _MockServiceEntry("webcam_camera"),
        ]
        ctx = _make_mock_ctx(entries)
        p = ServicesPresenter(ctx)
        result = p.list_services()

        assert len(result) == 2
        names = [r[0] for r in result]
        assert "sql" in names
        assert "webcam_camera" in names

    def test_list_services_uses_meta_title(self):
        """list_services() использует meta['title'] если есть."""
        entries = [_MockServiceEntry("sql", "База данных")]
        ctx = _make_mock_ctx(entries)
        p = ServicesPresenter(ctx)
        result = p.list_services()

        assert result[0][1] == "База данных"

    def test_list_services_generates_title_from_name(self):
        """list_services() генерирует title из name если meta['title'] нет."""
        entries = [_MockServiceEntry("webcam_camera")]
        ctx = _make_mock_ctx(entries)
        p = ServicesPresenter(ctx)
        result = p.list_services()

        # "webcam_camera" → "Webcam Camera"
        assert result[0][1] == "Webcam Camera"

    def test_list_services_none_registry_returns_empty(self):
        """list_services() возвращает [] если registry не инициализирован."""
        ctx = _make_mock_ctx(registry_is_none=True)
        p = ServicesPresenter(ctx)
        result = p.list_services()

        assert result == []


# ---------------------------------------------------------------------------
# Тесты ServicesTab
# ---------------------------------------------------------------------------


class TestServicesTab:
    def test_create(self, qtbot):
        """ServicesTab.create() создаёт экземпляр без ошибок."""
        ctx = _make_mock_ctx([_MockServiceEntry("sql")])
        tab = ServicesTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_tab_shows_all_services_from_registry(self, qtbot):
        """Tab показывает секции для каждого сервиса из registry (3 сервиса)."""
        entries = [
            _MockServiceEntry("sql"),
            _MockServiceEntry("webcam_camera"),
            _MockServiceEntry("hikvision_camera"),
        ]
        ctx = _make_mock_ctx(entries)
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        # services_root + 3 сервиса + neural_networks + __service_paths__
        assert "services_root" in keys
        assert "sql" in keys
        assert "webcam_camera" in keys
        assert "hikvision_camera" in keys

    def test_tab_handles_none_registry(self, qtbot):
        """Tab пустой без ошибок если service_registry() → None."""
        ctx = _make_mock_ctx(registry_is_none=True)
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        # Без сервисов: только neural_networks + __service_paths__
        assert "services_root" not in keys
        assert "neural_networks" in keys
        assert "__service_paths__" in keys

    def test_paths_subtab_appears_in_nav(self, qtbot):
        """Секция __service_paths__ присутствует в дереве навигации."""
        ctx = _make_mock_ctx([])
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "__service_paths__" in keys

    def test_neural_networks_always_present(self, qtbot):
        """Секция «Нейронные сети» всегда присутствует."""
        ctx = _make_mock_ctx(registry_is_none=True)
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "neural_networks" in keys

    def test_sections_structure_with_services(self, qtbot):
        """Корректная структура секций: root → дочерние → neural_networks → paths."""
        entries = [
            _MockServiceEntry("sql"),
            _MockServiceEntry("auth"),
        ]
        ctx = _make_mock_ctx(entries)
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        # services_root должен быть первым
        assert keys[0] == "services_root"
        # neural_networks перед __service_paths__
        nn_idx = keys.index("neural_networks")
        paths_idx = keys.index("__service_paths__")
        assert nn_idx < paths_idx

    def test_empty_registry_structure(self, qtbot):
        """Без сервисов: services_root отсутствует, только placeholders."""
        ctx = _make_mock_ctx([])
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        assert len(tab._sections_specs) == 2
        keys = [s.key for s in tab._sections_specs]
        assert "neural_networks" in keys
        assert "__service_paths__" in keys

    def test_paths_subtab_signal_triggers_refresh(self, qtbot):
        """catalog_updated от paths_subtab → tab вызывает refresh (rebuild sections)."""
        entries = [_MockServiceEntry("sql")]
        ctx = _make_mock_ctx(entries)
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)

        # Имитируем emit catalog_updated вызовом refresh_catalog напрямую
        # (paths_subtab ещё не построен lazy, поэтому тестируем метод напрямую)
        tab.refresh_catalog()
        after_count = len(tab._sections_specs)

        # После refresh секции перестроены (количество не должно упасть)
        assert after_count >= 1
        keys = [s.key for s in tab._sections_specs]
        assert "__service_paths__" in keys


# ---------------------------------------------------------------------------
# Тесты ServicesPresenter — lifecycle actions (Task 3.7)
# ---------------------------------------------------------------------------


class _FakeService:
    """Простой сервис для unit-тестов presenter (не реальный IService)."""

    name: str = "fake_service"

    def __init__(self):
        self.started_with: list[dict] = []
        self.stop_called: int = 0
        self._start_result = True
        self._stop_result = True
        self._should_raise_on_start = False
        self._should_raise_on_stop = False

    def start(self, config: dict) -> bool:
        if self._should_raise_on_start:
            raise RuntimeError("Тестовое исключение в start()")
        self.started_with.append(config)
        return self._start_result

    def stop(self) -> bool:
        if self._should_raise_on_stop:
            raise RuntimeError("Тестовое исключение в stop()")
        self.stop_called += 1
        return self._stop_result

    def get_status(self) -> dict:
        return {"name": self.name}


def _make_entry_with_cls(name: str, cls: type) -> "_MockServiceEntry":
    """Создать mock-запись с реальным cls для инстанцирования."""
    from multiprocess_framework.modules.service_module import ServiceLifecycle

    entry = _MockServiceEntry(name)
    entry.cls = cls
    entry.lifecycle = ServiceLifecycle.READY
    return entry


class TestServicesPresenterLifecycle:
    """Тесты методов start/stop/restart/get_lifecycle (Task 3.7)."""

    def test_start_service_calls_start_and_sets_running(self):
        """start_service("foo") → instance.start({}) вызван → lifecycle == RUNNING → True."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        fake_cls = _FakeService
        entry = _make_entry_with_cls("foo", fake_cls)
        registry = _MockServiceRegistry([entry])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        result = presenter.start_service("foo")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.RUNNING
        # Экземпляр закешировался
        assert "foo" in presenter._instances
        instance = presenter._instances["foo"]
        assert len(instance.started_with) == 1
        assert instance.started_with[0] == {}

    def test_stop_service_calls_stop_and_sets_stopped(self):
        """После start → stop_service() → instance.stop() вызван → lifecycle == STOPPED."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        entry = _make_entry_with_cls("bar", _FakeService)
        registry = _MockServiceRegistry([entry])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        presenter.start_service("bar")
        result = presenter.stop_service("bar")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.STOPPED
        assert presenter._instances["bar"].stop_called == 1

    def test_restart_service_calls_stop_then_start(self):
        """restart_service() → stop() + start() подряд, lifecycle == RUNNING."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        entry = _make_entry_with_cls("baz", _FakeService)
        registry = _MockServiceRegistry([entry])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        presenter.start_service("baz")  # первый запуск

        result = presenter.restart_service("baz")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.RUNNING
        instance = presenter._instances["baz"]
        # stop() вызван один раз (при restart), start() вызван дважды (init + restart)
        assert instance.stop_called == 1
        assert len(instance.started_with) == 2

    def test_start_unknown_service_returns_false(self):
        """start_service("nonexistent") → False, без исключений."""
        registry = _MockServiceRegistry([])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        result = presenter.start_service("nonexistent")

        assert result is False

    def test_start_exception_marks_error_lifecycle(self):
        """Если instance.start() поднимает исключение → lifecycle == ERROR, return False."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        class _RaisingService(_FakeService):
            name: str = "bad_service"

            def start(self, config: dict) -> bool:
                raise RuntimeError("Ошибка инициализации")

        entry = _make_entry_with_cls("bad_service", _RaisingService)
        registry = _MockServiceRegistry([entry])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        result = presenter.start_service("bad_service")

        assert result is False
        assert entry.lifecycle == ServiceLifecycle.ERROR

    def test_start_with_none_registry_returns_false(self):
        """start_service при registry=None → False, нет краша."""
        ctx = MagicMock()
        ctx.service_registry.return_value = None

        presenter = ServicesPresenter(ctx)
        result = presenter.start_service("anything")

        assert result is False

    def test_get_lifecycle_returns_current_value(self):
        """get_lifecycle() читает lifecycle прямо из registry entry."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        entry = _make_entry_with_cls("svc", _FakeService)
        entry.lifecycle = ServiceLifecycle.RUNNING
        registry = _MockServiceRegistry([entry])
        ctx = MagicMock()
        ctx.service_registry.return_value = registry

        presenter = ServicesPresenter(ctx)
        lc = presenter.get_lifecycle("svc")

        assert lc == ServiceLifecycle.RUNNING

    def test_get_lifecycle_none_registry_returns_none(self):
        """get_lifecycle() при registry=None → None."""
        ctx = MagicMock()
        ctx.service_registry.return_value = None

        presenter = ServicesPresenter(ctx)
        assert presenter.get_lifecycle("anything") is None


# ---------------------------------------------------------------------------
# Тесты _ServiceSection — кнопки и статус-лейбл (Task 3.7)
# ---------------------------------------------------------------------------


class TestServiceSection:
    """Тесты UI-секции сервиса: кнопки enabled/disabled + статус-лейбл."""

    def _make_section(self, qtbot, lifecycle=None, start_result: bool = True):
        """Вспомогательный метод: создать _ServiceSection с mock-presenter."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        if lifecycle is None:
            lifecycle = ServiceLifecycle.READY

        ctx = MagicMock()
        ctx.auth = None

        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = lifecycle
        mock_presenter.start_service.return_value = start_result
        mock_presenter.stop_service.return_value = True
        mock_presenter.restart_service.return_value = start_result

        section = _ServiceSection(ctx, "test_svc", "Test Service", lifecycle, mock_presenter)
        # Инициализируем widget и buttons
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        return section, mock_presenter

    def test_button_start_enabled_when_ready(self, qtbot):
        """Кнопка «Запустить» enabled при lifecycle=READY, «Остановить» disabled."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        section, _ = self._make_section(qtbot, ServiceLifecycle.READY)

        assert section._btn_start is not None
        assert section._btn_stop is not None
        assert section._btn_start.isEnabled() is True
        assert section._btn_stop.isEnabled() is False

    def test_button_start_disabled_when_running(self, qtbot):
        """После start: «Запустить» disabled, «Остановить» enabled."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        section, mock_presenter = self._make_section(qtbot, ServiceLifecycle.READY)

        # Симулируем переход в RUNNING после клика start
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.RUNNING
        section._on_start_click()

        assert section._btn_start is not None
        assert section._btn_stop is not None
        assert section._btn_start.isEnabled() is False
        assert section._btn_stop.isEnabled() is True

    def test_button_restart_enabled_when_error(self, qtbot):
        """«Перезапуск» enabled при lifecycle=ERROR."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        section, mock_presenter = self._make_section(qtbot, ServiceLifecycle.ERROR)
        # get_lifecycle должен вернуть ERROR при проверке
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.ERROR
        section._refresh_button_state(ServiceLifecycle.ERROR)

        assert section._btn_restart is not None
        assert section._btn_restart.isEnabled() is True

    def test_status_label_updates_after_start_click(self, qtbot):
        """Клик «Запустить» → статус-лейбл обновляется на 'running'."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        ctx = MagicMock()
        ctx.auth = None

        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.READY
        mock_presenter.start_service.return_value = True

        section = _ServiceSection(ctx, "test_svc", "Test", ServiceLifecycle.READY, mock_presenter)
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        # Переключаем lifecycle на RUNNING перед refresh
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.RUNNING
        section._on_start_click()

        # Проверяем статус-лейбл через objectName
        from PySide6.QtWidgets import QLabel

        status_label = widget.findChild(QLabel, "service_status_test_svc")
        assert status_label is not None
        assert "running" in status_label.text()

    def test_section_no_crash_when_registry_none(self, qtbot):
        """Клик на кнопку при registry=None → нет краша, lifecycle не обновляется."""
        from multiprocess_framework.modules.service_module import ServiceLifecycle
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        ctx = MagicMock()
        ctx.auth = None

        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = None  # registry=None
        mock_presenter.start_service.return_value = False

        section = _ServiceSection(ctx, "test_svc", "Test", ServiceLifecycle.READY, mock_presenter)
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        # Не должно быть исключений
        section._on_start_click()
        section._on_stop_click()
        section._on_restart_click()
