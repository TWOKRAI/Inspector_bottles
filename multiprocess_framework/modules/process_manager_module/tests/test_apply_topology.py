"""
Integration-тесты для PM.apply_topology (Task 2.2).

Покрытие:
    - Happy path: успешный apply с 5-фазными командами (stop→cleanup→provision→create→start).
    - Protected: не трогаются при apply, _topology_current_names исключает protected.
    - Rollback: инъекция падения на фазе create 3-го процесса → первые 2 откатаны.
    - Soft-fail: сид вернул success=False → rollback, _current_topology НЕ закоммичен.
    - Debounce: in-flight guard (второй вызов во время apply) → debounced.
    - Cooldown: второй вызов в окне cooldown → debounced.
    - _snapshot_processes: исключает protected.
    - _topology_current_names: live minus protected.
    - Monitor pause/resume: monitor paused на время apply, resumed после.
    - Topology not configured: apply без diff_fn/commands_fn → graceful error.

Все тесты используют mock-объекты, без реальных OS-процессов.
Framework-level: НЕ импортирует prototype (FullReplacePlanner), использует
fake diff_fn/commands_fn, эмитящие 5-фазные команды.
"""

import copy
from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess


# ---------------------------------------------------------------------------
# Mock-классы (переиспользуем паттерн из test_replace_blueprint)
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
        proc = self._processes.get(name)
        if proc is None:
            return False
        proc._alive = False
        return True

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
# Фабрика PM
# ---------------------------------------------------------------------------


def make_pm(
    process_configs: dict[str, dict] | None = None,
    *,
    with_memory_manager: bool = True,
    fail_on_create: set[str] | None = None,
) -> ProcessManagerProcess:
    """Создать минимальный PM с mock-компонентами и wired TopologyManager.

    НЕ вызывает initialize() — ручная настройка атрибутов.
    TopologyManager создаётся с реальными сидами PM (как _setup_topology_manager).
    """
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)

    pm.name = "ProcessManager"
    pm.config = {}
    pm.config_handler = None

    # SharedResources
    pm.shared_resources = MockSharedResources(with_memory_manager=with_memory_manager)

    # ProcessRegistry
    registry = MockProcessRegistry(fail_on_create=fail_on_create)
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
        cleanup_process_fn=pm._topology_cleanup,
        provision_process_fn=pm._topology_provision,
        start_process_fn=pm._topology_start,
        logger=pm.logger_manager,
        error=pm.error_manager,
        stats=pm.stats_manager,
    )
    pm._topology_manager.initialize()

    return pm


# ---------------------------------------------------------------------------
# Fake-планировщик (framework-level, НЕ импортирует prototype)
# ---------------------------------------------------------------------------


class FakePlanner:
    """Fake diff_fn/commands_fn для framework-тестов.

    Эмулирует FullReplacePlanner: 5-фазные команды (stop → cleanup →
    provision → create → start). Использует ``proc_dicts_fn`` для
    превращения blueprint в proc_dicts (framework-символы).
    """

    def __init__(self, pm: ProcessManagerProcess) -> None:
        self._pm = pm

    def _build_proc_dicts(self, blueprint: dict) -> dict[str, dict]:
        """Framework-level сборка: SystemBlueprint → proc_dicts."""
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
        """5-фазные команды: stop old → cleanup old → provision new → create new → start new."""
        proc_dicts = self._build_proc_dicts(desired)
        protected = self._pm._get_protected_names()
        old = set(self._pm._process_configs) - protected
        new = [n for n in proc_dicts if n not in protected]

        cmds: list[dict] = []
        for name in sorted(old):
            cmds.append({"cmd": "process.stop", "process_name": name})
        for name in sorted(old):
            cmds.append({"cmd": "process.cleanup", "process_name": name})
        for name in new:
            cmds.append({"cmd": "process.provision", "process_name": name, "proc_dict": proc_dicts[name]})
        for name in new:
            cmds.append({"cmd": "process.create", "process_name": name, "proc_dict": proc_dicts[name]})
        for name in new:
            cmds.append({"cmd": "process.start", "process_name": name})
        return cmds


def wire_planner(pm: ProcessManagerProcess) -> FakePlanner:
    """Сконфигурировать TopologyManager с FakePlanner."""
    planner = FakePlanner(pm)
    pm._topology_manager.configure(
        diff_fn=planner.diff,
        commands_fn=planner.commands,
    )
    return planner


