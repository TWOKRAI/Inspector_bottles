"""MorphologyRegisters — параметры морфологической чистки маски (live-tunable)."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

# Морфологическая операция над бинарной маской:
#   open       — эрозия→дилатация: убирает мелкие крапинки-шум (не трогает крупные пятна)
#   close      — дилатация→эрозия: заполняет мелкие дырки внутри пятен
#   open_close — сначала open, потом close: «вырезать» только чистые пятна (шум + дырки)
#   erode      — сжать пятна (отделить слипшиеся)
#   dilate     — расширить пятна
#   none       — без обработки (passthrough)
MorphOp = Literal["open", "close", "open_close", "erode", "dilate", "none"]

# Форма структурного элемента (ядра):
KernelShape = Literal["ellipse", "rect", "cross"]


@register_schema("MorphologyRegistersV1")
class MorphologyRegisters(SchemaBase):
    """Параметры морфологии: операция, форма и размер ядра, число итераций."""

    operation: Annotated[
        MorphOp,
        FieldMeta(
            "Operation",
            info="open=убрать шум, close=заполнить дырки, open_close=и то и то, erode/dilate, none",
            widget="combo",
        ),
    ] = "open_close"
    kernel_shape: Annotated[
        KernelShape,
        FieldMeta("Kernel Shape", info="Форма структурного элемента: ellipse / rect / cross", widget="combo"),
    ] = "ellipse"
    kernel_size: Annotated[
        int,
        FieldMeta(
            "Kernel Size",
            info="Размер ядра (px, нечётный; будет приведён к нечётному ≥ 1)",
            min=1,
            max=51,
            unit="px",
        ),
    ] = 5
    iterations: Annotated[
        int,
        FieldMeta("Iterations", info="Число повторов операции", min=1, max=10),
    ] = 1
