---
Slug: columnar-tab-unify
Дата: 2026-05-18
Статус: DRAFT
Ветка: refactor/columnar-tab-unify (создаётся в Phase 0)
Автор: Director (Opus)
Baseline: aa1062a (refactor/tab-template DONE)
Стратегия: Гибрид (rename DiffScrollTabLayout → ColumnarTabLayout + extend), не from-scratch
Связанные ADR: ADR-126 (шаблон), ADR-127 (отменяется через ADR-128), ADR-128 (новое — в Phase 0)
---

# Plan: Унификация layout'ов вкладок — ColumnarTabLayout

## Контекст

После Phase 6 плана `tab-template-extraction` в кодовой базе сосуществуют два layout-класса:
`DiffScrollTabLayout` (Settings — мастер-скролл, QGroupBox, статичная зона undo/redo) и
`StandardTabLayout` (Recipes — голый QScrollArea, add_top_action API, собственный ViewModeToggle).
Вкладка Recipes **визуально чужеродна** на фоне Settings: нет QGroupBox с заголовком, нет мастер-скролла.
ADR-127, разрешивший существование двух layout'ов, **отменяется**; вводится ADR-128 — единый `ColumnarTabLayout`.

Reviewer провёл анализ и рекомендовал **Гибрид (Вариант 3)**: не писать новый класс с нуля (~600 LOC), а
**переименовать** `DiffScrollTabLayout` → `ColumnarTabLayout` и **добавить** в него API из `StandardTabLayout`
(24 LOC методов + сигнал + встроенный ViewModeToggle). Проверенный код не переписываем — только дополняем.
Scope ограничен: Settings (rename-only, визуально не меняется) + Recipes (pilot нового шаблона).

---

## Архитектурные решения

1. **ViewModeToggle живёт в framework, не в prototype** — иначе `ColumnarTabLayout` (слой framework) не может его встроить без нарушения layer rule (`framework → prototype` запрещён). Перемещение в framework — pre-step Phase 1 (Task 1.0). Thin re-export shim остаётся в prototype для backward-compat.

2. **Toggle встроенный (opt-out), не slot** — пользователь решил: Cards/Table переключатель должен быть в layout по умолчанию везде. Потребитель явно скрывает через `hide_view_mode_toggle()` (Settings), или подключается к сигналу (Recipes). Авто-скрытие при отсутствии receivers не делаем — runtime check ненадёжен; вместо этого warning в лог.

---

## Целевая архитектура

### Публичный контракт `ColumnarTabLayout` после Phase 1

```python
class ColumnarTabLayout(_AbstractColumnarTabLayout):
    """Единый шаблон вкладки: 3 колонки + мастер-скролл + QGroupBox + ViewModeToggle.

    ViewModeToggle присутствует ВСЕГДА и виден по умолчанию (opt-out, не opt-in).
    Потребитель обязан либо подключить view_mode_changed, либо вызвать hide_view_mode_toggle().
    Если view_mode_changed не подключён после populate() — warning в лог (не авто-скрытие).

    Сигналы:
        section_changed(str)       — backward-compat, смена раздела
        action_triggered(str)      — Recipes-стиль: id кнопки
        view_mode_changed(str)     — Cards/Table; re-emit от внутреннего ViewModeToggle

    ViewModeToggle:
        __init__ сам создаёт ViewModeToggle (импортируется из framework после Task 1.0)
        и кладёт его сверху action-колонки (до _top_actions_layout).
        hide_view_mode_toggle()               — скрыть toggle
        set_view_mode_toggle_visible(bool)    — алиас hide/show
        @property view_mode_toggle → ViewModeToggle   — публичный доступ

    Наполнение action-колонки — два режима (НЕ одновременно):
        set_action_widget(w)       — один виджет целиком (Settings-стиль)
        add_top_action(id, label)  — добавить кнопку (Recipes-стиль)
        add_top_widget(w)          — добавить произвольный виджет
        action_triggered: Signal(str)

    Прочий API (без изменений из DiffScrollTabLayout):
        set_title(text), set_nav_widget(widget), set_content_widget(widget)
        enable_undo_redo(bus), register_inner_scrolls(widget)
        connect_stack(stack, role), refresh_after_page_change(role)
        nav_group / action_scroll / nav_scroll / content_scroll / master_scrollbar / static_bottom
    """
```

**Guard `set_action_widget` + `add_top_action`:** если `_top_actions_layout` не пуст в момент вызова `set_action_widget`, метод логирует `logger.warning(...)` и очищает `_top_actions_layout` перед размещением нового виджета.

**`TabLayoutProtocol`** — не трогаем. `view_mode_changed` / `hide_view_mode_toggle` — специфика `ColumnarTabLayout`, не часть обязательного контракта (потребители проверяют через `hasattr`).

### Диаграмма финального состояния (этот план)

```
multiprocess_framework/modules/frontend_module/widgets/
├── view_mode_toggle.py                ← НОВОЕ (Task 1.0 — перемещено из prototype)
└── tabs/tab_layouts/
    ├── _abstract_columnar.py          ← без изменений
    ├── diff_scroll_layout.py          ← ПЕРЕИМЕНОВАН в columnar_tab_layout.py (содержимое ИЗМЕНЕНО)
    ├── standard_layout.py             ← УДАЛЁН в Phase 4
    └── __init__.py                    ← обновлён: ColumnarTabLayout + thin shim DiffScrollTabLayout

multiprocess_prototype/frontend/
├── forms/view_mode_toggle.py          ← thin re-export shim (Task 1.0 — backward-compat)
└── widgets/
    ├── primitives/diff_scroll_tab_layout.py  ← thin alias → ColumnarTabLayout (Phase 2)
    ├── primitives/standard_tab_layout.py     ← УДАЛЁН в Phase 4
    └── tabs/
        ├── settings/tab.py            ← импорт + hide_view_mode_toggle() (Phase 2)
        └── recipes/tab.py             ← layout_factory + _setup_actions (Phase 3)

styles/.../components/domains/
├── diff_scroll.qss                    ← ПЕРЕИМЕНОВАН в columnar.qss (Task 1.0)
└── main.qss                           ← @import обновлён + objectName'ы (Task 1.0)

tests (Phase 4):
├── test_columnar_tab_layout.py        ← 28 перенесённых тестов из Standard(23) + DiffScroll(5)
└── test_diff_scroll_tab_layout_public_api.py  ← УДАЛЁН
    test_standard_tab_layout.py        ← УДАЛЁН
```

