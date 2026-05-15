"""PilotWidgetsRegisters — поля для тестового стенда form-фабрики.

Phase 2.0 pilot: только bool (CheckboxControl через ActionBusRegistersManager).
Phase 2.1+ постепенно добавит int / float / literal / color3.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("PilotWidgetsRegistersV1")
class PilotWidgetsRegisters(SchemaBase):
    """Параметры pilot-плагина — тестовый стенд для form-фабрики."""

    enabled: Annotated[
        bool,
        FieldMeta(
            "Enabled",
            info="Если включено — worker логирует tick и инкрементирует счётчик",
        ),
    ] = True
