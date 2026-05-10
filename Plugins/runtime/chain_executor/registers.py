"""ChainExecutorRegisters — все параметры chain_executor плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("ChainExecutorRegistersV1")
class ChainExecutorRegisters(SchemaBase):
    """Все параметры chain_executor — шаги, режим параллельности, обработка ошибок."""

    # Шаги цепочки
    steps: Annotated[list[dict], FieldMeta(
        "Steps",
        info='Шаги цепочки: [{"plugin_class": "full.path.Plugin", "plugin_name": "...", "config": {...}}]',
    )] = []

    # Параллельный режим
    parallel: Annotated[bool, FieldMeta(
        "Parallel", info="Параллельный режим (каждый шаг получает копию items)",
    )] = False

    # Максимальное число потоков для параллельного режима
    max_workers: Annotated[int, FieldMeta(
        "Max Workers", info="Максимальное число потоков для параллельного режима",
        min=1, max=64,
    )] = 4

    # При ошибке в шаге: skip (продолжить) или fail (остановить)
    on_error: Annotated[str, FieldMeta(
        "On Error", info='Поведение при ошибке шага: "skip" или "fail"',
    )] = "skip"
