"""Конфигурационная схема панели профилей настроек (Phase 2, Task 2.1)."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema
from pydantic import Field


@register_schema("SettingsProfileTabConfig")
class SettingsProfileTabConfig(SchemaBase):
    """UI-строки и настройки панели профилей настроек."""

    group_box_title: Annotated[
        str,
        FieldMeta("Группа профиля", info="QGroupBox вокруг селектора и кнопок."),
    ] = "Профиль настроек"

    label_profile: Annotated[
        str,
        FieldMeta("Подпись профиля", info="Метка перед QComboBox выбора профиля."),
    ] = "Профиль:"

    btn_apply: Annotated[
        str,
        FieldMeta("Кнопка применения", info="Загрузить профиль в регистры."),
    ] = "Применить"

    btn_save: Annotated[
        str,
        FieldMeta("Кнопка сохранения", info="Сохранить текущие регистры в профиль."),
    ] = "Сохранить"

    btn_default: Annotated[
        str,
        FieldMeta("Кнопка дефолта", info="Переключить на профиль 'default'."),
    ] = "По умолчанию"

    table_title: Annotated[
        str,
        FieldMeta("Заголовок таблицы", info="Подпись над деревом параметров приложения."),
    ] = "Параметры приложения"

    col_param: Annotated[
        str,
        FieldMeta("Колонка параметра", info="Заголовок первой колонки."),
    ] = "Параметр"

    col_value: Annotated[
        str,
        FieldMeta("Колонка значения", info="Заголовок колонки редактируемого значения."),
    ] = "Значение"

    col_info: Annotated[
        str,
        FieldMeta("Колонка описания", info="Заголовок колонки подсказки/описания."),
    ] = "Информация"

    touch_keyboard: Annotated[
        dict[str, Any] | None,
        FieldMeta("Touch-клавиатура", info="Конфиг touch-клавиатуры для панели."),
    ] = Field(default=None)


def default_settings_profile_tab_item():
    """TabItemConfig для встраивания в TabsConfig (будущая интеграция)."""
    from ...tabs_setting.tab_item_config import TabItemConfig

    return TabItemConfig(
        id="settings_profile",
        title="Профиль настроек",
        widget="settings_profile",
    )


__all__ = ["SettingsProfileTabConfig", "default_settings_profile_tab_item"]
