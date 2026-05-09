"""Тесты TopologyBridge — единый мост GUI ↔ Runtime.

Pure Python, без Qt. Тестируем:
- on_field_set: happy path, stateless skip, validation fail, debounce
- on_action_command: happy path, fail
- on_state_delta: rm sync
- lifecycle: start/stop/restart
- on_topology_changed: кэш очистка
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from multiprocess_prototype_2.frontend.bridge.topology_bridge import TopologyBridge


# --- Mock-объекты (детали конструктора) ---


@dataclass(frozen=True)
class MockResolvedCommand:
    process_name: str
    command_name: str
    plugin_name: str


@dataclass(frozen=True)
class MockValidationResult:
    ok: bool
    error: str | None = None

    @staticmethod
    def success() -> MockValidationResult:
        return MockValidationResult(ok=True)

    @staticmethod
    def fail(error: str) -> MockValidationResult:
        return MockValidationResult(ok=False, error=error)


@dataclass
class MockFieldInfo:
    field_name: str = ""
    name: str = ""
    field_type: type = int
    min_value: float | None = None
    max_value: float | None = None


class MockCatalog:
    """Мок CommandCatalog."""

    def __init__(
        self,
        field_resolves: dict[tuple[str, str], MockResolvedCommand | None] | None = None,
        action_resolves: dict[tuple[str, str], MockResolvedCommand | None] | None = None,
        plugins: dict[str, Any] | None = None,
    ) -> None:
        self._field_resolves = field_resolves or {}
        self._action_resolves = action_resolves or {}
        self._plugins = plugins or {}

    def resolve_field_command(self, plugin_name: str, field_name: str) -> MockResolvedCommand | None:
        return self._field_resolves.get((plugin_name, field_name))

    def resolve_action_command(self, plugin_name: str, command_name: str) -> MockResolvedCommand | None:
        return self._action_resolves.get((plugin_name, command_name))

    def get_plugin(self, plugin_name: str) -> Any | None:
        return self._plugins.get(plugin_name)


class MockValidator:
    """Мок CommandValidator."""

    def __init__(
        self,
        field_results: dict[str, MockValidationResult] | None = None,
        action_results: dict[str, MockValidationResult] | None = None,
    ) -> None:
        self._field_results = field_results or {}
        self._action_results = action_results or {}
        self._default = MockValidationResult.success()

    def validate_field_command(self, plugin_name: str, field_name: str, value: Any) -> MockValidationResult:
        key = f"{plugin_name}.{field_name}"
        return self._field_results.get(key, self._default)

    def validate_action_command(self, plugin_name: str, command_name: str) -> MockValidationResult:
        key = f"{plugin_name}.{command_name}"
        return self._action_results.get(key, self._default)


class MockSender:
    """Мок CommandSender — записывает все отправленные команды."""

    def __init__(self) -> None:
        self.field_commands: list[tuple[str, str, dict, int]] = []
        self.action_commands: list[tuple[str, str, dict | None]] = []
        self.commands: list[tuple[str, str, dict | None]] = []

    def send_field_command(
        self, target_process: str, command: str, args: dict[str, Any], *, debounce_ms: int = 0
    ) -> None:
        self.field_commands.append((target_process, command, args, debounce_ms))

    def send_action_command(
        self, target_process: str, command: str, args: dict[str, Any] | None = None
    ) -> None:
        self.action_commands.append((target_process, command, args))

    def send_command(
        self, target_process: str, command: str, args: dict[str, Any] | None = None
    ) -> None:
        self.commands.append((target_process, command, args))


class MockRegistersManager:
    """Мок RegistersManager — записывает set_value вызовы."""

    def __init__(self, fields: dict[str, list[MockFieldInfo]] | None = None) -> None:
        self._fields = fields or {}
        self.set_calls: list[tuple[str, str, Any]] = []

    def get_fields(self, plugin_name: str) -> list[MockFieldInfo]:
        return self._fields.get(plugin_name, [])

    def set_value(self, plugin_name: str, field_name: str, value: Any) -> bool:
        self.set_calls.append((plugin_name, field_name, value))
        return True


class MockTopologyHolder:
    """Мок TopologyHolder."""

    def __init__(self, topology: dict[str, Any] | None = None) -> None:
        self._topology = topology or {"processes": []}

    @property
    def topology(self) -> dict[str, Any]:
        return self._topology


# --- Fixtures ---


@pytest.fixture
def sender() -> MockSender:
    return MockSender()


@pytest.fixture
def catalog() -> MockCatalog:
    return MockCatalog(
        field_resolves={
            ("color_mask", "h_min"): MockResolvedCommand("processor_0", "set_hsv_range", "color_mask"),
            ("color_mask", "h_max"): MockResolvedCommand("processor_0", "set_hsv_range", "color_mask"),
            # grayscale — нет resolves (stateless)
        },
        action_resolves={
            ("capture", "start_capture"): MockResolvedCommand("camera_0", "start_capture", "capture"),
            ("capture", "stop_capture"): MockResolvedCommand("camera_0", "stop_capture", "capture"),
        },
    )


@pytest.fixture
def validator() -> MockValidator:
    return MockValidator()


@pytest.fixture
def rm() -> MockRegistersManager:
    return MockRegistersManager(
        fields={
            "color_mask": [
                MockFieldInfo(field_name="h_min", name="h_min", field_type=int, min_value=0, max_value=180),
                MockFieldInfo(field_name="h_max", name="h_max", field_type=int, min_value=0, max_value=180),
            ],
        }
    )


@pytest.fixture
def holder() -> MockTopologyHolder:
    return MockTopologyHolder({
        "processes": [
            {"process_name": "camera_0", "plugins": [{"plugin_name": "capture"}]},
            {"process_name": "processor_0", "plugins": [{"plugin_name": "color_mask"}]},
        ]
    })


@pytest.fixture
def bridge(
    sender: MockSender,
    catalog: MockCatalog,
    validator: MockValidator,
    rm: MockRegistersManager,
    holder: MockTopologyHolder,
) -> TopologyBridge:
    return TopologyBridge(sender, catalog, validator, rm, holder)


# --- Тесты on_field_set ---


class TestOnFieldSet:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """field_set → resolve → validate → send_field_command."""
        ok = bridge.on_field_set("color_mask", "h_min", 50)
        assert ok is True
        assert len(sender.field_commands) == 1
        target, cmd, args, debounce = sender.field_commands[0]
        assert target == "processor_0"
        assert cmd == "set_hsv_range"
        assert args == {"h_min": 50}

    def test_stateless_skip(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Stateless плагин (нет resolve) → return True, не отправлять."""
        ok = bridge.on_field_set("grayscale", "any_field", 1)
        assert ok is True
        assert len(sender.field_commands) == 0

    def test_validation_fail(
        self, sender: MockSender, catalog: MockCatalog, rm: MockRegistersManager, holder: MockTopologyHolder
    ) -> None:
        """Валидация не прошла → return False, не отправлять."""
        validator = MockValidator(
            field_results={"color_mask.h_min": MockValidationResult.fail("bad value")}
        )
        bridge = TopologyBridge(sender, catalog, validator, rm, holder)

        ok = bridge.on_field_set("color_mask", "h_min", -1)
        assert ok is False
        assert len(sender.field_commands) == 0

    def test_nonexistent_plugin(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Плагин не в каталоге → stateless path, return True."""
        ok = bridge.on_field_set("nonexistent", "field", 1)
        assert ok is True
        assert len(sender.field_commands) == 0

    def test_debounce_for_slider_field(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Числовое поле с min/max → debounce 50ms."""
        bridge.on_field_set("color_mask", "h_min", 50)
        _, _, _, debounce = sender.field_commands[0]
        assert debounce == 50

    def test_no_debounce_for_non_slider(
        self, sender: MockSender, validator: MockValidator, holder: MockTopologyHolder
    ) -> None:
        """Поле без min/max → debounce 0."""
        catalog = MockCatalog(
            field_resolves={
                ("my_plugin", "name"): MockResolvedCommand("proc", "set_config", "my_plugin"),
            }
        )
        rm = MockRegistersManager(
            fields={
                "my_plugin": [
                    MockFieldInfo(field_name="name", name="name", field_type=str),
                ],
            }
        )
        bridge = TopologyBridge(sender, catalog, validator, rm, holder)

        bridge.on_field_set("my_plugin", "name", "test")
        _, _, _, debounce = sender.field_commands[0]
        assert debounce == 0


# --- Тесты on_action_command ---


class TestOnActionCommand:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Action → validate → resolve → send."""
        ok = bridge.on_action_command("capture", "start_capture")
        assert ok is True
        assert len(sender.action_commands) == 1
        target, cmd, args = sender.action_commands[0]
        assert target == "camera_0"
        assert cmd == "start_capture"

    def test_with_args(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Action с аргументами."""
        ok = bridge.on_action_command("capture", "start_capture", {"device_id": 0})
        assert ok is True
        _, _, args = sender.action_commands[0]
        assert args == {"device_id": 0}

    def test_validation_fail(
        self, sender: MockSender, catalog: MockCatalog, rm: MockRegistersManager, holder: MockTopologyHolder
    ) -> None:
        """Валидация action не прошла → return False."""
        validator = MockValidator(
            action_results={"capture.bad_cmd": MockValidationResult.fail("unknown")}
        )
        bridge = TopologyBridge(sender, catalog, validator, rm, holder)

        ok = bridge.on_action_command("capture", "bad_cmd")
        assert ok is False
        assert len(sender.action_commands) == 0

    def test_no_resolve(
        self, sender: MockSender, validator: MockValidator, rm: MockRegistersManager, holder: MockTopologyHolder
    ) -> None:
        """Команда не в resolve → False (валидация пройдёт но resolve None)."""
        catalog = MockCatalog(action_resolves={})
        bridge = TopologyBridge(sender, catalog, validator, rm, holder)

        ok = bridge.on_action_command("capture", "start_capture")
        assert ok is False


# --- Тесты on_state_delta ---


class TestOnStateDelta:

    def test_config_path_updates_rm(self, bridge: TopologyBridge, rm: MockRegistersManager) -> None:
        """state_delta processes.X.config.field → rm.set_value."""
        bridge.on_state_delta("processes.color_mask.config.h_min", 100)
        assert len(rm.set_calls) == 1
        plugin, field, value = rm.set_calls[0]
        assert plugin == "color_mask"
        assert field == "h_min"
        assert value == 100

    def test_state_path_ignored(self, bridge: TopologyBridge, rm: MockRegistersManager) -> None:
        """state_delta processes.X.state.fps → не обновлять rm."""
        bridge.on_state_delta("processes.camera_0.state.fps", 30)
        assert len(rm.set_calls) == 0

    def test_system_path_ignored(self, bridge: TopologyBridge, rm: MockRegistersManager) -> None:
        """system.* path → не обновлять rm."""
        bridge.on_state_delta("system.fps", 25)
        assert len(rm.set_calls) == 0

    def test_short_path_ignored(self, bridge: TopologyBridge, rm: MockRegistersManager) -> None:
        """Слишком короткий path → игнорировать."""
        bridge.on_state_delta("processes.x", 1)
        assert len(rm.set_calls) == 0


# --- Тесты lifecycle ---


class TestLifecycle:

    def test_start_process(self, bridge: TopologyBridge, sender: MockSender) -> None:
        ok = bridge.start_process("camera_0")
        assert ok is True
        assert len(sender.commands) == 1
        target, cmd, _ = sender.commands[0]
        assert target == "camera_0"
        assert cmd == "process.start"

    def test_stop_process(self, bridge: TopologyBridge, sender: MockSender) -> None:
        ok = bridge.stop_process("processor_0")
        assert ok is True
        assert sender.commands[0][1] == "process.stop"

    def test_restart_process(self, bridge: TopologyBridge, sender: MockSender) -> None:
        ok = bridge.restart_process("camera_0")
        assert ok is True
        assert sender.commands[0][1] == "process.restart"

    def test_nonexistent_process(self, bridge: TopologyBridge, sender: MockSender) -> None:
        ok = bridge.start_process("nonexistent")
        assert ok is False
        assert len(sender.commands) == 0


# --- Тесты topology_changed ---


class TestTopologyChanged:

    def test_clears_slider_cache(self, bridge: TopologyBridge) -> None:
        """on_topology_changed очищает кэш slider-полей."""
        # Заполнить кэш
        bridge._slider_fields["color_mask"] = {"h_min"}
        bridge.on_topology_changed({"processes": []})
        assert bridge._slider_fields == {}

    def test_rebuild_catalog(self, bridge: TopologyBridge) -> None:
        """rebuild_catalog заменяет каталог."""
        new_catalog = MockCatalog()
        bridge.rebuild_catalog(new_catalog)
        assert bridge._catalog is new_catalog
        assert bridge._slider_fields == {}


# --- Properties ---


class TestProperties:

    def test_is_connected_default(self, bridge: TopologyBridge) -> None:
        assert bridge.is_connected is True
