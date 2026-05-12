# Plan: Рефакторинг inline setStyleSheet() -> централизованный QSS

**Дата:** 2026-05-12
**Статус:** DONE

## Обзор

Вынести ВСЕ вызовы `setStyleSheet()` с хардкодом стилей из ~25 Python-файлов frontend
в единый `main.qss`. В Python остаются только `setObjectName()` и/или `setProperty("role", "...")`.
Это устраняет дублирование цветов/размеров, делает тему полностью управляемой через QSS-файл
и позволяет менять оформление без правки Python-кода.

## Инвентарь inline стилей (27 файлов, ~50 вызовов)

### Категория A: Простые статические стили (objectName достаточно)

| # | Файл | Строка | Текущий inline стиль | Предлагаемый objectName / role |
|---|------|--------|----------------------|-------------------------------|
| A1 | `windows/main_window.py:193` | `color: orange; font-weight: bold;` | `#DirtyLabel` |
| A2 | `widgets/tabs/displays/tab.py:46` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A3 | `widgets/tabs/pipeline/tab.py:56` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A4 | `widgets/tabs/processes/tab.py:96` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A5 | `widgets/tabs/recipes/tab.py:71` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A6 | `widgets/tabs/plugins/tab.py:55` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A7 | `widgets/tabs/plugins/tab.py:73` | `color: #888; font-size: 14px;` | `#PlaceholderLabel` (уже есть в QSS) |
| A8 | `widgets/tabs/placeholder.py:32` | `color: #888; font-size: 14px;` | `#PlaceholderLabel` (уже есть в QSS) |
| A9 | `widgets/tabs/plugins/detail_panels.py:25` | `font-size: 16px; font-weight: bold;` | `#TabHeader` |
| A10 | `widgets/tabs/plugins/detail_panels.py:30` | `color: #aaa;` | `#MutedLabel` (уже есть — `@text_2`) |
| A11 | `widgets/tabs/settings/interface_section.py:53` | `color: #9ea6b2; font-size: 12px;` | `#HintLabelLg` (уже есть) |
| A12 | `widgets/tabs/settings/administration/dashboard.py:80` | `font-size: 14px; font-weight: bold;` | `#SectionTitle` (уже есть) |
| A13 | `widgets/tabs/settings/administration/dashboard.py:91` | `color: #9ea6b2; font-size: 11px;` | `#HintLabel` (уже ~совпадает; добавить в QSS точно) |
| A14 | `widgets/tabs/settings/administration/roles_panel.py:74` | `color: gray; font-size: 13px;` | `#PlaceholderLabel` |
| A15 | `widgets/tabs/settings/administration/roles_panel.py:83` | `font-weight: bold; font-size: 14px;` | `#SectionTitle` |
| A16 | `widgets/tabs/settings/administration/roles_panel.py:89` | `color: gray; font-size: 12px;` | `role="readonly-hint"` |
| A17 | `widgets/tabs/settings/administration/section.py:156` | `color: gray; font-size: 14px;` | `#PlaceholderLabel` |
| A18 | `widgets/tabs/services/tab.py:159` | `color: gray; font-size: 14px; font-style: italic;` | `role="placeholder-italic"` |
| A19 | `widgets/topology/editor.py:59` | `color: grey; font-size: 11px;` | `#StatusHint` |
| A20 | `widgets/tabs/settings/theme_editor_section.py:405` | `color: #1a1f25;` | `#ThemeDivider` |
| A21 | `widgets/tabs/pipeline/graph/graph_view.py:50` | `background-color: #1e1e1e;` | `#PipelineGraphView` |
| A22 | `widgets/primitives/diff_scroll_tab_layout.py:177` | `QScrollArea { background: transparent; border: none; }` | `#DiffScrollArea` (objectName уже ставится через `name` параметр — нужно QSS-правило) |

### Категория B: Компонентные стили (objectName на корневом виджете)

| # | Файл | Описание | Подход |
|---|------|----------|--------|
| B1 | `widgets/primitives/entity_card.py:52-53,66` | `_CARD_STYLE`: border/padding/margin на `EntityCard` | objectName `EntityCard` уже ставится (стр. 64). Удалить `_CARD_STYLE` + `setStyleSheet`, добавить `QFrame#EntityCard` правило в QSS |
| B2 | `widgets/primitives/entity_card.py:72` | `_title_label`: `font-weight: bold;` | `#EntityCardTitle` |
| B3 | `widgets/primitives/entity_card.py:138` | `key_label`: `color: #aaa;` | `#EntityCardKey` |
| B4 | `widgets/image_panel/display_slot.py:28-30` | `background-color: #1a1a2e; color: #aaa; font-size: 16px;` | `#DisplaySlotLabel` |
| B5 | `widgets/camera/view.py:24-26` | Аналогичный стиль | `#CameraViewLabel` |
| B6 | `forms/view_mode_toggle.py:23-43,74` | `_SWITCH_QSS`: многострочный iOS-тумблер | `#ViewModeSwitch` — перенести весь `_SWITCH_QSS` блок в QSS как `QCheckBox#ViewModeSwitch` + `::indicator` |

