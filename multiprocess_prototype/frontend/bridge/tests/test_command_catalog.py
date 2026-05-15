"""Тесты CommandCatalog — каталог IPC-команд из плагинов.

Pure Python, без Qt. Тестируем:
- Построение каталога из mock registry + connection_map
- resolve_field_command: точное совпадение, convention, stateless
- resolve_action_command: явные команды
- Инспекция: list, filter, contains
- Edge cases: плагин не в topology, пустой registry
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from multiprocess_prototype.frontend.bridge.command_catalog import (
    CommandCatalog,
)


# --- Mock-объекты (детали конструктора для тестов) ---


@dataclass
class MockPluginClass:
    """Мок класса плагина с commands dict."""

    commands: dict[str, str] = field(default_factory=dict)


@dataclass
class MockRegisterClass:
    """Мок register-класса с model_fields (как Pydantic)."""

    model_fields: dict[str, object] = field(default_factory=dict)


@dataclass
class MockPluginEntry:
    """Мок PluginEntry из PluginRegistry."""

    name: str
    plugin_class: MockPluginClass
    category: str = ""
    register_classes: list = field(default_factory=list)


class MockRegistry:
    """Мок PluginRegistry — реализует IPluginRegistry Protocol."""

    def __init__(self, entries: list[MockPluginEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def list(self) -> list[MockPluginEntry]:
        return list(self._entries.values())

    def get(self, name: str) -> MockPluginEntry | None:
        return self._entries.get(name)


class MockConnectionMap:
    """Мок ConnectionMap — реализует IConnectionMap Protocol."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = mapping

    def get_process(self, plugin_name: str) -> str | None:
        return self._map.get(plugin_name)

    def plugins(self) -> list[str]:
        return list(self._map.keys())


# --- Fixtures ---


@pytest.fixture
def color_mask_entry() -> MockPluginEntry:
    """Плагин с командой set_hsv_range и register_class."""
    reg_cls = MockRegisterClass(model_fields={"h_min": ..., "h_max": ..., "s_min": ...})
    return MockPluginEntry(
        name="color_mask",
        plugin_class=MockPluginClass(commands={"set_hsv_range": "set_hsv_range"}),
        category="processing",
        register_classes=[reg_cls],
    )


@pytest.fixture
def capture_entry() -> MockPluginEntry:
    """Плагин с несколькими action-командами."""
    return MockPluginEntry(
        name="capture",
        plugin_class=MockPluginClass(
            commands={
                "start_capture": "cmd_start_capture",
                "stop_capture": "cmd_stop_capture",
            }
        ),
        category="source",
    )


@pytest.fixture
def grayscale_entry() -> MockPluginEntry:
    """Stateless плагин — commands пуст."""
    return MockPluginEntry(
        name="grayscale",
        plugin_class=MockPluginClass(commands={}),
        category="processing",
    )


@pytest.fixture
def orphan_entry() -> MockPluginEntry:
    """Плагин, которого нет в topology (нет в connection_map)."""
    return MockPluginEntry(
        name="orphan_plugin",
        plugin_class=MockPluginClass(commands={"do_thing": "do_thing"}),
        category="utility",
    )


@pytest.fixture
def catalog(
    color_mask_entry: MockPluginEntry,
    capture_entry: MockPluginEntry,
    grayscale_entry: MockPluginEntry,
    orphan_entry: MockPluginEntry,
) -> CommandCatalog:
    """Каталог из 3 плагинов в topology + 1 orphan (не в topology)."""
    registry = MockRegistry([color_mask_entry, capture_entry, grayscale_entry, orphan_entry])
    cmap = MockConnectionMap(
        {
            "color_mask": "processor_0",
            "capture": "camera_0",
            "grayscale": "processor_0",
            # orphan_plugin НЕ в маппинге
        }
    )
    return CommandCatalog.from_registry_and_map(registry, cmap)


# --- Тесты построения каталога ---


