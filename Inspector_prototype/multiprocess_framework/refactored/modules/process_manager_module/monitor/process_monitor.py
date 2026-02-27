"""
Мониторинг состояний процессов (Refactored).

Компонент для ProcessManagerProcess, который отслеживает изменения состояний процессов
и отправляет broadcast сообщения через RouterManager.
"""

import time
from typing import Dict, Any, Optional
from multiprocessing import Event

from ...worker_module import ThreadConfig, ThreadPriority


class ProcessMonitor:
    """
    Мониторинг состояний процессов (Refactored).
    
    Компонент для ProcessManagerProcess, который отслеживает изменения состояний процессов
    и отправляет broadcast сообщения через RouterManager.
    
    Используется как компонент внутри ProcessManagerProcess, а не как отдельный ProcessModule.
    """
    
    def __init__(
        self,
        process_manager_process,
        poll_interval: float = 0.5
    ):
        """
        Инициализация монитора процессов.
        
        Args:
            process_manager_process: Ссылка на ProcessManagerProcess
            poll_interval: Интервал опроса состояний в секундах
        """
        self.process = process_manager_process
        self.poll_interval = poll_interval
        
        # Кэш предыдущих состояний для отслеживания изменений
        self.previous_states: Dict[str, Dict[str, Any]] = {}
        
        # Флаг запуска
        self._monitoring = False
    
    def start(self):
        """Запуск мониторинга состояний процессов."""
        if self._monitoring:
            self.process._log_warning("Monitor already running")
            return
        
        self.process._log_info("Starting process state monitor")
        
        # Используем WorkerManager для создания потока мониторинга
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.process.worker_manager.create_worker(
            "state_monitor",
            self._monitoring_loop,
            config,
            auto_start=True
        )
        
        self._monitoring = True
    
    def stop(self):
        """Остановка мониторинга."""
        if not self._monitoring:
            return
        
        self.process._log_info("Stopping process state monitor")
        self._monitoring = False
    
    def _monitoring_loop(self, stop_event: Event, pause_event: Event):
        """
        Основной цикл мониторинга состояний процессов.
        
        Args:
            stop_event: Событие остановки потока
            pause_event: Событие паузы (не используется)
        """
        self.process._log_info("Process monitor loop started")
        
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Получаем все состояния процессов из ProcessStateRegistry
                if not self.process.shared_resources:
                    time.sleep(self.poll_interval)
                    continue
                
                process_state_registry = self.process.shared_resources.process_state_registry
                if not process_state_registry:
                    time.sleep(self.poll_interval)
                    continue
                
                # Получаем все процессы
                all_processes = process_state_registry.get_all_processes()
                all_states = {}
                
                for process_name, process_data in all_processes.items():
                    if process_data and process_data.state:
                        all_states[process_name] = {
                            'status': process_data.state.get('status', 'unknown'),
                            'metadata': process_data.state.get('metadata', {}),
                            'custom': process_data.state.get('custom', {})
                        }
                
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
                    self.process._log_info(f"New process detected: {process_name}")
                    self.previous_states[process_name] = all_states[process_name].copy()
                
                # Проверяем удаленные процессы
                removed_processes = previous_processes - current_processes
                for process_name in removed_processes:
                    self.process._log_info(f"Process removed: {process_name}")
                    if process_name in self.previous_states:
                        del self.previous_states[process_name]
                
                # Ждем перед следующим опросом
                time.sleep(self.poll_interval)
                
            except Exception as e:
                self.process._log_error(f"Error in monitoring loop: {e}")
                time.sleep(self.poll_interval)
        
        self.process._log_info("Process monitor loop stopped")
    
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
            self.process._log_info(
                f"Process '{process_name}' status changed: {previous_status} -> {current_status}"
            )
            
            # Отправляем broadcast сообщение о изменении статуса через RouterManager
            self._broadcast_status_change(process_name, previous_status, current_status, current_state)
    
    def _broadcast_status_change(
        self,
        process_name: str,
        old_status: Optional[str],
        new_status: str,
        current_state: Dict[str, Any]
    ):
        """
        Отправка broadcast сообщения об изменении статуса процесса через RouterManager.
        
        Args:
            process_name: Имя процесса
            old_status: Старый статус
            new_status: Новый статус
            current_state: Текущее состояние процесса
        """
        try:
            if not self.process.router_manager:
                return
            
            # Создаем сообщение об изменении статуса
            message = {
                "type": "system",
                "subtype": "process_status_changed",
                "sender": self.process.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": current_state,
                "timestamp": time.time()
            }
            
            # Используем RouterManager для broadcast через Dispatch
            sent_count = self.process.communication.broadcast(message, exclude_self=True)
            
            if sent_count > 0:
                self.process._log_debug(
                    f"Broadcasted status change for '{process_name}' to {sent_count} processes"
                )
            else:
                self.process._log_warning(
                    f"No processes received status change for '{process_name}'"
                )
                
        except Exception as e:
            self.process._log_error(f"Failed to broadcast status change: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики мониторинга."""
        return {
            "monitoring": self._monitoring,
            "tracked_processes": len(self.previous_states),
            "poll_interval": self.poll_interval
        }

