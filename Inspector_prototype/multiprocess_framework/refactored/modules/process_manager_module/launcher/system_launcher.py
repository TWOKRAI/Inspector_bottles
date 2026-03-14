"""
SystemLauncher — фасад запуска системы (Refactored).

Dict at Boundary: принимает только (name, proc_dict). Конвертация config → dict
выполняется в app-слое через process() из data_schema_module.

Нормализация: merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA) —
consumer определяет ожидаемый формат, недостающие ключи заполняются.
"""

import sys
from typing import Optional, Dict, Any, List, Tuple, Callable, TYPE_CHECKING

from ...data_schema_module import merge_with_defaults
from .schema import DEFAULT_PROCESS_SCHEMA
from .spawner import ProcessSpawner

if TYPE_CHECKING:
    from ...logger_module import LoggerManager


class SystemLauncher:
    """
    Фасад запуска системы процессов.

    Реализует ISystemLauncher.
    Dict at Boundary: add_process(name, proc_dict) — только dict.
    Конвертация в app: launcher.add_process(*build_process_with_workers(Process1Config(), Worker1Config())).

    Args:
        config: Конфиг процессов (альтернатива add_process).
        stop_timeout: Время ожидания graceful stop (секунды).
        on_shutdown: Callback, вызываемый при завершении системы.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        stop_timeout: float = 5.0,
        on_shutdown: Optional[Callable[[], None]] = None,
    ) -> None:
        self._config = config
        self._processes: List[Tuple[str, Dict[str, Any]]] = []
        self._spawner: Optional[ProcessSpawner] = None
        self._stop_timeout = stop_timeout
        self._on_shutdown = on_shutdown

    def _get_logger(self) -> Optional["LoggerManager"]:
        """Получить логгер из spawner (доступен после run/start)."""
        return self._spawner.get_logger() if self._spawner else None

    def _log_info(self, message: str) -> None:
        """Логирование info с fallback на print."""
        logger = self._get_logger()
        if logger:
            logger.info(message, module="launcher")
        else:
            print(f"[*] {message}")

    def _log_warning(self, message: str) -> None:
        """Логирование warning с fallback на print."""
        logger = self._get_logger()
        if logger:
            logger.warning(message, module="launcher")
        else:
            print(f"[!] {message}")

    def add_process(
        self,
        name: str,
        proc_dict: Dict[str, Any],
    ) -> "SystemLauncher":
        """
        Добавить процесс. Только dict.

        proc_dict нормализуется через merge_with_defaults(DEFAULT_PROCESS_SCHEMA) —
        недостающие ключи (class, queues, priority, workers) заполняются.

        Args:
            name: имя процесса (ключ в processes_config)
            proc_dict: {"class": "...", "queues": {...}, "workers": {...}, ...}

        Returns:
            self для цепочки вызовов
        """
        normalized = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
        self._processes.append((name, normalized))
        return self

    def _build_processes_config(self) -> Dict[str, Dict[str, Any]]:
        """Собрать processes_config из _processes. Каждый proc_dict уже нормализован."""
        return {name: proc_dict for name, proc_dict in self._processes}

    def _get_processes_config(self) -> Dict[str, Dict[str, Any]]:
        """processes_config для ProcessSpawner: _processes или _config, с нормализацией."""
        if self._processes:
            return self._build_processes_config()
        if self._config:
            return {
                k: merge_with_defaults(v, DEFAULT_PROCESS_SCHEMA)
                for k, v in self._config.items()
            }
        return {}

    def _create_spawner(self, processes_config: Dict[str, Any]) -> ProcessSpawner:
        """Создать ProcessSpawner с текущими настройками."""
        return ProcessSpawner(
            processes_config=processes_config,
            stop_timeout=self._stop_timeout,
            on_shutdown=self._on_shutdown,
        )

    def run(self) -> None:
        """Запуск: launch_orchestrator + wait. Ctrl+C → stop."""
        processes_config = self._get_processes_config()
        self._spawner = self._create_spawner(processes_config)
        try:
            self._spawner.launch_orchestrator()
        except Exception as exc:
            error_mgr = self._spawner.get_error_manager() if self._spawner else None
            if error_mgr:
                error_mgr.log_exception(exc, "Failed to launch orchestrator", module="launcher")
            self.stop()
            raise
        self._log_info("ProcessManagerProcess started")
        self._log_info("System is running. Press Ctrl+C to stop.")
        try:
            self._spawner.wait()
        except KeyboardInterrupt:
            self.stop()

    def start(self) -> None:
        """Запуск (если run() не используется)."""
        processes_config = self._get_processes_config()
        if not processes_config:
            raise RuntimeError("No processes. Use add_process() or pass config.")
        self._spawner = self._create_spawner(processes_config)
        self._spawner.launch_orchestrator()

    def stop(self) -> None:
        """Остановка системы."""
        if self._spawner:
            self._log_info("Stopping system...")
            self._spawner.stop()
            self._log_info("System stopped")

    def wait(self) -> None:
        """Ожидание завершения."""
        if self._spawner:
            self._spawner.wait()

    def shutdown(self) -> None:
        """Алиас для stop()."""
        self.stop()

    def get_status(self) -> Dict[str, Any]:
        """Статус системы."""
        if not self._spawner:
            return {"spawner_running": False, "process": None}
        proc = self._spawner.get_process()
        status = {
            "spawner_running": self._spawner.is_running(),
            "process": {
                "name": proc.name if proc else None,
                "pid": proc.pid if proc and proc.is_alive() else None,
                "is_alive": proc.is_alive() if proc else False,
            } if proc else None,
        }
        if self._spawner.get_shared_resources():
            try:
                reg = self._spawner.get_shared_resources().process_state_registry
                status["registered_processes"] = reg.get_process_names()
            except Exception as e:
                self._log_warning(f"Failed to get process names: {e}")
        return status

    def get_stats(self) -> Dict[str, Any]:
        """Статистика системы."""
        if not self._spawner:
            return {"spawner": {"is_running": False}}
        return {
            "spawner": {
                "is_running": self._spawner.is_running(),
                "has_process": self._spawner.get_process() is not None,
            },
            "shared_resources": (
                self._spawner.get_shared_resources().get_stats()
                if self._spawner.get_shared_resources()
                else {}
            ),
        }


def main() -> int:
    """Пример: add_process() + run() + shutdown()."""
    launcher = SystemLauncher()
    launcher.run()
    launcher.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