---

## Стратегия: Гибрид (rename + extend), не from-scratch

Reviewer указал: `DiffScrollTabLayout` содержит ~419 LOC проверенного в production кода.
Создание `ColumnarTabLayout` с нуля — это 600 LOC, риск регрессий в мастер-скролле (сложный
дифференциальный механизм: `_on_master_changed`, `eventFilter`, `_redirect_nested_wheels`).

**Выбранный путь:**
1. Pre-step (Task 1.0): переместить `ViewModeToggle` в framework; переименовать `diff_scroll.qss` → `columnar.qss` и обновить objectName'ы в QSS + в Python-коде.
2. Переименовать `diff_scroll_layout.py` → `columnar_tab_layout.py`, класс `DiffScrollTabLayout` → `ColumnarTabLayout`.
3. Добавить методы из `StandardTabLayout`: `add_top_action`, `add_top_widget`, `set_action_enabled`, `get_button`, сигнал `action_triggered` (~24 LOC методов + handler).
4. Встроить `ViewModeToggle` в `__init__` layout'а — сверху action-колонки, до `_top_actions_layout`; сигнал `view_mode_changed` как re-emit; opt-out через `hide_view_mode_toggle()`.
5. Guard в `set_action_widget`: лог + очистка при конфликте.

Что **не делаем**: не трогаем scroll-sync механику (eventFilter, wheelEvent, _on_master_changed и т.д.) — она уже работает.

---

## Порядок выполнения

```
Phase 0: Task 0.1 (ADR-128, baseline)
    ↓
Phase 1: Task 1.0 (move ViewModeToggle в framework + QSS rename) — pre-step
         Task 1.1 (rename + extend ColumnarTabLayout) — главная фаза
    ↓
Phase 2: Task 2.1 (Settings: импорт + hide_view_mode_toggle + visual smoke)
    ↓
Phase 3: Task 3.1 (Recipes: layout_factory + _setup_actions + type: ignore cleanup)
    ↓
Phase 4: Task 4.1 (удалить Standard + переписать 28 тестов в test_columnar_tab_layout.py)
    ↓
Phase 5: Task 5.1 (ADR-128 закрыть + docs/refactors/ отчёт + план DONE)
```

---

## Phase 0 — Подготовка

### Task 0.1 — ADR-128 и baseline

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Зафиксировать отмену ADR-127 и принятие `ColumnarTabLayout` в DECISIONS.md; записать baseline тестов.

**Context:** ADR-документ нужен до кода — он формализует решение Гибрид и объясняет, почему ADR-127 отменяется. Baseline тестов нужен для сравнения «до/после» в Phase 4–5.

**Files:**
- `multiprocess_framework/DECISIONS.md` — добавить ADR-128, пометить ADR-127 как Superseded

**Steps:**
1. В `DECISIONS.md` добавить запись ADR-128 со следующим содержанием:
   - **Контекст:** два layout-класса (DiffScroll + Standard) создают визуальную несогласованность.
   - **Решение:** Стратегия Гибрид — rename `DiffScrollTabLayout` → `ColumnarTabLayout` + extend методами из Standard. `ViewModeToggle` перемещается из `multiprocess_prototype/frontend/forms/` в `multiprocess_framework/modules/frontend_module/widgets/` (pre-step Phase 1). `StandardTabLayout` удаляется после миграции Recipes. ProcessesTab, PluginsTab — вне scope.
   - **Последствия:** `DiffScrollTabLayout` становится thin alias в prototype на 1 цикл. `ViewModeToggle` в prototype — thin re-export shim. Тесты (23 + 5 = 28) переписываются под `ColumnarTabLayout`.
2. Пометить ADR-127 статусом «Superseded by ADR-128».
3. Зафиксировать baseline: количество тестов через `python scripts/run_framework_tests.py` (ожидаемый baseline: framework ~2746, Settings 128, Recipes 26).
4. Коммит `docs(decisions): ADR-128 — ColumnarTabLayout гибрид, отменяет ADR-127`.

**Acceptance criteria:**
- [ ] ADR-128 присутствует в `DECISIONS.md`
- [ ] ADR-127 помечен как Superseded
- [ ] Baseline чисел тестов зафиксирован в тексте коммита или комментарии ADR-128

**Out of scope:** Код не трогать. ADR не пишется отдельным `.md` файлом — только запись в `DECISIONS.md`.

**Dependencies:** нет

---

## Phase 1 — Pre-step + Rename + Extend

### Task 1.0 — Move ViewModeToggle в framework + QSS rename

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переместить `ViewModeToggle` из prototype в framework (устранить layer violation для Task 1.1); переименовать `diff_scroll.qss` → `columnar.qss` и обновить все objectName'ы в QSS и Python-коде.

**Context:** `ColumnarTabLayout` (слой framework) должен создавать `ViewModeToggle` в своём `__init__`. Слой framework не может импортировать из prototype — это запрещено layer rule и enforced через `.sentrux/rules.toml`. Поэтому `ViewModeToggle` перемещается в framework. В prototype остаётся thin re-export shim (`from multiprocess_framework... import *`) — все существующие импорты (`recipes/tab.py`, `processes/tab.py`, `settings/system/section.py`) продолжат работать без изменений.

QSS rename делается здесь, а не в Phase 5 — потому что objectName'ы Python-кода меняются вместе с rename класса в Task 1.1, и QSS должен быть синхронизирован до запуска тестов в Phase 2. Делать это в Phase 5 означало бы сломанные стили на весь период Phase 2–4.

**Точный mapping objectName'ов (Python-код → QSS):**

