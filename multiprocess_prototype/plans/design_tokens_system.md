# Plan: Design Tokens System — параметризация main.qss

**Дата:** 2026-05-12
**Статус:** DRAFT

## Обзор

Расширить ThemeVariables (22 переменных) полной системой design tokens: размерные шкалы (font-size, border-radius, spacing), компонентные цвета (кнопки, input'ы, tab'ы, scrollbar, danger, gradient stops), компонентные размеры и rgba-тени. После этого main.qss станет полностью параметризованным — каждое значимое значение будет подставляться через `@переменную`, и смена темы затронет всё визуальное оформление.

Редактор тем (ThemeEditorSection) полностью переделывается: вместо плоского QTreeWidget — SideNav (2-уровневое дерево) + QTableWidget + поиск.

**Обратная совместимость:** существующие 22 переменных (`bg_deep`...`font_family_mono`) НЕ трогаем — custom-темы пользователей продолжат работать. Новые переменные получают дефолтные значения, совпадающие с текущими хардкодами в main.qss.

## Инвентаризация хардкодов в main.qss (1006 строк)

### Хардкодные hex-цвета (не покрыты @var) — ~60 уникальных

**Gradient stops (промежуточные):**
- `#3e4552`, `#2a303b`, `#454c5a`, `#353b47`, `#252b37`, `#1e242e` — фоновые gradient stops
- `#3b414d`, `#333844` — pane/scroll area gradient
- `#383e4a`, `#4c5464` — card/groupbox gradient bottom
- `#4f5768` — tab selected bottom

**Кнопки (default):**
- `#6a7284`, `#4b5261`, `#3a4150` — normal gradient (top/mid/bottom)
- `#788092`, `#566075`, `#434a5a` — hover gradient
- Pressed = reversed normal

**Кнопки (primary) — производные от accent:**
- `#5ea3ff`, `#7ab3ff`, `#3d8cff`, `#2870e0` — primary hover/glow
- `#1a51ad`, `#133a82` — primary pressed

**Кнопки (danger):**
- `#b84050`, `#8a2d3d`, `#5f1f28` — normal
- `#c8505f`, `#9a3548`, `#6e2530` — hover

**Inputs:**
- `#1c2028`, `#262b34` — input bg gradient
- `#2e333d`, `#1e222a` — combo bg gradient
- `#2a2f39` — disabled bg
- `#232833` — alternate row

**Tabs:**
- `#4a5161`, `#363c49` — tab bg gradient
- `#5a6272`, `#434a58` — tab hover gradient

**Scrollbar:**
- `#1b1f27`, `#2a3040` — groove bg
- `#3d4e74`, `#9ab0d5` — handle gradient
- `#4a5b85`, `#abbfe0` — handle hover

**Slider handle (metallic):**
- `#ffffff`, `#d7e0ee`, `#7a8aa5` — normal
- `#e0e8f4`, `#8a9ab5` — hover
- `#e8eef8`, `#c0cce0`, `#6a7a95` — pressed

**Image slot:**
- `#14171d`, `#0a0c10` — dark slot bg

**Специфичные:**
- `#003087` — brand label color
- `#c0d4ff` — checkbox checked border, note text
- `#ff7894`, `#6ae0a8`, `#6aa8ff` — channel R/G/B labels
- `#d5e8fb`, `#000` — recipe slot selected
- `#333333` — watchdog overlay text
- `#FFF3CD`, `#856404`, `#FFE69C` — warning bar (yellow)
- `#1e1e1e` — pipeline graph bg
- `#1a1a2e` — display slot bg
- `#dc2626`, `#eab308` — error/warning banner borders
- `#2d5a2d`, `#1a5276` — slot occupied/selected bg

### rgba() — 25 уникальных паттернов

**Black opacity (border/shadow):** rgba(0,0,0, 0.10/0.15/0.25/0.35/0.4/0.45/0.5/0.55/0.6/0.65)
**White opacity (highlight):** rgba(255,255,255, 0.06/0.08/0.10/0.12/0.14/0.18/0.20/0.22)
**Accent opacity:** rgba(43,127,255, 0.05/0.15/0.25/0.35/0.55/0.75)
**Danger/warn opacity:** rgba(220,38,38, 0.15), rgba(234,179,8, 0.15), rgba(255,200,0, 180/255)

### font-size — 12 уникальных
9px, 10px, 11px, 12px, 13px, 14px, 15px, 16px, 17px, 20px, 22px, 28px

### border-radius — 11 уникальных
3px, 4px, 5px, 6px, 8px, 10px, 12px, 14px, 15px, 16px, 21px

---

## Проектирование системы токенов

### Уровень 1: Scale tokens (T-shirt размеры)

```python
# font-size шкала
font_xs: str = "9px"     # brand sub
font_sm: str = "11px"    # captions, hints, headers section
font_md: str = "13px"    # base (QWidget default)
font_lg: str = "15px"    # nav list, panel headers
font_xl: str = "17px"    # metric value, large tab header
font_xxl: str = "22px"   # pagination arrow
font_brand: str = "28px" # brand label

# border-radius шкала
radius_xs: str = "3px"   # checkbox, warning bar, inspector badge
radius_sm: str = "4px"   # tooltip, menu item, groupbox title, entity card
radius_md: str = "8px"   # inputs, combobox, diffscroll nav
radius_lg: str = "12px"  # groupbox, image slot, tab top, slider handle
radius_xl: str = "16px"  # ds-card
radius_pill: str = "21px"  # scrollbar, status pill (pill shape)

# spacing/padding (для компонентных размеров)
# НЕ добавляем как отдельные токены — padding задаётся через компонентные размеры
```

### Уровень 2: Компонентные цвета

