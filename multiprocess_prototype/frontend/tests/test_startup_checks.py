"""Тесты StartupChecker — валидация topology при старте."""

import pytest
from unittest.mock import MagicMock

from multiprocess_prototype.frontend.startup_checks import (
    StartupChecker,
)


@pytest.fixture
def checker():
    return StartupChecker()


@pytest.fixture
def valid_topology():
    return {
        "name": "test",
        "processes": [
            {
                "process_name": "camera_0",
                "chain_targets": ["gui"],
                "plugins": [{"plugin_name": "camera_service"}],
            },
            {
                "process_name": "gui",
                "plugins": [],
            },
        ],
    }


class TestCheckTopology:
    def test_valid_topology(self, checker, valid_topology):
        """Валидная topology — нет ошибок."""
        issues = checker.check_topology(valid_topology)
        assert issues == []

    def test_empty_topology(self, checker):
        """Пустая topology — ошибка."""
        issues = checker.check_topology({})
        assert len(issues) == 1
        assert "пуста" in issues[0].lower() or "нет процессов" in issues[0].lower()

    def test_duplicate_names(self, checker):
        """Дублирующиеся имена процессов."""
        topo = {
            "processes": [
                {"process_name": "a", "plugins": []},
                {"process_name": "a", "plugins": []},
            ],
        }
        issues = checker.check_topology(topo)
        assert any("дубл" in i.lower() for i in issues)

    def test_invalid_chain_target(self, checker):
        """chain_target ссылается на несуществующий процесс."""
        topo = {
            "processes": [
                {"process_name": "a", "chain_targets": ["nonexistent"], "plugins": []},
            ],
        }
        issues = checker.check_topology(topo)
        assert any("nonexistent" in i for i in issues)

    def test_missing_plugins_field(self, checker):
        """Процесс без поля plugins."""
        topo = {"processes": [{"process_name": "a"}]}
        issues = checker.check_topology(topo)
        assert any("plugins" in i.lower() for i in issues)

    def test_process_without_name(self, checker):
        """Процесс без process_name."""
        topo = {"processes": [{"plugins": []}]}
        issues = checker.check_topology(topo)
        assert any("без process_name" in i.lower() or "без" in i.lower() for i in issues)


class TestCheckPlugins:
    def test_all_plugins_registered(self, checker, valid_topology):
        """Все плагины найдены в registry."""
        registry = MagicMock()
        registry.list_plugins.return_value = ["camera_service"]
        issues = checker.check_plugins(registry, valid_topology)
        assert issues == []

    def test_unknown_plugin(self, checker, valid_topology):
        """Плагин не найден в registry."""
        registry = MagicMock()
        registry.list_plugins.return_value = []
        issues = checker.check_plugins(registry, valid_topology)
        assert any("camera_service" in i for i in issues)


class TestCheckAll:
    def test_ok_report(self, checker, valid_topology):
        """Валидная topology → report.ok == True."""
        report = checker.check_all(valid_topology)
        assert report.ok
        assert report.summary() == ""

    def test_errors_report(self, checker):
        """Невалидная topology → report.ok == False."""
        report = checker.check_all({})
        assert not report.ok
        assert "ошибок" in report.summary().lower() or "ошибок" in report.summary()
