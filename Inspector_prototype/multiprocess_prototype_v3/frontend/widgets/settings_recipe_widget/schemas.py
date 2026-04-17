# multiprocess_prototype_v3/frontend/widgets/settings_recipe_widget/schemas.py
"""
Общие подписи для панелей рецептов: **recipes_widget** (регистры) и **settings_recipe_widget** (app/UI).

Раньше модуль назывался `recipes_settings_widget`; каноническое расположение — здесь.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("RecipesTabConfig")
class RecipesTabConfig(SchemaBase):
    """Тексты для вкладки «Рецепты» и для панели app-рецепта в «Настройках»."""

    group_register_box: Annotated[
        str,
        FieldMeta("Группа рецепта регистров", info="QGroupBox вокруг слота и кнопок."),
    ] = "Рецепт регистров"

    group_app_box: Annotated[
        str,
        FieldMeta("Группа app-рецепта", info="QGroupBox вокруг слота и кнопок на вкладке настроек."),
    ] = "App-рецепт (UI)"

    label_slot: Annotated[str, FieldMeta("Подпись слота", info="Метка перед QLineEdit номера слота.")] = "Слот:"

    btn_load: Annotated[str, FieldMeta("Кнопка загрузки", info="Загрузить рецепт в регистры / из YAML.")] = (
        "Загрузить"
    )
    btn_save: Annotated[str, FieldMeta("Кнопка сохранения", info="Сохранить в слот YAML.")] = "Сохранить"
    btn_default: Annotated[str, FieldMeta("Кнопка дефолта", info="Загрузить значения по умолчанию.")] = (
        "По умолчанию"
    )

    table_group_title: Annotated[
        str,
        FieldMeta("Заголовок таблицы регистров", info="Подпись над деревом/таблицей полей алгоритма."),
    ] = "Параметры алгоритма (регистры)"

    table_app_group_title: Annotated[
        str,
        FieldMeta("Заголовок таблицы app", info="Подпись над деревом полей UI-схем."),
    ] = "Параметры UI (app-рецепт)"

    col_param: Annotated[str, FieldMeta("Колонка параметра", info="Заголовок первой колонки.")] = "Параметр"
    col_value: Annotated[str, FieldMeta("Колонка значения", info="Заголовок колонки редактируемого значения.")] = (
        "Значение"
    )
    col_info: Annotated[str, FieldMeta("Колонка описания", info="Заголовок колонки подсказки/описания.")] = (
        "Информация"
    )

    recipe_index_min: Annotated[
        int,
        FieldMeta("Минимальный номер слота", info="Нижняя граница для QLineEdit слота."),
    ] = 0
    recipe_index_max: Annotated[
        int,
        FieldMeta("Максимальный номер слота", info="Верхняя граница для QLineEdit слота."),
    ] = 21

    touch_keyboard: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для вкладки",
            info="Перекрывает глобальный конфиг; далее — touch_keyboard_slot / touch_keyboard_tree.",
        ),
    ] = Field(default=None)

    touch_keyboard_slot: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для поля слота",
            info="Перекрывает touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_tree: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для дерева параметров",
            info="Перекрывает touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)


def default_tab_item():
    """TabItemConfig вкладки «Рецепты» для TabsConfig."""
    from ..tabs_setting.tab_item_config import TabItemConfig

    return TabItemConfig(id="recipes", title="Рецепты", widget="recipes")