```python
# --- Кнопки (default) ---
btn_grad_top: str = "#6a7284"
btn_grad_mid: str = "#4b5261"
btn_grad_bot: str = "#3a4150"
btn_hover_top: str = "#788092"
btn_hover_mid: str = "#566075"
btn_hover_bot: str = "#434a5a"

# --- Кнопки (primary) — производные от accent ---
btn_primary_top: str = "#5ea3ff"
btn_primary_hover_top: str = "#7ab3ff"
btn_primary_hover_mid: str = "#3d8cff"
btn_primary_hover_bot: str = "#2870e0"
btn_primary_pressed_mid: str = "#1a51ad"
btn_primary_pressed_bot: str = "#133a82"

# --- Кнопки (danger) ---
btn_danger_top: str = "#b84050"
btn_danger_mid: str = "#8a2d3d"
btn_danger_bot: str = "#5f1f28"
btn_danger_hover_top: str = "#c8505f"
btn_danger_hover_mid: str = "#9a3548"
btn_danger_hover_bot: str = "#6e2530"

# --- Inputs ---
input_bg_top: str = "#1c2028"
input_bg_bot: str = "#262b34"
input_combo_top: str = "#2e333d"
input_combo_bot: str = "#1e222a"
input_disabled_bg: str = "#2a2f39"
input_alt_row: str = "#232833"

# --- Tabs ---
tab_bg_top: str = "#4a5161"
tab_bg_bot: str = "#363c49"
tab_hover_top: str = "#5a6272"
tab_hover_bot: str = "#434a58"
tab_selected_top: str = "#6a7284"
tab_selected_bot: str = "#4f5768"
tab_pane_top: str = "#3b414d"
tab_pane_bot: str = "#333844"

# --- Scrollbar ---
scroll_groove_top: str = "#1b1f27"
scroll_groove_bot: str = "#2a3040"
scroll_handle_a: str = "#3d4e74"
scroll_handle_b: str = "#9ab0d5"
scroll_handle_hover_a: str = "#4a5b85"
scroll_handle_hover_b: str = "#abbfe0"

# --- Slider handle (metallic) ---
slider_knob_hi: str = "#d7e0ee"
slider_knob_lo: str = "#7a8aa5"
slider_knob_hover_hi: str = "#e0e8f4"
slider_knob_hover_lo: str = "#8a9ab5"
slider_knob_pressed_top: str = "#e8eef8"
slider_knob_pressed_hi: str = "#c0cce0"
slider_knob_pressed_lo: str = "#6a7a95"

# --- Gradient stops (фоновые промежуточные) ---
grad_main_mid: str = "#3e4552"
grad_main_bot: str = "#2a303b"
grad_header_mid: str = "#454c5a"
grad_header_bot: str = "#353b47"
grad_ticker_mid: str = "#252b37"
grad_ticker_bot: str = "#1e242e"
grad_groupbox_bot: str = "#383e4a"
grad_card_top: str = "#4c5464"

# --- Image slot ---
slot_bg_top: str = "#14171d"
slot_bg_bot: str = "#0a0c10"

# --- Brand ---
brand_color: str = "#003087"

# --- Accent light (derived) ---
accent_light: str = "#c0d4ff"

# --- Channel labels (R/G/B) ---
ch_red: str = "#ff7894"
ch_green: str = "#6ae0a8"
ch_blue: str = "#6aa8ff"

# --- Warning bar ---
warning_bar_bg: str = "#FFF3CD"
warning_bar_text: str = "#856404"
warning_bar_border: str = "#FFE69C"

# --- Pipeline graph ---
pipeline_graph_bg: str = "#1e1e1e"

# --- Display slot ---
display_slot_bg: str = "#1a1a2e"

# --- Error banner ---
error_banner_border: str = "#dc2626"
warning_banner_border: str = "#eab308"

# --- Slot states ---
slot_occupied_bg: str = "#2d5a2d"
slot_selected_bg: str = "#1a5276"

# --- Watchdog overlay ---
watchdog_text: str = "#333333"

# --- Recipe slot ---
recipe_selected_bg: str = "#d5e8fb"
```

### Уровень 3: rgba-токены (готовые строки)

```python
# --- Black overlays ---
shadow_xs: str = "rgba(0, 0, 0, 0.10)"
shadow_sm: str = "rgba(0, 0, 0, 0.15)"
shadow_md: str = "rgba(0, 0, 0, 0.25)"
shadow_lg: str = "rgba(0, 0, 0, 0.35)"
shadow_xl: str = "rgba(0, 0, 0, 0.40)"
shadow_2xl: str = "rgba(0, 0, 0, 0.45)"
shadow_3xl: str = "rgba(0, 0, 0, 0.50)"
shadow_4xl: str = "rgba(0, 0, 0, 0.55)"
shadow_5xl: str = "rgba(0, 0, 0, 0.60)"
shadow_6xl: str = "rgba(0, 0, 0, 0.65)"

# --- White highlights ---
glow_xs: str = "rgba(255, 255, 255, 0.06)"
glow_sm: str = "rgba(255, 255, 255, 0.08)"
glow_md: str = "rgba(255, 255, 255, 0.10)"
glow_lg: str = "rgba(255, 255, 255, 0.12)"
glow_xl: str = "rgba(255, 255, 255, 0.14)"
glow_2xl: str = "rgba(255, 255, 255, 0.18)"
glow_3xl: str = "rgba(255, 255, 255, 0.20)"
glow_4xl: str = "rgba(255, 255, 255, 0.22)"

# --- Accent overlays ---
accent_glass_xs: str = "rgba(43, 127, 255, 0.05)"
accent_glass_sm: str = "rgba(43, 127, 255, 0.15)"
accent_glass_md: str = "rgba(43, 127, 255, 0.25)"
accent_glass_lg: str = "rgba(43, 127, 255, 0.35)"
accent_glass_xl: str = "rgba(43, 127, 255, 0.55)"
accent_glass_2xl: str = "rgba(43, 127, 255, 0.75)"

# --- Semantic overlays ---
danger_glass: str = "rgba(220, 38, 38, 0.15)"
warn_glass: str = "rgba(234, 179, 8, 0.15)"
watchdog_overlay_bg: str = "rgba(255, 200, 0, 180)"
```

### Уровень 4: Компонентные размеры

```python
# --- Header ---
header_height: str = "60px"

# --- Buttons ---
btn_min_height: str = "22px"
btn_padding: str = "8px 20px"

# --- Inputs ---
input_min_height: str = "24px"
input_padding: str = "6px 12px"

# --- Scrollbar ---
scrollbar_width: str = "50px"
scrollbar_h_height: str = "42px"
```

### Итого новых переменных: ~105

Суммарно с существующими 22: ~127 переменных.

### Группировка для THEME_VAR_TREE (UI)

Вместо плоского `THEME_VAR_GROUPS: dict[str, list[str]]` — вложенная структура с двумя уровнями: категория -> подкатегория -> список переменных.

```python
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
        "Подсветки": ["glow_xs", "glow_sm", "glow_md", "glow_lg", "glow_xl",
                       "glow_2xl", "glow_3xl", "glow_4xl"],
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
        "Шапка": ["header_height", "brand_color", "grad_header_mid", "grad_header_bot"],
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
```

**Важно:** THEME_VAR_TREE полностью заменяет старый THEME_VAR_GROUPS. Каждая переменная — ровно в одном месте. Размерные токены (btn_min_height, scrollbar_width и т.д.) включены в соответствующие компонентные подкатегории, а не в отдельную группу.

Дополнительно создаётся helper-функция для совместимости:

