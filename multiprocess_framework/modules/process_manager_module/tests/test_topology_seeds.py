"""Тесты сид-методов _topology_* в ProcessManagerProcess (Task 2.0).

Каждый сид мутирует РОВНО одну вещь. Проверяем:
- _topology_stop: только stop, без cleanup/SHM/config.
- _topology_stop_all: bulk через stop_many (паритет дороги B), не N×stop_one.
- _topology_cleanup: registry + SHM + _process_configs, НЕ стартует/останавливает.
- _topology_provision: очереди + SHM, НЕ создаёт экземпляр, НЕ стартует.
- _topology_create: create_and_register + priority + config, НЕ стартует, НЕ SHM.
- _topology_start: только start_process.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess


# ---------------------------------------------------------------------------
# Фабрика: минимальный PM с mock-компонентами
# ---------------------------------------------------------------------------


def _make_pm(
    process_configs: dict | None = None,
    *,
    with_memory_manager: bool = True,
) -> ProcessManagerProcess:
    """Создать ProcessManagerProcess с mock-компонентами (без initialize)."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)

    pm.name = "ProcessManager"
    pm.config = {}
    pm.config_handler = None

    # SharedResources
    pm.shared_resources = MagicMock()
    pm.shared_resources.register_process = MagicMock()
    if with_memory_manager:
        pm.shared_resources.memory_manager = MagicMock()
        pm.shared_resources.memory_manager.create_memory_dict = MagicMock()
        pm.shared_resources.memory_manager.release_process_memory = MagicMock()
    else:
        pm.shared_resources.memory_manager = None

    # ProcessRegistry
    pm._process_registry = MagicMock()
    pm._process_registry.remove_process = MagicMock()
    pm._process_registry.create_and_register = MagicMock()

    # Priority
    pm._priority = MagicMock()

    # Monitor
    pm._process_monitor = MagicMock()

    # Конфиги
    pm._process_configs = copy.deepcopy(process_configs or {})

    # Логирование
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()

    # get_config
    def _get_config(key: str):
        defaults = {"stop_process_timeout": 1.0, "shutdown_timeout": 1.0}
        return defaults.get(key)

    pm.get_config = _get_config

    return pm


# ===========================================================================
# _topology_stop
# ===========================================================================


class TestTopologyStop:
    def test_delegates_to_stop_process(self) -> None:
        """_topology_stop зовёт stop_process(name)."""
        pm = _make_pm()
        # Подмена stop_process для отслеживания
        pm.stop_process = MagicMock(return_value=True)
        result = pm._topology_stop("camera_0")
        pm.stop_process.assert_called_once_with("camera_0")
        assert result is True

    def test_does_not_cleanup(self) -> None:
        """stop НЕ зовёт cleanup/_cleanup_process_resources."""
        pm = _make_pm({"camera_0": {"class": "Cam"}})
        pm.stop_process = MagicMock(return_value=True)
        pm._topology_stop("camera_0")
        pm._process_registry.remove_process.assert_not_called()
        assert "camera_0" in pm._process_configs

    def test_returns_false_on_failure(self) -> None:
        pm = _make_pm()
        pm.stop_process = MagicMock(return_value=False)
        assert pm._topology_stop("nope") is False


# ===========================================================================
# _topology_stop_all
# ===========================================================================


