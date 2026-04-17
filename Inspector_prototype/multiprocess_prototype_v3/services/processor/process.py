"""ProcessorProcess — frame processing and blob detection."""

import time

try:
    import cv2
except ImportError:
    cv2 = None

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.worker_module import ThreadConfig, ExecutionMode

from multiprocess_prototype_v3.registers import PROCESSOR_REGISTER
from multiprocess_prototype_v3.services.processor.detection import ColorBlobDetector
from multiprocess_prototype_v3.services.database.schema import DetectionSchema
from multiprocess_prototype_v3.shared.frame_io import read_frame_from_msg, write_frame_to_shm, message_as_dict
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


class ProcessorProcess(ProcessModule):
    """Frame processing process. Consumes camera_frame, produces detection_result."""

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

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("processing_worker", self._processing_worker, config, auto_start=True)
        self._log_info("ProcessorProcess ready")

    def _build_register_handlers(self) -> dict:
        return {
            "color_lower": lambda v: self._cmd_set_color_range({"color_lower": v, "color_upper": None}),
            "color_upper": lambda v: self._cmd_set_color_range({"color_lower": None, "color_upper": v}),
            "min_area": lambda v: self._cmd_set_min_area({"min_area": v}),
            "max_area": lambda v: self._cmd_set_max_area({"max_area": v}),
        }

    def _processing_worker(self, stop_event, pause_event):
        register_handlers = self._build_register_handlers()
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            if msg_dict.get("data_type") == "register_update":
                apply_register_update(msg_dict.get("data") or {}, PROCESSOR_REGISTER, register_handlers)
                continue

            frame, data = read_frame_from_msg(msg, self.memory_manager, expected_data_type="frame_ready")
            if frame is None:
                continue

            if (frame.shape[0] != self._target_height or frame.shape[1] != self._target_width) and cv2 is not None:
                frame = cv2.resize(frame, (self._target_width, self._target_height), interpolation=cv2.INTER_LINEAR)
                data = dict(data)
                data["width"] = self._target_width
                data["height"] = self._target_height

            t_start = time.time()
            detections, mask, contours = self._detector.detect(frame)
            processing_time = time.time() - t_start

            mask_shm_name, mask_shm_index = write_frame_to_shm(self.memory_manager, self.name, "processor_mask", mask)
            self._send_detection_result(data, detections, contours, processing_time, mask_shm_name, mask_shm_index)
            self._send_feedback_to_camera(data.get("frame_id", 0), processing_time)

    def _send_detection_result(self, data, detections, contours, processing_time, mask_shm_name, mask_shm_index):
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
        if mask_shm_name:
            result_data["mask_shm_name"] = "processor_mask"
            result_data["mask_shm_index"] = mask_shm_index
            result_data["mask_shm_actual_name"] = mask_shm_name
        msg = self._msg.data(targets=["renderer"], data_type="detection_result", data=result_data)
        self.send_message("renderer", msg.to_dict())

        if detections:
            timestamp = data.get("timestamp", time.time())
            frame_id = data.get("frame_id", 0)
            detection_rows = []
            for d in detections:
                row = DetectionSchema(
                    timestamp=timestamp, frame_name=f"frame_{frame_id}", frame_id=frame_id,
                    x1=d["bbox"][0], y1=d["bbox"][1], x2=d["bbox"][2], y2=d["bbox"][3],
                    center_x=d["center"][0], center_y=d["center"][1], area=d["area"],
                ).model_dump(exclude_none=True, exclude={"id"})
                detection_rows.append(row)
            db_msg = self._msg.command(targets=["database"], command="db.save_detections", args={"detections": detection_rows}, data={})
            self.send_message("database", db_msg.to_dict())

    def _send_feedback_to_camera(self, frame_id, processing_time):
        feedback = self._msg.event(event_type="frame_processed", targets=["camera"],
                                    event_data={"frame_id": frame_id, "processing_time": processing_time})
        self.send_message("camera", feedback.to_dict())

    def _cmd_set_color_range(self, data):
        self._detector.apply_color_range(data.get("color_lower"), data.get("color_upper"))
        return {"status": "ok"}

    def _cmd_set_min_area(self, data):
        self._detector.set_min_area(data.get("min_area", self._detector.min_area))
        return {"status": "ok", "min_area": self._detector.min_area}

    def _cmd_set_max_area(self, data):
        self._detector.set_max_area(data.get("max_area", self._detector.max_area))
        return {"status": "ok", "max_area": self._detector.max_area}

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