```python
def flatten_theme_var_tree() -> dict[str, list[str]]:
    """THEME_VAR_TREE -> плоский dict (подкатегория -> vars) для обратной совместимости."""
    flat: dict[str, list[str]] = {}
    for _cat, subcats in THEME_VAR_TREE.items():
        for subcat_name, var_names in subcats.items():
            flat[subcat_name] = var_names
    return flat
```

---

## Порядок выполнения

### Фаза 1: Расширение ThemeVariables + variables.yaml

#### Task 1.1 — Scale tokens: font-size и border-radius

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить 23 scale-токена (12 font-size + 11 border-radius) в ThemeVariables и variables.yaml. Заменить THEME_VAR_GROUPS на THEME_VAR_TREE.
**Context:** Сейчас font-size и border-radius хардкодятся в main.qss (12+11 уникальных значений). T-shirt naming позволяет менять все размеры из одного места. Одновременно меняем структуру группировки с плоского dict на вложенный THEME_VAR_TREE для нового UI.
**Files:**
- `multiprocess_prototype/registers/theme/schemas.py` — добавить поля + ЗАМЕНИТЬ THEME_VAR_GROUPS на THEME_VAR_TREE + обновить THEME_VAR_DESCRIPTIONS + обновить `__all__`
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/variables.yaml` — добавить секции
- `multiprocess_prototype/registers/theme/__init__.py` — обновить экспорты

**Steps:**
1. В `schemas.py` после секции `# --- Шрифты ---` добавить секции:
   - `# --- Размеры шрифтов ---`: `font_xs`="9px", `font_2xs`="10px", `font_sm`="11px", `font_base`="12px", `font_md`="13px", `font_lg_sm`="14px", `font_lg`="15px", `font_xl_sm`="16px", `font_xl`="17px", `font_xxl_sm`="20px", `font_xxl`="22px", `font_brand`="28px" (12 полей)
   - `# --- Скругления ---`: `radius_xs`="3px", `radius_sm`="4px", `radius_5`="5px", `radius_6`="6px", `radius_md`="8px", `radius_10`="10px", `radius_lg`="12px", `radius_14`="14px", `radius_pill_sm`="15px", `radius_xl`="16px", `radius_pill`="21px" (11 полей)
2. **Заменить** `THEME_VAR_GROUPS: dict[str, list[str]]` на `THEME_VAR_TREE: dict[str, dict[str, list[str]]]` с категориями: "Глобальное" (10 подкат.), "Компоненты" (7 подкат.), "Окно" (4 подкат.), "Специальное" (4 подкат.). Полная структура — в секции "Группировка для THEME_VAR_TREE" выше.
   - Пока в THEME_VAR_TREE только существующие 22 + новые 23 переменных. Компонентные подкатегории (Кнопки, Поля ввода...) — пустые placeholder'ы с комментарием `# TODO: Task 1.2`.
3. Добавить helper `flatten_theme_var_tree() -> dict[str, list[str]]`.
4. В `THEME_VAR_DESCRIPTIONS` добавить описания для каждого нового поля.
5. В `variables.yaml` добавить секции с теми же дефолтными значениями.
6. В `__all__` заменить `"THEME_VAR_GROUPS"` на `"THEME_VAR_TREE"`, добавить `"flatten_theme_var_tree"`.
7. Обновить `multiprocess_prototype/registers/theme/__init__.py` — заменить экспорт `THEME_VAR_GROUPS` на `THEME_VAR_TREE` и `flatten_theme_var_tree`. Добавить обратную совместимость:
   ```python
   # Обратная совместимость
   THEME_VAR_GROUPS = flatten_theme_var_tree(THEME_VAR_TREE)
   ```

**Acceptance criteria:**
- [ ] `ThemeVariables().font_md == "13px"` и аналогично для всех 23 новых полей
- [ ] `get_default_variables()` возвращает dict с 45 ключами (22 + 23)
- [ ] `THEME_VAR_TREE` содержит 4 категории верхнего уровня
- [ ] `flatten_theme_var_tree()` возвращает плоский dict (подкатегория -> vars)
- [ ] `variables.yaml` содержит 45 ключей
- [ ] Существующие 22 переменных не изменены (ни имена, ни дефолты)

**Out of scope:** Замена хардкодов в main.qss (это Фаза 2). Компонентные цвета (Task 1.2). Обновление ThemeEditorSection (Фаза 3).
**Dependencies:** Нет

---

#### Task 1.2 — Компонентные цвета: кнопки, inputs, tabs, scrollbar

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить ~55 компонентных цветовых токенов в ThemeVariables и variables.yaml. Заполнить компонентные подкатегории в THEME_VAR_TREE.
**Context:** Каждый компонент (кнопка, input, tab, scrollbar, slider) имеет свой набор gradient stops, которые сейчас хардкодятся. Параметризация позволит менять облик компонентов из темы.
**Files:**
- `multiprocess_prototype/registers/theme/schemas.py` — добавить поля + заполнить подкатегории в THEME_VAR_TREE + THEME_VAR_DESCRIPTIONS
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/variables.yaml` — добавить секции

**Steps:**
1. Добавить секции полей в `ThemeVariables` в следующем порядке (после scale tokens из Task 1.1):
   - `# --- Кнопки (default) ---`: `btn_grad_top`, `btn_grad_mid`, `btn_grad_bot`, `btn_hover_top`, `btn_hover_mid`, `btn_hover_bot` (6 полей)
   - `# --- Кнопки (primary) ---`: `btn_primary_top`, `btn_primary_hover_top`, `btn_primary_hover_mid`, `btn_primary_hover_bot`, `btn_primary_pressed_mid`, `btn_primary_pressed_bot` (6 полей)
   - `# --- Кнопки (danger) ---`: `btn_danger_top`, `btn_danger_mid`, `btn_danger_bot`, `btn_danger_hover_top`, `btn_danger_hover_mid`, `btn_danger_hover_bot` (6 полей)
   - `# --- Поля ввода ---`: `input_bg_top`, `input_bg_bot`, `input_combo_top`, `input_combo_bot`, `input_disabled_bg`, `input_alt_row` (6 полей)
   - `# --- Вкладки ---`: `tab_bg_top`, `tab_bg_bot`, `tab_hover_top`, `tab_hover_bot`, `tab_selected_top`, `tab_selected_bot`, `tab_pane_top`, `tab_pane_bot` (8 полей)
   - `# --- Скроллбар ---`: `scroll_groove_top`, `scroll_groove_bot`, `scroll_handle_a`, `scroll_handle_b`, `scroll_handle_hover_a`, `scroll_handle_hover_b` (6 полей)
   - `# --- Слайдер ---`: `slider_knob_hi`, `slider_knob_lo`, `slider_knob_hover_hi`, `slider_knob_hover_lo`, `slider_knob_pressed_top`, `slider_knob_pressed_hi`, `slider_knob_pressed_lo` (7 полей)
   - `# --- Градиенты фона ---`: `grad_main_mid`, `grad_main_bot`, `grad_header_mid`, `grad_header_bot`, `grad_ticker_mid`, `grad_ticker_bot`, `grad_groupbox_bot`, `grad_card_top` (8 полей)
   - `# --- Слоты / карточки ---`: `slot_bg_top`, `slot_bg_bot`, `display_slot_bg`, `slot_occupied_bg`, `slot_selected_bg` (5 полей)
   - `# --- Бренд / каналы ---`: `brand_color`, `accent_light`, `ch_red`, `ch_green`, `ch_blue` (5 полей)
   - `# --- Предупреждения ---`: `warning_bar_bg`, `warning_bar_text`, `warning_bar_border`, `error_banner_border`, `warning_banner_border`, `watchdog_text` (6 полей)
   - `# --- Другое ---`: `pipeline_graph_bg`, `recipe_selected_bg` (2 поля) — итого ~71 поле
