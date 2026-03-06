#!/usr/bin/env python3
"""
Главный запускатель системы процессов (Refactored).

Предоставляет удобный интерфейс для запуска и управления всей системой процессов.
Использует ProcessManagerBootstrap для запуска ProcessManagerProcess.

Поддерживает два режима:
- add_process(config) + run() — конфиги с методом build() -> (name, proc_dict)
- config в конструкторе — путь к файлу или готовый dict processes_config
"""

import sys
import signal
from typing import Optional, Union, Dict, Any, List, Tuple
from pathlib import Path

from ..bootstrap import ProcessManagerBootstrap


class ProcessBuilder:
    """
    Сборщик процесса: конфиг процесса + список воркеров.
    Используется для fluent API: create_process().add_worker().add_worker().add_process().
    """

    def __init__(self, config: Any):
        self._config = config
        self._workers: List[Tuple[str, Dict[str, Any]]] = []

    def add_worker(self, config: Any) -> "ProcessBuilder":
        """Добавить воркер. config: build() -> (name, worker_dict) или dict."""
        if hasattr(config, "build") and callable(config.build):
            name, w = config.build()
        elif isinstance(config, dict):
            name = config.get("name", config.get("worker_name", "unknown"))
            w = config
        else:
            raise TypeError(f"worker config must have build() or be dict, got {type(config)}")
        w_dict = w if isinstance(w, dict) else {}
        self._workers.append((name, w_dict))
        return self

    def build(self) -> Tuple[str, Dict[str, Any]]:
        """Вернуть (process_name, proc_dict) для ProcessManager."""
        if hasattr(self._config, "build") and callable(self._config.build):
            name, proc_dict = self._config.build()
        elif isinstance(self._config, dict):
            name = self._config.get("name", self._config.get("process_name", "unknown"))
            proc_dict = dict(self._config)
        else:
            raise TypeError(f"process config must have build() or be dict, got {type(self._config)}")
        if self._workers:
            proc_dict.setdefault("workers", {})
            for w_name, w_dict in self._workers:
                proc_dict["workers"][w_name] = w_dict
        return (name, proc_dict)