class TestTopologyStopAll:
    """_topology_stop_all: bulk через stop_many (паритет дороги B)."""

    def test_calls_stop_many(self) -> None:
        """_topology_stop_all зовёт stop_many, а не N×stop_one."""
        pm = _make_pm({"cam": {"class": "Cam"}, "det": {"class": "Det"}})
        pm._process_registry.stop_many = MagicMock(return_value={"cam": True, "det": True})
        result = pm._topology_stop_all(["cam", "det"])
        assert result is True
        pm._process_registry.stop_many.assert_called_once_with(
            ["cam", "det"],
            1.0,  # stop_process_timeout из _get_config
        )

    def test_empty_list_returns_true(self) -> None:
        """Пустой список → True без вызова stop_many."""
        pm = _make_pm()
        pm._process_registry.stop_many = MagicMock()
        result = pm._topology_stop_all([])
        assert result is True
        pm._process_registry.stop_many.assert_not_called()

    def test_partial_fail_returns_false(self) -> None:
        """Один процесс не остановлен → False."""
        pm = _make_pm({"a": {"class": "A"}, "b": {"class": "B"}})
        pm._process_registry.stop_many = MagicMock(return_value={"a": True, "b": False})
        result = pm._topology_stop_all(["a", "b"])
        assert result is False

    def test_all_fail_returns_false(self) -> None:
        """Все не остановлены → False."""
        pm = _make_pm({"x": {"class": "X"}})
        pm._process_registry.stop_many = MagicMock(return_value={"x": False})
        result = pm._topology_stop_all(["x"])
        assert result is False

    def test_partial_fail_logs_result_map(self) -> None:
        """При частичном провале в лог уходит список неостановленных + карта результатов."""
        pm = _make_pm({"a": {"class": "A"}, "b": {"class": "B"}})
        pm._process_registry.stop_many = MagicMock(return_value={"a": True, "b": False})
        pm._topology_stop_all(["a", "b"])
        logged = " ".join(str(c.args[0]) for c in pm._log_error.call_args_list)
        assert "['b']" in logged
        assert "'a': True" in logged

    def test_missing_name_in_results_returns_false(self) -> None:
        """stop_many не вернул результат для имени → трактуется как False."""
        pm = _make_pm({"a": {"class": "A"}})
        pm._process_registry.stop_many = MagicMock(
            return_value={}  # пустой dict — имя отсутствует
        )
        result = pm._topology_stop_all(["a"])
        assert result is False


# ===========================================================================
# _topology_cleanup
# ===========================================================================


class TestTopologyCleanup:
    def test_removes_from_registry_and_config(self) -> None:
        """cleanup удаляет из реестра, снимает с SRM (SHM+PSR+конфиг) и из _process_configs."""
        pm = _make_pm({"worker_1": {"class": "mod.W", "priority": "normal"}})
        result = pm._topology_cleanup("worker_1")
        assert result is True
        # Реестр
        pm._process_registry.remove_process.assert_called_once_with("worker_1")
        # SRM: единая точка снятия — SHM + запись PSR + конфиг (ADR-SRM-009)
        pm.shared_resources.unregister_process.assert_called_once_with("worker_1")
        # Хвосты монитора забыты (heartbeat/счётчики/статусы имени)
        pm._process_monitor.forget_process.assert_called_once_with("worker_1")
        # Конфиг
        assert "worker_1" not in pm._process_configs

    def test_no_start_or_stop(self) -> None:
        """cleanup НЕ стартует и НЕ останавливает процесс."""
        pm = _make_pm({"x": {"class": "X"}})
        pm.start_process = MagicMock()
        pm.stop_process = MagicMock()
        pm._topology_cleanup("x")
        pm.start_process.assert_not_called()
        pm.stop_process.assert_not_called()

    def test_missing_config_key_ok(self) -> None:
        """cleanup не падает если имени нет в _process_configs."""
        pm = _make_pm()
        result = pm._topology_cleanup("nonexistent")
        assert result is True


# ===========================================================================
# _topology_provision
# ===========================================================================