2. Дефолтное значение каждого поля = текущий хардкод из main.qss (точное hex-значение).
3. Заполнить компонентные подкатегории в THEME_VAR_TREE (Кнопки, Кнопки Accent, Кнопки Danger, Поля ввода, Скроллбар, Слайдер, Карточки, Шапка, Фон окна, Вкладки, GroupBox/Card, Каналы RGB, Оповещения, Pipeline, Watchdog).
4. Обновить `THEME_VAR_DESCRIPTIONS` — добавить описание для каждого нового поля (русский язык).
5. Продублировать все новые ключи в `variables.yaml` с теми же значениями.

**Acceptance criteria:**
- [ ] `ThemeVariables().btn_grad_top == "#6a7284"` и аналогично для всех новых полей
- [ ] `get_default_variables()` возвращает dict с ~116 ключами (45 из Task 1.1 + ~71)
- [ ] Каждый хардкодный hex из инвентаризации (кроме `#ffffff`, `#000`) покрыт переменной
- [ ] `variables.yaml` синхронизирован с `ThemeVariables` — те же ключи и значения
- [ ] Все компонентные подкатегории в THEME_VAR_TREE заполнены (нет пустых)

**Out of scope:** rgba-токены (Task 1.3). Замена хардкодов в main.qss (Фаза 2).
**Dependencies:** Task 1.1

---

#### Task 1.3 — rgba-токены и компонентные размеры

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить ~30 rgba-токенов (shadow/glow/glass) и ~7 компонентных размеров в ThemeVariables.
**Context:** rgba() значения в QSS нельзя параметризовать частично (подставить только opacity). Решение: каждый rgba подставляется целиком как готовая строка (`@shadow_md` -> `rgba(0, 0, 0, 0.45)`). re.sub `@(\w+)` заменит плейсхолдер на полную строку — это работает в QSS корректно.
**Files:**
- `multiprocess_prototype/registers/theme/schemas.py` — добавить поля + обновить THEME_VAR_TREE + THEME_VAR_DESCRIPTIONS
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/variables.yaml`

**Steps:**
1. Добавить секции в `ThemeVariables`:
   - `# --- Тени (чёрные) ---`: `shadow_xs`...`shadow_6xl` (10 полей, дефолты = `"rgba(0, 0, 0, 0.10)"`...`"rgba(0, 0, 0, 0.65)"`)
   - `# --- Подсветки (белые) ---`: `glow_xs`...`glow_4xl` (8 полей)
   - `# --- Акцент стекло ---`: `accent_glass_xs`...`accent_glass_2xl` (6 полей)
   - `# --- Семантика стекло ---`: `danger_glass`, `warn_glass`, `watchdog_overlay_bg` (3 поля)
   - `# --- Размеры компонентов ---`: `header_height`, `btn_min_height`, `btn_padding`, `input_min_height`, `input_padding`, `scrollbar_width`, `scrollbar_h_height` (7 полей)
2. Обновить THEME_VAR_TREE — добавить rgba-токены в соответствующие подкатегории (Тени, Подсветки, Акцент (стекло) — в "Глобальное"; danger_glass/warn_glass — в "Оповещения"; watchdog_overlay_bg — в "Watchdog"; размерные — в компонентные подкатегории).
3. Обновить `THEME_VAR_DESCRIPTIONS`.
4. Продублировать в `variables.yaml`.

**Acceptance criteria:**
- [ ] `ThemeVariables().shadow_3xl == "rgba(0, 0, 0, 0.50)"` и аналогично для всех
- [ ] `ThemeVariables().header_height == "60px"`
- [ ] `get_default_variables()` возвращает dict с ~140 ключами (итого)
- [ ] Значения rgba-токенов в yaml содержат кавычки: `shadow_xs: "rgba(0, 0, 0, 0.10)"`

**Out of scope:** Замена в main.qss (Фаза 2).
**Dependencies:** Task 1.2

---

### Фаза 2: Замена хардкодов в main.qss на @переменные

#### Task 2.1 — Замена font-size и border-radius на scale tokens

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить все хардкодные font-size и border-radius в main.qss на @font_* и @radius_* переменные.
**Context:** В main.qss 12 уникальных font-size (35 вхождений) и 11 уникальных border-radius (46 вхождений). Каждое значение маппится на ближайший T-shirt токен.
**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

**Steps:**
1. Заменить все `font-size: Npx` на `font-size: @font_*` по маппингу:
   9px=@font_xs, 10px=@font_2xs, 11px=@font_sm, 12px=@font_base, 13px=@font_md, 14px=@font_lg_sm, 15px=@font_lg, 16px=@font_xl_sm, 17px=@font_xl, 20px=@font_xxl_sm, 22px=@font_xxl, 28px=@font_brand
2. Заменить все `border-radius: Npx` на `@radius_*` по маппингу:
   3px=@radius_xs, 4px=@radius_sm, 5px=@radius_5, 6px=@radius_6, 8px=@radius_md, 10px=@radius_10, 12px=@radius_lg, 14px=@radius_14, 15px=@radius_pill_sm, 16px=@radius_xl, 21px=@radius_pill
3. НЕ менять `border-radius: 7px` в spinbox sub-controls (оставить литералом).
4. `border-top-left-radius: 12px` -> `@radius_lg`. `border-radius: 0 0 10px 10px` -> заменить `10px` на `@radius_10`.

**Acceptance criteria:**
- [ ] В main.qss нет литеральных `font-size: Npx` (кроме комментариев) — все через `@font_*`
- [ ] В main.qss нет литеральных `border-radius: Npx` (кроме `7px` в spinbox sub-controls) — все через `@radius_*`
- [ ] `load_theme("innotech_theme")` возвращает QSS без нерезолвенных `@font_*` / `@radius_*`
- [ ] Визуально приложение выглядит идентично (ручная проверка)