### Категория C: Динамические стили (property-based подход)

| # | Файл | Описание | Подход |
|---|------|----------|--------|
| C1 | `widgets/chrome/error_banner.py:121` | `_STYLE_ERROR` / `_STYLE_WARNING` — строки разного уровня | `setProperty("level", "error"|"warning")` + QSS `QWidget[level="error"]`, `QWidget[level="warning"]` на `#ErrorBannerRow` |
| C2 | `widgets/topology/validation_panel.py:60,63,70` | green/red по результату валидации | `setProperty("validation", "ok"|"error"|"")` + QSS на `#ValidationOutput` |
| C3 | `widgets/dialogs/login_dialog.py:80` | `color: #d32f2f;` для error_label | `#LoginErrorLabel` + QSS `{ color: @danger; }` |
| C4 | `widgets/dialogs/confirm_with_password.py:83` | `color: #d32f2f;` для error_label | `#ConfirmErrorLabel` + QSS `{ color: @danger; }` |
| C5 | `widgets/tabs/settings/administration/user_form.py:84` | `color: #d32f2f; font-size: 11px;` — password error | `#PasswordErrorLabel` + QSS |
| C6 | `widgets/tabs/settings/administration/user_form.py:123,140,147,154,162` | `border: 1px solid #d32f2f;` — validation border toggle | `setProperty("hasError", True/False)` + QSS `QLineEdit[hasError="true"]` + `style().unpolish()/polish()` |
| C7 | `widgets/tabs/settings/tab.py:561,566` | `border: 1px solid red;` / `""` — pydantic validation | Аналогично C6: `setProperty("hasError", ...)` |
| C8 | `widgets/primitives/slot_selector.py:14-24,51,74` | 3 состояния: empty/occupied/selected — стили кнопок | `setProperty("slotState", "empty"|"occupied"|"selected")` + QSS `QPushButton#SlotButton[slotState="..."]` + unpolish/polish |
| C9 | `widgets/tabs/pipeline/inspector/inspector_panel.py:67` | placeholder italic | `#InspectorPlaceholder` |
| C10 | `widgets/tabs/pipeline/inspector/inspector_panel.py:78` | title bold | `#InspectorTitle` |
| C11 | `widgets/tabs/pipeline/inspector/inspector_panel.py:83` | category badge base style | `#InspectorCategoryBadge` |
| C12 | `widgets/tabs/pipeline/inspector/inspector_panel.py:89` | divider `color: #555;` | `#InspectorDivider` |
| C13 | `widgets/tabs/pipeline/inspector/inspector_panel.py:137` | category badge dynamic `background-color: {color}` | `setProperty("category", category)` + QSS per-category или оставить `setStyleSheet` только для background-color (допустимо — динамический цвет из CATEGORY_COLORS) |
| C14 | `widgets/tabs/pipeline/inspector/inspector_panel.py:150` | plugin name label | `role="plugin-name"` |

### Специальный случай: `theme_loader.py:94`

`app.setStyleSheet(qss)` — это корректный вызов загрузки темы. **НЕ трогать.**

## Порядок выполнения

### Фаза 1: QSS-расширение (1 файл, ~120 строк QSS)

- Task 1.1: Добавить все новые правила в main.qss [DONE]

### Фаза 2: Статические стили (A1-A22, B1-B6) — ~20 файлов

- Task 2.1: Tab headers + placeholders (A2-A9, A14, A17) [DONE]
- Task 2.2: Admin dashboard + roles + section (A12-A16) [DONE]
- Task 2.3: Остальные статические (A1, A10, A11, A18-A22) [DONE]
- Task 2.4: Компонентные стили (B1-B6) [DONE]

### Фаза 3: Динамические стили (C1-C14) — ~8 файлов

- Task 3.1: Validation errors — property hasError (C6, C7) [DONE]
- Task 3.2: Error labels — objectName (C3, C4, C5) [DONE]
- Task 3.3: Error banner — property level (C1) [DONE]
- Task 3.4: Validation panel — property validation (C2) [DONE]
- Task 3.5: Slot selector — property slotState (C8) [DONE]
- Task 3.6: Inspector panel — static + dynamic category (C9-C14) [DONE]

### Фаза 4: Верификация

- Task 4.1: Grep-проверка + визуальный осмотр [DONE]

---

## Детальные спецификации задач

### Task 1.1 — Расширение main.qss новыми правилами

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить в main.qss все QSS-правила для замены inline стилей
**Context:** Файл уже содержит секцию «INLINE -> QSS» (строки 750-818). Все новые правила добавлять туда же. Использовать @-переменные из variables.yaml где цвет совпадает (например `#9ea6b2` = `@silver`, `#d32f2f` ≈ `@danger` и т.д.).

**Файлы:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss` — дописать правила

**Шаги:**

1. В секцию `/* ===================== INLINE → QSS */` добавить следующие блоки (порядок: сначала общие утилитарные, потом компонентные, потом динамические):

```
/* --- Tab headers (общий objectName для всех заголовков вкладок) --- */
QLabel#TabHeader {
    font-size: 16px;
    font-weight: bold;
}

