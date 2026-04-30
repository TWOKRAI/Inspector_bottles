"""Тесты для поля plugins в ProcessDefinition и validate_refs() SystemTopology.

Запускать из корня проекта:
    python -m pytest multiprocess_prototype/registers/system_topology/tests/test_schemas_plugins.py -v
"""

import pytest

from multiprocess_prototype.registers.system_topology.schemas import (
    ProcessDefinition,
    SystemTopology,
)


# ---------------------------------------------------------------------------
# ProcessDefinition: поле plugins
# ---------------------------------------------------------------------------


class TestProcessDefinitionPlugins:
    """Проверка поля plugins в ProcessDefinition."""

    def test_plugins_default_empty(self):
        """По умолчанию plugins — пустой список."""
        proc = ProcessDefinition(name="cam")
        assert proc.plugins == []

    def test_plugins_model_dump_contains_key(self):
        """model_dump() содержит ключ plugins."""
        proc = ProcessDefinition(
            name="cam",
            plugins=[{"plugin_class": "SomeClass", "plugin_name": "capture", "category": "source"}],
        )
        dumped = proc.model_dump()
        assert "plugins" in dumped
        assert len(dumped["plugins"]) == 1
        assert dumped["plugins"][0]["plugin_name"] == "capture"

    def test_plugins_model_validate(self):
        """model_validate парсит plugins корректно."""
        data = {
            "name": "cam",
            "plugins": [
                {"plugin_class": "Foo", "plugin_name": "step1"},
                {"plugin_class": "Bar", "plugin_name": "step2"},
            ],
        }
        proc = ProcessDefinition.model_validate(data)
        assert len(proc.plugins) == 2
        assert proc.plugins[0]["plugin_name"] == "step1"
        assert proc.plugins[1]["plugin_class"] == "Bar"

    def test_plugin_names_returns_list(self):
        """plugin_names() возвращает список plugin_name в порядке цепочки."""
        proc = ProcessDefinition(
            name="proc",
            plugins=[
                {"plugin_class": "A", "plugin_name": "alpha"},
                {"plugin_class": "B", "plugin_name": "beta"},
            ],
        )
        assert proc.plugin_names() == ["alpha", "beta"]

    def test_plugin_names_empty(self):
        """plugin_names() при пустом plugins возвращает пустой список."""
        proc = ProcessDefinition(name="proc")
        assert proc.plugin_names() == []

    def test_plugin_names_missing_plugin_name(self):
        """plugin_names() при отсутствии plugin_name возвращает пустую строку."""
        proc = ProcessDefinition(
            name="proc",
            plugins=[{"plugin_class": "A"}],  # нет plugin_name
        )
        assert proc.plugin_names() == [""]


# ---------------------------------------------------------------------------
# validate_refs: проверка plugins
# ---------------------------------------------------------------------------


class TestValidateRefsPlugins:
    """Проверка validate_refs() на корректность plugins."""

    def _make_topology(self, plugins: list) -> SystemTopology:
        """Хелпер: топология с одним процессом и заданными plugins."""
        return SystemTopology(
            processes={
                "proc_0": ProcessDefinition(name="proc_0", plugins=plugins)
            }
        )

    def test_empty_plugins_valid(self):
        """Пустой plugins=[] — валидно (legacy процессы)."""
        topo = self._make_topology([])
        errors = topo.validate_refs()
        assert errors == []

    def test_valid_plugins_no_errors(self):
        """Валидные plugins (есть plugin_class и plugin_name) — нет ошибок."""
        topo = self._make_topology([
            {"plugin_class": "path.to.CapturePlugin", "plugin_name": "capture"},
            {"plugin_class": "path.to.FilterPlugin", "plugin_name": "filter"},
        ])
        errors = topo.validate_refs()
        assert errors == []

    def test_plugin_missing_plugin_class(self):
        """validate_refs ловит dict без plugin_class."""
        topo = self._make_topology([
            {"plugin_name": "capture"}  # нет plugin_class
        ])
        errors = topo.validate_refs()
        assert len(errors) == 1
        assert "plugin_class" in errors[0]
        assert "proc_0" in errors[0]

    def test_plugin_missing_plugin_name(self):
        """validate_refs ловит dict без plugin_name."""
        topo = self._make_topology([
            {"plugin_class": "path.to.CapturePlugin"}  # нет plugin_name
        ])
        errors = topo.validate_refs()
        assert len(errors) == 1
        assert "plugin_name" in errors[0]
        assert "proc_0" in errors[0]

    def test_plugin_missing_both_keys(self):
        """validate_refs ловит dict без обоих обязательных ключей."""
        topo = self._make_topology([
            {"category": "source"}  # нет plugin_class и plugin_name
        ])
        errors = topo.validate_refs()
        assert len(errors) == 1
        assert "plugin_class" in errors[0]
        assert "plugin_name" in errors[0]

    def test_duplicate_plugin_name_error(self):
        """validate_refs ловит дублирующийся plugin_name внутри одного процесса."""
        topo = self._make_topology([
            {"plugin_class": "A", "plugin_name": "capture"},
            {"plugin_class": "B", "plugin_name": "capture"},  # дубль
        ])
        errors = topo.validate_refs()
        assert len(errors) == 1
        assert "дублирующийся" in errors[0]
        assert "capture" in errors[0]
        assert "proc_0" in errors[0]

    def test_multiple_processes_independent(self):
        """Одинаковый plugin_name в разных процессах — допустимо."""
        topo = SystemTopology(
            processes={
                "proc_0": ProcessDefinition(
                    name="proc_0",
                    plugins=[{"plugin_class": "A", "plugin_name": "capture"}],
                ),
                "proc_1": ProcessDefinition(
                    name="proc_1",
                    plugins=[{"plugin_class": "B", "plugin_name": "capture"}],  # другой процесс
                ),
            }
        )
        errors = topo.validate_refs()
        assert errors == []

    def test_plugin_error_reports_index(self):
        """Ошибка включает индекс проблемного плагина."""
        topo = self._make_topology([
            {"plugin_class": "A", "plugin_name": "ok"},
            {"category": "broken"},  # plugin[1] — без обязательных ключей
        ])
        errors = topo.validate_refs()
        assert len(errors) == 1
        assert "plugin[1]" in errors[0]
