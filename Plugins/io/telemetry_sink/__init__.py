"""telemetry_sink — сток истории телеметрии StateStore в SQLite (через Services/sql)."""

from .config import TelemetrySinkPluginConfig
from .plugin import TelemetrySinkPlugin
from .registers import TelemetrySinkRegisters
from .schemas import TelemetrySnapshot

__all__ = [
    "TelemetrySinkPlugin",
    "TelemetrySinkPluginConfig",
    "TelemetrySinkRegisters",
    "TelemetrySnapshot",
]