/* --- Dirty indicator (statusbar) --- */
QLabel#DirtyLabel {
    color: @warn;
    font-weight: bold;
}

/* --- Topology --- */
QLabel#StatusHint {
    color: @text_3;
    font-size: 11px;
}

QWidget#PipelineGraphView {
    background-color: #1e1e1e;
}

QFrame#ThemeDivider {
    color: @bg_deep;
}

/* --- Readonly hint (roles panel, etc.) --- */
QLabel[role="readonly-hint"] {
    color: @text_3;
    font-size: 12px;
}

/* --- Placeholder italic (services tab, etc.) --- */
QLabel[role="placeholder-italic"] {
    color: @text_3;
    font-size: 14px;
    font-style: italic;
}

/* --- Permissions hint (admin dashboard) --- */
QLabel#PermissionsHint {
    color: @silver;
    font-size: 11px;
}

/* --- DiffScroll transparent ScrollArea --- */
QScrollArea#DiffScrollLeft,
QScrollArea#DiffScrollRight {
    background: transparent;
    border: none;
}

/* --- EntityCard --- */
QFrame#EntityCard {
    border: 1px solid @surf_1;
    border-radius: 4px;
    padding: 8px;
    margin: 2px;
}
QLabel#EntityCardTitle {
    font-weight: bold;
}
QLabel#EntityCardKey {
    color: @text_2;
}

/* --- Display slot / Camera view label --- */
QLabel#DisplaySlotLabel,
QLabel#CameraViewLabel {
    background-color: #1a1a2e;
    color: @text_2;
    font-size: 16px;
}

/* --- ViewModeToggle (iOS-switch) --- */
QCheckBox#ViewModeSwitch {
    spacing: 0px;
}
QCheckBox#ViewModeSwitch::indicator {
    width: 56px;
    height: 30px;
    border-radius: 15px;
    border: 1px solid rgba(0, 0, 0, 0.4);
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 @bg_hi, stop:1 @surf_0);
}
QCheckBox#ViewModeSwitch::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 @accent_hi, stop:1 @accent);
    border: 1px solid rgba(0, 0, 0, 0.3);
}
QCheckBox#ViewModeSwitch::indicator:hover {
    border: 1px solid rgba(255, 255, 255, 0.2);
}

/* --- Error banner rows --- */
QWidget#ErrorBannerRow[level="error"] {
    background: rgba(220, 38, 38, 0.15);
    border-left: 3px solid #dc2626;
    padding: 4px 8px;
}
QWidget#ErrorBannerRow[level="warning"] {
    background: rgba(234, 179, 8, 0.15);
    border-left: 3px solid #eab308;
    padding: 4px 8px;
}

/* --- Validation panel output --- */
QPlainTextEdit#ValidationOutput[validation="ok"] {
    color: @success;
}
QPlainTextEdit#ValidationOutput[validation="error"] {
    color: @danger;
}

/* --- Error labels (login, confirm, user_form) --- */
QLabel#LoginErrorLabel,
QLabel#ConfirmErrorLabel,
QLabel#PasswordErrorLabel {
    color: @danger;
}
QLabel#PasswordErrorLabel {
    font-size: 11px;
}

/* --- Validation error border (dynamic property) --- */
QLineEdit[hasError="true"],
QPlainTextEdit[hasError="true"],
QTextEdit[hasError="true"] {
    border: 1px solid @danger;
}

/* --- Slot selector states --- */
QPushButton#SlotButton[slotState="empty"] {
    background: @surf_0;
    color: @text_3;
    border: 1px solid @surf_1;
}
QPushButton#SlotButton[slotState="occupied"] {
    background: #2d5a2d;
    color: @text_1;
    border: 1px solid @success;
}
QPushButton#SlotButton[slotState="selected"] {
    background: #1a5276;
    color: @text_0;
    border: 2px solid @accent;
}

/* --- Inspector panel --- */
QLabel#InspectorPlaceholder {
    color: @text_3;
    font-style: italic;
    padding: 20px;
}
QLabel#InspectorTitle {
    font-size: 14px;
    font-weight: bold;
    color: @text_0;
}
QLabel#InspectorCategoryBadge {
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 3px;
}
QFrame#InspectorDivider {
    color: @surf_1;
}
QLabel[role="plugin-name"] {
    font-weight: bold;
    color: @text_1;
    margin-top: 4px;
}
```

2. **НЕ** трогать существующие правила в QSS.

**Acceptance criteria:**
- [ ] Все objectName/role из инвентаря (A1-A22, B1-B6, C1-C14) имеют соответствующее QSS-правило
- [ ] Все цвета, совпадающие с переменными из variables.yaml, заменены на @-плейсхолдеры
- [ ] Нет дубликатов с существующими правилами (проверить `#PlaceholderLabel`, `#SectionTitle`, `#MutedLabel`, `#HintLabel`, `#HintLabelLg`)

**Out of scope:** Не менять Python-файлы. Не менять существующие QSS-правила.
**Dependencies:** Нет

---

