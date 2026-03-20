# multiprocess_prototype/backend/processes/processor/process.py
"""
ProcessorProcess — обработка кадров, детекция пятен.

Домен: `backend.modules.processor_frame`.
"""

import time

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
from multiprocess_prototype.backend.database.schema_1 import DetectionSchema
from multiprocess_prototype.backend.modules.processor_frame.detection import ColorBlobDetector
from multiprocess_prototype.backend.modules.processor_frame.frame_io import (
    read_frame_from_frame_ready,
    write_mask_to_process_shm,
)
from multiprocess_prototype.backend.modules.processor_frame.register_sync import (
    apply_processor_register_update,
)
from multiprocess_prototype.backend.shared import message_as_dict


class ProcessorProcess(ProcessModule):
    """Процесс обработки кадров. Consumer camera_frame."""

    def _init_application_threads(self):
        self._log_info("ProcessorProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        app_cfg = self.get_config("config") or {}
        self._target_width = app_cfg.get("resolution_width", 640)
        self._target_height = app_cfg.get("resolution_height", 480)
        self._detector = ColorBlobDetector(
            app_cfg.get("color_lower", [0, 0, 150]),
            app_cfg.get("color_upper", [100, 100, 255]),
            app_cfg.get("min_area", 500),
            app_cfg.get("max_area", 50000),
        )

        self.command_manager.register_command("set_color_range", self._cmd_set_color_range)
        self.command_manager.register_command("set_min_area", self._cmd_set_min_area)
        self.command_manager.register_command("set_max_area", self._cmd_set_max_area)

        if not self.memory_manager:
            self._log_warning("MemoryManager not available, processor_mask disabled")

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "processing_worker", self._processing_worker, config, auto_start=True
        )

        self._log_info(
            f"ProcessorProcess ready: color_lower={self._detector.color_lower.tolist()}, "
            f"color_upper={self._detector.color_upper.tolist()}, "
            f"min_area={self._detector.min_area}, max_area={self._detector.max_area}"
        )

    def _processing_worker(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            if msg_dict.get("data_type") == "register_update":
                apply_processor_register_update(
                    msg_dict.get("data") or {},
                    set_color_range=self._cmd_set_color_range,
                    set_min_area=self._cmd_set_min_area,
                    set_max_area=self._cmd_set_max_area,
                )
                continue

            frame, data = read_frame_from_frame_ready(
                msg,
                self.memory_manager,
                log_info=self._log_info,
                log_warning=self._log_warning,
            )
            if frame is None:
                continue

            if (
                frame.shape[0] != self._target_height
                or frame.shape[1] != self._target_width
            ) and cv2 is not None:
                frame = cv2.resize(
                    frame,
                    (self._target_width, self._target_height),
                    interpolation=cv2.INTER_LINEAR,
                )
                data = dict(data)
                data["width"] = self._target_width
                data["height"] = self._target_height

            t_start = time.time()
            detections, mask, contours = self._detector.detect(frame)
            processing_time = time.time() - t_start

            mask_shm_actual_name, mask_shm_index = write_mask_to_process_shm(
                self.memory_manager, self.name, mask
            )
            self._send_detection_result(
                data,
                detections,
                contours,
                processing_time,
                mask_shm_actual_name,
                mask_shm_index,
            )
            self._send_feedback_to_camera(data.get("frame_id", 0), processing_time)

            self._record_metric("processor.processing_time_ms", value=processing_time * 1000)
            self._record_metric("processor.detections_count", value=len(detections))
            self._log_info(
                f"[PERF] processor: frame={data.get('frame_id', 0)}, "
                f"processing_time={processing_time*1000:.1f}ms, detections={len(detections)}",
                module="processor_frames",
            )

    def _send_detection_result(
        self,
        data: dict,
        detections: list,
        contours: list,
        processing_time: float,
        mask_shm_actual_name: str,
        mask_shm_index: int,
    ):
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

        if detections:
            timestamp = data.get("timestamp", time.time())
            frame_id = data.get("frame_id", 0)
            frame_name = f"frame_{frame_id}"
            detection_rows = []
            for d in detections:
                bbox, center, area = d["bbox"], d["center"], d["area"]
                row = DetectionSchema(
                    timestamp=timestamp,
                    frame_name=frame_name,
                    frame_id=frame_id,
                    x1=bbox[0],
                    y1=bbox[1],
                    x2=bbox[2],
                    y2=bbox[3],
                    center_x=center[0],
                    center_y=center[1],
                    area=area,
                ).model_dump(exclude_none=True, exclude={"id"})
                detection_rows.append(row)
            db_msg = self._msg.command(
                targets=["database"],
                command="db.save_detections",
                args={"detections": detection_rows},
                data={},
            )
            self.send_message("database", db_msg.to_dict())

    def _send_feedback_to_camera(self, frame_id: int, processing_time: float):
        feedback = self._msg.event(
            event_type="frame_processed",
            targets=["camera"],
            event_data={"frame_id": frame_id, "processing_time": processing_time},
        )
        self.send_message("camera", feedback.to_dict())

    def _cmd_set_color_range(self, data):
        lower = data.get("color_lower")
        upper = data.get("color_upper")
        self._detector.apply_color_range(lower, upper)
        self._log_info(
            f"Color range set: lower={self._detector.color_lower.tolist()}, "
            f"upper={self._detector.color_upper.tolist()}"
        )
        return {
            "status": "ok",
            "color_lower": self._detector.color_lower.tolist(),
            "color_upper": self._detector.color_upper.tolist(),
        }

    def _cmd_set_min_area(self, data):
        new_val = data.get("min_area", self._detector.min_area)
        self._detector.set_min_area(new_val)
        self._log_info(f"Min area set to {self._detector.min_area}")
        return {"status": "ok", "min_area": self._detector.min_area}

    def _cmd_set_max_area(self, data):
        new_val = data.get("max_area", self._detector.max_area)
        self._detector.set_max_area(new_val)
        self._log_info(f"Max area set to {self._detector.max_area} (0=no limit)")
        return {"status": "ok", "max_area": self._detector.max_area}

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
