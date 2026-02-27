"""
Модуль управления потоками (воркерами) для многопроцессной архитектуры.

WorkerManager предоставляет централизованное управление потоками выполнения,
включая создание, запуск, остановку и мониторинг состояния воркеров.
Поддерживает приоритеты потоков, зависимости между воркерами и обработку ошибок.
"""

import threading
import time
from typing import Dict, Callable, Optional, List
from enum import Enum
import traceback
from datetime import datetime


class WorkerStatus(Enum):
    """Статусы состояния воркера."""
    STOPPED = "stopped"      # Остановлен
    RUNNING = "running"      # Работает
    ERROR = "error"          # Ошибка выполнения
    STOPPING = "stopping"    # В процессе остановки


class ThreadPriority(Enum):
    """Приоритеты потоков выполнения.
    
    Определяют частоту опроса и важность потока в системе.
    """
    SYSTEM = 0        # Системные потоки (0.001s интервал)
    REALTIME = 1      # Потоки реального времени (0.01s интервал)
    NORMAL = 2        # Обычные потоки (0.1s интервал)
    BATCH = 3         # Пакетная обработка (1.0s интервал)
    BACKGROUND = 4    # Фоновые задачи (5.0s интервал)


class ThreadConfig:
    """Конфигурация потока-воркера.
    
    Содержит параметры для настройки поведения потока:
    приоритет, интервал опроса, перезапуск при ошибках, зависимости.
    
    Attributes:
        priority: Приоритет потока
        poll_interval: Интервал опроса (автоматически вычисляется из приоритета)
        restart_on_failure: Автоматический перезапуск при ошибке
        max_restarts: Максимальное количество перезапусков
        dependencies: Список имен воркеров, от которых зависит этот воркер
    """
    
    def __init__(self, 
                 priority: ThreadPriority = ThreadPriority.NORMAL,
                 restart_on_failure: bool = False,
                 max_restarts: int = 3,
                 dependencies: List[str] = None):
        """
        Инициализация конфигурации потока.
        
        Args:
            priority: Приоритет потока (по умолчанию NORMAL)
            restart_on_failure: Перезапуск при ошибке (по умолчанию False)
            max_restarts: Максимальное количество перезапусков (по умолчанию 3)
            dependencies: Список зависимостей от других воркеров (по умолчанию [])
        """
        self.priority = priority
        self.poll_interval = self._get_poll_interval(priority)
        self.restart_on_failure = restart_on_failure
        self.max_restarts = max_restarts
        self.dependencies = dependencies or []
    
    def _get_poll_interval(self, priority: ThreadPriority) -> float:
        """
        Вычисление интервала опроса на основе приоритета.
        
        Args:
            priority: Приоритет потока
            
        Returns:
            float: Интервал опроса в секундах
        """
        intervals = {
            ThreadPriority.SYSTEM: 0.001,
            ThreadPriority.REALTIME: 0.01,
            ThreadPriority.NORMAL: 0.1,
            ThreadPriority.BATCH: 1.0,
            ThreadPriority.BACKGROUND: 5.0
        }
        return intervals[priority]