class TestTopologyProvision:
    def test_registers_queues(self) -> None:
        """provision зовёт shared_resources.register_process."""
        pm = _make_pm()
        proc_dict = {"class": "mod.P", "queues": {"data": {"maxsize": 50}}}
        result = pm._topology_provision("proc_a", proc_dict)
        assert result is True
        pm.shared_resources.register_process.assert_called_once_with("proc_a", proc_dict)

    def test_allocates_shm(self) -> None:
        """provision аллоцирует SHM если memory в proc_dict."""
        pm = _make_pm()
        proc_dict = {
            "class": "mod.P",
            "memory": {"frame": (1, (480, 640, 3), "uint8"), "coll": 4},
        }
        pm._topology_provision("cam_0", proc_dict)
        mm = pm.shared_resources.memory_manager
        mm.create_memory_dict.assert_called_once_with(
            "cam_0",
            {"frame": (1, (480, 640, 3), "uint8")},
            4,
        )

    def test_no_shm_without_memory(self) -> None:
        """provision без memory → SHM не аллоцируется."""
        pm = _make_pm()
        proc_dict = {"class": "mod.P"}
        pm._topology_provision("proc_b", proc_dict)
        pm.shared_resources.memory_manager.create_memory_dict.assert_not_called()

    def test_does_not_create_or_start(self) -> None:
        """provision НЕ создаёт экземпляр и НЕ стартует."""
        pm = _make_pm()
        pm._topology_provision("x", {"class": "X"})
        pm._process_registry.create_and_register.assert_not_called()
        assert "x" not in pm._process_configs

    def test_shm_failure_logged_not_raised(self) -> None:
        """SHM-аллокация упала → логируется warning, НЕ exception."""
        pm = _make_pm()
        pm.shared_resources.memory_manager.create_memory_dict.side_effect = OSError("SHM fail")
        proc_dict = {"class": "P", "memory": {"slot": (1, (100,), "float32")}}
        # Не должен бросить
        result = pm._topology_provision("proc_c", proc_dict)
        assert result is True
        pm._log_warning.assert_called_once()


# ===========================================================================
# _topology_create
# ===========================================================================


class TestTopologyCreate:
    def test_creates_and_registers(self) -> None:
        """create зовёт create_and_register + priority + config."""
        pm = _make_pm()
        mock_process = MagicMock()
        pm._process_registry.create_and_register.return_value = mock_process

        proc_dict = {"class": "mod.Worker", "priority": "high", "config": {"key": 1}}
        result = pm._topology_create("worker_1", proc_dict)
        assert result is True

        pm._process_registry.create_and_register.assert_called_once_with("worker_1", "mod.Worker", proc_dict, "high")
        pm._priority.apply_priority.assert_called_once_with(mock_process)
        pm._priority.register_priority.assert_called_once_with("worker_1", "high")
        assert "worker_1" in pm._process_configs
        # Глубокая копия
        assert pm._process_configs["worker_1"] == proc_dict
        assert pm._process_configs["worker_1"] is not proc_dict

    def test_does_not_start(self) -> None:
        """create НЕ зовёт process.start()."""
        pm = _make_pm()
        mock_process = MagicMock()
        pm._process_registry.create_and_register.return_value = mock_process
        pm._topology_create("w", {"class": "W"})
        mock_process.start.assert_not_called()

    def test_does_not_allocate_shm(self) -> None:
        """create НЕ аллоцирует SHM (это provision)."""
        pm = _make_pm()
        mock_process = MagicMock()
        pm._process_registry.create_and_register.return_value = mock_process
        proc_dict = {"class": "W", "memory": {"slot": (1, (100,), "uint8")}}
        pm._topology_create("w", proc_dict)
        pm.shared_resources.memory_manager.create_memory_dict.assert_not_called()

    def test_returns_false_on_create_failure(self) -> None:
        """create_and_register вернул None → False."""
        pm = _make_pm()
        pm._process_registry.create_and_register.return_value = None
        result = pm._topology_create("w", {"class": "W"})
        assert result is False
        assert "w" not in pm._process_configs

    def test_default_priority_normal(self) -> None:
        """Без явного priority → "normal"."""
        pm = _make_pm()
        pm._process_registry.create_and_register.return_value = MagicMock()
        pm._topology_create("w", {"class": "W"})
        pm._process_registry.create_and_register.assert_called_once_with("w", "W", {"class": "W"}, "normal")


# ===========================================================================
# _topology_start
# ===========================================================================


