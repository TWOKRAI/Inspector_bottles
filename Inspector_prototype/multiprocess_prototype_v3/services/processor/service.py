"""ProcessorService — бизнес-логика обработки кадров."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional

try:
    import cv2
except ImportError:
    cv2 = None

if TYPE_CHECKING:
    import numpy as np
    from multiprocess_prototype_v3.services.processor.ports import ProcessorOutputPort

from multiprocess_prototype_v3.services.processor.detection import ColorBlobDetector
from multiprocess_prototype_v3.services.database.schema import DetectionSchema


class ProcessorService:
    """Сервис обработки кадров. Чистая бизнес-логика без привязки к фреймворку."""

    def __init__(
        self,
        output: ProcessorOutputPort,
        detector: ColorBlobDetector,
        target_width: int = 640,
        target_height: int = 480,
    ) -> None:
        self._out = output
        self._detector = detector
        self._target_width = target_width
        self._target_height = target_height

    @property
    def detector(self) -> ColorBlobDetector:
        return self._detector

    @property
    def target_width(self) -> int:
        return self._target_width

    @property
    def target_height(self) -> int:
        return self._target_height

    def process_frame(self, frame: np.ndarray, metadata: dict[str, Any]) -> None:
        """Обработать кадр: детекция → маска → отправка результатов через порт."""
        # Resize при необходимости
        if (
            frame.shape[0] != self._target_height or frame.shape[1] != self._target_width
        ) and cv2 is not None:
            frame = cv2.resize(
                frame,
                (self._target_width, self._target_height),
                interpolation=cv2.INTER_LINEAR,
            )
            metadata = dict(metadata)
            metadata["width"] = self._target_width
            metadata["height"] = self._target_height

        t_start = time.time()
        detections, mask, contours = self._detector.detect(frame)
        processing_time = time.time() - t_start

        # Записать маску в SHM через порт
        mask_shm_name, mask_shm_index = self._out.write_mask_to_shm(mask)

        # Построить и отправить результат рендереру
        result_data = self._build_detection_result(
            metadata, detections, contours, processing_time, mask_shm_name, mask_shm_index
        )
        self._out.send_detection_to_renderer(result_data)

        # Отправить детекции в БД
        if detections:
            rows = self._build_detection_rows(detections, metadata)
            self._out.send_detections_to_database(rows)

        # Feedback камере
        self._out.send_feedback_to_camera(metadata.get("frame_id", 0), processing_time)

    def _build_detection_result(
        self,
        metadata: dict,
        detections: list,
        contours: list,
        processing_time: float,
        mask_shm_name: Optional[str],
        mask_shm_index: int,
    ) -> dict:
        """Построить словарь результата детекции."""
        result = {
            "frame_id": metadata.get("frame_id", 0),
            "shm_name": "camera_frame",
            "shm_index": metadata.get("shm_index", 0),
            "shm_actual_name": metadata.get("shm_actual_name"),
            "detections": detections,
            "processing_time": processing_time,
            "timestamp": metadata.get("timestamp", 0),
            "width": metadata.get("width", 640),
            "height": metadata.get("height", 480),
            "contours": contours,
        }
        if mask_shm_name:
            result["mask_shm_name"] = "processor_mask"
            result["mask_shm_index"] = mask_shm_index
            result["mask_shm_actual_name"] = mask_shm_name
        return result

    def _build_detection_rows(self, detections: list[dict], metadata: dict) -> list[dict]:
        """Построить строки DetectionSchema для записи в БД."""
        timestamp = metadata.get("timestamp", time.time())
        frame_id = metadata.get("frame_id", 0)
        rows = []
        for d in detections:
            row = DetectionSchema(
                timestamp=timestamp,
                frame_name=f"frame_{frame_id}",
                frame_id=frame_id,
                x1=d["bbox"][0],
                y1=d["bbox"][1],
                x2=d["bbox"][2],
                y2=d["bbox"][3],
                center_x=d["center"][0],
                center_y=d["center"][1],
                area=d["area"],
            ).model_dump(exclude_none=True, exclude={"id"})
            rows.append(row)
        return rows

    def set_color_range(self, lower: Optional[list] = None, upper: Optional[list] = None) -> dict:
        """Установить цветовой диапазон детекции."""
        self._detector.apply_color_range(lower, upper)
        return {"status": "ok"}

    def set_min_area(self, value: int) -> int:
        """Установить минимальную площадь. Возвращает фактическое значение."""
        self._detector.set_min_area(value)
        return self._detector.min_area

    def set_max_area(self, value: int) -> int:
        """Установить максимальную площадь. Возвращает фактическое значение."""
        self._detector.set_max_area(value)
        return self._detector.max_area
