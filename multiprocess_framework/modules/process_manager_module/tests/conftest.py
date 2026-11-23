"""
Shared mock-классы и фабрики для тестов process_manager_module.

Содержит:
    - MockProcess: имитация OS-процесса (pid=None до start — lifecycle mp.Process).
    - MockProcessRegistry: контролируемый реестр процессов.
    - MockSharedResources: имитация SharedResourcesManager.
    - FakePlanner: framework-level планировщик (5 фаз, без импорта prototype).
    - make_pm: фабрика PM с TopologyManager + FakePlanner wired.
    - wire_planner: подключить FakePlanner к TopologyManager PM.
    - _isolated_home: autouse-фикстура, ``HOME``/``USERPROFILE`` во временный каталог (файл токена 0.12b).
    - _join_run_sequence_threads: autouse-фикстура, дожидающаяся одноразовых потоков последовательностей
      останова (``run-stop``, ``run-fault-stop``, ``run-shutdown``) PM без исполнителя.

Phase 2.3: общий код вынесен из test_apply_topology / test_replace_blueprint.
"""

import copy
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from ..process.process_manager_process import ProcessManagerProcess

# Имена одноразовых потоков, которые ``_submit_run_sequence`` заводит у PM без исполнителя ``pm-lifecycle``.
_RUN_SEQUENCE_THREAD_NAMES = frozenset({"run-stop", "run-fault-stop", "run-shutdown"})
_RUN_SEQUENCE_JOIN_DEADLINE_S = 2.0