**Out of scope:** Замена цветов (Task 2.2). Замена rgba (Task 2.3).
**Edge cases:** `border-top-left-radius: 12px;` -> `@radius_lg`. `border-radius: 0 0 10px 10px` — shorthand, заменить `10px` на `@radius_10`.
**Dependencies:** Task 1.1

---

#### Task 2.2 — Замена компонентных hex-цветов на @переменные

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить все ~60 хардкодных hex-цветов в main.qss на @переменные из Task 1.2.
**Context:** Самая объёмная задача — ~100 точечных замен. Каждый hex-литерал маппится на конкретный компонентный токен. Критично не ошибиться в маппинге (stop-позиция gradient'а != другой компонент).
**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

**Steps:**
1. Пройти main.qss сверху вниз, секция за секцией. Для каждого хардкодного hex-цвета:
   - Определить к какому компоненту/состоянию он относится
   - Заменить на соответствующий `@токен`
2. Маппинг по секциям (полный список в инвентаризации выше). Ключевые:
   - `QPushButton` normal: `#6a7284`->`@btn_grad_top`, `#4b5261`->`@btn_grad_mid`, `#3a4150`->`@btn_grad_bot`
   - `QPushButton:hover`: `#788092`->`@btn_hover_top`, и т.д.
   - `QPushButton:pressed`: reversed normal (`#3a4150`->`@btn_grad_bot` в stop:0, `#6a7284`->`@btn_grad_top` в stop:1)
   - `QPushButton[role="primary"]`: `#5ea3ff`->`@btn_primary_top`, и т.д.
   - `QPushButton[role="danger"]`: `#b84050`->`@btn_danger_top`, и т.д.
   - Inputs: `#1c2028`->`@input_bg_top`, `#262b34`->`@input_bg_bot`
   - Tabs: `#4a5161`->`@tab_bg_top`, `#363c49`->`@tab_bg_bot`
   - Scrollbar: `#1b1f27`->`@scroll_groove_top`, и т.д.
   - `#ffffff` в `selection-color`, `color` кнопок — оставить литералом (белый = константа)
3. Для `#ffffff` в slider handle (`stop:0 #ffffff`) — **оставить литералом** (это физический белый, не тема).
4. Для `#000` в recipe selected — оставить литералом.

**Acceptance criteria:**
- [ ] В main.qss остались только hex-литералы: `#ffffff`, `#000`, `#000000` (и те что в комментариях)
- [ ] `load_theme("innotech_theme")` не содержит нерезолвенных `@btn_*`, `@input_*`, `@tab_*` и т.д.
- [ ] Визуально приложение выглядит идентично

**Out of scope:** rgba-замены (Task 2.3).
**Edge cases:** Один hex используется в нескольких компонентах — каждый маппится на СВОЙ компонентный токен (даже если значение совпадает). Однако если это один и тот же семантический смысл (градиент фона `grad_header_bot`), то использовать один токен.
**Dependencies:** Task 1.2

---

#### Task 2.3 — Замена rgba() на @shadow/@glow/@glass переменные

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить все ~29 вхождений rgba() в main.qss на @-переменные.
**Context:** re.sub `@(\w+)` заменит `@shadow_3xl` на `rgba(0, 0, 0, 0.50)` — Qt QSS парсит это корректно.
**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

**Steps:**
1. Заменить `rgba(0, 0, 0, X)` на `@shadow_*` по маппингу:
   0.10->@shadow_xs, 0.15->@shadow_sm, 0.25->@shadow_md, 0.35->@shadow_lg, 0.40->@shadow_xl, 0.45->@shadow_2xl, 0.50->@shadow_3xl, 0.55->@shadow_4xl, 0.60->@shadow_5xl, 0.65->@shadow_6xl
2. Заменить `rgba(255, 255, 255, X)` на `@glow_*`.
3. Заменить `rgba(43, 127, 255, X)` на `@accent_glass_*`.
4. Заменить `rgba(220, 38, 38, 0.15)` -> `@danger_glass`, `rgba(234, 179, 8, 0.15)` -> `@warn_glass`, `rgba(255, 200, 0, 180)` -> `@watchdog_overlay_bg`.
5. `stop:0 rgba(...)` -> `stop:0 @glow_sm` — Qt QSS это обрабатывает.

**Acceptance criteria:**
- [ ] В main.qss не осталось литеральных `rgba(` (кроме комментариев)
- [ ] `load_theme("innotech_theme")` содержит реальные rgba() (подставлены из переменных)
- [ ] Визуально приложение выглядит идентично

**Out of scope:** Нет.
**Edge cases:** `rgba(43, 127, 255, 0.55)` в `QComboBox:hover` — это `@accent_glass_xl`. Не путать с `@accent` (#2b7fff = тот же RGB без alpha).
**Dependencies:** Task 1.3

---

#### Task 2.4 — Замена компонентных размеров на @переменные

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить хардкодные размеры компонентов (header height, btn min-height, padding, scrollbar width) на @-переменные.
**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

**Steps:**
1. Заменить:
   - `min-height: 60px; max-height: 60px;` в `QWidget#AppHeader` -> `@header_height`
   - `min-height: 22px` в `QPushButton` -> `@btn_min_height`
   - `padding: 8px 20px` в `QPushButton` -> `@btn_padding`
   - `min-height: 24px` в `QComboBox` -> `@input_min_height`
   - `padding: 6px 12px` в `QLineEdit` и `QComboBox` -> `@input_padding`
   - `width: 50px` в `QScrollBar:vertical` -> `@scrollbar_width`
   - `height: 42px` в `QScrollBar:horizontal` -> `@scrollbar_h_height`
2. **НЕ** заменять `padding: 6px 28px 6px 12px` в QComboBox (4-значный padding).

**Acceptance criteria:**
- [ ] `load_theme()` не содержит нерезолвенных `@header_height`, `@btn_min_height` и т.д.

**Out of scope:** Padding с 4 значениями (оставляем литералами).
**Dependencies:** Task 1.3

---

### Фаза 3: Обновление UI и совместимость

#### Task 3.0 — TreeNavWidget: 2-уровневый навигационный виджет

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Создать переиспользуемый виджет TreeNavWidget — 2-уровневое QTreeWidget-дерево для навигации (замена плоского QListWidget из SideNavLayout для случаев с 2 уровнями).
**Context:** SideNavLayout использует QListWidget (1 уровень) — он не подходит для 2-уровневой навигации (категория -> подкатегория). Нужно создать новый примитив TreeNavWidget. SideNavLayout НЕ трогаем — он используется в ServicesTab и AdministrationSection.

**Files:**
- `multiprocess_prototype/frontend/widgets/primitives/tree_nav_widget.py` — создать
- `multiprocess_prototype/frontend/widgets/primitives/__init__.py` — добавить экспорт
- `multiprocess_prototype/frontend/widgets/primitives/tests/test_tree_nav_widget.py` — создать

**Steps:**
1. Создать класс `TreeNavWidget(QWidget)` с интерфейсом:
   ```python
   class TreeNavWidget(QWidget):
       leaf_selected = Signal(str, str)      # (category_key, subcategory_key)
       category_selected = Signal(str)       # category_key (клик на категорию верхнего уровня)

       def __init__(self, nav_width: int = 200, parent=None): ...
       def set_tree(self, tree: dict[str, list[str]]) -> None:
           """Загрузить дерево: {категория: [подкатегория, ...]}."""
       def filter(self, text: str) -> None:
           """Скрыть несовпадающие листы. Пустые категории — скрывать."""
       def clear_filter(self) -> None: ...
       def select(self, category: str, subcategory: str) -> None: ...
       def current_selection(self) -> tuple[str, str] | None: ...
   ```
2. Внутри — QTreeWidget с `setRootIsDecorated(True)`, `setHeaderHidden(True)`.
3. Категории — top-level items с флагом `ItemIsEnabled` (не селектабельны как листы).
4. Подкатегории — child items с флагами `ItemIsEnabled | ItemIsSelectable`.
5. Signal `currentItemChanged` -> проверить что выбранный item — лист (не категория) -> emit `leaf_selected`.
6. Клик на top-level item -> emit `category_selected`. Обработка через `itemClicked`: если `item.parent() is None` — это категория.
7. `filter(text)`: обход всех листов, `item.setHidden(text.lower() not in item.text(0).lower())`. После фильтрации: категория, у которой все дети скрыты -> скрыть и категорию. Категория с хотя бы одним видимым ребёнком -> развернуть.
8. Тесты (pytest-qt): создание, set_tree, выделение, фильтрация, сигнал.

**Acceptance criteria:**
- [ ] `TreeNavWidget` эмитит `leaf_selected("Компоненты", "Кнопки")` при клике на "Кнопки"
- [ ] `category_selected("Компоненты")` эмитится при клике на "Компоненты"
- [ ] `filter("кноп")` оставляет видимыми только подкатегории с "кноп" в названии
- [ ] Клик на категорию верхнего уровня — НЕ эмитит `leaf_selected` (она только сворачивается/разворачивается)
- [ ] Тесты: `pytest multiprocess_prototype/frontend/widgets/primitives/tests/test_tree_nav_widget.py -v`

**Out of scope:** Интеграция с ThemeEditorSection (Task 3.1). QSS-стилизация (используется общий QSS).
**Edge cases:** Пустое дерево (0 категорий). Дерево с пустой категорией (0 подкатегорий) — не отображать. Фильтр без совпадений — всё скрыто.
**Dependencies:** Нет (можно делать параллельно с Фазой 1-2)

---

#### Task 3.1 — Полная переделка ThemeEditorSection: SideNav + Table + Search

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Полностью переписать ThemeEditorSection: вместо плоского QTreeWidget с группами — TreeNavWidget (слева) + QTableWidget (справа) + QLineEdit (поиск).
**Context:** Текущий ThemeEditorSection использует QTreeWidget с группами и ~22 переменными. После расширения до ~140 переменных плоское дерево неуправляемо. Новая архитектура:

```
+------------------+------------------------------------------+
| Поиск...         |                                          |
+------------------+  Таблица параметров: "Кнопки"            |
|                  |                                          |
| > Глобальное     |  Имя            | Значение | Описание    |
|   Палитра        |  btn_grad_top   | #6a72    | Верх град.  |
|   Текст          |  btn_grad_mid   | #4b52    | Середина    |
|   ...            |  btn_grad_bot   | #3a41    | Низ град.   |
|                  |  ...                                     |
| > Компоненты     |                                          |
|   Кнопки       <-|                                          |
|   Кнопки Accent  |                                          |
|   ...            |                                          |
|                  |                                          |
| > Окно           |                                          |
|   Шапка          |                                          |
|   ...            |                                          |
+------------------+------------------------------------------+
```

**Ключевые требования:**
- TreeNavWidget (из Task 3.0) слева с 2-уровневым деревом из THEME_VAR_TREE
- QTableWidget справа с 4 колонками: Имя | Значение | Превью | Описание
- QLineEdit поиск сверху — фильтрует TreeNavWidget и таблицу одновременно
- Двойной клик на hex-значение -> QColorDialog
- Двойной клик на px/rgba значение -> inline редактирование (через EditTriggers)
- Превью колонка: цветной квадратик для hex-цветов, текст для px/rgba
- Клик на категорию верхнего уровня -> показать ВСЕ переменные всех вложенных подкатегорий

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/theme_editor_section.py` — полная переделка
- `multiprocess_prototype/registers/theme/schemas.py` — import THEME_VAR_TREE вместо THEME_VAR_GROUPS

**Steps:**
1. **Импорты:** заменить import `THEME_VAR_GROUPS` на `THEME_VAR_TREE` из schemas.py. Добавить import `TreeNavWidget` из primitives.
2. **Удалить** старый `_init_ui` блок с QTreeWidget. Создать новый layout:
   ```
   QVBoxLayout (весь виджет)
     +-- QGroupBox("Темы")
     |     +-- QTableWidget (таблица тем — БЕЗ ИЗМЕНЕНИЙ)
     +-- QGroupBox("Переменные темы")
           +-- QVBoxLayout
                 +-- QLineEdit (поиск) с setPlaceholderText("Поиск переменной...")
                 +-- QHBoxLayout
                       +-- TreeNavWidget (слева, фиксир. ширина 200px)
                       +-- QTableWidget (справа, stretch)
   ```
3. **TreeNavWidget настройка:** вызвать `set_tree()` с ключами из THEME_VAR_TREE: `{"Глобальное": ["Палитра", "Текст", ...], "Компоненты": ["Кнопки", ...], ...}`.
4. **Signal leaf_selected -> заполнить таблицу:** при выборе подкатегории:
   - Определить список переменных: `THEME_VAR_TREE[category][subcategory]`
   - Очистить QTableWidget
   - Заполнить строками: для каждой переменной:
     - Кол. 0 (Имя): var_name (read-only)
     - Кол. 1 (Значение): self._current_vars[var_name] (editable)
     - Кол. 2 (Превью): QWidget с цветным фоном для hex, текст для остальных
     - Кол. 3 (Описание): THEME_VAR_DESCRIPTIONS[var_name] (read-only)
5. **Signal category_selected -> показать все переменные категории:** собрать все переменные: `[var for subcat in THEME_VAR_TREE[category].values() for var in subcat]`. Заполнить таблицу.
6. **Превью цвета** — для hex-значений создать QLabel с `setAutoFillBackground(True)` и установкой цвета через `QPalette`:
   ```python
   palette = preview.palette()
   palette.setColor(QPalette.ColorRole.Window, QColor(value))
   preview.setPalette(palette)
   preview.setAutoFillBackground(True)
   ```
   НЕ использовать setStyleSheet для preview — это создаёт приоритетный конфликт с глобальным QSS и не масштабируется (50 строк = 50 inline стилей).
   Для не-hex значений (px, rgba) — показать текст значения в ячейке без превью.
7. **Редактирование значений:**
   - Установить `self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)` глобально
   - Подключить `self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)`
   - В `_on_cell_double_clicked`: если значение hex-цвет → открыть QColorDialog; иначе → `self._table.editItem(item)` для inline-редактирования
   - Это предотвращает race condition между inline-edit и QColorDialog при двойном клике на hex-ячейку
8. **Поиск (QLineEdit):** signal `textChanged` ->
   - Вызвать `self._tree_nav.filter(text)` для фильтрации навигации
   - Если таблица заполнена — фильтровать строки таблицы по имени/описанию
   - Если текст пустой — сбросить фильтр
9. **_collect_vars_from_tree() -> _collect_vars_from_table():** переписать — теперь собирать из QTableWidget (текущий набор) + из self._current_vars (остальные, которые не в таблице). Логика: пройти все строки таблицы, обновить self._current_vars[var_name] = value из кол. 1. Вернуть self._current_vars.
10. **Убрать зависимость от _update_tree_height():** QTableWidget + TreeNavWidget имеют свои скроллы. Виджет больше не нуждается в фиксации высоты дерева.
11. **Сохранить весь остальной код БЕЗ ИЗМЕНЕНИЙ:** _refresh_table, _load_theme, action_buttons, обработчики кнопок (_on_apply, _on_save, _on_add, _on_copy, _on_rename, _on_delete, _on_reset_defaults, _on_revert).
12. **Важно: перед переключением подкатегории** — собирать текущие значения из таблицы в self._current_vars, чтобы не терять несохранённые правки.

**Acceptance criteria:**
- [ ] UI отображает TreeNavWidget с 4 категориями и ~25 подкатегориями
- [ ] Клик на подкатегорию "Кнопки" -> таблица показывает 8 переменных (btn_grad_top...btn_padding)
- [ ] Клик на категорию "Компоненты" -> таблица показывает ВСЕ переменные всех подкатегорий (~50)
- [ ] Поиск "btn" -> TreeNavWidget фильтрует, таблица фильтрует
- [ ] Двойной клик на hex-значение в таблице -> QColorDialog
- [ ] Двойной клик на px-значение -> inline edit
- [ ] Превью колонка показывает цветной квадратик для hex
- [ ] _on_apply / _on_save / _on_revert работают корректно (собирают все ~140 переменных)
- [ ] Кнопки action-колонки работают как раньше

**Out of scope:** QSS-стилизация TreeNavWidget (используется общий QSS). Drag-n-drop переменных. Undo/redo.
**Edge cases:**
- Подкатегория без переменных (не должна быть — проверяется в THEME_VAR_TREE)
- Переменная не найдена в _current_vars (использовать дефолт из get_default_variables())
- Переключение подкатегорий при несохранённых изменениях в таблице — собирать перед переключением
**Dependencies:** Task 3.0, Tasks 1.1, 1.2, 1.3

---

#### Task 3.2 — Совместимость ThemePresetsManager с расширенной схемой

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Убедиться что ThemePresetsManager корректно обрабатывает custom-темы с неполным набором переменных (обратная совместимость).
**Context:** Пользовательские custom-темы (data/custom_themes/*.yaml) могут содержать только оригинальные 22 ключа. При загрузке через `ThemeVariables.model_validate(raw)` Pydantic заполнит недостающие поля дефолтами — это уже работает из коробки. Нужно только подтвердить тестами.
**Files:**
- `multiprocess_prototype/frontend/managers/theme_presets_manager.py` — **не менять** (только проверить)
- `multiprocess_prototype/frontend/tests/test_theme_presets_compat.py` — создать

**Steps:**
1. Написать тест: создать YAML с 22 оригинальными ключами, загрузить через `ThemePresetsManager.get_variables()`, проверить что все новые поля получили дефолтные значения.
2. Написать тест: сохранить через `save_custom()` полную ThemeVariables, проверить что YAML содержит все ~140 ключей.
3. Написать тест: загрузить ThemeVariables из YAML с неизвестными ключами — Pydantic должен их проигнорировать (SchemaBase обычно `model_config = ConfigDict(extra="ignore")`). Проверить что это так; если нет — добавить `model_config`.

**Acceptance criteria:**
- [ ] Тест старой custom-темы (22 ключа) -> загрузка без ошибок, новые поля = дефолты
- [ ] Тест полной custom-темы (~140 ключей) -> сохранение и загрузка round-trip
- [ ] Тест с лишними ключами -> нет ошибок

**Out of scope:** Миграция существующих custom-тем на диске (не нужна — Pydantic заполняет пропуски).
**Dependencies:** Tasks 1.1, 1.2, 1.3

---

### Фаза 4: Тесты

#### Task 4.1 — Тесты подстановки новых переменных

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Расширить test_theme_loader.py для проверки что все ~140 переменных резолвятся в load_theme().
**Files:**
- `multiprocess_prototype/frontend/tests/test_theme_loader.py`

**Steps:**
1. Обновить `test_load_theme_no_unresolved_variables` — он уже проверяет все ключи из variables.yaml. После расширения yaml он автоматически покроет новые ключи. **Убедиться** что тест проходит.
2. Добавить тест `test_all_schema_fields_in_yaml`: все поля `ThemeVariables.model_fields` присутствуют в `variables.yaml` (синхронизация).
3. Добавить тест `test_no_hardcoded_hex_in_resolved_qss`: после `load_theme()` подсчитать оставшиеся hex-литералы — допустимы только `#ffffff`, `#000`, `#000000` (и в комментариях). Остальные должны были прийти из переменных.
4. Добавить тест `test_no_literal_rgba_in_resolved_qss`: после `load_theme()` в не-комментарных строках не должно быть `rgba(` (все заменены на @-переменные, которые при подстановке дают rgba-строки).
   **Внимание:** этот тест проверяет QSS-шаблон (до подстановки) — в нём не должно быть литеральных rgba. В результате load_theme() rgba-строки БУДУТ (подставлены из переменных), поэтому тест на шаблон, а не на результат.