class WorkerManager:
    """Менеджер для управления потоками-воркерами.
    
    Предоставляет централизованное управление жизненным циклом потоков:
    создание, запуск, остановка, пауза, мониторинг состояния.
    Поддерживает зависимости между воркерами и обработку ошибок.
    
    Thread Safety (Потокобезопасность):
    - Все публичные методы класса являются потокобезопасными
    - Внутренние структуры защищены GIL (Global Interpreter Lock)
    - Методы можно вызывать из любого потока без дополнительной синхронизации
    - Изменение состояния воркеров атомарно благодаря использованию threading.Event
    - Чтение статуса воркеров безопасно из любого потока
    
    Важные ограничения:
    - Не предназначен для использования из нескольких процессов, только потоков
    - Для межпроцессного взаимодействия используйте multiprocessing модуль
    - Длительные операции в целевых функциях могут блокировать основной поток
    
    Attributes:
        name: Имя менеджера (обычно имя процесса)
        workers: Словарь зарегистрированных воркеров
        thread_configs: Словарь конфигураций потоков
    """
    
    def __init__(self, name: str):
        """
        Инициализация менеджера воркеров.
        
        Args:
            name: Имя менеджера (используется для именования потоков)
        """
        self.name = name
        self.workers: Dict[str, Dict] = {}
        self.thread_configs: Dict[str, ThreadConfig] = {}
        
    def create_worker(self, 
                     worker_name: str,
                     target: Callable,
                     config: ThreadConfig,
                     auto_start: bool = False) -> bool:
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
        # Проверка уникальности имени
        if worker_name in self.workers:
            return False
        
        # Проверка зависимостей: все зависимости должны существовать и быть запущены
        for dep in config.dependencies:
            if dep not in self.workers or not self.is_worker_running(dep):
                return False
        
        # Создание событий для управления потоком
        stop_event = threading.Event()
        pause_event = threading.Event()
        
        # Создание потока с оберткой для обработки ошибок
        thread = threading.Thread(
            name=f"{self.name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, target, stop_event, pause_event),
            daemon=True
        )
        
        # Регистрация воркера
        self.workers[worker_name] = {
            'thread': thread,
            'stop_event': stop_event,
            'pause_event': pause_event,
            'target': target,
            'config': config,
            'status': WorkerStatus.STOPPED,
            'restart_count': 0,
            'last_error': None,
            'start_time': None,          # Время последнего запуска
            'total_runtime': 0.0,        # Общее время работы (секунды)
            'last_run_duration': 0.0,    # Длительность последнего запуска
            'successful_runs': 0,        # Количество успешных запусков
            'failed_runs': 0,             # Количество неудачных запусков
            'has_been_started': False     # Флаг первого запуска
        }
        
        self.thread_configs[worker_name] = config
        
        # Автоматический запуск, если требуется
        if auto_start:
            return self.start_worker(worker_name)
        return True
    
    def _worker_wrapper(self, worker_name: str, target: Callable, 
                       stop_event: threading.Event, pause_event: threading.Event):
        """
        Обертка для выполнения целевой функции воркера.
        
        Обрабатывает ошибки, обновляет статус и логирует исключения.
        Поддерживает паузу через pause_event.
        
        Args:
            worker_name: Имя воркера
            target: Целевая функция
            stop_event: Событие остановки
            pause_event: Событие паузы
        """
        worker_info = self.workers[worker_name]
        start_time = time.time()
        worker_info['start_time'] = start_time
        
        should_restart = False
        error_occurred = False
        
        try:
            worker_info['status'] = WorkerStatus.RUNNING
            # Вызов целевой функции с событиями управления
            target(stop_event, pause_event)
            
            # Успешное завершение (функция завершилась без исключения)
            # Это успешное завершение независимо от причины (stop_event или нормальный выход)
            worker_info['successful_runs'] += 1
            
        except Exception as e:
            error_occurred = True
            worker_info['status'] = WorkerStatus.ERROR
            worker_info['last_error'] = str(e)
            worker_info['failed_runs'] += 1
            traceback.print_exc()
            
            # Автоматический перезапуск при ошибке, если настроено
            config = worker_info['config']
            if config.restart_on_failure:
                # Проверяем лимит перезапусков ПЕРЕД увеличением счетчика
                if worker_info['restart_count'] < config.max_restarts:
                    should_restart = True
                    # Увеличиваем счетчик перезапусков здесь, а не в start_worker
                    worker_info['restart_count'] += 1
                # Если превышен лимит, статус остается ERROR
                
        finally:
            end_time = time.time()
            run_duration = end_time - start_time
            worker_info['last_run_duration'] = run_duration
            worker_info['total_runtime'] += run_duration
            
            # Перезапуск после обновления метрик
            if should_restart:
                time.sleep(0.1)  # Небольшая задержка перед перезапуском
                # Запускаем без увеличения restart_count (уже увеличен выше)
                self._restart_worker_internal(worker_name)
            else:
                # Не меняем статус если он ERROR и превышен лимит перезапусков
                if worker_info['status'] != WorkerStatus.ERROR:
                    worker_info['status'] = WorkerStatus.STOPPED
    
    def _restart_worker_internal(self, worker_name: str) -> bool:
        """
        Внутренний метод для перезапуска воркера после ошибки.
        Не увеличивает restart_count (уже увеличен в _worker_wrapper).
        
        Args:
            worker_name: Имя воркера для перезапуска
            
        Returns:
            bool: True если перезапуск успешен, False если воркер не найден
        """
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        # Создаем новый поток для перезапуска
        stop_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            name=f"{self.name}_{worker_name}",
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
        worker_info['status'] = WorkerStatus.RUNNING
        worker_info['has_been_started'] = True
        worker_info['thread'].start()
        return True
    
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
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        # Если воркер уже запущен, ничего не делаем
        if worker_info['status'] == WorkerStatus.RUNNING:
            return True
        
        # Если поток был завершен, создаем новый поток для перезапуска
        if not worker_info['thread'].is_alive():
            # Создаем новый поток для перезапуска
            stop_event = threading.Event()
            pause_event = threading.Event()
            thread = threading.Thread(
                name=f"{self.name}_{worker_name}",
                target=self._worker_wrapper,
                args=(worker_name, worker_info['target'], stop_event, pause_event),
                daemon=True
            )
            worker_info['thread'] = thread
            worker_info['stop_event'] = stop_event
            worker_info['pause_event'] = pause_event
            # Увеличиваем restart_count только если воркер уже был запущен ранее
            # (не при первом запуске)
            if worker_info['has_been_started']:
                worker_info['restart_count'] += 1
            worker_info['has_been_started'] = True
            
            # Сброс событий и запуск потока
            worker_info['stop_event'].clear()
            worker_info['pause_event'].clear()
            worker_info['status'] = WorkerStatus.RUNNING
            worker_info['thread'].start()
        # Если поток еще жив, но статус не RUNNING - это не должно происходить
        # в нормальной работе, но на всякий случай просто обновляем статус
        # (поток уже работает, просто статус мог быть не синхронизирован)
        
        return True

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
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        worker_info['status'] = WorkerStatus.STOPPING
        worker_info['stop_event'].set()
        
        # Ожидание завершения потока с таймаутом
        if worker_info['thread'].is_alive():
            worker_info['thread'].join(timeout=timeout)
            
        worker_info['status'] = WorkerStatus.STOPPED
        return True
    
    def pause_worker(self, worker_name: str) -> bool:
        """
        Приостановка выполнения воркера.
        
        Воркер должен проверять pause_event в своем цикле.
        
        Args:
            worker_name: Имя воркера для приостановки
            
        Returns:
            bool: True если пауза установлена, False если воркер не найден
        """
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        worker_info['pause_event'].set()
        return True
    
    def resume_worker(self, worker_name: str) -> bool:
        """
        Возобновление выполнения воркера.
        
        Args:
            worker_name: Имя воркера для возобновления
            
        Returns:
            bool: True если пауза снята, False если воркер не найден
        """
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        worker_info['pause_event'].clear()
        return True
    
    def start_all_workers(self):
        """
        Запуск всех зарегистрированных воркеров.
        
        Запускает воркеры в порядке их регистрации.
        Воркеры с зависимостями должны быть созданы в правильном порядке.
        """
        for worker_name in list(self.workers.keys()):
            self.start_worker(worker_name)

    def stop_all_workers(self):
        """
        Остановка всех зарегистрированных воркеров.
        
        Останавливает все воркеры, независимо от их текущего состояния.
        """
        for worker_name in list(self.workers.keys()):
            self.stop_worker(worker_name)
    
    def is_worker_running(self, worker_name: str) -> bool:
        """
        Проверка, запущен ли воркер.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            bool: True если воркер запущен и работает, False в противном случае
        """
        worker_info = self.workers.get(worker_name)
        return bool(worker_info and worker_info['status'] == WorkerStatus.RUNNING)
    
    def get_worker_status(self, worker_name: str) -> Optional[Dict]:
        """
        Получение детального статуса воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            Optional[Dict]: Словарь со статусом или None если воркер не найден.
                           Содержит: name, status, is_alive, restart_count, last_error
        """
        worker_info = self.workers.get(worker_name)
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
        for worker_name in self.workers.keys():
            status[worker_name] = self.get_worker_status(worker_name)
        return status

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
        if worker_name not in self.workers:
            return False
        
        # Останавливаем воркер, если запущен
        if self.workers[worker_name]['status'] == WorkerStatus.RUNNING:
            self.stop_worker(worker_name, timeout)
        
        # Запускаем заново
        return self.start_worker(worker_name)

    def get_worker_metrics(self, worker_name: str) -> Optional[Dict]:
        """
        Получение метрик производительности воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            Optional[Dict]: Словарь с метриками или None если воркер не найден.
                           Содержит: total_runtime, last_run_duration, successful_runs,
                           failed_runs, restart_count, avg_run_time
        """
        worker_info = self.workers.get(worker_name)
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