| Старый objectName (Python/QSS) | Новый objectName (Python/QSS) | Где используется |
|-------------------------------|-------------------------------|-----------------|
| `DiffScrollNavGroup` | `ColumnarNavGroup` | `diff_scroll_layout.py` строка 120; `diff_scroll.qss` строки 4,9; `main.qss` строки 785,790 |
| `DiffScrollMaster` | `ColumnarMaster` | `diff_scroll_layout.py` строка 152 |
| `DiffScrollActions` | `ColumnarActions` | `diff_scroll_layout.py` строка 104 |
| `DiffScrollNav` | `ColumnarNav` | `diff_scroll_layout.py` строка 130 |
| `DiffScrollContent` | `ColumnarContent` | `diff_scroll_layout.py` строка 147 |
| `DiffScrollUndo` | `ColumnarUndo` | `diff_scroll_layout.py` строки 293 |
| `DiffScrollRedo` | `ColumnarRedo` | `diff_scroll_layout.py` строка 294 |
| `DiffScrollLeft` | `ColumnarActions` | `diff_scroll.qss` строки 15-16; `main.qss` строки 864-865 (QSS-имена scroll area) |
| `DiffScrollRight` | `ColumnarContent` | `diff_scroll.qss` строки 15-16; `main.qss` строки 864-865 (QSS-имена scroll area) |

**Примечание:** `DiffScrollLeft` / `DiffScrollRight` — это QSS-псевдонимы для тех же scroll area, что в Python именуются `DiffScrollActions` / `DiffScrollContent`. После переименования QSS и Python используют одно имя: `ColumnarActions` / `ColumnarContent`.

**Files:**
- `multiprocess_prototype/frontend/forms/view_mode_toggle.py` — оставить как thin re-export shim
- `multiprocess_framework/modules/frontend_module/widgets/view_mode_toggle.py` — СОЗДАТЬ (переместить содержимое)
- `multiprocess_framework/modules/frontend_module/widgets/__init__.py` — добавить реэкспорт `ViewModeToggle`, `ViewMode`
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/components/domains/diff_scroll.qss` — переименовать в `columnar.qss`, обновить содержимое
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss` — обновить `@import` и objectName'ы (строки 784–868)

**Steps:**
1. Создать `multiprocess_framework/modules/frontend_module/widgets/view_mode_toggle.py` — скопировать полное содержимое из `multiprocess_prototype/frontend/forms/view_mode_toggle.py` (классы `ViewMode`, `ViewModeToggle` без изменений).
2. В `multiprocess_framework/modules/frontend_module/widgets/__init__.py` добавить:
   ```python
   from .view_mode_toggle import ViewMode, ViewModeToggle
   ```
3. Заменить содержимое `multiprocess_prototype/frontend/forms/view_mode_toggle.py` на thin re-export shim:
   ```python
   """Backward-compat re-export. ViewModeToggle перемещён в framework.
   Удалить не ранее чем через 1 major-цикл.
   """
   from multiprocess_framework.modules.frontend_module.widgets.view_mode_toggle import (
       ViewMode,
       ViewModeToggle,
   )
   __all__ = ["ViewMode", "ViewModeToggle"]
   ```
4. Переименовать файл `diff_scroll.qss` → `columnar.qss` (git mv или эквивалент).
5. Заменить содержимое нового `columnar.qss`:
   - Заголовочный комментарий: `/* === columnar.qss — ColumnarNavGroup, ColumnarActions, ColumnarContent === */`
   - `QGroupBox#DiffScrollNavGroup` → `QGroupBox#ColumnarNavGroup` (оба вхождения: правило + `::title`)
   - `QScrollArea#DiffScrollLeft, QScrollArea#DiffScrollRight` → `QScrollArea#ColumnarActions, QScrollArea#ColumnarContent`
   - Внутренние комментарии: `/* --- DiffScrollTabLayout --- */` → `/* --- ColumnarTabLayout --- */`
   - Внутренние комментарии: `/* --- DiffScroll transparent ScrollArea --- */` → `/* --- Columnar transparent ScrollArea --- */`
6. В `main.qss` выполнить следующие замены (точные строки — ориентиры, проверить перед правкой):
   - Строка 784: `/* --- DiffScrollTabLayout --- */` → `/* --- ColumnarTabLayout --- */`
   - Строка 785: `QGroupBox#DiffScrollNavGroup` → `QGroupBox#ColumnarNavGroup`
   - Строка 790: `QGroupBox#DiffScrollNavGroup::title` → `QGroupBox#ColumnarNavGroup::title`
   - Если есть `@import "diff_scroll.qss"` — заменить на `@import "columnar.qss"` (grep для точного поиска)
   - Строка 863: `/* --- DiffScroll transparent ScrollArea --- */` → `/* --- Columnar transparent ScrollArea --- */`
   - Строки 864–865: `QScrollArea#DiffScrollLeft, QScrollArea#DiffScrollRight` → `QScrollArea#ColumnarActions, QScrollArea#ColumnarContent`
7. Проверить: `grep -rn "DiffScroll" multiprocess_prototype/frontend/styles/` → 0 результатов.
8. Проверить: `grep -rn "ViewModeToggle\|ViewMode" multiprocess_prototype/frontend/forms/view_mode_toggle.py` — только re-export строки.
9. Проверить: `from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle` — работает (через shim).
10. Проверить: `from multiprocess_framework.modules.frontend_module.widgets import ViewModeToggle` — работает напрямую.
11. Коммит `refactor(framework): move ViewModeToggle to framework + columnar.qss rename`.

**Acceptance criteria:**
- [ ] `multiprocess_framework/modules/frontend_module/widgets/view_mode_toggle.py` существует, содержит классы `ViewMode` и `ViewModeToggle`
- [ ] `multiprocess_prototype/frontend/forms/view_mode_toggle.py` — только thin re-export shim (не содержит определений классов)
- [ ] `from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle` — работает без изменений
- [ ] `from multiprocess_framework.modules.frontend_module.widgets import ViewModeToggle` — работает
- [ ] `multiprocess_prototype/frontend/styles/themes/innotech_theme/components/domains/columnar.qss` существует
- [ ] `diff_scroll.qss` более не существует
- [ ] `grep -rn "DiffScroll" multiprocess_prototype/frontend/styles/` → 0 результатов
- [ ] `grep -rn "DiffScrollLeft\|DiffScrollRight" multiprocess_prototype/` → 0 результатов
- [ ] `python scripts/validate.py` — зелёный

