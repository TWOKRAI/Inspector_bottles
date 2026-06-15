"""EdgeDetectionRegisters — параметры TEED-детектора линий (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("EdgeDetectionRegistersV1")
class EdgeDetectionRegisters(SchemaBase):
    """Параметры детекции линий (TEED или U2Net Portrait)."""

    method: Annotated[
        str,
        FieldMeta("Метод", info="teed (тонкие края) | u2net_portrait (художественный портрет)"),
    ] = "teed"
    invert: Annotated[
        bool,
        FieldMeta("Инвертировать", info="Если линии/фон поменялись местами — включи"),
    ] = False
    threshold: Annotated[
        float,
        FieldMeta("Порог", info="Порог бинаризации карты линий (0..1; меньше = больше деталей)", min=0.0, max=1.0),
    ] = 0.5
    device: Annotated[
        str,
        FieldMeta("Устройство", info="cuda | cpu (auto-fallback на cpu без CUDA)"),
    ] = "cuda"
    weights_path: Annotated[
        str,
        FieldMeta("Путь к весам", info="Пусто = авто-поиск (~/.cache/sketch_robot, data/models/teed)"),
    ] = ""
    inference_every_n: Annotated[
        int,
        FieldMeta("Инференс каждый N кадр", info="1 = каждый кадр; >1 = пропуск для скорости", min=1, max=30),
    ] = 1
