# multiprocess_prototype_v3/frontend/windows/main_window/config.py
"""
Конфиги главного окна (feature main_window): окно, шапка, панель изображений.

AppHeaderConfig — наследник framework HeaderConfig с дефолтами приложения.
"""

from typing import Annotated, List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema
from multiprocess_framework.modules.frontend_module.widgets.header import (
    AdminButtonConfig,
    HeaderButtonItem,
    HeaderConfig,
    LogoConfig,
)


@register_schema("WindowConfig")
class WindowConfig(SchemaBase):
    """Параметры QMainWindow (главный фрейм прототипа)."""

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


@register_schema("ImageSlotConfig")
class ImageSlotConfig(SchemaBase):
    """Слот панели изображений."""

    id: str = "original"
    label: Annotated[
        str,
        FieldMeta("Подпись слота", info="Метка слота в UI."),
    ] = "Original"
    visible_default: Annotated[
        bool,
        FieldMeta("Видим по умолчанию", info="Показывать слот при старте."),
    ] = True


def _default_image_slots() -> List[ImageSlotConfig]:
    return [
        ImageSlotConfig(id="original", label="Original", visible_default=True),
        ImageSlotConfig(id="mask", label="Mask", visible_default=True),
    ]


@register_schema("ImagePanelConfig")
class ImagePanelConfig(SchemaBase):
    """Конфигурация ImagePanelWidget."""

    slots: List[ImageSlotConfig] = Field(default_factory=_default_image_slots)


@register_schema("AppHeaderConfig")
class AppHeaderConfig(HeaderConfig):
    """Шапка прототипа.

    `brand_text` — надпись справа от кнопки-переключателя в AppHeaderWidget.
    Поля `logo`/`admin_button` унаследованы от framework HeaderConfig для
    обратной совместимости валидации, но AppHeaderWidget их не использует.
    """

    brand_text: str = "INNOTECH"
    logo: LogoConfig = Field(
        default_factory=lambda: LogoConfig(
            path="resources/logo.png",
            max_width=200,
            max_height=80,
            visible=False,
        )
    )
    admin_button: AdminButtonConfig = Field(
        default_factory=lambda: AdminButtonConfig(
            label="Админ панель",
            visible=False,
            action_id="admin",
        )
    )
    windows: List[HeaderButtonItem] = Field(
        default_factory=lambda: [
            HeaderButtonItem(id="main", label="Домой"),
            HeaderButtonItem(id="loading", label="Загрузка"),
        ]
    )


@register_schema("MainWindowConfig")
class MainWindowConfig(SchemaBase):
    """Композиция секций dict для MainWindow."""

    window: WindowConfig = Field(default_factory=WindowConfig)
    header: AppHeaderConfig = Field(default_factory=AppHeaderConfig)
    image_panel: ImagePanelConfig = Field(default_factory=ImagePanelConfig)


__all__ = [
    "WindowConfig",
    "ImageSlotConfig",
    "ImagePanelConfig",
    "AppHeaderConfig",
    "MainWindowConfig",
]
