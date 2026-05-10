# multiprocess_prototype/frontend/widgets/post_processing_widget/schemas.py
"""Конфиг вкладки постобработки / регионов просмотра."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from ...tabs_setting.tab_item_config import TabItemConfig


@register_schema("PostProcessingTabUiConfig")
class PostProcessingTabUiConfig(SchemaBase):
    """Тексты вкладки постобработки."""

    group_regions: Annotated[str, FieldMeta("Группа таблицы", info="QGroupBox вокруг таблицы регионов.")] = (
        "Регионы / изображения"
    )

    group_edit: Annotated[str, FieldMeta("Группа формы", info="Редактирование выбранного региона.")] = (
        "Редактирование региона"
    )

    label_camera: Annotated[str, FieldMeta("Подпись камеры", info="Перед ComboBox камер.")] = "Камера:"

    camera_ids: Annotated[
        List[str],
        FieldMeta("Камеры", info="Идентификаторы для ComboBox; объединяются с ключами из данных."),
    ] = Field(default_factory=lambda: ["default"])

    col_name: Annotated[str, FieldMeta("Колонка имя", info="")] = "Название"
    col_enabled: Annotated[str, FieldMeta("Колонка вкл.", info="")] = "Вкл."
    col_is_main: Annotated[str, FieldMeta("Колонка главный", info="")] = "Главный"
    col_processing: Annotated[str, FieldMeta("Колонка обработка", info="")] = "Обработка"
    col_coords: Annotated[str, FieldMeta("Колонка координаты", info="")] = "Координаты"

    placeholder_name: Annotated[str, FieldMeta("Placeholder имени", info="")] = "Имя региона"

    btn_show: Annotated[str, FieldMeta("Показать регион", info="MVP: заглушка.")] = "Показать"
    btn_back_main: Annotated[str, FieldMeta("К основному", info="MVP: заглушка.")] = "Вернуться к основному"

    hint_footer: Annotated[str, FieldMeta("Подсказка", info="")] = (
        "Регионы задаются по камере; порядок строк — порядок в пайплайне. "
        "Кнопки «Показать» / «Вернуться к основному» в прототипе не связаны с окном просмотра."
    )

    touch_keyboard: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура",
            info="Перекрывает глобальный конфиг; QSpinBox координат и дерево; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_tree: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для дерева регионов",
            info="Перекрывает touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_form: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для формы редактирования",
            info="QLineEdit имени и QSpinBox координат; перекрывает touch_keyboard вкладки.",
        ),
    ] = Field(default=None)


def default_tab_item() -> TabItemConfig:
    return TabItemConfig(
        id="post_processing",
        title="Постобработка",
        widget="post_processing",
    )
