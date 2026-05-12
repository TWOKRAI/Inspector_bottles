"""ThemeVariables — регистр переменных темы оформления.

Содержит все CSS-переменные палитры: цвета, шрифты.
Группировка для UI задаётся через THEME_VAR_GROUPS (dict-маппинг).

Добавление новой переменной = одно поле + одна строка в THEME_VAR_GROUPS.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


# ---------------------------------------------------------------------------
# Группировка переменных для отображения в UI (двухуровневое дерево)
# ---------------------------------------------------------------------------
THEME_VAR_GROUPS: dict[str, list[str]] = {
    "Фон": ["bg_deep", "bg_mid", "bg_hi", "bg_hi2"],
    "Поверхности": ["surf_0", "surf_1", "surf_2", "surf_deep"],
    "Серебро": ["silver_hi", "silver", "silver_lo"],
    "Текст": ["text_0", "text_1", "text_2", "text_3"],
    "Акцент": ["accent", "accent_hi", "accent_lo", "accent_deep"],
    "Семантика": ["danger", "success", "warn"],
    "Шрифты": ["font_family", "font_family_mono"],
}

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
}


@register_schema("ThemeVariablesV3")
class ThemeVariables(SchemaBase):
    """Регистр переменных темы — цвета и шрифты.

    Все значения — строки: hex-цвета (#rrggbb) и названия шрифтов.
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


def get_default_variables() -> dict[str, str]:
    """Вернуть дефолтные значения всех переменных как плоский dict."""
    defaults = ThemeVariables()
    return {
        field_name: getattr(defaults, field_name)
        for field_name in ThemeVariables.model_fields
    }


__all__ = [
    "ThemeVariables",
    "THEME_VAR_GROUPS",
    "THEME_VAR_DESCRIPTIONS",
    "get_default_variables",
]
