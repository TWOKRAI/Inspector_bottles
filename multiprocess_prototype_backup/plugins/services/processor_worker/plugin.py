"""ProcessorWorkerPlugin — воркер пула обработки изображений.

Service-плагин: получает задачи от Processor через IPC,
исполняет операцию из каталога над кадром из SHM,
возвращает результат обратно.
"""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.helpers import message_as_dict
from multiprocess_prototype.backend.processes.processor_worker.adapter import WorkerAdapter
from multiprocess_prototype.backend.processes.processor_worker.commands import build_command_table
from multiprocess_prototype.registers.processor.catalog.loader import load_catalog
from multiprocess_prototype.services.processor.operations.base import (
    ChainContext,
    ProcessingOperation,
)
from multiprocess_prototype.services.processor.operations.loader import load_operation_class


@register_plugin("processor_worker", category="service", description="Воркер пула обработки изображений")
class ProcessorWorkerPlugin(ProcessModulePlugin):
    """Воркер пула обработки изображений."""

    name = "processor_worker"
    category = "service"
    inputs = []
    outputs = []
    commands = {}  # регистрация вручную

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: каталог, кэш операций, адаптер, команды, воркер."""
        self._ctx = ctx
        cfg = ctx.config

        self._owner_process_id: str = cfg.get("process_id", "")
        self._worker_index: int = cfg.get("worker_index", 0)
        self._result_shm_slot = f"worker_{self._worker_index}_result"

        # Загрузка каталога операций
        catalog_path = cfg.get("catalog_path", "data/processing_catalog.yaml")
        resolved_catalog = str(Path(catalog_path).resolve())
        self._catalog = load_catalog(resolved_catalog)
        ctx.log_info(
            f"ProcessorWorkerPlugin[{self._worker_index}]: "
            f"каталог загружен ({len(self._catalog)} операций)"
        )

        # Кэш экземпляров операций
        self._operations: dict[str, ProcessingOperation] = {}

        # Адаптер для IPC/SHM
        self._adapter = WorkerAdapter(ctx._process, self._result_shm_slot)

        # Команды
        cmd_table = build_command_table(ctx._process)
        for cmd, handler in cmd_table.items():
            ctx.command_manager.register_command(cmd, handler)

        # Воркер-поток
        worker_cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "task_worker", self._task_worker, worker_cfg, auto_start=True
        )

        pid_info = f", process_id='{self._owner_process_id}'" if self._owner_process_id else ""
        ctx.log_info(
            f"ProcessorWorkerPlugin configured (worker_index={self._worker_index}{pid_info})"
        )

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING."""
        ctx.log_info(f"ProcessorWorkerPlugin[{self._worker_index}] ready")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED."""
        ctx.log_info(f"ProcessorWorkerPlugin[{self._worker_index}] shutting down...")
        self._operations.clear()
        if ctx.memory_manager:
            ctx.memory_manager.close_all(ctx.process_name)

    # --- Получение/создание операции из кэша ---

    def _get_operation(self, operation_ref: str) -> ProcessingOperation:
        """Получить экземпляр операции по ключу, создать при необходимости."""
        if operation_ref in self._operations:
            return self._operations[operation_ref]

        op_def = self._catalog.get(operation_ref)
        if op_def is None:
            raise KeyError(
                f"Операция '{operation_ref}' не найдена в каталоге. "
                f"Доступные: {list(self._catalog.keys())}"
            )

        op_class = load_operation_class(op_def.module_path)
        instance = op_class()
        self._operations[operation_ref] = instance

        self._ctx.log_info(f"Операция '{operation_ref}' создана ({op_def.module_path})")
        return instance

    # --- Основной воркер-цикл ---

    def _task_worker(self, stop_event, pause_event) -> None:
        """Воркер: получить задачу → прочитать frame → execute → ответить."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self._ctx.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)

            if msg_dict.get("data_type") != "worker_task_request":
                continue

            data = msg_dict.get("data", {})
            task_id = data.get("task_id", "unknown")
            correlation_id = data.get("correlation_id", "")
            source = msg_dict.get("sender", msg_dict.get("source", ""))

            self._process_task(data, task_id, correlation_id, source)

    def _process_task(
        self,
        data: dict,
        task_id: str,
        correlation_id: str,
        source: str,
    ) -> None:
        """Обработать одну задачу."""
        start_time = time.monotonic()

        try:
            result = self._execute_task(data)
            processing_time = time.monotonic() - start_time

            output_shm_name: str | None = None
            output_shm_index: int = 0
            output_frame = result.get("output_frame")
            if output_frame is not None:
                shm_result = self._adapter.write_output_frame(output_frame)
                if shm_result is not None:
                    output_shm_name, output_shm_index = shm_result

            response = {
                "task_id": task_id,
                "correlation_id": correlation_id,
                "success": True,
                "error": None,
                "output_shm_name": output_shm_name,
                "output_shm_index": output_shm_index,
                "detections": result.get("detections", []),
                "processing_time": processing_time,
            }

        except Exception as exc:
            processing_time = time.monotonic() - start_time
            error_msg = f"{type(exc).__name__}: {exc}"
            self._ctx.log_error(f"Ошибка задачи {task_id}: {error_msg}")

            response = {
                "task_id": task_id,
                "correlation_id": correlation_id,
                "success": False,
                "error": error_msg,
                "output_shm_name": None,
                "output_shm_index": 0,
                "detections": [],
                "processing_time": processing_time,
            }

        target = source or "processor"
        self._adapter.send_response(target, response)

    def _execute_task(self, data: dict) -> dict:
        """Исполнить задачу: прочитать frame, запустить операцию, собрать результаты."""
        operation_ref = data.get("operation_ref", "")
        params = data.get("params", {})

        frame = self._adapter.read_input_frame(
            shm_name=data.get("input_shm_name", ""),
            owner=data.get("input_shm_owner", ""),
            index=data.get("input_shm_index", 0),
            shape=tuple(data.get("frame_shape", [])),
        )
        if frame is None:
            raise RuntimeError(
                f"Не удалось прочитать frame из SHM "
                f"(name={data.get('input_shm_name')}, index={data.get('input_shm_index')})"
            )

        operation = self._get_operation(operation_ref)
        operation.configure(params)

        context = ChainContext(
            camera_id=data.get("camera_id", ""),
            region_id=data.get("region_id", ""),
            seq_id=data.get("seq_id", 0),
        )

        output_frame = operation.execute(frame, context)

        detections = []
        if hasattr(operation, "last_detections"):
            detections = list(operation.last_detections)

        return {
            "output_frame": output_frame,
            "detections": detections,
        }