5. Добавить тест `test_scale_tokens_are_valid_css_values`: все `font_*` содержат `"Npx"`, все `radius_*` содержат `"Npx"`, все `shadow_*` / `glow_*` содержат `"rgba("`.

**Acceptance criteria:**
- [ ] Все тесты проходят: `pytest multiprocess_prototype/frontend/tests/test_theme_loader.py -v`
- [ ] Покрытие: синхронизация schema<->yaml, отсутствие хардкодов, валидность значений

**Out of scope:** UI-тесты (pytest-qt) для ThemeEditorSection (слишком хрупкие).
**Dependencies:** Tasks 2.1, 2.2, 2.3, 2.4

---

#### Task 4.2 — Тест обратной совместимости custom-тем

**Level:** Junior (Haiku, normal thinking)
**Assignee:** developer
**Goal:** Добавить в test_theme_presets_compat.py (из Task 3.2) параметризованный тест для всех 22 оригинальных переменных.
**Files:**
- `multiprocess_prototype/frontend/tests/test_theme_presets_compat.py`

**Steps:**
1. Параметризованный тест `@pytest.mark.parametrize("var_name", ORIGINAL_22)` — загрузить ThemeVariables с только 22 ключами, проверить `getattr(tv, var_name) == expected_value`.
2. Тест что `get_default_variables()` содержит все 22 оригинальных ключа с неизменёнными значениями.

