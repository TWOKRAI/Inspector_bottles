"""PilotWidgetsRegisters — поля для тестового стенда form-фабрики.

Phase 2.0 pilot: bool + int. Поля объявлены прямым Annotated[T, FieldMeta(...)]
— тот же стиль, что используется во всём фреймворке (multiprocess_prototype/
registers/, framework/modules/*/registers/). Фабрика форм рисует виджет
по FieldMeta.ui_hint.
"""

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
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
            info="Если включено — инкрементирует счётчик",
            widget="checkbox",
        ),
    ] = False

    info: Annotated[
        bool,
        FieldMeta(
            "Info",
            info="Если включено — worker логирует tick",
            widget="checkbox",
        ),
    ] = True

    time_value: Annotated[
        int,
        FieldMeta(
            "Частота опроса",
            info="Время между tick-ами worker'а",
            widget="slider",
            min=1,
            max=60,
            unit="s",
        ),
    ] = 1