# ===========================================================================
# Тесты
# ===========================================================================


class TestSnapshotAndCurrentNames:
    """_snapshot_processes и _topology_current_names."""

    def test_snapshot_excludes_protected(self) -> None:
        """Protected процессы (включая self) не попадают в snapshot."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM", "protected": True},
                "gui": {"class": "m.GUI", "protected": True},
                "worker_1": {"class": "m.W1"},
                "worker_2": {"class": "m.W2"},
            }
        )
        snap = pm._snapshot_processes()
        assert "ProcessManager" not in snap
        assert "gui" not in snap
        assert "worker_1" in snap
        assert "worker_2" in snap

    def test_snapshot_is_deep_copy(self) -> None:
        """Snapshot — deep copy: мутация оригинала не затрагивает snapshot."""
        pm = make_pm({"w1": {"class": "m.W1", "data": [1, 2]}})
        snap = pm._snapshot_processes()
        pm._process_configs["w1"]["data"].append(3)
        assert snap["w1"]["data"] == [1, 2]

    def test_current_names_excludes_protected(self) -> None:
        """_topology_current_names = live minus protected."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM"},
                "gui": {"class": "m.GUI", "protected": True},
                "camera_0": {"class": "m.Cam"},
                "detector": {"class": "m.Det"},
            }
        )
        names = pm._topology_current_names()
        assert "ProcessManager" not in names
        assert "gui" not in names
        assert "camera_0" in names
        assert "detector" in names


class TestApplyTopologyHappyPath:
    """Успешный apply_topology."""

    def test_success_old_stopped_new_started(self) -> None:
        """Старые non-protected остановлены+очищены, новые provisioned+created+started."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "old_worker": {"class": "m.OldW"},
            }
        )
        wire_planner(pm)

        new_bp = {
            "processes": [
                {"process_name": "new_cam", "process_class": "m.Cam"},
                {"process_name": "new_det", "process_class": "m.Det"},
            ]
        }
        result = pm.apply_topology(new_bp)

        assert result["success"] is True
        assert result["rolled_back"] is False
        # Старый worker удалён из конфигов
        assert "old_worker" not in pm._process_configs
        # Новые присутствуют
        assert "new_cam" in pm._process_configs
        assert "new_det" in pm._process_configs
        # Protected не тронут
        assert "gui" in pm._process_configs

    def test_topology_committed_on_success(self) -> None:
        """При успехе _current_topology обновлён (коммит в TopologyManager)."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        wire_planner(pm)

        bp = {"processes": [{"process_name": "n1", "process_class": "m.N1"}]}
        pm.apply_topology(bp)

        assert pm._topology_manager._current_topology == bp

    def test_protected_not_touched(self) -> None:
        """Protected-процесс не останавливается и не пересоздаётся."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.W"},
            }
        )
        wire_planner(pm)

        gui_proc = pm._process_registry.get_process_by_name("gui")
        gui_proc._started = False

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        # GUI процесс жив, start() не вызывался
        assert gui_proc._alive is True
        assert gui_proc._started is False
        assert "gui" in pm._process_configs

    def test_monitor_paused_and_resumed(self) -> None:
        """Monitor останавливается на время apply и возобновляется после."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        wire_planner(pm)

        pm.apply_topology({"processes": []})

        pm._process_monitor.stop.assert_called()
        pm._process_monitor.start.assert_called()


