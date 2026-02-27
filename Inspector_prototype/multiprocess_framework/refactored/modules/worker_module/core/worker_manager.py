"""
Менеджер для управления потоками-воркерами (Refactored).

Наследуется от BaseManager и использует ObservableMixin для логирования и мониторинга.
"""

import time
from typing import Dict, Callable, Optional, List

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager

from .thread_config import ThreadConfig, ThreadPriority, WorkerStatus
from ..registry import WorkerRegistry
from ..lifecycle import WorkerLifecycle


class WorkerManager(BaseManager, ObservableMixin):
    """
    Менеджер для управления потоками-воркерами (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Предоставляет централизованное управление жизненным циклом потоков:
    создание, запуск, остановка, пауза, мониторинг состояния.
    Поддерживает зависимости между воркерами и обработку ошибок.
    
    Thread Safety (Потокобезопасность):
    - Все публичные методы класса являются потокобезопасными
    - Внутренние структуры защищены GIL (Global Interpreter Lock)
    - Методы можно вызывать из любого потока без дополнительной синхронизации
    
    Attributes:
        manager_name: Имя менеджера (обычно имя процесса)
        _worker_registry: Реестр воркеров (не путать с _registry из ObservableMixin)
        _lifecycle: Управление жизненным циклом воркеров
    """
    
    def __init__(self, manager_name: str, process=None):
        """
        Инициализация менеджера воркеров.
        
        Args:
            manager_name: Имя менеджера (используется для именования потоков)
            process: Ссылка на родительский процесс (опционально)
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin (без менеджеров, так как WorkerManager сам является менеджером)
        # ВАЖНО: ObservableMixin создает self._registry как ManagerRegistry
        ObservableMixin.__init__(
            self,
            managers={},
            config={},
            auto_proxy=True  # Автоматические прокси-методы для логирования
        )
        
        # Компоненты менеджера
        # ВАЖНО: Используем _worker_registry вместо _registry, чтобы не конфликтовать с ObservableMixin._registry
        self._worker_registry = WorkerRegistry()
        self._lifecycle = WorkerLifecycle(self)
        
        # Синоним для совместимости со старым API
        self.name = manager_name
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация менеджера воркеров.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            self.is_initialized = True
            self._log_info(f"WorkerManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize WorkerManager '{self.manager_name}': {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы менеджера воркеров.
        
        Останавливает все воркеры перед завершением.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Останавливаем все воркеры
            self.stop_all_workers()
            
            self.is_initialized = False
            self._log_info(f"WorkerManager '{self.manager_name}' shut down")
            return True
        except Exception as e:
            self._log_error(f"Error during shutdown of WorkerManager '{self.manager_name}': {e}")
            return False
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СОЗДАНИЕ И УПРАВЛЕНИЕ ВОРКЕРАМИ
    # ========================================================================
    
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: ThreadConfig,
        auto_start: bool = False
    ) -> bool:
        """
        Создание нового воркера (потока).
        
        Проверяет уникальность имени и зависимости перед созданием.
        Создает поток с событиями остановки и паузы.
        
        Args:
            worker_name: Уникальное имя воркера
            target: Целевая функция для выполнения (должна принимать stop_event, pause_event)
            config: Конфигурация потока
            auto_start: Автоматический запуск после создания (по умолчанию False)
            
        Returns:
            bool: True если создание успешно, False если воркер уже существует
                  или не выполнены зависимости
                  
        Example:
            def my_worker(stop_event, pause_event):
                while not stop_event.is_set():
                    if pause_event.is_set():
                        time.sleep(0.1)
                        continue
                    # Работа воркера
                    time.sleep(0.1)
            
            config = ThreadConfig(priority=ThreadPriority.NORMAL)
            manager.create_worker("worker1", my_worker, config, auto_start=True)
        """
        success = self._lifecycle.create_worker(worker_name, target, config, auto_start)
        if success:
            self._log_info(f"Worker '{worker_name}' created")
        else:
            self._log_warning(f"Failed to create worker '{worker_name}'")
        return success
    
    def start_worker(self, worker_name: str) -> bool:
        """
        Запуск воркера.
        
        Если воркер уже запущен, возвращает True без повторного запуска.
        Если поток был завершен, создает новый поток для перезапуска.
        
        Args:
            worker_name: Имя воркера для запуска
            
        Returns:
            bool: True если запуск успешен, False если воркер не найден
        """
        success = self._lifecycle.start_worker(worker_name)
        if success:
            self._log_info(f"Worker '{worker_name}' started")
        return success
    
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """
        Остановка воркера.
        
        Устанавливает событие остановки и ждет завершения потока.
        Если поток не завершился за timeout, продолжает выполнение.
        
        Args:
            worker_name: Имя воркера для остановки
            timeout: Таймаут ожидания завершения потока в секундах (по умолчанию 5.0)
            
        Returns:
            bool: True если воркер найден и остановка инициирована, False если воркер не найден
        """
        success = self._lifecycle.stop_worker(worker_name, timeout)
        if success:
            self._log_info(f"Worker '{worker_name}' stopped")
        return success
    
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """
        Перезапуск воркера.
        
        Останавливает воркер (если запущен) и запускает заново.
        
        Args:
            worker_name: Имя воркера для перезапуска
            timeout: Таймаут ожидания остановки в секундах (по умолчанию 5.0)
            
        Returns:
            bool: True если перезапуск успешен, False если воркер не найден
        """
        success = self._lifecycle.restart_worker(worker_name, timeout)
        if success:
            self._log_info(f"Worker '{worker_name}' restarted")
        return success
    
    def pause_worker(self, worker_name: str) -> bool:
        """
        Приостановка выполнения воркера.
        
        Воркер должен проверять pause_event в своем цикле.
        
        Args:
            worker_name: Имя воркера для приостановки
            
        Returns:
            bool: True если пауза установлена, False если воркер не найден
        """
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return False
        worker_info['pause_event'].set()
        self._log_info(f"Worker '{worker_name}' paused")
        return True
    
    def resume_worker(self, worker_name: str) -> bool:
        """
        Возобновление выполнения воркера.
        
        Args:
            worker_name: Имя воркера для возобновления
            
        Returns:
            bool: True если пауза снята, False если воркер не найден
        """
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return False
        worker_info['pause_event'].clear()
        self._log_info(f"Worker '{worker_name}' resumed")
        return True
    
    def start_all_workers(self):
        """
        Запуск всех зарегистрированных воркеров.
        
        Запускает воркеры в порядке их регистрации.
        Воркеры с зависимостями должны быть созданы в правильном порядке.
        """
        for worker_name in self._worker_registry.get_all_names():
            self.start_worker(worker_name)
        self._log_info("All workers started")
    
    def stop_all_workers(self):
        """
        Остановка всех зарегистрированных воркеров.
        
        Останавливает все воркеры, независимо от их текущего состояния.
        """
        for worker_name in self._worker_registry.get_all_names():
            self.stop_worker(worker_name)
        self._log_info("All workers stopped")
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - МОНИТОРИНГ И СТАТУС
    # ========================================================================
    
    def is_worker_running(self, worker_name: str) -> bool:
        """
        Проверка, запущен ли воркер.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            bool: True если воркер запущен и работает, False в противном случае
        """
        worker_info = self._worker_registry.get(worker_name)
        return bool(worker_info and worker_info['status'] == WorkerStatus.RUNNING)
    
    def get_worker_status(self, worker_name: str) -> Optional[Dict]:
        """
        Получение детального статуса воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            Optional[Dict]: Словарь со статусом или None если воркер не найден.
                           Содержит: name, status, is_alive, restart_count, last_error, metrics
        """
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return None
        
        return {
            'name': worker_name,
            'status': worker_info['status'].value,
            'is_alive': worker_info['thread'].is_alive(),
            'restart_count': worker_info['restart_count'],
            'last_error': worker_info['last_error'],
            'metrics': self.get_worker_metrics(worker_name)
        }
    
    def get_all_workers_status(self) -> Dict[str, Dict]:
        """
        Получение статусов всех воркеров.
        
        Returns:
            Dict[str, Dict]: Словарь статусов всех воркеров, ключ - имя воркера
        """
        status = {}
        for worker_name in self._worker_registry.get_all_names():
            status[worker_name] = self.get_worker_status(worker_name)
        return status
    
    def get_worker_metrics(self, worker_name: str) -> Optional[Dict]:
        """
        Получение метрик производительности воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            Optional[Dict]: Словарь с метриками или None если воркер не найден.
                           Содержит: total_runtime, last_run_duration, successful_runs,
                           failed_runs, restart_count, avg_run_time, uptime
        """
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return None
        
        # Для работающего воркера добавляем текущее время работы к total_runtime
        current_runtime = worker_info['total_runtime']
        if (worker_info['status'] == WorkerStatus.RUNNING and 
            worker_info['start_time'] is not None):
            # Добавляем время текущего запуска
            current_run_duration = time.time() - worker_info['start_time']
            current_runtime = worker_info['total_runtime'] + current_run_duration
        
        total_runs = worker_info['successful_runs'] + worker_info['failed_runs']
        avg_run_time = current_runtime / total_runs if total_runs > 0 else 0
        
        return {
            'total_runtime': round(current_runtime, 3),
            'last_run_duration': round(worker_info['last_run_duration'], 3),
            'successful_runs': worker_info['successful_runs'],
            'failed_runs': worker_info['failed_runs'],
            'restart_count': worker_info['restart_count'],
            'avg_run_time': round(avg_run_time, 3),
            'start_time': worker_info['start_time'],
            'uptime': round(time.time() - worker_info['start_time'], 3) if worker_info['start_time'] else 0
        }
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СТАТИСТИКА (из BaseManager)
    # ========================================================================
    
    def get_stats(self) -> Dict[str, any]:
        """
        Получение статистики менеджера воркеров.
        
        Returns:
            Dict[str, Any]: Словарь со статистикой менеджера и всех воркеров
        """
        # Базовая статистика из BaseManager
        stats = super().get_stats()
        
        # Добавляем специфичную статистику воркеров
        stats.update({
            'workers_count': len(self._worker_registry.get_all_names()),
            'workers_status': self.get_all_workers_status(),
            'running_workers': sum(
                1 for name in self._worker_registry.get_all_names()
                if self.is_worker_running(name)
            )
        })
        
        return stats
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def has_worker(self, worker_name: str) -> bool:
        """
        Проверка наличия воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            bool: True если воркер зарегистрирован
        """
        return self._worker_registry.has(worker_name)
    
    def list_workers(self) -> List[str]:
        """
        Получение списка имен всех воркеров.
        
        Returns:
            List[str]: Список имен воркеров
        """
        return self._worker_registry.get_all_names()