**Out of scope:** Не менять Python objectName'ы в `diff_scroll_layout.py` — это делает Task 1.1. Не трогать QSS-правила других доменов.

**Edge cases:**
- Если `main.qss` не содержит `@import` для `diff_scroll.qss` (а подключение идёт иначе) — не добавлять; только заменить objectName'ы внутри файла.
- Если `__init__.py` widgets уровня framework уже содержит wildcard import — добавить явный именованный импорт рядом.

**Dependencies:** Task 0.1

---

### Task 1.1 — Rename DiffScrollTabLayout → ColumnarTabLayout + extend + встроенный toggle

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Переименовать `DiffScrollTabLayout` в `ColumnarTabLayout`, добавить API из StandardTabLayout и встроить `ViewModeToggle` напрямую в layout.

**Context:** Это главная фаза плана. Весь scroll-sync механизм (`_on_master_changed`, `eventFilter`, `wheelEvent`, `_redirect_nested_wheels`, `_install_wheel_redirect`) остаётся без изменений — только добавляем новый функционал поверх. После Task 1.0 `ViewModeToggle` доступен в framework без layer violation — `ColumnarTabLayout` импортирует его из `multiprocess_framework.modules.frontend_module.widgets`.

**Toggle-стратегия:** `__init__` создаёт `ViewModeToggle` и помещает его в верх action-колонки (до `_top_actions_layout`). Сигнал `view_mode_changed(str)` эмитируется как re-emit от `self._toggle.mode_changed`. Если потребитель не подключил обработчик — warning в лог (не авто-скрытие). Потребитель вызывает `hide_view_mode_toggle()` явно (Settings) или подключается к `view_mode_changed` (Recipes).

**Объём изменений:** к существующим 419 LOC добавить ~50–70 LOC (toggle + actions API + guard).

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/diff_scroll_layout.py` → **переименовать файл** в `columnar_tab_layout.py`
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/__init__.py` — обновить реэкспорты
- `multiprocess_prototype/frontend/widgets/primitives/diff_scroll_tab_layout.py` — пока НЕ трогать (Phase 2)

**Steps:**
1. Переименовать файл `diff_scroll_layout.py` → `columnar_tab_layout.py` (git mv).
2. Добавить импорт в начало нового файла:
   ```python
   from multiprocess_framework.modules.frontend_module.widgets.view_mode_toggle import (
       ViewMode,
       ViewModeToggle,
   )
   ```
3. Переименовать класс `DiffScrollTabLayout` → `ColumnarTabLayout`. Обновить docstring: убрать ссылку на ADR-127, добавить ссылку на ADR-128. Добавить описание ViewModeToggle (opt-out: visible by default, explicit `hide_view_mode_toggle()` для отключения) и Guard.
4. Переименовать objectName'ы в `_build_ui` согласно mapping из Task 1.0:
   - `"DiffScrollActions"` → `"ColumnarActions"` (строка 104)
   - `"DiffScrollNav"` → `"ColumnarNav"` (строка 130)
   - `"DiffScrollContent"` → `"ColumnarContent"` (строка 147)
   - `"DiffScrollMaster"` → `"ColumnarMaster"` (строка 152)
   - `"DiffScrollUndo"` → `"ColumnarUndo"` (строка 293)
   - `"DiffScrollRedo"` → `"ColumnarRedo"` (строка 294)
   - `"DiffScrollNavGroup"` → `"ColumnarNavGroup"` (строка 120)
5. Добавить сигналы в тело класса (рядом с `section_changed`):
   ```python
   action_triggered = Signal(str)
   view_mode_changed = Signal(str)
   ```
6. В `_build_ui` в начале формирования action-колонки (до `_top_actions_layout`):
   - Создать `self._toggle = ViewModeToggle()` и добавить его в action-колонку через `left_col.addWidget(self._toggle)`.
   - Подключить re-emit: `self._toggle.mode_changed.connect(self.view_mode_changed.emit)`.
   - `self._toggle_container = self._toggle` (для opt-out методов).
