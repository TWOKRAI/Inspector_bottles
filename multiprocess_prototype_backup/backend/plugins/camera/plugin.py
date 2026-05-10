"""CameraServicePlugin — плагин захвата камеры через CameraService.

Оборачивает CameraService: поддерживает webcam и simulator сейчас,
hikvision — отдельным плагином позже.

Переносит всю логику из CameraProcess в plugin-архитектуру GenericProcess:
    configure(): SHM ring-buffer + middleware + сервис + команды + StateProxy
    start():     начальный state в StateStore
    shutdown():  воркер → сервис → SHM
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.backend.processes.camera.adapter import CameraAdapter
from multiprocess_prototype.backend.processes.camera.commands import (
    build_command_table,
    build_state_config_handlers,
)
from multiprocess_prototype.backend.shm.ring_buffer import RingBufferWriter
from multiprocess_prototype.services.camera.service import CameraService


class CameraServicePlugin(ProcessModulePlugin):
    """Захват кадров через CameraService (webcam / simulator / file).

    Команды регистрируются вручную через build_command_table (14 команд),
    поэтому commands = {} — автоматическая регистрация не используется.
    """

    name = "capture"
    category = "source"
    inputs = []
    outputs = []
    commands = {}  # регистрация вручную в configure()

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: SHM, сервис, команды, StateProxy, воркер."""
        self._ctx = ctx
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        shm_owner = f"camera_{self._camera_id}"
        shm_slot = f"camera_{self._camera_id}_frame"
        ring_buffer_size: int = cfg.get("ring_buffer_size", 3)

        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}] initializing "
            f"(type={cfg.get('camera_type', 'simulator')}, K={ring_buffer_size})..."
        )

        # Ring-buffer (AD-6) — round-robin по K SHM-слотам
        self._ring_buffer = RingBufferWriter(
            ctx.memory_manager,
            owner=shm_owner,
            slot_prefix=shm_slot,
            k=ring_buffer_size,
        )

        # SHM middleware для отправки кадров camera → processor
        self._frame_mw = FrameShmMiddleware(
            ctx.memory_manager, owner=shm_owner, slot=shm_slot
        )
        ctx.router_manager.add_send_middleware(self._frame_mw.on_send)

        # Адаптер + сервис (camera_id + ring_buffer параметризуют SHM naming)
        adapter = CameraAdapter(
            ctx._process, camera_id=self._camera_id, ring_buffer=self._ring_buffer
        )
        self._service = CameraService(output=adapter, config=cfg)

        # Команды: полная таблица из commands.py (14 команд)
        cmd_table = build_command_table(self._service, ctx.worker_manager)
        for cmd, handler in cmd_table.items():
            ctx.command_manager.register_command(cmd, handler)

        # StateProxy для чтения config / записи state
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            f"camera_{self._camera_id}",
            router=ctx.router_manager,
            server_target="ProcessManager",
        )
        ctx.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        # Подписка на config-ветвь — exclude_self, чтобы не реагировать на свои записи
        self._state_config_handlers = build_state_config_handlers(
            self._service, cmd_table["set_camera_type"]
        )
        self._state_proxy.subscribe(
            f"cameras.{self._camera_id}.config.*",
            callback=self._on_config_changed,
            exclude_self=True,
        )

        # Воркер захвата (стартует в паузе — ждёт start_capture)
        cfg_worker = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "capture_worker", self._capture_worker, cfg_worker, auto_start=False
        )
        ctx.worker_manager.pause_worker("capture_worker")

        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}] configured, "
            f"camera_type={self._service.current_type}"
        )

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: записать начальный state в StateStore."""
        self._state_proxy.set(f"cameras.{self._camera_id}.state.status", "initialized")
        self._state_proxy.set(
            f"cameras.{self._camera_id}.state.camera_type", self._service.current_type
        )
        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}] ready, "
            f"camera_type={self._service.current_type}"
        )

    def pause(self, ctx: PluginContext) -> None:
        ctx.worker_manager.pause_worker("capture_worker")

    def resume(self, ctx: PluginContext) -> None:
        if self._service.is_capturing:
            ctx.worker_manager.resume_worker("capture_worker")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: пауза воркера → shutdown сервиса → close SHM."""
        ctx.log_info(f"CameraServicePlugin[{self._camera_id}] shutting down...")
        if ctx.worker_manager:
            ctx.worker_manager.pause_worker("capture_worker")
        self._service.shutdown()
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set(f"cameras.{self._camera_id}.state.status", "shutdown")
            self._state_proxy.shutdown()
        if ctx.memory_manager:
            ctx.memory_manager.close_all(f"camera_{self._camera_id}")

    # --- Воркер захвата ---

    def _capture_worker(self, stop_event, pause_event) -> None:
        """Основной цикл захвата: capture_and_publish (config через StateProxy)."""
        ctx = self._ctx
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Обработка входящих сообщений (shm_region_changed от ProcessManager)
            msg = ctx.receive_message(timeout=0, channel_types=["data"])
            if msg:
                msg_dict = message_as_dict(msg)
                if msg_dict.get("data_type") == "shm_region_changed":
                    self._handle_shm_resized(msg_dict.get("data") or {}, ctx)
                    continue

            # Делегация захвата в сервис
            self._service.capture_and_publish()

            # Метрика is_capturing в StateStore
            if hasattr(self, "_state_proxy"):
                self._state_proxy.set(
                    f"cameras.{self._camera_id}.state.is_capturing", True
                )

    def _handle_shm_resized(self, data: dict, ctx: PluginContext) -> None:
        """Пересоздать ring-buffer после подтверждения resize SHM от ProcessManager."""
        new_w = data.get("new_width", 0)
        new_h = data.get("new_height", 0)
        if new_w <= 0 or new_h <= 0:
            return

        self._ring_buffer = RingBufferWriter(
            ctx.memory_manager,
            owner=f"camera_{self._camera_id}",
            slot_prefix=f"camera_{self._camera_id}_frame",
            k=self._ring_buffer._k,
        )
        # Обновить ссылку на ring_buffer в адаптере сервиса
        if hasattr(self._service, "_out") and hasattr(self._service._out, "_ring_buffer"):
            self._service._out._ring_buffer = self._ring_buffer
        self._service.handle_shm_resized(new_w, new_h)
        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}] SHM resized to {new_w}x{new_h}"
        )

    # --- StateProxy callback ---

    def _on_config_changed(self, deltas: list) -> None:
        """Callback StateProxy: config изменился → роутинг к обработчику."""
        prefix = f"cameras.{self._camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = self._state_config_handlers.get(field)
            if handler:
                handler(delta.new_value)
