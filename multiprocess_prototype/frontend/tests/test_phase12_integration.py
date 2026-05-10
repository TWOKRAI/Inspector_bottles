"""Интеграционные тесты Phase 12 — TopologyBridge pipeline.

Проверяем полный цикл: field_set → ActionBus → FieldSetHandler → bridge → sender.
Без Qt event loop — mock всех внешних зависимостей.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from multiprocess_prototype.frontend.bridge.command_catalog import CommandCatalog
from multiprocess_prototype.frontend.bridge.command_validator import CommandValidator
from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
from multiprocess_prototype.frontend.actions.bus_factory import create_action_bus


# --- Mock-объекты ---


class MockProcess:
    name = "gui"
    sent: list[tuple[str, dict]] = []

    def send_message(self, target: str, msg: dict) -> None:
        MockProcess.sent.append((target, msg))


@dataclass
class MockPluginClass:
    commands: dict[str, str] = field(default_factory=dict)


@dataclass
class MockRegisterClass:
    model_fields: dict[str, object] = field(default_factory=dict)


@dataclass
class MockPluginEntry:
    name: str
    plugin_class: MockPluginClass
    category: str = ""
    register_classes: list = field(default_factory=list)


class MockRegistry:
    def __init__(self, entries: list[MockPluginEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def list(self) -> list[MockPluginEntry]:
        return list(self._entries.values())

    def get(self, name: str) -> MockPluginEntry | None:
        return self._entries.get(name)


class MockConnectionMap:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = mapping

    def get_process(self, plugin_name: str) -> str | None:
        return self._map.get(plugin_name)

    def plugins(self) -> list[str]:
        return list(self._map.keys())


class MockTopologyHolder:
    def __init__(self, topology: dict | None = None) -> None:
        self._topology = topology or {"processes": []}
        self._callbacks: list = []

    @property
    def topology(self) -> dict:
        return self._topology

    def set_topology(self, new: dict) -> dict:
        old = self._topology
        self._topology = new
        return old

    def on_changed(self, cb) -> None:
        self._callbacks.append(cb)

    def remove_callback(self, cb) -> None:
        self._callbacks.remove(cb)


@dataclass
class SimpleFieldInfo:
    name: str
    field_name: str = ""
    field_type: type = int
    min_value: float | None = None
    max_value: float | None = None

    def __post_init__(self):
        if not self.field_name:
            self.field_name = self.name


class SimpleRM:
    """Простой RegistersManager-мок для ActionBus."""

    def __init__(self, fields: dict[str, list] | None = None) -> None:
        self._values: dict[str, dict[str, Any]] = {}
        self._fields: dict[str, list] = fields or {}

    def set_field_value(self, reg: str, field: str, val: Any) -> tuple[bool, str | None]:
        self._values.setdefault(reg, {})[field] = val
        return True, None

    def get_fields(self, plugin_name: str) -> list:
        return self._fields.get(plugin_name, [])

    def validate(self, plugin_name: str, field_name: str, value: Any) -> tuple[bool, str | None]:
        return True, None

    def set_value(self, plugin_name: str, field_name: str, value: Any) -> bool:
        self._values.setdefault(plugin_name, {})[field_name] = value
        return True

    # ActionBus compat
    def register_names(self) -> list[str]:
        return list(self._values.keys())

    def get_register(self, name: str) -> Any:
        return self._values.get(name)


# --- Fixtures ---


@pytest.fixture(autouse=True)
def _clear_mock_process():
    MockProcess.sent = []
    yield


@pytest.fixture
def topology() -> dict:
    return {
        "processes": [
            {"process_name": "camera_0", "plugins": [{"plugin_name": "capture"}]},
            {"process_name": "processor_0", "plugins": [{"plugin_name": "color_mask"}]},
        ]
    }


@pytest.fixture
def registry() -> MockRegistry:
    reg_cls = MockRegisterClass(model_fields={"h_min": ..., "h_max": ...})
    return MockRegistry([
        MockPluginEntry(
            name="color_mask",
            plugin_class=MockPluginClass(commands={"set_hsv_range": "set_hsv_range"}),
            category="processing",
            register_classes=[reg_cls],
        ),
        MockPluginEntry(
            name="capture",
            plugin_class=MockPluginClass(commands={"start_capture": "cmd_start"}),
            category="source",
        ),
    ])


@pytest.fixture
def full_pipeline(registry, topology):
    """Собрать полный pipeline Phase 12."""
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender

    process = MockProcess()
    sender = CommandSender(process)
    cmap = MockConnectionMap({"color_mask": "processor_0", "capture": "camera_0"})
    catalog = CommandCatalog.from_registry_and_map(registry, cmap)

    rm = SimpleRM(fields={
        "color_mask": [
            SimpleFieldInfo(name="h_min", field_type=int, min_value=0, max_value=180),
            SimpleFieldInfo(name="h_max", field_type=int, min_value=0, max_value=180),
        ],
    })
    validator = CommandValidator(catalog, rm)
    holder = MockTopologyHolder(topology)

    bridge = TopologyBridge(sender, catalog, validator, rm, holder)

    # ActionBus с bridge integration
    bus = create_action_bus(rm, holder, topology_bridge=bridge)

    return bus, bridge, rm, process, sender


# --- Тесты ---


class TestFullPipeline:
    """Полный цикл: ActionBus.execute → FieldSetHandler → bridge → sender → IPC."""

    def test_field_set_sends_ipc(self, full_pipeline) -> None:
        """field_set action → IPC-команда отправлена."""
        bus, bridge, rm, process, sender = full_pipeline

        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            "color_mask", "h_min", 50, 0, description="test",
        )

        bus.execute(action)
        sender.flush()  # debounce → принудительно отправить pending

        # rm обновлён
        assert rm._values.get("color_mask", {}).get("h_min") == 50

        # IPC отправлен (через sender → process)
        assert len(MockProcess.sent) >= 1
        target, msg = MockProcess.sent[-1]
        assert target == "processor_0"
        # set_h_min нет в commands → convention fallback: set_config
        assert msg["command"] == "set_config"
        assert msg["data"] == {"h_min": 50}

    def test_undo_sends_revert_ipc(self, full_pipeline) -> None:
        """undo → IPC-команда с old_value."""
        bus, bridge, rm, process, sender = full_pipeline

        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            "color_mask", "h_min", 100, 0, description="test",
        )

        bus.execute(action)
        sender.flush()
        MockProcess.sent.clear()

        bus.undo()
        sender.flush()

        # IPC с откатом
        assert len(MockProcess.sent) >= 1
        target, msg = MockProcess.sent[-1]
        assert msg["data"] == {"h_min": 0}

    def test_state_delta_syncs_rm(self, full_pipeline) -> None:
        """state_delta → bridge.on_state_delta → rm обновлён."""
        bus, bridge, rm, process, sender = full_pipeline

        bridge.on_state_delta("processes.color_mask.config.h_min", 77)

        assert rm._values.get("color_mask", {}).get("h_min") == 77

    def test_lifecycle_start(self, full_pipeline) -> None:
        """bridge.start_process → IPC process.start."""
        bus, bridge, rm, process, sender = full_pipeline
        MockProcess.sent.clear()

        ok = bridge.start_process("camera_0")
        assert ok is True
        assert len(MockProcess.sent) == 1
        target, msg = MockProcess.sent[0]
        assert target == "camera_0"
        assert msg["command"] == "process.start"

    def test_lifecycle_nonexistent(self, full_pipeline) -> None:
        """Запуск несуществующего процесса → False."""
        bus, bridge, rm, process, sender = full_pipeline
        ok = bridge.start_process("nonexistent")
        assert ok is False
