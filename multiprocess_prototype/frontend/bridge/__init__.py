"""bridge — пакет IPC-мостов: DataReceiverBridge, CommandSender, TopologyBridge.

Phase 12: CommandCatalog, CommandValidator, TopologyBridge — модульные блоки конструктора.
Phase 12.5: WireProtocol, SystemCommands — wire data classes + IPC command builders.
Phase 12.6: TopologyBridge runtime extensions — hot_add/remove, wire connect/disconnect,
apply_topology_diff, get_capabilities, WireStatusMonitor.
Phase 1A (Task A1): wire_protocol, diff_engine, system_commands, wire_monitor,
command_sender, command_validator перенесены во framework — импортируются оттуда.
"""

# Реэкспорт DataReceiverBridge для обратной совместимости (остаётся в прото)
from ..bridge_impl import DataReceiverBridge

# Локальные модули (остаются в прото — зависят от прото-специфики)
from .command_catalog import CommandCatalog, PluginCommands, ResolvedCommand
from .topology_bridge import TopologyBridge, TopologyApplyResult

# re-export перенесённых модулей из фреймворка
from multiprocess_framework.modules.frontend_module.bridge import (
    CommandSender,
    CommandValidator,
    ICommandCatalog,
    IProcess,
    IRegistersManager,
    ProcessDiff,
    ShmConfig,
    SYSTEM_COMMANDS,
    TopologyDiff,
    ValidationResult,
    WireConfig,
    WireDiff,
    WireMetrics,
    WireStatus,
    WireStatusMonitor,
    build_hot_add_process,
    build_hot_remove_process,
    build_process_restart,
    build_process_start,
    build_process_stop,
    build_wire_setup,
    build_wire_teardown,
    compute_diff,
    validate_wire,
)

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
    # diff engine
    "ProcessDiff",
    "TopologyDiff",
    "WireDiff",
    "compute_diff",
    # Protocols
    "IProcess",
    "ICommandCatalog",
    "IRegistersManager",
]