### Task 2.1 — Tab headers + placeholders (10 файлов)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить `setStyleSheet("font-size: 16px; font-weight: bold;")` и placeholder-стили на `setObjectName()`
**Context:** В QSS уже есть `#PlaceholderLabel` (стр. 771). Task 1.1 добавит `#TabHeader`.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/displays/tab.py` — строка 46
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — строка 56
- `multiprocess_prototype/frontend/widgets/tabs/processes/tab.py` — строка 96
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py` — строка 71
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — строки 55, 73
- `multiprocess_prototype/frontend/widgets/tabs/plugins/detail_panels.py` — строка 25
- `multiprocess_prototype/frontend/widgets/tabs/placeholder.py` — строка 32
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py` — строка 74
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/section.py` — строка 156

**Шаги:**

1. В каждом файле заменить `header.setStyleSheet("font-size: 16px; font-weight: bold;")` на `header.setObjectName("TabHeader")`
2. Для detail_panels.py строка 25: `name_label.setObjectName("TabHeader")` (аналогичный стиль)
3. Для placeholder-ов (`color: #888; font-size: 14px;`): заменить на `label.setObjectName("PlaceholderLabel")` — objectName `PlaceholderLabel` уже определён в QSS
4. Для roles_panel.py:74 (placeholder `color: gray; font-size: 13px;`): `placeholder.setObjectName("PlaceholderLabel")`
5. Для section.py:156 (`color: gray; font-size: 14px;`): `label.setObjectName("PlaceholderLabel")`

**Acceptance criteria:**
- [ ] Grep `setStyleSheet.*font-size: 16px.*font-weight: bold` в перечисленных файлах возвращает 0 результатов
- [ ] Grep `setStyleSheet.*color: #888` в перечисленных файлах возвращает 0 результатов
- [ ] Каждый виджет получил корректный `setObjectName`

**Out of scope:** Не менять логику виджетов. Не менять файлы не из списка.
**Dependencies:** Task 1.1

---

### Task 2.2 — Admin dashboard + roles (3 файла)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить inline стили в admin-панелях на objectName/property
**Context:** `#SectionTitle` (font-weight: bold; font-size: 14px) уже есть в QSS.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/dashboard.py` — строки 80, 91
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py` — строки 83, 89

**Шаги:**

1. `dashboard.py:80` — `self._lbl_user.setStyleSheet(...)` заменить на `self._lbl_user.setObjectName("SectionTitle")`
2. `dashboard.py:91` — `self._lbl_permissions.setStyleSheet(...)` заменить на `self._lbl_permissions.setObjectName("PermissionsHint")`
3. `roles_panel.py:83` — `title_label.setStyleSheet(...)` заменить на `title_label.setObjectName("SectionTitle")`
4. `roles_panel.py:89` — `readonly_label.setStyleSheet(...)` заменить на `readonly_label.setProperty("role", "readonly-hint")`

**Acceptance criteria:**
- [ ] Ноль `setStyleSheet` в dashboard.py и roles_panel.py
- [ ] Визуально: шрифт заголовков и цвет подсказок сохранились

**Out of scope:** Не менять roles_panel.py:74 (это Task 2.1).
**Dependencies:** Task 1.1

---

### Task 2.3 — Остальные статические стили (7 файлов)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Убрать оставшиеся статические inline стили

**Файлы:**
- `multiprocess_prototype/frontend/windows/main_window.py` — строка 193: `self._dirty_label.setObjectName("DirtyLabel")`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/detail_panels.py` — строка 30: `cat_label.setObjectName("MutedLabel")`
- `multiprocess_prototype/frontend/widgets/tabs/settings/interface_section.py` — строка 53: `desc.setObjectName("HintLabelLg")`
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — строка 159: `label.setProperty("role", "placeholder-italic")`
- `multiprocess_prototype/frontend/widgets/topology/editor.py` — строка 59: `self._status_label.setObjectName("StatusHint")`
- `multiprocess_prototype/frontend/widgets/tabs/settings/theme_editor_section.py` — строка 405: `line.setObjectName("ThemeDivider")` (вместо `setStyleSheet("color: #1a1f25;")`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_view.py` — строка 50: `self.setObjectName("PipelineGraphView")` (вместо `setStyleSheet("background-color: #1e1e1e;")`)
- `multiprocess_prototype/frontend/widgets/primitives/diff_scroll_tab_layout.py` — строка 177: удалить `sa.setStyleSheet(...)` — objectName уже ставится через параметр `name` (`DiffScrollLeft` / `DiffScrollRight`). QSS-правило из Task 1.1 подхватит.

**Шаги:**

1. Для каждого файла: удалить `setStyleSheet(...)`, добавить `setObjectName(...)` или `setProperty("role", ...)` как указано выше
2. `graph_view.py`: добавить `self.setObjectName("PipelineGraphView")` **перед** удалением `setStyleSheet`. Виджет наследует `QGraphicsView` — проверить, что `QWidget#PipelineGraphView` сработает (QGraphicsView — подкласс QWidget, QSS-селектор подхватит)
3. `diff_scroll_tab_layout.py`: проверить что objectName уже ставится через `sa.setObjectName(name)` на строке 171 — значит просто удалить `setStyleSheet` на строке 177

