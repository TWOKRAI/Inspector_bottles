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


def _apply_vision_pipeline(service, value: object) -> None:
    """Применить vision_pipeline dict к ProcessorService.

    Извлекает параметры детекции из первого найденного блока обработки
    любого региона любой камеры. Phase 4 MVP — единый детектор,
    per-region processing в Phase 5.
    """
    if not isinstance(value, dict):
        logger.warning("vision_pipeline: ожидался dict, получен %s", type(value).__name__)
        return

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


def build_register_handlers(service) -> dict:
    """Возвращает {field_name: handler} для apply_register_update().

    Args:
        service: ProcessorService instance.
    """
    return {
        "color_lower": lambda v: service.set_color_range(lower=v),
        "color_upper": lambda v: service.set_color_range(upper=v),
        "min_area": lambda v: service.set_min_area(v),
        "max_area": lambda v: service.set_max_area(v),
        "vision_pipeline": lambda v: _apply_vision_pipeline(service, v),
    }
