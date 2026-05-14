"""bridge — пакет IPC-мостов: DataReceiverBridge, CommandSender, TopologyBridge.

Phase 12: CommandCatalog, CommandValidator, TopologyBridge — модульные блоки конструктора.
Phase 12.5: WireProtocol, SystemCommands — wire data classes + IPC command builders.
Phase 12.6: TopologyBridge runtime extensions — hot_add/remove, wire connect/disconnect,
apply_topology_diff, get_capabilities, WireStatusMonitor.
"""

# Реэкспорт DataReceiverBridge для обратной совместимости
from ..bridge_impl import DataReceiverBridge

from .command_catalog import CommandCatalog, PluginCommands, ResolvedCommand
from .command_sender import CommandSender
from .command_validator import CommandValidator, ValidationResult
from .topology_bridge import TopologyBridge, TopologyApplyResult

# Phase 12.5: wire data classes + валидация
from .wire_protocol import ShmConfig, WireConfig, validate_wire

# Phase 12.5: builders для system-level IPC-команд
from .system_commands import (
    SYSTEM_COMMANDS,
    build_hot_add_process,
    build_hot_remove_process,
    build_process_restart,
    build_process_start,
    build_process_stop,
    build_wire_setup,
    build_wire_teardown,
)

# Phase 12.6: wire monitor
from .wire_monitor import WireStatusMonitor, WireStatus, WireMetrics

__all__ = [
    "DataReceiverBridge",
    "CommandCatalog",
    "CommandSender",
    "CommandValidator",
    "TopologyBridge",
    "TopologyApplyResult",
    "PluginCommands",
    "ResolvedCommand",
    "ValidationResult",
    # Phase 12.5 — wire protocol
    "ShmConfig",
    "WireConfig",
    "validate_wire",
    # Phase 12.5 — system commands
    "SYSTEM_COMMANDS",
    "build_process_start",
    "build_process_stop",
    "build_process_restart",
    "build_hot_add_process",
    "build_hot_remove_process",
    "build_wire_setup",
    "build_wire_teardown",
    # Phase 12.6 — wire monitor
    "WireStatusMonitor",
    "WireStatus",
    "WireMetrics",
]