**Acceptance criteria:**
- [ ] Ноль `setStyleSheet` в перечисленных файлах (кроме theme_loader.py и main.qss-комментария)
- [ ] `PipelineGraphView` имеет objectName и получает фон из QSS

**Out of scope:** Не трогать `theme_loader.py:94` (`app.setStyleSheet(qss)` — это загрузка темы).
**Dependencies:** Task 1.1

---

### Task 2.4 — Компонентные стили (3 файла)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Перенести многострочные компонентные QSS-блоки в main.qss

**Файлы:**
- `multiprocess_prototype/frontend/widgets/primitives/entity_card.py` — строки 51-53, 66, 72, 138
- `multiprocess_prototype/frontend/widgets/image_panel/display_slot.py` — строки 28-30
- `multiprocess_prototype/frontend/widgets/camera/view.py` — строки 24-26
- `multiprocess_prototype/frontend/forms/view_mode_toggle.py` — строки 23-43, 74

**Шаги:**

1. **entity_card.py:**
   - Удалить `_CARD_STYLE` class variable (строки 51-54)
   - Удалить `self.setStyleSheet(self._CARD_STYLE)` (строка 66). objectName `EntityCard` уже ставится (строка 64) — QSS-правило `QFrame#EntityCard` из Task 1.1 подхватит
   - Строка 72: заменить `self._title_label.setStyleSheet("font-weight: bold;")` на `self._title_label.setObjectName("EntityCardTitle")`
   - Строка 138: заменить `key_label.setStyleSheet("color: #aaa;")` на `key_label.setObjectName("EntityCardKey")`

2. **display_slot.py:**
   - Строки 28-30: заменить `self._label.setStyleSheet(...)` на `self._label.setObjectName("DisplaySlotLabel")`

3. **camera/view.py:**
   - Строки 24-26: заменить `self._label.setStyleSheet(...)` на `self._label.setObjectName("CameraViewLabel")`

4. **view_mode_toggle.py:**
   - Удалить переменную `_SWITCH_QSS` (строки 23-43)
   - Строка 74: заменить `self._checkbox.setStyleSheet(_SWITCH_QSS)` на `self._checkbox.setObjectName("ViewModeSwitch")`

**Acceptance criteria:**
- [ ] `_CARD_STYLE` и `_SWITCH_QSS` переменные удалены из Python
- [ ] Ноль `setStyleSheet` в перечисленных файлах
- [ ] entity_card сохраняет визуальный вид (border, padding)
- [ ] Toggle-переключатель сохраняет iOS-стиль

**Edge cases:**
- `EntityCard` использует `setObjectName("EntityCard")` — уже задан; убедиться что QSS-селектор `QFrame#EntityCard` работает (EntityCard наследует QFrame)
- ViewModeSwitch: `QCheckBox#ViewModeSwitch::indicator` — QSS-subcontrol. Проверить что Qt применяет стили при наличии objectName на `QCheckBox` (а не на wrapper `QWidget`)

**Out of scope:** Не менять логику компонентов.
**Dependencies:** Task 1.1

---

### Task 3.1 — Validation error borders (2 файла)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить динамическое `setStyleSheet("border: 1px solid #d32f2f;")` / `setStyleSheet("")` на `setProperty("hasError", True/False)` + `style().unpolish()/polish()`
**Context:** Qt QSS не реагирует на изменение dynamic property без unpolish/polish. Это **критично** — без этого стиль не обновится.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/user_form.py` — строки 123, 140, 143, 147, 154, 162
- `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py` — строки 561, 566

**Шаги:**

1. **user_form.py** — создать вспомогательный метод `_set_error(widget, has_error: bool)`:
   ```python
   def _set_error(self, widget: QWidget, has_error: bool) -> None:
       widget.setProperty("hasError", has_error)
       widget.style().unpolish(widget)
       widget.style().polish(widget)
   ```
2. Заменить все `widget.setStyleSheet("border: 1px solid #d32f2f;")` на `self._set_error(widget, True)`
3. Заменить все `widget.setStyleSheet("")` на `self._set_error(widget, False)`
4. **tab.py** — аналогично: `editor.widget.setProperty("hasError", True)` + unpolish/polish, и `setProperty("hasError", False)` + unpolish/polish для сброса. Также убрать `editor.widget.setStyleSheet("")` на строке 566.

**Acceptance criteria:**
- [ ] Ноль `setStyleSheet` в user_form.py и в строках 555-567 tab.py
- [ ] При вводе невалидных данных border становится красным
- [ ] При исправлении — border возвращается к нормальному

**Edge cases:**
- `style().unpolish(widget)` + `style().polish(widget)` обязательны после `setProperty` — иначе Qt не пересчитает QSS
- В tab.py также очищается `toolTip` — это оставить как есть

**Dependencies:** Task 1.1

---

### Task 3.2 — Error labels (3 файла)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить `setStyleSheet("color: #d32f2f;")` на objectName для error labels
**Context:** objectName уже ставится в login_dialog.py и confirm_with_password.py (LoginErrorLabel, ConfirmErrorLabel). Нужно только убрать setStyleSheet.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py` — строка 80
- `multiprocess_prototype/frontend/widgets/dialogs/confirm_with_password.py` — строка 83
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/user_form.py` — строка 84

**Шаги:**

1. `login_dialog.py:80` — удалить `self._error_label.setStyleSheet("color: #d32f2f;")`. objectName `LoginErrorLabel` уже установлен на строке 79. QSS-правило из Task 1.1 подхватит.
2. `confirm_with_password.py:83` — удалить `self._error_label.setStyleSheet("color: #d32f2f;")`. objectName `ConfirmErrorLabel` уже установлен на строке 82.
3. `user_form.py:84` — заменить `self._password_error_label.setStyleSheet("color: #d32f2f; font-size: 11px;")` на `self._password_error_label.setObjectName("PasswordErrorLabel")`

**Acceptance criteria:**
- [ ] Ноль `setStyleSheet.*d32f2f` в перечисленных файлах (кроме user_form.py строки, обрабатываемые в Task 3.1)
- [ ] Error labels отображаются красным цветом (@danger)

**Out of scope:** Не трогать user_form.py border-стили (это Task 3.1).
**Dependencies:** Task 1.1

---

### Task 3.3 — Error banner dynamic styles (1 файл)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить inline стили error/warning строк на property-based QSS
**Context:** `error_banner.py` создаёт строки динамически в `_add_row()`. Каждая строка — `QWidget` с одним из двух стилей. Подход: `setObjectName("ErrorBannerRow")` + `setProperty("level", "error"|"warning")`.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/chrome/error_banner.py` — строки 17-27, 120-121

