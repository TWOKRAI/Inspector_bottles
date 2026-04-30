"""
Управление состоянием процесса.

Тонкая обёртка — делегирует в shared_resources через ISharedResources protocol.
Не хранит прямую ссылку на ProcessModule, работает через переданные зависимости.
"""

from typing import Dict, Any, Optional


class ProcessState:
    """
    Управление состоянием процесса.

    Делегирует регистрацию и обновление состояния в shared_resources.
    Работает через ISharedResources protocol — нет прямой зависимости от реализации.
    """

    def __init__(self, process):
        """
        Args:
            process: Ссылка на ProcessModule (используется только для доступа к
                     process.name, process.shared_resources, process.queues и логирования)
        """
        self.process = process

    def register(self):
        """Регистрация состояния процесса в shared_resources."""
        if not self.process.shared_resources:
            return

        try:
            shared = self.process.shared_resources
            psr = getattr(shared, "process_state_registry", None)
            if psr is not None and hasattr(psr, "register_process"):
                psr.register_process(
                    self.process.name,
                    initial_state={
                        "status": "initializing",
                        "metadata": {
                            "config": self.process.config or {},
                            "queues_count": len(self.process.queues) if self.process.queues else 0,
                        },
                    },
                )
            elif hasattr(shared, "process_state_registry") and hasattr(
                shared.process_state_registry, "update_state"
            ):
                shared.process_state_registry.update_state(
                    self.process.name, status="initializing"
                )

            self.process._log_info(f"Process state registered: {self.process.name}")
        except Exception as e:
            self.process._log_error(f"Failed to register process state: {e}")

    def update(
        self,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ):
        """
        Обновление состояния процесса.

        Args:
            status: Новый статус (ready, running, stopping, error)
            events: События для добавления
            metadata: Метаданные для обновления
            custom: Кастомные данные для обновления
        """
        if not self.process.shared_resources:
            return

        try:
            shared = self.process.shared_resources
            psr = getattr(shared, "process_state_registry", None)
            if psr is not None and hasattr(psr, "update_state"):
                psr.update_state(
                    self.process.name,
                    status=status,
                    events=events,
                    metadata=metadata,
                    custom=custom,
                )
        except Exception as e:
            self.process._log_error(f"Failed to update process state: {e}")
