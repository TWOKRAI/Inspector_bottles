"""ProcessorProcess — инфраструктурный контейнер для ProcessorService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
"""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.services.processor.chain.thread_pool import ChainThreadPool
from multiprocess_prototype.services.processor.detection import ColorBlobDetector
from multiprocess_prototype.services.processor.service import ProcessorService
from multiprocess_prototype.services.processor.worker_pool.dispatcher import WorkerPoolDispatcher

from .adapter import ProcessorAdapter
from .commands import (
    build_command_table,
    build_state_config_handlers,
    _apply_vision_pipeline,
)


class ProcessorProcess(ProcessModule):
    """Процесс обработки кадров. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("ProcessorProcess initializing...")
        app_cfg = self.get_config("config") or {}

        # camera_id из конфига — определяет привязку к камере
        camera_id = app_cfg.get("camera_id", 0)
        self._camera_id = camera_id

        # SHM middleware: приём кадров от конкретной камеры (camera_{id}/camera_{id}_frame)
        self._recv_frame_mw = FrameShmMiddleware(
            self.memory_manager,
            owner=f"camera_{camera_id}",
            slot=f"camera_{camera_id}_frame",
        )
        self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        # SHM middleware: отправка масок (processor_{id}/processor_{id}_mask)
        self._send_mask_mw = FrameShmMiddleware(
            self.memory_manager,
            owner=self.name,
            slot=f"processor_{camera_id}_mask",
        )
        self.router_manager.add_send_middleware(self._send_mask_mw.on_send)

        # Создаём адаптер (реализация порта), привязанный к camera_id
        adapter = ProcessorAdapter(self, camera_id=camera_id)

        # Создаём детектор (бизнес-зависимость)
        detector = ColorBlobDetector(
            app_cfg.get("color_lower", [0, 0, 150]),
            app_cfg.get("color_upper", [100, 100, 255]),
            app_cfg.get("min_area", 500),
            app_cfg.get("max_area", 50000),
        )

        # Phase 5b: создаём пул потоков для параллельного исполнения шагов chain
        workers_per_processor: int = app_cfg.get("workers_per_processor", 2)
        step_timeout: float = float(app_cfg.get("step_timeout", 10.0))
        # workers_per_processor <= 1 → линейный режим, пул не создаётся
        if workers_per_processor > 1:
            pool: ChainThreadPool | None = ChainThreadPool(
                max_workers=workers_per_processor,
                step_timeout=step_timeout,
            )
        else:
            pool = None
        self._pool = pool

        # Phase 5c: создаём dispatcher для worker pool (если worker_pool_size > 0)
        worker_pool_size: int = app_cfg.get("worker_pool_size", 0)
        if worker_pool_size > 0:
            dispatcher: WorkerPoolDispatcher | None = WorkerPoolDispatcher(
                send_fn=lambda target, data, data_type: adapter._io.send_data(
                    target, data_type, data
                ),
                worker_count=worker_pool_size,
                timeout=float(app_cfg.get("worker_timeout", 5.0)),
                input_queue_size=int(app_cfg.get("worker_queue_size", 4)),
            )
            self._log_info(
                "WorkerPoolDispatcher создан: %d workers, timeout=%.1fs",
                worker_pool_size,
                float(app_cfg.get("worker_timeout", 5.0)),
            )
        else:
            dispatcher = None
        self._dispatcher = dispatcher

        # Создаём сервис с инжектированным портом
        self._service = ProcessorService(
            output=adapter,
            detector=detector,
            target_width=app_cfg.get("resolution_width", 640),
            target_height=app_cfg.get("resolution_height", 480),
            pool=pool,
            dispatcher=dispatcher,
        )

        # Phase 5a: загрузка каталога операций обработки
        catalog_path = app_cfg.get("catalog_path", "data/processing_catalog.yaml")
        resolved_catalog = str(Path(catalog_path).resolve())
        self._service.set_catalog(resolved_catalog)

        # Команды из таблицы
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # StateProxy для чтения config / записи state
        from state_store.proxy.state_proxy import StateProxy

        self._state_proxy = StateProxy(f"processor_{self._camera_id}", router=self.router_manager)

        # Регистрация обработчика state.changed
        self.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        # Config handlers для StateProxy callback
        # Phase 9 / Task 9.5: передаём router для пересчёта router-топологии
        self._state_config_handlers = build_state_config_handlers(
            self._service, router=self.router_manager,
        )

        # Подписка на processor config (simple fields: color_lower, min_area, etc.)
        self._state_proxy.subscribe(
            f"processor.{self._camera_id}.config.*",
            callback=self._on_config_changed,
            exclude_self=True,
        )

        # Подписка на regions (deep changes → rebuild_runnables)
        self._state_proxy.subscribe(
            f"cameras.{self._camera_id}.regions.**",
            callback=self._on_regions_changed,
            exclude_self=True,
        )

        # Начальная запись state
        self._state_proxy.set(f"processor.{self._camera_id}.state.status", "initialized")

        # Воркер
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "processing_worker", self._processing_worker, cfg, auto_start=True
        )
        self._log_info("ProcessorProcess ready")

    # --- Воркер обработки ---

    def _processing_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → middleware frame → service.process_frame() (config через StateProxy)."""
        # Phase 5c: счётчик кадров для периодического экспорта stats
        frames_processed = 0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Инфраструктура: получение сообщения (receive middleware уже читает frame из SHM)
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
                    # Закрыть старый SHM handle и переоткрыть с новым shape
                    camera_id = change_data.get("camera_id", 0)
                    owner = f"camera_{camera_id}"
                    if self.memory_manager:
                        self.memory_manager.close_all(owner)
                    # Обновить receive middleware shape (будет использовать новый handle)
                    self._recv_frame_mw = FrameShmMiddleware(
                        self.memory_manager, owner=owner, slot=region_name
                    )
                    # Обновить target_width/height в сервисе
                    self._service._target_width = new_w
                    self._service._target_height = new_h
                    self._log_info(
                        "ProcessorProcess: SHM region %s resized to %dx%d",
                        region_name,
                        new_w,
                        new_h,
                    )
                continue

            # Phase 5c: ответ от worker-процесса → dispatcher
            if msg_dict.get("data_type") == "worker_task_response":
                if self._dispatcher is not None:
                    self._dispatcher.handle_response(msg_dict.get("data") or {})
                continue

            # Проверка типа сообщения
            if msg_dict.get("data_type") != "frame_ready":
                continue

            # Кадр уже прочитан из SHM receive middleware (FrameShmMiddleware.on_receive)
            frame = msg_dict.get("frame")
            if frame is None:
                continue

            data = msg_dict.get("data", {})

            # Делегация бизнес-логики в сервис
            self._service.process_frame(frame, data)

            # Запись метрик в StateStore (ThrottleMiddleware ограничит частоту)
            if hasattr(self, "_state_proxy"):
                self._state_proxy.set(
                    f"processor.{self._camera_id}.state.is_processing", True
                )

            # Phase 5c: периодический экспорт worker pool stats
            frames_processed += 1
            if self._dispatcher is not None and frames_processed % 100 == 0:
                self._export_worker_pool_stats()

    # --- StateProxy callbacks ---

    def _on_config_changed(self, deltas: list) -> None:
        """Config fields (color_lower, min_area, etc.) → dispatch to handler.

        Принимает список Delta от StateProxy (подписка processor.{id}.config.*).
        Суффикс пути после processor.{id}.config. используется как ключ маппинга.
        """
        prefix = f"processor.{self._camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = self._state_config_handlers.get(field)
            if handler:
                handler(delta.new_value)

    def _on_regions_changed(self, deltas: list) -> None:
        """Regions tree changed → ONE rebuild_runnables().

        Transaction batching: все дельты в одном callback = одна транзакция.
        Не делаем rebuild для каждой дельты — читаем всё поддерево и rebuild один раз.

        Phase 9 / Task 9.5: передаём router_manager для пересчёта router-топологии.
        """
        if not deltas:
            return
        regions = self._state_proxy.get_subtree(f"cameras.{self._camera_id}.regions")
        if regions is not None:
            # Оборачиваем в формат vision_pipeline для совместимости с rebuild_runnables
            pipeline_data = {"cameras": {str(self._camera_id): {"regions": regions}}}
            _apply_vision_pipeline(self._service, pipeline_data, router=self.router_manager)

    # --- Phase 5c: worker pool stats ---

    def _export_worker_pool_stats(self) -> None:
        """Экспортировать статистику worker pool через update_process_state."""
        if self._dispatcher is None:
            return
        stats = self._dispatcher.stats
        self.update_process_state(custom={"worker_pool": stats})
        if stats.get("drops_total", 0) > 0:
            self._log_warning(
                "Worker pool stats: dispatched=%d, drops=%d, pending=%d, timeouts=%d",
                stats.get("dispatched_total", 0),
                stats.get("drops_total", 0),
                stats.get("pending", 0),
                stats.get("timeout_total", 0),
            )

    # --- Shutdown ---

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        # StateProxy: записать статус и отписаться
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set(f"processor.{self._camera_id}.state.status", "shutdown")
            self._state_proxy.shutdown()
        # Phase 5b: graceful shutdown пула потоков перед остановкой процесса
        if self._pool is not None:
            self._pool.shutdown(wait=True)
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
