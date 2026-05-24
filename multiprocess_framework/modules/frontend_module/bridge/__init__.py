"""bridge — подпакет IPC-мостов для frontend_module.

Phase 1A (Task A1): перенесён из multiprocess_prototype в framework.
Содержит pure-Python примитивы для IPC-коммуникации GUI ↔ процессы.

Stability: partial (→ contract после Task C1)
"""

from multiprocess_framework.modules.frontend_module.bridge.command_sender import (
    CommandSender,
    IProcess,
)
from multiprocess_framework.modules.frontend_module.bridge.command_validator import (
    CommandValidator,
    ICommandCatalog,
    IRegistersManager,
    ValidationResult,
)
from multiprocess_framework.modules.frontend_module.bridge.diff_engine import (
    ProcessDiff,
    TopologyDiff,
    WireDiff,
    compute_diff,
)
from multiprocess_framework.modules.frontend_module.bridge.system_commands import (
    SYSTEM_COMMANDS,
    build_hot_add_process,
    build_hot_remove_process,
    build_process_restart,
    build_process_start,
    build_process_stop,
    build_wire_setup,
    build_wire_teardown,
)
from multiprocess_framework.modules.frontend_module.bridge.wire_monitor import (
    WireMetrics,
    WireStatus,
    WireStatusMonitor,
)
from multiprocess_framework.modules.frontend_module.bridge.wire_protocol import (
    ShmConfig,
    WireConfig,
    validate_wire,
)

__all__ = [
    # command_sender
    "CommandSender",
    "IProcess",
    # command_validator
    "CommandValidator",
    "ICommandCatalog",
    "IRegistersManager",
    "ValidationResult",
    # diff_engine
    "ProcessDiff",
    "TopologyDiff",
    "WireDiff",
    "compute_diff",
    # system_commands
    "SYSTEM_COMMANDS",
    "build_hot_add_process",
    "build_hot_remove_process",
    "build_process_restart",
    "build_process_start",
    "build_process_stop",
    "build_wire_setup",
    "build_wire_teardown",
    # wire_monitor
    "WireMetrics",
    "WireStatus",
    "WireStatusMonitor",
    # wire_protocol
    "ShmConfig",
    "WireConfig",
    "validate_wire",
]
