# multiprocess_prototype_v2/backend/gui_process_mixin.py
"""
GuiProcessMixin — gui_* и _handle_* для GUI-процесса.

Живёт в backend/, чтобы ``gui_process`` не импортировал пакет ``frontend`` (цикл импорта с ``GuiConfig`` / ``class_path_from_type(GuiProcess)``).

Требует: self._msg (MessageAdapter), self.send_message, self.memory_manager, self._window.

Команды camera/processor/renderer: targets из ``registers.command_routing`` (RegisterDispatchMeta).
"""

from typing import Any, Dict, Optional

import numpy as np

from multiprocess_prototype_v2.utils.shm_utils import read_frame_from_shm


class GuiProcessMixin:
    """
    Миксин с методами для связи GUI с backend.

    Ожидает атрибуты: _msg, _window, memory_manager, send_message, _log_info, _log_error.
    """

    def _send_command(
        self,
        command_id: str,
        args: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Сформировать command-сообщение и отправить первому получателю из targets.

        ``targets`` берутся из схем регистров (или EXPLICIT_COMMAND_TARGETS)
        через ``RoutedCommandSender`` на процессе.
        """
        args = args if args is not None else {}
        return self._routed_command_sender.send(command_id, args=args, data=data)

    def _poll_messages(self):
        """Вызывается QTimer. Читает rendered_frame_ready и другие data-сообщения."""
        msgs = self.receive(timeout=0.001, channel_types=["data"])
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
                original_frame
                if original_frame is not None
                else np.zeros((height, width, 3), dtype=np.uint8),
                mask_frame
                if mask_frame is not None
                else np.zeros((height, width, 3), dtype=np.uint8),
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
            ok = self._send_command("system.shutdown", {}, {})
            self._log_info(f"GUI: shutdown request sent, ok={ok}")
        except Exception as e:
            self._log_error(f"GUI: failed to send shutdown: {e}")

    def gui_start_capture(self):
        self._log_info("[DEBUG] gui: gui_start_capture -> sending start_capture to camera")
        self._send_command("start_capture", {}, {})

    def gui_stop_capture(self):
        self._send_command("stop_capture", {}, {})

    def gui_set_fps(self, fps: int):
        self._send_command("set_fps", {"fps": fps}, {"fps": fps})

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
        data = {
            "color_lower": [b_lower, g_lower, r_lower],
            "color_upper": [b_upper, g_upper, r_upper],
        }
        self._send_command("set_color_range", {}, data)

    def gui_set_min_area(self, min_area: int):
        self._send_command("set_min_area", {"min_area": min_area}, {"min_area": min_area})

    def gui_set_max_area(self, max_area: int):
        self._send_command("set_max_area", {"max_area": max_area}, {"max_area": max_area})

    def gui_set_show_original(self, show: bool):
        self._send_command(
            "set_show_original",
            {"show_original": show},
            {"show_original": show},
        )

    def gui_set_show_mask(self, show: bool):
        self._send_command(
            "set_show_mask",
            {"show_mask": show},
            {"show_mask": show},
        )

    def gui_set_draw_contours(self, draw: bool):
        self._send_command(
            "set_draw_contours",
            {"draw_contours": draw},
            {"draw_contours": draw},
        )

    def gui_enum_devices(self):
        self._send_command("enum_devices", {}, {})

    def gui_open_camera(self, camera_index: int = 0):
        self._send_command(
            "open",
            {"camera_index": camera_index},
            {"camera_index": camera_index},
        )

    def gui_close_camera(self):
        self._send_command("close", {}, {})

    def gui_start_grabbing(self):
        self._send_command("start_grabbing", {}, {})

    def gui_stop_grabbing(self):
        self._send_command("stop_grabbing", {}, {})

    def gui_get_parameters(self):
        self._send_command("get_parameters", {}, {})

    def gui_set_parameters(
        self, frame_rate: float, exposure_time: float, gain: float
    ):
        data = {
            "frame_rate": frame_rate,
            "exposure_time": exposure_time,
            "gain": gain,
        }
        self._send_command("set_parameters", {}, data)

    def gui_camera_type_changed(self, camera_type: str) -> bool:
        """
        Переключить тип камеры без перезапуска + сохранить в prefs.
        Отправляет set_camera_type в camera процесс.
        """
        from multiprocess_prototype_v2.persistence import set_camera_type

        ok = self._send_command(
            "set_camera_type",
            {"camera_type": camera_type},
            {"camera_type": camera_type},
        )
        set_camera_type(camera_type)
        return ok