class TestTopologyStart:
    def test_delegates_to_start_process(self) -> None:
        """_topology_start зовёт start_process(name)."""
        pm = _make_pm()
        pm.start_process = MagicMock(return_value=True)
        result = pm._topology_start("proc_a")
        pm.start_process.assert_called_once_with("proc_a")
        assert result is True

    def test_returns_false_on_failure(self) -> None:
        pm = _make_pm()
        pm.start_process = MagicMock(return_value=False)
        assert pm._topology_start("nope") is False


# ===========================================================================
# RS-2/RS-3: честный state — очистка ghost, pid+config, unstoppable-alert
# ===========================================================================


class TestHonestStateRS2RS3:
    """cleanup удаляет поддерево процесса из StateStore; start публикует pid+config;
    unstoppable → alert в state (RS-2/RS-3)."""

    def _attach_real_state_store(self, pm, initial=None):
        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        ssm = StateStoreManager(initial_state=initial or {})
        pm._state_store_manager = ssm
        return ssm

    def test_cleanup_deletes_process_state_subtree(self) -> None:
        """Ж-2/LP-4: _topology_cleanup снимает processes.<name> из StateStore."""
        pm = _make_pm({"preproc": {"class": "mod.P"}})
        ssm = self._attach_real_state_store(
            pm, initial={"processes": {"preproc": {"state": {"status": "running"}}}}
        )
        assert ssm.store.get("processes.preproc", None) is not None

        pm._topology_cleanup("preproc")

        # Ghost-запись удалена — state сходится с ОС (процесса больше нет)
        assert ssm.store.get("processes.preproc", None) is None

    def test_start_publishes_pid_and_config(self) -> None:
        """RS-2: после успешного старта в дереве есть pid и config нового рецепта."""
        pm = _make_pm({"cam0": {"class": "mod.Cam", "config": {"fps": 30}}})
        ssm = self._attach_real_state_store(pm)
        pm.start_process = MagicMock(return_value=True)

        fake_proc = MagicMock()
        fake_proc.pid = 4242
        pm._process_registry.get_process_by_name = MagicMock(return_value=fake_proc)

        assert pm._topology_start("cam0") is True

        assert ssm.store.get("processes.cam0.pid") == 4242
        assert ssm.store.get("processes.cam0.config") == {"class": "mod.Cam", "config": {"fps": 30}}

    def test_unstoppable_alert_published_to_state(self) -> None:
        """B-3: неостановленное имя → alert в system.switch.unstoppable."""
        pm = _make_pm({"stuck": {"class": "S"}})
        ssm = self._attach_real_state_store(pm)
        pm._process_registry.stop_many = MagicMock(return_value={"stuck": False})

        assert pm._topology_stop_all(["stuck"]) is False
        assert ssm.store.get("system.switch.unstoppable") == ["stuck"]

    def test_restart_publishes_fresh_identity(self) -> None:
        """Блокер#3 (RS-2): restart_process публикует НОВЫЙ pid в state (не остаётся
        pid мёртвого инстанса)."""
        pm = _make_pm({"cam0": {"class": "mod.Cam", "priority": "normal"}})
        ssm = self._attach_real_state_store(
            pm, initial={"processes": {"cam0": {"pid": 1111}}}
        )
        # Заглушки тяжёлых шагов restart_process (проверяем именно publish identity).
        pm.stop_process = MagicMock(return_value=True)
        pm._wire_reissue_enabled = MagicMock(return_value=False)
        pm._process_queue_ids = MagicMock(return_value=set())
        pm._drain_process_queues = MagicMock()
        pm._bump_routing_epoch = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._wait_processes_ready = MagicMock(return_value={})

        fake_proc = MagicMock()
        fake_proc.pid = 7777
        pm._process_registry.create_and_register = MagicMock(return_value=fake_proc)
        pm._process_registry.get_process_by_name = MagicMock(return_value=fake_proc)

        assert pm.restart_process("cam0") is True
        # pid мёртвого инстанса (1111) заменён на новый (7777).
        assert ssm.store.get("processes.cam0.pid") == 7777
