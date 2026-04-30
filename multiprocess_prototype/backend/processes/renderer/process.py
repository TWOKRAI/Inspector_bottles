"""RendererProcess — инфраструктурный контейнер для RendererService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
"""

from __future__ import annotations

import time

import numpy as np
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.services.renderer.service import RendererService

from .adapter import RendererAdapter
from .commands import build_command_table, build_state_config_handlers


class RendererProcess(ProcessModule):
    """Процесс рендеринга. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("RendererProcess initializing...")

        # Task 2.4: НЕ регистрируем статический FrameShmMiddleware для camera frame.
        # При N камерах owner/slot определяются динамически из camera_id в данных
        # сообщения (см. _read_original_frame). Middleware не нужен — кадры читаются
        # вручную из SHM по camera_id.

        adapter = RendererAdapter(self)
        self._service = RendererService(
            output=adapter,
            output_dir=self.get_config("output_dir", "./output_frames"),
            save_frames=self.get_config("save_frames", False),
            draw_bboxes=self.get_config("draw_bboxes", True),
            draw_contours=self.get_config("draw_contours", True),
            show_original=self.get_config("show_original", True),
            show_mask=self.get_config("show_mask", True),
        )

        # Команды из таблицы
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # StateProxy для чтения config / записи state
        from state_store.proxy.state_proxy import StateProxy

        self._state_proxy = StateProxy("renderer", router=self.router_manager)

        # Регистрация обработчика state.changed
        self.router_manager.register_message_handler("state.changed", self._state_proxy.on_state_changed)

        # Config handlers для StateProxy callback
        self._state_config_handlers = build_state_config_handlers(self._service)

        # Подписка на renderer config
        self._state_proxy.subscribe(
            "renderer.config.*",
            callback=self._on_config_changed,
            exclude_self=True,
        )

        # Начальная запись state
        self._state_proxy.set("renderer.state.status", "initialized")

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, cfg, auto_start=True
        )
        self._log_info("RendererProcess ready")

    # --- Воркер рендеринга ---

    def _render_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → read SHM → service.render_frame() (config через StateProxy)."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            data_type = msg_dict.get("data_type")

            # Task 2.2: SHM-регион камеры пересоздан — переоткрыть handle
            if data_type == "shm_region_changed":
                change_data = msg_dict.get("data") or {}
                region_name = change_data.get("region_name", "")
                new_w = change_data.get("new_width", 0)
                new_h = change_data.get("new_height", 0)
                if region_name and new_w > 0 and new_h > 0:
                    camera_id = change_data.get("camera_id", 0)
                    owner = f"camera_{camera_id}"
                    if self.memory_manager:
                        self.memory_manager.close_all(owner)
                    self._log_info(
                        "RendererProcess: SHM region %s resized to %dx%d",
                        region_name,
                        new_w,
                        new_h,
                    )
                continue

            if data_type != "detection_result":
                continue
            data = msg_dict.get("data", {})

            # Task 2.4: кадр читается напрямую из SHM по camera_id из данных
            # (middleware не используется — у каждой камеры свой owner/slot)
            original = self._read_original_frame(data)
            if original is None:
                continue
            mask = self._read_mask_frame(data, original.shape[1], original.shape[0])

            # Делегация бизнес-логики в сервис
            self._service.render_frame(original, mask, data)

    def _read_original_frame(self, data: dict) -> np.ndarray | None:
        """Прочитать оригинальный кадр из SHM камеры через MemoryManager.

        Task 2.4: owner/slot определяются динамически по camera_id из данных.
        """
        mm = self.memory_manager
        if not mm:
            return None
        camera_id = data.get("camera_id", 0)
        owner = f"camera_{camera_id}"
        slot = f"camera_{camera_id}_frame"
        images = mm.read_images(owner, slot, data.get("shm_index", 0), n=1)
        if images:
            return images[0].copy()
        return None

    def _read_mask_frame(self, data: dict, width: int, height: int) -> np.ndarray:
        """Прочитать маску из SHM процессора через MemoryManager.

        Task 2.4: owner/slot определяются динамически по camera_id из данных.
        """
        mm = self.memory_manager
        camera_id = data.get("camera_id", 0)
        mask_owner = f"processor_{camera_id}"
        mask_slot = f"processor_{camera_id}_mask"
        if mm and data.get("mask_shm_actual_name"):
            images = mm.read_images(mask_owner, mask_slot, data.get("mask_shm_index", 0), n=1)
            if images:
                return images[0].copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    # --- StateProxy callback ---

    def _on_config_changed(self, deltas: list) -> None:
        """Callback StateProxy: config изменился → роутинг к обработчику.

        Принимает список Delta от StateProxy (подписка renderer.config.*).
        Суффикс пути после renderer.config. используется как ключ маппинга.
        """
        prefix = "renderer.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = self._state_config_handlers.get(field)
            if handler:
                handler(delta.new_value)

    # --- Shutdown ---

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set("renderer.state.status", "shutdown")
            self._state_proxy.shutdown()
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()