**Шаги:**

1. Удалить константы `_STYLE_ERROR` и `_STYLE_WARNING` (строки 17-27)
2. В методе `_add_row()`:
   - Убрать строку `row_widget.setStyleSheet(style)` (строка 121)
   - Добавить: `row_widget.setObjectName("ErrorBannerRow")`
   - Добавить: `row_widget.setProperty("level", level)`  (level уже приходит как `"error"` или `"warning"`)
   - Для корректного фона у кастомного QWidget: `row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)`
3. Убрать неиспользуемые переменные `style` и `icon_text` из начала `_add_row` — нет, `icon_text` ещё используется для `icon_label`. Убрать только строку `style = _STYLE_ERROR if level == "error" else _STYLE_WARNING`.
4. Добавить импорт `Qt` если отсутствует (для `WA_StyledBackground`)

**Acceptance criteria:**
- [ ] `_STYLE_ERROR` и `_STYLE_WARNING` удалены из Python
- [ ] `setStyleSheet` не вызывается в error_banner.py
- [ ] Error строки показывают красный фон, warning — жёлтый

**Edge cases:**
- `WA_StyledBackground` обязателен для QWidget — без него `background` из QSS не применится
- `setProperty("level", ...)` не требует unpolish/polish при создании виджета (стиль применяется при первом показе)

**Dependencies:** Task 1.1

---

### Task 3.4 — Validation panel (1 файл)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Заменить динамические color green/red на property-based QSS
**Context:** `validation_panel.py` переключает цвет `QPlainTextEdit` между green, red и default.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/topology/validation_panel.py` — строки 60, 63, 70

**Шаги:**

1. Добавить objectName для `self._output`: `self._output.setObjectName("ValidationOutput")` — в `__init__` (при создании виджета)
2. Создать вспомогательный метод:
   ```python
   def _set_validation_state(self, state: str) -> None:
       self._output.setProperty("validation", state)
       self._output.style().unpolish(self._output)
       self._output.style().polish(self._output)
   ```
3. Строка 60: заменить `self._output.setStyleSheet("color: green;")` на `self._set_validation_state("ok")`
4. Строка 63: заменить `self._output.setStyleSheet("color: red;")` на `self._set_validation_state("error")`
5. Строка 70: заменить `self._output.setStyleSheet("")` на `self._set_validation_state("")`

**Acceptance criteria:**
- [ ] Ноль `setStyleSheet` в validation_panel.py
- [ ] OK = зелёный текст, ошибки = красный текст, clear = дефолтный цвет

**Dependencies:** Task 1.1

---

### Task 3.5 — Slot selector (1 файл)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить словарь `_STYLES` на property-based QSS
**Context:** `slot_selector.py` имеет 3 состояния кнопок: empty, occupied, selected. Каждая кнопка меняет стиль динамически.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/primitives/slot_selector.py` — строки 14-24, 51, 74

**Шаги:**

1. Удалить словарь `_STYLES` (строки 14-24)
2. В `__init__`, при создании кнопок (строка 49-51):
   - Заменить `btn.setStyleSheet(_STYLES["empty"])` на:
     ```python
     btn.setObjectName("SlotButton")
     btn.setProperty("slotState", "empty")
     ```
