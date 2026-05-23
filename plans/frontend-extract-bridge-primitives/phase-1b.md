# Фаза 1B — Консолидация `qt_imports` (после стабилизации `widgets/tabs/`)

- **Родительский план:** [`plan.md`](plan.md)
- **Статус:** DONE (2026-05-24). Стартовала после мержа пилота `refactor/recipes-columnar-pilot` в main (commit `cf281be`). Второй блокер (`columnar-tab-unify` Phase 1) не понадобился — будущий rename `DiffScrollTabLayout → ColumnarTabLayout` сохранит уже консолидированные импорты внутри файла; перенос `view_mode_toggle` в framework сделает свою замену в момент переноса.
- **Содержание:** B1 (qt_imports консолидация)

До разблокировки `widgets/tabs/` — hot-conflict zone: переименования и удаления файлов сделают повторную замену импортов бессмысленной.

---

## Task B1 — Расширение `core/qt_imports.py` и замена прямых PySide6-импортов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** добавить ~12 отсутствующих Qt-символов в `core/qt_imports.py` и заменить
прямые `from PySide6.*` на `from frontend_module.core.qt_imports import ...`
в проблемных файлах.
**Context:** 40 файлов фреймворка импортируют PySide6 напрямую (проверено grep на 2026-05-23).
`qt_imports.py` создан именно как единая точка — нужно довести консолидацию. После этого
поиск «используемых Qt-символов» будет тривиальным grep по одному файлу.

**Pre-flight checklist (обязательно перед стартом B1):**
- [x] `refactor/recipes-columnar-pilot` смержен в main (commit `cf281be`)
- [ ] ~~`columnar-tab-unify` Phase 1 завершена~~ — не требовалось: rename файла не ломает внутренние импорты, перенос `view_mode_toggle` будет сопровождаться собственным переходом на qt_imports
- [ ] ~~`widgets/view_mode_toggle.py` существует в framework~~ — пока в прото, переход на qt_imports делается на момент переноса
- [x] `mcp__sentrux__session_start` — baseline сохранён (7159)
- [x] Повторный grep `from PySide6\.` по `frontend_module/` — актуальный список 33 файла (после Phase 1A: components/primitives + bridge переехали в fw)

**Module contract:** public-api-change (расширение `__all__` существующего модуля)

