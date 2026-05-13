---
Phase: 4
Название: Разбивка ThemeEditorSection (869 LOC → 6 файлов)
Статус: DONE
Зависит от: Phase 3 (✅)
Коммит: cbcf157
---

# Phase 4 — Appearance секция (разбивка монолита)

## Цель

Разбить `theme_editor_section.py` (869 LOC) на 6 файлов с MVP. Самая объёмная фаза.

## Задачи

### Task 4.1 — `appearance/view.py` (~40 LOC)
AppearanceView Protocol: set_themes, set_vars, set_color_preview, etc.

### Task 4.2 — `appearance/presenter.py` (~200 LOC)
CRUD тем, owner `_current_vars`/`_last_saved_vars`. Вся бизнес-логика.

### Task 4.3 — `appearance/inline_color_editor.py` (~100 LOC)
Inline color dialog: API `open(table, row, color)`, `close()`, `color_changed` signal.

### Task 4.4 — `appearance/themes_table.py` (~150 LOC)
QTableWidget с таблицей тем (Name, Type, Parent).

### Task 4.5 — `appearance/vars_editor.py` (~250 LOC)
TreeNav + таблица переменных + `var_changed` signal.

### Task 4.6 — `appearance/section.py` (~120 LOC)
Компоновка виджетов, implements SectionProtocol.

### Task 4.7 — Удалить `theme_editor_section.py`

### Task 4.8 — Тесты `test_appearance_presenter.py`

## Acceptance Criteria

- [x] Ни один файл > 400 LOC (max 376 — vars_editor.py)
- [x] Presenter владеет данными, vars_editor эмитит var_changed
- [x] inline_color_editor: API open/close/signal (без crash при повторном открытии)
- [x] Все тесты green (22/22 passed)
- [x] theme_editor_section.py удалён
