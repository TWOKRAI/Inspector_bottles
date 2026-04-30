"""system_topology — единая декларативная конфигурация системы.

SystemTopology объединяет все секции конфигурации (процессы, источники,
pipeline, дисплеи) в один SchemaBase-объект. Каждая вкладка UI редактирует
свою секцию, TopologyBridge координирует отправку через три транспорта.
"""

from .converters import (
    diff_process_configs,
    extract_display_diff,
    extract_process_commands,
    extract_source_commands,
    extract_source_topology,
    inject_source_topology,
)
from .schemas import (
    ALL_SECTIONS,
    SECTION_DISPLAYS,
    SECTION_KEYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
    DisplayDefinition,
    ProcessDefinition,
    SystemTopology,
    WorkerDefinition,
)
from .topology_adapter import (
    configure_topology_manager,
    system_commands_fn,
    system_diff_fn,
)

__all__ = [
    # Schemas
    "DisplayDefinition",
    "ProcessDefinition",
    "SystemTopology",
    "WorkerDefinition",
    # Section constants
    "ALL_SECTIONS",
    "SECTION_DISPLAYS",
    "SECTION_KEYS",
    "SECTION_PIPELINE",
    "SECTION_PROCESSES",
    "SECTION_SOURCES",
    # Converters
    "diff_process_configs",
    "extract_display_diff",
    "extract_process_commands",
    "extract_source_commands",
    "extract_source_topology",
    "inject_source_topology",
    # Topology Adapter
    "configure_topology_manager",
    "system_commands_fn",
    "system_diff_fn",
]