**Acceptance criteria:**
- [ ] Все 22 оригинальных переменных имеют те же дефолтные значения что и до рефакторинга
- [ ] Тесты проходят

**Out of scope:** Нет.
**Dependencies:** Task 3.2

---

## Уточнение Task 1.1: финальный список scale tokens

По результатам анализа маппинга (Task 2.1) font-size шкала должна содержать **12** токенов (не 7):

```python
font_xs: str = "9px"       # brand sub
font_2xs: str = "10px"     # hint labels, metric key
font_sm: str = "11px"      # captions, section titles, permissions hint
font_base: str = "12px"    # mono labels, readonly hint, panel title, status pill
font_md: str = "13px"      # QWidget default, ch-value, placeholder, panel title lg
font_lg_sm: str = "14px"   # section title, inspector title, placeholder italic
font_lg: str = "15px"      # nav list, panel header
font_xl_sm: str = "16px"   # tab header, display slot label
font_xl: str = "17px"      # metric value, large tab header
font_xxl_sm: str = "20px"  # watchdog overlay
font_xxl: str = "22px"     # pagination arrow
font_brand: str = "28px"   # brand label
```

А border-radius шкала — **11** токенов:

```python
radius_xs: str = "3px"     # checkbox, warning bar, inspector badge
radius_sm: str = "4px"     # tooltip, menu item, groupbox title, entity card, slider groove
radius_5: str = "5px"      # progress chunk
radius_6: str = "6px"      # table, progress bar
radius_md: str = "8px"     # inputs, combobox, diffscroll nav, radio indicator
radius_10: str = "10px"    # btn, info ticker, note, tab pane bottom
radius_lg: str = "12px"    # groupbox, image slot, tab top corners, slider handle
radius_14: str = "14px"    # status pill
radius_pill_sm: str = "15px"  # scrollbar handle, viewmode switch
radius_xl: str = "16px"    # ds-card
radius_pill: str = "21px"  # scrollbar track
```

