"""
Управление состоянием процесса.

Отвечает за регистрацию и обновление состояния процесса в ProcessStateRegistry.
"""

from typing import Dict, Any, Optional


class ProcessState:
    """
    Управление состоянием процесса.
    
    Инкапсулирует логику регистрации и обновления состояния процесса.
    """
    
    def __init__(self, process):
        """
        Инициализация управления состоянием.
        
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process
    
    def register(self):
        """Регистрация состояния процесса."""
        if not self.process.shared_resources:
            return
        
        try:
            # Получаем имена очередей из локального queue_registry
            queue_names = {}
            if self.process.queue_registry:
                process_queues = self.process.queue_registry.get_process_queues(self.process.name)
                if process_queues:
                    queue_names = {
                        queue_type: f"{self.process.name}_{queue_type}" 
                        for queue_type in process_queues.keys()
                    }
            
            # Регистрируем процесс со статусом "initializing"
            if hasattr(self.process.shared_resources, 'register_process_state'):
                self.process.shared_resources.register_process_state(
                    process_name=self.process.name,
                    initial_state={
                        "status": "initializing",
                        "metadata": {
                            "config": self.process.config or {},
                            "queues_count": len(self.process.queues) if self.process.queues else 0
                        }
                    },
                    queue_names=queue_names
                )
            elif hasattr(self.process.shared_resources, 'update_process_state'):
                # Альтернативный способ регистрации
                self.process.shared_resources.update_process_state(
                    self.process.name,
                    status="initializing"
                )
            
            self.process._log_info(f"Process state registered: {self.process.name}")
        except Exception as e:
            self.process._log_error(f"Failed to register process state: {e}")
    
    def update(
        self,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None
    ):
        """
        Обновление состояния процесса.
        
        Args:
            status: Новый статус процесса (ready, running, stopping, error)
            events: События для добавления
            metadata: Метаданные для обновления
            custom: Кастомные данные для обновления
        """
        if not self.process.shared_resources:
            return
        
        try:
            if hasattr(self.process.shared_resources, 'update_process_state'):
                self.process.shared_resources.update_process_state(
                    process_name=self.process.name,
                    status=status,
                    events=events,
                    metadata=metadata,
                    custom=custom
                )
        except Exception as e:
            self.process._log_error(f"Failed to update process state: {e}")

