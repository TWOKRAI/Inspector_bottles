# -*- coding: utf-8 -*-
"""
ProcessLaunchConfig — базовый SchemaBase для конфигов процесса под launcher.

Канон: ``model_dump()`` для полезной нагрузки; ``build()`` → HasBuild без
дублирования строк в каждом процессном конфиге.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Tuple

from ...data_schema_module import FieldMeta, SchemaBase


class ProcessLaunchConfig(SchemaBase):
    """
    Базовый конфиг запуска процесса.

    ``build()`` возвращает ``(process_name, proc_dict)`` с полями
    ``class`` и ``config``, где ``config`` — результат ``model_dump()`` без
    ``process_name`` и ``process_class`` (в т.ч. вложенный ``managers`` при
    использовании :class:`ManagersConfig`).
    """

    process_name: Annotated[
        str,
        FieldMeta("Имя процесса", info="Ключ процесса в launcher / shared registry."),
    ] = "process"

    process_class: Annotated[
        str,
        FieldMeta("Класс процесса", info="Полный путь к классу ProcessModule."),
    ] = (
        "Inspector_prototype.multiprocess_framework.modules"
        ".process_module.core.process_module.ProcessModule"
    )

    def build(self) -> Tuple[str, Dict[str, Any]]:
        payload = self.model_dump()
        name = str(payload.pop("process_name"))
        class_path = str(payload.pop("process_class"))
        return name, {"class": class_path, "config": payload}