# PM, созданные ``make_pm`` в текущем тесте (список чистит фикстура ниже).
_PMS_OF_THIS_TEST: list[ProcessManagerProcess] = []


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """``HOME``/``USERPROFILE`` — во временный каталог (Task 0.12b).

    Endpoint порта управления пишет файл токена в ``~/.multiprocess_framework/ctl_<port>.token``: без
    подмены тесты трогали бы настоящий домашний каталог, а под xdist гонялись бы на одном имени файла.
    Каталог свой у каждого теста и лежит вне ``tmp_path`` теста (его содержимое тесты не видят);
    тест, задающий ``HOME`` сам, делает это позже и главнее.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("BACKEND_CTL_TOKEN_FILE", raising=False)
    return home


@pytest.fixture(autouse=True)
def _join_run_sequence_threads():
    """После теста дождаться (не дольше 2 с суммарно) потоков ``run-stop``/``run-fault-stop``/``run-shutdown``
    этого теста.

    Источник потоков — ветка одноразовых потоков в ``_submit_run_sequence``; без ожидания они переживают тест
    (стражи жизненного цикла G4 и предупреждения pytest). Такой поток ждёт ``paused`` у живых процессов набора до
    ``run_stop_timeout_s`` (до 10 с), а в тесте дети молчат; поэтому перед ожиданием процессы-двойники PM этого теста
    помечаются остановленными: «мёртвый процесс считается остановленным» (``_paused_pending``), поток завершается на
    ближайшем шаге опроса. Это делается ПОСЛЕ проверок теста (teardown); src PM не меняется. Поток, начатый до теста,
    не трогаем.
    """
    _PMS_OF_THIS_TEST.clear()
    before = {t.ident for t in threading.enumerate() if t.name in _RUN_SEQUENCE_THREAD_NAMES}
    yield
    for pm in _PMS_OF_THIS_TEST:
        processes = getattr(getattr(pm, "_process_registry", None), "_processes", None)
        if isinstance(processes, dict):
            for proc in processes.values():
                proc._alive = False
    _PMS_OF_THIS_TEST.clear()
    deadline = time.monotonic() + _RUN_SEQUENCE_JOIN_DEADLINE_S
    for thread in threading.enumerate():
        if thread.name in _RUN_SEQUENCE_THREAD_NAMES and thread.ident not in before:
            thread.join(max(0.0, deadline - time.monotonic()))


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
        # Ф3.2: per-process ready-event. По умолчанию пусто → get_ready_event
        # вернёт None → барьер PM работает в режиме death-watch (прежнее
        # поведение). Тесты готовности могут заполнить событиями явно.
        self._ready_events: dict[str, object] = {}

    def get_process_by_name(self, name: str) -> MockProcess | None:
        return self._processes.get(name)

    def get_ready_event(self, name: str):
        """Ф3.2: event готовности процесса (None — не задан → death-watch фолбэк)."""
        return self._ready_events.get(name)

    def stop_outcome(self, name: str) -> str | None:
        """Task 1.10: итог последнего стопа воплощения (двойник стопов не ведёт — None)."""
        return None

    def stop_window_s(self, name: str) -> float | None:
        """Task 1.2: окно стопа имени (двойник окон не ведёт — None; PM отдаёт ``stop_deadline_at`` None)."""
        return None

    def reset_call_stop_outcomes(self) -> None:
        """Task 1.10: сброс канала итога вызова (двойник канала не ведёт)."""

    def call_stop_outcome(self, name: str) -> str | None:
        """Task 1.10: итог стопа в последнем вызове этого потока (двойник — None)."""
        return None

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

    def stop_one(self, name: str, timeout: float = 5.0, *, mark_reader_gone: bool = True) -> bool:
        # Контракт «ensure stopped» (Task 1.1): нет в реестре → уже остановлен → True
        proc = self._processes.get(name)
        if proc is None:
            return True
        proc._alive = False
        return True

    def stop_many(self, names: list[str], timeout: float = 5.0, *, mark_reader_gone: bool = True) -> dict[str, bool]:
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
        # Моделируем реальный контракт: cleanup снимает запись процесса с PSR
        # (очереди/события) — _registered здесь и есть «записи PSR».
        self.process_state_registry.unregister_process = MagicMock(
            side_effect=lambda name: self._registered.pop(name, None) is not None
        )

    def register_process(self, name: str, config: dict, *, reuse_queues: bool = False) -> None:
        # reuse_queues (Ф3.1) — паритет реального SRM; в mock очередей нет,
        # поэтому флаг лишь принимается (не ломает вызовы restart_process).
        self._registered[name] = config

    def unregister_process(self, name: str) -> bool:
        """Контракт ADR-SRM-009: SHM + запись PSR + конфиг — единая точка снятия."""
        if self.memory_manager is not None:
            self.memory_manager.release_process_memory(name)
        self._registered.pop(name, None)
        return True

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
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
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


def make_monitor_double() -> MagicMock:
    """Двойник ``ProcessMonitor`` с ответами настоящей формы: политика по умолчанию годна, листов и рестартов нет."""
    from ..core.restart_policy import RestartPolicy
    from ..monitor.process_monitor import ProcessMonitor

    monitor = MagicMock(spec=ProcessMonitor)
    monitor.resolve_policy.return_value = (RestartPolicy(), True)
    monitor.readiness_view.return_value = ({}, frozenset())
    return monitor


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

    # ProcessMonitor: двойник с формой настоящего (r2 N3) — PM зовёт resolve_policy / readiness_view без проверки формы.
    pm._process_monitor = make_monitor_double()
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
    # Сигнатура ОБЯЗАНА совпадать с реальной ProcessModule.get_config(key, default):
    # однопараметрический фейк ронял вызывающих с TypeError вместо того, чтобы их
    # проверять (найдено при вводе read_process_config, Task 5.12).
    values = {
        "stop_process_timeout": 1.0,
        "shutdown_timeout": 1.0,
        # Быстрый readiness-барьер (Task 2.2): не замедлять сьют, но
        # сохранить карту ready в ответах apply_topology
        "start_ready_timeout_s": 0.05,
    }

    def _get_config(key: str, default=None):
        return values.get(key, default)

    # Task 5.11: конфиг фейка ПИШЕТСЯ, а не только читается. Настоящий
    # ProcessModule умеет `update_config`, и на нём держится адрес рецепта
    # (его пишет ретаргет, а читают ассемблер, `persist` и раздача слоя).
    # Read-only фейк делал бы эту связку недоказуемой: тест проверял бы
    # резолвер вместо того, кто ключ обновляет (та же дыра, что нашёл живой
    # прогон R6).
    def _update_config(key: str, value):
        values[key] = value
        return True

    pm.get_config = _get_config
    pm.update_config = _update_config

    _PMS_OF_THIS_TEST.append(pm)

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
