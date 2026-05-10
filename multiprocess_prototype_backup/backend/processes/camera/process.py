"""CameraProcess — инфраструктурный контейнер для CameraService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
Вся бизнес-логика — в CameraService.

Phase 3: параметризация по camera_id — каждый экземпляр обслуживает
одну камеру с уникальным SHM region/slot.
"""
from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.backend.shm.ring_buffer import RingBufferWriter
from multiprocess_prototype.services.camera.service import CameraService

from .adapter import CameraAdapter
from .commands import build_command_table, build_state_config_handlers


class CameraProcess(ProcessModule):
    """Процесс камеры. Инфраструктура: воркеры, IPC, SHM, команды.

    Делегирует бизнес-логику в CameraService через adapter pattern.
    camera_id из config определяет SHM region/slot naming.
    """

    def _init_application_threads(self) -> None:
        # camera_id из конфига (default 0 для обратной совместимости)
        app_cfg = self.get_config("config") or {}
        self._camera_id: int = app_cfg.get("camera_id", 0)
        shm_owner = f"camera_{self._camera_id}"
        shm_slot = f"camera_{self._camera_id}_frame"

        ring_buffer_size = app_cfg.get("ring_buffer_size", 3)
        self._log_info(f"CameraProcess[{self._camera_id}] initializing (K={ring_buffer_size})...")

        # Ring-buffer (AD-6) — round-robin по K SHM-слотам
        self._ring_buffer = RingBufferWriter(
            self.memory_manager, owner=shm_owner, slot_prefix=shm_slot, k=ring_buffer_size
        )

        # SHM middleware для отправки кадров (camera → processor)
        self._frame_mw = FrameShmMiddleware(
            self.memory_manager, owner=shm_owner, slot=shm_slot
        )
        self.router_manager.add_send_middleware(self._frame_mw.on_send)

        # Создать сервис с адаптером для IPC (параметризован camera_id + ring-buffer)
        adapter = CameraAdapter(self, camera_id=self._camera_id, ring_buffer=self._ring_buffer)
        self._service = CameraService(output=adapter, config=app_cfg)

        # Команды из таблицы
        cmd_table = build_command_table(self._service, self.worker_manager)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # StateProxy для чтения config / записи state
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            f"camera_{self._camera_id}",
            router=self.router_manager,
            server_target="ProcessManager",
        )
        self.state_proxy = self._state_proxy  # ADR-SS-006: авто-регистрация в _init_state_proxy()

        # Подписка на config-ветвь — exclude_self, чтобы не реагировать на собственные записи
        self._state_config_handlers = build_state_config_handlers(
            self._service, cmd_table["set_camera_type"]
        )
        self._state_proxy.subscribe(
            f"cameras.{self._camera_id}.config.*",
            callback=self._on_config_changed,
            exclude_self=True,
        )

        # Начальная запись state
        self._state_proxy.set(f"cameras.{self._camera_id}.state.status", "initialized")
        self._state_proxy.set(
            f"cameras.{self._camera_id}.state.camera_type", self._service.current_type
        )

        # Воркер захвата (стартует в паузе — ждёт start_capture)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, cfg, auto_start=False
        )
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(
            f"CameraProcess[{self._camera_id}] ready, camera_type={self._service.current_type}"
        )

    # --- Воркер захвата ---

    def _capture_worker(self, stop_event, pause_event) -> None:
        """Основной цикл захвата: capture_and_publish (config через StateProxy)."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Обработка входящих сообщений
            msg = self.receive_message(timeout=0, channel_types=["data"])
            if msg:
                msg_dict = message_as_dict(msg)
                data_type = msg_dict.get("data_type")
                if data_type == "shm_region_changed":
                    # ProcessManager подтвердил пересоздание SHM (Task 2.2)
                    data = msg_dict.get("data") or {}
                    new_w = data.get("new_width", 0)
                    new_h = data.get("new_height", 0)
                    if new_w > 0 and new_h > 0:
                        # Пересоздать ring-buffer с новым shape
                        self._ring_buffer = RingBufferWriter(
                            self.memory_manager,
                            owner=f"camera_{self._camera_id}",
                            slot_prefix=f"camera_{self._camera_id}_frame",
                            k=self._ring_buffer._k,
                        )
                        # Обновить адаптер: подменить ring_buffer
                        if hasattr(self._service, '_out') and hasattr(self._service._out, '_ring_buffer'):
                            self._service._out._ring_buffer = self._ring_buffer
                        # Уведомить сервис о новых размерах
                        self._service.handle_shm_resized(new_w, new_h)
                        self._log_info(
                            f"CameraProcess[{self._camera_id}] SHM resized to {new_w}x{new_h}"
                        )
                    continue

            # Делегация захвата в сервис
            self._service.capture_and_publish()

            # Запись метрик в StateStore (ThrottleMiddleware ограничит частоту на стороне менеджера)
            if hasattr(self, "_state_proxy"):
                self._state_proxy.set(
                    f"cameras.{self._camera_id}.state.is_capturing", True
                )

    # --- StateProxy callback ---

    def _on_config_changed(self, deltas: list) -> None:
        """Callback StateProxy: config изменился → роутинг к обработчику.

        Принимает список Delta от StateProxy (подписка cameras.{id}.config.*).
        Суффикс пути после cameras.{id}.config. используется как ключ маппинга.
        """
        prefix = f"cameras.{self._camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = self._state_config_handlers.get(field)
            if handler:
                handler(delta.new_value)

    # --- Shutdown ---

    def shutdown(self) -> bool:
        """Корректное завершение: пауза воркера → shutdown сервиса → close SHM."""
        self._log_info(f"CameraProcess[{self._camera_id}] shutting down...")
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        self._service.shutdown()
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set(
                f"cameras.{self._camera_id}.state.status", "shutdown"
            )
            self._state_proxy.shutdown()
        if self.memory_manager:
            self.memory_manager.close_all(f"camera_{self._camera_id}")
        self.is_initialized = False
        return super().shutdown()
