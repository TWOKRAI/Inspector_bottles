"""
Тесты для ProcessManagerProcess.

Проверяют:
- initialize: успех, ошибка → error_module → shutdown
- shutdown: корень PM — монитор до сигнала детям, backend_ctl закрывается после детей
- create_process, start_process, stop_process
- get_process_status, get_all_processes_status
- Регистрацию встроенных команд
"""

import socket
import threading
from multiprocessing import Event
from unittest.mock import MagicMock, patch

from ...process_module import ProcessModule
from ..core.stop_budget import stop_budget
from ..process.backend_ctl_endpoint import setup_backend_ctl_channel
from ..process.process_manager_process import ProcessManagerProcess


def _make_mock_shared_resources(process_name: str = "ProcessManager"):
    """Создать mock SharedResourcesManager."""
    mock_srm = MagicMock()
    mock_process_data = MagicMock()
    mock_process_data.custom = {"stop_event": Event()}
    mock_process_data.state = {"status": "running"}
    mock_srm.get_process_data.return_value = mock_process_data
    mock_srm.process_state_registry = MagicMock()
    mock_srm.process_state_registry.queue_registry = None
    return mock_srm


class TestProcessManagerProcessInit:
    def test_init_creates_components(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._console_manager = None
            # config_handler инициализируется в ProcessModule.__init__; задаём None вручную
            # т.к. __init__ подменён и атрибут не создаётся автоматически
            pmp.config_handler = None

            # Проверяем что _create_components не падает без shared_resources
            with (
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessRegistry"
                ) as _mock_reg,
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessPriority"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessStatusMonitor"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessMonitor"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.QueueRegistry"
                ) as mock_qr,
            ):
                mock_qr.return_value.initialize.return_value = None
                pmp._create_components()
                assert hasattr(pmp, "_process_registry")
                assert hasattr(pmp, "_priority")
                assert hasattr(pmp, "_status")
                assert hasattr(pmp, "_process_monitor")


class _StopGroup:
    """Группа детей: фиксирует порядок и сама пишет наблюдение в момент фазы 1 и ожидания."""

    def __init__(self, journal: list, observe=None, fail: bool = False) -> None:
        self._journal = journal
        self._observe = observe
        self._fail = fail

    def request_stop(self) -> None:
        self._journal.append("children.request_stop")
        if self._observe is not None:
            self._observe()
        if self._fail:
            raise RuntimeError("boom-children")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("children.join_until")
        if self._observe is not None:
            self._observe()
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict:
        return {"child": True}


class _StopRegistry:
    def __init__(self, group: _StopGroup) -> None:
        self._group = group

    def children_stop(self, *, mark_reader_gone: bool) -> _StopGroup:
        return self._group

    def exit_report(self, name: str) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": True}


class _JournalMonitor:
    def __init__(self, journal: list) -> None:
        self._journal = journal

    def stop(self, wait: bool = True, timeout: float = 10.0) -> None:
        self._journal.append("monitor.stop")