class TestCatalogBuilding:
    """Построение каталога из registry + connection_map."""

    def test_builds_from_registry_and_map(self, catalog: CommandCatalog) -> None:
        """Каталог содержит только плагины из topology."""
        assert len(catalog) == 3
        assert "color_mask" in catalog
        assert "capture" in catalog
        assert "grayscale" in catalog

    def test_orphan_plugin_excluded(self, catalog: CommandCatalog) -> None:
        """Плагин без процесса в topology — не попадает в каталог."""
        assert "orphan_plugin" not in catalog

    def test_plugin_commands_stored(self, catalog: CommandCatalog) -> None:
        """commands dict сохраняется в PluginCommands.

        Каталог дополнительно автодобавляет generic set_config, если у
        плагина есть register_class — зеркалит runtime-авторегистрацию
        из ProcessModulePlugin._auto_register_commands.
        """
        pc = catalog.get_plugin("color_mask")
        assert pc is not None
        assert pc.commands == {
            "set_hsv_range": "set_hsv_range",
            "set_config": "cmd_set_config",
        }
        assert pc.process_name == "processor_0"
        assert pc.category == "processing"

    def test_register_fields_extracted(self, catalog: CommandCatalog) -> None:
        """Имена полей из register_class.model_fields сохраняются."""
        pc = catalog.get_plugin("color_mask")
        assert pc is not None
        assert set(pc.register_fields) == {"h_min", "h_max", "s_min"}

    def test_stateless_plugin_no_commands(self, catalog: CommandCatalog) -> None:
        """Stateless плагин: commands пуст, has_commands = False."""
        pc = catalog.get_plugin("grayscale")
        assert pc is not None
        assert not pc.has_commands
        assert pc.commands == {}

    def test_empty_registry(self) -> None:
        """Пустой registry → пустой каталог."""
        catalog = CommandCatalog.from_registry_and_map(
            MockRegistry([]),
            MockConnectionMap({}),
        )
        assert len(catalog) == 0

    def test_empty_topology(self, color_mask_entry: MockPluginEntry) -> None:
        """Плагины есть, но topology пуст → пустой каталог."""
        catalog = CommandCatalog.from_registry_and_map(
            MockRegistry([color_mask_entry]),
            MockConnectionMap({}),
        )
        assert len(catalog) == 0


# --- Тесты resolve_field_command ---


class TestResolveFieldCommand:
    """resolve_field_command: (plugin, field) → ResolvedCommand | None."""

    def test_exact_match(self, catalog: CommandCatalog) -> None:
        """Точное совпадение: set_hsv_range в commands."""
        result = catalog.resolve_field_command("color_mask", "hsv_range")
        assert result is not None
        assert result.process_name == "processor_0"
        assert result.command_name == "set_hsv_range"
        assert result.plugin_name == "color_mask"

    def test_convention_fallback(self, catalog: CommandCatalog) -> None:
        """Нет точного совпадения, но commands не пуст → set_config."""
        result = catalog.resolve_field_command("color_mask", "unknown_field")
        assert result is not None
        assert result.command_name == "set_config"
        assert result.process_name == "processor_0"

    def test_stateless_returns_none(self, catalog: CommandCatalog) -> None:
        """Stateless плагин (commands пуст) → None."""
        result = catalog.resolve_field_command("grayscale", "any_field")
        assert result is None

    def test_nonexistent_plugin_returns_none(self, catalog: CommandCatalog) -> None:
        """Несуществующий плагин → None."""
        result = catalog.resolve_field_command("nonexistent", "field")
        assert result is None

    def test_orphan_plugin_returns_none(self, catalog: CommandCatalog) -> None:
        """Плагин не в topology (orphan) → None."""
        result = catalog.resolve_field_command("orphan_plugin", "field")
        assert result is None


# --- Тесты resolve_action_command ---


