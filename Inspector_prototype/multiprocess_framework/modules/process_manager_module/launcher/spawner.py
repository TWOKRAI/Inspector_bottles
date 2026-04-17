"""
ProcessSpawner — создание и запуск ProcessManagerProcess (bootstrap).

Минимальная инфраструктура: SRM + лёгкий логгер; полный стек — внутри ProcessManagerProcess.
"""

import signal
from multiprocessing import Event, Process
from typing import Any, Callable, Dict, Optional, Union

from ..runner.class_loader import _ProcessLogger
from ..runner.process_runner import run_process_function
from ..platforms import get_platform_adapter
from ...shared_resources_module import SharedResourcesManager

PROCESS_MANAGER_CLASS_PATH = (
    "multiprocess_framework.modules.process_manager_module."
    "process.process_manager_process.ProcessManagerProcess"
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
    ) -> None:
        self._processes_config = processes_config or {}
        self._platform = platform_adapter or get_platform_adapter()
        self._stop_event = Event()
        self._process: Optional[Process] = None
        self._shared_resources: Optional[SharedResourcesManager] = None
        self._logger: Optional[_ProcessLogger] = None
        self._stop_timeout = stop_timeout
        self._on_shutdown = on_shutdown

    def launch_orchestrator(self) -> bool:
        """SRM + Process(ProcessManager) + сигналы."""
        self._platform.setup_multiprocessing()
        self._shared_resources = SharedResourcesManager(manager_name="shared_resources")
        self._shared_resources.initialize()

        self._logger = _ProcessLogger("spawner")

        process_config = {"processes_config": self._processes_config}
        bundle = {
            "queues": {},
            "config": process_config,
            "custom": {"process_config": process_config},
        }

        self._process = Process(
            target=run_process_function,
            args=(PROCESS_MANAGER_CLASS_PATH, "ProcessManager", self._stop_event, bundle),
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
            print(f"\n[*] Received signal {signum}, shutting down...")
        self.stop()

    def stop(self, timeout: Optional[float] = None) -> None:
        effective_timeout = timeout if timeout is not None else self._stop_timeout
        graceful_timeout = min(effective_timeout, 3.0)

        if self._logger:
            self._logger.info("Stopping ProcessManager...")

        if self._process and self._process.is_alive():
            self._stop_event.set()
            self._process.join(timeout=graceful_timeout)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning(
                        f"Process did not stop in {graceful_timeout}s, terminating..."
                    )
                self._process.terminate()
                self._process.join(timeout=effective_timeout)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning("Force killing ProcessManager")
                self._process.kill()

        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"on_shutdown callback error: {e}")

        if self._shared_resources:
            self._shared_resources.shutdown()

        if self._logger:
            self._logger.info("ProcessManager stopped")

    def wait(self) -> None:
        if self._process:
            self._process.join()

    def is_running(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def get_process(self) -> Optional[Process]:
        return self._process

    def get_shared_resources(self) -> Optional[SharedResourcesManager]:
        return self._shared_resources
