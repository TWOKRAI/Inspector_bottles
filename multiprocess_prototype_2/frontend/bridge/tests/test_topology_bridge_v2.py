"""Тесты TopologyBridge v2 — runtime extensions (Phase 12.6).

Pure Python, без Qt. Тестируем:
- hot_add_process: happy path, already exists, send_system_command вызов
- hot_remove_process: happy path, not found, каскад wire disconnect
- connect_wire: happy path, validation fail (self-loop), wire_monitor notified
- disconnect_wire: happy path, not found, wire_monitor notified
- apply_topology_diff: happy path, empty diff, partial failure, порядок, guard
- get_capabilities: полный dict
- TopologyApplyResult: ok property, summary format
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from multiprocess_prototype_2.frontend.bridge.topology_bridge import (
    TopologyBridge,
    TopologyApplyResult,
)
from multiprocess_prototype_2.frontend.bridge.wire_monitor import WireStatusMonitor


# --- Mock-объекты (расширяют стиль test_topology_bridge.py) ---


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

    def __init__(self) -> None:
        self._default = MockValidationResult.success()

    def validate_field_command(self, plugin_name: str, field_name: str, value: Any) -> MockValidationResult:
        return self._default

    def validate_action_command(self, plugin_name: str, command_name: str) -> MockValidationResult:
        return self._default


class MockSender:
    """Мок CommandSender с поддержкой send_system_command."""

    def __init__(self) -> None:
        self.field_commands: list[tuple[str, str, dict, int]] = []
        self.action_commands: list[tuple[str, str, dict | None]] = []
        self.commands: list[tuple[str, str, dict | None]] = []
        self.system_commands: list[dict[str, Any]] = []

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

    def send_system_command(self, command: dict[str, Any]) -> None:
        self.system_commands.append(command)


class MockRegistersManager:
    """Мок RegistersManager."""

    def __init__(self) -> None:
        self.set_calls: list[tuple[str, str, Any]] = []

    def get_fields(self, plugin_name: str) -> list[MockFieldInfo]:
        return []

    def set_value(self, plugin_name: str, field_name: str, value: Any) -> bool:
        self.set_calls.append((plugin_name, field_name, value))
        return True


class MockTopologyHolder:
    """Мок TopologyHolder с возможностью обновления topology."""

    def __init__(self, topology: dict[str, Any] | None = None) -> None:
        self._topology = topology or {"processes": [], "wires": []}

    @property
    def topology(self) -> dict[str, Any]:
        return self._topology

    def set_topology(self, topology: dict[str, Any]) -> None:
        """Вспомогательный метод для тестов — обновить topology."""
        self._topology = topology


# --- Fixtures ---


@pytest.fixture
def sender() -> MockSender:
    return MockSender()


@pytest.fixture
def catalog() -> MockCatalog:
    return MockCatalog()


@pytest.fixture
def validator() -> MockValidator:
    return MockValidator()


@pytest.fixture
def rm() -> MockRegistersManager:
    return MockRegistersManager()


@pytest.fixture
def holder() -> MockTopologyHolder:
    return MockTopologyHolder({
        "processes": [
            {"process_name": "camera_0", "plugin_name": "capture"},
            {"process_name": "processor_0", "plugin_name": "color_mask"},
        ],
        "wires": [
            {
                "source": "camera_0.capture.output",
                "target": "processor_0.color_mask.input",
                "transport": "router",
            },
        ],
    })


@pytest.fixture
def wire_monitor() -> WireStatusMonitor:
    return WireStatusMonitor()


@pytest.fixture
def bridge(
    sender: MockSender,
    catalog: MockCatalog,
    validator: MockValidator,
    rm: MockRegistersManager,
    holder: MockTopologyHolder,
    wire_monitor: WireStatusMonitor,
) -> TopologyBridge:
    return TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)


# --- Тесты hot_add_process ---


class TestHotAddProcess:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """hot_add нового процесса → send_system_command вызван."""
        ok = bridge.hot_add_process("new_proc", "my_plugin", {"key": "val"})
        assert ok is True
        assert len(sender.system_commands) == 1
        cmd = sender.system_commands[0]
        assert cmd["cmd"] == "process.hot_add"
        assert cmd["process_name"] == "new_proc"
        assert cmd["plugin_name"] == "my_plugin"
        assert cmd["plugin_config"] == {"key": "val"}
        assert cmd["auto_start"] is True

    def test_process_already_exists(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """hot_add существующего процесса → False, команда не отправлена."""
        ok = bridge.hot_add_process("camera_0", "capture")
        assert ok is False
        assert len(sender.system_commands) == 0

    def test_send_system_command_called(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Проверка что именно send_system_command (не send_command) вызван."""
        bridge.hot_add_process("proc_x", "plugin_x")
        assert len(sender.system_commands) == 1
        assert len(sender.commands) == 0  # НЕ send_command

    def test_auto_start_false(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """auto_start=False передаётся в команду."""
        bridge.hot_add_process("proc_y", "plugin_y", auto_start=False)
        cmd = sender.system_commands[0]
        assert cmd["auto_start"] is False

    def test_no_plugin_config(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Без plugin_config → пустой dict в команде."""
        bridge.hot_add_process("proc_z", "plugin_z")
        cmd = sender.system_commands[0]
        assert cmd["plugin_config"] == {}


# --- Тесты hot_remove_process ---


class TestHotRemoveProcess:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """hot_remove существующего процесса → True."""
        ok = bridge.hot_remove_process("camera_0")
        assert ok is True
        # Должна быть команда wire.teardown + process.hot_remove
        cmds = sender.system_commands
        # Как минимум hot_remove отправлен
        hot_remove_cmds = [c for c in cmds if c["cmd"] == "process.hot_remove"]
        assert len(hot_remove_cmds) == 1
        assert hot_remove_cmds[0]["process_name"] == "camera_0"

    def test_process_not_found(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """hot_remove несуществующего процесса → False."""
        ok = bridge.hot_remove_process("nonexistent")
        assert ok is False
        assert len(sender.system_commands) == 0

    def test_cascade_wire_disconnect(
        self, bridge: TopologyBridge, sender: MockSender
    ) -> None:
        """hot_remove каскадно отключает wire'ы процесса."""
        bridge.hot_remove_process("camera_0")
        # wire camera_0.capture.output|processor_0.color_mask.input должен быть отключён
        teardown_cmds = [c for c in sender.system_commands if c["cmd"] == "wire.teardown"]
        assert len(teardown_cmds) == 1
        assert teardown_cmds[0]["source_process"] == "camera_0"

    def test_graceful_false(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """graceful=False передаётся в команду."""
        bridge.hot_remove_process("camera_0", graceful=False)
        hot_remove_cmds = [c for c in sender.system_commands if c["cmd"] == "process.hot_remove"]
        assert hot_remove_cmds[0]["graceful"] is False


# --- Тесты connect_wire ---


class TestConnectWire:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """connect_wire с валидной конфигурацией → True."""
        ok = bridge.connect_wire(
            "w1",
            "proc_a.plugin_a.out",
            "proc_b.plugin_b.in_port",
        )
        assert ok is True
        assert len(sender.system_commands) == 1
        cmd = sender.system_commands[0]
        assert cmd["cmd"] == "wire.setup"
        assert cmd["wire_key"] == "w1"

    def test_validation_fail_self_loop(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Self-loop (одинаковые source и target) → False."""
        ok = bridge.connect_wire(
            "w_bad",
            "proc_a.plugin_a.port",
            "proc_a.plugin_a.port",
        )
        assert ok is False
        assert len(sender.system_commands) == 0

    def test_validation_fail_same_process(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """Wire внутри одного процесса → False."""
        ok = bridge.connect_wire(
            "w_bad",
            "proc_a.plugin_a.out",
            "proc_a.plugin_b.in_port",
        )
        assert ok is False
        assert len(sender.system_commands) == 0

    def test_wire_monitor_notified(
        self, bridge: TopologyBridge, wire_monitor: WireStatusMonitor
    ) -> None:
        """wire_monitor.on_wire_setup_sent вызван при успехе."""
        bridge.connect_wire("w2", "proc_a.p.out", "proc_b.p.in_port")
        from multiprocess_prototype_2.frontend.bridge.wire_monitor import WireStatus
        assert wire_monitor.get_status("w2") == WireStatus.PENDING

    def test_wire_monitor_not_notified_on_fail(
        self, bridge: TopologyBridge, wire_monitor: WireStatusMonitor
    ) -> None:
        """wire_monitor НЕ уведомляется при провале валидации."""
        bridge.connect_wire("w_bad", "proc_a.p.port", "proc_a.p.port")
        from multiprocess_prototype_2.frontend.bridge.wire_monitor import WireStatus
        assert wire_monitor.get_status("w_bad") == WireStatus.NOT_CONFIGURED


# --- Тесты disconnect_wire ---


class TestDisconnectWire:

    def test_happy_path(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """disconnect_wire существующего wire → True."""
        wire_key = "camera_0.capture.output|processor_0.color_mask.input"
        ok = bridge.disconnect_wire(wire_key)
        assert ok is True
        assert len(sender.system_commands) == 1
        cmd = sender.system_commands[0]
        assert cmd["cmd"] == "wire.teardown"
        assert cmd["wire_key"] == wire_key

    def test_wire_not_found(self, bridge: TopologyBridge, sender: MockSender) -> None:
        """disconnect_wire несуществующего wire → False."""
        ok = bridge.disconnect_wire("nonexistent|wire")
        assert ok is False
        assert len(sender.system_commands) == 0

    def test_wire_monitor_notified(
        self, bridge: TopologyBridge, wire_monitor: WireStatusMonitor
    ) -> None:
        """wire_monitor.on_wire_teardown_sent вызван при успехе."""
        wire_key = "camera_0.capture.output|processor_0.color_mask.input"
        # Сначала зарегистрируем wire в мониторе
        wire_monitor.on_wire_setup_sent(wire_key)
        from multiprocess_prototype_2.frontend.bridge.wire_monitor import WireStatus
        assert wire_monitor.get_status(wire_key) == WireStatus.PENDING

        bridge.disconnect_wire(wire_key)
        assert wire_monitor.get_status(wire_key) == WireStatus.NOT_CONFIGURED


# --- Тесты apply_topology_diff ---


class TestApplyTopologyDiff:

    def test_happy_path_add_and_remove(
        self, sender: MockSender, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, wire_monitor: WireStatusMonitor,
    ) -> None:
        """apply_diff с добавлением и удалением процессов."""
        old = {
            "processes": [
                {"process_name": "old_proc", "plugin_name": "old_plugin"},
            ],
            "wires": [],
        }
        new = {
            "processes": [
                {"process_name": "new_proc", "plugin_name": "new_plugin"},
            ],
            "wires": [],
        }
        holder = MockTopologyHolder(old)
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)

        result = bridge.apply_topology_diff(old, new)
        assert result.ok is True
        assert "new_proc" in result.processes_added
        assert "old_proc" in result.processes_removed

    def test_empty_diff(self, bridge: TopologyBridge) -> None:
        """Одинаковые topology → пустой результат."""
        topo = {"processes": [{"process_name": "a"}], "wires": []}
        result = bridge.apply_topology_diff(topo, topo)
        assert result.ok is True
        assert result.summary() == "Нет изменений"

    def test_partial_failure(
        self, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, wire_monitor: WireStatusMonitor,
    ) -> None:
        """Частичная ошибка: sender бросает exception на hot_remove."""

        class FailingSender(MockSender):
            def send_system_command(self, command: dict[str, Any]) -> None:
                if command.get("cmd") == "process.hot_remove":
                    raise RuntimeError("PM unavailable")
                super().send_system_command(command)

        old = {
            "processes": [
                {"process_name": "to_remove", "plugin_name": "p"},
                {"process_name": "to_keep", "plugin_name": "p2"},
            ],
            "wires": [],
        }
        new = {
            "processes": [
                {"process_name": "to_keep", "plugin_name": "p2"},
                {"process_name": "to_add", "plugin_name": "p3"},
            ],
            "wires": [],
        }
        sender = FailingSender()
        holder = MockTopologyHolder(old)
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)

        result = bridge.apply_topology_diff(old, new)
        assert result.ok is False
        assert len(result.errors) == 1
        assert "to_remove" in result.errors[0]
        # Добавление должно было пройти
        assert "to_add" in result.processes_added

    def test_operation_order(
        self, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, wire_monitor: WireStatusMonitor,
    ) -> None:
        """Порядок: teardown wire → remove proc → add proc → setup wire."""
        old = {
            "processes": [
                {"process_name": "old_p", "plugin_name": "p1"},
            ],
            "wires": [
                {"source": "old_p.p1.out", "target": "other.p2.in"},
            ],
        }
        new = {
            "processes": [
                {"process_name": "new_p", "plugin_name": "p3"},
            ],
            "wires": [
                {"source": "new_p.p3.out", "target": "other.p2.in"},
            ],
        }
        sender = MockSender()
        holder = MockTopologyHolder(old)
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)

        bridge.apply_topology_diff(old, new)

        # Проверяем порядок: сначала teardown, потом remove, потом add, потом setup
        cmds = [c["cmd"] for c in sender.system_commands]

        # Должны быть teardown перед remove, remove перед add
        if "wire.teardown" in cmds and "process.hot_remove" in cmds:
            assert cmds.index("wire.teardown") < cmds.index("process.hot_remove")
        if "process.hot_remove" in cmds and "process.hot_add" in cmds:
            assert cmds.index("process.hot_remove") < cmds.index("process.hot_add")

    def test_guard_applying(
        self, sender: MockSender, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, holder: MockTopologyHolder,
        wire_monitor: WireStatusMonitor,
    ) -> None:
        """Повторный вызов apply_topology_diff при _applying=True → ошибка."""
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)
        bridge._applying = True

        result = bridge.apply_topology_diff({"processes": []}, {"processes": [{"process_name": "x"}]})
        assert result.ok is False
        assert "re-entrant" in result.errors[0]

    def test_applying_flag_reset_after_error(
        self, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, wire_monitor: WireStatusMonitor,
    ) -> None:
        """_applying сбрасывается даже при exception внутри."""

        class BombSender(MockSender):
            def send_system_command(self, command: dict[str, Any]) -> None:
                raise RuntimeError("boom")

        sender = BombSender()
        holder = MockTopologyHolder({"processes": [], "wires": []})
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)

        old = {"processes": [{"process_name": "a"}], "wires": []}
        new = {"processes": [], "wires": []}
        bridge.apply_topology_diff(old, new)
        # _applying должен быть сброшен
        assert bridge._applying is False

    def test_diff_with_new_wires(
        self, sender: MockSender, catalog: MockCatalog, validator: MockValidator,
        rm: MockRegistersManager, wire_monitor: WireStatusMonitor,
    ) -> None:
        """apply_diff с добавлением wire'ов."""
        old = {"processes": [], "wires": []}
        new = {
            "processes": [],
            "wires": [
                {
                    "source": "proc_a.plugin.out",
                    "target": "proc_b.plugin.in_port",
                    "transport": "router",
                }
            ],
        }
        holder = MockTopologyHolder(old)
        bridge = TopologyBridge(sender, catalog, validator, rm, holder, wire_monitor=wire_monitor)

        result = bridge.apply_topology_diff(old, new)
        assert "proc_a.plugin.out|proc_b.plugin.in_port" in result.wires_added


# --- Тесты get_capabilities ---


class TestGetCapabilities:

    def test_returns_full_dict(self, bridge: TopologyBridge) -> None:
        """get_capabilities возвращает все ключи."""
        caps = bridge.get_capabilities()
        assert caps == {
            "field_set": True,
            "hot_add": True,
            "wire": True,
            "diff_apply": True,
        }

    def test_all_values_are_bool(self, bridge: TopologyBridge) -> None:
        """Все значения — bool."""
        caps = bridge.get_capabilities()
        for key, val in caps.items():
            assert isinstance(val, bool), f"{key} is {type(val)}, expected bool"


# --- Тесты TopologyApplyResult ---


class TestTopologyApplyResult:

    def test_ok_when_no_errors(self) -> None:
        """ok=True когда errors пуст."""
        result = TopologyApplyResult(processes_added=["a"])
        assert result.ok is True

    def test_not_ok_when_errors(self) -> None:
        """ok=False когда есть ошибки."""
        result = TopologyApplyResult(errors=["что-то пошло не так"])
        assert result.ok is False

    def test_summary_empty(self) -> None:
        """Пустой результат → 'Нет изменений'."""
        result = TopologyApplyResult()
        assert result.summary() == "Нет изменений"

    def test_summary_with_changes(self) -> None:
        """summary с добавлениями и удалениями."""
        result = TopologyApplyResult(
            processes_added=["a", "b"],
            processes_removed=["c"],
            wires_added=["w1"],
            errors=["e1"],
        )
        s = result.summary()
        assert "+2 процессов" in s
        assert "-1 процессов" in s
        assert "+1 wire" in s
        assert "ошибок: 1" in s

    def test_summary_configs_updated(self) -> None:
        """summary с обновлёнными конфигами."""
        result = TopologyApplyResult(configs_updated=["proc_a"])
        s = result.summary()
        assert "~1 конфигов" in s
