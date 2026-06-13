"""CenterCropRegisters — параметры center_crop плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).

Динамический crop квадратной области вокруг координаты центра, пришедшей от
line_filter (item["filtered"][*]["xy"]). Размер стороны — в пикселях (калибровки
мм↔px пока нет; см. план, Часть 2). Поведение у границы кадра настраивается.
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase

SizeMode = Literal["fixed", "radius"]


@register_schema("CenterCropRegistersV1")
class CenterCropRegisters(SchemaBase):
    """Параметры center_crop — размер квадрата и поведение на границе кадра."""

    # --- Режим размера выреза ---
    size_mode: Annotated[
        SizeMode,
        FieldMeta(
            "Size Mode",
            info=(
                "fixed = фиксированная сторона side_px; radius = под размер круга (сторона = 2·radius·scale + 2·margin)"
            ),
        ),
    ] = "fixed"

    # --- Размер выреза (size_mode=fixed) ---
    side_px: Annotated[
        int,
        FieldMeta(
            "Crop Side",
            info="Сторона квадрата (px) при size_mode=fixed. Размер в мм считается после калибровки.",
            min=2,
            max=4000,
            unit="px",
        ),
    ] = 200

    # --- Размер выреза (size_mode=radius) ---
    radius_scale: Annotated[
        float,
        FieldMeta(
            "Radius Scale",
            info="Множитель радиуса при size_mode=radius (1.0 = плотно по кругу, его bbox)",
            min=0.1,
            max=5.0,
        ),
    ] = 1.0
    margin_px: Annotated[
        int,
        FieldMeta(
            "Margin",
            info="Поля вокруг круга (px с каждой стороны) при size_mode=radius",
            min=0,
            max=2000,
            unit="px",
        ),
    ] = 10

    # --- Поведение на границе кадра ---
    drop_partial: Annotated[
        bool,
        FieldMeta(
            "Drop Partial",
            info="Если квадрат выходит за границу кадра — пропустить (не сохранять). Приоритетнее pad.",
        ),
    ] = False
    pad_if_oob: Annotated[
        bool,
        FieldMeta(
            "Pad If Out-of-Bounds",
            info=(
                "Дополнять выход за границу цветом pad_color → вырез всегда side_px×side_px. "
                "Если выключено и drop_partial выключен — окно обрезается к границам (вырез меньше стороны)."
            ),
        ),
    ] = True
    pad_color_bgr: Annotated[
        list[int],
        FieldMeta(
            "Pad Color BGR",
            info="Цвет заполнения вне кадра (BGR), когда pad_if_oob включён",
            widget="color3",
        ),
    ] = [0, 0, 0]

    # --- Привязка координаты центра / sidecar ---
    radius_match_dist: Annotated[
        int,
        FieldMeta(
            "Radius Match Distance",
            info="Макс. расстояние (px) сопоставления xy центра с detection-кругом для radius в sidecar (0 = выкл)",
            min=0,
            max=2000,
            unit="px",
        ),
    ] = 30
