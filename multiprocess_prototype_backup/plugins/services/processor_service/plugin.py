"""ProcessorServicePlugin — оркестратор обработки кадров.

Самый сложный плагин: dual SHM middleware (receive frame + send mask),
ProcessorService, ChainThreadPool, WorkerPoolDispatcher, dual StateProxy
подписки (config + regions), каталог операций.

Построчный перенос из ProcessorProcess._init_application_threads().
"""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.backend.processes.processor.adapter import ProcessorAdapter
from multiprocess_prototype.backend.processes.processor.commands import (
    build_command_table,
    build_state_config_handlers,
    _apply_vision_pipeline,
)
from multiprocess_prototype.services.processor.chain.thread_pool import ChainThreadPool
from multiprocess_prototype.services.processor.detection import ColorBlobDetector
from multiprocess_prototype.services.processor.service import ProcessorService
from multiprocess_prototype.services.processor.worker_pool.dispatcher import WorkerPoolDispatcher


@register_plugin(
    "processor",
    category="processing",
    description="Оркестратор обработки кадров (SHM, chain, detector, worker pool)"
)
class ProcessorServicePlugin(ProcessModulePlugin):
    """Оркестратор обработки кадров."""

    name = "processor"
    category = "processing"
    inputs = []
    outputs = []
    commands = {}  # регистрация вручную

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: SHM middleware, сервис, команды, StateProxy, воркер."""
        self._ctx = ctx
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        process = ctx._process

        # SHM middleware: приём кадров от камеры
        self._recv_frame_mw = FrameShmMiddleware(
            ctx.memory_manager,
            owner=f"camera_{self._camera_id}",
            slot=f"camera_{self._camera_id}_frame",
        )
        ctx.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        # SHM middleware: отправка масок
        self._send_mask_mw = FrameShmMiddleware(
            ctx.memory_manager,
            owner=ctx.process_name,
            slot=f"processor_{self._camera_id}_mask",
        )
        ctx.router_manager.add_send_middleware(self._send_mask_mw.on_send)

        # Адаптер
        adapter = ProcessorAdapter(process, camera_id=self._camera_id)

        # Детектор
        detector = ColorBlobDetector(
            cfg.get("color_lower", [0, 0, 150]),
            cfg.get("color_upper", [100, 100, 255]),
            cfg.get("min_area", 500),
            cfg.get("max_area", 50000),
        )

        # ChainThreadPool
        workers_per_processor: int = cfg.get("workers_per_processor", 2)
        step_timeout: float = float(cfg.get("step_timeout", 10.0))
        if workers_per_processor > 1:
            self._pool: ChainThreadPool | None = ChainThreadPool(
                max_workers=workers_per_processor,
                step_timeout=step_timeout,
            )
        else:
            self._pool = None

        # WorkerPoolDispatcher
        worker_pool_size: int = cfg.get("worker_pool_size", 0)
        if worker_pool_size > 0:
            self._dispatcher: WorkerPoolDispatcher | None = WorkerPoolDispatcher(
                send_fn=lambda target, data, data_type: adapter._io.send_data(
                    target, data_type, data
                ),
                worker_count=worker_pool_size,
                timeout=float(cfg.get("worker_timeout", 5.0)),
                input_queue_size=int(cfg.get("worker_queue_size", 4)),
            )
        else:
            self._dispatcher = None

        # Сервис
        self._service = ProcessorService(
            output=adapter,
            detector=detector,
            target_width=cfg.get("resolution_width", 640),
            target_height=cfg.get("resolution_height", 480),
            pool=self._pool,
            dispatcher=self._dispatcher,
        )

        # Каталог операций
        catalog_path = cfg.get("catalog_path", "data/processing_catalog.yaml")
        resolved_catalog = str(Path(catalog_path).resolve())
        self._service.set_catalog(resolved_catalog)

        # Команды
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            ctx.command_manager.register_command(cmd, handler)

        # StateProxy
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            f"processor_{self._camera_id}",
            router=ctx.router_manager,
            server_target="ProcessManager",
        )
        ctx.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        # Config handlers
        self._state_config_handlers = build_state_config_handlers(
            self._service, router=ctx.router_manager,
        )

        # Подписка на processor config
        self._state_proxy.subscribe(
            f"processor.{self._camera_id}.config.*",
            callback=self._on_config_changed,
            exclude_self=True,
        )

        # Подписка на regions
        self._state_proxy.subscribe(
            f"cameras.{self._camera_id}.regions.**",
            callback=self._on_regions_changed,
            exclude_self=True,
        )

        # Воркер
        worker_cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "processing_worker", self._processing_worker, worker_cfg, auto_start=True
        )

        ctx.log_info(
            f"ProcessorServicePlugin[{self._camera_id}] configured "
            f"(pool={'yes' if self._pool else 'no'}, "
            f"dispatcher={'yes' if self._dispatcher else 'no'})"
        )

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: начальный state."""
        self._state_proxy.set(
            f"processor.{self._camera_id}.state.status", "initialized"
        )
        ctx.log_info(f"ProcessorServicePlugin[{self._camera_id}] ready")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED."""
        ctx.log_info(f"ProcessorServicePlugin[{self._camera_id}] shutting down...")

        if hasattr(self, "_state_proxy"):
            self._state_proxy.set(
                f"processor.{self._camera_id}.state.status", "shutdown"
            )
            self._state_proxy.shutdown()

        if self._pool is not None:
            self._pool.shutdown(wait=True)

        if ctx.memory_manager:
            ctx.memory_manager.close_all(ctx.process_name)

    # --- Воркер обработки ---

    def _processing_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → SHM frame → service.process_frame()."""
        frames_processed = 0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self._ctx.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            data_type = msg_dict.get("data_type")

            # SHM resize
            if data_type == "shm_region_changed":
                self._handle_shm_resize(msg_dict)
                continue

            # Worker pool response
            if data_type == "worker_task_response":
                if self._dispatcher is not None:
                    self._dispatcher.handle_response(msg_dict.get("data") or {})
                continue

            if data_type != "frame_ready":
                continue

            frame = msg_dict.get("frame")
            if frame is None:
                continue

            data = msg_dict.get("data", {})
            self._service.process_frame(frame, data)

            if hasattr(self, "_state_proxy"):
                self._state_proxy.set(
                    f"processor.{self._camera_id}.state.is_processing", True
                )

            frames_processed += 1
            if self._dispatcher is not None and frames_processed % 100 == 0:
                self._export_worker_pool_stats()

    def _handle_shm_resize(self, msg_dict: dict) -> None:
        """SHM-регион камеры пересоздан — переоткрыть handle."""
        change_data = msg_dict.get("data") or {}
        region_name = change_data.get("region_name", "")
        new_w = change_data.get("new_width", 0)
        new_h = change_data.get("new_height", 0)
        if not region_name or new_w <= 0 or new_h <= 0:
            return

        camera_id = change_data.get("camera_id", 0)
        owner = f"camera_{camera_id}"
        if self._ctx.memory_manager:
            self._ctx.memory_manager.close_all(owner)

        self._recv_frame_mw = FrameShmMiddleware(
            self._ctx.memory_manager, owner=owner, slot=region_name
        )
        self._service._target_width = new_w
        self._service._target_height = new_h
        self._ctx.log_info(
            f"ProcessorServicePlugin: SHM {region_name} resized to {new_w}x{new_h}"
        )

    # --- StateProxy callbacks ---

    def _on_config_changed(self, deltas: list) -> None:
        """Config fields → dispatch to handler."""
        prefix = f"processor.{self._camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = self._state_config_handlers.get(field)
            if handler:
                handler(delta.new_value)

    def _on_regions_changed(self, deltas: list) -> None:
        """Regions tree changed → ONE rebuild_runnables()."""
        if not deltas:
            return
        regions = self._state_proxy.get_subtree(
            f"cameras.{self._camera_id}.regions"
        )
        if regions is not None:
            pipeline_data = {
                "cameras": {str(self._camera_id): {"regions": regions}}
            }
            _apply_vision_pipeline(
                self._service, pipeline_data, router=self._ctx.router_manager
            )

    def _export_worker_pool_stats(self) -> None:
        """Экспорт статистики worker pool."""
        if self._dispatcher is None:
            return
        stats = self._dispatcher.stats
        self._ctx._process.update_process_state(custom={"worker_pool": stats})