7. Добавить `_top_actions_layout = QVBoxLayout()` в action-колонке (ниже toggle, выше stretch).
8. Добавить методы из `StandardTabLayout` (скопировать, адаптировать objectName'ы):
   - `add_top_action(self, action_id: str, label: str) -> QPushButton`
   - `add_top_widget(self, widget: QWidget) -> None`
   - `set_action_enabled(self, action_id: str, enabled: bool) -> None`
   - `get_button(self, action_id: str) -> QPushButton | None`
   - `_make_button(self, action_id: str, label: str) -> QPushButton`
   - `_buttons: dict[str, QPushButton]` — атрибут для хранения кнопок
9. Добавить Guard в `set_action_widget(self, widget: QWidget) -> None`:
   ```python
   if self._top_actions_layout.count() > 0:
       import logging
       logging.getLogger(__name__).warning(
           "ColumnarTabLayout.set_action_widget вызван при непустом "
           "_top_actions_layout. Кнопки add_top_action будут удалены."
       )
       while self._top_actions_layout.count():
           item = self._top_actions_layout.takeAt(0)
           if item.widget():
               item.widget().setParent(None)
   self._action_scroll.setWidget(widget)  # существующая логика
   ```
10. Добавить opt-out методы:
    - `hide_view_mode_toggle(self) -> None` — `self._toggle_container.setVisible(False)`
    - `set_view_mode_toggle_visible(self, visible: bool) -> None` — `self._toggle_container.setVisible(visible)`
    - `@property view_mode_toggle(self) -> ViewModeToggle` — `return self._toggle`
11. Обновить `__init__.py` уровня `tab_layouts/`:
    - Добавить `from .columnar_tab_layout import ColumnarTabLayout`
    - Добавить thin shim: `DiffScrollTabLayout = ColumnarTabLayout` (backward-compat alias внутри framework)
    - Сохранить `StandardTabLayout` в реэкспорте до Phase 4
12. Обновить `__init__.py` уровня `tabs/` (`widgets/tabs/__init__.py`) — добавить `ColumnarTabLayout` в реэкспорт.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts import ColumnarTabLayout` — работает без ошибок
- [ ] `ColumnarTabLayout` наследует `_AbstractColumnarTabLayout`
- [ ] Создание `ColumnarTabLayout(title="Test")` не падает
- [ ] `layout._toggle` существует, является экземпляром `ViewModeToggle`
- [ ] `layout.view_mode_toggle` property возвращает `ViewModeToggle`
- [ ] `layout.view_mode_changed` — сигнал существует; подключение к нему работает
- [ ] Клик на toggle эмитирует `layout.view_mode_changed`
- [ ] `layout.add_top_action("a", "A")` → кнопка добавлена, `action_triggered` эмитируется при клике
- [ ] `layout.set_action_widget(w)` при непустом `_top_actions_layout` → warning в лог, layout не падает
- [ ] `layout.hide_view_mode_toggle()` → `layout._toggle_container.isVisible() == False`
- [ ] `layout.set_view_mode_toggle_visible(True)` → `layout._toggle_container.isVisible() == True`
- [ ] `isinstance(layout, _AbstractColumnarTabLayout)` — True
- [ ] `layout.set_title("X")` → `layout.nav_group.title() == "X"`
- [ ] `python scripts/validate.py` — зелёный (нет broken imports)
- [ ] `grep -rn "DiffScrollNavGroup\|DiffScrollMaster\|DiffScrollUndo\|DiffScrollRedo\|DiffScrollActions\|DiffScrollNav\b\|DiffScrollContent" multiprocess_framework/` → 0 результатов

**Out of scope:** Не трогать `standard_layout.py` (удалится в Phase 4). Не мигрировать потребителей — это Phase 2–3.

**Edge cases:**
- `set_action_widget` вызывается дважды: второй вызов перезаписывает первый без ошибки
- `add_top_action` после `set_action_widget`: документировать в docstring как неопределённое поведение
- `hide_view_mode_toggle()` до полного построения layout: не должно падать

**Dependencies:** Task 1.0

---

## Phase 2 — Settings миграция (smoke)

### Task 2.1 — Settings: импорт + hide_view_mode_toggle + visual smoke

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переключить Settings на `ColumnarTabLayout`, скрыть toggle (Settings не использует Cards/Table), убедиться что визуально ничего не изменилось и `view_mode_changed` fixture в тестах работает.

**Context:** Settings сейчас использует `DiffScrollTabLayout(title="Настройки", action_width=160, nav_width=230)` через `BaseTreeNavTab._layout_factory`. После rename thin shim в `__init__.py` обеспечивает backward-compat, но правильнее явно использовать новое имя. QSS objectName'ы уже обновлены в Task 1.0, поэтому стили не ломаются.

После перехода на `ColumnarTabLayout` toggle виден по умолчанию — Settings должен явно вызвать `layout.hide_view_mode_toggle()` в `_layout_factory`. Acceptance criterion — проверить что toggle скрыт в Settings (тест `test_view_mode_toggle_persists_to_prefs` в `test_settings_tab.py` проверяет логику RegisterView — убедиться что этот тест по-прежнему проходит через `SystemSection`, не через layout-toggle).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py` — обновить импорт + `_layout_factory`
- `multiprocess_prototype/frontend/widgets/primitives/diff_scroll_tab_layout.py` — обновить thin alias на `ColumnarTabLayout`

**Steps:**
1. В `settings/tab.py` заменить `from ... import DiffScrollTabLayout` → `from ... import ColumnarTabLayout`. В `_layout_factory` заменить `DiffScrollTabLayout(...)` → `ColumnarTabLayout(...)`. Добавить вызов `layout.hide_view_mode_toggle()` в factory (toggle-слот скрыть — Settings не использует Cards/Table).
2. В `diff_scroll_tab_layout.py` (prototype) изменить реэкспорт:
   ```python
   # Backward-compat alias. Удалить в Phase 4 плана columnar-tab-unify.
   from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts.columnar_tab_layout import (
       ColumnarTabLayout as DiffScrollTabLayout,
   )
   __all__ = ["DiffScrollTabLayout"]
   ```
3. Запустить тесты Settings: `pytest multiprocess_prototype/frontend/widgets/tabs/settings/ -v`.
4. Проверить что `test_view_mode_toggle_persists_to_prefs` зелёный — он проверяет логику `SystemSection.ViewModeToggle` (внутри content-виджета), не layout-toggle.
5. Visual smoke: запустить приложение, убедиться что Settings выглядит идентично (QGroupBox «Настройки», мастер-скролл, undo/redo кнопки, ViewModeToggle от layout НЕ виден).

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/settings/` — все тесты зелёные (128 тестов)
- [ ] `pytest multiprocess_prototype/frontend/widgets/primitives/tests/test_diff_scroll_tab_layout_public_api.py` — 5 тестов зелёные (через alias)
- [ ] `from multiprocess_prototype.frontend.widgets.primitives import DiffScrollTabLayout` — работает
- [ ] `python scripts/validate.py` — зелёный
- [ ] Visual smoke: QGroupBox «Настройки» присутствует, layout-level ViewModeToggle скрыт, стили не сломаны
- [ ] `test_view_mode_toggle_persists_to_prefs` проходит (SystemSection toggle не затронут)

**Out of scope:** Не трогать секции Settings (содержимое, presenter). Не трогать `standard_layout.py` и `StandardTabLayout` — Phase 4.

**Dependencies:** Task 1.1

---

## Phase 3 — Recipes pilot

### Task 3.1 — Recipes: переход на ColumnarTabLayout + cleanup type: ignore

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Переключить `RecipesTab` с `StandardTabLayout` на `ColumnarTabLayout`, получив QGroupBox + мастер-скролл + встроенный ViewModeToggle; удалить локальный toggle (`add_top_widget(self._toggle)`), подключившись к layout-сигналу; убрать 4 комментария `# type: ignore[attr-defined]`.

**Context:** Recipes — единственный потребитель `StandardTabLayout`. После перехода:
- `layout_factory` создаёт `ColumnarTabLayout(title="Рецепты")` вместо `StandardTabLayout(show_sub_nav=False)`.
- `_setup_actions` убирает `lay.add_top_widget(self._toggle)` — toggle теперь встроен в layout. Recipes **удаляет** создание локального `ViewModeToggle` и вместо этого получает доступ через `lay.view_mode_toggle`. Подключение: `lay.view_mode_changed.connect(self._on_view_mode_changed)`.
- Кнопки load/save/delete — через `add_top_action` (совместимо, API тот же).
- `# type: ignore[attr-defined]` на строках 87–93 в `recipes/tab.py` удаляются: методы теперь есть в `ColumnarTabLayout`.
- Recipes получает `QGroupBox("Рецепты")` и мастер-скролл — визуально становится как Settings.

**Важный нюанс:** Recipes имеет короткие формы (RecipeFormWidget). При малом контенте handle мастер-скроллбара займёт почти всю высоту рельса — это ожидаемое поведение (скролл всегда виден, даже если нечего скроллить: дизайн шаблона).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py` — `layout_factory` + `_setup_actions`

**Steps:**
1. Заменить импорт: убрать `StandardTabLayout` из импорта. Добавить `ColumnarTabLayout` в тот же импорт из framework.
2. Убрать импорт `ViewModeToggle` из строки 22 — он больше не нужен: toggle создаётся внутри layout.
3. В `__init__`: изменить `layout_factory=lambda: StandardTabLayout(show_sub_nav=False)` → `layout_factory=lambda: ColumnarTabLayout(title="Рецепты")`.
4. В `_setup_actions`:
   - Убрать `self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)` — layout уже создал toggle.
   - Убрать `self._toggle.mode_changed.connect(self._on_view_mode_changed)`.
   - Убрать `lay.add_top_widget(self._toggle)` (строка 87 — `# type: ignore[attr-defined]` исчезает).
   - Вместо этого: подключиться к layout-сигналу:
     ```python
     lay.view_mode_changed.connect(self._on_view_mode_changed)
     ```
   - Если `_on_view_mode_changed` ссылается на `self._toggle.mode()` — заменить на `lay.view_mode_toggle.mode()` или `ViewMode(mode_str)` из аргумента сигнала.
   - Строки `lay.add_top_action(...)` (88–91) — оставить как есть, `# type: ignore` удалить.
   - Строка `lay.action_triggered.connect(...)` (93) — оставить, `# type: ignore` удалить.