class TestApplyTopologyRollback:
    """Rollback при failure."""

    def test_create_failure_rolls_back(self) -> None:
        """Падение на create 3-го процесса → первые 2 откатаны, snapshot восстановлен."""
        pm = make_pm(
            {
                "old_1": {"class": "m.O1"},
                "old_2": {"class": "m.O2"},
            }
        )

        # Инъекция: create 3-го процесса (proc_c) падает
        create_count = {"n": 0}
        original_create = pm._topology_create

        def failing_create(name: str, proc_dict: dict) -> bool:
            create_count["n"] += 1
            if create_count["n"] == 3:
                raise RuntimeError(f"injected failure on create #{create_count['n']} ({name})")
            return original_create(name, proc_dict)

        pm._topology_manager.configure(create_process_fn=failing_create)
        wire_planner(pm)

        snapshot_before = copy.deepcopy(pm._process_configs)

        bp = {
            "processes": [
                {"process_name": "proc_a", "process_class": "m.A"},
                {"process_name": "proc_b", "process_class": "m.B"},
                {"process_name": "proc_c", "process_class": "m.C"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is False
        assert result["rolled_back"] is True
        # Конфиги восстановлены из snapshot
        for name in snapshot_before:
            assert name in pm._process_configs
            assert pm._process_configs[name]["class"] == snapshot_before[name]["class"]
        # _current_topology НЕ закоммичен
        assert pm._topology_manager._current_topology is None

    def test_soft_fail_rolls_back(self) -> None:
        """Сид вернул success=False (без exception) → rollback, topology НЕ закоммичен."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        # Подменяем start_process_fn чтобы возвращал False
        pm._topology_manager.configure(start_process_fn=lambda name: False)
        wire_planner(pm)

        old_topo = {"old": True}
        pm._topology_manager._current_topology = old_topo

        result = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True
        assert pm._topology_manager._current_topology is old_topo

    def test_monitor_resumed_after_failure(self) -> None:
        """Monitor возобновляется даже при failure."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._topology_manager.configure(start_process_fn=lambda name: False)
        wire_planner(pm)

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        pm._process_monitor.start.assert_called()


class TestApplyTopologyDebounce:
    """Debounce: in-flight guard + cooldown."""

    def test_in_flight_guard(self) -> None:
        """Пока apply выполняется (_replace_in_progress=True) → второй debounced."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        wire_planner(pm)
        pm._replace_in_progress = True

        result = pm.apply_topology({"processes": []})

        assert result["success"] is False
        assert result["debounced"] is True
        # Реальная замена не выполнялась
        assert "w1" in pm._process_configs

    def test_cooldown_rejects_rapid_second(self) -> None:
        """С replace_debounce_s>0 повторный запрос в окне → debounced."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        wire_planner(pm)
        pm.get_config = lambda key: {
            "stop_process_timeout": 1.0,
            "replace_debounce_s": 10.0,
        }.get(key)

        # Первый apply проходит
        r1 = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert r1["success"] is True

        # Второй сразу же — в пределах cooldown
        r2 = pm.apply_topology({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert r2["success"] is False
        assert r2["debounced"] is True
        assert "n1" in pm._process_configs
        assert "n2" not in pm._process_configs

    def test_in_flight_flag_cleared_after_apply(self) -> None:
        """После apply (успех или нет) флаг _replace_in_progress снят."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        wire_planner(pm)

        pm.apply_topology({"processes": []})

        assert pm._replace_in_progress is False
        assert pm._last_replace_ts > 0.0

    def test_in_flight_flag_cleared_after_failure(self) -> None:
        """Флаг снимается даже при failure (finally)."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._topology_manager.configure(
            start_process_fn=lambda name: False,
        )
        wire_planner(pm)

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert pm._replace_in_progress is False


class TestApplyTopologyNotConfigured:
    """apply_topology без конфигурации планировщика."""

    def test_no_topology_manager(self) -> None:
        """_topology_manager is None → graceful error."""
        pm = make_pm()
        pm._topology_manager = None

        result = pm.apply_topology({"processes": []})
        assert result["success"] is False
        assert "not initialized" in result.get("error", "")

    def test_no_commands_fn(self) -> None:
        """commands_fn не установлен → graceful error."""
        pm = make_pm()
        # TopologyManager создан но не configured (diff_fn/commands_fn = None)

        result = pm.apply_topology({"processes": []})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")


class TestCmdTopologyApplyRouting:
    """_cmd_topology_apply маршрутизирует в apply_topology."""

    def test_cmd_routes_to_apply_topology(self) -> None:
        """_cmd_topology_apply вызывает apply_topology, не напрямую manager.apply."""
        pm = make_pm()
        wire_planner(pm)

        # Подменяем apply_topology чтобы проверить маршрутизацию
        pm.apply_topology = MagicMock(return_value={"success": True})

        bp = {"some": "topology"}
        pm._cmd_topology_apply({"topology_dict": bp})

        pm.apply_topology.assert_called_once_with(bp)

    def test_cmd_no_topology_dict(self) -> None:
        """Без topology_dict → error."""
        pm = make_pm()
        result = pm._cmd_topology_apply({})
        assert "error" in result
