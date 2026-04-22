# -*- coding: utf-8 -*-
"""
ProcessorRegisters — параметры цветовой детекции и площади контура (Inspector prototype).

Маршрутизация: processor.
"""
from typing import Annotated, Any, ClassVar, List

from pydantic import Field, model_validator

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

PROCESSOR_ROUTING = FieldRouting(channel="control_processor")

DEFAULT_CROP_CAMERA_FOR_REGISTER = "default"

from ..pipeline.pipeline_config import PipelineConfig  # noqa: E402 — после PROCESSOR_ROUTING


class ProcessorRegisters(SchemaBase):
    """Регистры параметров цветовой детекции (BGR) и площади пятна."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_nested_payloads(cls, data: Any) -> Any:
        """Миграция legacy crop/post в ``vision_pipeline`` при load / validate."""
        if not isinstance(data, dict):
            return data
        from ..pipeline.migration import normalize_processor_register_payload

        return normalize_processor_register_payload(dict(data))

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

    logical_camera_ids: Annotated[
        List[str],
        FieldMeta(
            "Логические камеры",
            info="Стабильные id для ComboBox ROI/постобработки: simulator, webcam_<device_id>, "
            "hikvision_<index>. Согласованы с ключами vision_pipeline.cameras; доставка в процессор не требуется.",
            routing={"channel": "control_processor", "process_targets": []},
        ),
    ] = Field(default_factory=list)

    vision_pipeline: Annotated[
        PipelineConfig,
        FieldMeta(
            "Конвейер камера→ROI→обработки",
            info="Иерархическая конфигурация (камеры → регионы → обработки); значения в рецепте YAML.",
            routing=PROCESSOR_ROUTING,
        ),
    ] = Field(default_factory=PipelineConfig)
