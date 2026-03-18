# multiprocess_prototype\processes\gui_process.py
"""
GuiProcess — отображение видео и управление (PyQt5).

Consumer rendered_frame. QTimer для опроса сообщений в главном потоке.
Без воркеров — PyQt в главном потоке.

Интеграция с frontend_module:
- Создаёт FrontendManager с RegistersManager (DrawRegisters) и connection_map
- process.frontend_manager — для доступа к регистрам и конфигу
- Виджеты могут использовать registers для связи с backend (set_field_value → send)
"""

import sys

import numpy as np

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_prototype.utils.shm_utils import read_frame_from_shm


def _create_frontend_manager(process: "GuiProcess", app_cfg: dict):
    """Создать FrontendManager с регистрами и connection_map для GuiProcess."""
    try:
        from frontend_module import FrontendManager
        from multiprocess_prototype.frontend.registers import create_frontend_registers

        registers, connection_map = create_frontend_registers()
        config = {
            "window": app_cfg,
            **app_cfg,
        }
        fm = FrontendManager(
            manager_name="GuiFrontend",
            config=config,
            registers=registers,
            router=process,
            connection_map=connection_map,
        )
        fm.initialize()
        return fm
    except ImportError:
        return None


class GuiProcess(ProcessModule):
    """
    GUI-процесс с PyQt5.

    run() запускает QApplication.exec_() — блокирующий вызов.
    QTimer опрашивает входящие сообщения. Воркеры не создаются.
    """

    def _init_application_threads(self):
        """GUI без воркеров — только конфиг."""
        self._log_info("GuiProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._window_width = app_cfg.get("window_width", 1024)
        self._window_height = app_cfg.get("window_height", 600)
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._log_info("GuiProcess ready (no workers)")

    def _init_system_threads(self):
        """GUI не использует message_processor — опрос через QTimer в главном потоке."""
        pass

    def _stop_system_threads(self):
        """Нет системных потоков для остановки."""
        pass

    def run(self):
        """Основной цикл GUI — QApplication.exec_()."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer

        from multiprocess_prototype.gui.main_window import InspectorWindow

        app = QApplication(sys.argv)

        app_cfg = self.get_config("config") or {}
        try:
            self._frontend_manager = _create_frontend_manager(self, app_cfg)
        except Exception:
            self._frontend_manager = None

        app.aboutToQuit.connect(self.gui_request_shutdown)

        self._window = InspectorWindow(
            title=self._window_title,
            width=self._window_width,
            height=self._window_height,
            process=self,
            camera_type=self._camera_type,
        )
        self._window.show()

        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_messages)
        self._timer.start(self._poll_interval)

        self._stop_timer = QTimer()
        self._stop_timer.timeout.connect(lambda: self._check_stop(app))
        self._stop_timer.start(100)

        app.exec_()

        if self._frontend_manager:
            self._frontend_manager.shutdown()

    def _poll_messages(self):
        """Вызывается QTimer. Читает rendered_frame_ready."""
        msgs = self.receive(timeout=0.001, channel_types=['data'])
        if msgs:
            types = [m.get("data_type", m.get("type", "?")) for m in msgs if isinstance(m, dict)]
            if getattr(self, "_gui_msg_count", 0) < 5:
                self._gui_msg_count = getattr(self, "_gui_msg_count", 0) + len(msgs)
                self._log_info(f"[DEBUG] gui: received {len(msgs)} msg(s), data_types={types}")
        for msg in msgs:
            if isinstance(msg, dict):
                msg_dict = msg
            elif hasattr(msg, "to_dict"):
                msg_dict = msg.to_dict()
            else:
                continue
            data_type = msg_dict.get("data_type")
            data = msg_dict.get("data", {})
            if data_type == "rendered_frame_ready":
                self._handle_new_frame(data)
            elif data_type == "status":
                self._handle_camera_status(data.get("status", ""))
            elif data_type == "error":
                self._handle_camera_error(data.get("error", ""))
            elif data_type == "parameters_response":
                self._handle_parameters_response(data)
            elif data_type == "enum_devices_response":
                self._handle_enum_devices_response(data)
            elif data_type == "camera_type_changed":
                self._handle_camera_type_changed(data)
            elif data_type == "fps_update":
                self._handle_fps_update(data)

    def _handle_camera_status(self, text: str):
        """Сообщение status от камеры (Hikvision)."""
        if self._window and hasattr(self._window, "update_camera_status"):
            self._window.update_camera_status(text)
        else:
            self._log_info(f"Camera status: {text}")

    def _handle_camera_error(self, text: str):
        """Сообщение error от камеры (Hikvision)."""
        self._log_error(f"Camera error: {text}")
        if self._window and hasattr(self._window, "update_camera_error"):
            self._window.update_camera_error(text)

    def _handle_parameters_response(self, data: dict):
        """Параметры камеры (Hikvision)."""
        if self._window and hasattr(self._window, "update_camera_parameters"):
            self._window.update_camera_parameters(data.get("parameters", {}))

    def _handle_enum_devices_response(self, data: dict):
        """Список устройств (Hikvision)."""
        if self._window and hasattr(self._window, "update_camera_devices"):
            self._window.update_camera_devices(data.get("devices", []))

    def _handle_camera_type_changed(self, data: dict):
        """Подтверждение переключения типа камеры — синхронизация UI."""
        if self._window and hasattr(self._window, "sync_camera_type"):
            self._window.sync_camera_type(data.get("camera_type", "simulator"))

    def _handle_fps_update(self, data: dict):
        """Обновление реального FPS с камеры."""
        if self._window and hasattr(self._window, "update_camera_fps"):
            self._window.update_camera_fps(data.get("fps", 0))

    def _handle_new_frame(self, data: dict):
        """Получен новый отрендеренный кадр (оригинал + маска)."""
        shm_actual_name = data.get("shm_actual_name")
        mask_shm_actual_name = data.get("mask_shm_actual_name")
        width = data.get("width", 640)
        height = data.get("height", 480)
        frame_id = data.get("frame_id", 0)
        show_original = data.get("show_original", True)
        show_mask = data.get("show_mask", True)

        original_frame = None
        mask_frame = None
        mm = self.memory_manager
        shm_index = data.get("shm_index", 0)
        mask_shm_index = data.get("mask_shm_index", 0)

        if mm:
            images = mm.read_images("renderer", "rendered_frame", shm_index, n=1)
            if images:
                original_frame = images[0]
            if mask_shm_actual_name:
                mask_images = mm.read_images("renderer", "mask_frame", mask_shm_index, n=1)
                if mask_images:
                    mask_frame = mask_images[0]
        if original_frame is None and shm_actual_name:
            original_frame = read_frame_from_shm(shm_actual_name, width, height)
        if mask_frame is None and mask_shm_actual_name:
            mask_frame = read_frame_from_shm(mask_shm_actual_name, width, height)

        if self._window:
            if frame_id <= 3 or frame_id % 50 == 0:
                self._log_info(
                    f"[DEBUG] gui: update_frame frame_id={frame_id} "
                    f"original={original_frame.shape if original_frame is not None else None} "
                    f"mask={mask_frame.shape if mask_frame is not None else None}"
                )
            self._window.update_frame(
                original_frame if original_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                mask_frame if mask_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                frame_id,
                show_original=show_original,
                show_mask=show_mask,
            )

    def _check_stop(self, app):
        """Проверка stop_event для graceful shutdown."""
        if self.should_stop():
            app.quit()

    # === Методы для вызова из GUI ===

    def gui_request_shutdown(self):
        """Запрос на остановку всей системы (при закрытии окна или Cmd+Q)."""
        try:
            self._log_info("GUI: requesting system shutdown")
            msg = self._msg.command(
                targets=["ProcessManager"],
                command="system.shutdown",
                args={},
                data={},
            )
            ok = self.send_message("ProcessManager", msg.to_dict())
            self._log_info(f"GUI: shutdown request sent, ok={ok}")
        except Exception as e:
            self._log_error(f"GUI: failed to send shutdown: {e}")

    def gui_start_capture(self):
        self._log_info("[DEBUG] gui: gui_start_capture -> sending start_capture to camera")
        msg = self._msg.command(targets=["camera"], command="start_capture", args={}, data={})
        self.send_message("camera", msg.to_dict())

    def gui_stop_capture(self):
        msg = self._msg.command(targets=["camera"], command="stop_capture", args={}, data={})
        self.send_message("camera", msg.to_dict())

    def gui_set_fps(self, fps: int):
        msg = self._msg.command(
            targets=["camera"],
            command="set_fps",
            args={"fps": fps},
            data={"fps": fps},
        )
        self.send_message("camera", msg.to_dict())

    def gui_set_color_range(
        self,
        b_lower: int,
        g_lower: int,
        r_lower: int,
        b_upper: int,
        g_upper: int,
        r_upper: int,
    ):
        """Отправка BGR-диапазона в processor для детекции цвета."""
        msg = self._msg.command(
            targets=["processor"],
            command="set_color_range",
            args={},
            data={
                "color_lower": [b_lower, g_lower, r_lower],
                "color_upper": [b_upper, g_upper, r_upper],
            },
        )
        self.send_message("processor", msg.to_dict())

    def gui_set_min_area(self, min_area: int):
        msg = self._msg.command(
            targets=["processor"],
            command="set_min_area",
            args={"min_area": min_area},
            data={"min_area": min_area},
        )
        self.send_message("processor", msg.to_dict())

    def gui_set_max_area(self, max_area: int):
        msg = self._msg.command(
            targets=["processor"],
            command="set_max_area",
            args={"max_area": max_area},
            data={"max_area": max_area},
        )
        self.send_message("processor", msg.to_dict())

    def gui_set_show_original(self, show: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_show_original",
            args={"show_original": show},
            data={"show_original": show},
        )
        self.send_message("renderer", msg.to_dict())

    def gui_set_show_mask(self, show: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_show_mask",
            args={"show_mask": show},
            data={"show_mask": show},
        )
        self.send_message("renderer", msg.to_dict())

    def gui_set_draw_contours(self, draw: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_draw_contours",
            args={"draw_contours": draw},
            data={"draw_contours": draw},
        )
        self.send_message("renderer", msg.to_dict())

    # --- Hikvision camera commands ---

    def gui_enum_devices(self):
        msg = self._msg.command(
            targets=["camera"], command="enum_devices", args={}, data={}
        )
        self.send_message("camera", msg.to_dict())

    def gui_open_camera(self, camera_index: int = 0):
        msg = self._msg.command(
            targets=["camera"],
            command="open",
            args={"camera_index": camera_index},
            data={"camera_index": camera_index},
        )
        self.send_message("camera", msg.to_dict())

    def gui_close_camera(self):
        msg = self._msg.command(
            targets=["camera"], command="close", args={}, data={}
        )
        self.send_message("camera", msg.to_dict())

    def gui_start_grabbing(self):
        msg = self._msg.command(
            targets=["camera"], command="start_grabbing", args={}, data={}
        )
        self.send_message("camera", msg.to_dict())

    def gui_stop_grabbing(self):
        msg = self._msg.command(
            targets=["camera"], command="stop_grabbing", args={}, data={}
        )
        self.send_message("camera", msg.to_dict())

    def gui_get_parameters(self):
        msg = self._msg.command(
            targets=["camera"], command="get_parameters", args={}, data={}
        )
        self.send_message("camera", msg.to_dict())

    def gui_set_parameters(
        self, frame_rate: float, exposure_time: float, gain: float
    ):
        msg = self._msg.command(
            targets=["camera"],
            command="set_parameters",
            args={},
            data={
                "frame_rate": frame_rate,
                "exposure_time": exposure_time,
                "gain": gain,
            },
        )
        self.send_message("camera", msg.to_dict())

    def gui_camera_type_changed(self, camera_type: str) -> bool:
        """
        Переключить тип камеры без перезапуска + сохранить в prefs.
        Отправляет set_camera_type в camera процесс.
        """
        from multiprocess_prototype.prefs import set_camera_type
        msg = self._msg.command(
            targets=["camera"],
            command="set_camera_type",
            args={"camera_type": camera_type},
            data={"camera_type": camera_type},
        )
        ok = self.send_message("camera", msg.to_dict())
        set_camera_type(camera_type)  # для следующего запуска
        return ok
