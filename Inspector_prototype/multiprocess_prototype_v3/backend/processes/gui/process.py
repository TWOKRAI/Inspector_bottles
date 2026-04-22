"""GuiProcess — инфраструктурный контейнер для GuiService.

Тонкий ProcessModule: инициализация, polling сообщений, dispatch в handlers.
Обработчики входящих сообщений — в handlers.py.
"""
from __future__ import annotations

from frontend_module.core.routed_command import RoutedCommandSender
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_prototype_v3.registers.commands.catalog import GUI_COMMAND_CATALOG
from multiprocess_prototype_v3.registers.commands.routing import resolve_command_targets
from multiprocess_prototype_v3.services.gui.service import GuiService

from .handlers import (
    handle_camera_error,
    handle_camera_status,
    handle_camera_type_changed,
    handle_enum_devices_response,
    handle_fps_update,
    handle_parameters_response,
    handle_recorder_stats,
)

# Dispatch table: data_type → handler function
_HANDLER_MAP = {
    "status": handle_camera_status,
    "error": handle_camera_error,
    "parameters_response": handle_parameters_response,
    "enum_devices_response": handle_enum_devices_response,
    "camera_type_changed": handle_camera_type_changed,
    "fps_update": handle_fps_update,
    "recorder_stats": handle_recorder_stats,
}


class GuiProcess(ProcessModule):
    """Процесс GUI: FrontendManager, команды, поллинг сообщений."""

    def _init_application_threads(self) -> None:
        self._log_info("GuiProcess initializing...")

        # SHM middleware: приём rendered-кадров от renderer (renderer/rendered_frame)
        self._recv_frame_mw = FrameShmMiddleware(
            self.memory_manager, owner="renderer", slot="rendered_frame"
        )
        self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        self._msg = MessageAdapter(sender=self.name)
        self._service = GuiService()

        self._routed_command_sender = RoutedCommandSender(
            router=self,
            message_factory=self._msg,
            resolve_targets=resolve_command_targets,
            get_args_builder=lambda cid: GUI_COMMAND_CATALOG.get(cid),
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

    # --- Поллинг сообщений (вызывается QTimer) ---

    def _poll_messages(self):
        """Получить входящие сообщения и передать в handlers."""
        msgs = self.receive(timeout=0.001, channel_types=["data"])
        for msg in msgs:
            msg_dict = (
                msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
            )
            data_type = msg_dict.get("data_type")
            data = msg_dict.get("data", {})

            # Dispatch через таблицу
            handler = _HANDLER_MAP.get(data_type)
            if handler is not None:
                if handler is handle_camera_error:
                    handler(self._window, data, self._log_error)
                else:
                    handler(self._window, data)
            elif data_type == "rendered_frame_ready":
                self._handle_new_frame(data)

    # --- Сложный handler (зависит от memory_manager + service) ---

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

        # Fallback: чтение по shm_actual_name через MemoryManager не поддерживается,
        # возвращаем None — GuiService подставит чёрный кадр.
        def _no_fallback(_name, _w, _h):
            return None

        original, mask = self._service.read_frame_pair(
            data,
            read_rendered_fn,
            read_mask_fn,
            _no_fallback,
        )

        if self._window:
            self._window.update_frame(
                original,
                mask,
                data.get("frame_id", 0),
                show_original=data.get("show_original", True),
                show_mask=data.get("show_mask", True),
            )

        # Phase 6: dispatch кадров в display-окна через DisplayRouter
        if hasattr(self, '_display_router') and self._display_router is not None:
            for sub in self._display_router.get_active_subscriptions():
                channel = f"display_{sub.window_id}"
                self._display_router.dispatch_frame(channel, original)

    def gui_request_shutdown(self):
        """Вызывается Qt при aboutToQuit — запрашиваем остановку процесса."""
        self._log_info("GUI requested shutdown")
        self.stop_process = True

    def _check_stop(self, app):
        """Завершить Qt приложение если процесс должен остановиться."""
        if self.should_stop():
            app.quit()
