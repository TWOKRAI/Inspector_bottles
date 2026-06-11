"""Тесты для ServicesTab (Task 3.6/3.7; Task E.4 — AppServices DI).

Presenter делегирует lifecycle в services.services (ServiceManagerFromRegistry).
Builder make_services_services() строит AppServices с реальным адаптером над
stub-реестром — тестирует настоящий Protocol-путь.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_framework.modules.service_module import ServiceLifecycle

from multiprocess_prototype.frontend.widgets.tabs.services.presenter import ServicesPresenter
from multiprocess_prototype.frontend.widgets.tabs.services.tab import ServicesTab

from ._helpers import (
    _FakeService,
    _StubServiceEntry,
    make_services_services,
)


# ---------------------------------------------------------------------------
# Тесты ServicesPresenter — list_services
# ---------------------------------------------------------------------------


class TestServicesPresenter:
    def test_list_services_returns_tuples(self):
        """list_services() возвращает список (name, title, lifecycle)."""
        services = make_services_services(
            entries=[_StubServiceEntry("sql", "База данных"), _StubServiceEntry("webcam_camera")]
        )
        p = ServicesPresenter(services)
        result = p.list_services()

        assert len(result) == 2
        names = [r[0] for r in result]
        assert "sql" in names
        assert "webcam_camera" in names

    def test_list_services_uses_meta_title(self):
        """list_services() использует metadata['title'] если есть."""
        services = make_services_services(entries=[_StubServiceEntry("sql", "База данных")])
        p = ServicesPresenter(services)
        result = p.list_services()

        assert result[0][1] == "База данных"

    def test_list_services_generates_title_from_name(self):
        """list_services() генерирует title из name если metadata['title'] нет."""
        services = make_services_services(entries=[_StubServiceEntry("webcam_camera")])
        p = ServicesPresenter(services)
        result = p.list_services()

        # "webcam_camera" → "Webcam Camera"
        assert result[0][1] == "Webcam Camera"

    def test_list_services_empty_returns_empty(self):
        """list_services() возвращает [] если сервисов нет."""
        p = ServicesPresenter(make_services_services(entries=[]))
        assert p.list_services() == []


# ---------------------------------------------------------------------------
# Тесты ServicesTab
# ---------------------------------------------------------------------------


class TestServicesTab:
    def test_create(self, qtbot):
        """ServicesTab.create() создаёт экземпляр без ошибок."""
        services = make_services_services(entries=[_StubServiceEntry("sql")])
        tab = ServicesTab.create(services)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_tab_shows_all_services_from_registry(self, qtbot):
        """Tab показывает секции для каждого сервиса из registry (3 сервиса)."""
        services = make_services_services(
            entries=[
                _StubServiceEntry("sql"),
                _StubServiceEntry("webcam_camera"),
                _StubServiceEntry("hikvision_camera"),
            ]
        )
        tab = ServicesTab(services)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "services_root" in keys
        assert "sql" in keys
        assert "webcam_camera" in keys
        # hikvision_camera намеренно скрыт из авто-списка: у него полноценная
        # секция «Hikvision Camera» в группе «Камеры» (см. _sections.py).
        assert "hikvision_camera" not in keys
        assert "__hikvision__" in keys

    def test_tab_handles_empty_registry(self, qtbot):
        """Tab пустой без ошибок если сервисов нет."""
        tab = ServicesTab(make_services_services(entries=[]))
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        # Без сервисов: только neural_networks + __service_paths__
        assert "services_root" not in keys
        assert "neural_networks" in keys
        assert "__service_paths__" in keys

    def test_paths_subtab_appears_in_nav(self, qtbot):
        """Секция __service_paths__ присутствует в дереве навигации."""
        tab = ServicesTab(make_services_services(entries=[]))
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "__service_paths__" in keys

    def test_neural_networks_always_present(self, qtbot):
        """Секция «Нейронные сети» всегда присутствует."""
        tab = ServicesTab(make_services_services(entries=[]))
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "neural_networks" in keys

    def test_sections_structure_with_services(self, qtbot):
        """Корректная структура секций: root → дочерние → neural_networks → paths."""
        services = make_services_services(entries=[_StubServiceEntry("sql"), _StubServiceEntry("auth")])
        tab = ServicesTab(services)
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert keys[0] == "services_root"
        nn_idx = keys.index("neural_networks")
        paths_idx = keys.index("__service_paths__")
        assert nn_idx < paths_idx

    def test_empty_registry_structure(self, qtbot):
        """Без сервисов: services_root отсутствует, только placeholders + камера."""
        tab = ServicesTab(make_services_services(entries=[]))
        qtbot.addWidget(tab)

        keys = [s.key for s in tab._sections_specs]
        assert "services_root" not in keys
        assert "__camera__" in keys
        assert "neural_networks" in keys
        assert "__service_paths__" in keys

    def test_paths_subtab_signal_triggers_refresh(self, qtbot):
        """refresh_catalog() перестраивает секции."""
        services = make_services_services(entries=[_StubServiceEntry("sql")])
        tab = ServicesTab(services)
        qtbot.addWidget(tab)

        tab.refresh_catalog()
        after_count = len(tab._sections_specs)

        assert after_count >= 1
        keys = [s.key for s in tab._sections_specs]
        assert "__service_paths__" in keys


# ---------------------------------------------------------------------------
# Тесты ServicesPresenter — lifecycle actions (делегирование в ServiceManager)
# ---------------------------------------------------------------------------


class TestServicesPresenterLifecycle:
    """Lifecycle делегируется в services.services (ServiceManagerFromRegistry).

    Кэш экземпляров и мутация entry.lifecycle живут в адаптере
    (services.services._instances), не в presenter.
    """

    def test_start_service_calls_start_and_sets_running(self):
        """start_service("foo") → instance.start({}) → entry.lifecycle == RUNNING → True."""
        entry = _StubServiceEntry("foo", cls=_FakeService)
        services = make_services_services(entries=[entry])
        presenter = ServicesPresenter(services)

        result = presenter.start_service("foo")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.RUNNING
        # Экземпляр закеширован в адаптере
        instance = services.services._instances["foo"]
        assert len(instance.started_with) == 1
        assert instance.started_with[0] == {}

    def test_stop_service_calls_stop_and_sets_stopped(self):
        """После start → stop_service() → instance.stop() → entry.lifecycle == STOPPED."""
        entry = _StubServiceEntry("bar", cls=_FakeService)
        services = make_services_services(entries=[entry])
        presenter = ServicesPresenter(services)

        presenter.start_service("bar")
        result = presenter.stop_service("bar")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.STOPPED
        assert services.services._instances["bar"].stop_called == 1

    def test_restart_service_calls_stop_then_start(self):
        """restart_service() → stop() + start() подряд, lifecycle == RUNNING."""
        entry = _StubServiceEntry("baz", cls=_FakeService)
        services = make_services_services(entries=[entry])
        presenter = ServicesPresenter(services)

        presenter.start_service("baz")  # первый запуск
        result = presenter.restart_service("baz")

        assert result is True
        assert entry.lifecycle == ServiceLifecycle.RUNNING
        instance = services.services._instances["baz"]
        # stop() вызван один раз (при restart), start() — дважды (init + restart)
        assert instance.stop_called == 1
        assert len(instance.started_with) == 2

    def test_start_unknown_service_returns_false(self):
        """start_service("nonexistent") → False (DomainError проглочен), без исключений."""
        presenter = ServicesPresenter(make_services_services(entries=[]))
        assert presenter.start_service("nonexistent") is False

    def test_start_exception_marks_error_lifecycle(self):
        """Если instance.start() поднимает исключение → entry.lifecycle == ERROR, return False."""

        class _RaisingService(_FakeService):
            name: str = "bad_service"

            def start(self, config: dict) -> bool:
                raise RuntimeError("Ошибка инициализации")

        entry = _StubServiceEntry("bad_service", cls=_RaisingService)
        services = make_services_services(entries=[entry])
        presenter = ServicesPresenter(services)

        result = presenter.start_service("bad_service")

        assert result is False
        assert entry.lifecycle == ServiceLifecycle.ERROR

    def test_get_lifecycle_returns_current_value(self):
        """get_lifecycle() читает lifecycle через ServiceManager Protocol."""
        entry = _StubServiceEntry("svc", cls=_FakeService)
        entry.lifecycle = ServiceLifecycle.RUNNING
        services = make_services_services(entries=[entry])
        presenter = ServicesPresenter(services)

        assert presenter.get_lifecycle("svc") == ServiceLifecycle.RUNNING

    def test_get_lifecycle_unknown_returns_none(self):
        """get_lifecycle() для неизвестного сервиса → None (DomainError проглочен)."""
        presenter = ServicesPresenter(make_services_services(entries=[]))
        assert presenter.get_lifecycle("anything") is None


# ---------------------------------------------------------------------------
# Тесты _ServiceSection — кнопки и статус-лейбл (Task 3.7)
# ---------------------------------------------------------------------------


class TestServiceSection:
    """Тесты UI-секции сервиса: кнопки enabled/disabled + статус-лейбл."""

    def _make_section(self, qtbot, lifecycle=None, start_result: bool = True):
        """Создать _ServiceSection с mock-presenter (presenter мокается, services реальны)."""
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        if lifecycle is None:
            lifecycle = ServiceLifecycle.READY

        services = make_services_services(entries=[])

        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = lifecycle
        mock_presenter.start_service.return_value = start_result
        mock_presenter.stop_service.return_value = True
        mock_presenter.restart_service.return_value = start_result

        section = _ServiceSection(services, "test_svc", "Test Service", lifecycle, mock_presenter)
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        return section, mock_presenter

    def test_button_start_enabled_when_ready(self, qtbot):
        """Кнопка «Запустить» enabled при lifecycle=READY, «Остановить» disabled."""
        section, _ = self._make_section(qtbot, ServiceLifecycle.READY)

        assert section._btn_start is not None
        assert section._btn_stop is not None
        assert section._btn_start.isEnabled() is True
        assert section._btn_stop.isEnabled() is False

    def test_button_start_disabled_when_running(self, qtbot):
        """После start: «Запустить» disabled, «Остановить» enabled."""
        section, mock_presenter = self._make_section(qtbot, ServiceLifecycle.READY)

        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.RUNNING
        section._on_start_click()

        assert section._btn_start is not None
        assert section._btn_stop is not None
        assert section._btn_start.isEnabled() is False
        assert section._btn_stop.isEnabled() is True

    def test_button_restart_enabled_when_error(self, qtbot):
        """«Перезапуск» enabled при lifecycle=ERROR."""
        section, mock_presenter = self._make_section(qtbot, ServiceLifecycle.ERROR)
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.ERROR
        section._refresh_button_state(ServiceLifecycle.ERROR)

        assert section._btn_restart is not None
        assert section._btn_restart.isEnabled() is True

    def test_status_label_updates_after_start_click(self, qtbot):
        """Клик «Запустить» → статус-лейбл обновляется на 'running'."""
        from PySide6.QtWidgets import QLabel
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        services = make_services_services(entries=[])
        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.READY
        mock_presenter.start_service.return_value = True

        section = _ServiceSection(services, "test_svc", "Test", ServiceLifecycle.READY, mock_presenter)
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        mock_presenter.get_lifecycle.return_value = ServiceLifecycle.RUNNING
        section._on_start_click()

        status_label = widget.findChild(QLabel, "service_status_test_svc")
        assert status_label is not None
        assert "running" in status_label.text()

    def test_section_no_crash_when_lifecycle_none(self, qtbot):
        """Клик на кнопку при get_lifecycle()=None → нет краша."""
        from multiprocess_prototype.frontend.widgets.tabs.services._sections import _ServiceSection

        services = make_services_services(entries=[])
        mock_presenter = MagicMock(spec=ServicesPresenter)
        mock_presenter.get_lifecycle.return_value = None
        mock_presenter.start_service.return_value = False

        section = _ServiceSection(services, "test_svc", "Test", ServiceLifecycle.READY, mock_presenter)
        widget = section.widget()
        qtbot.addWidget(widget)
        _ = section.action_buttons()

        # Не должно быть исключений
        section._on_start_click()
        section._on_stop_click()
        section._on_restart_click()