3. В `set_slot_state()` (строки 73-74):
   - Заменить `self._buttons[index].setStyleSheet(style)` на:
     ```python
     btn = self._buttons[index]
     btn.setProperty("slotState", state)
     btn.style().unpolish(btn)
     btn.style().polish(btn)
     ```
   - Удалить строку `style = _STYLES.get(state, _STYLES["empty"])` (строка 73)

**Acceptance criteria:**
- [ ] `_STYLES` словарь удалён
- [ ] Ноль `setStyleSheet` в slot_selector.py
- [ ] Кнопки корректно меняют вид при смене состояния (empty → occupied → selected)

**Edge cases:**
- unpolish/polish обязателен при каждом `setProperty` изменении — иначе стиль не пересчитается
- Невалидный state (не из 3-х) — QSS не применит ни одно правило, кнопка получит дефолтный стиль QPushButton — допустимый fallback

**Dependencies:** Task 1.1

---

### Task 3.6 — Inspector panel (1 файл)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Перенести статические стили inspector panel в QSS, обработать динамический category badge
**Context:** `inspector_panel.py` имеет ~7 inline стилей. Большинство статические, но category badge меняет background-color динамически на основе `CATEGORY_COLORS`. Для category badge применяем гибридный подход: базовый стиль в QSS, динамический background-color остаётся через setStyleSheet (единственное допустимое исключение — цвет приходит из runtime данных).

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` — строки 67, 78, 83, 89, 137, 150

**Шаги:**

1. Строка 67 — placeholder: заменить `setStyleSheet(...)` на `self._placeholder.setObjectName("InspectorPlaceholder")`
2. Строка 78 — title: заменить `setStyleSheet(...)` на `self._title.setObjectName("InspectorTitle")`
3. Строка 83 — category badge base: заменить `setStyleSheet(...)` на `self._category_badge.setObjectName("InspectorCategoryBadge")`
4. Строка 89 — divider: заменить `setStyleSheet("color: #555;")` на `line.setObjectName("InspectorDivider")`
5. Строка 137 — **динамический category badge**: оставить `setStyleSheet` **только для** `background-color` и `color`:
   ```python
   self._category_badge.setStyleSheet(
       f"background-color: {color}; color: #fff;"
   )
   ```
   Это единственное допустимое исключение — цвет зависит от runtime-данных (CATEGORY_COLORS dict).
   **Альтернатива (опционально):** если категорий фиксированный набор (7 шт.), можно добавить в QSS правила `QLabel#InspectorCategoryBadge[category="source"]` и т.д., и в Python делать `setProperty("category", category)` + unpolish/polish. Выбор за исполнителем, но property-подход предпочтительнее.
6. Строка 150 — plugin name label: заменить `setStyleSheet(...)` на `label.setProperty("role", "plugin-name")`

**Acceptance criteria:**
- [ ] 6 из 7 inline стилей убраны (или все 7, если применён property-подход для category badge)
- [ ] Inspector panel визуально сохраняет вид
- [ ] Минимум: `setStyleSheet` остаётся только на строке 137 (или ноль, если property-подход)

**Edge cases:**
- При property-подходе для categories: если появится новая категория, нужно добавить QSS-правило. Поэтому если категории часто меняются — `setStyleSheet` допустим.

**Dependencies:** Task 1.1

---

### Task 4.1 — Верификация: grep + визуальный осмотр

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Убедиться что ноль inline стилей осталось (кроме theme_loader и допустимого исключения inspector category badge)
**Context:** Финальная проверка после всех задач.

**Файлы:** Все файлы frontend

**Шаги:**

1. Выполнить: `grep -rn "setStyleSheet" multiprocess_prototype/frontend/` 
2. Допустимые результаты:
   - `styles/theme_loader.py` — `app.setStyleSheet(qss)` (загрузка темы)
   - `main.qss` — комментарий с примером `app.setStyleSheet(qss)`
   - `inspector_panel.py` — строка 137 (если НЕ применён property-подход)
3. Все остальные вхождения — баг, нужно исправить
4. Визуально проверить ключевые экраны: tab headers, entity cards, toggle, error banner, validation panel, slot selector, inspector panel

**Acceptance criteria:**
- [ ] `grep setStyleSheet` возвращает ≤3 результата (все допустимые)
- [ ] Визуально: все виджеты сохранили свой вид

**Dependencies:** Tasks 2.1-2.4, 3.1-3.6

---

## Фаза 5: Python font/size → QSS (где возможно)

Вынести `setFont()` / `setBold()` / `setPointSize()` на label-заголовках в QSS.
`setFixedWidth()` на кнопках — тоже в QSS через `min-width`/`max-width`.

### Что переносится

