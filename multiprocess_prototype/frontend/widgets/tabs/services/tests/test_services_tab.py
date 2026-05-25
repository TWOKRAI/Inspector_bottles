"""Тесты для ServicesTab (Task 3.6 — ServiceRegistry-based)."""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_prototype.frontend.widgets.tabs.services.presenter import ServicesPresenter
from multiprocess_prototype.frontend.widgets.tabs.services.tab import ServicesTab


# ---------------------------------------------------------------------------
# Вспомогательные классы-заглушки
# ---------------------------------------------------------------------------


class _MockServiceEntry:
    """Минимальный mock для ServiceEntry."""

    def __init__(self, name: str, title: str | None = None):
        from multiprocess_framework.modules.service_module import ServiceLifecycle

        self.name = name
        self.lifecycle = ServiceLifecycle.READY
        self.meta = {"title": title} if title else {}


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
