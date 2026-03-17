"""
ProcessorProcess — обработка кадров, детекция пятен.

Consumer блока SharedMemory camera_frame (чтение через shm_actual_name в сообщении).
Owner блока SharedMemory processor_mask.
Получает DATA frame_ready от Camera, отправляет DATA detection_result в Renderer,
EVENT frame_processed в Camera.
"""

import time

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)
from multiprocess_prototype.utils.shm_utils import read_frame_from_shm


class ProcessorProcess(ProcessModule):
    """Процесс обработки кадров. Consumer camera_frame."""

    def _init_application_threads(self):
        """Инициализация ProcessorProcess: команды, processing_worker."""
        self._log_info("ProcessorProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        # Параметры из конфига (BGR для детекции цвета)
        self._min_area = self.get_config("min_area", 500)
        self._color_lower = np.array(
            self.get_config("color_lower", [0, 0, 150]), dtype=np.uint8
        )
        self._color_upper = np.array(
            self.get_config("color_upper", [100, 100, 255]), dtype=np.uint8
        )

        # Регистрация команд
        self.command_manager.register_command("set_color_range", self._cmd_set_color_range)
        self.command_manager.register_command("set_min_area", self._cmd_set_min_area)

        # Shared Memory: создаётся фреймворком из config["memory"] в process_runner
        if not self.memory_manager:
            self._log_warning("MemoryManager not available, processor_mask disabled")

        # Создание воркера
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "processing_worker", self._processing_worker, config, auto_start=True
        )

        self._log_info(
            f"ProcessorProcess ready: color_lower={self._color_lower.tolist()}, "
            f"color_upper={self._color_upper.tolist()}, min_area={self._min_area}"
        )

    def _processing_worker(self, stop_event, pause_event):
        """Циклическая обработка кадров. Режим LOOP."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=['data'])
            frame, data = self._read_frame_from_message(msg)
            if frame is None:
                continue

            t_start = time.time()
            detections, mask, contours = self._detect_color_blobs(frame)
            processing_time = time.time() - t_start

            mask_shm_actual_name, mask_shm_index = self._write_mask_to_shm(mask)
            self._send_detection_result(
                data, detections, contours, processing_time,
                mask_shm_actual_name, mask_shm_index,
            )
            self._send_feedback_to_camera(data.get("frame_id", 0), processing_time)

            self._record_metric("processor.processing_time_ms", value=processing_time * 1000)
            self._record_metric("processor.detections_count", value=len(detections))
            self._log_info(
                f"[PERF] processor: frame={data.get('frame_id', 0)}, "
                f"processing_time={processing_time*1000:.1f}ms, detections={len(detections)}"
            )

    def _read_frame_from_message(self, msg) -> tuple:
        """Чтение кадра из сообщения frame_ready. Возврат (frame, data) или (None, {})."""
        if msg is None:
            return None, {}
        msg_dict = msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
        if msg_dict.get("data_type") != "frame_ready":
            return None, {}
        data = msg_dict.get("data", {})
        frame_id_log = data.get("frame_id", 0)
        if frame_id_log <= 3 or frame_id_log % 50 == 0:
            self._log_info(f"[DEBUG] processor: frame_ready received frame_id={frame_id_log}")
        shm_index = data.get("shm_index", 0)
        width = data.get("width", 640)
        height = data.get("height", 480)
        shm_actual_name = data.get("shm_actual_name")
        shm_name = data.get("shm_name", "camera_frame")
        frame = None
        mm = self.memory_manager
        if mm:
            images = mm.read_images("camera", shm_name, shm_index, n=1)
            if images:
                frame = images[0]
        if frame is None and shm_actual_name:
            frame = read_frame_from_shm(shm_actual_name, width, height)
        if frame is None:
            self._log_warning(f"[DEBUG] processor: frame is None for frame_id={frame_id_log}")
        return frame, data

    def _write_mask_to_shm(self, mask) -> tuple:
        """Записать маску в processor_mask. Возврат (shm_actual_name, shm_index)."""
        if mask is None:
            return None, 0
        mm = self.memory_manager
        if not mm:
            return None, 0
        free_idx = mm.find_free_index(self.name, "processor_mask") or 0
        shm_name = mm.write_images(self.name, "processor_mask", [mask], free_idx)
        return (shm_name, free_idx) if shm_name else (None, 0)

    def _send_detection_result(
        self, data: dict, detections: list, contours: list, processing_time: float,
        mask_shm_actual_name: str, mask_shm_index: int,
    ):
        """Формирование и отправка detection_result в Renderer."""
        result_data = {
            "frame_id": data.get("frame_id", 0),
            "shm_name": "camera_frame",
            "shm_index": data.get("shm_index", 0),
            "shm_actual_name": data.get("shm_actual_name"),
            "detections": detections,
            "processing_time": processing_time,
            "timestamp": data.get("timestamp", 0),
            "width": data.get("width", 640),
            "height": data.get("height", 480),
            "contours": contours,
        }
        if mask_shm_actual_name:
            result_data["mask_shm_name"] = "processor_mask"
            result_data["mask_shm_index"] = mask_shm_index
            result_data["mask_shm_actual_name"] = mask_shm_actual_name
        result_msg = self._msg.data(
            targets=["renderer"],
            data_type="detection_result",
            data=result_data,
        )
        self.send_message("renderer", result_msg.to_dict())

    def _send_feedback_to_camera(self, frame_id: int, processing_time: float):
        """Обратная связь в Camera (frame_processed)."""
        feedback = self._msg.event(
            event_type="frame_processed",
            targets=["camera"],
            event_data={"frame_id": frame_id, "processing_time": processing_time},
        )
        self.send_message("camera", feedback.to_dict())

    def _detect_color_blobs(self, frame: np.ndarray) -> tuple:
        """
        Детекция цветных пятен по BGR-диапазону.

        Returns:
            (detections, mask, contours)
            - detections: list of {bbox, center, area}
            - mask: H×W×3 BGR для отображения (grayscale → 3 channels)
            - contours: list of np.ndarray (N,1,2) от cv2.findContours
        """
        mask_binary = np.all(
            (frame >= self._color_lower) & (frame <= self._color_upper),
            axis=2,
        ).astype(np.uint8) * 255

        detections = []
        ys, xs = np.where(mask_binary > 0)
        if len(ys) >= self._min_area:
            x_min, x_max = int(xs.min()), int(xs.max())
            y_min, y_max = int(ys.min()), int(ys.max())
            area = int(len(ys))
            cx = (x_min + x_max) // 2
            cy = (y_min + y_max) // 2
            detections.append(
                {
                    "bbox": [x_min, y_min, x_max, y_max],
                    "center": [cx, cy],
                    "area": area,
                }
            )

        # Контуры через cv2.findContours
        contours = []
        if cv2 is not None:
            cnts, _ = cv2.findContours(
                mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contours = [c.astype(np.int32) for c in cnts]

        # Маска для отображения: H×W×3 (grayscale → BGR)
        mask_display = np.stack([mask_binary] * 3, axis=-1)

        return detections, mask_display, contours

    def _cmd_set_color_range(self, data):
        """Установка BGR-диапазона для детекции цвета. data: color_lower, color_upper."""
        lower = data.get("color_lower")
        upper = data.get("color_upper")
        if lower is not None and len(lower) >= 3:
            self._color_lower = np.array(
                [max(0, min(255, int(lower[i]))) for i in range(3)],
                dtype=np.uint8,
            )
        if upper is not None and len(upper) >= 3:
            self._color_upper = np.array(
                [max(0, min(255, int(upper[i]))) for i in range(3)],
                dtype=np.uint8,
            )
        self._log_info(
            f"Color range set: lower={self._color_lower.tolist()}, upper={self._color_upper.tolist()}"
        )
        return {
            "status": "ok",
            "color_lower": self._color_lower.tolist(),
            "color_upper": self._color_upper.tolist(),
        }

    def _cmd_set_min_area(self, data):
        new_val = data.get("min_area", self._min_area)
        self._min_area = max(10, min(10000, int(new_val)))
        self._log_info(f"Min area set to {self._min_area}")
        return {"status": "ok", "min_area": self._min_area}

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
