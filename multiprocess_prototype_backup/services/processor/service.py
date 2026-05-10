"""ProcessorService — бизнес-логика обраб��тки кадров."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Optional

try:
    import cv2
except ImportError:
    cv2 = None

if TYPE_CHECKING:
    import numpy as np
    from multiprocess_framework.modules.router_module.interfaces import IRouterManager
    from multiprocess_prototype.services.processor.ports import ProcessorOutputPort
    from multiprocess_prototype.services.processor.topology.builder import RouterTopology

from multiprocess_prototype.services.processor.detection import ColorBlobDetector
from multiprocess_prototype.services.database.schema import DetectionSchema
from multiprocess_prototype.services.processor.chain import (
    ChainResult,
    ChainRunnable,
    GraphRunnableBuilder,
    autofill_inputs,
)
from multiprocess_prototype.services.processor.chain.thread_pool import ChainThreadPool
from multiprocess_prototype.services.processor.worker_pool.dispatcher import WorkerPoolDispatcher
from multiprocess_prototype.registers.processor.catalog import (
    ProcessingOperationDef,
    load_catalog,
)
from multiprocess_prototype.registers.pipeline.processing_node import ProcessingNode

logger = logging.getLogger(__name__)


class ProcessorService:
    """Сервис обработки кадров. Чистая бизнес-логика без привязки к фреймворку."""

    def __init__(
        self,
        output: ProcessorOutputPort,
        detector: ColorBlobDetector,
        target_width: int = 640,
        target_height: int = 480,
        pool: ChainThreadPool | None = None,
        dispatcher: WorkerPoolDispatcher | None = None,
    ) -> None:
        self._out = output
        self._detector = detector
        self._target_width = target_width
        self._target_height = target_height

        # Phase 5b: пул потоков для параллельного исполнения шагов (None = линейный режим)
        self._pool = pool

        # Phase 5c: диспетчер worker pool для cross-process шагов (None = без worker pool)
        self._dispatcher = dispatcher

        # Phase 5a: per-region chain runnables
        self._catalog: dict[str, ProcessingOperationDef] = {}
        self._runnables: dict[str, ChainRunnable] = {}
        self._catalog_path: str | None = None

        # Phase 9 / Task 9.5: последняя применённая router-топология (для diff)
        self._last_topology: RouterTopology | None = None

    @property
    def detector(self) -> ColorBlobDetector:
        return self._detector

    @property
    def target_width(self) -> int:
        return self._target_width

    @property
    def target_height(self) -> int:
        return self._target_height

    # --- Phase 5a: каталог и per-region chain runnables ---

    def set_catalog(self, catalog_path: str) -> None:
        """Загрузить каталог операций из YAML-файла.

        Каталог необходим для построения chain runnables из nodes.
        Если файл не найден — каталог остаётся пустым (предупреждение в логе).
        """
        self._catalog_path = catalog_path
        self._catalog = load_catalog(catalog_path)
        logger.info(
            "Каталог операций загружен: %d операций из %s",
            len(self._catalog),
            catalog_path,
        )

    def rebuild_runnables(
        self,
        pipeline_data: dict,
        router: IRouterManager | None = None,
    ) -> None:
        """Построить per-region ChainRunnable из pipeline dict (cameras → regions → nodes).

        Для каждого региона: если есть непустой nodes → строим chain через GraphRunnableBuilder.
        Если nodes нет или пуст, но есть processing_blocks → регион остаётся на legacy пути.

        Если router передан — пересчитываем topology через to_router_topology(pipeline)
        и вызываем apply_topology(router, topology, previous=self._last_topology).
        Сохраняем self._last_topology для следующего diff.

        Атомарный swap: собираем новый dict целиком, затем присваиваем одним statement.
        """
        if not isinstance(pipeline_data, dict):
            logger.warning("rebuild_runnables: ожидался dict, получен %s", type(pipeline_data).__name__)
            return

        cameras = pipeline_data.get("cameras")
        if not isinstance(cameras, dict):
            logger.debug("rebuild_runnables: пустой или невалидный cameras")
            return

        new_runnables: dict[str, ChainRunnable] = {}

        for cam_id, cam_data in cameras.items():
            if not isinstance(cam_data, dict):
                continue
            regions = cam_data.get("regions")
            if not isinstance(regions, dict):
                continue

            for region_id, region_data in regions.items():
                if not isinstance(region_data, dict):
                    continue

                raw_nodes = region_data.get("nodes")
                if not isinstance(raw_nodes, dict) or not raw_nodes:
                    # Нет nodes — этот регион остаётся на legacy пути
                    continue

                # Десериализация нод из dict
                nodes: dict[str, ProcessingNode] = {}
                for node_id, node_data in raw_nodes.items():
                    if isinstance(node_data, dict):
                        node = ProcessingNode.model_validate({**node_data, "node_id": node_id})
                        nodes[node_id] = node
                    elif isinstance(node_data, ProcessingNode):
                        nodes[node_id] = node_data

                if not nodes:
                    continue

                # Автозаполнение inputs для линейной цепочки
                nodes = autofill_inputs(nodes)

                try:
                    # Phase 5b/5c: передаём pool и dispatcher — builder выбирает режим автоматически
                    runnable = GraphRunnableBuilder.build(
                        nodes, self._catalog, pool=self._pool, dispatcher=self._dispatcher,
                    )
                    # Ключ — составной: cam_id/region_id для уникальности
                    composite_key = f"{cam_id}/{region_id}"
                    new_runnables[composite_key] = runnable
                    logger.info(
                        "Chain построен: cam=%s region=%s, %d шагов",
                        cam_id,
                        region_id,
                        len(runnable.steps),
                    )
                except (KeyError, ValueError) as exc:
                    logger.error(
                        "Ошибка построения chain для cam=%s region=%s: %s",
                        cam_id,
                        region_id,
                        exc,
                    )

        # Атомарный swap — один assignment
        self._runnables = new_runnables
        logger.info("Runnables обновлены: %d регионов с chain", len(new_runnables))

        # Phase 9 / Task 9.5: пересчёт и применение router-топологии
        if router is not None and self._catalog:
            self._apply_router_topology(pipeline_data, router)

    def _apply_router_topology(self, pipeline_data: dict, router: IRouterManager) -> None:
        """Пересчитать router-топологию и применить diff к router.

        Вызывается из rebuild_runnables() при наличии router.
        Внутренний метод — не вызывайте напрямую.
        """
        from multiprocess_prototype.registers.pipeline.schemas import Pipeline
        from multiprocess_prototype.services.processor.topology.builder import to_router_topology
        from multiprocess_prototype.services.processor.topology.registrar import apply_topology

        try:
            pipeline = Pipeline.model_validate(pipeline_data)
            topology = to_router_topology(pipeline, self._catalog)
            result = apply_topology(
                router,
                topology,
                previous=self._last_topology,
            )
            self._last_topology = topology
            logger.info(
                "Router-топология применена: channels +%d/-%d, routes +%d, broadcasts +%d",
                result.channels_added,
                result.channels_removed,
                result.routes_added,
                result.broadcast_routes_added,
            )
        except Exception as exc:
            logger.error("Ошибка применения router-топологии: %s", exc, exc_info=True)

    def resize_pool(self, max_workers: int) -> None:
        """Изменить размер пула потоков на лету.

        Если пул не создан (workers_per_processor=1 или не задан) — вызов игнорируется.
        После resize нужно вызвать rebuild_runnables(), чтобы применить новый режим.
        """
        if self._pool is not None:
            self._pool.resize(max_workers)
            logger.info("Пул потоков изменён: %d workers", max_workers)

    def process_frame_chain(
        self, frame: np.ndarray, metadata: dict[str, Any], region_id: str
    ) -> ChainResult | None:
        """Обработать кадр через chain для конкретного региона.

        Если runnable для region_id отсутствует — возвращает None.
        """
        runnable = self._runnables.get(region_id)
        if runnable is None:
            return None

        return runnable.execute(frame, {
            "camera_id": metadata.get("camera_id", ""),
            "region_id": region_id,
            "seq_id": metadata.get("frame_id", 0),
        })

    # --- Обработка кадра ---

    def process_frame(self, frame: np.ndarray, metadata: dict[str, Any]) -> None:
        """Обработать кадр: детекция → маска → отправка результатов через порт.

        Если есть per-region runnables — используется chain путь.
        Иначе — legacy детектор (backward compat).
        """
        # Resize при необходимости
        if (
            frame.shape[0] != self._target_height or frame.shape[1] != self._target_width
        ) and cv2 is not None:
            frame = cv2.resize(
                frame,
                (self._target_width, self._target_height),
                interpolation=cv2.INTER_LINEAR,
            )
            metadata = dict(metadata)
            metadata["width"] = self._target_width
            metadata["height"] = self._target_height

        # Новый путь: per-region chain (Phase 5a)
        if self._runnables:
            self._process_frame_via_chain(frame, metadata)
            return

        # Legacy путь: единый detector (backward compat)
        self._process_frame_legacy(frame, metadata)

    def _process_frame_via_chain(self, frame: np.ndarray, metadata: dict[str, Any]) -> None:
        """Обработать кадр через per-region chain runnables."""
        for region_id, runnable in self._runnables.items():
            processor_start_ts = time.time()
            chain_result = runnable.execute(frame, {
                "camera_id": metadata.get("camera_id", ""),
                "region_id": region_id,
                "seq_id": metadata.get("frame_id", 0),
            })
            processor_end_ts = time.time()

            if chain_result.failed:
                logger.warning(
                    "Chain для region=%s завершился с ошибкой (level=%s)",
                    region_id,
                    chain_result.fail_level,
                )
                continue

            # Записать маску в SHM если есть
            mask_shm_name: str | None = None
            mask_shm_index: int = -1
            if chain_result.masks:
                mask_shm_name, mask_shm_index = self._out.write_mask_to_shm(
                    chain_result.masks[0]
                )

            # Построить и отправить результат рендереру
            result_data = self._build_detection_result(
                metadata,
                chain_result.detections,
                chain_result.contours,
                chain_result.processing_time,
                mask_shm_name,
                mask_shm_index,
                processor_start_ts=processor_start_ts,
                processor_end_ts=processor_end_ts,
            )
            self._out.send_detection_to_renderer(result_data)

            # Отправить детекции в БД
            if chain_result.detections:
                rows = self._build_detection_rows(chain_result.detections, metadata)
                self._out.send_detections_to_database(rows)

            # Feedback камере
            self._out.send_feedback_to_camera(
                metadata.get("frame_id", 0), chain_result.processing_time
            )

    def _process_frame_legacy(self, frame: np.ndarray, metadata: dict[str, Any]) -> None:
        """Legacy путь обработки: единый детектор (backward compat)."""
        processor_start_ts = time.time()
        detections, mask, contours = self._detector.detect(frame)
        processor_end_ts = time.time()
        processing_time = processor_end_ts - processor_start_ts

        # Записать маску в SHM через порт
        mask_shm_name, mask_shm_index = self._out.write_mask_to_shm(mask)

        # Построить и отправить результат рендереру
        result_data = self._build_detection_result(
            metadata,
            detections,
            contours,
            processing_time,
            mask_shm_name,
            mask_shm_index,
            processor_start_ts=processor_start_ts,
            processor_end_ts=processor_end_ts,
        )
        self._out.send_detection_to_renderer(result_data)

        # Отправить детекции в БД
        if detections:
            rows = self._build_detection_rows(detections, metadata)
            self._out.send_detections_to_database(rows)

        # Feedback камере
        self._out.send_feedback_to_camera(metadata.get("frame_id", 0), processing_time)

    def _build_detection_result(
        self,
        metadata: dict,
        detections: list,
        contours: list,
        processing_time: float,
        mask_shm_name: Optional[str],
        mask_shm_index: int,
        processor_start_ts: float = 0.0,
        processor_end_ts: float = 0.0,
    ) -> dict:
        """Построить словарь результата детекции."""
        result = {
            "frame_id": metadata.get("frame_id", 0),
            "shm_name": "camera_frame",
            "shm_index": metadata.get("shm_index", 0),
            "shm_actual_name": metadata.get("shm_actual_name"),
            "detections": detections,
            "processing_time": processing_time,
            "timestamp": metadata.get("timestamp", 0),
            "width": metadata.get("width", 640),
            "height": metadata.get("height", 480),
            "contours": contours,
            # Timestamps для e2e latency (прокидываем из metadata)
            "capture_ts": metadata.get("capture_ts", 0.0),
            "processor_start_ts": processor_start_ts,
            "processor_end_ts": processor_end_ts,
        }
        if mask_shm_name:
            result["mask_shm_name"] = "processor_mask"
            result["mask_shm_index"] = mask_shm_index
            result["mask_shm_actual_name"] = mask_shm_name
        return result

    def _build_detection_rows(self, detections: list[dict], metadata: dict) -> list[dict]:
        """Построить строки DetectionSchema для записи в БД."""
        timestamp = metadata.get("timestamp", time.time())
        frame_id = metadata.get("frame_id", 0)
        rows = []
        for d in detections:
            row = DetectionSchema(
                timestamp=timestamp,
                frame_name=f"frame_{frame_id}",
                frame_id=frame_id,
                x1=d["bbox"][0],
                y1=d["bbox"][1],
                x2=d["bbox"][2],
                y2=d["bbox"][3],
                center_x=d["center"][0],
                center_y=d["center"][1],
                area=d["area"],
            ).model_dump(exclude_none=True, exclude={"id"})
            rows.append(row)
        return rows

    def set_color_range(self, lower: Optional[list] = None, upper: Optional[list] = None) -> dict:
        """Установить цветовой диапазон детекции."""
        self._detector.apply_color_range(lower, upper)
        return {"status": "ok"}

    def set_min_area(self, value: int) -> int:
        """Установить минимальную площадь. Возвращает фактическое значение."""
        self._detector.set_min_area(value)
        return self._detector.min_area

    def set_max_area(self, value: int) -> int:
        """Установить максимальную площадь. Возвращает фактическое значение."""
        self._detector.set_max_area(value)
        return self._detector.max_area
