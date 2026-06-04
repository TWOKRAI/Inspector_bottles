"""
ProcessSpawner — создание и запуск ProcessManagerProcess (bootstrap).

Минимальная инфраструктура: SRM + лёгкий логгер; полный стек — внутри ProcessManagerProcess.
"""

import signal
from multiprocessing import Event, Process
from typing import Any, Callable, Dict, Optional, Union

from ...logger_module.utils import FallbackLogger
from ..runner.class_loader import _ProcessLogger
from ..runner.process_runner import run_process_function
from ..platforms import get_platform_adapter
from ...shared_resources_module import SharedResourcesManager

_logger = FallbackLogger(__name__)

PROCESS_MANAGER_CLASS_PATH = (
    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessManagerProcess"
)


class ProcessSpawner:
    """
    Создание и запуск ProcessManagerProcess.

    Graceful shutdown: SIGINT/SIGTERM → stop() без sys.exit().
    """

    def __init__(
        self,
        processes_config: Union[Dict[str, Any], None] = None,
        platform_adapter=None,
        stop_timeout: float = 5.0,
        on_shutdown: Optional[Callable[[], None]] = None,
        system_ready_event: Optional[Event] = None,
        system_stop_event: Optional[Event] = None,
        orchestrator_class_path: str = PROCESS_MANAGER_CLASS_PATH,
        orchestrator_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._processes_config = processes_config or {}
        self._platform = platform_adapter or get_platform_adapter()
        self._stop_event = Event()
        self._process: Optional[Process] = None
        self._shared_resources: Optional[SharedResourcesManager] = None
        self._logger: Optional[_ProcessLogger] = None
        self._stop_timeout = stop_timeout
        self._on_shutdown = on_shutdown
        # Event для сигнализации готовности системы (ADR-116).
        # ProcessManagerProcess выставляет его после завершения initialize().
        self._system_ready_event: Optional[Event] = system_ready_event
        # ОБЩИЙ system-wide stop (см. SystemLauncher): проброшен PM и всем детям.
        self._system_stop_event: Optional[Event] = system_stop_event
        # Путь к классу оркестратора (по умолчанию ProcessManagerProcess).
        # Прототип может подставить свой подкласс.
        self._orchestrator_class_path = orchestrator_class_path
        # Дополнительный конфиг оркестратора (Dict at Boundary).
        # Ключи мёржатся в process_config и доступны через self.get_config(key).
        self._orchestrator_config: Dict[str, Any] = orchestrator_config or {}

    def launch_orchestrator(self) -> bool:
        """SRM + Process(ProcessManager) + сигналы."""
        self._platform.setup_multiprocessing()
        self._shared_resources = SharedResourcesManager(manager_name="shared_resources")
        self._shared_resources.initialize()

        self._logger = _ProcessLogger("spawner")

        process_config = {"processes_config": self._processes_config}
        # Мёрджим дополнительный конфиг оркестратора поверх process_config.
        # Это позволяет прототипу передавать app_config и другие данные
        # без изменения внутренней структуры processes_config.
        if self._orchestrator_config:
            process_config.update(self._orchestrator_config)
        custom = {"process_config": process_config}
        # Передаём system_ready_event в ProcessManagerProcess через bundle (ADR-116).
        # multiprocessing.Event pickle-safe и безопасно пробрасывается через spawn.
        if self._system_ready_event is not None:
            custom["system_ready_event"] = self._system_ready_event
        # ОБЩИЙ stop НЕ кладём в bundle custom (иначе сериализуется через Queue и сырой
        # mp.Event падает на Windows-spawn). Передаём отдельным Process-аргументом —
        # process_runner положит его в локальный custom после build, PM прочитает оттуда
        # и пробросит детям (ProcessRegistry, тоже отдельным аргументом).
        bundle = {
            "queues": {},
            "config": process_config,
            "custom": custom,
        }

        self._process = Process(
            target=run_process_function,
            # system_stop_event — отдельным аргументом (inheritance), НЕ в bundle custom.
            args=(
                self._orchestrator_class_path,
                "ProcessManager",
                self._stop_event,
                bundle,
                self._system_stop_event,
            ),
            name="ProcessManager",
        )
        self._process.start()

        self._setup_signals()
        return True

    def _setup_signals(self) -> None:
        import threading

        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        if self._logger:
            self._logger.warning(f"Received signal {signum}, shutting down...")
        else:
            _logger.warning("Received signal %s, shutting down...", signum)
        self.stop()

    def stop(self, timeout: Optional[float] = None) -> None:
        effective_timeout = timeout if timeout is not None else self._stop_timeout

        if self._logger:
            self._logger.info("Stopping system...")

        # Снимок ВСЕГО поддерева ДО убийства PM. Воркеры — внуки (launcher → PM →
        # дети), и как только PM убит (шаг 1), PPID-цепочка рвётся:
        # children(recursive=True) на шаге 2 их уже не находит → сироты. Снятые
        # сейчас psutil.Process кэшируют create_time и проверяют идентичность при
        # terminate(), поэтому переиспользованный ОС PID не пострадает.
        pre_kill_descendants = self._snapshot_descendants()

        # 0. ОБЩИЙ stop — все процессы (PM + дети) видят его в своём lifecycle и
        # начинают граceful-стоп ПАРАЛЛЕЛЬНО, не дожидаясь команды от PM.
        if self._system_stop_event is not None:
            self._system_stop_event.set()

        # 1. Сигнал ProcessManager — он внутри shutdown() остановит дочерние
        if self._process and self._process.is_alive():
            self._stop_event.set()
            self._process.join(timeout=effective_timeout)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning(f"ProcessManager did not stop in {effective_timeout}s, terminating...")
                self._process.terminate()
                self._process.join(timeout=3.0)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning("Force killing ProcessManager")
                self._process.kill()

        # 2. Убить все дочерние процессы-сироты (если ProcessManager не успел).
        # Передаём снимок поддерева, снятый ДО убийства PM, — иначе обход по живым
        # PPID не дойдёт до внуков (их родитель уже мёртв).
        self._kill_orphan_children(pre_kill_descendants)

        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"on_shutdown callback error: {e}")

        if self._shared_resources:
            self._shared_resources.shutdown()

        if self._logger:
            self._logger.info("System stopped")

    def _snapshot_descendants(self) -> list:
        """Снимок всего поддерева текущего процесса (psutil.Process, recursive).

        Снимается ДО остановки PM, пока PPID-цепочка цела. Best-effort: при любой
        ошибке (нет psutil/доступа) возвращает пустой список.
        """
        try:
            import os

            import psutil

            return psutil.Process(os.getpid()).children(recursive=True)
        except Exception:  # noqa: BLE001 — снимок не критичен
            return []

    def _kill_orphan_children(self, pre_kill: Optional[list] = None) -> None:
        """Убить дочерние процессы, не завершившиеся вместе с ProcessManager.

        Args:
            pre_kill: снимок поддерева, снятый ДО убийства PM (см. stop()). Нужен,
                т.к. после смерти PM внуки осиротевают и обход по живым PPID их не
                находит. Объединяется с текущим обходом и дедуплицируется по PID.
        """
        import os

        import psutil

        try:
            current = psutil.Process(os.getpid())
            # Объединяем снимок «до» и текущий обход; дедуп по PID. self исключаем.
            by_pid: dict[int, "psutil.Process"] = {}
            for proc in list(pre_kill or []) + current.children(recursive=True):
                if proc.pid != current.pid:
                    by_pid[proc.pid] = proc
            children = list(by_pid.values())
            if not children:
                return
            if self._logger:
                self._logger.warning(f"Killing {len(children)} orphan child process(es)...")
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(children, timeout=2.0)
            for child in alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Orphan cleanup error: {e}")

    def wait(self) -> None:
        if self._process:
            self._process.join()

    def is_running(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def get_process(self) -> Optional[Process]:
        return self._process

    def get_shared_resources(self) -> Optional[SharedResourcesManager]:
        return self._shared_resources
