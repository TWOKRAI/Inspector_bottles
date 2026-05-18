"""Тесты для ServicesTab."""

from __future__ import annotations
from unittest.mock import MagicMock
from multiprocess_prototype.frontend.widgets.tabs.services.tab import ServicesTab
from multiprocess_prototype.frontend.widgets.tabs.services.presenter import ServicesPresenter


class _MockEntry:
    def __init__(self, name, category):
        self.name = name
        self.category = category


class _MockFieldInfo:
    """Минимальный mock для FieldInfo."""

    def __init__(self, plugin_name, field_name, field_type=int, default=0):
        self.plugin_name = plugin_name
        self.field_name = field_name
        self.field_type = field_type
        self.default = default
        self.meta = None
        self.category = "default"

    @property
    def title(self):
        return self.field_name

    @property
    def min_value(self):
        return None

    @property
    def max_value(self):
        return None

    @property
    def unit(self):
        return ""


class _MockRegistry:
    def __init__(self, entries):
        self._entries = entries

    def get(self, name):
        return next((e for e in self._entries if e.name == name), None)

    def list(self):
        return self._entries


class _MockRM:
    def __init__(self, fields_map):
        self._fields_map = fields_map

    def get_fields(self, plugin_name):
        return self._fields_map.get(plugin_name, [])


def _make_mock_ctx(with_fields=True):
    entries = [
        _MockEntry("database", "output"),
        _MockEntry("robot_control", "service"),
    ]
    registry = _MockRegistry(entries)

    fields_map = {}
    if with_fields:
        fields_map = {
            "database": [_MockFieldInfo("database", "db_path", str, "/data/db")],
            "robot_control": [_MockFieldInfo("robot_control", "enabled", bool, False)],
        }
    rm = _MockRM(fields_map)

    ctx = MagicMock()
    ctx.plugin_registry.return_value = registry
    ctx.registers_manager.return_value = rm
    ctx.config = {}
    ctx.extras = {}
    ctx.bindings.return_value = None
    # form_context() должен возвращать None в тестах — тогда RegisterView использует
    # legacy путь (без binding-aware builders, которые требуют реального ActionBus).
    ctx.form_context.return_value = None
    return ctx


class TestServicesPresenter:
    def test_get_service_sections(self):
        ctx = _make_mock_ctx()
        p = ServicesPresenter(ctx)
        sections = p.get_service_sections()
        # database и robot_control существуют в реестре и имеют поля
        assert len(sections) >= 2
        titles = [s[0] for s in sections]
        assert "База данных" in titles
        assert "Управление роботом" in titles

    def test_no_fields(self):
        ctx = _make_mock_ctx(with_fields=False)
        p = ServicesPresenter(ctx)
        sections = p.get_service_sections()
        # Нет полей — секции не создаются
        assert len(sections) == 0

    def test_no_registry(self):
        ctx = MagicMock()
        ctx.plugin_registry.return_value = None
        ctx.registers_manager.return_value = None
        p = ServicesPresenter(ctx)
        sections = p.get_service_sections()
        assert len(sections) == 0


class TestServicesTab:
    def test_create(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ServicesTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_nn_placeholder_always_present(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)
        # Секция "Нейронные сети" всегда есть (+2 сервисных = 3 итого)
        assert tab._side_nav.section_count() >= 1  # минимум placeholder

    def test_empty_services(self, qtbot):
        ctx = MagicMock()
        ctx.plugin_registry.return_value = None
        ctx.registers_manager.return_value = None
        ctx.config = {}
        ctx.extras = {}
        ctx.bindings.return_value = None
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)
        # Только placeholder нейронок
        assert tab._side_nav.section_count() == 1

    def test_sections_with_fields(self, qtbot):
        ctx = _make_mock_ctx()
        tab = ServicesTab(ctx)
        qtbot.addWidget(tab)
        # 2 сервисных секции + 1 нейронки
        assert tab._side_nav.section_count() == 3