def _bounded(fn, timeout_s: float = 15.0):
    """``fn`` в daemon-потоке с дедлайном join: (завершился, результат, ошибка)."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест разбирает ошибку сам
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="pm_shutdown_order_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


def _connectable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _real_pm(registry, monitor=None) -> ProcessManagerProcess:
    """Настоящий PM: бюджет 1.0, ``initialize()``; реестр и монитор подменены ПОСЛЕ (читаются при остановке)."""
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    pm._process_registry = registry
    if monitor is not None:
        pm._process_monitor = monitor
    return pm


class TestProcessManagerProcessShutdownOrder:
    def test_shutdown_order_monitor_then_registry(self) -> None:
        """Монитор на паузе до первого сигнала остановки детям (корень PM, ADR-PMM-036)."""
        journal: list = []
        pm = _real_pm(_StopRegistry(_StopGroup(journal)), _JournalMonitor(journal))
        try:
            done, result, error = _bounded(pm.shutdown)
        finally:
            _bounded(pm.shutdown)
        assert done and error is None, repr(error)
        assert result is True
        assert "monitor.stop" in journal and "children.request_stop" in journal, journal
        assert journal.index("monitor.stop") < journal.index("children.request_stop"), journal

    def test_backend_ctl_socket_accepts_while_children_stop(self) -> None:
        """Сокет backend_ctl жив, пока PM останавливает детей, и закрыт после shutdown().

        Ответ на ``system.shutdown`` уходит через этот сокет, а на системном стопе PM видит
        событие за <=0.1 с; закрытие сокета первым шагом shutdown теряло ответ в ~1 из 10
        живых прогонов (Task 1.1 lifecycle-stop-ownership). Теперь сокет — запись
        ``transport/backend_ctl``, а дети — в ``work``: transport закрывается после work.
        Наблюдаемое — TCP-connect на настоящий порт, а не шпион на ``close()``.
        """
        seen: list = []
        ports: list = []  # порт канала: шпион группы читает его после создания канала
        journal: list = []
        group = _StopGroup(journal, observe=lambda: seen.append(_connectable(ports[0])))
        pm = _real_pm(_StopRegistry(group), _JournalMonitor(journal))
        channel = setup_backend_ctl_channel(pm.router_manager, env={}, config={"enabled": True, "port": 0})
        assert channel is not None
        pm._backend_ctl_channel = channel
        port = channel.port
        ports.append(port)
        try:
            done, _, error = _bounded(pm.shutdown)
        finally:
            _bounded(pm.shutdown)
            channel.close()
        assert done and error is None, repr(error)
        assert seen == [True, True]  # request_stop и join_until детей: сокет принимает
        assert _connectable(port) is False
        assert pm._backend_ctl_channel is None

    def test_backend_ctl_socket_closed_even_if_stop_all_raises(self) -> None:
        """Группа детей упала в фазе 1 — сокет backend_ctl всё равно закрыт, ``shutdown()`` не бросает.

        Было: исключение ``stop_all`` уходило из ``shutdown()``. Теперь ошибка записи области
        ``work/children`` уходит в отчёт корня (``shutdown()`` → ``False``), а ``transport``
        закрывается своим барьером независимо.
        """
        journal: list = []
        pm = _real_pm(_StopRegistry(_StopGroup(journal, fail=True)), _JournalMonitor(journal))
        channel = setup_backend_ctl_channel(pm.router_manager, env={}, config={"enabled": True, "port": 0})
        assert channel is not None
        pm._backend_ctl_channel = channel
        port = channel.port
        try:
            done, result, error = _bounded(pm.shutdown)
            reachable_after = _connectable(port)
        finally:
            _bounded(pm.shutdown)
            channel.close()
        assert done and error is None, repr(error)
        assert result is False
        assert "children.request_stop" in journal, journal
        assert reachable_after is False
        assert pm._backend_ctl_channel is None

    def test_shutdown_without_console_does_not_raise(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.config_handler = None
            pmp._process_monitor = MagicMock()
            pmp._process_registry = MagicMock()
            pmp._console_manager = None

            with patch.object(ProcessManagerProcess.__bases__[0], "shutdown", return_value=True):
                pmp.shutdown()


class TestProcessManagerProcessStopProcess:
    def test_stop_process_graceful_before_terminate(self) -> None:
        """stop_process: join → terminate → kill (graceful cascade)."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_process = MagicMock()
            mock_process.is_alive.return_value = True

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = mock_process
            mock_registry.stop_one.return_value = True
            pmp._process_registry = mock_registry

            def get_config(key):
                return {"stop_process_timeout": 0.1}.get(key)

            pmp.get_config = get_config

            mock_process.is_alive.side_effect = [True, False, False]

            pmp.stop_process("TestProcess")

            mock_registry.stop_one.assert_called_once_with("TestProcess", 0.1, mark_reader_gone=True)

    def test_stop_process_unknown_returns_true(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = None
            pmp._process_registry = mock_registry
            pmp.get_config = lambda k: None

            result = pmp.stop_process("Unknown")
            assert result is True


class TestProcessManagerProcessGetStatus:
    def test_get_process_status_unknown_returns_empty(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = None
            pmp._process_registry = mock_registry

            result = pmp.get_process_status("Unknown")
            assert result == {}

    def test_get_all_processes_status_delegates_to_status(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {"P1": {"alive": True}}
            pmp._status = mock_status

            result = pmp.get_all_processes_status()
            assert result == {"P1": {"alive": True}}


class TestProcessManagerProcessBuiltinCommands:
    def test_cmd_process_list_returns_dict(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._process_configs = {}  # обязателен для обогащения статуса

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {"P1": {}}
            pmp._status = mock_status

            result = pmp._cmd_process_list()
            assert isinstance(result, dict)

    def test_cmd_process_start_requires_name(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            result = pmp._cmd_process_start()
            assert "error" in result

    def test_cmd_process_stop_requires_name(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            result = pmp._cmd_process_stop()
            assert "error" in result

    def test_cmd_system_shutdown_sets_stop_event(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.stop_event = Event()
            pmp._system_stop_event = Event()
            pmp._log_info = MagicMock()

            result = pmp._cmd_system_shutdown()
            assert result["success"] is True
            assert pmp.stop_event.is_set()
            # Task 1.1 lifecycle-stop-ownership: команда == системный стоп.
            assert pmp._system_stop_event.is_set()

    def test_cmd_system_shutdown_without_system_event_still_stops_pm(self) -> None:
        """PM без shared_resources (``_system_stop_event is None``) — команда не падает и гасит PM."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.stop_event = Event()
            pmp._system_stop_event = None
            pmp._log_info = MagicMock()

            result = pmp._cmd_system_shutdown()
            assert result["success"] is True
            assert pmp.stop_event.is_set()

    def test_cmd_system_stats_returns_dict(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_monitor = MagicMock()
            mock_monitor.get_stats.return_value = {"monitoring": False}
            pmp._process_monitor = mock_monitor

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {}
            pmp._status = mock_status

            result = pmp._cmd_system_stats()
            assert "monitor" in result
            assert "processes" in result

    def test_cmd_supervision_status_returns_epoch_and_processes(self) -> None:
        # D.1b: routing-fence-истина PM (epoch/incarnation) + monitor-срез одним ответом.
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 3
            pmp._incarnations = {"camera": 2, "gui": 0}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "camera": {"status": "running", "last_exit": None, "restart_count": 1},
                "gui": {"status": "running", "last_exit": 0, "restart_count": 0},
            }
            pmp._process_monitor = mon

            res = pmp._cmd_supervision_status()
            assert res["success"] is True
            assert res["epoch"] == 3
            assert res["processes"]["camera"]["incarnation"] == 2
            assert res["processes"]["camera"]["restart_count"] == 1
            assert res["processes"]["camera"]["status"] == "running"
            assert res["processes"]["gui"]["last_exit"] == 0

    def test_cmd_supervision_status_filters_by_process(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 1
            pmp._incarnations = {"camera": 1, "gui": 0}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "camera": {"status": "running", "last_exit": None, "restart_count": 0},
                "gui": {"status": "running", "last_exit": None, "restart_count": 0},
            }
            pmp._process_monitor = mon
            res = pmp._cmd_supervision_status(data={"process": "camera"})
            assert set(res["processes"]) == {"camera"}
            assert res["processes"]["camera"]["incarnation"] == 1

    def test_cmd_supervision_status_tolerates_non_dict_data(self) -> None:
        # Ревью #6: non-dict data не роняет хендлер (фильтр просто не применяется).
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 0
            pmp._incarnations = {"cam": 1}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "cam": {"status": "running", "last_exit": None, "restart_count": 0}
            }
            pmp._process_monitor = mon
            res = pmp._cmd_supervision_status(data=["cam"])  # non-dict
            assert res["success"] is True
            assert "cam" in res["processes"]

    def test_register_builtin_commands_registers_all(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_cm = MagicMock()
            mock_cm.register_command.return_value = True
            pmp.command_manager = mock_cm

            pmp._register_builtin_commands()

            registered_names = [call_args[0][0] for call_args in mock_cm.register_command.call_args_list]
            assert "process.list" in registered_names
            assert "process.start" in registered_names
            assert "process.stop" in registered_names
            assert "process.restart" in registered_names
            assert "process.status" in registered_names
            assert "system.shutdown" in registered_names
            assert "system.stats" in registered_names
            assert "supervision.status" in registered_names
            assert "process.relay" in registered_names

    def test_register_builtin_commands_skips_if_no_command_manager(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.command_manager = None

            pmp._register_builtin_commands()  # не должен падать


class TestOrchestratorReadySignalIsHonest:
    """B-1-1 сквозного ревью Ф5 — детерминированная пара к живому наблюдению.

    Дефект: внешний сигнал готовности взводился в КОНЦЕ ``initialize()``, а
    ``introspect.capabilities`` регистрируется позже — в ``ProcessModule.run()``.
    Наблюдатель (launcher/harness), поверивший сигналу, слал команду в окно без
    обработчика и получал ``No handler for key 'introspect.capabilities'`` — окно
    длиной со спавн детей и boot-барьер, до 5 секунд.

    Ревью корзины 2 (Ф-6) отметило, что доказательство было ТОЛЬКО живым: зонд
    успевал спросить и получал ответ — но успевал он по времени, а не по
    построению, и на медленной машине такой «зелёный» ничего не значит. Пара
    ниже времени не знает вовсе: проверяется, что ``initialize()`` события НЕ
    взводит (а лишь передаёт его процессу), и что к моменту взвода команда уже
    разрешима.
    """

    def _bare_pm(self, event):
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp.name = "ProcessManager"
        pmp.shared_resources = None
        pmp.config = {}
        pmp.command_manager = MagicMock()
        pmp.router_manager = MagicMock()
        pmp._process_monitor = MagicMock()
        pmp._system_ready_event = event
        pmp._backend_ctl_channel = None
        return pmp

    def test_initialize_hands_the_event_over_instead_of_setting_it(self) -> None:
        """Ключевая половина: к концу ``initialize()`` готовность НЕ объявлена."""
        event = Event()
        pmp = self._bare_pm(event)
        with (
            patch.object(ProcessModule, "initialize", return_value=True),
            patch.object(ProcessManagerProcess, "_setup_lifecycle_executor", return_value=True),
            patch.object(ProcessManagerProcess, "_setup_console_manager"),
            patch.object(ProcessManagerProcess, "_setup_topology_manager"),
            patch.object(ProcessManagerProcess, "_setup_state_store"),
            patch.object(ProcessManagerProcess, "_register_builtin_commands"),
            patch.object(ProcessManagerProcess, "_log_active_feature_flags"),
            patch.object(ProcessManagerProcess, "_wait_boot_ready"),
            patch.object(ProcessManagerProcess, "get_config", return_value=None),
            patch(
                "multiprocess_framework.modules.process_manager_module.process."
                "process_manager_process.setup_backend_ctl_channel",
                return_value=None,
            ),
        ):
            assert pmp.initialize() is True

        assert not event.is_set(), (
            "готовность объявлена в конце initialize() — команды ProcessModule.run() "
            "ещё не зарегистрированы, и наблюдатель попадёт в окно без обработчика"
        )
        assert pmp._ready_event is event, "событие не передано процессу — объявлять его будет некому"

    def test_the_event_is_announced_when_capabilities_already_answer(self) -> None:
        """Вторая половина пары: взвод происходит ПОСЛЕ регистрации команд.

        Без неё первая доказывала бы лишь «сигнала нет», что одинаково верно и
        для системы, которая не объявляет готовность никогда.
        """
        registered: list = []
        cm = MagicMock()
        cm.register_command = MagicMock(side_effect=lambda name, *a, **k: registered.append(name))

        seen_at_announce: list = []
        event = MagicMock()
        event.set = MagicMock(side_effect=lambda: seen_at_announce.append(list(registered)))

        process = ProcessModule("ProcessManager")
        process.command_manager = cm
        process.worker_manager = MagicMock()
        process.update_process_state = MagicMock()
        process.log = MagicMock()
        process.shutdown = MagicMock(return_value=True)
        process.attach_ready_event(event)

        process.run()
        process.stop()

        assert seen_at_announce, "готовность не объявлена вовсе"
        assert "introspect.capabilities" in seen_at_announce[0], (
            "в момент объявления готовности не зарегистрирована ровно та команда, "
            f"на которой ловили дефект живьём (зарегистрировано: {len(seen_at_announce[0])})"
        )


class TestInitializeRequiresExecutorManager:
    """Task 1.9b (D1): без ``ExecutorManager`` PM не поднимается без команд жизненного цикла.

    Команды класса L/T регистрируются с ``executor=`` по имени; без менеджера имя не разрешится, и PM
    поднялся бы без ``process.stop``. Тест готовности выше подменяет установку исполнителя — здесь она
    настоящая. Пара: тот же стенд с менеджером доходит до регистрации (иначе «не зарегистрировано» ничего
    не доказывает).
    """

    def _initialize(self, executor_manager):
        registered: list = []
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp.name = "ProcessManager"
        pmp.shared_resources = None
        pmp.config = {}
        pmp.command_manager = MagicMock()
        pmp.command_manager.register_command = MagicMock(side_effect=lambda name, *a, **k: registered.append(name))
        pmp.router_manager = MagicMock()
        pmp._process_monitor = MagicMock()
        pmp._system_ready_event = None
        pmp._backend_ctl_channel = None
        pmp._lifecycle_submit = None
        pmp.executor_manager = executor_manager
        pmp._log_error = MagicMock()
        with (
            patch.object(ProcessModule, "initialize", return_value=True),
            patch.object(ProcessManagerProcess, "_setup_console_manager"),
            patch.object(ProcessManagerProcess, "_setup_topology_manager"),
            patch.object(ProcessManagerProcess, "_setup_state_store"),
            patch.object(ProcessManagerProcess, "_log_active_feature_flags"),
            patch.object(ProcessManagerProcess, "_wait_boot_ready"),
            patch.object(ProcessManagerProcess, "get_config", return_value=None),
            patch(
                "multiprocess_framework.modules.process_manager_module.process."
                "process_manager_process.setup_backend_ctl_channel",
                return_value=None,
            ),
        ):
            result = pmp.initialize()
        return result, registered, pmp

    def test_without_executor_manager_initialize_fails_before_registering(self) -> None:
        result, registered, pmp = self._initialize(executor_manager=None)

        assert result is False
        assert registered == [], f"команды зарегистрированы без исполнителя: {registered}"
        assert pmp._log_error.call_count == 1

    def test_with_executor_manager_initialize_reaches_lifecycle_registration(self) -> None:
        result, registered, _ = self._initialize(executor_manager=MagicMock())

        assert result is True
        assert "process.stop" in registered
        assert "process.restart" in registered


class TestProcessCommandResponse:
    """_handle_process_command делегирует ответ дженерик reply_to_request
    (absorb bespoke-reply, ADR-COMM-005). Адресация/correlation — внутри
    reply_to_request (покрыто router_module/tests reply_to_request)."""

    def _make_pmp(self):
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp.name = "ProcessManager"
        pmp.command_manager = MagicMock()
        pmp.router_manager = MagicMock()
        pmp._log_error = MagicMock()
        pmp._log_debug = MagicMock()
        return pmp

    def test_delegates_result_to_reply_to_request(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"success": True, "replaced": ["a"]}
        msg = {
            "command": "process.command",
            "sender": "gui",
            "data": {"cmd": "topology.apply", "correlation_id": "c1", "topology_dict": {}},
        }
        pmp._handle_process_command(msg)

        pmp.router_manager.reply_to_request.assert_called_once()
        call = pmp.router_manager.reply_to_request.call_args
        # исходный билет передан → reply_to_request извлечёт correlation/target сам
        assert call.args[0] is msg
        assert call.args[1] == {"success": True, "replaced": ["a"]}  # результат вложенной команды
        assert call.kwargs.get("success") is True
        assert call.kwargs.get("response_command") == "process.command.response"
        pmp.router_manager.send.assert_not_called()  # больше НЕ кустарный send

    def test_inner_command_unwrapped_without_service_fields(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"status": "ok"}
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "process.start", "correlation_id": "c2", "process_name": "cam"},
            }
        )
        inner = pmp.command_manager.handle_command.call_args[0][0]
        assert inner["command"] == "process.start"
        assert inner["data"] == {"process_name": "cam"}  # cmd/correlation_id отфильтрованы

    def test_command_error_marks_success_false(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"status": "error", "reason": "boom"}
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "process.start", "correlation_id": "c3"},
            }
        )
        call = pmp.router_manager.reply_to_request.call_args
        assert call.kwargs.get("success") is False
        assert call.args[1] == {"status": "error", "reason": "boom"}

    def test_explicit_success_honored_over_error_none(self) -> None:
        """command-result-bridge fix-forward: result со ``success=True`` + ``error=None``
        (форма PM ``apply_topology`` на успехе) → транспортный success=True.

        До фикса эвристика ``"error" not in result`` ложно давала False, потому что
        ключ ``error`` присутствует (со значением None).
        """
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {
            "success": True,
            "replaced": ["a", "b"],
            "skipped_protected": [],
            "error": None,
            "rolled_back": False,
        }
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "topology.apply", "correlation_id": "c4", "topology_dict": {}},
            }
        )
        call = pmp.router_manager.reply_to_request.call_args
        assert call.kwargs.get("success") is True

    def test_explicit_success_false_honored(self) -> None:
        """result со ``success=False`` (rollback) → транспортный success=False."""
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {
            "success": False,
            "replaced": ["a"],
            "error": "Ошибка старта процесса 'x'",
            "rolled_back": True,
        }
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "topology.apply", "correlation_id": "c5", "topology_dict": {}},
            }
        )
        call = pmp.router_manager.reply_to_request.call_args
        assert call.kwargs.get("success") is False


class TestProcessRelay:
    """process.relay: PM доставляет вложенный билет процессу через свой свежий PSR.

    Зачем relay: GUI (protected) после hot-swap рецепта держит стейл-копию очередей,
    прямой GUI→процесс кладёт в мёртвый pipe (тихая потеря). PM держит актуальные
    очереди, поэтому relay доставляет через PM.send_message.
    """

    def _make_pmp(self, target_exists: bool = True):
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp.name = "ProcessManager"
        srm = MagicMock()
        srm.get_process_data.return_value = MagicMock() if target_exists else None
        pmp.shared_resources = srm
        pmp.send_message = MagicMock()
        pmp._log_error = MagicMock()
        return pmp

    def test_relay_delivers_inner_to_target(self) -> None:
        pmp = self._make_pmp(target_exists=True)
        inner = {
            "type": "command",
            "command": "register_update",
            "sender": "gui",
            "targets": ["vision"],
            "data": {"register": "hsv_mask", "field": "s_max", "value": 40},
        }

        result = pmp._cmd_process_relay(data={"target_process": "vision", "inner_message": inner})

        assert result["success"] is True
        assert result["target_process"] == "vision"
        # Доставлено через send_message PM (свежий PSR), inner «как есть»
        pmp.send_message.assert_called_once_with("vision", inner)

    def test_relay_unknown_target_visible_error(self) -> None:
        """Цель не зарегистрирована в PM → видимая ошибка, БЕЗ тихого дропа."""
        pmp = self._make_pmp(target_exists=False)

        result = pmp._cmd_process_relay(data={"target_process": "ghost", "inner_message": {"command": "x", "data": {}}})

        assert result["success"] is False
        assert "не зарегистрирован" in result["error"]
        pmp.send_message.assert_not_called()

    def test_relay_requires_target_and_inner(self) -> None:
        pmp = self._make_pmp(target_exists=True)

        assert pmp._cmd_process_relay(data={"inner_message": {"command": "x"}})["success"] is False
        assert pmp._cmd_process_relay(data={"target_process": "vision"})["success"] is False
        pmp.send_message.assert_not_called()

    def test_relay_send_failure_returns_visible_error(self) -> None:
        """Исключение при доставке → видимая ошибка инициатору."""
        pmp = self._make_pmp(target_exists=True)
        pmp.send_message.side_effect = RuntimeError("queue dead")

        result = pmp._cmd_process_relay(
            data={"target_process": "vision", "inner_message": {"command": "x", "data": {}}}
        )

        assert result["success"] is False
        assert "queue dead" in result["error"]


class TestLogActiveFeatureFlags:
    """Boot-лог FW_*-маркеров в оркестраторе (наблюдаемость, 0.2/G.F)."""

    def _bare_pmp(self) -> ProcessManagerProcess:
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp._log_info = MagicMock()
        pmp._log_warning = MagicMock()
        pmp._log_error = MagicMock()
        return pmp

    def test_all_default_logs_neutral_line(self, monkeypatch) -> None:
        # given чистое окружение (все флаги на дефолте)
        from ...config_module import feature_flags as ff

        for name, spec in ff.FLAGS.items():
            monkeypatch.delenv(name, raising=False)
            for alias in spec.aliases:
                monkeypatch.delenv(alias, raising=False)

        pmp = self._bare_pmp()
        pmp._log_active_feature_flags()

        # then одна info-строка «все на дефолте», без warning/error
        pmp._log_info.assert_called_once()
        assert "дефолт" in pmp._log_info.call_args[0][0]
        pmp._log_warning.assert_not_called()
        pmp._log_error.assert_not_called()

    def test_active_flag_is_reported_with_source(self, monkeypatch) -> None:
        # given один флаг включён через env
        monkeypatch.setenv("FW_SHM_PREFIX_CLEANUP", "1")

        pmp = self._bare_pmp()
        pmp._log_active_feature_flags()

        # then info-строка называет флаг и источник env
        msg = pmp._log_info.call_args[0][0]
        assert "FW_SHM_PREFIX_CLEANUP" in msg and "env" in msg

    def test_requires_violation_emits_warning(self, monkeypatch) -> None:
        # given gc-scheduled включён без своей зависимости gc-freeze
        monkeypatch.delenv("FW_GC_FREEZE", raising=False)
        monkeypatch.setenv("FW_GC_SCHEDULED", "1")

        pmp = self._bare_pmp()
        pmp._log_active_feature_flags()

        # then advisory-нарушение уходит в warning
        assert pmp._log_warning.called
        warned = " ".join(c[0][0] for c in pmp._log_warning.call_args_list)
        assert "FW_GC_SCHEDULED" in warned
