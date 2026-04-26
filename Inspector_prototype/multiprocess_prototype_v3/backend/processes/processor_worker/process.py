"""ProcessorWorkerProcess — воркер пула обработки изображений.

Отдельный процесс, получающий задачи от Processor через IPC,
исполняющий операцию из каталога над кадром из SHM,
и возвращающий результат обратно.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

from multiprocess_prototype_v3.backend.helpers import message_as_dict
from multiprocess_prototype_v3.registers.processor.catalog.loader import load_catalog
from multiprocess_prototype_v3.services.processor.operations.base import (
    ChainContext,
    ProcessingOperation,
)
from multiprocess_prototype_v3.services.processor.operations.loader import load_operation_class

from .adapter import WorkerAdapter
from .commands import build_command_table

logger = logging.getLogger(__name__)


class ProcessorWorkerProcess(ProcessModule):
    """Процесс-воркер пула обработки. Инфраструктура: IPC, SHM, кэш операций."""

    def _init_application_threads(self) -> None:
        self._log_info("ProcessorWorkerProcess initializing...")
        app_cfg = self.get_config("config") or {}

        # Идентификатор процесса из topology (Task 9.6).
        # Используется для определения «сферы ответственности» воркера.
        # TODO: фильтрация задач по process_id когда topology поддержит
        #       прямую маршрутизацию задач к воркерам (Task 9.7+).
        self._owner_process_id: str = app_cfg.get("process_id", "")

        # Индекс воркера — определяет имя SHM-слота результата
        self._worker_index: int = app_cfg.get("worker_index", 0)
        self._result_shm_slot = f"worker_{self._worker_index}_result"

        # Загрузка каталога операций обработки
        catalog_path = app_cfg.get("catalog_path", "data/processing_catalog.yaml")
        resolved_catalog = str(Path(catalog_path).resolve())
        self._catalog = load_catalog(resolved_catalog)
        self._log_info(
            f"Каталог загружен: {len(self._catalog)} операций из {resolved_catalog}"
        )

        # Кэш экземпляров операций: operation_ref → ProcessingOperation
        self._operations: dict[str, ProcessingOperation] = {}

        # Адаптер для IPC/SHM
        self._adapter = WorkerAdapter(self, self._result_shm_slot)

        # Команды
        cmd_table = build_command_table(self)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # Воркер-поток для обработки входящих задач
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "task_worker", self._task_worker, cfg, auto_start=True
        )
        pid_info = f", process_id='{self._owner_process_id}'" if self._owner_process_id else ""
        self._log_info(
            f"ProcessorWorkerProcess ready (worker_index={self._worker_index}{pid_info})"
        )

    # --- Получение/создание операции из кэша ---

    def _get_operation(self, operation_ref: str) -> ProcessingOperation:
        """Получить экземпляр операции по ключу, создать при необходимости.

        Raises:
            KeyError: operation_ref не найден в каталоге.
            ImportError: класс операции не удалось загрузить.
        """
        if operation_ref in self._operations:
            return self._operations[operation_ref]

        # Ищем определение в каталоге
        op_def = self._catalog.get(operation_ref)
        if op_def is None:
            raise KeyError(
                f"Операция '{operation_ref}' не найдена в каталоге. "
                f"Доступные: {list(self._catalog.keys())}"
            )

        # Загрузить класс и создать экземпляр
        op_class = load_operation_class(op_def.module_path)
        instance = op_class()
        self._operations[operation_ref] = instance

        self._log_info(f"Операция '{operation_ref}' создана ({op_def.module_path})")
        return instance

    def reload_catalog(self) -> dict:
        """Перезагрузить каталог операций. Сбрасывает кэш экземпляров."""
        app_cfg = self.get_config("config") or {}
        catalog_path = app_cfg.get("catalog_path", "data/processing_catalog.yaml")
        resolved_catalog = str(Path(catalog_path).resolve())

        self._catalog = load_catalog(resolved_catalog)
        self._operations.clear()

        msg = f"Каталог перезагружен: {len(self._catalog)} операций"
        self._log_info(msg)
        return {"status": "ok", "operations_count": len(self._catalog)}

    # --- Основной воркер-цикл ---

    def _task_worker(self, stop_event, pause_event) -> None:
        """Воркер: получить задачу → прочитать frame из SHM → execute → записать результат → ответить."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Получение сообщения
            msg = self.receive_message(timeout=0.1, channel_types=["data"])
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
        """Обработать одну задачу. Отправляет response в любом случае."""
        start_time = time.monotonic()

        try:
            result = self._execute_task(data)
            processing_time = time.monotonic() - start_time

            # Записать output frame в SHM
            output_shm_name: str | None = None
            output_shm_index: int = 0

            output_frame = result.get("output_frame")
            if output_frame is not None:
                shm_result = self._adapter.write_output_frame(output_frame)
                if shm_result is not None:
                    output_shm_name, output_shm_index = shm_result

            # Собрать response
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
            self._log_error(f"Ошибка обработки задачи {task_id}: {error_msg}")

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

        # Отправить response обратно source-процессу
        target = source or "processor"
        self._adapter.send_response(target, response)

    def _execute_task(self, data: dict) -> dict:
        """Исполнить задачу: прочитать frame, запустить операцию, собрать результаты.

        Returns:
            dict с ключами output_frame (np.ndarray | None) и detections (list).

        Raises:
            KeyError: operation_ref не найден.
            ImportError: класс операции не загружается.
            Exception: ошибка в execute операции.
        """
        operation_ref = data.get("operation_ref", "")
        params = data.get("params", {})

        # Чтение frame из SHM
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

        # Получить/создать операцию
        operation = self._get_operation(operation_ref)

        # Настроить и выполнить
        operation.configure(params)

        context = ChainContext(
            camera_id=data.get("camera_id", ""),
            region_id=data.get("region_id", ""),
            seq_id=data.get("seq_id", 0),
        )

        output_frame = operation.execute(frame, context)

        # Собрать side results через duck-typing
        detections = []
        if hasattr(operation, "last_detections"):
            detections = list(operation.last_detections)

        return {
            "output_frame": output_frame,
            "detections": detections,
        }

    # --- Shutdown ---

    def shutdown(self) -> bool:
        self._log_info("ProcessorWorkerProcess shutting down...")
        # Очистка кэша операций
        self._operations.clear()
        # Cleanup SHM
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
