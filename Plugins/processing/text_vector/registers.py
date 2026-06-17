"""TextVectorRegisters — параметры векторного генератора текста/сердца (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("TextVectorRegistersV1")
class TextVectorRegisters(SchemaBase):
    """Генерация однолинейных штрихов текста/сердца → draw_points (в пикселях кадра).

    Точки в пикселях [0..src]×[0..src] — дальше robot_scale впишет в лист робота (тот же
    контракт, что у strokes_to_points). Несколько экземпляров в цепочке (merge=True)
    накапливают элементы: основной текст + имя ниже + сердце.
    """

    enabled: Annotated[
        bool,
        FieldMeta("Включён", info="False = проброс входных draw_points без изменений"),
    ] = True

    element: Annotated[
        str,
        FieldMeta("Элемент", info="text = текст по шрифту; heart = сердце"),
    ] = "text"

    text: Annotated[
        str,
        FieldMeta("Текст", info="строка для рисования (лат/кириллица/цифры; неизвестные — пропуск)"),
    ] = ""

    font: Annotated[
        str,
        FieldMeta("Шрифт", info="hershey_simplex (однолинейный)"),
    ] = "hershey_simplex"

    # Геометрия элемента (в пикселях кадра).
    size_px: Annotated[
        float,
        FieldMeta("Размер (px)", info="высота прописной/сердца в пикселях", min=2.0, max=2000.0),
    ] = 80.0
    pos_x: Annotated[
        float,
        FieldMeta("Позиция X (px)", info="центр элемента по X в кадре", min=-2000.0, max=2000.0),
    ] = 320.0
    pos_y: Annotated[
        float,
        FieldMeta("Позиция Y (px)", info="центр элемента по Y в кадре", min=-2000.0, max=2000.0),
    ] = 240.0
    rotation_deg: Annotated[
        float,
        FieldMeta("Поворот (°)", info="поворот вокруг центра элемента", min=-360.0, max=360.0),
    ] = 0.0
    scale: Annotated[
        float,
        FieldMeta("Масштаб", info="доп. множитель размера (1 = как size_px)", min=0.05, max=20.0),
    ] = 1.0
    tracking_px: Annotated[
        float,
        FieldMeta("Трекинг (px)", info="доп. зазор между символами", min=-200.0, max=500.0),
    ] = 0.0

    # Накапливать с входными точками (несколько элементов) или заменять.
    merge: Annotated[
        bool,
        FieldMeta("Добавлять к входу", info="True = дописать к входным точкам; False = заменить только этим элементом"),
    ] = True

    # Ключ точек в item (вход и выход).
    points_source: Annotated[
        str,
        FieldMeta("Ключ точек", info="ключ draw_points в item"),
    ] = "draw_points"

    # Счётчики (readonly).
    points_last: Annotated[int, FieldMeta("Точек элемента", readonly=True)] = 0
    skipped_last: Annotated[str, FieldMeta("Пропущено символов", readonly=True)] = ""