**Files:**
<!-- V1 (v2): список файлов НЕ фиксируется статически — реальных файлов 24+, пропускаются
     forms/form_context.py, widgets/tabs/base_columnar_tab.py, core/qt_thread_guard.py,
     core/prefs_store.py, widgets/tabs/tab_layout_protocol.py, widgets/tabs/section_protocol.py.
     Полный список определяется динамически на Step 1.
     v3: после columnar-tab-unify перечень файлов в widgets/tabs/* изменится — строить grep заново. -->
- `multiprocess_framework/modules/frontend_module/core/qt_imports.py` — расширить импорты и `__all__`
- **Все файлы** из `multiprocess_framework/modules/frontend_module/` (исключая `core/qt_imports.py`,
  `tests/`, `__pycache__/`), которые содержат `from PySide6` — определяются на Step 1.
  Ориентировочный список (~24 файла на 2026-05-23, **актуализировать после columnar-tab-unify**):
  `widgets/entity_editor/entity_tree_widget.py`, `widgets/entity_editor/base_editor_tree.py`,
  `widgets/entity_editor/params_form.py`, `widgets/entity_editor/base_editor_toolbar.py`,
  `widgets/entity_editor/schema_inspector_panel.py`, `widgets/tabs/base_tree_nav_tab.py`,
  `widgets/tabs/base_list_nav_tab.py`, `widgets/tabs/nav_tree_utils.py`,
  `widgets/tabs/current_page_stack.py`, `widgets/tabs/tab_layouts/columnar_tab_layout.py` (после rename),
  `widgets/tabs/tab_layouts/_abstract_columnar.py`,
  `widgets/tabs/base_columnar_tab.py`, `widgets/tabs/tab_layout_protocol.py`,
  `widgets/tabs/section_protocol.py`, `managers/theme_manager.py`,
  `widgets/chrome/app_header/widget.py`, `widgets/chrome/recording_indicator/widget.py`,
  `widgets/chrome/side_panels/collapsible.py`, `widgets/chrome/watchdog_overlay/widget.py`,
  `widgets/view_mode_toggle.py` (новый, переехал из прото в columnar-plan Task 1.0),
  `forms/form_context.py`, `core/qt_thread_guard.py`, `core/prefs_store.py`
  (и возможные другие — актуальный список только из Step 1)

**Steps:**
1. Составить полный список символов из `from PySide6.*` по всем файлам после стабилизации
   `widgets/tabs/` (grep) — вычесть уже имеющиеся в `qt_imports.py`.
2. Добавить недостающие в `qt_imports.py`:
   - `QtGui`: `QColor`, `QPainter`, `QStandardItem`, `QStandardItemModel`
   - `QtWidgets`: `QTreeView`, `QAbstractScrollArea`, `QScrollBar`
   - `QtCore`: `QChildEvent` (и `SignalInstance` только под `TYPE_CHECKING`)
   - прочие по результату шага 1
3. В каждом из файлов заменить `from PySide6.QtXxx import A, B` на
   `from multiprocess_framework.modules.frontend_module.core.qt_imports import A, B`.
   Для символов под `TYPE_CHECKING` (`SignalInstance`, `QWheelEvent`) — оставить
   условный блок, но источник изменить на `qt_imports`.
4. Файлы вне `frontend_module` (тесты, прото) — не трогать.
5. Прогнать `make check`.

**Acceptance criteria:**
- [x] `grep -r "from PySide6\." multiprocess_framework/modules/frontend_module/ --include="*.py"` возвращает только `core/qt_imports.py` (источник) и `tests/*` (out of scope). Все TYPE_CHECKING-блоки тоже переведены на qt_imports для единообразия.
- [x] `ruff` + `pyright` — 0 errors (37 warnings — pre-existing, не из правок B1)
- [x] `python scripts/run_framework_tests.py` — 2859 passed, 8 skipped
- [x] `mcp__sentrux__session_end` — quality 7159 → 7166 (+8), 0 циклов, 0 violations
- [x] `python scripts/validate.py` зелёный

**Out of scope:**
- Не трогать файлы вне `frontend_module` (прото, сервисы, плагины)
- Не переименовывать символы Qt
- Не менять логику файлов — только строки импортов

**Edge cases:**
- `tab_layout_protocol.py` и `section_protocol.py` используют PySide6 только под
  `TYPE_CHECKING` — для TYPE_CHECKING-блоков замена допустима, но можно оставить
  напрямую если pyright не ругается. Принять решение по месту.
- `base_list_nav_tab.py` использует `QIcon` только под `TYPE_CHECKING` — аналогично.
- **v3:** после `columnar-tab-unify` имя файла `tab_layouts/diff_scroll_layout.py` сменится
  на `columnar_tab_layout.py`. Список файлов в Step 1 нужно строить **после** rename'а,
  иначе придётся править файл, которого больше нет.
- **v3:** если пилот `recipes-columnar-pilot` добавит новые файлы в `widgets/tabs/`
  (например, для processing/sources/displays), они автоматически попадут в grep Step 1.
- **v3:** новый файл `widgets/view_mode_toggle.py` (после columnar Task 1.0) тоже должен
  оказаться в списке — проверить, что в нём `from PySide6.*` заменён.

**Dependencies:** Фаза 1A полностью завершена (A1, A2, B2, B3, C1, C2, C3) + мерж пилота вкладок
+ Phase 1 плана `columnar-tab-unify` (см. Pre-flight checklist выше).

---

## Локальные риски Фазы 1B

1. **qt_imports TYPE_CHECKING (B1):** `SignalInstance`, `QWheelEvent` — только под `TYPE_CHECKING`.
   Mitigation: отдельный `TYPE_CHECKING`-блок в `qt_imports.py`.

2. **Hot-conflict с пилотом вкладок (B1):** `widgets/tabs/*` активно меняется
   ветками `refactor/recipes-columnar-pilot` и (будущей) реализацией `columnar-tab-unify`.
   Mitigation: B1 не стартует до выполнения Pre-flight checklist в описании задачи.
   Список файлов строится через grep заново после стабилизации `widgets/tabs/`.

3. **Rename `DiffScrollTabLayout → ColumnarTabLayout` пройдёт между Фазой 1A и Фазой 1B.**
   Это означает, что `tab_layouts/diff_scroll_layout.py` исчезнет, появится
   `tab_layouts/columnar_tab_layout.py`. Список файлов B1 в плане — ориентировочный,
   реальный набор определяется на Step 1.
