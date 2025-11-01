import threading
import time
import queue
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
import traceback

class WorkerStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"

class WorkerManager:
    """
    Независимый менеджер для управления worker'ами.
    Отвечает только за создание, запуск, остановку и мониторинг worker'ов.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.is_running = False
        
        # Реестр worker'ов
        self.workers: Dict[str, Dict] = {}
        
        # Очередь для внутренних команд (если нужно)
        self.internal_queue = queue.Queue()
        
        # Callback'и для событий (опционально)
        self.event_callbacks = {
            'worker_started': [],
            'worker_stopped': [],
            'worker_error': [],
            'worker_created': [],
            'worker_destroyed': []
        }
    
    def start(self):
        """Запуск менеджера worker'ов"""
        self.is_running = True
        self._log_event(f"WorkerManager started")
        
    def stop(self):
        """Остановка менеджера worker'ов"""
        self.is_running = False
        self._log_event(f"WorkerManager stopping...")
        
        # Останавливаем всех worker'ов
        self.stop_all_workers()
        
        self._log_event(f"WorkerManager stopped")
    
    def create_worker(self, 
                     worker_name: str, 
                     target: Callable,
                     auto_start: bool = False,
                     daemon: bool = True,
                     **worker_config) -> bool:
        """
        Создание нового worker'а
        
        Args:
            worker_name: Уникальное имя worker'а
            target: Функция для выполнения (должна принимать stop_event)
            auto_start: Запускать ли автоматически
            daemon: Демонический ли поток
            **worker_config: Дополнительная конфигурация worker'а
            
        Returns:
            bool: Успешно ли создан worker
        """
        if worker_name in self.workers:
            self._log_event(f"Worker {worker_name} already exists", level="WARNING")
            return False
        
        try:
            # Создаем события управления
            stop_event = threading.Event()
            pause_event = threading.Event()
            
            # Создаем поток
            thread = threading.Thread(
                name=f"{self.name}_{worker_name}",
                target=self._worker_wrapper,
                args=(worker_name, target, stop_event, pause_event),
                daemon=daemon
            )
            
            # Сохраняем информацию о worker'е
            self.workers[worker_name] = {
                'thread': thread,
                'stop_event': stop_event,
                'pause_event': pause_event,
                'target': target,
                'status': WorkerStatus.STOPPED,
                'daemon': daemon,
                'config': worker_config,
                'created_time': time.time(),
                'started_time': None,
                'error_count': 0,
                'last_error': None
            }
            
            self._fire_event('worker_created', worker_name)
            self._log_event(f"Worker {worker_name} created")
            
            # Автозапуск если требуется
            if auto_start:
                return self.start_worker(worker_name)
                
            return True
            
        except Exception as e:
            self._log_event(f"Error creating worker {worker_name}: {e}", level="ERROR")
            return False
    
    def _worker_wrapper(self, 
                       worker_name: str, 
                       target: Callable, 
                       stop_event: threading.Event,
                       pause_event: threading.Event):
        """
        Обертка для выполнения worker'а с обработкой ошибок
        """
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return
            
        try:
            worker_info['status'] = WorkerStatus.RUNNING
            worker_info['started_time'] = time.time()
            worker_info['error_count'] = 0
            worker_info['last_error'] = None
            
            self._fire_event('worker_started', worker_name)
            self._log_event(f"Worker {worker_name} started")
            
            # Выполняем целевую функцию
            target(stop_event, pause_event)
            
        except Exception as e:
            worker_info['error_count'] += 1
            worker_info['last_error'] = str(e)
            worker_info['status'] = WorkerStatus.ERROR
            
            error_traceback = traceback.format_exc()
            self._log_event(f"Worker {worker_name} error: {e}\n{error_traceback}", level="ERROR")
            self._fire_event('worker_error', worker_name, e, error_traceback)
            
        finally:
            worker_info['status'] = WorkerStatus.STOPPED
            self._fire_event('worker_stopped', worker_name)
            self._log_event(f"Worker {worker_name} stopped")
    
    def start_worker(self, worker_name: str) -> bool:
        """Запуск worker'а"""
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            self._log_event(f"Worker {worker_name} not found", level="WARNING")
            return False
        
        if worker_info['status'] == WorkerStatus.RUNNING:
            self._log_event(f"Worker {worker_name} already running", level="WARNING")
            return True
        
        try:
            # Сбрасываем события
            worker_info['stop_event'].clear()
            worker_info['pause_event'].clear()
            
            # Запускаем поток
            worker_info['thread'].start()
            return True
            
        except Exception as e:
            self._log_event(f"Error starting worker {worker_name}: {e}", level="ERROR")
            return False
    
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановка worker'а"""
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            self._log_event(f"Worker {worker_name} not found", level="WARNING")
            return False
        
        if worker_info['status'] != WorkerStatus.RUNNING:
            self._log_event(f"Worker {worker_name} not running", level="WARNING")
            return True
        
        try:
            worker_info['status'] = WorkerStatus.STOPPING
            worker_info['stop_event'].set()
            
            # Ждем завершения
            if worker_info['thread'].is_alive():
                worker_info['thread'].join(timeout=timeout)
                
                if worker_info['thread'].is_alive():
                    self._log_event(f"Worker {worker_name} didn't stop in time", level="WARNING")
                    return False
            
            worker_info['status'] = WorkerStatus.STOPPED
            return True
            
        except Exception as e:
            self._log_event(f"Error stopping worker {worker_name}: {e}", level="ERROR")
            return False
    
    def stop_all_workers(self, timeout: float = 5.0) -> Dict[str, bool]:
        """Остановка всех worker'ов"""
        results = {}
        
        for worker_name in list(self.workers.keys()):
            results[worker_name] = self.stop_worker(worker_name, timeout)
            
        return results
    
    def restart_worker(self, worker_name: str) -> bool:
        """Перезапуск worker'а"""
        if not self.stop_worker(worker_name):
            return False
        
        # Небольшая задержка перед перезапуском
        time.sleep(0.1)
        
        return self.start_worker(worker_name)
    
    def pause_worker(self, worker_name: str) -> bool:
        """Пауза worker'а"""
        worker_info = self.workers.get(worker_name)
        if not worker_info or worker_info['status'] != WorkerStatus.RUNNING:
            return False
        
        worker_info['pause_event'].set()
        self._log_event(f"Worker {worker_name} paused")
        return True
    
    def resume_worker(self, worker_name: str) -> bool:
        """Возобновление worker'а"""
        worker_info = self.workers.get(worker_name)
        if not worker_info or worker_info['status'] != WorkerStatus.RUNNING:
            return False
        
        worker_info['pause_event'].clear()
        self._log_event(f"Worker {worker_name} resumed")
        return True
    
    def remove_worker(self, worker_name: str) -> bool:
        """Удаление worker'а (после остановки)"""
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        # Сначала останавливаем, если работает
        if worker_info['status'] == WorkerStatus.RUNNING:
            self.stop_worker(worker_name)
        
        # Удаляем из реестра
        del self.workers[worker_name]
        self._fire_event('worker_destroyed', worker_name)
        self._log_event(f"Worker {worker_name} removed")
        
        return True
    
    def get_worker_status(self, worker_name: str) -> Optional[Dict[str, Any]]:
        """Получение статуса worker'а"""
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return None
        
        status = worker_info['status'].value
        is_alive = worker_info['thread'].is_alive() if worker_info['thread'] else False
        
        # Если поток умер, но статус не STOPPED, обновляем статус
        if not is_alive and status != WorkerStatus.STOPPED.value:
            worker_info['status'] = WorkerStatus.STOPPED
            status = WorkerStatus.STOPPED.value
        
        return {
            'name': worker_name,
            'status': status,
            'is_alive': is_alive,
            'daemon': worker_info['daemon'],
            'error_count': worker_info['error_count'],
            'last_error': worker_info['last_error'],
            'created_time': worker_info['created_time'],
            'started_time': worker_info['started_time'],
            'running_time': time.time() - worker_info['started_time'] if worker_info['started_time'] else 0,
            'is_paused': worker_info['pause_event'].is_set() if worker_info['pause_event'] else False
        }
    
    def get_all_workers_status(self) -> Dict[str, Dict[str, Any]]:
        """Получение статуса всех worker'ов"""
        status = {}
        for worker_name in self.workers.keys():
            status[worker_name] = self.get_worker_status(worker_name)
        return status
    
    def get_running_workers(self) -> List[str]:
        """Получение списка запущенных worker'ов"""
        running = []
        for worker_name, worker_info in self.workers.items():
            if worker_info['status'] == WorkerStatus.RUNNING:
                running.append(worker_name)
        return running
    
    def get_stopped_workers(self) -> List[str]:
        """Получение списка остановленных worker'ов"""
        stopped = []
        for worker_name, worker_info in self.workers.items():
            if worker_info['status'] == WorkerStatus.STOPPED:
                stopped.append(worker_name)
        return stopped
    
    def worker_exists(self, worker_name: str) -> bool:
        """Проверка существования worker'а"""
        return worker_name in self.workers
    
    def is_worker_running(self, worker_name: str) -> bool:
        """Проверка, запущен ли worker"""
        worker_info = self.workers.get(worker_name)
        return worker_info and worker_info['status'] == WorkerStatus.RUNNING
    
    # Callback система для событий
    def register_callback(self, event_type: str, callback: Callable):
        """Регистрация callback'а для события"""
        if event_type in self.event_callbacks:
            self.event_callbacks[event_type].append(callback)
    
    def unregister_callback(self, event_type: str, callback: Callable):
        """Удаление callback'а для события"""
        if event_type in self.event_callbacks:
            if callback in self.event_callbacks[event_type]:
                self.event_callbacks[event_type].remove(callback)
    
    def _fire_event(self, event_type: str, *args, **kwargs):
        """Вызов всех callback'ов для события"""
        if event_type in self.event_callbacks:
            for callback in self.event_callbacks[event_type]:
                try:
                    callback(event_type, *args, **kwargs)
                except Exception as e:
                    self._log_event(f"Error in event callback {event_type}: {e}", level="ERROR")
    
    def _log_event(self, message: str, level: str = "INFO"):
        """Логирование событий (для интеграции с LoggerManager)"""
        # В реальном использовании это будет передано в LoggerManager
        # Сейчас просто выводим в консоль
        print(f"[WorkerManager {level}] {message}")
    
    # Методы для интеграции с ProcessModule
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса менеджера для мониторинга"""
        workers_status = self.get_all_workers_status()
        running_count = len(self.get_running_workers())
        stopped_count = len(self.get_stopped_workers())
        error_count = sum(1 for ws in workers_status.values() if ws and ws['status'] == WorkerStatus.ERROR.value)
        
        return {
            'running': self.is_running,
            'total_workers': len(self.workers),
            'running_workers': running_count,
            'stopped_workers': stopped_count,
            'workers_with_errors': error_count,
            'workers': workers_status
        }
    
    def is_ready(self) -> bool:
        """Проверка готовности менеджера"""
        return self.is_running
    

if __name__ == "__init__":
    # Создание менеджера
    worker_manager = WorkerManager("VideoProcessor")

    # Функции worker'ов
    def video_processing_worker(stop_event, pause_event):
        """Worker для обработки видео"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                # Имитация обработки видео
                print("Обрабатываю видео кадр...")
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Ошибка обработки видео: {e}")

    def data_analysis_worker(stop_event, pause_event):
        """Worker для анализа данных"""
        counter = 0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                # Имитация анализа данных
                print(f"Анализирую данные... {counter}")
                counter += 1
                time.sleep(1.0)
                
            except Exception as e:
                print(f"Ошибка анализа данных: {e}")


    if __name__ == "__main__":
        # Запуск менеджера
        worker_manager.start()

        # Создание worker'ов
        worker_manager.create_worker(
            "video_processor",
            video_processing_worker,
            auto_start=True,
            daemon=True
        )

        worker_manager.create_worker(
            "data_analyzer", 
            data_analysis_worker,
            auto_start=True,
            daemon=True
        )

        # Мониторинг статуса
        time.sleep(2)
        status = worker_manager.get_all_workers_status()
        print("Статус worker'ов:", status)

        # Управление worker'ами
        worker_manager.pause_worker("video_processor")
        time.sleep(1)
        worker_manager.resume_worker("video_processor")

        # Добавление callback'ов для событий
        def on_worker_event(event_type, worker_name, *args):
            print(f"Событие: {event_type}, Worker: {worker_name}")

        worker_manager.register_callback('worker_started', on_worker_event)
        worker_manager.register_callback('worker_stopped', on_worker_event)

        # Остановка
        time.sleep(3)
        worker_manager.stop_all_workers()
        worker_manager.stop()