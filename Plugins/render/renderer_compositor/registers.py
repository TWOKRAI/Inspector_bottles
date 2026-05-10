"""RendererCompositorRegisters — все параметры renderer_compositor плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("RendererCompositorRegistersV1")
class RendererCompositorRegisters(SchemaBase):
    """Все параметры renderer_compositor — layout + размеры + PiP + overlay."""

    # Режим compositing
    layout_mode: Annotated[str, FieldMeta(
        "Layout Mode", info='Тип layout: "grid", "side_by_side", "pip"',
    )] = "grid"

    # Параметры сетки
    grid_cols: Annotated[int, FieldMeta(
        "Grid Cols", info="Количество колонок в grid-layout",
        min=1, max=16,
    )] = 2
    grid_rows: Annotated[int, FieldMeta(
        "Grid Rows", info="Количество строк в grid-layout",
        min=1, max=16,
    )] = 2

    # Размер выходного кадра
    output_width: Annotated[int, FieldMeta(
        "Output Width", info="Ширина выходного кадра", unit="px",
        min=1,
    )] = 1280
    output_height: Annotated[int, FieldMeta(
        "Output Height", info="Высота выходного кадра", unit="px",
        min=1,
    )] = 720

    # Параметры PiP
    pip_scale: Annotated[float, FieldMeta(
        "PiP Scale", info="Масштаб PiP-окна (0.0–1.0)",
        min=0.05, max=1.0,
    )] = 0.25
    pip_position: Annotated[str, FieldMeta(
        "PiP Position",
        info='Позиция PiP-окна: "top_right", "top_left", "bottom_right", "bottom_left"',
    )] = "top_right"

    # Текстовый overlay
    overlay_enabled: Annotated[bool, FieldMeta(
        "Overlay Enabled", info="Показывать текстовый overlay на кадре",
    )] = True
    overlay_font_scale: Annotated[float, FieldMeta(
        "Overlay Font Scale", info="Масштаб шрифта overlay",
        min=0.1, max=5.0,
    )] = 0.5