5. Убедиться что `_on_view_mode_changed(self, mode_str: str)` принимает строку (сигнал `view_mode_changed(str)` передаёт строку — это `ViewMode` StrEnum, совместимо).
6. Запустить тесты Recipes: `pytest multiprocess_prototype/frontend/widgets/tabs/recipes/ -v`.
7. Visual smoke: запустить приложение, убедиться что Recipes имеет QGroupBox «Рецепты», мастер-скролл, ViewModeToggle виден и работает (переключает режим), кнопки load/save/delete работают.

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/recipes/` — все тесты зелёные (26 тестов)
- [ ] Файл `recipes/tab.py`: 0 вхождений `# type: ignore[attr-defined]` (было 4)
- [ ] `python scripts/validate.py` — зелёный
- [ ] Visual smoke: QGroupBox «Рецепты» присутствует; toggle встроенный (от layout), кнопки, мастер-скролл работают
- [ ] `lay.view_mode_changed` подключён к `_on_view_mode_changed` — переключение режима работает

**Out of scope:** Не менять `RecipeFormWidget`, `RecipesPresenter`. Не менять логику `_on_action`, `_sync_nav`, `_show_table`.

**Edge cases:** При `_sync_nav` после save/delete — мастер-скролл может прыгнуть на 0 (штатное поведение). Не фиксировать.

**Dependencies:** Task 2.1

---

## Phase 4 — Удаление StandardTabLayout + 28 тестов

### Task 4.1 — Удалить StandardTabLayout + переписать тесты

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Удалить `StandardTabLayout` из framework и prototype; переписать 28 тестов (23 из `test_standard_tab_layout.py` + 5 из `test_diff_scroll_tab_layout_public_api.py`) в единый файл `test_columnar_tab_layout.py`.

**Context:** После Phase 3 `StandardTabLayout` не имеет потребителей — Recipes мигрирован. Тесты НЕ удаляем — переписываем под `ColumnarTabLayout`, сохраняя покрытие. Итого: `test_columnar_tab_layout.py` содержит минимум 28 тестов. Reviewer: тесты — ценность, их потеря недопустима.

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/standard_layout.py` — УДАЛИТЬ
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/__init__.py` — убрать `StandardTabLayout`
- `multiprocess_prototype/frontend/widgets/primitives/standard_tab_layout.py` — УДАЛИТЬ
- `multiprocess_prototype/frontend/widgets/primitives/__init__.py` — убрать `StandardTabLayout`
- `multiprocess_prototype/frontend/widgets/primitives/tests/test_standard_tab_layout.py` — УДАЛИТЬ (тесты переписаны)
- `multiprocess_prototype/frontend/widgets/primitives/tests/test_diff_scroll_tab_layout_public_api.py` — УДАЛИТЬ (тесты переписаны)
- `multiprocess_framework/modules/frontend_module/tests/test_columnar_tab_layout.py` — СОЗДАТЬ

