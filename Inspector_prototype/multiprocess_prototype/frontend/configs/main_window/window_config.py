# multiprocess_prototype/frontend/configs/main_window/window_config.py
"""
WindowConfig — конфигурация главного окна.

Параметры: title, min_width, min_height.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("WindowConfig")
class WindowConfig(SchemaBase):
    """Конфигурация окна MainWindow."""

    title: Annotated[
        str,
        FieldMeta(
            "Заголовок окна",
            info="Отображается в title bar приложения.",
            info_i18n={"ru": "Заголовок окна", "en": "Window title"},
        ),
    ] = "Inspector Prototype"

    min_width: Annotated[
        int,
        FieldMeta(
            "Минимальная ширина",
            info="Минимальная ширина окна в пикселях.",
            unit="px",
            min=400,
            max=3840,
        ),
    ] = 1024

    min_height: Annotated[
        int,
        FieldMeta(
            "Минимальная высота",
            info="Минимальная высота окна в пикселях.",
            unit="px",
            min=300,
            max=2160,
        ),
    ] = 600