class TestResolveActionCommand:
    """resolve_action_command: (plugin, command_name) → ResolvedCommand | None."""

    def test_existing_action(self, catalog: CommandCatalog) -> None:
        """Команда есть в commands dict."""
        result = catalog.resolve_action_command("capture", "start_capture")
        assert result is not None
        assert result.process_name == "camera_0"
        assert result.command_name == "start_capture"
        assert result.plugin_name == "capture"

    def test_another_action(self, catalog: CommandCatalog) -> None:
        """Другая команда того же плагина."""
        result = catalog.resolve_action_command("capture", "stop_capture")
        assert result is not None
        assert result.command_name == "stop_capture"

    def test_nonexistent_action(self, catalog: CommandCatalog) -> None:
        """Команда не существует у плагина → None."""
        result = catalog.resolve_action_command("capture", "nonexistent_cmd")
        assert result is None

    def test_nonexistent_plugin_action(self, catalog: CommandCatalog) -> None:
        """Плагин не найден → None."""
        result = catalog.resolve_action_command("nonexistent", "start")
        assert result is None

    def test_stateless_plugin_action(self, catalog: CommandCatalog) -> None:
        """Stateless плагин, любая action → None."""
        result = catalog.resolve_action_command("grayscale", "anything")
        assert result is None


# --- Тесты инспекции ---


class TestInspection:
    """Методы инспекции каталога."""

    def test_all_plugins(self, catalog: CommandCatalog) -> None:
        """all_plugins() — все плагины в каталоге."""
        names = catalog.all_plugins()
        assert set(names) == {"color_mask", "capture", "grayscale"}

    def test_plugins_with_commands(self, catalog: CommandCatalog) -> None:
        """plugins_with_commands() — только плагины с командами."""
        names = catalog.plugins_with_commands()
        assert set(names) == {"color_mask", "capture"}

    def test_plugins_without_commands(self, catalog: CommandCatalog) -> None:
        """plugins_without_commands() — stateless плагины."""
        names = catalog.plugins_without_commands()
        assert names == ["grayscale"]

    def test_list_commands(self, catalog: CommandCatalog) -> None:
        """list_commands() — имена команд конкретного плагина."""
        cmds = catalog.list_commands("capture")
        assert set(cmds) == {"start_capture", "stop_capture"}

    def test_list_commands_empty(self, catalog: CommandCatalog) -> None:
        """list_commands() для stateless → пустой список."""
        assert catalog.list_commands("grayscale") == []

    def test_list_commands_nonexistent(self, catalog: CommandCatalog) -> None:
        """list_commands() для несуществующего → пустой список."""
        assert catalog.list_commands("nonexistent") == []

    def test_contains(self, catalog: CommandCatalog) -> None:
        """Оператор in."""
        assert "color_mask" in catalog
        assert "nonexistent" not in catalog


# --- Тест двух плагинов с одинаковой командой в разных процессах ---


class TestSameCommandDifferentProcesses:
    """Два плагина с одинаковым command_name в разных процессах."""

    def test_resolve_returns_correct_process(self) -> None:
        """Каждый resolve возвращает правильный process_name."""
        entry_a = MockPluginEntry(
            name="plugin_a",
            plugin_class=MockPluginClass(commands={"set_config": "set_config"}),
            category="processing",
        )
        entry_b = MockPluginEntry(
            name="plugin_b",
            plugin_class=MockPluginClass(commands={"set_config": "set_config"}),
            category="processing",
        )

        catalog = CommandCatalog.from_registry_and_map(
            MockRegistry([entry_a, entry_b]),
            MockConnectionMap({"plugin_a": "process_1", "plugin_b": "process_2"}),
        )

        result_a = catalog.resolve_action_command("plugin_a", "set_config")
        result_b = catalog.resolve_action_command("plugin_b", "set_config")

        assert result_a is not None
        assert result_a.process_name == "process_1"
        assert result_b is not None
        assert result_b.process_name == "process_2"
