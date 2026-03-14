"""
Мониторинг состояний процессов в ProcessManager.

Наследуется от ProcessModule для использования всей инфраструктуры:
- Менеджеры и адаптеры через ManagersComponents
- Коммуникация через ProcessCommunication
- Логирование через LoggerAdapter
- WorkerManager для потоков
"""

import time
from typing import Dict, Any, Optional
from multiprocessing import Event

from ...Process_module.process_module import ProcessModule
from ...Worker_module.worker_manager import ThreadConfig, ThreadPriority


class ProcessMonitor(ProcessModule):
    """
    Мониторинг состояний процессов.
    
    Наследуется от ProcessModule для использования всей инфраструктуры.
    Работает в основном процессе ProcessManager, отслеживает изменения
    состояний процессов и уведомляет их через broadcast сообщения.
    """
    
    def __init__(
        self,
        shared_resources,
        stop_event: Event,
        queue_registry=None,
        logger=None,
        poll_interval: float = 0.5
    ):
        """
        Инициализация монитора процессов.
        
        Args:
            shared_resources: SharedResourcesManager с ProcessStateRegistry
            stop_event: Событие остановки
            queue_registry: QueueRegistry для отправки сообщений (опционально)
            logger: LoggerManager для логирования (опционально)
            poll_interval: Интервал опроса состояний в секундах
        """
        # Инициализируем ProcessModule
        super().__init__(
            name="ProcessMonitor",
            shared_resources=shared_resources,
            config={
                "managers": {
                    "logger": {"enabled": True},
                    "worker": {"enabled": True},
                    "router": {"enabled": True}
                }
            }
        )
        
        self.stop_event = stop_event
        self.queue_registry = queue_registry
        self.poll_interval = poll_interval
        
        # Кэш предыдущих состояний для отслеживания изменений
        self.previous_states: Dict[str, Dict[str, Any]] = {}
        
        # Флаг запуска
        self._monitoring = False
    
    def _init_application_threads(self):
        """Инициализация потока мониторинга"""
        # Поток мониторинга будет создан в start()
        pass
    
    def start(self):
        """Запуск мониторинга состояний процессов"""
        if self._monitoring:
            self.log("WARNING", "Monitor already running", "monitor")
            return
        
        self.log("INFO", "Starting process state monitor", "monitor")
        
        # Используем WorkerManager для создания потока мониторинга
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker(
            "state_monitor",
            self._monitoring_loop,
            config,
            auto_start=True
        )
        
        self._monitoring = True
    
    def stop(self):
        """Остановка мониторинга"""
        if not self._monitoring:
            return
        
        self.log("INFO", "Stopping process state monitor", "monitor")
        
        # Останавливаем все воркеры (включая поток мониторинга)
        super().stop()
        
        self._monitoring = False
    
    def _monitoring_loop(self, stop_event: Event, pause_event: Event):
        """
        Основной цикл мониторинга состояний процессов.
        
        Args:
            stop_event: Событие остановки потока
            pause_event: Событие паузы (не используется)
        """
        self.log("INFO", "Process monitor loop started", "monitor")
        
        while not stop_event.is_set() and not self.stop_event.is_set():
            try:
                # Получаем все состояния процессов
                all_states = self.shared_resources.get_all_process_states()
                
                # Проверяем изменения состояний
                for process_name, current_state in all_states.items():
                    previous_state = self.previous_states.get(process_name)
                    
                    # Если состояние изменилось
                    if previous_state != current_state:
                        self._handle_state_change(process_name, previous_state, current_state)
                        self.previous_states[process_name] = current_state.copy()
                
                # Проверяем новые процессы
                current_processes = set(all_states.keys())
                previous_processes = set(self.previous_states.keys())
                new_processes = current_processes - previous_processes
                
                for process_name in new_processes:
                    self.log("INFO", f"New process detected: {process_name}", "monitor")
                    self.previous_states[process_name] = all_states[process_name].copy()
                
                # Проверяем удаленные процессы
                removed_processes = previous_processes - current_processes
                for process_name in removed_processes:
                    self.log("INFO", f"Process removed: {process_name}", "monitor")
                    if process_name in self.previous_states:
                        del self.previous_states[process_name]
                
                # Ждем перед следующим опросом
                time.sleep(self.poll_interval)
                
            except Exception as e:
                self.log("ERROR", f"Error in monitoring loop: {e}", "monitor")
                import traceback
                traceback.print_exc()
                time.sleep(self.poll_interval)
        
        self.log("INFO", "Process monitor loop stopped", "monitor")
    
    def _handle_state_change(
        self,
        process_name: str,
        previous_state: Optional[Dict[str, Any]],
        current_state: Dict[str, Any]
    ):
        """
        Обработка изменения состояния процесса.
        
        Args:
            process_name: Имя процесса
            previous_state: Предыдущее состояние (None для новых процессов)
            current_state: Текущее состояние
        """
        current_status = current_state.get("status", "unknown")
        previous_status = previous_state.get("status", "unknown") if previous_state else None
        
        # Если статус изменился
        if previous_status != current_status:
            self.log("INFO", f"Process '{process_name}' status changed: {previous_status} -> {current_status}", "monitor")
            
            # Отправляем broadcast сообщение о изменении статуса
            self._broadcast_status_change(process_name, previous_status, current_status, current_state)
    
    def _broadcast_status_change(
        self,
        process_name: str,
        old_status: Optional[str],
        new_status: str,
        current_state: Dict[str, Any]
    ):
        """
        Отправка broadcast сообщения об изменении статуса процесса.
        
        Использует ProcessCommunication для отправки через роутер.
        
        Args:
            process_name: Имя процесса
            old_status: Старый статус
            new_status: Новый статус
            current_state: Текущее состояние процесса
        """
        try:
            # Создаем сообщение об изменении статуса
            message = {
                "type": "system",
                "subtype": "process_status_changed",
                "sender": self.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": current_state,
                "timestamp": time.time()
            }
            
            # Используем ProcessCommunication для broadcast через роутер
            sent_count = self.broadcast_message(message, exclude_self=True)
            
            if sent_count > 0:
                self.log("DEBUG", f"Broadcasted status change for '{process_name}' to {sent_count} processes", "monitor")
            else:
                self.log("WARNING", f"No processes received status change for '{process_name}'", "monitor")
                
        except Exception as e:
            self.log("ERROR", f"Failed to broadcast status change: {e}", "monitor")
            import traceback
            traceback.print_exc()
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики мониторинга"""
        stats = {
            "monitoring": self._monitoring,
            "tracked_processes": len(self.previous_states),
            "poll_interval": self.poll_interval
        }
        
        # Добавляем статистику процесса (из ProcessModule)
        stats.update(super().get_stats())
        
        return stats
