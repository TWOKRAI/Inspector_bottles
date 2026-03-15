"""
CameraProcess — захват видеокадров (реальная камера или имитация).

Owner блока SharedMemory camera_frame.
Отправляет DATA frame_ready в ProcessorProcess.
"""

import time

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)


class CameraProcess(ProcessModule):
    """Процесс захвата кадров. Owner camera_frame в SharedMemory."""

    def _init_application_threads(self):
        """Инициализация CameraProcess: SharedMemory, команды, capture_worker."""
        self._log_info("CameraProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        # Параметры из конфига
        self._fps = self.get_config("fps", 30)
        self._width = self.get_config("resolution_width", 640)
        self._height = self.get_config("resolution_height", 480)
        self._use_simulator = self.get_config("use_simulator", True)

        # Генератор кадров (имитация камеры: изображение → numpy BGR)
        if self._use_simulator:
            from multiprocess_prototype.utils.frame_generator import FrameGenerator

            image_path = self.get_config("simulator_image_path")
            self._generator = FrameGenerator(
                self._width, self._height, image_path=image_path
            )
        else:
            self._generator = None
            self._log_warning("Real camera (cv2) not implemented, use_simulator=True")

        # Shared Memory: создаётся из config["memory"] или fallback в process_runner
        mm = self.memory_manager
        if mm:
            # Использовать память из fallback (process_runner), если уже есть
            md = mm.get_memory_data(self.name, "camera_frame")
            if not md or not md.get("handles"):
                memory_cfg = self.get_config("memory")
                if memory_cfg and isinstance(memory_cfg, dict):
                    names = memory_cfg.get("names", {})
                    coll = memory_cfg.get("coll", 2)
                    if names:
                        mm.create_memory_dict(self.name, names, coll)
                    else:
                        mm.create_memory_dict(
                            self.name,
                            {"camera_frame": (1, (self._height, self._width, 3), "uint8")},
                            coll=2,
                        )
                else:
                    mm.create_memory_dict(
                        self.name,
                        {"camera_frame": (1, (self._height, self._width, 3), "uint8")},
                        coll=2,
                    )
        else:
            self._log_warning("MemoryManager not available, shared memory disabled")

        # Регистрация команд
        self.command_manager.register_command("start_capture", self._cmd_start)
        self.command_manager.register_command("stop_capture", self._cmd_stop)
        self.command_manager.register_command("set_fps", self._cmd_set_fps)
        self.command_manager.register_command(
            "set_resolution", self._cmd_set_resolution
        )

        # Создание воркера (не из config.workers)
        # auto_start=False — воркер стартует в run() через start_all_workers(), избегая race
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, config, auto_start=False
        )
        # Старт в паузе — кнопка Start запускает захват
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(
            f"CameraProcess ready: {self._width}x{self._height} @ {self._fps} FPS"
        )

    def _capture_worker(self, stop_event, pause_event):
        """Циклический захват кадров. Режим LOOP."""
        frame_count = 0
        stats_start = time.time()
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if not self._generator:
                time.sleep(0.1)
                continue

            # 1. Захватить кадр
            frame = self._generator.generate_frame()
            frame_count += 1
            timestamp = time.time()

            # 2. Записать в shared memory (если доступен)
            mm = self.memory_manager
            if not mm and frame_count == 1:
                self._log_warning("MemoryManager not available — frames not sent to processor")
            if mm:
                free_idx = mm.find_free_index("camera", "camera_frame")
                if free_idx is None:
                    free_idx = 0

                shm_actual_name = mm.write_images(
                    "camera", "camera_frame", [frame], free_idx
                )

                if not shm_actual_name and frame_count <= 3:
                    self._log_warning(
                        f"write_images returned None (frame={frame_count}); "
                        "check MemoryManager init and create_memory_dict"
                    )

                # 3. Отправить уведомление (shm_actual_name для consumer)
                if shm_actual_name:
                    if frame_count <= 3 or frame_count % 50 == 0:
                        self._log_info(f"[DEBUG] camera: frame={frame_count} -> processor, shm={shm_actual_name[:20]}...")
                    notification = self._msg.data(
                        targets=["processor"],
                        data_type="frame_ready",
                        data={
                            "frame_id": frame_count,
                            "timestamp": timestamp,
                            "shm_name": "camera_frame",
                            "shm_index": free_idx,
                            "shm_actual_name": shm_actual_name,
                            "width": frame.shape[1],
                            "height": frame.shape[0],
                        },
                    )
                    self.send_message("processor", notification.to_dict())

            # Метрики: каждые 100 кадров — FPS в StatsManager
            if frame_count % 100 == 0 and frame_count > 0:
                elapsed = time.time() - stats_start
                actual_fps = 100.0 / elapsed if elapsed > 0 else 0
                self._record_metric("camera.frames_captured", value=100, tags={"target_fps": str(self._fps)})
                self._record_metric("camera.actual_fps", value=actual_fps)
                self._log_info(f"[PERF] camera: frames={frame_count}, actual_fps={actual_fps:.1f}, target_fps={self._fps}")
                stats_start = time.time()

            # 4. Соблюдать FPS
            delay = 1.0 / max(1, self._fps)
            time.sleep(delay)

    def _cmd_start(self, data):
        self._log_info("[DEBUG] camera: start_capture received, resuming capture_worker")
        if self.worker_manager:
            if not self.worker_manager.is_worker_running("capture_worker"):
                self.worker_manager.start_worker("capture_worker")
            self.worker_manager.resume_worker("capture_worker")
        self._log_info("Capture started")
        return {"status": "ok"}

    def _cmd_stop(self, data):
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        self._log_info("Capture stopped")
        return {"status": "ok"}

    def _cmd_set_fps(self, data):
        new_fps = data.get("fps", self._fps)
        self._fps = max(1, min(120, new_fps))
        self._log_info(f"FPS set to {self._fps}")
        return {"status": "ok", "fps": self._fps}

    def _cmd_set_resolution(self, data):
        self._width = data.get("width", self._width)
        self._height = data.get("height", self._height)
        if self._use_simulator and self._generator:
            from multiprocess_prototype.utils.frame_generator import FrameGenerator

            image_path = self.get_config("simulator_image_path")
            self._generator = FrameGenerator(
                self._width, self._height, image_path=image_path
            )
        self._log_info(f"Resolution set to {self._width}x{self._height}")
        return {"status": "ok"}

    def shutdown(self) -> bool:
        self._log_info("CameraProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
