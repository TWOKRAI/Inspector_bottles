# multiprocess_prototype/frontend/widgets/cropped_regions_widget/schemas.py
"""Конфиг панели «Регионы обрезки»: подписи таблицы и кнопок + TabItemConfig."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from ..tabs_setting.tab_item_config import TabItemConfig


@register_schema("CroppedRegionsTabUiConfig")
class CroppedRegionsTabUiConfig(SchemaBase):
    """Тексты вкладки регионов обрезки (таблица + тулбар)."""

    group_regions: Annotated[
        str,
        FieldMeta("Группа регионов", info="QGroupBox вокруг тулбара и таблицы."),
    ] = "Регионы обрезки"

    table_title: Annotated[str, FieldMeta("Заголовок над таблицей", info="Подпись над StructuredTableWidget.")] = (
        "Список регионов (текущая камера)"
    )

    label_camera: Annotated[str, FieldMeta("Подпись выбора камеры", info="Метка перед QComboBox камер.")] = "Камера:"

    camera_ids: Annotated[
        List[str],
        FieldMeta(
            "Идентификаторы камер",
            info="Список имён камер для ComboBox; объединяется с ключами из данных рецепта.",
        ),
    ] = Field(default_factory=lambda: ["default"])

    label_region_pick: Annotated[
        str,
        FieldMeta("Подпись выбора региона", info="Метка перед QComboBox списка регионов текущей камеры."),
    ] = "Регион:"

    label_region_name: Annotated[
        str,
        FieldMeta("Подпись имени региона", info="Метка перед полем имени выбранного/нового региона."),
    ] = "Имя региона:"

    label_name_input: Annotated[str, FieldMeta("Подпись поля имени", info="Устар.: использовать label_region_name.")] = (
        "Имя:"
    )

    placeholder_name: Annotated[str, FieldMeta("Placeholder имени", info="Подсказка в поле имени.")] = (
        "Имя нового региона"
    )

    btn_add: Annotated[str, FieldMeta("Кнопка добавить", info="Добавить регион с текущими параметрами ROI.")] = (
        "Добавить регион"
    )

    btn_remove: Annotated[str, FieldMeta("Кнопка удалить", info="Удалить выбранную строку.")] = "Удалить"

    btn_save: Annotated[
        str,
        FieldMeta("Кнопка сохранить в регион", info="Записать слайдеры в выбранный регион."),
    ] = "Сохранить в регион"

    col_name: Annotated[str, FieldMeta("Колонка имя", info="Заголовок колонки имени региона.")] = "Имя"
    col_x: Annotated[str, FieldMeta("Колонка x", info="Заголовок колонки x.")] = "x"
    col_y: Annotated[str, FieldMeta("Колонка y", info="Заголовок колонки y.")] = "y"
    col_width: Annotated[str, FieldMeta("Колонка width", info="Заголовок колонки ширины.")] = "width"
    col_height: Annotated[str, FieldMeta("Колонка height", info="Заголовок колонки высоты.")] = "height"

    hint_footer: Annotated[
        str,
        FieldMeta(
            "Подсказка внизу",
            info="Краткое описание синхронизации таблицы и слайдеров.",
        ),
    ] = (
        "Регион выбирают строкой в таблице или списком «Регион». Числа и имя можно править в таблице или на панели ниже; "
        "«Сохранить в регион» записывает координаты слайдеров и переименование из поля имени. "
        "«Добавить регион» — новый регион с текущими координатами."
    )

    group_roi_params: Annotated[
        str,
        FieldMeta("Группа ROI", info="Заголовок QGroupBox вокруг контролов params."),
    ] = "Параметры области (ROI)"

    roi_numeric_views: Annotated[
        Dict[str, str],
        FieldMeta(
            "Вид числового поля",
            info="Ключ поля CroppedRoiPanelRegisters (x, y, width, height) → «slider» или «spinbox».",
        ),
    ] = Field(default_factory=dict)

    touch_keyboard: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для NumericControl ROI",
            info="Перекрывает глобальный FrontendConfig.touch_keyboard; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_tree: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для дерева регионов",
            info="Перекрывает touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_roi: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для слайдеров/спинбоксов ROI",
            info="Перекрывает touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)

    touch_keyboard_name: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для поля имени региона",
            info="Перекрывает touch_keyboard_roi и touch_keyboard вкладки; mode: mini | full.",
        ),
    ] = Field(default=None)


def default_tab_item() -> TabItemConfig:
    """TabItemConfig для вкладки «Регионы обрезки» в TabsConfig."""
    return TabItemConfig(
        id="cropped_regions",
        title="Регионы обрезки",
        widget="cropped_regions",
    )
