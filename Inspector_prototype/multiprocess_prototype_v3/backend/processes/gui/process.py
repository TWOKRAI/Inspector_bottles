"""GuiProcess — инфраструктурный контейнер для GuiService."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from frontend_module.core.routed_command import RoutedCommandSender
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_prototype_v3.services.gui.service import GuiService
from multiprocess_prototype_v3.shared.frame_io import read_frame_from_shm


# --- Маппинг команд на целевые процессы ---
COMMAND_TO_REGISTER_KEY: dict[str, str] = {
    "start_capture": "camera",
    "stop_capture": "camera",
    "set_fps": "camera",
    "set_color_range": "processor",
    "set_min_area": "processor",
    "set_max_area": "processor",
    "set_show_original": "renderer",
    "set_show_mask": "renderer",
    "set_draw_contours": "renderer",
    "set_draw_bboxes": "renderer",
    "set_save_frames": "renderer",
    "enum_devices": "camera",
    "open": "camera",
    "close": "camera",
    "start_grabbing": "camera",
    "stop_grabbing": "camera",
    "get_parameters": "camera",
    "set_parameters": "camera",
    "set_camera_type": "camera",
}
EXPLICIT_COMMAND_TARGETS: dict[str, list[str]] = {"system.shutdown": ["ProcessManager"]}


def resolve_command_targets(command_id: str) -> list[str]:
    """Определить целевые процессы для команды."""
    if command_id in EXPLICIT_COMMAND_TARGETS:
        return list(EXPLICIT_COMMAND_TARGETS[command_id])
    return [COMMAND_TO_REGISTER_KEY[command_id]]


class GuiProcess(ProcessModule):
    """Процесс GUI: FrontendManager, команды, поллинг сообщений."""

    def _init_application_threads(self) -> None:
        self._log_info("GuiProcess initializing...")
        self._msg = MessageAdapter(sender=self.name)
        self._service = GuiService()

        self._routed_command_sender = RoutedCommandSender(
            router=self,
            message_factory=self._msg,
            resolve_targets=resolve_command_targets,
            get_args_builder=lambda cid: None,
        )
        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._window = None
        self._gui_msg_count = 0
        self._log_info("GuiProcess ready")

    def _init_system_threads(self):
        pass

    def _stop_system_threads(self):
        pass

    def run(self):
        """Запустить FrontendLauncher (PyQt5 event loop)."""
        from multiprocess_prototype_v3.frontend.launcher import FrontendLauncher

        app_cfg = self.get_config("config") or {}
        launcher = FrontendLauncher(process_ref=self, app_config=app_cfg)
        launcher.run(initial_window="loading", loading_delay_ms=2000)

    # --- Отправка команд ---
    def _send_command(self, command_id: str, args=None, data=None) -> bool:
        """Отправить команду через RoutedCommandSender."""
        return self._routed_command_sender.send(command_id, args=args or {}, data=data)

    # --- Поллинг сообщений (вызывается QTimer) ---
    def _poll_messages(self):
        """Получить входящие сообщения и передать хендлерам."""
        msgs = self.receive(timeout=0.001, channel_types=["data"])
        for msg in msgs:
            msg_dict = (
                msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
            )
            data_type = msg_dict.get("data_type")
            data = msg_dict.get("data", {})

            handler_name = self._service.dispatch_data_type(data_type)
            if handler_name:
                handler = getattr(self, f"_{handler_name}", None)
                if handler:
                    handler(data)

    # --- Хендлеры сообщений ---
    def _handle_camera_status(self, data):
        """Обновить статус камеры в окне."""
        text = data.get("status", "")
        if self._window and hasattr(self._window, "update_camera_status"):
            self._window.update_camera_status(text)

    def _handle_camera_error(self, data):
        """Обработать ошибку камеры и отобразить в окне."""
        text = data.get("error", "")
        self._log_error(f"Camera error: {text}")
        if self._window and hasattr(self._window, "update_camera_error"):
            self._window.update_camera_error(text)

    def _handle_parameters_response(self, data):
        """Передать параметры камеры в окно."""
        if self._window and hasattr(self._window, "update_camera_parameters"):
            self._window.update_camera_parameters(data.get("parameters", {}))

    def _handle_enum_devices_response(self, data):
        """Передать список устройств в окно."""
        if self._window and hasattr(self._window, "update_camera_devices"):
            self._window.update_camera_devices(data.get("devices", []))

    def _handle_camera_type_changed(self, data):
        """Синхронизировать тип камеры в окне."""
        if self._window and hasattr(self._window, "sync_camera_type"):
            self._window.sync_camera_type(data.get("camera_type", "simulator"))

    def _handle_fps_update(self, data):
        """Обновить счётчик FPS в окне."""
        if self._window and hasattr(self._window, "update_camera_fps"):
            self._window.update_camera_fps(data.get("fps", 0))

    def _handle_new_frame(self, data):
        """Прочитать пару кадров из SHM и передать в окно."""
        mm = self.memory_manager

        def read_rendered_fn(index):
            if mm:
                images = mm.read_images("renderer", "rendered_frame", index, n=1)
                return images[0] if images else None
            return None

        def read_mask_fn(index, actual_name):
            if mm:
                images = mm.read_images("renderer", "mask_frame", index, n=1)
                return images[0] if images else None
            return None

        original, mask = self._service.read_frame_pair(
            data,
            read_rendered_fn,
            read_mask_fn,
            read_frame_from_shm,
        )

        if self._window:
            self._window.update_frame(
                original,
                mask,
                data.get("frame_id", 0),
                show_original=data.get("show_original", True),
                show_mask=data.get("show_mask", True),
            )

    def _check_stop(self, app):
        """Завершить Qt приложение если процесс должен остановиться."""
        if self.should_stop():
            app.quit()

    # --- GUI API (все gui_* методы — API для frontend, остаются в процессе) ---
    def gui_request_shutdown(self):
        """Отправить команду shutdown всем процессам."""
        try:
            self._send_command("system.shutdown", {}, {})
        except Exception as e:
            self._log_error(f"GUI: failed to send shutdown: {e}")

    def gui_start_capture(self):
        """Запустить захват кадров."""
        self._send_command("start_capture", {}, {})

    def gui_stop_capture(self):
        """Остановить захват кадров."""
        self._send_command("stop_capture", {}, {})

    def gui_set_fps(self, fps):
        """Установить FPS камеры."""
        self._send_command("set_fps", {"fps": fps}, {"fps": fps})

    def gui_set_color_range(self, b_lower, g_lower, r_lower, b_upper, g_upper, r_upper):
        """Установить цветовой диапазон для процессора."""
        self._send_command(
            "set_color_range",
            {},
            {"color_lower": [b_lower, g_lower, r_lower], "color_upper": [b_upper, g_upper, r_upper]},
        )

    def gui_set_min_area(self, min_area):
        """Установить минимальную площадь контура."""
        self._send_command("set_min_area", {"min_area": min_area}, {"min_area": min_area})

    def gui_set_max_area(self, max_area):
        """Установить максимальную площадь контура."""
        self._send_command("set_max_area", {"max_area": max_area}, {"max_area": max_area})

    def gui_set_show_original(self, show):
        """Переключить отображение оригинального кадра."""
        self._send_command("set_show_original", {"show_original": show}, {"show_original": show})

    def gui_set_show_mask(self, show):
        """Переключить отображение маски."""
        self._send_command("set_show_mask", {"show_mask": show}, {"show_mask": show})

    def gui_set_draw_contours(self, draw):
        """Переключить отрисовку контуров."""
        self._send_command("set_draw_contours", {"draw_contours": draw}, {"draw_contours": draw})

    def gui_enum_devices(self):
        """Запросить список доступных устройств камеры."""
        self._send_command("enum_devices", {}, {})

    def gui_open_camera(self, camera_index=0):
        """Открыть камеру по индексу."""
        self._send_command("open", {"camera_index": camera_index}, {"camera_index": camera_index})

    def gui_close_camera(self):
        """Закрыть камеру."""
        self._send_command("close", {}, {})

    def gui_start_grabbing(self):
        """Начать захват кадров с камеры."""
        self._send_command("start_grabbing", {}, {})

    def gui_stop_grabbing(self):
        """Остановить захват кадров с камеры."""
        self._send_command("stop_grabbing", {}, {})

    def gui_get_parameters(self):
        """Запросить параметры камеры."""
        self._send_command("get_parameters", {}, {})

    def gui_set_parameters(self, frame_rate, exposure_time, gain):
        """Установить параметры камеры (frame_rate, exposure_time, gain)."""
        self._send_command(
            "set_parameters",
            {},
            {"frame_rate": frame_rate, "exposure_time": exposure_time, "gain": gain},
        )

    def gui_camera_type_changed(self, camera_type):
        """Сменить тип камеры (simulator / real / etc.)."""
        return self._send_command(
            "set_camera_type", {"camera_type": camera_type}, {"camera_type": camera_type}
        )
