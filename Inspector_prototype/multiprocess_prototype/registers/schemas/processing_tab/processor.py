# -*- coding: utf-8 -*-
"""
ProcessorRegisters — параметры цветовой детекции и площади контура (Inspector prototype).

Маршрутизация: processor.
"""
from typing import Annotated, Any, ClassVar, Dict, List

from pydantic import Field, model_validator

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

PROCESSOR_ROUTING = FieldRouting(channel="control_processor")

DEFAULT_CROP_CAMERA_FOR_REGISTER = "default"


class ProcessorRegisters(SchemaBase):
    """Регистры параметров цветовой детекции (BGR) и площади пятна."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_nested_payloads(cls, data: Any) -> Any:
        """Миграция legacy crop_regions и нормализация post_processing при load / validate."""
        if not isinstance(data, dict):
            return data
        from .crop_regions_payload import normalize_crop_regions_payload
        from .post_processing_payload import normalize_post_processing_payload

        out = dict(data)
        if "crop_regions" in out:
            out["crop_regions"] = normalize_crop_regions_payload(
                out["crop_regions"],
                default_camera=DEFAULT_CROP_CAMERA_FOR_REGISTER,
            )
        if "post_processing_regions" in out:
            out["post_processing_regions"] = normalize_post_processing_payload(
                out["post_processing_regions"]
            )
        return out

    color_lower: Annotated[
        List[int],
        FieldMeta(
            "BGR Lower",
            info="Нижняя граница BGR для маски (B, G, R).",
            routing=PROCESSOR_ROUTING,
        ),
    ] = [0, 0, 150]

    color_upper: Annotated[
        List[int],
        FieldMeta(
            "BGR Upper",
            info="Верхняя граница BGR для маски (B, G, R).",
            routing=PROCESSOR_ROUTING,
        ),
    ] = [100, 100, 255]

    min_area: Annotated[
        int,
        FieldMeta(
            "Мин. площадь",
            info="Минимальная площадь контура (px).",
            min=10,
            max=5000,
            unit="px",
            routing=PROCESSOR_ROUTING,
        ),
    ] = 500

    max_area: Annotated[
        int,
        FieldMeta(
            "Макс. площадь",
            info="Максимальная площадь контура (px). 0 — без ограничения.",
            min=0,
            max=50000,
            unit="px",
            routing=PROCESSOR_ROUTING,
        ),
    ] = 50000

    crop_regions: Annotated[
        Dict[str, Any],
        FieldMeta(
            "Регионы обрезки",
            info="Вложенный dict: camera_id → region_name → [x, y, width, height]. "
            "Плоский legacy {region → {params, rect}} мигрируется при загрузке в GUI.",
            routing=PROCESSOR_ROUTING,
        ),
    ] = Field(default_factory=dict)

    post_processing_regions: Annotated[
        Dict[str, Any],
        FieldMeta(
            "Регионы постобработки / просмотра",
            info="camera_id → список регионов (порядок важен). "
            "Каждый регион: name, x1, y1, x2, y2, enabled, is_main, processing_enabled.",
            routing=PROCESSOR_ROUTING,
        ),
    ] = Field(default_factory=dict)

    logical_camera_ids: Annotated[
        List[str],
        FieldMeta(
            "Логические камеры",
            info="Стабильные id для ComboBox ROI/постобработки: simulator, webcam_<device_id>, "
            "hikvision_<index>. Согласованы с ключами crop_regions; доставка в процессор не требуется.",
            routing={"channel": "control_processor", "process_targets": []},
        ),
    ] = Field(default_factory=list)
