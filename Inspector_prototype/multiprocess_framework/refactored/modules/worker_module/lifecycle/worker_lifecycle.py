"""
Жизненный цикл воркеров.

Управление созданием, запуском и остановкой воркеров.
"""

import threading
import time
import traceback
from typing import Callable, Optional

from ..core.thread_config import ThreadConfig, WorkerStatus


class WorkerLifecycle:
    """
    Управление жизненным циклом воркеров.
    
    Инкапсулирует логику создания, запуска и остановки воркеров.
    """
    
    def __init__(self, manager):
        """
        Инициализация управления жизненным циклом.
        
        Args:
            manager: Ссылка на WorkerManager
        """
        self.manager = manager
    
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: ThreadConfig,
        auto_start: bool = False
    ) -> bool:
        """
        Создание нового воркера (потока).
        
        Args:
            worker_name: Уникальное имя воркера
            target: Целевая функция для выполнения
            config: Конфигурация потока
            auto_start: Автоматический запуск после создания
            
        Returns:
            bool: True если создание успешно
        """
        # Проверка уникальности имени
        if self.manager._worker_registry.has(worker_name):
            return False
        
        # Проверка зависимостей
        # Зависимый воркер может быть создан, если базовый воркер существует
        # Базовый воркер должен быть запущен только если зависимый воркер запускается
        for dep in config.dependencies:
            if not self.manager._worker_registry.has(dep):
                return False
            # Если зависимый воркер запускается сразу (auto_start), базовый должен быть запущен
            if auto_start and not self.manager.is_worker_running(dep):
                return False
        
        # Создание событий для управления потоком
        stop_event = threading.Event()
        pause_event = threading.Event()
        
        # Создание потока с оберткой для обработки ошибок
        thread = threading.Thread(
            name=f"{self.manager.manager_name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, target, stop_event, pause_event),
            daemon=True
        )
        
        # Регистрация воркера
        success = self.manager._worker_registry.register(
            worker_name,
            target,
            config,
            thread,
            stop_event,
            pause_event
        )
        
        if not success:
            return False
        
        # Автоматический запуск, если требуется
        if auto_start:
            return self.start_worker(worker_name)
        
        return True
    
    def start_worker(self, worker_name: str) -> bool:
        """
        Запуск воркера.
        
        Args:
            worker_name: Имя воркера для запуска
            
        Returns:
            bool: True если запуск успешен
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False
        
        # Если воркер уже запущен, ничего не делаем
        if worker_info['status'] == WorkerStatus.RUNNING:
            return True
        
        # Если поток был завершен, создаем новый поток для перезапуска
        if not worker_info['thread'].is_alive():
            stop_event = threading.Event()
            pause_event = threading.Event()
            thread = threading.Thread(
                name=f"{self.manager.manager_name}_{worker_name}",
                target=self._worker_wrapper,
                args=(worker_name, worker_info['target'], stop_event, pause_event),
                daemon=True
            )
            worker_info['thread'] = thread
            worker_info['stop_event'] = stop_event
            worker_info['pause_event'] = pause_event
            
            # Увеличиваем restart_count только если воркер уже был запущен ранее
            if worker_info['has_been_started']:
                worker_info['restart_count'] += 1
            worker_info['has_been_started'] = True
            
            # Сброс событий и запуск потока
            worker_info['stop_event'].clear()
            worker_info['pause_event'].clear()
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
            worker_info['thread'].start()
        
        return True
    
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """
        Остановка воркера.
        
        Args:
            worker_name: Имя воркера для остановки
            timeout: Таймаут ожидания завершения потока
            
        Returns:
            bool: True если остановка успешна
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False
        
        self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPING)
        worker_info['stop_event'].set()
        
        # Ожидание завершения потока с таймаутом
        if worker_info['thread'].is_alive():
            worker_info['thread'].join(timeout=timeout)
        
        self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)
        return True
    
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """
        Перезапуск воркера.
        
        Args:
            worker_name: Имя воркера для перезапуска
            timeout: Таймаут ожидания остановки
            
        Returns:
            bool: True если перезапуск успешен
        """
        if not self.manager._worker_registry.has(worker_name):
            return False
        
        # Останавливаем воркер, если запущен
        worker_info = self.manager._worker_registry.get(worker_name)
        if worker_info and worker_info['status'] == WorkerStatus.RUNNING:
            self.stop_worker(worker_name, timeout)
        
        # Запускаем заново
        return self.start_worker(worker_name)
    
    def _worker_wrapper(
        self,
        worker_name: str,
        target: Callable,
        stop_event: threading.Event,
        pause_event: threading.Event
    ):
        """
        Обертка для выполнения целевой функции воркера.
        
        Args:
            worker_name: Имя воркера
            target: Целевая функция
            stop_event: Событие остановки
            pause_event: Событие паузы
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return
        
        start_time = time.time()
        worker_info['start_time'] = start_time
        
        should_restart = False
        error_occurred = False
        
        try:
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
            # Вызов целевой функции с событиями управления
            target(stop_event, pause_event)
            
            # Успешное завершение
            worker_info['successful_runs'] += 1
            
        except Exception as e:
            error_occurred = True
            self.manager._worker_registry.update_status(worker_name, WorkerStatus.ERROR)
            worker_info['last_error'] = str(e)
            worker_info['failed_runs'] += 1
            
            # Логирование ошибки через ObservableMixin
            self.manager._log_error(f"Worker '{worker_name}' error: {e}")
            traceback.print_exc()
            
            # Автоматический перезапуск при ошибке, если настроено
            config = worker_info['config']
            if config.restart_on_failure:
                if worker_info['restart_count'] < config.max_restarts:
                    should_restart = True
                    worker_info['restart_count'] += 1
                
        finally:
            end_time = time.time()
            run_duration = end_time - start_time
            worker_info['last_run_duration'] = run_duration
            worker_info['total_runtime'] += run_duration
            
            # Перезапуск после обновления метрик
            if should_restart:
                time.sleep(0.1)  # Небольшая задержка перед перезапуском
                self._restart_worker_internal(worker_name)
            else:
                # Не меняем статус если он ERROR и превышен лимит перезапусков
                if worker_info['status'] != WorkerStatus.ERROR:
                    self.manager._worker_registry.update_status(worker_name, WorkerStatus.STOPPED)
    
    def _restart_worker_internal(self, worker_name: str) -> bool:
        """
        Внутренний метод для перезапуска воркера после ошибки.
        
        Args:
            worker_name: Имя воркера для перезапуска
            
        Returns:
            bool: True если перезапуск успешен
        """
        worker_info = self.manager._worker_registry.get(worker_name)
        if not worker_info:
            return False
        
        # Создаем новый поток для перезапуска
        stop_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            name=f"{self.manager.manager_name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, worker_info['target'], stop_event, pause_event),
            daemon=True
        )
        worker_info['thread'] = thread
        worker_info['stop_event'] = stop_event
        worker_info['pause_event'] = pause_event
        
        # Сброс событий и запуск потока
        worker_info['stop_event'].clear()
        worker_info['pause_event'].clear()
        self.manager._worker_registry.update_status(worker_name, WorkerStatus.RUNNING)
        worker_info['has_been_started'] = True
        worker_info['thread'].start()
        return True

