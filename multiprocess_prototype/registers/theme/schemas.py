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
        "Тени": ["shadow_xs", "shadow_sm", "shadow_md", "shadow_lg", "shadow_xl",
                  "shadow_2xl", "shadow_3xl", "shadow_4xl", "shadow_5xl", "shadow_6xl"],
        "Подсветки": ["glow_xs", "glow_sm", "glow_md", "glow_lg",
                       "glow_xl", "glow_2xl", "glow_3xl", "glow_4xl"],
        "Акцент (стекло)": ["accent_glass_xs", "accent_glass_sm", "accent_glass_md",
                              "accent_glass_lg", "accent_glass_xl", "accent_glass_2xl"],
    },
    "Компоненты": {
        "Кнопки": ["btn_grad_top", "btn_grad_mid", "btn_grad_bot",
                    "btn_hover_top", "btn_hover_mid", "btn_hover_bot",
                    "btn_min_height", "btn_padding"],
        "Кнопки Accent": ["btn_primary_top", "btn_primary_hover_top",
                           "btn_primary_hover_mid", "btn_primary_hover_bot",
                           "btn_primary_pressed_mid", "btn_primary_pressed_bot"],
        "Кнопки Danger": ["btn_danger_top", "btn_danger_mid", "btn_danger_bot",
                           "btn_danger_hover_top", "btn_danger_hover_mid", "btn_danger_hover_bot"],
        "Поля ввода": ["input_bg_top", "input_bg_bot", "input_combo_top", "input_combo_bot",
                       "input_disabled_bg", "input_alt_row",
                       "input_min_height", "input_padding"],
        "Скроллбар": ["scroll_groove_top", "scroll_groove_bot",
                      "scroll_handle_a", "scroll_handle_b",
                      "scroll_handle_hover_a", "scroll_handle_hover_b",
                      "scrollbar_width", "scrollbar_h_height"],
        "Слайдер": ["slider_knob_hi", "slider_knob_lo",
                    "slider_knob_hover_hi", "slider_knob_hover_lo",
                    "slider_knob_pressed_top", "slider_knob_pressed_hi", "slider_knob_pressed_lo"],
        "Карточки": ["slot_bg_top", "slot_bg_bot", "display_slot_bg",
                     "slot_occupied_bg", "slot_selected_bg",
                     "recipe_selected_bg"],
    },
    "Окно": {
        "Шапка": ["brand_color", "grad_header_mid", "grad_header_bot", "header_height"],
        "Фон окна": ["grad_main_mid", "grad_main_bot",
                     "grad_ticker_mid", "grad_ticker_bot"],
        "Вкладки": ["tab_bg_top", "tab_bg_bot", "tab_hover_top", "tab_hover_bot",
                    "tab_selected_top", "tab_selected_bot", "tab_pane_top", "tab_pane_bot"],
        "GroupBox / Card": ["grad_groupbox_bot", "grad_card_top", "accent_light"],
    },
    "Специальное": {
        "Каналы RGB": ["ch_red", "ch_green", "ch_blue"],
        "Оповещения": ["warning_bar_bg", "warning_bar_text", "warning_bar_border",
                       "error_banner_border", "warning_banner_border",
                       "danger_glass", "warn_glass"],
        "Pipeline": ["pipeline_graph_bg"],
        "Watchdog": ["watchdog_text", "watchdog_overlay_bg"],
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
    # --- Кнопки (default) ---
    "btn_grad_top": "Кнопка (default) — верх градиента",
    "btn_grad_mid": "Кнопка (default) — середина градиента",
    "btn_grad_bot": "Кнопка (default) — низ градиента",
    "btn_hover_top": "Кнопка (default) hover — верх градиента",
    "btn_hover_mid": "Кнопка (default) hover — середина градиента",
    "btn_hover_bot": "Кнопка (default) hover — низ градиента",
    # --- Кнопки (primary) ---
    "btn_primary_top": "Кнопка Accent — верх градиента",
    "btn_primary_hover_top": "Кнопка Accent hover — верх градиента",
    "btn_primary_hover_mid": "Кнопка Accent hover — середина градиента",
    "btn_primary_hover_bot": "Кнопка Accent hover — низ градиента",
    "btn_primary_pressed_mid": "Кнопка Accent нажата — середина градиента",
    "btn_primary_pressed_bot": "Кнопка Accent нажата — низ градиента",
    # --- Кнопки (danger) ---
    "btn_danger_top": "Кнопка Danger — верх градиента",
    "btn_danger_mid": "Кнопка Danger — середина градиента",
    "btn_danger_bot": "Кнопка Danger — низ градиента",
    "btn_danger_hover_top": "Кнопка Danger hover — верх градиента",
    "btn_danger_hover_mid": "Кнопка Danger hover — середина градиента",
    "btn_danger_hover_bot": "Кнопка Danger hover — низ градиента",
    # --- Поля ввода ---
    "input_bg_top": "Поле ввода — верх фона",
    "input_bg_bot": "Поле ввода — низ фона",
    "input_combo_top": "Комбобокс — верх фона",
    "input_combo_bot": "Комбобокс — низ фона",
    "input_disabled_bg": "Поле ввода — фон в отключённом состоянии",
    "input_alt_row": "Таблица/список — чередующийся фон строки",
    # --- Вкладки ---
    "tab_bg_top": "Вкладка — верх фона",
    "tab_bg_bot": "Вкладка — низ фона",
    "tab_hover_top": "Вкладка hover — верх фона",
    "tab_hover_bot": "Вкладка hover — низ фона",
    "tab_selected_top": "Вкладка выбранная — верх фона",
    "tab_selected_bot": "Вкладка выбранная — низ фона",
    "tab_pane_top": "Панель вкладок — верх фона",
    "tab_pane_bot": "Панель вкладок — низ фона",
    # --- Скроллбар ---
    "scroll_groove_top": "Скроллбар — желоб (верх)",
    "scroll_groove_bot": "Скроллбар — желоб (низ)",
    "scroll_handle_a": "Скроллбар — ручка (начало градиента)",
    "scroll_handle_b": "Скроллбар — ручка (конец градиента)",
    "scroll_handle_hover_a": "Скроллбар — ручка hover (начало градиента)",
    "scroll_handle_hover_b": "Скроллбар — ручка hover (конец градиента)",
    # --- Слайдер ---
    "slider_knob_hi": "Слайдер — ручка (светлый конец градиента)",
    "slider_knob_lo": "Слайдер — ручка (тёмный конец градиента)",
    "slider_knob_hover_hi": "Слайдер — ручка hover (светлый конец)",
    "slider_knob_hover_lo": "Слайдер — ручка hover (тёмный конец)",
    "slider_knob_pressed_top": "Слайдер — ручка нажата (верх)",
    "slider_knob_pressed_hi": "Слайдер — ручка нажата (светлый тон)",
    "slider_knob_pressed_lo": "Слайдер — ручка нажата (тёмный тон)",
    # --- Градиенты фона ---
    "grad_main_mid": "Основной фон окна — середина градиента",
    "grad_main_bot": "Основной фон окна — низ градиента",
    "grad_header_mid": "Шапка — середина градиента",
    "grad_header_bot": "Шапка — низ градиента",
    "grad_ticker_mid": "Тикер/нижняя панель — середина градиента",
    "grad_ticker_bot": "Тикер/нижняя панель — низ градиента",
    "grad_groupbox_bot": "GroupBox — низ градиента",
    "grad_card_top": "Карточка — верх градиента",
    # --- Слоты / карточки ---
    "slot_bg_top": "Слот — верх фона",
    "slot_bg_bot": "Слот — низ фона",
    "display_slot_bg": "Display-слот — фон",
    "slot_occupied_bg": "Слот занят — фон",
    "slot_selected_bg": "Слот выбран — фон",
    # --- Бренд / каналы ---
    "brand_color": "Брендовый цвет (синий корпоратив)",
    "accent_light": "Акцент светлый (GroupBox/Card)",
    "ch_red": "Канал R — цвет отображения",
    "ch_green": "Канал G — цвет отображения",
    "ch_blue": "Канал B — цвет отображения",
    # --- Предупреждения ---
    "warning_bar_bg": "Предупреждение — фон полосы",
    "warning_bar_text": "Предупреждение — цвет текста",
    "warning_bar_border": "Предупреждение — цвет рамки",
    "error_banner_border": "Баннер ошибки — цвет рамки",
    "warning_banner_border": "Баннер предупреждения — цвет рамки",
    "watchdog_text": "Watchdog — цвет текста",
    # --- Другое ---
    "pipeline_graph_bg": "Pipeline граф — фон рабочей области",
    "recipe_selected_bg": "Рецепт выбранный — фон строки",
    # --- Тени (чёрные rgba) ---
    "shadow_xs": "Тень xs — rgba(0,0,0, 10%)",
    "shadow_sm": "Тень sm — rgba(0,0,0, 15%)",
    "shadow_md": "Тень md — rgba(0,0,0, 25%)",
    "shadow_lg": "Тень lg — rgba(0,0,0, 35%)",
    "shadow_xl": "Тень xl — rgba(0,0,0, 40%)",
    "shadow_2xl": "Тень 2xl — rgba(0,0,0, 45%)",
    "shadow_3xl": "Тень 3xl — rgba(0,0,0, 50%)",
    "shadow_4xl": "Тень 4xl — rgba(0,0,0, 55%)",
    "shadow_5xl": "Тень 5xl — rgba(0,0,0, 60%)",
    "shadow_6xl": "Тень 6xl — rgba(0,0,0, 65%)",
    # --- Подсветки (белые rgba) ---
    "glow_xs": "Подсветка xs — rgba(255,255,255, 6%)",
    "glow_sm": "Подсветка sm — rgba(255,255,255, 8%)",
    "glow_md": "Подсветка md — rgba(255,255,255, 10%)",
    "glow_lg": "Подсветка lg — rgba(255,255,255, 12%)",
    "glow_xl": "Подсветка xl — rgba(255,255,255, 14%)",
    "glow_2xl": "Подсветка 2xl — rgba(255,255,255, 18%)",
    "glow_3xl": "Подсветка 3xl — rgba(255,255,255, 20%)",
    "glow_4xl": "Подсветка 4xl — rgba(255,255,255, 22%)",
    # --- Акцент (стекло rgba) ---
    "accent_glass_xs": "Акцент стекло xs — rgba(#2b7fff, 5%)",
    "accent_glass_sm": "Акцент стекло sm — rgba(#2b7fff, 15%)",
    "accent_glass_md": "Акцент стекло md — rgba(#2b7fff, 25%)",
    "accent_glass_lg": "Акцент стекло lg — rgba(#2b7fff, 35%)",
    "accent_glass_xl": "Акцент стекло xl — rgba(#2b7fff, 55%)",
    "accent_glass_2xl": "Акцент стекло 2xl — rgba(#2b7fff, 75%)",
    # --- Семантика (стекло rgba) ---
    "danger_glass": "Опасность стекло — rgba(danger, 15%)",
    "warn_glass": "Предупреждение стекло — rgba(warn, 15%)",
    "watchdog_overlay_bg": "Watchdog оверлей — полупрозрачный жёлтый фон",
    # --- Размеры компонентов ---
    "header_height": "Шапка — высота (60px)",
    "btn_min_height": "Кнопка — минимальная высота (22px)",
    "btn_padding": "Кнопка — внутренние отступы (8px 20px)",
    "input_min_height": "Поле ввода — минимальная высота (24px)",
    "input_padding": "Поле ввода — внутренние отступы (6px 12px)",
    "scrollbar_width": "Скроллбар вертикальный — ширина (50px)",
    "scrollbar_h_height": "Скроллбар горизонтальный — высота (42px)",
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

    # --- Кнопки (default) ---
    btn_grad_top: Annotated[
        str, FieldMeta("Кнопка верх", info="Кнопка (default) — верх градиента")
    ] = "#6a7284"
    btn_grad_mid: Annotated[
        str, FieldMeta("Кнопка середина", info="Кнопка (default) — середина градиента")
    ] = "#4b5261"
    btn_grad_bot: Annotated[
        str, FieldMeta("Кнопка низ", info="Кнопка (default) — низ градиента")
    ] = "#3a4150"
    btn_hover_top: Annotated[
        str, FieldMeta("Кнопка hover верх", info="Кнопка (default) hover — верх градиента")
    ] = "#788092"
    btn_hover_mid: Annotated[
        str, FieldMeta("Кнопка hover середина", info="Кнопка (default) hover — середина градиента")
    ] = "#566075"
    btn_hover_bot: Annotated[
        str, FieldMeta("Кнопка hover низ", info="Кнопка (default) hover — низ градиента")
    ] = "#434a5a"

    # --- Кнопки (primary / accent) ---
    btn_primary_top: Annotated[
        str, FieldMeta("Кнопка Accent верх", info="Кнопка Accent — верх градиента")
    ] = "#5ea3ff"
    btn_primary_hover_top: Annotated[
        str, FieldMeta("Кнопка Accent hover верх", info="Кнопка Accent hover — верх градиента")
    ] = "#7ab3ff"
    btn_primary_hover_mid: Annotated[
        str, FieldMeta("Кнопка Accent hover середина", info="Кнопка Accent hover — середина градиента")
    ] = "#3d8cff"
    btn_primary_hover_bot: Annotated[
        str, FieldMeta("Кнопка Accent hover низ", info="Кнопка Accent hover — низ градиента")
    ] = "#2870e0"
    btn_primary_pressed_mid: Annotated[
        str, FieldMeta("Кнопка Accent нажата середина", info="Кнопка Accent нажата — середина градиента")
    ] = "#1a51ad"
    btn_primary_pressed_bot: Annotated[
        str, FieldMeta("Кнопка Accent нажата низ", info="Кнопка Accent нажата — низ градиента")
    ] = "#133a82"

    # --- Кнопки (danger) ---
    btn_danger_top: Annotated[
        str, FieldMeta("Кнопка Danger верх", info="Кнопка Danger — верх градиента")
    ] = "#b84050"
    btn_danger_mid: Annotated[
        str, FieldMeta("Кнопка Danger середина", info="Кнопка Danger — середина градиента")
    ] = "#8a2d3d"
    btn_danger_bot: Annotated[
        str, FieldMeta("Кнопка Danger низ", info="Кнопка Danger — низ градиента")
    ] = "#5f1f28"
    btn_danger_hover_top: Annotated[
        str, FieldMeta("Кнопка Danger hover верх", info="Кнопка Danger hover — верх градиента")
    ] = "#c8505f"
    btn_danger_hover_mid: Annotated[
        str, FieldMeta("Кнопка Danger hover середина", info="Кнопка Danger hover — середина градиента")
    ] = "#9a3548"
    btn_danger_hover_bot: Annotated[
        str, FieldMeta("Кнопка Danger hover низ", info="Кнопка Danger hover — низ градиента")
    ] = "#6e2530"

    # --- Поля ввода ---
    input_bg_top: Annotated[
        str, FieldMeta("Ввод фон верх", info="Поле ввода — верх фона")
    ] = "#1c2028"
    input_bg_bot: Annotated[
        str, FieldMeta("Ввод фон низ", info="Поле ввода — низ фона")
    ] = "#262b34"
    input_combo_top: Annotated[
        str, FieldMeta("Комбобокс верх", info="Комбобокс — верх фона")
    ] = "#2e333d"
    input_combo_bot: Annotated[
        str, FieldMeta("Комбобокс низ", info="Комбобокс — низ фона")
    ] = "#1e222a"
    input_disabled_bg: Annotated[
        str, FieldMeta("Ввод отключён фон", info="Поле ввода — фон в отключённом состоянии")
    ] = "#2a2f39"
    input_alt_row: Annotated[
        str, FieldMeta("Чередующийся ряд", info="Таблица/список — чередующийся фон строки")
    ] = "#232833"

    # --- Вкладки ---
    tab_bg_top: Annotated[
        str, FieldMeta("Вкладка фон верх", info="Вкладка — верх фона")
    ] = "#4a5161"
    tab_bg_bot: Annotated[
        str, FieldMeta("Вкладка фон низ", info="Вкладка — низ фона")
    ] = "#363c49"
    tab_hover_top: Annotated[
        str, FieldMeta("Вкладка hover верх", info="Вкладка hover — верх фона")
    ] = "#5a6272"
    tab_hover_bot: Annotated[
        str, FieldMeta("Вкладка hover низ", info="Вкладка hover — низ фона")
    ] = "#434a58"
    tab_selected_top: Annotated[
        str, FieldMeta("Вкладка выбрана верх", info="Вкладка выбранная — верх фона")
    ] = "#6a7284"
    tab_selected_bot: Annotated[
        str, FieldMeta("Вкладка выбрана низ", info="Вкладка выбранная — низ фона")
    ] = "#4f5768"
    tab_pane_top: Annotated[
        str, FieldMeta("Панель вкладок верх", info="Панель вкладок — верх фона")
    ] = "#3b414d"
    tab_pane_bot: Annotated[
        str, FieldMeta("Панель вкладок низ", info="Панель вкладок — низ фона")
    ] = "#333844"

    # --- Скроллбар ---
    scroll_groove_top: Annotated[
        str, FieldMeta("Скроллбар желоб верх", info="Скроллбар — желоб (верх)")
    ] = "#1b1f27"
    scroll_groove_bot: Annotated[
        str, FieldMeta("Скроллбар желоб низ", info="Скроллбар — желоб (низ)")
    ] = "#2a3040"
    scroll_handle_a: Annotated[
        str, FieldMeta("Скроллбар ручка A", info="Скроллбар — ручка (начало градиента)")
    ] = "#3d4e74"
    scroll_handle_b: Annotated[
        str, FieldMeta("Скроллбар ручка B", info="Скроллбар — ручка (конец градиента)")
    ] = "#9ab0d5"
    scroll_handle_hover_a: Annotated[
        str, FieldMeta("Скроллбар ручка hover A", info="Скроллбар — ручка hover (начало градиента)")
    ] = "#4a5b85"
    scroll_handle_hover_b: Annotated[
        str, FieldMeta("Скроллбар ручка hover B", info="Скроллбар — ручка hover (конец градиента)")
    ] = "#abbfe0"

    # --- Слайдер ---
    slider_knob_hi: Annotated[
        str, FieldMeta("Слайдер ручка hi", info="Слайдер — ручка (светлый конец градиента)")
    ] = "#d7e0ee"
    slider_knob_lo: Annotated[
        str, FieldMeta("Слайдер ручка lo", info="Слайдер — ручка (тёмный конец градиента)")
    ] = "#7a8aa5"
    slider_knob_hover_hi: Annotated[
        str, FieldMeta("Слайдер ручка hover hi", info="Слайдер — ручка hover (светлый конец)")
    ] = "#e0e8f4"
    slider_knob_hover_lo: Annotated[
        str, FieldMeta("Слайдер ручка hover lo", info="Слайдер — ручка hover (тёмный конец)")
    ] = "#8a9ab5"
    slider_knob_pressed_top: Annotated[
        str, FieldMeta("Слайдер ручка нажата верх", info="Слайдер — ручка нажата (верх)")
    ] = "#e8eef8"
    slider_knob_pressed_hi: Annotated[
        str, FieldMeta("Слайдер ручка нажата hi", info="Слайдер — ручка нажата (светлый тон)")
    ] = "#c0cce0"
    slider_knob_pressed_lo: Annotated[
        str, FieldMeta("Слайдер ручка нажата lo", info="Слайдер — ручка нажата (тёмный тон)")
    ] = "#6a7a95"

    # --- Градиенты фона ---
    grad_main_mid: Annotated[
        str, FieldMeta("Фон окна середина", info="Основной фон окна — середина градиента")
    ] = "#3e4552"
    grad_main_bot: Annotated[
        str, FieldMeta("Фон окна низ", info="Основной фон окна — низ градиента")
    ] = "#2a303b"
    grad_header_mid: Annotated[
        str, FieldMeta("Шапка середина", info="Шапка — середина градиента")
    ] = "#454c5a"
    grad_header_bot: Annotated[
        str, FieldMeta("Шапка низ", info="Шапка — низ градиента")
    ] = "#353b47"
    grad_ticker_mid: Annotated[
        str, FieldMeta("Тикер середина", info="Тикер/нижняя панель — середина градиента")
    ] = "#252b37"
    grad_ticker_bot: Annotated[
        str, FieldMeta("Тикер низ", info="Тикер/нижняя панель — низ градиента")
    ] = "#1e242e"
    grad_groupbox_bot: Annotated[
        str, FieldMeta("GroupBox низ", info="GroupBox — низ градиента")
    ] = "#383e4a"
    grad_card_top: Annotated[
        str, FieldMeta("Карточка верх", info="Карточка — верх градиента")
    ] = "#4c5464"

    # --- Слоты / карточки ---
    slot_bg_top: Annotated[
        str, FieldMeta("Слот фон верх", info="Слот — верх фона")
    ] = "#14171d"
    slot_bg_bot: Annotated[
        str, FieldMeta("Слот фон низ", info="Слот — низ фона")
    ] = "#0a0c10"
    display_slot_bg: Annotated[
        str, FieldMeta("Display-слот фон", info="Display-слот — фон")
    ] = "#1a1a2e"
    slot_occupied_bg: Annotated[
        str, FieldMeta("Слот занят фон", info="Слот занят — фон")
    ] = "#2d5a2d"
    slot_selected_bg: Annotated[
        str, FieldMeta("Слот выбран фон", info="Слот выбран — фон")
    ] = "#1a5276"

    # --- Бренд / каналы ---
    brand_color: Annotated[
        str, FieldMeta("Брендовый цвет", info="Брендовый цвет (синий корпоратив)")
    ] = "#003087"
    accent_light: Annotated[
        str, FieldMeta("Акцент светлый", info="Акцент светлый (GroupBox/Card)")
    ] = "#c0d4ff"
    ch_red: Annotated[
        str, FieldMeta("Канал R", info="Канал R — цвет отображения")
    ] = "#ff7894"
    ch_green: Annotated[
        str, FieldMeta("Канал G", info="Канал G — цвет отображения")
    ] = "#6ae0a8"
    ch_blue: Annotated[
        str, FieldMeta("Канал B", info="Канал B — цвет отображения")
    ] = "#6aa8ff"

    # --- Предупреждения ---
    warning_bar_bg: Annotated[
        str, FieldMeta("Предупреждение фон", info="Предупреждение — фон полосы")
    ] = "#FFF3CD"
    warning_bar_text: Annotated[
        str, FieldMeta("Предупреждение текст", info="Предупреждение — цвет текста")
    ] = "#856404"
    warning_bar_border: Annotated[
        str, FieldMeta("Предупреждение рамка", info="Предупреждение — цвет рамки")
    ] = "#FFE69C"
    error_banner_border: Annotated[
        str, FieldMeta("Баннер ошибки рамка", info="Баннер ошибки — цвет рамки")
    ] = "#dc2626"
    warning_banner_border: Annotated[
        str, FieldMeta("Баннер предупреждения рамка", info="Баннер предупреждения — цвет рамки")
    ] = "#eab308"
    watchdog_text: Annotated[
        str, FieldMeta("Watchdog текст", info="Watchdog — цвет текста")
    ] = "#333333"

    # --- Другое ---
    pipeline_graph_bg: Annotated[
        str, FieldMeta("Pipeline граф фон", info="Pipeline граф — фон рабочей области")
    ] = "#1e1e1e"
    recipe_selected_bg: Annotated[
        str, FieldMeta("Рецепт выбран фон", info="Рецепт выбранный — фон строки")
    ] = "#d5e8fb"

    # --- Тени (чёрные rgba) ---
    shadow_xs: Annotated[
        str, FieldMeta("Тень xs", info="Тень xs — rgba(0,0,0, 10%)")
    ] = "rgba(0, 0, 0, 0.10)"
    shadow_sm: Annotated[
        str, FieldMeta("Тень sm", info="Тень sm — rgba(0,0,0, 15%)")
    ] = "rgba(0, 0, 0, 0.15)"
    shadow_md: Annotated[
        str, FieldMeta("Тень md", info="Тень md — rgba(0,0,0, 25%)")
    ] = "rgba(0, 0, 0, 0.25)"
    shadow_lg: Annotated[
        str, FieldMeta("Тень lg", info="Тень lg — rgba(0,0,0, 35%)")
    ] = "rgba(0, 0, 0, 0.35)"
    shadow_xl: Annotated[
        str, FieldMeta("Тень xl", info="Тень xl — rgba(0,0,0, 40%)")
    ] = "rgba(0, 0, 0, 0.40)"
    shadow_2xl: Annotated[
        str, FieldMeta("Тень 2xl", info="Тень 2xl — rgba(0,0,0, 45%)")
    ] = "rgba(0, 0, 0, 0.45)"
    shadow_3xl: Annotated[
        str, FieldMeta("Тень 3xl", info="Тень 3xl — rgba(0,0,0, 50%)")
    ] = "rgba(0, 0, 0, 0.50)"
    shadow_4xl: Annotated[
        str, FieldMeta("Тень 4xl", info="Тень 4xl — rgba(0,0,0, 55%)")
    ] = "rgba(0, 0, 0, 0.55)"
    shadow_5xl: Annotated[
        str, FieldMeta("Тень 5xl", info="Тень 5xl — rgba(0,0,0, 60%)")
    ] = "rgba(0, 0, 0, 0.60)"
    shadow_6xl: Annotated[
        str, FieldMeta("Тень 6xl", info="Тень 6xl — rgba(0,0,0, 65%)")
    ] = "rgba(0, 0, 0, 0.65)"

    # --- Подсветки (белые rgba) ---
    glow_xs: Annotated[
        str, FieldMeta("Подсветка xs", info="Подсветка xs — rgba(255,255,255, 6%)")
    ] = "rgba(255, 255, 255, 0.06)"
    glow_sm: Annotated[
        str, FieldMeta("Подсветка sm", info="Подсветка sm — rgba(255,255,255, 8%)")
    ] = "rgba(255, 255, 255, 0.08)"
    glow_md: Annotated[
        str, FieldMeta("Подсветка md", info="Подсветка md — rgba(255,255,255, 10%)")
    ] = "rgba(255, 255, 255, 0.10)"
    glow_lg: Annotated[
        str, FieldMeta("Подсветка lg", info="Подсветка lg — rgba(255,255,255, 12%)")
    ] = "rgba(255, 255, 255, 0.12)"
    glow_xl: Annotated[
        str, FieldMeta("Подсветка xl", info="Подсветка xl — rgba(255,255,255, 14%)")
    ] = "rgba(255, 255, 255, 0.14)"
    glow_2xl: Annotated[
        str, FieldMeta("Подсветка 2xl", info="Подсветка 2xl — rgba(255,255,255, 18%)")
    ] = "rgba(255, 255, 255, 0.18)"
    glow_3xl: Annotated[
        str, FieldMeta("Подсветка 3xl", info="Подсветка 3xl — rgba(255,255,255, 20%)")
    ] = "rgba(255, 255, 255, 0.20)"
    glow_4xl: Annotated[
        str, FieldMeta("Подсветка 4xl", info="Подсветка 4xl — rgba(255,255,255, 22%)")
    ] = "rgba(255, 255, 255, 0.22)"

    # --- Акцент (стекло rgba) ---
    accent_glass_xs: Annotated[
        str, FieldMeta("Акцент стекло xs", info="Акцент стекло xs — rgba(#2b7fff, 5%)")
    ] = "rgba(43, 127, 255, 0.05)"
    accent_glass_sm: Annotated[
        str, FieldMeta("Акцент стекло sm", info="Акцент стекло sm — rgba(#2b7fff, 15%)")
    ] = "rgba(43, 127, 255, 0.15)"
    accent_glass_md: Annotated[
        str, FieldMeta("Акцент стекло md", info="Акцент стекло md — rgba(#2b7fff, 25%)")
    ] = "rgba(43, 127, 255, 0.25)"
    accent_glass_lg: Annotated[
        str, FieldMeta("Акцент стекло lg", info="Акцент стекло lg — rgba(#2b7fff, 35%)")
    ] = "rgba(43, 127, 255, 0.35)"
    accent_glass_xl: Annotated[
        str, FieldMeta("Акцент стекло xl", info="Акцент стекло xl — rgba(#2b7fff, 55%)")
    ] = "rgba(43, 127, 255, 0.55)"
    accent_glass_2xl: Annotated[
        str, FieldMeta("Акцент стекло 2xl", info="Акцент стекло 2xl — rgba(#2b7fff, 75%)")
    ] = "rgba(43, 127, 255, 0.75)"

    # --- Семантика (стекло rgba) ---
    danger_glass: Annotated[
        str, FieldMeta("Опасность стекло", info="Опасность стекло — rgba(danger, 15%)")
    ] = "rgba(220, 38, 38, 0.15)"
    warn_glass: Annotated[
        str, FieldMeta("Предупреждение стекло", info="Предупреждение стекло — rgba(warn, 15%)")
    ] = "rgba(234, 179, 8, 0.15)"
    watchdog_overlay_bg: Annotated[
        str, FieldMeta("Watchdog оверлей фон", info="Watchdog оверлей — полупрозрачный жёлтый фон")
    ] = "rgba(255, 200, 0, 180)"

    # --- Размеры компонентов ---
    header_height: Annotated[
        str, FieldMeta("Высота шапки", info="Шапка — высота (60px)")
    ] = "60px"
    btn_min_height: Annotated[
        str, FieldMeta("Кнопка мин. высота", info="Кнопка — минимальная высота (22px)")
    ] = "22px"
    btn_padding: Annotated[
        str, FieldMeta("Кнопка отступы", info="Кнопка — внутренние отступы (8px 20px)")
    ] = "8px 20px"
    input_min_height: Annotated[
        str, FieldMeta("Поле ввода мин. высота", info="Поле ввода — минимальная высота (24px)")
    ] = "24px"
    input_padding: Annotated[
        str, FieldMeta("Поле ввода отступы", info="Поле ввода — внутренние отступы (6px 12px)")
    ] = "6px 12px"
    scrollbar_width: Annotated[
        str, FieldMeta("Скроллбар ширина", info="Скроллбар вертикальный — ширина (50px)")
    ] = "50px"
    scrollbar_h_height: Annotated[
        str, FieldMeta("Скроллбар горизонтальный высота", info="Скроллбар горизонтальный — высота (42px)")
    ] = "42px"


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
