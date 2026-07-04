"""
Shared mock-классы и фабрики для тестов process_manager_module.

Содержит:
    - MockProcess: имитация OS-процесса (pid=None до start — lifecycle mp.Process).
    - MockProcessRegistry: контролируемый реестр процессов.
    - MockSharedResources: имитация SharedResourcesManager.
    - FakePlanner: framework-level планировщик (5 фаз, без импорта prototype).
    - make_pm: фабрика PM с TopologyManager + FakePlanner wired.
    - wire_planner: подключить FakePlanner к TopologyManager PM.

Phase 2.3: общий код вынесен из test_apply_topology / test_replace_blueprint.
"""

import copy
from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess


# ---------------------------------------------------------------------------
# Mock-классы
# ---------------------------------------------------------------------------


class MockProcess:
    """Имитация OS-процесса без реального запуска.

    pid=None до start() — имитирует multiprocessing.Process: pid присваивается
    только после start. PM.start_process() проверяет ``pid is not None`` и
    отказывает в повторном запуске (ограничение mp).
    """

    def __init__(
        self,
        name: str,
        *,
        alive: bool = True,
        pid: int | None = None,
        fail_on_start: bool = False,
    ) -> None:
        self.name = name
        self._alive = alive
        # Для «уже бегущих» процессов (alive=True) pid устанавливается сразу;
        # для «свежесозданных» (alive=False) — None (как mp.Process до start).
        self.pid = pid if pid is not None else (hash(name) % 10000 if alive else None)
        self._fail_on_start = fail_on_start
        self._started = False

    def is_alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        if self._fail_on_start:
            raise RuntimeError(f"MockProcess '{self.name}': start failure (injected)")
        self._alive = True
        self._started = True
        self.pid = hash(self.name) % 10000  # pid появляется после start

    def stop(self) -> None:
        self._alive = False

    def join(self, timeout: float | None = None) -> None:
        pass

    def terminate(self) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


class MockProcessRegistry:
    """Имитация ProcessRegistry с контролируемым поведением."""

    def __init__(self, *, fail_on_create: set[str] | None = None) -> None:
        self._processes: dict[str, MockProcess] = {}
        self._fail_on_create: set[str] = fail_on_create or set()
        self._next_process_factory: dict[str, MockProcess] = {}

    def get_process_by_name(self, name: str) -> MockProcess | None:
        return self._processes.get(name)

    def create_and_register(
        self,
        name: str,
        class_path: str,
        config: dict | None = None,
        priority: str = "normal",
    ) -> MockProcess | None:
        if name in self._fail_on_create:
            return None
        # alive=False, pid=None — ещё не стартован (как mp.Process)
        proc = self._next_process_factory.get(name) or MockProcess(name, alive=False)
        self._processes[name] = proc
        return proc

    def remove_process(self, name: str) -> None:
        self._processes.pop(name, None)

    def stop_one(self, name: str, timeout: float = 5.0) -> bool:
        # Контракт «ensure stopped» (Task 1.1): нет в реестре → уже остановлен → True
        proc = self._processes.get(name)
        if proc is None:
            return True
        proc._alive = False
        return True

    def stop_many(self, names: list[str], timeout: float = 5.0) -> dict[str, bool]:
        """Параллельная остановка (мок: синхронно помечает остановленными)."""
        results: dict[str, bool] = {}
        for name in names:
            results[name] = self.stop_one(name, timeout)
        return results

    @property
    def os_processes(self) -> list[MockProcess]:
        return list(self._processes.values())


class MockSharedResources:
    """Имитация SharedResourcesManager."""

    def __init__(self, *, with_memory_manager: bool = True) -> None:
        if with_memory_manager:
            self.memory_manager = MagicMock()
            self.memory_manager.release_process_memory = MagicMock()
            self.memory_manager.create_memory_dict = MagicMock()
        else:
            self.memory_manager = None

        self.process_state_registry = MagicMock()
        self.process_state_registry.queue_registry = None
        self._registered: dict[str, dict] = {}

    def register_process(self, name: str, config: dict) -> None:
        self._registered[name] = config

    def get_process_data(self, name: str) -> MagicMock:
        mock_data = MagicMock()
        mock_data.custom = {}
        mock_data.state = {"status": "running"}
        return mock_data

    def get_process_names(self) -> list[str]:
        return list(self._registered.keys())

    def get_system_stop_event(self):
        return None


# ---------------------------------------------------------------------------
# Fake-планировщик (framework-level, НЕ импортирует prototype)
# ---------------------------------------------------------------------------


