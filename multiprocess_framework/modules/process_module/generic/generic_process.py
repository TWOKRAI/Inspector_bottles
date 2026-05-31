"""GenericProcess — backward-compat shim + data pipeline.

DEPRECATED: Используйте ProcessModule напрямую с config.plugins.
ProcessModule теперь нативно поддерживает плагины через PluginOrchestrator.

GenericProcess добавляет только app-specific data pipeline
(DataReceiver, PipelineExecutor, SourceProducer) — это не часть
фреймворка, а логика Inspector vision приложения.
"""

from __future__ import annotations

import queue

from ..core.process_module import ProcessModule
from .data_receiver import DataReceiver
from .frame_shm_middleware import FrameShmMiddleware
from .inspector_manager import InspectorManager
from .pipeline_executor import PipelineExecutor
from .source_producer import SourceProducer


class GenericProcess(ProcessModule):
    """DEPRECATED: ProcessModule теперь поддерживает плагины нативно.

    GenericProcess = ProcessModule + data pipeline (app-specific).
    Plugin lifecycle (load → configure → start → shutdown) полностью
    обрабатывается ProcessModule через PluginOrchestrator.
    """

    def _init_application_threads(self) -> None:
        """super() делает plugin boot, здесь только data pipeline."""
        super()._init_application_threads()

        # Data pipeline — только если orchestrator загрузил плагины
        if self._orchestrator is not None:
            self._init_data_pipeline()

    # --- Data Pipeline (Phase 5) — остаётся без изменений ---

    def _init_data_pipeline(self) -> None:
        """Bootstrap data pipeline: DataReceiver, PipelineExecutor, SourceProducer."""
        app_cfg = self.get_config("config") or {}

        # Pipeline config
        chain_targets = app_cfg.get("chain_targets", [])
        queue_size = app_cfg.get("queue_size", 64)
        lag_threshold = app_cfg.get("lag_alert_threshold_sec", 2.0)
        source_fps = app_cfg.get("source_target_fps", 25.0)
        max_fails = app_cfg.get("error_max_consecutive_fails", 5)
        auto_reset = app_cfg.get("error_auto_reset_sec", 60.0)
        critical = app_cfg.get("error_critical_plugins", [])

        # Плагины через orchestrator
        all_plugins = self._orchestrator.plugins

        # Разделить плагины на source и processing
        source_plugins = [p for p in all_plugins if p.is_source]
        processing_plugins = [p for p in all_plugins if not p.is_source]

        # Если нет ни source, ни processing — pipeline не нужен
        if not source_plugins and not processing_plugins:
            return

        # FrameShmMiddleware (если есть memory_manager)
        shm_middleware = None
        if self.memory_manager:
            shm_middleware = FrameShmMiddleware(
                memory_manager=self.memory_manager,
                owner=self.name,
                slot="output_frames",
                log_error=self._log_error,
            )

        # chain_queue: DataReceiver -> PipelineExecutor
        self._chain_queue: queue.Queue = queue.Queue(maxsize=queue_size)

        # --- DataReceiver (если есть processing плагины) ---
        if processing_plugins:
            inspector = InspectorManager(
                timeout_sec=0.5,
                log_info=self._log_info,
                log_error=self._log_error,
                log_debug=self._log_debug,
            )
            self._data_receiver = DataReceiver(
                receive_fn=self.receive_message,
                shm_middleware=shm_middleware,
                inspector_manager=inspector,
                chain_queue=self._chain_queue,
                lag_alert_threshold_sec=lag_threshold,
                log_info=self._log_info,
                log_error=self._log_error,
            )
            # Подключить callback
            inspector._on_ready = self._data_receiver.on_items_ready

            # PipelineExecutor
            self._pipeline_executor = PipelineExecutor(
                plugins=processing_plugins,
                chain_targets=chain_targets,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                max_consecutive_fails=max_fails,
                auto_reset_sec=auto_reset,
                critical_plugins=critical,
                log_info=self._log_info,
                log_error=self._log_error,
            )

            # Запуск workers через WorkerManager
            if self.worker_manager:
                self.worker_manager.create_worker(
                    worker_name="data_receiver",
                    target=self._data_receiver.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self.worker_manager.create_worker(
                    worker_name="pipeline_executor",
                    target=lambda stop, pause: self._pipeline_executor.run_loop(self._chain_queue, stop, pause),
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(
                    f"GenericProcess[{self.name}]: data pipeline started ({len(processing_plugins)} processing plugins)"
                )

        # --- SourceProducer (для каждого source-плагина) ---
        self._source_producers: list[SourceProducer] = []
        for i, source_plugin in enumerate(source_plugins):
            producer = SourceProducer(
                plugin=source_plugin,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                chain_targets=chain_targets,
                target_fps=source_fps,
                log_info=self._log_info,
                log_error=self._log_error,
            )
            self._source_producers.append(producer)

            if self.worker_manager:
                worker_name = f"source_producer_{source_plugin.name}"
                self.worker_manager.create_worker(
                    worker_name=worker_name,
                    target=producer.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(f"GenericProcess[{self.name}]: source '{source_plugin.name}' producer started")