class SystemLauncher:
    """
    Главный запускатель системы процессов (Refactored).
    
    Предоставляет удобный интерфейс для:
    - Запуска ProcessManagerProcess через ProcessManagerBootstrap
    - Остановки системы
    - Обработки сигналов
    - add_process() для регистрации процессов с build() -> (name, proc_dict)
    
    Использует новую архитектуру с ProcessManagerProcess.
    """
    
    def __init__(
        self,
        config: Optional[Union[str, Path, Dict[str, Any]]] = None,
        bootstrap: Optional[ProcessManagerBootstrap] = None
    ):
        """
        Инициализация запускателя системы.
        
        Args:
            config: Конфигурация процессов (путь к файлу или словарь)
            bootstrap: ProcessManagerBootstrap (если None, создается в run())
        """
        self._config = config
        self._processes: List[Tuple[str, Dict[str, Any]]] = []
        self.bootstrap: Optional[ProcessManagerBootstrap] = None
        if bootstrap is not None:
            self.bootstrap = bootstrap
        elif config is not None:
            self.bootstrap = ProcessManagerBootstrap(config=config)
        self.setup_signal_handlers()

    def create_process(self, config: Any) -> ProcessBuilder:
        """Создать сборщик процесса. Цепочка: add_worker().add_worker().add_process()."""
        return ProcessBuilder(config)

    def add_process(self, config: Any) -> "SystemLauncher":
        """
        Добавить процесс. Принимает ProcessBuilder, config с build() или dict.
        
        Args:
            config: ProcessBuilder, объект с build() или dict {name: proc_dict}
        """
        if isinstance(config, ProcessBuilder):
            name, proc_dict = config.build()
            self._processes.append((name, proc_dict))
        elif hasattr(config, "build") and callable(config.build):
            name, proc_dict = config.build()
            self._processes.append((name, proc_dict))
        elif isinstance(config, dict):
            name = config.get("name", config.get("process_name", "unknown"))
            proc_dict = config.copy()
            proc_dict.setdefault("name", name)
            self._processes.append((name, proc_dict))
        else:
            raise TypeError(f"config must have build() or be dict, got {type(config)}")
        return self

    def _build_processes_config(self) -> Dict[str, Dict[str, Any]]:
        """Собрать processes_config из _processes."""
        return {name: proc_dict for name, proc_dict in self._processes}

    def run(self):
        """Запуск: start() + wait(). Создаёт bootstrap из add_process() если не задан."""
        if self.bootstrap is None and self._processes:
            processes_config = self._build_processes_config()
            self.bootstrap = ProcessManagerBootstrap(config=processes_config)
        elif self.bootstrap is None and self._config is not None:
            self.bootstrap = ProcessManagerBootstrap(config=self._config)
        elif self.bootstrap is None:
            self.bootstrap = ProcessManagerBootstrap(config={})
        self.start()
        try:
            self.wait()
        except KeyboardInterrupt:
            self.stop()

    def shutdown(self):
        """Остановка и освобождение ресурсов (bootstrap.stop() вызывает shared_resources.shutdown())."""
        self.stop()
    
    def setup_signal_handlers(self):
        """Настройка обработчиков сигналов для graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов остановки."""
        print(f"\n[*] Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)

    def start(self):
        """Запуск системы. Вызывать после run() или при наличии bootstrap."""
        if self.bootstrap is None:
            raise RuntimeError("No bootstrap. Use add_process() + run() or pass config to constructor.")
        print("[*] Starting ProcessManagerProcess...")
        success = self.bootstrap.start()
        if not success:
            raise RuntimeError("Failed to start ProcessManagerProcess")
        
        # Вывод информации о запущенном ProcessManagerProcess
        if self.bootstrap.process_manager_process:
            print(f"\n[*] ProcessManagerProcess started:")
            status = "[+]" if self.bootstrap.process_manager_process.is_alive() else "[-]"
            print(f"  {status} {self.bootstrap.process_manager_process.name} (PID: {self.bootstrap.process_manager_process.pid})")
        print("\n[*] System is running. Press Ctrl+C to stop.")
    
    def stop(self):
        """Остановка системы"""
        if self.bootstrap is None:
            return
        print("\n[*] Stopping system...")
        self.bootstrap.stop()
        print("[OK] System stopped")

    def wait(self):
        """Ожидание завершения работы"""
        if self.bootstrap is None:
            return
        try:
            self.bootstrap.wait()
        except KeyboardInterrupt:
            self.stop()

    def get_status(self) -> dict:
        """
        Получить статус системы.
        
        Returns:
            Dict: Статус ProcessManagerProcess и информация о системе
        """
        if self.bootstrap is None:
            return {'bootstrap_running': False, 'process_manager_process': None}
        status = {
            'bootstrap_running': self.bootstrap.is_running(),
            'process_manager_process': None
        }
        if self.bootstrap.process_manager_process:
            status['process_manager_process'] = {
                'name': self.bootstrap.process_manager_process.name,
                'pid': self.bootstrap.process_manager_process.pid,
                'is_alive': self.bootstrap.process_manager_process.is_alive()
            }
        
        # Получаем информацию о процессах из shared_resources
        if self.bootstrap.shared_resources:
            registered_processes = (
                self.bootstrap.shared_resources.process_state_registry.get_process_names()
            )
            status['registered_processes'] = registered_processes
        
        return status
    
    def get_stats(self) -> dict:
        """
        Получить статистику системы.
        
        Returns:
            Dict: Полная статистика системы
        """
        if self.bootstrap is None:
            return {'bootstrap': {'is_running': False, 'has_process_manager_process': False}, 'shared_resources': {}}
        stats = {
            'bootstrap': {
                'is_running': self.bootstrap.is_running(),
                'has_process_manager_process': self.bootstrap.process_manager_process is not None
            },
            'shared_resources': {}
        }
        
        # Получаем статистику из shared_resources
        if self.bootstrap.shared_resources:
            try:
                stats['shared_resources'] = self.bootstrap.shared_resources.get_stats()
            except Exception:
                pass
        
        return stats


def main():
    """Пример: add_process() + run() + shutdown(). Без add_process — пустая система."""
    launcher = SystemLauncher()
    # launcher.add_process(SomeConfig())
    launcher.run()
    launcher.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