| # | Файл | Строки | Текущий код | QSS-замена |
|---|------|--------|-------------|------------|
| F1 | `audit_log_panel.py` | 86-90 | `font.setBold(True); font.setPointSize(+2); header_label.setFont(font)` | objectName `PanelHeader` → `font-weight: bold; font-size: 15px;` |
| F2 | `sessions_panel.py` | 77-79 | то же | objectName `PanelHeader` |
| F3 | `users_panel.py` | 79-81 | то же | objectName `PanelHeader` |
| F4 | `services/tab.py` | 77-79 | `font.setPointSize(+4); font.setBold(True)` | objectName `TabHeaderLg` → `font-weight: bold; font-size: 17px;` |
| F5 | `confirm_with_password.py` | 66-67 | `font.setBold(True); _action_label.setFont(_font)` | objectName `ConfirmActionLabel` → `font-weight: bold;` |
| F6 | `audit_log_panel.py` | 167,176 | `setFixedWidth(50)` на кнопках пагинации | `QPushButton#PaginationArrow { min-width: 50px; max-width: 50px; }` |
| F7 | `main_window.py` | 154 | `self._tab_widget.setFont(_tab_font)` | `QTabBar { font-size: Xpx; font-weight: bold; }` (если шрифт отличается от базового) |

### Что НЕ переносится (структурное / не-QSS-таргетируемое)

| Файл | Причина |
|------|---------|
| `side_nav_layout.py` — `setFixedWidth(nav_width)` | Структурный layout constraint |
| `node_item.py` — `QGraphicsTextItem.setFont()` | QGraphicsScene — QSS не применяется |
| `form_builder.py`, `register_view.py` — `QTableWidgetItem.setFont()` | QSS не таргетирует отдельные items |
| `processes/tab.py` — `QTreeWidgetItem.setFont()` | Аналогично |
| Все `setMinimumWidth/Height` на диалогах и input-ах | Структурные размеры, не оформление |
| `diff_scroll_tab_layout.py` — `setFixedWidth` на scroll areas | Layout proportions |

---

### Task 5.1 — Font-стили заголовков → QSS

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Заменить `setFont()` + `setBold()` + `setPointSize()` на objectName + QSS-правила для label-заголовков

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/audit_log_panel.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/sessions_panel.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/users_panel.py`
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py`
- `multiprocess_prototype/frontend/widgets/dialogs/confirm_with_password.py`

**Шаги:**

1. Добавить в main.qss:
   ```css
   QLabel#PanelHeader { font-weight: bold; font-size: 15px; }
   QLabel#TabHeaderLg { font-weight: bold; font-size: 17px; }
   QLabel#ConfirmActionLabel { font-weight: bold; }
   ```

2. В каждом файле (F1-F3): заменить блок из 4 строк:
   ```python
   font = header_label.font()
   font.setBold(True)
   font.setPointSize(font.pointSize() + 2)
   header_label.setFont(font)
   ```
   на одну строку: `header_label.setObjectName("PanelHeader")`

3. F4 (services/tab.py): аналогично → `title_label.setObjectName("TabHeaderLg")`

4. F5 (confirm_with_password.py): убрать `_font = ...` блок → `_action_label.setObjectName("ConfirmActionLabel")`

**Acceptance criteria:**
- [ ] Grep `\.setFont\(` в перечисленных файлах возвращает 0
- [ ] Grep `\.setBold\(` в перечисленных файлах возвращает 0
- [ ] Заголовки визуально идентичны

**Out of scope:** `node_item.py`, `form_builder.py`, `register_view.py`, `processes/tab.py` — оставить как есть (QGraphicsItem/QTableWidgetItem)
**Dependencies:** Task 1.1

---

### Task 5.2 — Размеры кнопок пагинации → QSS

**Level:** Junior+ (Sonnet)
**Assignee:** developer
**Goal:** Перенести `setFixedWidth(50)` кнопок пагинации в QSS

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/audit_log_panel.py`
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

**Шаги:**

1. В main.qss дополнить правило `QPushButton#PaginationArrow`:
   ```css
   QPushButton#PaginationArrow {
       font-size: 22px;
       padding: 4px 4px;
       min-width: 50px;
       max-width: 50px;
   }
   ```

2. В audit_log_panel.py: убрать `self._btn_prev.setFixedWidth(50)` и `self._btn_next.setFixedWidth(50)`

**Acceptance criteria:**
- [ ] Кнопки сохраняют ширину 50px
- [ ] Ноль `setFixedWidth` для кнопок пагинации

**Dependencies:** Task 1.1

---

## Риски и ограничения

1. **unpolish/polish забыт** — самый частый баг при property-based QSS. В Tasks 3.1, 3.4, 3.5 это критично. Без unpolish/polish Qt не пересчитывает стили при изменении property.
2. **WA_StyledBackground** — для кастомных QWidget (error_banner rows) `background` из QSS не работает без этого атрибута. Task 3.3 явно это указывает.
3. **QGraphicsView** (graph_view.py) — наследует QAbstractScrollArea. QSS `QWidget#PipelineGraphView` может не подхватить background. Если не сработает — использовать `QGraphicsView#PipelineGraphView` в селекторе QSS.
4. **Конфликт objectName** — некоторые виджеты могут уже иметь objectName для других целей. Проверять перед заменой.
5. **Каскадирование QSS** — objectName-селекторы имеют высокий приоритет, но если родитель задаёт `color` на `*`, это может перекрыться. Тестировать визуально.
6. **Category badge dynamic color** — единственный допустимый inline стиль. Если в будущем появятся новые категории, QSS-подход потребует обновления. setStyleSheet — более гибкий вариант для этого случая.
