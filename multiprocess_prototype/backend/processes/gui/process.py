"""GuiProcess — инфраструктурный контейнер для GuiService.

Тонкий ProcessModule: инициализация, polling сообщений, dispatch в handlers.
Обработчики входящих сообщений — в handlers.py.
"""
from __future__ import annotations

import time

from multiprocess_framework.modules.frontend_module.core.routed_command import RoutedCommandSender
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_prototype.registers.commands.catalog import GUI_COMMAND_CATALOG
from multiprocess_prototype.registers.commands.routing import resolve_command_targets
from multiprocess_prototype.services.gui.service import GuiService
from multiprocess_prototype.services.metrics import LatencyTracker

from .handlers import (
    handle_camera_error,
    handle_camera_status,
    handle_camera_type_changed,
    handle_enum_devices_response,
    handle_fps_update,
    handle_parameters_response,
    handle_recorder_stats,
    handle_shm_region_changed,
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
    "shm_region_changed": handle_shm_region_changed,
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
        self._latency_tracker = LatencyTracker(log_interval_sec=10.0, buffer_size=1000)

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
        # Watchdog state
        self._last_frame_time = 0.0
        self._watchdog_state = "ok"

        # Phase 4d: GuiStateProxy — Qt-safe StateProxy для GUI-процесса
        from state_store.proxy.gui_state_proxy import GuiStateProxy

        self._state_proxy = GuiStateProxy("gui", router=self.router_manager)

        # Регистрация обработчика state.changed
        self.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        # Начальная запись состояния в StateStore
        self._state_proxy.set("gui.state.status", "initialized")

        self._log_info("GuiProcess ready")

    def _init_system_threads(self):
        pass

    def _stop_system_threads(self):
        pass

    def run(self):
        """Запустить FrontendLauncher (PySide6 event loop)."""
        # Базовый run(): статус RUNNING + запуск heartbeat воркера
        super().run()

        from multiprocess_prototype.frontend.launcher import FrontendLauncher

        app_cfg = self.get_config("config") or {}
        launcher = FrontendLauncher(process_ref=self, app_config=app_cfg)
        launcher.run(initial_window="loading", loading_delay_ms=2000)

    # --- Поллинг сообщений (вызывается QTimer) ---

    def _poll_messages(self):
        """Получить входящие сообщения и передать в handlers."""
        msgs = self.receive(timeout=0.001, channel_types=["data", "system"])
        for msg in msgs:
            msg_dict = (
                msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else {})
            )

            # System-сообщения (broadcast от ProcessMonitor)
            msg_type = msg_dict.get("type")
            if msg_type == "system":
                subtype = msg_dict.get("subtype", "")
                if subtype in ("process_status_changed", "process_full_status"):
                    self._handle_process_status_update(msg_dict)
                continue  # system-сообщения не имеют data_type

            # Data-сообщения: dispatch через таблицу
            data_type = msg_dict.get("data_type")
            data = msg_dict.get("data", {})

            handler = _HANDLER_MAP.get(data_type)
            if handler is not None:
                if handler is handle_camera_error:
                    handler(self._window, data, self._log_error)
                else:
                    handler(self._window, data)
            elif data_type == "rendered_frame_ready":
                self._handle_new_frame(data)

        self._check_watchdog()

    def _handle_process_status_update(self, msg: dict) -> None:
        """Переслать broadcast process_status_changed / process_full_status в ProcessDataBridge."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.process_data_bridge import (
            get_active_bridge,
        )

        bridge = get_active_bridge()
        if bridge is None:
            return

        subtype = msg.get("subtype", "")
        if subtype == "process_status_changed":
            bridge.on_status_update(msg)
        elif subtype == "process_full_status":
            processes = msg.get("processes", {})
            bridge.on_full_snapshot(processes)

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

        # Расчёт e2e latency
        gui_display_ts = time.time()
        capture_ts = data.get("capture_ts", 0.0)
        if capture_ts:
            e2e_latency_ms = (gui_display_ts - capture_ts) * 1000
        else:
            e2e_latency_ms = 0.0
        self._latency_tracker.record(e2e_latency_ms)
        self._latency_tracker.maybe_log()

        if self._window:
            self._window.update_frame(
                original,
                mask,
                data.get("frame_id", 0),
                show_original=data.get("show_original", True),
                show_mask=data.get("show_mask", True),
            )
            self._window.update_latency(e2e_latency_ms)

        # Обновить время последнего кадра и сбросить watchdog
        self._last_frame_time = time.time()
        self._reset_watchdog()

        # Phase 6: dispatch кадров в display-окна через DisplayRouter
        if hasattr(self, '_display_router') and self._display_router is not None:
            for sub in self._display_router.get_active_subscriptions():
                channel = f"display_{sub.window_id}"
                self._display_router.dispatch_frame(channel, original)

    def _reset_watchdog(self) -> None:
        """Сбросить watchdog в состояние ok если он не в ok."""
        if self._watchdog_state != "ok":
            self._watchdog_state = "ok"
            if self._window:
                self._window.hide_watchdog()

    def _check_watchdog(self) -> None:
        """Проверить таймаут кадров и обновить состояние watchdog."""
        if self._last_frame_time == 0.0:
            # Ещё не получили ни одного кадра — не запускаем watchdog
            return
        elapsed = time.time() - self._last_frame_time
        if elapsed > 15.0 and self._watchdog_state != "dialog_shown":
            self._watchdog_state = "dialog_shown"
            if self._window:
                self._window.show_watchdog_dialog()
        elif elapsed > 5.0 and self._watchdog_state == "ok":
            self._watchdog_state = "warning"
            if self._window:
                self._window.show_watchdog_warning("Ожидание backend...")

    def gui_request_shutdown(self):
        """Вызывается Qt при aboutToQuit — запрашиваем остановку процесса."""
        self._log_info("GUI requested shutdown")
        self._stop_requested = True

    def _check_stop(self, app):
        """Завершить Qt приложение если процесс должен остановиться."""
        if self.should_stop():
            app.quit()

    def shutdown(self):
        """Остановка процесса: записываем статус и завершаем StateProxy."""
        # Phase 4d: записать финальный статус перед отключением
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set("gui.state.status", "shutdown")
            self._state_proxy.shutdown()
        return super().shutdown()
