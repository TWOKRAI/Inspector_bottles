"""
Обработчик конфигурации процесса.
"""

from .managers_normalize import MANAGER_SECTION_KEYS, normalize_managers_view
from .observability_config import (
    ObservabilityConfig,
    ObservabilityErrorsConfig,
    ObservabilityStatsConfig,
    expand_observability,
)
from .process_config_handler import ProcessConfigHandler
from .process_launch_config import ProcessLaunchConfig
from .telemetry_publish_config import MetricRule, TelemetryPublishConfig

__all__ = [
    "MANAGER_SECTION_KEYS",
    "normalize_managers_view",
    "ObservabilityConfig",
    "ObservabilityErrorsConfig",
    "ObservabilityStatsConfig",
    "expand_observability",
    "ProcessConfigHandler",
    "ProcessLaunchConfig",
    "MetricRule",
    "TelemetryPublishConfig",
]
