"""Конфиг RendererCompositorPlugin — параметры compositing нескольких кадров."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RendererCompositorPluginConfigV1")
class RendererCompositorConfig(PluginConfig):
    """Конфиг плагина compositing нескольких кадров.

    Processing: несколько кадров → один составной кадр (grid/side_by_side/pip).
    Layout и overlay изменяются runtime через команды set_layout / toggle_overlay.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.renderer_compositor.plugin.RendererCompositorPlugin"
    )
    plugin_name: str = "renderer_compositor"
    category: str = "processing"

    # Режим compositing
    layout_mode: Annotated[
        str, FieldMeta(description='Тип layout: "grid", "side_by_side", "pip"')
    ] = "grid"

    # Параметры сетки
    grid_cols: Annotated[
        int, FieldMeta(description="Количество колонок в grid-layout")
    ] = 2

    grid_rows: Annotated[
        int, FieldMeta(description="Количество строк в grid-layout")
    ] = 2

    # Размер выходного кадра
    output_width: Annotated[
        int, FieldMeta(description="Ширина выходного кадра (px)")
    ] = 1280

    output_height: Annotated[
        int, FieldMeta(description="Высота выходного кадра (px)")
    ] = 720

    # Параметры PiP
    pip_scale: Annotated[
        float, FieldMeta(description="Масштаб PiP-окна (0.0–1.0)")
    ] = 0.25

    pip_position: Annotated[
        str,
        FieldMeta(
            description='Позиция PiP-окна: "top_right", "top_left", "bottom_right", "bottom_left"'
        ),
    ] = "top_right"

    # Текстовый overlay
    overlay_enabled: Annotated[
        bool, FieldMeta(description="Показывать текстовый overlay на кадре")
    ] = True

    overlay_font_scale: Annotated[
        float, FieldMeta(description="Масштаб шрифта overlay")
    ] = 0.5

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM не нужен — compositing происходит в памяти."""
        return None
