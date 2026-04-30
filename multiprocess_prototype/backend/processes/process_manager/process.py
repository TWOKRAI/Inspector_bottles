"""
ProcessManagerProcessApp — подкласс ProcessManagerProcess для прототипа.

Подключает topology_adapter к TopologyManager после базовой инициализации,
чтобы topology.apply() понимал схему SystemTopology прототипа.
"""

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)

# Путь для передачи в SystemLauncher(orchestrator_class_path=...)
PROCESS_MANAGER_APP_CLASS_PATH = (
    "multiprocess_prototype.backend.processes.process_manager.process"
    ".ProcessManagerProcessApp"
)


class ProcessManagerProcessApp(ProcessManagerProcess):
    """ProcessManagerProcess с подключённым topology_adapter прототипа."""

    def _setup_topology_manager(self) -> None:
        """Создать TopologyManager (базовый) + подключить diff/commands из прототипа."""
        super()._setup_topology_manager()
        if self._topology_manager is None:
            return
        from multiprocess_prototype.registers.system_topology.topology_adapter import (
            configure_topology_manager,
        )
        configure_topology_manager(self._topology_manager)