class FakePlanner:
    """Fake diff_fn/commands_fn для framework-тестов.

    Эмулирует FullReplacePlanner: 5-фазные команды (stop -> cleanup ->
    provision -> create -> start). Использует ``proc_dicts_fn`` для
    превращения blueprint в proc_dicts (framework-символы).
    """

    def __init__(self, pm: ProcessManagerProcess) -> None:
        self._pm = pm

    def _build_proc_dicts(self, blueprint: dict) -> dict[str, dict]:
        """Framework-level сборка: SystemBlueprint -> proc_dicts."""
        from multiprocess_framework.modules.process_module.generic.blueprint import (
            SystemBlueprint,
        )
        from multiprocess_framework.modules.data_schema_module import process

        topology = SystemBlueprint.model_validate(blueprint or {})
        result: dict[str, dict] = {}
        for cfg in topology.build_configs():
            name, proc_dict = process(cfg)
            result[name] = proc_dict
        return result

    def diff(self, current: dict | None, desired: dict) -> dict:
        """Full-replace: всегда has_changes=True."""
        return {"has_changes": True}

    def commands(self, diff_result: dict, desired: dict) -> list[dict]:
        """5-фазные команды: stop_all old -> cleanup old -> provision new -> create new -> start new."""
        proc_dicts = self._build_proc_dicts(desired)
        protected = self._pm._get_protected_names()
        old = set(self._pm._process_configs) - protected
        new = [n for n in proc_dicts if n not in protected]

        cmds: list[dict] = []
        # Фаза A: bulk-остановка (одна команда, параллельный stop_many)
        if old:
            cmds.append({"cmd": "process.stop_all", "process_names": sorted(old)})
        for name in sorted(old):
            cmds.append({"cmd": "process.cleanup", "process_name": name})
        for name in new:
            cmds.append({"cmd": "process.provision", "process_name": name, "proc_dict": proc_dicts[name]})
        for name in new:
            cmds.append({"cmd": "process.create", "process_name": name, "proc_dict": proc_dicts[name]})
        for name in new:
            cmds.append({"cmd": "process.start", "process_name": name})
        return cmds


# ---------------------------------------------------------------------------
# Фабрика PM
# ---------------------------------------------------------------------------


def make_pm(
    process_configs: dict[str, dict] | None = None,
    *,
    with_memory_manager: bool = True,
    fail_on_create: set[str] | None = None,
    shared_resources: MockSharedResources | None = ...,
    next_process_factory: dict[str, MockProcess] | None = None,
) -> ProcessManagerProcess:
    """Создать минимальный PM с mock-компонентами и wired TopologyManager.

    НЕ вызывает initialize() — ручная настройка атрибутов.
    TopologyManager создаётся с реальными сидами PM (как _setup_topology_manager).
    FakePlanner подключается автоматически.
    """
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)

    pm.name = "ProcessManager"
    pm.config = {}
    pm.config_handler = None

    # SharedResources
    if shared_resources is ...:
        pm.shared_resources = MockSharedResources(with_memory_manager=with_memory_manager)
    else:
        pm.shared_resources = shared_resources

    # ProcessRegistry
    registry = MockProcessRegistry(fail_on_create=fail_on_create)
    if next_process_factory:
        registry._next_process_factory = next_process_factory
    pm._process_registry = registry

    # ProcessMonitor
    pm._process_monitor = MagicMock()
    pm._process_monitor._monitoring = True

    # Priority
    pm._priority = MagicMock()

    # StatusMonitor
    pm._status = MagicMock()

    # Конфиги процессов
    pm._process_configs = copy.deepcopy(process_configs or {})
    pm._active_wires = {}
    pm._replace_in_progress = False
    pm._last_replace_ts = 0.0

    # Заполнить реестр MockProcess для каждого конфига
    for pname in pm._process_configs:
        proc = MockProcess(pname, alive=True, pid=hash(pname) % 10000)
        registry._processes[pname] = proc

    # Observability
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()
    pm.logger_manager = MagicMock()
    pm.error_manager = MagicMock()
    pm.stats_manager = MagicMock()

    # get_config
    def _get_config(key: str):
        defaults = {"stop_process_timeout": 1.0, "shutdown_timeout": 1.0}
        return defaults.get(key)

    pm.get_config = _get_config

    # TopologyManager с реальными сидами PM (как _setup_topology_manager)
    from ..process.topology_manager import TopologyManager

    pm._topology_manager = TopologyManager(
        create_process_fn=pm._topology_create,
        stop_process_fn=pm._topology_stop,
        stop_all_process_fn=pm._topology_stop_all,
        cleanup_process_fn=pm._topology_cleanup,
        provision_process_fn=pm._topology_provision,
        start_process_fn=pm._topology_start,
        logger=pm.logger_manager,
        error=pm.error_manager,
        stats=pm.stats_manager,
    )
    pm._topology_manager.initialize()

    # Подключить FakePlanner
    wire_planner(pm)

    return pm


def wire_planner(pm: ProcessManagerProcess) -> FakePlanner:
    """Сконфигурировать TopologyManager с FakePlanner."""
    planner = FakePlanner(pm)
    pm._topology_manager.configure(
        diff_fn=planner.diff,
        commands_fn=planner.commands,
    )
    return planner
