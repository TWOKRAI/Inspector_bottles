"""ProcessorWorker configuration — один воркер пула обработки изображений.

Каждый воркер получает уникальный worker_index → уникальный process_name
и собственный SHM-регион результата.
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import (
    ProcessLaunchConfig,
    ProcessPriorityLevel,
)


@register_schema("ProcessorWorkerConfigV3")
class ProcessorWorkerConfig(ProcessLaunchConfig):
    """Конфигурация одного воркера пула обработки.

    worker_index — позиция в пуле (0..K-1). Определяет имя процесса
    и имя SHM-региона для результата.
    """

    process_name: str = "processor_worker_0"
    process_class: str = (
        "multiprocess_prototype_v3.backend.processes.processor_worker.process.ProcessorWorkerProcess"
    )
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH

    # --- Идентификация воркера ---
    worker_index: int = 0

    # --- Параметры выполнения ---
    step_timeout: float = 10.0
    input_queue_size: int = 4

    def model_post_init(self, __context: object) -> None:
        """process_name всегда соответствует worker_index."""
        object.__setattr__(self, "process_name", f"processor_worker_{self.worker_index}")

    @property
    def result_shm_name(self) -> str:
        """Имя SHM-региона с результатом данного воркера."""
        return f"worker_{self.worker_index}_result"