**Steps:**
1. Перед удалением: `grep -rn "StandardTabLayout" multiprocess_prototype/ multiprocess_framework/` — убедиться, что только `standard_tab_layout.py`, `standard_layout.py`, их `__init__.py` и тест-файлы упоминают `StandardTabLayout`. Если есть другие потребители — стоп, эскалировать.
2. Создать `test_columnar_tab_layout.py` со следующими классами:

   **Из `test_standard_tab_layout.py` (адаптировать под `ColumnarTabLayout`):**
   - `TestActionsColumn` (4 теста): `add_top_action_creates_button`, `action_triggered_signal_emits_id`, `set_action_enabled`, `add_top_widget_adds_widget`
   - `TestUndoRedo` (6 тестов): все 6 тестов из `TestUndoRedo` — адаптировать (кнопки в `_static_bottom`, не в `_bottom_actions_layout`)
   - `TestGuardSetActionWidget` (2 теста): `set_action_widget_clears_top_actions_with_warning`, `set_action_widget_without_conflict_no_warning`
   - `TestViewModeToggle` (4 теста): `toggle_is_visible_by_default`, `hide_view_mode_toggle_hides_widget`, `set_view_mode_toggle_visible_shows_widget`, `view_mode_changed_signal_emits_on_toggle_click`

   **Из `test_diff_scroll_tab_layout_public_api.py` (переименовать fixture, класс тот же):**
   - `TestRefreshAfterPageChange` (2 теста): `refresh_content_does_not_crash`, `refresh_action_does_not_crash`
   - `TestConnectStack` (2 теста): `connect_stack_auto_refresh_content`, `connect_stack_auto_refresh_action`
   - `TestAutoPickInnerScrolls` (1 тест): `set_content_widget_auto_picks_inner_scrolls`

   **Дополнительно (новое):**
   - `TestColumnarLayoutStructure` (3 теста): `set_title_updates_groupbox`, `set_nav_widget_replaces_placeholder`, `set_content_widget_attaches_to_scroll`
   - `TestViewModeToggleProperty` (2 теста): `view_mode_toggle_property_returns_instance`, `view_mode_toggle_property_initial_mode_is_cards`

   **Итого: ≥ 28 тестов.**

3. Fixture `layout` в `test_columnar_tab_layout.py` создаёт `ColumnarTabLayout(title="Test")` (не через alias).
4. Удалить файлы: `standard_layout.py`, `standard_tab_layout.py`, `test_standard_tab_layout.py`, `test_diff_scroll_tab_layout_public_api.py`.
5. Обновить `__init__.py` в обоих пакетах: убрать `StandardTabLayout` из `__all__` и из импортов.
6. Запустить `python scripts/validate.py` — нет broken imports.
7. Запустить `pytest multiprocess_framework/modules/frontend_module/tests/test_columnar_tab_layout.py -v` — все ≥ 28 тестов зелёные.

**Acceptance criteria:**
- [ ] `grep -rn "StandardTabLayout" multiprocess_framework/modules/ multiprocess_prototype/frontend/widgets/tabs/` → 0 результатов
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_columnar_tab_layout.py` — ≥ 28 тестов, все зелёные
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — не меньше тестов чем baseline (±5 от delta Phase 0)

**Out of scope:** Не удалять `diff_scroll_tab_layout.py` из prototype — thin alias остаётся. Не трогать QSS — уже обновлён в Task 1.0.

**Dependencies:** Task 3.1

---

## Phase 5 — Закрытие

### Task 5.1 — ADR-128 закрыть + docs/refactors/ отчёт + план DONE

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Зафиксировать закрытие ADR-128; создать отчёт рефакторинга; закрыть план.

**Context:** QSS уже обновлён в Task 1.0, переименование сделано. Здесь — финальная проверка чистоты кодовой базы и документация. Отчёт `docs/refactors/2026-05_columnar_unify.md` нужен для ретроспективы (по стандарту проекта для значимых рефакторов).

**Files:**
- `multiprocess_framework/DECISIONS.md` — закрыть ADR-128 (добавить дату закрытия)
- `docs/refactors/2026-05_columnar_unify.md` — СОЗДАТЬ (краткий отчёт ~30-40 строк)
- `plans/columnar-tab-unify/plan.md` — статус DRAFT → DONE

**Steps:**
1. `grep -rn "DiffScroll" multiprocess_prototype/frontend/styles/` — убедиться 0 результатов. `grep -rn "DiffScroll" multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/` — убедиться 0 результатов (кроме комментариев в DECISIONS.md).
2. Проверить objectName'ы в `ColumnarTabLayout._build_ui` — они должны совпадать с QSS-правилами (`ColumnarNavGroup`, `ColumnarActions`, `ColumnarNav`, `ColumnarContent`, `ColumnarMaster`).
3. Создать `docs/refactors/2026-05_columnar_unify.md` с разделами: «Что сделано», «Стратегия (Гибрид)», «Метрики до/после», «Что вне scope», «Связанные ADR».
   - В разделе «Что сделано» зафиксировать: **ViewModeToggle перемещён из `multiprocess_prototype/frontend/forms/` в `multiprocess_framework/modules/frontend_module/widgets/`** — побочный архитектурный win (устранён layer violation).
4. В `DECISIONS.md` добавить в ADR-128 дату закрытия и ссылку на отчёт.
5. В `plans/columnar-tab-unify/plan.md` обновить `Статус: DRAFT` → `Статус: DONE`.
6. Коммит `docs(plans): columnar-tab-unify DONE — Phase 5`.

**Acceptance criteria:**
- [ ] `grep -rn "DiffScroll" multiprocess_prototype/frontend/styles/` → 0 результатов
- [ ] `grep -rn "DiffScrollLeft\|DiffScrollRight\|DiffScrollNavGroup" multiprocess_framework/` → 0 результатов (кроме `DECISIONS.md`)
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — зелёный
- [ ] `docs/refactors/2026-05_columnar_unify.md` существует, содержит упоминание переноса ViewModeToggle в framework
- [ ] `plans/columnar-tab-unify/plan.md` статус DONE

**Out of scope:** Не мигрировать ProcessesTab, PluginsTab — это отдельные планы. Не удалять `diff_scroll_tab_layout.py` alias из prototype.

**Dependencies:** Task 4.1

---

## Будущие миграции (вне scope этого плана)

Зафиксированные договорённости для следующих планов:

| Вкладка | Статус | Договорённость |
|---------|--------|----------------|
| **ProcessesTab** | Вне scope | Health panel остаётся **внутри content-страницы «Все процессы»** (sticky-сверху контента, не в nav, не в action). Не делать sticky на уровне layout. |
| **PluginsTab** | Вне scope | Поиск + фильтр → composited `PluginNavWidget(QWidget)` через `set_nav_widget()`. QSplitter (`MasterDetailLayout`) заменяется на `ColumnarTabLayout`. |
| **DisplaysTab** | Defer | Структура неизвестна. Проверить при необходимости. |
| **ServicesTab** | Defer | Структура неизвестна. Проверить при необходимости. |
| **PipelineTab** | Никогда | Graph-view (QSplitter + canvas). Несовместим с columnar layout. |

---

## Открытые вопросы

Все вопросы закрыты:
- **ViewModeToggle**: перемещается в framework (Task 1.0), встроен в layout (Task 1.1). Thin re-export shim в prototype. Toggle opt-out (виден по умолчанию, скрывается явным вызовом).
- **QSS rename**: `diff_scroll.qss` → `columnar.qss` в Task 1.0 (не в Phase 5). Полный mapping objectName'ов задокументирован в Task 1.0.

---

## Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Регрессия Settings (baseline качества) | Средняя | Высокое | Phase 2: все 128 тестов Settings зелёные + visual smoke до merge |
| QSS objectName'ы: Settings теряет стили | Высокая | Среднее | Task 1.0 обновляет оба QSS файла (columnar.qss + main.qss); acceptance criteria включает visual smoke |
| layer rule нарушен при импорте ViewModeToggle | Высокая → **Закрыт** | Высокое | Task 1.0: toggle перемещён в framework, нарушения нет |
| `view_mode_changed` без обработчика у потребителя | Средняя | Низкое | Warning в лог. Settings явно вызывает `hide_view_mode_toggle()`. Recipes явно подключает сигнал. |
| Guard `set_action_widget` + `add_top_action` конфликт | Низкая | Низкое | Warning в лог + очистка layout; тест `TestGuardSetActionWidget` покрывает оба сценария |
| Тесты Standard/DiffScroll потеряны при удалении | Высокая (без митигации) | Высокое | Task 4.1: 28 тестов сначала переписываются, только потом удаляются исходники |
| Shim в `forms/view_mode_toggle.py` сломает импорты в processes/settings | Средняя | Среднее | Task 1.0 step 9: явная проверка `from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle` |

---

## Метрики до/после

| Метрика | До (baseline) | После (Phase 5) |
|---------|---------------|-----------------|
| Конкретных layout-классов | 2 (`DiffScrollTabLayout` + `StandardTabLayout`) | 1 (`ColumnarTabLayout`) |
| LOC layout-классов | ~856 (419 + 437) | ~480–500 (rename + extend, без Standard) |
| Файлов layout в framework | 2 + 1 abstract = 3 | 1 + 1 abstract = 2 |
| Тест-файлов layout | 2 (23 + 5 = 28 тестов) | 1 (28+ тестов в `test_columnar_tab_layout.py`) |
| `# type: ignore[attr-defined]` в `recipes/tab.py` | 4 | 0 |
| ADR | ADR-126 + ADR-127 | ADR-126 + ADR-127(superseded) + ADR-128(closed) |
| Потребителей на `ColumnarTabLayout` | 1 (Settings) | 2 (Settings + Recipes) |
| `ViewModeToggle` location | `multiprocess_prototype/frontend/forms/` | `multiprocess_framework/modules/frontend_module/widgets/` |
| QSS-файл layout | `diff_scroll.qss` | `columnar.qss` |

