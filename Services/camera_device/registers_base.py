# -*- coding: utf-8 -*-
"""Register ядра камеры (Task 1.8, заготовка): что нужно сквозному срезу «фейк -> поток -> item -> дерево».

Профили run/rest и поля триггера добавляют следующие задачи; здесь только то, что видно в срезе.
Слой: Services -> framework, без импорта `multiprocess_prototype`.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CameraDeviceRegistersV1")
class CameraDeviceRegisters(SchemaBase):
    """Параметры источника кадров и его телеметрия."""

    driver: Annotated[
        str,
        FieldMeta("Драйвер", info="Имя драйвера порта; сейчас известен только fake"),
    ] = "fake"

    camera_id: Annotated[
        int,
        FieldMeta("ID камеры", info="Попадает в item (camera_id) — различать несколько источников", min=0),
    ] = 0

    device_id: Annotated[
        str,
        FieldMeta("ID прибора", info="Серийный номер; пусто = первый найденный прибор"),
    ] = ""

    auto_start: Annotated[
        bool,
        FieldMeta("Автозахват", info="Взять прибор при старте процесса; иначе — командой take_device"),
    ] = True

    # --- Телеметрия (readonly — GUI смотрит, не правит) ---
    device_state: Annotated[
        str,
        FieldMeta(
            "Состояние прибора",
            info="idle | opening | grabbing | stopping | closed | busy | not_found | error",
            readonly=True,
        ),
    ] = "closed"

    frames: Annotated[
        int,
        FieldMeta("Кадров", info="Сколько кадров отдано с момента старта", readonly=True),
    ] = 0
