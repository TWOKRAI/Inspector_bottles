"""Команды и register-хендлеры для ProcessorProcess.

Фабричные функции получают зависимости как аргументы и возвращают dict.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_command_table(service) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: ProcessorService instance.
    """

    def cmd_set_color_range(data: dict) -> dict:
        return service.set_color_range(data.get("color_lower"), data.get("color_upper"))

    def cmd_set_min_area(data: dict) -> dict:
        value = service.set_min_area(data.get("min_area", service.detector.min_area))
        return {"status": "ok", "min_area": value}

    def cmd_set_max_area(data: dict) -> dict:
        value = service.set_max_area(data.get("max_area", service.detector.max_area))
        return {"status": "ok", "max_area": value}

    return {
        "set_color_range": cmd_set_color_range,
        "set_min_area": cmd_set_min_area,
        "set_max_area": cmd_set_max_area,
    }


def _has_any_nodes(pipeline_data: dict) -> bool:
    """Проверить, есть ли хотя бы один регион с непустым nodes dict.

    Используется для выбора между chain (Phase 5a) и legacy путём.
    """
    cameras = pipeline_data.get("cameras")
    if not isinstance(cameras, dict):
        return False
    for cam_data in cameras.values():
        if not isinstance(cam_data, dict):
            continue
        regions = cam_data.get("regions")
        if not isinstance(regions, dict):
            continue
        for region_data in regions.values():
            if not isinstance(region_data, dict):
                continue
            nodes = region_data.get("nodes")
            if isinstance(nodes, dict) and nodes:
                return True
    return False


def _apply_vision_pipeline(service, value: object, router=None) -> None:
    """Применить vision_pipeline dict к ProcessorService.

    Phase 5a: если хотя бы один регион содержит непустой nodes —
    вызываем service.rebuild_runnables() (per-region chain).
    Иначе — legacy поведение: извлекаем параметры из первого processing_block.

    Args:
        service: ProcessorService instance.
        value: pipeline dict.
        router: IRouterManager для Phase 9 router-топологии (None = без topology).
    """
    if not isinstance(value, dict):
        logger.warning("vision_pipeline: ожидался dict, получен %s", type(value).__name__)
        return

    # Phase 5a: новый формат с nodes → per-region chain runnables
    if _has_any_nodes(value):
        logger.info("vision_pipeline: обнаружены nodes — переход на chain runnables")
        service.rebuild_runnables(value, router=router)
        return

    # Legacy путь: единый детектор, параметры из первого processing_block
    cameras = value.get("cameras")
    if not isinstance(cameras, dict):
        logger.debug("vision_pipeline: пустой или невалидный cameras")
        return

    total_cameras = len(cameras)
    total_regions = 0

    for cam_id, cam_data in cameras.items():
        if not isinstance(cam_data, dict):
            continue
        regions = cam_data.get("regions")
        if not isinstance(regions, dict):
            continue
        total_regions += len(regions)

        for region_id, region_data in regions.items():
            if not isinstance(region_data, dict):
                continue
            blocks = region_data.get("processing_blocks")
            if not isinstance(blocks, dict):
                continue

            for block_id, block_data in blocks.items():
                if not isinstance(block_data, dict):
                    continue
                params = block_data.get("params")
                if not isinstance(params, dict):
                    continue

                # Извлекаем параметры детекции из блока
                color_lower = params.get("color_lower")
                color_upper = params.get("color_upper")
                min_area = params.get("min_area")
                max_area = params.get("max_area")

                if color_lower is not None or color_upper is not None:
                    service.set_color_range(lower=color_lower, upper=color_upper)
                if min_area is not None:
                    service.set_min_area(int(min_area))
                if max_area is not None:
                    service.set_max_area(int(max_area))

                logger.info(
                    "vision_pipeline: применены параметры из cam=%s region=%s block=%s",
                    cam_id,
                    region_id,
                    block_id,
                )
                # Phase 4 MVP: берём параметры из первого найденного блока
                break
            else:
                continue
            break
        else:
            continue
        break

    logger.info("vision_pipeline: %d камер, %d регионов", total_cameras, total_regions)


def build_state_config_handlers(service, router=None) -> dict:
    """Маппинг config field suffix → handler для StateProxy callback.

    Ключи = суффиксы после processor.{id}.config.
    Используется в ProcessorProcess._on_config_changed для роутинга дельт.

    Args:
        service: ProcessorService instance.
        router: IRouterManager для Phase 9 router-топологии (None = без topology).
    """
    return {
        "color_lower": lambda v: service.set_color_range(lower=v),
        "color_upper": lambda v: service.set_color_range(upper=v),
        "min_area": lambda v: service.set_min_area(v),
        "max_area": lambda v: service.set_max_area(v),
        "vision_pipeline": lambda v: _apply_vision_pipeline(service, v, router=router),
        "workers_per_processor": lambda v: service.resize_pool(int(v)),
    }


