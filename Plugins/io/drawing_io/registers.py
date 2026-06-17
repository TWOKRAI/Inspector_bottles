"""DrawingIoRegisters — параметры сохранения/загрузки карты точек (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("DrawingIoRegistersV1")
class DrawingIoRegisters(SchemaBase):
    """Сохранение карты точек (JSON + PNG-референс) и загрузка её обратно в тракт.

    Сохранение: команда drawing_save снимает текущие draw_points (мм) + границы + кадр.
    Загрузка: drawing_load читает JSON, ставит load_active — и плагин ПОДМЕНЯЕТ draw_points
    в каждом кадре (превью и робот рисуют загруженное), пока load_active не снят.
    """

    drawings_dir: Annotated[
        str,
        FieldMeta("Папка рисунков", info="куда сохранять/откуда грузить (json+png)"),
    ] = "drawings"

    save_image: Annotated[
        bool,
        FieldMeta("Сохранять кадр (PNG)", info="класть кадр-референс рядом с json"),
    ] = True

    # Ключи в item.
    points_source: Annotated[str, FieldMeta("Ключ точек", info="ключ draw_points")] = "draw_points"
    bounds_source: Annotated[str, FieldMeta("Ключ границ", info="ключ draw_bounds (лист)")] = "draw_bounds"

    # Загрузка: активна ли подмена + путь последнего загруженного.
    load_active: Annotated[
        bool,
        FieldMeta("Загрузка активна", info="True = рисуем загруженные точки (не живые)"),
    ] = False
    loaded_path: Annotated[str, FieldMeta("Загружено из", readonly=True)] = ""

    # Readonly статус.
    last_saved: Annotated[str, FieldMeta("Сохранено в", readonly=True)] = ""
    saves_done: Annotated[int, FieldMeta("Сохранений", readonly=True)] = 0
    loaded_points: Annotated[int, FieldMeta("Точек загружено", readonly=True)] = 0
