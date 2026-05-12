"""ThemeVariables — регистр переменных темы оформления.

Содержит все CSS-переменные палитры: цвета, шрифты, размеры шрифтов, скругления.
Группировка для UI задаётся через THEME_VAR_TREE (двухуровневый dict).

Добавление новой переменной = одно поле + одна строка в THEME_VAR_TREE.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


# ---------------------------------------------------------------------------
# Двухуровневое дерево переменных для отображения в UI
# ---------------------------------------------------------------------------
THEME_VAR_TREE: dict[str, dict[str, list[str]]] = {
    "Глобальное": {
        "Палитра": ["bg_deep", "bg_mid", "bg_hi", "bg_hi2",
                     "surf_0", "surf_1", "surf_2", "surf_deep",
                     "silver_hi", "silver", "silver_lo"],
        "Текст": ["text_0", "text_1", "text_2", "text_3"],
        "Акцент": ["accent", "accent_hi", "accent_lo", "accent_deep"],
        "Семантика": ["danger", "success", "warn"],
        "Шрифты": ["font_family", "font_family_mono"],
        "Размеры шрифтов": ["font_xs", "font_2xs", "font_sm", "font_base",
                              "font_md", "font_lg_sm", "font_lg",
                              "font_xl_sm", "font_xl", "font_xxl_sm",
                              "font_xxl", "font_brand"],
        "Скругления": ["radius_xs", "radius_sm", "radius_5", "radius_6",
                         "radius_md", "radius_10", "radius_lg", "radius_14",
                         "radius_pill_sm", "radius_xl", "radius_pill"],
        "Тени": [],  # TODO: Task 1.3
        "Подсветки": [],  # TODO: Task 1.3
        "Акцент (стекло)": [],  # TODO: Task 1.3
    },
    "Компоненты": {
        "Кнопки": [],  # TODO: Task 1.2
        "Кнопки Accent": [],  # TODO: Task 1.2
        "Кнопки Danger": [],  # TODO: Task 1.2
        "Поля ввода": [],  # TODO: Task 1.2
        "Скроллбар": [],  # TODO: Task 1.2
        "Слайдер": [],  # TODO: Task 1.2
        "Карточки": [],  # TODO: Task 1.2
    },
    "Окно": {
        "Шапка": [],  # TODO: Task 1.2
        "Фон окна": [],  # TODO: Task 1.2
        "Вкладки": [],  # TODO: Task 1.2
        "GroupBox / Card": [],  # TODO: Task 1.2
    },
    "Специальное": {
        "Каналы RGB": [],  # TODO: Task 1.2
        "Оповещения": [],  # TODO: Task 1.2
        "Pipeline": [],  # TODO: Task 1.2
        "Watchdog": [],  # TODO: Task 1.2
    },
}


def flatten_theme_var_tree(tree: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    """Конвертировать 2-уровневый THEME_VAR_TREE в плоский dict для обратной совместимости."""
    result = {}
    for _category, subcats in tree.items():
        for subcat_name, var_list in subcats.items():
            result[subcat_name] = var_list
    return result


# Описания переменных (для столбца «Описание» в UI)
THEME_VAR_DESCRIPTIONS: dict[str, str] = {
    "bg_deep": "Самый тёмный фон",
    "bg_mid": "Средний фон",
    "bg_hi": "Светлый фон",
    "bg_hi2": "Самый светлый фон",
    "surf_0": "Поверхность базовая",
    "surf_1": "Поверхность средняя",
    "surf_2": "Поверхность светлая",
    "surf_deep": "Поверхность глубокая",
    "silver_hi": "Серебро светлое",
    "silver": "Серебро базовое",
    "silver_lo": "Серебро тёмное",
    "text_0": "Основной текст",
    "text_1": "Вторичный текст",
    "text_2": "Приглушённый текст",
    "text_3": "Самый тёмный текст",
    "accent": "Акцентный цвет",
    "accent_hi": "Акцент светлый",
    "accent_lo": "Акцент тёмный",
    "accent_deep": "Акцент глубокий",
    "danger": "Ошибка / опасность",
    "success": "Успех",
    "warn": "Предупреждение",
    "font_family": "Основной шрифт",
    "font_family_mono": "Моноширинный шрифт",
    # --- Размеры шрифтов ---
    "font_xs": "Минимальный шрифт (9px) — подписи бренда",
    "font_2xs": "Очень маленький шрифт (10px) — hint labels",
    "font_sm": "Маленький шрифт (11px) — captions, секции",
    "font_base": "Базовый шрифт (12px) — основной текст таблиц",
    "font_md": "Средний шрифт (13px) — кнопки, поля ввода",
    "font_lg_sm": "Немного крупнее среднего (14px) — заголовки секций",
    "font_lg": "Крупный шрифт (15px) — заголовки панелей",
    "font_xl_sm": "Чуть меньше xl (16px) — заголовки окон",
    "font_xl": "Большой шрифт (17px) — акцентные заголовки",
    "font_xxl_sm": "Очень крупный шрифт (20px) — дашборд, счётчики",
    "font_xxl": "Двойной крупный шрифт (22px) — главные метрики",
    "font_brand": "Брендовый шрифт (28px) — логотип, splash",
    # --- Скругления ---
    "radius_xs": "Минимальное скругление (3px) — чекбоксы, badges",
    "radius_sm": "Маленькое скругление (4px) — inline-метки",
    "radius_5": "Скругление 5px — inputs, compact-кнопки",
    "radius_6": "Скругление 6px — стандартные кнопки",
    "radius_md": "Среднее скругление (8px) — карточки, панели",
    "radius_10": "Скругление 10px — groupbox, блоки контента",
    "radius_lg": "Крупное скругление (12px) — диалоги, модали",
    "radius_14": "Скругление 14px — крупные карточки",
    "radius_pill_sm": "Малая таблетка (15px) — теги, chip-элементы",
    "radius_xl": "Большое скругление (16px) — боковые панели",
    "radius_pill": "Полная таблетка (21px) — переключатели, toggle",
}


@register_schema("ThemeVariablesV3")
class ThemeVariables(SchemaBase):
    """Регистр переменных темы — цвета, шрифты, размеры шрифтов, скругления.

    Все значения — строки: hex-цвета (#rrggbb), названия шрифтов, px-размеры.
    Это упрощает подстановку в QSS-шаблоны через re.sub.
    """

    # --- Фон ---
    bg_deep: Annotated[
        str, FieldMeta("Фон глубокий", info="Самый тёмный фон (#1a1f28)")
    ] = "#1a1f28"
    bg_mid: Annotated[
        str, FieldMeta("Фон средний", info="Средний фон (#2d3440)")
    ] = "#2d3440"
    bg_hi: Annotated[
        str, FieldMeta("Фон светлый", info="Светлый фон (#4a5362)")
    ] = "#4a5362"
    bg_hi2: Annotated[
        str, FieldMeta("Фон ярче", info="Самый светлый фон (#5c6573)")
    ] = "#5c6573"

    # --- Поверхности ---
    surf_0: Annotated[
        str, FieldMeta("Поверхность 0", info="Поверхность базовая (#3a414e)")
    ] = "#3a414e"
    surf_1: Annotated[
        str, FieldMeta("Поверхность 1", info="Поверхность средняя (#5a6370)")
    ] = "#5a6370"
    surf_2: Annotated[
        str, FieldMeta("Поверхность 2", info="Поверхность светлая (#6e7886)")
    ] = "#6e7886"
    surf_deep: Annotated[
        str, FieldMeta("Поверхность глубокая", info="Поверхность глубокая (#252a33)")
    ] = "#252a33"

    # --- Серебро ---
    silver_hi: Annotated[
        str, FieldMeta("Серебро светлое", info="Серебро светлое (#c8ccd4)")
    ] = "#c8ccd4"
    silver: Annotated[
        str, FieldMeta("Серебро", info="Серебро базовое (#9ea6b2)")
    ] = "#9ea6b2"
    silver_lo: Annotated[
        str, FieldMeta("Серебро тёмное", info="Серебро тёмное (#6a7280)")
    ] = "#6a7280"

    # --- Текст ---
    text_0: Annotated[
        str, FieldMeta("Текст основной", info="Основной текст (#f2f5fa)")
    ] = "#f2f5fa"
    text_1: Annotated[
        str, FieldMeta("Текст вторичный", info="Вторичный текст (#c0c7d2)")
    ] = "#c0c7d2"
    text_2: Annotated[
        str, FieldMeta("Текст приглушённый", info="Приглушённый текст (#8a93a1)")
    ] = "#8a93a1"
    text_3: Annotated[
        str, FieldMeta("Текст тёмный", info="Самый тёмный текст (#5e6674)")
    ] = "#5e6674"

    # --- Акцент ---
    accent: Annotated[
        str, FieldMeta("Акцент", info="Акцентный цвет (#2b7fff)")
    ] = "#2b7fff"
    accent_hi: Annotated[
        str, FieldMeta("Акцент светлый", info="Акцент светлый (#4a95ff)")
    ] = "#4a95ff"
    accent_lo: Annotated[
        str, FieldMeta("Акцент тёмный", info="Акцент тёмный (#1f5fcc)")
    ] = "#1f5fcc"
    accent_deep: Annotated[
        str, FieldMeta("Акцент глубокий", info="Акцент глубокий (#153f8a)")
    ] = "#153f8a"

    # --- Семантика ---
    danger: Annotated[
        str, FieldMeta("Опасность", info="Ошибка / опасность (#e54863)")
    ] = "#e54863"
    success: Annotated[
        str, FieldMeta("Успех", info="Успех (#2ecc8f)")
    ] = "#2ecc8f"
    warn: Annotated[
        str, FieldMeta("Предупреждение", info="Предупреждение (#f0a23a)")
    ] = "#f0a23a"

    # --- Шрифты ---
    font_family: Annotated[
        str, FieldMeta("Основной шрифт", info="Семейство основного шрифта")
    ] = "Rajdhani"
    font_family_mono: Annotated[
        str, FieldMeta("Моноширинный шрифт", info="Семейство моноширинного шрифта")
    ] = "JetBrains Mono"

    # --- Размеры шрифтов ---
    font_xs: Annotated[
        str, FieldMeta("Шрифт xs", info="Минимальный шрифт (9px) — подписи бренда")
    ] = "9px"
    font_2xs: Annotated[
        str, FieldMeta("Шрифт 2xs", info="Очень маленький шрифт (10px) — hint labels")
    ] = "10px"
    font_sm: Annotated[
        str, FieldMeta("Шрифт sm", info="Маленький шрифт (11px) — captions, секции")
    ] = "11px"
    font_base: Annotated[
        str, FieldMeta("Шрифт base", info="Базовый шрифт (12px) — основной текст таблиц")
    ] = "12px"
    font_md: Annotated[
        str, FieldMeta("Шрифт md", info="Средний шрифт (13px) — кнопки, поля ввода")
    ] = "13px"
    font_lg_sm: Annotated[
        str, FieldMeta("Шрифт lg_sm", info="Немного крупнее среднего (14px) — заголовки секций")
    ] = "14px"
    font_lg: Annotated[
        str, FieldMeta("Шрифт lg", info="Крупный шрифт (15px) — заголовки панелей")
    ] = "15px"
    font_xl_sm: Annotated[
        str, FieldMeta("Шрифт xl_sm", info="Чуть меньше xl (16px) — заголовки окон")
    ] = "16px"
    font_xl: Annotated[
        str, FieldMeta("Шрифт xl", info="Большой шрифт (17px) — акцентные заголовки")
    ] = "17px"
    font_xxl_sm: Annotated[
        str, FieldMeta("Шрифт xxl_sm", info="Очень крупный шрифт (20px) — дашборд, счётчики")
    ] = "20px"
    font_xxl: Annotated[
        str, FieldMeta("Шрифт xxl", info="Двойной крупный шрифт (22px) — главные метрики")
    ] = "22px"
    font_brand: Annotated[
        str, FieldMeta("Шрифт brand", info="Брендовый шрифт (28px) — логотип, splash")
    ] = "28px"

    # --- Скругления ---
    radius_xs: Annotated[
        str, FieldMeta("Радиус xs", info="Минимальное скругление (3px) — чекбоксы, badges")
    ] = "3px"
    radius_sm: Annotated[
        str, FieldMeta("Радиус sm", info="Маленькое скругление (4px) — inline-метки")
    ] = "4px"
    radius_5: Annotated[
        str, FieldMeta("Радиус 5", info="Скругление 5px — inputs, compact-кнопки")
    ] = "5px"
    radius_6: Annotated[
        str, FieldMeta("Радиус 6", info="Скругление 6px — стандартные кнопки")
    ] = "6px"
    radius_md: Annotated[
        str, FieldMeta("Радиус md", info="Среднее скругление (8px) — карточки, панели")
    ] = "8px"
    radius_10: Annotated[
        str, FieldMeta("Радиус 10", info="Скругление 10px — groupbox, блоки контента")
    ] = "10px"
    radius_lg: Annotated[
        str, FieldMeta("Радиус lg", info="Крупное скругление (12px) — диалоги, модали")
    ] = "12px"
    radius_14: Annotated[
        str, FieldMeta("Радиус 14", info="Скругление 14px — крупные карточки")
    ] = "14px"
    radius_pill_sm: Annotated[
        str, FieldMeta("Радиус pill_sm", info="Малая таблетка (15px) — теги, chip-элементы")
    ] = "15px"
    radius_xl: Annotated[
        str, FieldMeta("Радиус xl", info="Большое скругление (16px) — боковые панели")
    ] = "16px"
    radius_pill: Annotated[
        str, FieldMeta("Радиус pill", info="Полная таблетка (21px) — переключатели, toggle")
    ] = "21px"


def get_default_variables() -> dict[str, str]:
    """Вернуть дефолтные значения всех переменных как плоский dict."""
    defaults = ThemeVariables()
    return {
        field_name: getattr(defaults, field_name)
        for field_name in ThemeVariables.model_fields
    }


__all__ = [
    "ThemeVariables",
    "THEME_VAR_TREE",
    "flatten_theme_var_tree",
    "THEME_VAR_DESCRIPTIONS",
    "get_default_variables",
]
