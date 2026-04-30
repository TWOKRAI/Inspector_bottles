"""Протокол обмена данными между Processor и Worker-процессами (Phase 5c).

Dict at Boundary: между процессами передаются только dict через to_dict()/from_dict().
Внутри процесса — типизированные dataclass-ы.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class WorkerTaskRequest:
    """Запрос на выполнение операции в worker-процессе.

    Processor создаёт request, сериализует в dict через to_dict(),
    отправляет через IPC. Worker десериализует через from_dict().
    """

    task_id: str
    correlation_id: str
    camera_id: str
    region_id: str
    seq_id: int
    operation_ref: str  # ссылка на операцию в каталоге
    params: dict = field(default_factory=dict)
    input_shm_name: str = ""  # имя SHM-блока с входным кадром
    input_shm_index: int = 0
    frame_shape: tuple = ()  # (height, width, channels)

    @staticmethod
    def create(
        *,
        correlation_id: str = "",
        camera_id: str,
        region_id: str,
        seq_id: int,
        operation_ref: str,
        params: dict | None = None,
        input_shm_name: str,
        input_shm_index: int,
        frame_shape: tuple,
    ) -> WorkerTaskRequest:
        """Фабрика с автогенерацией task_id."""
        return WorkerTaskRequest(
            task_id=uuid.uuid4().hex,
            correlation_id=correlation_id,
            camera_id=camera_id,
            region_id=region_id,
            seq_id=seq_id,
            operation_ref=operation_ref,
            params=params or {},
            input_shm_name=input_shm_name,
            input_shm_index=input_shm_index,
            frame_shape=tuple(frame_shape),
        )

    def to_dict(self) -> dict:
        """Сериализация для IPC (Dict at Boundary)."""
        return {
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "camera_id": self.camera_id,
            "region_id": self.region_id,
            "seq_id": self.seq_id,
            "operation_ref": self.operation_ref,
            "params": self.params,
            "input_shm_name": self.input_shm_name,
            "input_shm_index": self.input_shm_index,
            "frame_shape": list(self.frame_shape),
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkerTaskRequest:
        """Десериализация из IPC dict."""
        return cls(
            task_id=data["task_id"],
            correlation_id=data.get("correlation_id", ""),
            camera_id=data.get("camera_id", ""),
            region_id=data.get("region_id", ""),
            seq_id=data.get("seq_id", 0),
            operation_ref=data["operation_ref"],
            params=data.get("params", {}),
            input_shm_name=data.get("input_shm_name", ""),
            input_shm_index=data.get("input_shm_index", 0),
            frame_shape=tuple(data.get("frame_shape", ())),
        )


@dataclass
class WorkerTaskResponse:
    """Ответ worker-процесса на выполненную задачу.

    Worker создаёт response, сериализует в dict через to_dict(),
    отправляет обратно Processor. Processor десериализует через from_dict().
    """

    task_id: str
    correlation_id: str = ""
    success: bool = True
    error: str | None = None
    output_shm_name: str = ""  # имя SHM-блока с результатом
    output_shm_index: int = 0
    detections: list[dict] = field(default_factory=list)
    processing_time: float = 0.0

    @staticmethod
    def error_response(
        task_id: str,
        error: str,
        correlation_id: str = "",
    ) -> WorkerTaskResponse:
        """Фабрика для ответа с ошибкой."""
        return WorkerTaskResponse(
            task_id=task_id,
            correlation_id=correlation_id,
            success=False,
            error=error,
        )

    def to_dict(self) -> dict:
        """Сериализация для IPC (Dict at Boundary)."""
        return {
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "success": self.success,
            "error": self.error,
            "output_shm_name": self.output_shm_name,
            "output_shm_index": self.output_shm_index,
            "detections": self.detections,
            "processing_time": self.processing_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkerTaskResponse:
        """Десериализация из IPC dict."""
        return cls(
            task_id=data["task_id"],
            correlation_id=data.get("correlation_id", ""),
            success=data.get("success", True),
            error=data.get("error"),
            output_shm_name=data.get("output_shm_name", ""),
            output_shm_index=data.get("output_shm_index", 0),
            detections=data.get("detections", []),
            processing_time=data.get("processing_time", 0.0),
        )


__all__ = ["WorkerTaskRequest", "WorkerTaskResponse"]