---

## Риски и ограничения

1. **Объём:** ~140 переменных + ~200 замен в main.qss — высок риск опечаток. Миттигация: тесты в Фазе 4 ловят нерезолвенные плейсхолдеры.
2. **rgba в gradient stops:** Qt QSS может по-разному обработать `stop:0 rgba(...)` vs `stop:0 #hex`. Нужна ручная проверка визуала после Task 2.3.
3. **TreeNavWidget — новый примитив:** нужно качественно спроектировать API, чтобы в будущем переиспользовать. Миттигация: Task 3.0 назначен teamlead'у (Senior).
4. **Переделка ThemeEditorSection — высокая сложность:** полная замена UI-слоя с сохранением всех обработчиков кнопок и логики save/load. Миттигация: Task 3.1 назначен teamlead'у (Senior+), чёткий список "что НЕ менять".
5. **Pydantic валидация:** SchemaBase может иметь strict mode — нужно проверить что строковые значения вроде "rgba(0, 0, 0, 0.50)" не вызывают ошибок.
6. **Обратная совместимость:** custom-темы с 22 ключами продолжат работать (Pydantic defaults). Но при `save_custom()` — перезапишутся со всеми ~140 ключами. Это ожидаемое поведение.
7. **SideNavLayout НЕ трогаем:** он используется в ServicesTab и AdministrationSection. Создаём отдельный TreeNavWidget.
8. **Синхронизация таблицы и навигации при поиске:** поиск должен фильтровать и TreeNavWidget, и таблицу. Если пользователь вводит текст когда таблица заполнена — строки таблицы тоже фильтруются. Это дополнительная сложность в Task 3.1.
9. **Потеря правок при переключении подкатегории:** при клике на другую подкатегорию текущие несохранённые значения из таблицы должны быть собраны в `_current_vars` перед очисткой таблицы. Миттигация: шаг 12 в Task 3.1 явно описывает это.
10. **Дублирование логики загрузки переменных.** `theme_loader._load_variables()` и `ThemeManager.read_default_variables()` делают одно и то же по-разному. `read_default_variables` фильтрует ключи по `if k in defaults` (строка 162-163 theme_manager.py), а `_load_variables` читает все ключи. Каноничный путь: `_load_variables` в `theme_loader.py`. Рекомендация на будущее: убрать `_load_variables`, починить `read_default_variables` (убрать фильтр), унифицировать. Не блокирует текущий план, но зафиксировать как техдолг.

---

## Инновации (Phase 5+ — после реализации текущего плана)

### Computed tokens
Вместо ручного задания `btn_hover_top = "#788092"` — функции `lighten(btn_bg, 10%)`, `darken()`, `alpha()`.
Сократит число "ручных" переменных с ~140 до ~40 базовых + вычисляемые.
Реализация: `resolve_computed_tokens(base_vars) -> all_vars` между загрузкой yaml и подстановкой в QSS.

### Token inheritance / theme layers
Слоистая архитектура: `dark_blue.yaml: _extends: innotech_theme, accent: "#0055ff"` — остальные 138 наследуются.
Уже частично есть (`_parent` в custom-темах) — расширить до inheritance переменных.

### Live preview
Debounced `app.setStyleSheet()` при изменении переменной в редакторе (QTimer 300ms).
`setStyleSheet` на 1000 строк QSS = ~50-100ms задержка — debounce обязателен.

### Palette generation
Material Design подход: 5-7 seed-цветов → полная палитра через HSL-арифметику.
Создание темы = выбор 5 цветов вместо 140.
