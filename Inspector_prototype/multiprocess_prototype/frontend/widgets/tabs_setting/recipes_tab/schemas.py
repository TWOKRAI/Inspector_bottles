# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/schemas.py
"""
Конфиг вкладки «Рецепты»: подписи, диапазон слота, колонки таблицы.

default_tab_item — для TabsConfig.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("RecipesTabConfig")
class RecipesTabConfig(SchemaBase):
    """Тексты и параметры вкладки рецептов."""

    group_title: Annotated[
        str,
        FieldMeta("Заголовок группы", info="QGroupBox вокруг панели управления слотом."),
    ] = "Рецепт"

    btn_load: Annotated[str, FieldMeta("Кнопка загрузки", info="Применить слот из YAML в регистры.")] = "Загрузить"
    btn_save: Annotated[str, FieldMeta("Кнопка сохранения", info="Сохранить текущие регистры в слот.")] = "Сохранить"
    btn_default: Annotated[
        str,
        FieldMeta("Кнопка дефолта", info="Загрузить слот default_value."),
    ] = "По умолчанию"

    label_slot: Annotated[str, FieldMeta("Подпись слота", info="Метка рядом с номером рецепта.")] = "Слот"
    recipe_index_min: Annotated[int, FieldMeta("Мин. индекс", info="Нижняя граница номера слота.")] = 0
    recipe_index_max: Annotated[int, FieldMeta("Макс. индекс", info="Верхняя граница номера слота.")] = 21

    table_group_title: Annotated[str, FieldMeta("Заголовок таблицы", info="Подпись над таблицей полей регистров.")] = (
        "Параметры (регистры)"
    )

    group_register_box: Annotated[
        str,
        FieldMeta("Группа регистров", info="QGroupBox вокруг слота и таблицы регистров."),
    ] = "Рецепт: параметры алгоритма"

    group_app_box: Annotated[
        str,
        FieldMeta("Группа приложения", info="QGroupBox вокруг слота и таблицы UI-схем."),
    ] = "Рецепт: интерфейс и приложение"

    table_app_group_title: Annotated[
        str,
        FieldMeta("Заголовок таблицы app", info="Подпись над таблицей схем приложения."),
    ] = "Параметры интерфейса (RecipesTab + Processing UI)"

    col_param: Annotated[str, FieldMeta("Колонка параметра", info="Заголовок колонки field id.")] = "Параметр"
    col_value: Annotated[str, FieldMeta("Колонка значения", info="Заголовок колонки значения.")] = "Значение"
    col_info: Annotated[str, FieldMeta("Колонка описания", info="Заголовок колонки FieldMeta.")] = "Информация"


def default_tab_item():
    from ..tab_item_config import TabItemConfig

    return TabItemConfig(id="recipes", title="Рецепты", widget="recipes")