---

## Что точно не делаем (Out of scope)

- **Не** создаём `ColumnarTabLayout` с нуля (600 LOC) — только rename + extend.
- **Не** мигрируем `ProcessesTab`, `PluginsTab`, `DisplaysTab`, `ServicesTab` — отдельные планы.
- **Не** трогаем `PipelineTab` — graph-view, несовместим.
- **Не** добавляем sub-nav API в `ColumnarTabLayout` — он не нужен ни одному текущему потребителю.
- **Не** вводим новые UI-фичи (animated toggle, resizable columns, theme switching).
- **Не** трогаем presenter-логику, `RecipeFormWidget`, `RecipesPresenter`, секции Settings.
- **Не** создаём отдельный `columnar_tab_layout.py` рядом со старым — rename, не дублирование.

---

## Верификация перед закрытием плана

```bash
# Базовая валидация импортов и ADR-sync
python scripts/validate.py

# Полный прогон
python scripts/run_framework_tests.py

# Тесты layout (новый файл)
pytest multiprocess_framework/modules/frontend_module/tests/test_columnar_tab_layout.py -v

# Тесты потребителей
pytest multiprocess_prototype/frontend/widgets/tabs/settings/ -v
pytest multiprocess_prototype/frontend/widgets/tabs/recipes/ -v

# Проверка: нет старых имён в framework/prototype (кроме DECISIONS.md и alias)
grep -rn "StandardTabLayout" multiprocess_framework/modules/ multiprocess_prototype/frontend/widgets/tabs/
# Ожидаемый результат: 0

grep -rn "DiffScrollTabLayout" multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/
# Ожидаемый результат: только __init__.py (thin shim) или 0

# QSS чистота
grep -rn "DiffScroll" multiprocess_prototype/frontend/styles/
# Ожидаемый результат: 0

# ViewModeToggle layer
grep -rn "from multiprocess_prototype" multiprocess_framework/
# Ожидаемый результат: 0
```

---

## Оценка трудоёмкости

| Phase | Задача | Уровень | Оценка |
|-------|--------|---------|--------|
| Phase 0 | 0.1 ADR + baseline | Senior | ~1 ч |
| Phase 1 | 1.0 Move ViewModeToggle + QSS rename | Middle+ | ~1–1.5 ч |
| Phase 1 | 1.1 rename + extend + toggle встроенный | Senior+ | ~3–4 ч |
| Phase 2 | 2.1 Settings + hide_toggle | Middle+ | ~1–1.5 ч |
| Phase 3 | 3.1 Recipes pilot | Senior | ~1.5–2 ч |
| Phase 4 | 4.1 удаление + 28 тестов | Middle+ | ~2–2.5 ч |
| Phase 5 | 5.1 docs + закрытие | Middle | ~0.5–1 ч |
| **Итого** | **6 задач** | | **~11–14 ч** |

Добавленные задачи (Task 1.0) расширили оценку на ~1.5–2 ч относительно исходных 10–12 ч. Основной риск по трудоёмкости — Task 1.1 (интеграция toggle в layout + Guard + тесты).
