# Frontend Module — конструктор: рефакторинг и эволюция

- **Slug:** frontend-extract-bridge-primitives
- **Дата:** 2026-05-23
- **Статус:** DRAFT
- **Ветка:** feat/frontend-extract-bridge-primitives
- **Автор:** Manager (Sonnet)

---

## История ревизий

- **v2 (2026-05-23)**: Применены правки ревьюера — K1/K2/K3 (критичные), V1-V8 (важные), T1-T4 (тактические). Подробности в комментариях к каждой задаче.

---

## TL;DR

Три фазы рефакторинга `frontend_module`:

- **Фаза 1** — вынос созревших элементов (`bridge/`, primitives) + техгигиена (`qt_imports`, тесты менеджеров)
- **Фаза 2** — small wins реорганизации: deprecated мёртвый стек, убрать хардкод, завершить миграцию `graph/`, закрыть ADR-090
- **Фаза 3** — реструктуризация пакетов (13 → 7), scaffold CLI (отложено до стабилизации прототипа)

---

## Контекст и обоснование

Аудит `frontend_module` выявил:

- **6 файлов `bridge/`** (wire_protocol, diff_engine, system_commands, wire_monitor, command_sender, command_validator) — pure Python, 0 зависимостей от прото; готовы к переносу во фреймворк.
- **4 primitive-виджета** — pure PySide6, 0 зависимостей от прото; также готовы к переносу.
- **40 файлов** делают прямые `from PySide6.*` вместо `core/qt_imports` — консолидация.
- **Декларативный стек** (`WidgetRegistry`, `layout_composer`, `default_factories`, `widget_descriptor`) — 0 потребителей в прото после 4+ месяцев. Канонический путь — императивный BaseWidget.
- **`_ORG = "Inspector"`** в `prefs_store.py` — утечка домена прото в framework.
- **`graph/`** — уже перенесён в framework ранее (dag_utils + layout), прото использует re-export shims (`pipeline/dag_utils.py`, `pipeline/layout.py`). Требует завершения: обновить потребителей на прямой импорт.
- **ADR-090** (координаторы) — в прото нет ни одного файла с `coordinators/`; концепция не реализована и требует резолюции.
- **Фаза 3** (структурная реорганизация 13 → 7 пакетов, scaffold CLI) — отложено до стабилизации прото.

---

## Порядок выполнения

```
Фаза 1:   A1 ║ A2  →  B1 ║ B2 ║ B3 ║ C1 ║ C2 ║ C3  (B2, B3, C1-C3 параллельно после A1+A2)
Фаза 2:   2.1 ║ 2.2 ║ 2.3 ║ 2.4  (все параллельно, после завершения Фазы 1)
Фаза 3:   3.1  →  3.2  →  3.3  →  3.4  →  3.5  (последовательно, после стабилизации прото)
```
<!-- V8: C1-C3 зависят от B1 только в смысле стабильности импортов, но менеджеры
     (FrontendManager, WindowManager, ThemeManager) уже используют qt_imports.
     C1-C3 не ждут B1 — они могут идти параллельно с B1, B2, B3.
     Это сокращает elapsed time Фазы 1 примерно на 30%. -->

---

## Фаза 1: Вынос созревших элементов + техгигиена

### Task A1 — Вынос `bridge/` подпакета во framework

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** скопировать 6 файлов `bridge/` из прототипа в `frontend_module/bridge/`,
исправить единственную прото-ссылку (`GuiProcess` → Protocol/Any) и добавить
re-export в прото-`__init__.py` для обратной совместимости.
**Context:** шесть файлов — pure Python без зависимостей от прото; единственный
грязный edge — `TYPE_CHECKING` lazy import `GuiProcess` в `command_sender.py`.
После переноса все 42 точки использования в прото работают через re-export.
**Module contract:** new-full (новый подпакет ≥3 файлов с публичным API)

**Files:**
- `multiprocess_framework/modules/frontend_module/bridge/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/wire_protocol.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/diff_engine.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/system_commands.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/wire_monitor.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/command_sender.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/command_validator.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/README.md` — создать (contract-first)
- `multiprocess_prototype/frontend/bridge/__init__.py` — добавить re-export из fw

**Steps:**
<!-- K2: Step 2 с созданием _GuiProcessLike удалён — используем существующий IProcess (строки 17-24 command_sender.py) -->
1. Скопировать `wire_protocol.py`, `diff_engine.py`, `system_commands.py`,
   `wire_monitor.py`, `command_validator.py` дословно (без правок — нет зависимостей).
2. Скопировать `command_sender.py`; удалить `TYPE_CHECKING` импорт
   `from ..process import GuiProcess` (строки ~14-16); заменить аннотацию
   `"GuiProcess | IProcess"` (строка ~38) на просто `IProcess`.
   Существующий `IProcess` (строки 17-24, Protocol с двумя аргументами
   `send_message(target: str, msg: dict[str, Any]) -> None`) остаётся без изменений
   и реэкспортируется вместе с файлом.
3. Создать `frontend_module/bridge/__init__.py` с `__all__` — реэкспортирует все
   публичные символы из 6 модулей (те же, что сейчас в прото-`bridge/__init__.py`,
   кроме `DataReceiverBridge` — он не переносится).
4. Создать `bridge/README.md` — назначение подпакета, список публичных классов,
   stability marker (`partial` → `contract` после тестов C1-C3).
5. В прото-`bridge/__init__.py`: заменить прямые импорты из `.wire_protocol`,
   `.diff_engine` и т.д. на импорты из
   `multiprocess_framework.modules.frontend_module.bridge.*`;
   сохранить строку `from ..bridge_impl import DataReceiverBridge` и
   `from .command_catalog import ...`, `from .topology_bridge import ...` (они остаются
   в прото).
5.5. **[K1]** В прототипе заменить КАЖДЫЙ из 6 оригинальных файлов на однострочный
   re-export shim — так все 17 потребителей, импортирующих напрямую из подмодулей
   (`from multiprocess_prototype.frontend.bridge.command_sender import CommandSender`),
   продолжат работать:
   ```python
   """Re-export из framework (Phase 1, A1)."""
   from multiprocess_framework.modules.frontend_module.bridge.command_sender import *  # noqa: F401, F403
   from multiprocess_framework.modules.frontend_module.bridge.command_sender import __all__  # noqa: F401
   ```
   Применить аналогично к `wire_protocol.py`, `diff_engine.py`, `system_commands.py`,
   `wire_monitor.py`, `command_validator.py`. После замены в каждом файле не должно
   остаться определений классов/функций — только re-export.
6. Прогнать существующие тесты в `bridge/tests/` — все должны пройти без правки
   (импортируют из `multiprocess_prototype.frontend.bridge`, что теперь re-export).

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.bridge import WireConfig, CommandSender, WireStatusMonitor"` без ошибок
- [ ] `python -c "from multiprocess_prototype.frontend.bridge import WireConfig, CommandSender"` без ошибок (re-export работает)
- [ ] `python -c "from multiprocess_prototype.frontend.bridge.command_sender import CommandSender"` без ошибок (прямой импорт из подмодуля работает)
- [ ] `grep -c "^class\|^def " multiprocess_prototype/frontend/bridge/command_sender.py` возвращает `0` (только re-export, без определений)
- [ ] То же проверить для остальных 5 shim-файлов: `wire_protocol.py`, `diff_engine.py`, `system_commands.py`, `wire_monitor.py`, `command_validator.py`
- [ ] `python scripts/run_framework_tests.py` зелёный (все прото-тесты bridge/)
- [ ] `mcp__sentrux__check_rules` — 0 новых нарушений boundary `framework → prototype`
- [ ] `make check` (ruff + pyright + bandit) зелёный

**Out of scope:**
- Не переносить `command_catalog.py`, `topology_bridge.py` (зависимости от прото)
- Не удалять и не переименовывать файлы в `multiprocess_prototype/frontend/bridge/` (только заменять содержимое на shims)
- Не менять публичный API (сигнатуры классов и функций)
- Не создавать тесты для новых файлов (это Task C1)

**Edge cases:**
- `system_commands.py` использует `TYPE_CHECKING: from .wire_protocol import WireConfig` —
  после копирования в один пакет этот относительный импорт корректен, проверить.
- `wire_monitor.py` зависит от `command_sender.py` (проверить граф импортов внутри
  подпакета перед копированием).

**Dependencies:** нет (первый в цепочке)

---

### Task A2 — Вынос primitive-виджетов во framework

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** перенести 4 primitive-виджета из `multiprocess_prototype/frontend/widgets/primitives/`
в `multiprocess_framework/modules/frontend_module/components/primitives/` и добавить
re-export в прото-`__init__.py`.
**Context:** виджеты — pure PySide6, 0 зависимостей от прото-пакета.
<!-- K3: директория widgets/primitives/ во фреймворке НЕ существует. Реальные framework-primitives
     живут в components/primitives/ (control_label.py, numeric_line_edit.py, styled_slider.py,
     value_bridge.py). Целевой путь исправлен с widgets/primitives/ → components/primitives/ -->
Директория `components/primitives/` во фреймворке уже существует (содержит
`control_label.py`, `numeric_line_edit.py`, `styled_slider.py`, `value_bridge.py`);
нужно дополнить её 4 новыми виджетами.
**Module contract:** public-api-change (расширение существующего подпакета)

**Files:**
- `multiprocess_framework/modules/frontend_module/components/primitives/status_indicator.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/entity_card.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/crud_table.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/master_detail.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/__init__.py` — обновить (добавить 4 новых символа в `__all__`)
- `multiprocess_prototype/frontend/widgets/primitives/__init__.py` — обновить (добавить re-export из fw для 4 символов)

**Steps:**
1. Скопировать 4 файла дословно (нет зависимостей, нет правок).
2. Обновить `frontend_module/components/primitives/__init__.py`:
   добавить импорты и символы в `__all__`:
   `StatusIndicator`, `EntityCard`, `CardAction`, `CrudTable`, `MasterDetailLayout`.
   **Замечание:** если 4 переносимых виджета (UI-карточки, таблицы) семантически
   конфликтуют с существующими control-primitives (control_label, slider, numeric_input) —
   escalate в teamlead для решения, нужна ли отдельная директория. Решение
   зафиксировать в ADR (локальный `DECISIONS.md` или отдельный ADR в `DECISIONS.md` фреймворка).
3. Обновить прото-`__init__.py`: для 4 перенесённых символов сделать re-export из
   `multiprocess_framework.modules.frontend_module.components.primitives`:
   ```python
   # re-export перенесённых primitives из фреймворка
   from multiprocess_framework.modules.frontend_module.components.primitives import (
       StatusIndicator,
       EntityCard,
       CardAction,
       CrudTable,
       MasterDetailLayout,
   )
   ```
   Остальные символы (ActionToolbar, SlotSelector и т.д.) остаются локальными.
4. Убедиться, что `from multiprocess_prototype.frontend.widgets.primitives import
   StatusIndicator` продолжает работать.

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.primitives import StatusIndicator, EntityCard, CrudTable, MasterDetailLayout"` без ошибок
- [ ] `python -c "from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator"` без ошибок (re-export)
- [ ] `make check` зелёный
- [ ] Существующие тесты `test_primitives_batch1.py`, `test_primitives_batch2.py` зелёные

**Out of scope:**
- Не переносить ActionToolbar, SlotSelector, SectionedForm, SideNavLayout, StandardTabLayout,
  DiffScrollTabLayout, TreeNavWidget (они в активной разработке или зависимы)
- Не удалять исходные файлы из прото

**Edge cases:**
- Проверить, что `entity_card.py` экспортирует `CardAction` — он нужен в `__init__.py`.
- Если выявлен семантический конфликт типов primitives — см. замечание в Step 2.

**Dependencies:** нет (параллельно с A1)

---

### Task B1 — Расширение `core/qt_imports.py` и замена прямых PySide6-импортов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** добавить ~12 отсутствующих Qt-символов в `core/qt_imports.py` и заменить
прямые `from PySide6.*` на `from frontend_module.core.qt_imports import ...`
в проблемных файлах.
**Context:** 40 файлов фреймворка импортируют PySide6 напрямую. `qt_imports.py`
создан именно как единая точка — нужно довести консолидацию. После этого
поиск «используемых Qt-символов» будет тривиальным grep по одному файлу.
**Module contract:** public-api-change (расширение `__all__` существующего модуля)

**Files:**
<!-- V1: список файлов НЕ фиксируется статически — реальных файлов 24+, пропускаются
     forms/form_context.py, widgets/tabs/base_columnar_tab.py, core/qt_thread_guard.py,
     core/prefs_store.py, widgets/tabs/tab_layout_protocol.py, widgets/tabs/section_protocol.py.
     Полный список определяется динамически на Step 1. -->
- `multiprocess_framework/modules/frontend_module/core/qt_imports.py` — расширить импорты и `__all__`
- **Все файлы** из `multiprocess_framework/modules/frontend_module/` (исключая `core/qt_imports.py`,
  `tests/`, `__pycache__/`), которые содержат `from PySide6` — определяются на Step 1.
  Ориентировочный список (~24 файла), включая:
  `widgets/entity_editor/entity_tree_widget.py`, `widgets/entity_editor/base_editor_tree.py`,
  `widgets/entity_editor/params_form.py`, `widgets/entity_editor/base_editor_toolbar.py`,
  `widgets/entity_editor/schema_inspector_panel.py`, `widgets/tabs/base_tree_nav_tab.py`,
  `widgets/tabs/base_list_nav_tab.py`, `widgets/tabs/nav_tree_utils.py`,
  `widgets/tabs/current_page_stack.py`, `widgets/tabs/tab_layouts/diff_scroll_layout.py`,
  `widgets/tabs/tab_layouts/standard_layout.py`, `widgets/tabs/tab_layouts/_abstract_columnar.py`,
  `widgets/tabs/base_columnar_tab.py`, `widgets/tabs/tab_layout_protocol.py`,
  `widgets/tabs/section_protocol.py`, `managers/theme_manager.py`,
  `widgets/chrome/app_header/widget.py`, `widgets/chrome/recording_indicator/widget.py`,
  `widgets/chrome/side_panels/collapsible.py`, `widgets/chrome/watchdog_overlay/widget.py`,
  `forms/form_context.py`, `core/qt_thread_guard.py`, `core/prefs_store.py`
  (и возможные другие — актуальный список только из Step 1)

**Steps:**
1. Составить полный список символов из `from PySide6.*` по всем 40 файлам
   (grep) — вычесть уже имеющиеся в `qt_imports.py`.
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
- [ ] `grep -r "from PySide6\." multiprocess_framework/modules/frontend_module/ --include="*.py"` возвращает только `core/qt_imports.py` и файлы под `TYPE_CHECKING` (допустимо)
- [ ] `make check` зелёный (ruff + pyright)
- [ ] `python scripts/run_framework_tests.py` зелёный

**Out of scope:**
- Не трогать файлы вне `frontend_module` (прото, сервисы, плагины)
- Не переименовывать символы Qt
- Не менять логику файлов — только строки импортов

**Edge cases:**
- `tab_layout_protocol.py` и `section_protocol.py` используют PySide6 только под
  `TYPE_CHECKING` — для TYPE_CHECKING-блоков замена допустима, но можно оставить
  напрямую если pyright не ругается. Принять решение по месту.
- `base_list_nav_tab.py` использует `QIcon` только под `TYPE_CHECKING` — аналогично.

**Dependencies:** A1, A2 (bridge/ и primitives/ должны быть в фреймворке, иначе
шаг 1 даст неполный список файлов)

---

### Task B2 — Устранение дублирования в `EntityTreeWidget`

**Level:** Junior (developer, normal thinking)
**Assignee:** developer
**Goal:** извлечь приватный метод `_build_level_row` из дублирующихся
`_build_parent_row` и `_build_child_row` в `entity_tree_widget.py`.
**Context:** 554-строчный файл. Методы строки 218-258 и 260-303 идентичны на 80%.
Рефакторинг устраняет divergence-риск при будущих изменениях UI-формата строк.
**Module contract:** impl-only

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/entity_editor/entity_tree_widget.py`

**Steps:**
1. Создать приватный метод `_build_level_row`:
   ```python
   def _build_level_row(
       self,
       level,           # EntityLevel (parent_level или child_level из конфига)
       display_key: str,
       role_type: str,          # "parent" | "child"
       data: dict,
       *,
       role_parent: str,
       role_child: str | None = None,
   ) -> list[QStandardItem]:
   ```
   Внутри — общая логика создания `name_item`, `val_item`, `comment_item`, `summary_item`.
2. В `_build_parent_row` — делегировать `_build_level_row` с `role_type="parent"`,
   `role_child=None`.
3. В `_build_child_row` — делегировать `_build_level_row` с `role_type="child"`,
   передать `parent_key` как `role_parent`, `child_key` как `role_child`.
4. Убедиться, что тесты, использующие tree widget, не упали (тест в
   `tests/test_base_tree_nav_tab.py` или аналог).

**Acceptance criteria:**
- [ ] `entity_tree_widget.py` уменьшился на 25-35 строк
- [ ] `_build_parent_row` и `_build_child_row` вызывают `_build_level_row` (нет дублирования)
- [ ] `python scripts/run_framework_tests.py` зелёный
- [ ] `make check` зелёный

**Out of scope:**
- Не менять публичный API `entity_tree_widget.py`
- Не рефакторить другие методы файла
- Не добавлять тесты (уже есть)

**Edge cases:**
- Убедиться, что в `_build_parent_row` иконка не зависит от `child_key` (в parent_row
  его нет) — в общем методе параметр `role_child` = `None`, `setData` для `ROLE_CHILD`
  вызывается только если не None.

**Dependencies:** B1 (замена импортов не должна конфликтовать с рефакторингом)

---

### Task B3 — README для подпакетов `frontend_module`

**Level:** Junior (Haiku, normal thinking)
**Assignee:** docs-writer
**Goal:** создать минимальные README (≤1 экрана) для 6 подпакетов, у которых его нет.
**Context:** из 13 подпакетов верхнего уровня только `components/` имеет README.
Этап 8 STATUS.md — «Финальная документация». Минимальный README: назначение +
ключевые публичные символы + ссылка на корневой README.
**Module contract:** n/a (только документация)

**Files (создать):**
- `multiprocess_framework/modules/frontend_module/application/README.md`
- `multiprocess_framework/modules/frontend_module/widgets/README.md`
- `multiprocess_framework/modules/frontend_module/managers/README.md`
- `multiprocess_framework/modules/frontend_module/core/README.md`
- `multiprocess_framework/modules/frontend_module/schemas/README.md`
- `multiprocess_framework/modules/frontend_module/configs/README.md`

**Steps:**
<!-- T4: список подпакетов без README может измениться после A1 и A2 -->
0. Перед началом — повторный glob по подпакетам `frontend_module` и проверка наличия
   `README.md`. После A1 `bridge/` уже получит README (создаётся там — не дублировать).
   После A2 `components/primitives/` может получить README (уточнить у исполнителя A2).
   Актуализировать список файлов для создания.
1. Прочитать `__init__.py` каждого подпакета — определить публичные символы.
2. Для каждого создать README по шаблону:
   ```markdown
   # <имя> — <назначение одной строкой>

   ## Ключевые символы
   - `ClassName` — что делает
   ...

   ## Stability
   partial | contract | lite

   → Корневой README: `../../README.md`
   ```
3. Не включать в README внутренние (`_*`) классы.

**Acceptance criteria:**
- [ ] Все 6 файлов созданы
- [ ] Каждый README ≤ 30 строк
- [ ] `make check` не ломается (ruff не проверяет .md)

**Out of scope:**
- Не создавать README для `bridge/` (создан в A1) и `components/` (уже есть)
- Не писать ADR (это task tech-writer)
- Не обновлять корневой README модуля

**Dependencies:** A1 (bridge/README.md создаётся там; B3 не дублирует его)

---

### Task C1 — Unit-тесты `FrontendManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `application/frontend_manager.py` на ≥60% unit-тестами
с моком Qt и зависимостей фреймворка.
**Context:** FrontendManager — самый критичный класс модуля (223 LOC): initialize,
run_app, shutdown_app, config hot-reload через подписку. Сейчас 0 тестов. Этап 7
STATUS.md.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_frontend_manager.py` — создать

**Steps:**
1. Определить стратегию мокирования:
   - `QApplication` — мок через `pytest-qt` (`qtbot`) или `unittest.mock.patch`
   - `WindowManager` — мок-объект с `show/close/register`
   - `ThreadManager` — мок-объект
   - `FrontendRegistersBridge` — мок
   - `BaseManager.initialize` — patch
2. Тест-кейсы:
   - `test_initialize_sets_managers` — после `initialize()` атрибуты заполнены
   - `test_run_app_calls_window_manager` — `run_app()` вызывает `window_manager.show_main()`
   - `test_shutdown_app_calls_cleanup` — `shutdown_app()` вызывает teardown-методы
   - `test_config_hotreload_emits_signal` — подписка на config_module, изменение
     конфига → emit `config_changed`
   - `test_initialize_without_process` — инициализация без process не бросает
3. Формат тестов: `pytest`, given/when/then комментарии.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_frontend_manager.py -v` — все тесты зелёные
- [ ] Coverage `application/frontend_manager.py` ≥ 60% (`pytest --cov`)
- [ ] Нет импортов из `multiprocess_prototype` в тестовом файле
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать `WindowManager`, `ThemeManager` здесь (это C2/C3)
- Не тестировать реальный Qt event loop (только мок)

**Edge cases:**
- `FrontendManager` наследует `BaseManager` + `ObservableMixin` — моки должны учитывать
  MRO и то, что `initialize()` вызывает `super().initialize()`

**Dependencies:** A1, A2 (bridge/ и primitives/ должны быть во фреймворке; B1 не требуется — менеджеры уже используют qt_imports)

---

### Task C2 — Unit-тесты `WindowManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `application/window_manager.py` на ≥60% unit-тестами.
**Context:** WindowManager — реестр окон (221 LOC): register, show, close,
fullscreen, access_level, cursor. Сейчас 0 тестов.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_window_manager_unit.py` — создать
  (NB: `test_window_registry.py` уже есть — это другой класс, не дублировать)

**Steps:**
1. Стратегия мокирования:
   - `QObject.__init__` — pytest-qt `qapp` fixture (нужен реальный `QApplication`)
   - Окна — мок-объекты с `show()`, `hide()`, `showFullScreen()`
   - `WindowRegistry` — использовать реальный (он не Qt)
2. Тест-кейсы:
   - `test_register_window` — `register()` добавляет в реестр
   - `test_show_registered_window` — `show_window(name)` вызывает `window.show()`
   - `test_close_all` — `close_all()` вызывает `hide()` на всех окнах
   - `test_access_level_restricts_visibility` — при `access_level < required` окно
     не показывается
   - `test_show_unknown_window_raises` — `show_window("unknown")` → ValueError или
     warning (проверить по коду)
   - `test_config_get_dict` — хелпер `_config_get` с dict и dot-notation
3. Формат: `pytest`, given/when/then.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_window_manager_unit.py -v` — зелёный
- [ ] Coverage `application/window_manager.py` ≥ 60%
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать `WindowRegistry` — уже есть `test_window_registry.py`
- Не тестировать реальный fullscreen (только мок)

**Edge cases:**
- `WindowManager(QObject)` требует `QApplication` до инициализации — fixture `qapp`
  из pytest-qt обязательна.

**Dependencies:** A1, A2 (не B1 — менеджеры уже используют qt_imports независимо)

---

### Task C3 — Unit-тесты `ThemeManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `managers/theme_manager.py` на ≥60% unit-тестами с файловой
изоляцией через `tmp_path`.
**Context:** ThemeManager (273 LOC): загрузка QSS, модульные темы (папка с
несколькими .qss), CSS-переменные (`@var` плейсхолдеры), hot-reload,
`variables.yaml`. Сейчас 0 тестов.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_theme_manager.py` — создать

**Steps:**
1. Стратегия: `tmp_path` для создания фиктивных `.qss` и `variables.yaml`.
   Мок `QApplication.instance().setStyleSheet` (или реальный `qapp` fixture).
2. Тест-кейсы:
   - `test_load_single_file_theme` — файл `styles/dark.qss` → `load_theme("dark")`
     вызывает `setStyleSheet`
   - `test_load_modular_theme` — папка `styles/themes/dark/*.qss` — файлы
     конкатенируются по алфавиту
   - `test_resolve_qss_variables` — `@bg_deep` заменяется на значение из словаря
   - `test_variables_from_yaml` — `variables.yaml` в папке темы подхватывается
   - `test_switch_theme` — `switch_theme("light")` → другой QSS применяется
   - `test_hot_reload` — повторный `load_theme()` → `setStyleSheet` вызван снова
   - `test_missing_theme_raises` — `load_theme("nonexistent")` → FileNotFoundError
     или warning (проверить по коду)
3. Формат: `pytest`, given/when/then.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_theme_manager.py -v` — зелёный
- [ ] Coverage `managers/theme_manager.py` ≥ 60%
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать реальный рендеринг Qt (только применение QSS)
- Не создавать реальные темы в `styles/` — только через `tmp_path`

**Edge cases:**
- `ThemeManager` использует `yaml` — убедиться, что `pyyaml` есть в dev-зависимостях
  (скорее всего есть, но проверить).
- Если `QApplication` не инициализирован, `setStyleSheet` может не работать —
  нужна `qapp` fixture.

**Dependencies:** A1, A2 (не B1 — менеджеры уже используют qt_imports независимо)

---

## Фаза 2: Small wins реорганизации

> **Статус:** PENDING. Стартует после полного завершения Фазы 1.
> Все задачи фазы выполняются параллельно — файловых конфликтов нет.

---

### Task 2.1 — ADR-128 + `@deprecated` на мёртвый декларативный стек

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer (код) + docs-writer (ADR)
**Goal:** зафиксировать в ADR-128, что декларативная сборка через дескрипторы провалилась,
и пометить 4 файла `@deprecated` — оставить до следующего пересмотра.
**Context:** 4 файла (`widget_registry`, `layout_composer`, `default_factories`,
`widget_descriptor`) существуют с момента создания модуля. За 4+ месяцев — 0 потребителей
в прото. Аудит qex/grep подтвердил: все упоминания WidgetRegistry — только внутри
тех же 4 файлов и `core/__init__.py`. Канонический путь — императивный `BaseWidget`.
ADR нужен чтобы зафиксировать решение и предупредить о сроках удаления.
**Module contract:** impl-only

**Files:**
- `multiprocess_framework/DECISIONS.md` — добавить ADR-128 в конец
- `multiprocess_framework/modules/frontend_module/DECISIONS.md` — добавить строку в индекс
- `multiprocess_framework/modules/frontend_module/core/widget_registry.py` (79 LOC) — `@deprecated`
- `multiprocess_framework/modules/frontend_module/core/layout_composer.py` (55 LOC) — `@deprecated`
- `multiprocess_framework/modules/frontend_module/core/default_factories.py` (136 LOC) — `@deprecated`
- `multiprocess_framework/modules/frontend_module/schemas/widget_descriptor.py` (97 LOC) — `@deprecated`

**Steps:**
1. Написать ADR-128 в `DECISIONS.md` по шаблону проекта:
   - **Контекст:** декларативный стек (дескрипторы + WidgetRegistry + LayoutComposer) создавался
     для автоматической генерации UI из конфигов. Прошло 4+ месяцев — 0 потребителей в прото.
   - **Решение:** помечаем deprecated с датой пересмотра через 2 спринта (или при появлении
     первого потребителя). Канонический путь — `BaseWidget[TModel]` + императивная сборка.
   - **Следствие:** удаление 4 файлов (~367 LOC) запланировано в Фазе 3 или раньше.
2. <!-- V4: разделить логику для классов и функций -->
   Для классов (`WidgetRegistry`, `LayoutComposer`, `WidgetDescriptor`) — добавить
   `warnings.warn` в `__init__`:
   ```python
   import warnings
   warnings.warn(
       "WidgetRegistry is deprecated (ADR-128). Use BaseWidget directly.",
       DeprecationWarning,
       stacklevel=2,
   )
   ```
   Для функций (`create_default_registry` в `default_factories.py`) — добавить
   `warnings.warn` в начало тела функции (не на уровне модуля, не при импорте):
   ```python
   def create_default_registry() -> WidgetRegistry:
       warnings.warn(
           "create_default_registry is deprecated (ADR-128). Use BaseWidget directly.",
           DeprecationWarning,
           stacklevel=2,
       )
       ...
   ```
3. В docstring каждого из 4 файлов добавить первой строкой:
   `DEPRECATED (ADR-128, 2026-05-23). Будет удалён в Фазе 3 при 0 потребителях.`
4. Запустить `python -m scripts.sync` для обновления сводных разделов DECISIONS.md.

**Acceptance criteria:**
- [ ] ADR-128 присутствует в `multiprocess_framework/DECISIONS.md`
- [ ] `python -m scripts.sync` завершается без ошибок (оглавление обновлено)
- [ ] Строка `DeprecationWarning` есть в `__init__` каждого из 4 классов
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_widget_descriptor.py` — проходит (DeprecationWarning в выводе — не ошибка)
- [ ] `python scripts/validate.py` зелёный

**Out of scope:**
- Не удалять файлы (это Фаза 3)
- Не реализовывать scaffold CLI (это Task 3.5)
- Не менять `core/__init__.py` — WidgetRegistry остаётся в публичном API (deprecated)

**Edge cases:**
- `DeprecationWarning` при импорте (не только в `__init__`) может шуметь в тестах.
  Правило: `warnings.warn` только в `__init__` класса, не на уровне модуля.
- `default_factories.py` создаёт `WidgetRegistry` внутри `create_default_registry()` —
  warning сработает при вызове конструктора, не при импорте функции.

**Dependencies:** нет (параллельно с 2.2, 2.3, 2.4)
**Module contract:** impl-only

---

### Task 2.2 — Убрать app-specific хардкод из framework (`prefs_store`)

**Level:** Junior (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** убрать `_ORG = "Inspector"` из framework `prefs_store.py` — это утечка
домена прото в фреймворк. Сделать `organization` параметром модуля.
**Context:** `prefs_store.py` хранит `_ORG = "Inspector"` — имя организации из
Windows Registry / macOS plist. Фреймворк не знает, как называется приложение-потребитель.
Текущие потребители: в прото нет прямых вызовов `prefs_store` (используется через
register bridge), но файл живёт в framework-пакете.
**Module contract:** public-api-change (изменение параметров публичных функций)

**Files:**
- `multiprocess_framework/modules/frontend_module/core/prefs_store.py`
- `multiprocess_prototype/frontend/registers_bridge.py` (или где prefs_store вызывается в прото — уточнить через `mcp__qex__search_code "prefs_store"` перед реализацией)

**Steps:**
1. Перед началом — найти всех потребителей: `mcp__qex__search_code "prefs_store OR get_view_mode OR set_view_mode"`.
2. Добавить переменную конфигурации модуля:
   ```python
   # prefs_store.py
   _ORGANIZATION: str = "frontend_module"  # generic default
   _APP = "ui_preferences"

   def configure(organization: str) -> None:
       """Установить имя организации для QSettings. Вызвать из app init."""
       global _ORGANIZATION
       _ORGANIZATION = organization

   def _settings() -> QSettings:
       return QSettings(_ORGANIZATION, _APP)
   ```
3. Убрать `_ORG = "Inspector"`.
4. В прото (`app.py` или `registers_bridge.py`): добавить вызов
   `prefs_store.configure("Inspector")` при инициализации.
5. Написать тест: `test_prefs_store_organization_isolation` — два вызова с разными
   organization → разные ключи QSettings не пересекаются (через `tmp_path` или
   мок `QSettings`).

**Acceptance criteria:**
- [ ] Строки `"Inspector"` нет в `prefs_store.py`
- [ ] `configure()` документирована в docstring файла
- [ ] Прото продолжает работать (вызов `configure("Inspector")` добавлен)
- [ ] `test_prefs_store_organization_isolation` проходит
- [ ] `make check` зелёный

**Out of scope:**
- Не делать env-variable fallback (`FRONTEND_ORG`) — оверинжиниринг для одного файла
- Не менять ключи `KEY_SETTINGS_MODE` / `KEY_RECIPES_MODE` / `KEY_HEADER_MODE`

**Edge cases:**
- `QSettings` на Windows использует Registry — в тестах нужен мок или изолированный
  `QSettings` через `IniFormat` + `tmp_path`.
- Если `configure()` не вызван — дефолт `"frontend_module"` не будет читать старые
  значения "Inspector". Миграция: прото явно вызывает `configure("Inspector")` при старте.
- <!-- T2: избежать global как изменяемого модульного состояния -->
  Не использовать `global _ORGANIZATION` как изменяемое модульное состояние — это anti-pattern.
  Предпочтительные варианты: (a) параметр функции
  `get_view_mode(key, organization='frontend_module')`, (b) `functools.partial` при
  инициализации. Выбор за developer/teamlead по месту.

**Dependencies:** нет (параллельно с 2.1, 2.3, 2.4)
**Module contract:** public-api-change

---

### Task 2.3 — Завершить миграцию `graph/`: удалить re-export shims в прото

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** `frontend_module/graph/` уже перенесён во framework. В прото остались
re-export shims `pipeline/dag_utils.py` и `pipeline/layout.py`. Найти всех
потребителей и переключить на прямой импорт из framework, затем удалить shims.
**Context:** При аудите обнаружено, что `graph/` в framework — это уже финальное
состояние (dag_utils.py + layout.py, ~430 LOC). Прото содержит два shim-файла
(`pipeline/dag_utils.py`, `pipeline/layout.py`) с однострочными re-export.
Пока shims живут — импортный граф засорён промежуточными узлами.
**Module contract:** impl-only

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/dag_utils.py` — удалить
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/layout.py` — удалить
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py` — обновить импорт (V3)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_dag_utils.py` — проверить импорты после удаления shims
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_layout.py` — проверить импорты
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_schema_driven_ports.py` — проверить импорты
- Все прочие файлы в `multiprocess_prototype/`, импортирующие из `pipeline.dag_utils` или
  `pipeline.layout` — обновить импорты (найти через `mcp__qex__search_code`)

**Steps:**
1. Найти всех потребителей shim-файлов:
   `mcp__qex__search_code "pipeline.dag_utils OR pipeline.layout"` в прото.
2. В каждом потребителе заменить:
   ```python
   # было
   from ...widgets.tabs.pipeline.dag_utils import has_cycle
   # стало
   from multiprocess_framework.modules.frontend_module.graph import has_cycle
   ```
3. <!-- V3: pipeline/model.py использует `from . import dag_utils` (относительный импорт) —
        после удаления shim сломается. Обновить явно. -->
   Обновить `pipeline/model.py`: заменить `from . import dag_utils` на
   `from multiprocess_framework.modules.frontend_module.graph import dag_utils`
   (или `from multiprocess_framework.modules.frontend_module import graph as dag_utils`
   если используется как модуль целиком — проверить по коду).
4. Удалить `pipeline/dag_utils.py` и `pipeline/layout.py`.
5. Убедиться, что `frontend_module.graph.__init__.py` экспортирует все нужные символы
   (`has_cycle`, `topological_sort`, `validate_port_compatibility`,
   `find_connected_edges`, `auto_layout`).
6. `mcp__sentrux__check_rules` — проверить 0 новых нарушений.

**Acceptance criteria:**
- [ ] `pipeline/dag_utils.py` и `pipeline/layout.py` удалены из прото
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.graph import has_cycle, auto_layout"` — без ошибок
- [ ] `python scripts/run_framework_tests.py` зелёный (тесты `graph/tests/` проходят)
- [ ] Все тесты в `pipeline/tests/` (`test_dag_utils.py`, `test_layout.py`, `test_schema_driven_ports.py`) зелёные после удаления shims
- [ ] `mcp__sentrux__check_rules` — 0 нарушений
- [ ] `make check` зелёный

**Out of scope:**
- Не трогать `graph/tests/` — они уже в framework
- Не переименовывать функции graph/

**Edge cases:**
- Pipeline tab может импортировать из shim-файлов через `from . import dag_utils` (relative)
  — проверить все относительные импорты внутри pipeline-пакета.
- Если shim использовался как `import pipeline.dag_utils as dag_utils` (module alias) —
  заменить на `import multiprocess_framework.modules.frontend_module.graph as dag_utils`.

**Dependencies:** нет (параллельно с 2.1, 2.2, 2.4)
**Module contract:** impl-only

---

### Task 2.4 — Резолюция ADR-090 (координаторы)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** ADR-090 декларирует слой координаторов между виджетом и managers,
но в прото нет ни одного файла `coordinators/` — концепция не реализована.
Решить: обобщить как framework-паттерн или закрыть.
**Context:** ADR-090 принят ранее, упомянут в `MODULE_CONTRACTS.md`. Grep по прото
вернул 0 файлов с `coordinators/`. `IDEAS_AND_IMPROVEMENTS.md` содержит эскиз
`ApplicationCoordinator`. Либо концепция нужна (тогда нужен минимальный blueprint
в framework), либо ADR закрывается как "не понадобилось — MVP-паттерн закрыл потребность".
**Module contract:** n/a

**Files:**
- `multiprocess_framework/DECISIONS.md` — обновить ADR-090: добавить резолюцию
- `multiprocess_framework/modules/frontend_module/DECISIONS.md` — обновить индекс
- `multiprocess_framework/docs/MODULE_CONTRACTS.md` — убрать или обновить упоминание координаторов

**Steps:**
1. Прочитать ADR-090 полностью (строка 1533 в DECISIONS.md).
2. Проверить `IDEAS_AND_IMPROVEMENTS.md` — есть ли реализованный аналог в прото.
3. Принять решение (вилка):
   - **Вариант A (закрыть):** координаторы не понадобились — MVP Presenter закрыл
     потребность. Добавить в ADR-090 раздел `## Резолюция: closed — superseded by MVP pattern`.
   - **Вариант B (обобщить):** написать минимальный `ApplicationCoordinator` blueprint
     (Protocol + комментарий назначения) в `application/coordinator.py` фреймворка.
     Добавить ADR-090 раздел `## Резолюция: implemented — см. application/coordinator.py`.
4. В любом варианте: убрать вводящую в заблуждение строку из `MODULE_CONTRACTS.md`
   или заменить на актуальный статус.
5. Запустить `python -m scripts.sync`.

**Acceptance criteria:**
- [ ] ADR-090 имеет раздел `## Резолюция:` с одним из двух статусов
- [ ] `MODULE_CONTRACTS.md` не содержит неактуального упоминания `coordinators/`
   как "ожидающей реализации" (либо обновлено, либо удалено)
- [ ] `python scripts/validate.py` зелёный

**Out of scope:**
- Не реализовывать полную систему координаторов (это отдельный план если вариант B)
- Не трогать MVP Presenter — он уже работает

**Edge cases:**
- Если teamlead выберет вариант B, реализация `coordinator.py` — минимум: один
  Protocol-класс с аннотациями, без боевого кода. Боевой код — отдельная задача
  следующего плана.

**Dependencies:** нет (параллельно с 2.1, 2.2, 2.3)
**Module contract:** n/a

---

## Фаза 3: Реструктуризация пакетов (отложено)

> **Статус:** PENDING. Стартует после стабилизации прото (≥2 спринта после Фазы 2).
> Самый рискованный этап — механическое перемещение 13 пакетов в 7.
> Требует: прото заморожен на рефакторинг, все тесты зелёные, sentrux baseline снят.

**Целевая иерархия пакетов:**

```
frontend_module/
  runtime/        # из application/ + core/(runtime: qt_thread_guard, registers_bridge, app_context, routed_command)
  contracts/      # из schemas/ + configs/ + forms/ + interfaces.py
  components/     # без изменений
  widgets/        # + windows/ влить (loading_window → widgets/windows/)
  managers/       # без изменений
  utils/          # из core/(utility: diagnostics, prefs_store, action_binding, schema_config)
  tests/
```

---

### Task 3.1 — Миграция auth_source + AccessTrait из `BaseConfigurableWidget` в `BaseWidget`

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** объединить два базовых виджета. `BaseWidget[TModel]` получает фичу
`auth_source` + `_wire_auth_source` + `_apply_access`. `BaseConfigurableWidget`
помечается deprecated.
**Context:** `BaseConfigurableWidget` (393 LOC) реализует `auth_source` + AccessTrait.
Единственный прото-потребитель — `permission_gate.py`. Дублирование с `BaseWidget`
накапливает расхождения. Аудит: `tests/test_base_widget_auth_source.py` уже
тестирует auth-поведение на `BaseWidget` — значит идея уже была, нужно завершить.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/base_widget/base_widget.py`
- `multiprocess_framework/modules/frontend_module/core/base_configurable_widget.py`
- `multiprocess_prototype/frontend/widgets/access/permission_gate.py`
- `multiprocess_framework/modules/frontend_module/tests/test_base_widget_auth_source.py` — расширить

**Steps:**
1. Изучить `_wire_auth_source`, `_on_auth_context_changed`, `_apply_access` в `BaseConfigurableWidget`.
2. Проверить `test_base_widget_auth_source.py` — какие методы уже тестируются на `BaseWidget`.
3. Перенести auth-логику как mixin или прямое расширение `BaseWidget`:
   - `_wire_auth_source(auth_source: Any) -> None`
   - `_on_auth_context_changed(ctx: Any) -> None`
   - `_apply_access() -> None`
   - параметр `auth_source` в `__init__`
4. Мигрировать `permission_gate.py` — убрать наследование от `BaseConfigurableWidget`,
   использовать `BaseWidget` с `auth_source`.
5. Пометить `BaseConfigurableWidget` deprecated: `warnings.warn(..., DeprecationWarning)`.
6. Расширить `test_base_widget_auth_source.py` — покрыть полный цикл auth-поведения.

**Acceptance criteria:**
- [ ] `BaseWidget` принимает параметр `auth_source` в `__init__`
- [ ] `permission_gate.py` использует `BaseWidget` (не `BaseConfigurableWidget`)
- [ ] `test_base_widget_auth_source.py` — все тесты зелёные
- [ ] `BaseConfigurableWidget` помечен `@deprecated`
- [ ] `make check` зелёный

**Out of scope:**
- Не удалять `BaseConfigurableWidget` (Фаза 3 только deprecated-маркировка)
- Не мигрировать другие потребители `BaseConfigurableWidget` (если они появились)

**Edge cases:**
- `BaseWidget` может быть generic `BaseWidget[TModel]` — параметр `auth_source`
  должен добавиться без ломающего изменения сигнатуры.
- MRO: если `BaseWidget` наследует несколько mix-ins — проверить порядок `super().__init__`.

**Dependencies:** зависит от завершения Фазы 2
**Module contract:** public-api-change

---

### Task 3.2 — Объединение `schemas/` + `configs/` + `forms/` + `interfaces.py` → `contracts/`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** под одной крышей `contracts/` — все типы границ модуля.
Уменьшение шума на top-level с 13 до 10 пакетов.
**Context:** `schemas/` (3 файла, ~340 LOC), `configs/` (3 файла, ~75 LOC),
`forms/` (1 файл, ~110 LOC), `interfaces.py` (~200 LOC) — логически одна зона.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/contracts/` — создать пакет
- `multiprocess_framework/modules/frontend_module/schemas/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/configs/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/forms/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/interfaces.py` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/__init__.py` — обновить публичный API

**Steps:**
1. Создать `contracts/` с `__init__.py` — реэкспортирует все публичные символы.
2. Переместить файлы в `contracts/`:
   - `schemas/register_binding.py`, `schemas/widget_descriptor.py` (deprecated) → `contracts/`
   - `configs/frontend_manager_config.py`, `configs/thread_manager_config.py`,
     `configs/window_manager_config.py` → `contracts/`
   - `forms/form_config.py` → `contracts/`
   - `interfaces.py` → `contracts/interfaces.py`
3. Старые пути оставить как re-export shims с `DeprecationWarning`.
4. Обновить `__init__.py` модуля — публичный API переключить на `contracts/`.
5. Добавить ADR о структуре `contracts/` в `frontend_module/DECISIONS.md`.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.contracts import FrontendManagerConfig` работает
- [ ] `from multiprocess_framework.modules.frontend_module.configs import FrontendManagerConfig` работает с `DeprecationWarning`
- [ ] `from multiprocess_framework.modules.frontend_module.interfaces import IFrontendManager` работает с `DeprecationWarning`
- [ ] Прото не сломан (re-exports работают)
- [ ] `make check` зелёный

**Out of scope:**
- Не удалять старые shim-пакеты (только deprecated)
- Не мигрировать потребителей в прото (они работают через re-export)

**Edge cases:**
- `widget_descriptor.py` уже помечен deprecated в Task 2.1 — перенести его в
  `contracts/_deprecated/` внутри `contracts/`, чтобы не смешивать с живыми типами.
- Проверить, что `__init__.py` contracts не создаёт циклических импортов с `core/`.

**Dependencies:** Task 3.1 (BaseWidget должен быть стабилен до реструктуризации contracts)
**Module contract:** public-api-change

---

### Task 3.3 — Разделение `core/` → `runtime/` + `utils/`

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** самое масштабное изменение Фазы 3. `core/` (15 файлов, ~1498 LOC)
разбивается на два пакета по семантике: `runtime/` (Qt-зависимые) и `utils/` (чистые утилиты).
**Context:** `core/` смешивает runtime-зависимые компоненты (qt_thread_guard, app_context,
registers_bridge) с чистыми утилитами (diagnostics, prefs_store, action_binding).
Разделение улучшает тестируемость — `utils/` тестируется без Qt.
**Module contract:** public-api-change

**Files (core/ — 15 файлов, ~1498 LOC):**

В **`runtime/`** (Qt-зависимые):
- `qt_imports.py`, `qt_thread_guard.py`, `registers_bridge.py` (если есть),
  `app_context.py`, `routed_command.py`
- Из `application/` влить: `frontend_manager.py`, `window_manager.py`,
  `thread_manager.py`, `process_attached_frontend.py`

В **`utils/`** (чистые утилиты):
- `diagnostics.py`, `prefs_store.py`, `action_binding.py`, `schema_config.py`

В **`_deprecated/`** (если Фазы 1-2 не удалили):
- `widget_registry.py`, `layout_composer.py`, `default_factories.py`,
  `base_configurable_widget.py`

**Steps:**
<!-- V6: добавить sentrux baseline без него "0 новых циклов" не проверяемо -->
0. Запустить `mcp__sentrux__session_start` и сохранить baseline перед любыми изменениями.
1. Проверить актуальный список файлов в `core/` перед началом (к моменту Фазы 3
   состав может измениться после Фаз 1-2).
2. Создать `runtime/` и `utils/` с `__init__.py`.
3. Переместить файлы группами — обновить внутренние импорты.
4. Оставить `core/__init__.py` как re-export shim с `DeprecationWarning` на все символы.
5. Обновить `tests/` — импорты теперь из `runtime/` и `utils/`.
6. Обновить документацию: `README.md` (обоих пакетов), `STATUS.md`, `DECISIONS.md`.
7. `mcp__sentrux__dsm` — проверить 0 новых циклов.
8. Запустить `mcp__sentrux__session_end` для delta-отчёта. Сохранить результат в
   `docs/refactors/2026-XX_phase3_dsm_delta.md` (имя файла уточнить по дате выполнения).

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.runtime import FrontendManager` работает
- [ ] `from multiprocess_framework.modules.frontend_module.utils import diagnostics` работает
- [ ] `from multiprocess_framework.modules.frontend_module.core import FrontendManager` работает с `DeprecationWarning`
- [ ] `mcp__sentrux__dsm`: 0 новых циклов
- [ ] Все тесты зелёные

**Out of scope:**
- Не удалять `core/` — только re-export shim
- Не переименовывать публичные классы

**Edge cases:**
- `qt_imports.py` сам по себе является "реэкспортом" Qt — если его переместить в `runtime/`,
  нужно убедиться, что все файлы внутри `runtime/` и `utils/` импортируют из нового пути.
- `prefs_store.py` после Task 2.2 принимает `configure(organization)` — при переносе
  в `utils/` проверить, что прото-вызов `configure("Inspector")` находит новый путь.

**Dependencies:** Tasks 3.1, 3.2 должны быть завершены
**Module contract:** public-api-change

---

### Task 3.4 — Влить `windows/` в `widgets/windows/`

**Level:** Junior (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** один файл `LoadingWindow` в отдельном top-level пакете `windows/` — неоправданно.
Влить в `widgets/windows/`. Уменьшение пакетов с 13 до 12.
**Context:** `windows/loading_window.py` — единственный файл в пакете. Прямых потребителей
в прото нет (прото использует `MainWindow` через `frontend/windows/main_window.py`,
не через framework). Перемещение — чисто структурное.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/windows/loading_window.py` — переместить
- `multiprocess_framework/modules/frontend_module/widgets/windows/` — создать подпакет
- `multiprocess_framework/modules/frontend_module/widgets/windows/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/windows/__init__.py` — превратить в re-export shim
- `multiprocess_framework/modules/frontend_module/widgets/__init__.py` — добавить re-export LoadingWindow

**Steps:**
1. Создать `widgets/windows/` с `__init__.py`.
2. Переместить `loading_window.py` в `widgets/windows/loading_window.py`.
3. Обновить `widgets/windows/__init__.py`:
   ```python
   from .loading_window import LoadingWindow
   __all__ = ["LoadingWindow"]
   ```
4. Старый `windows/__init__.py` — re-export shim:
   ```python
   import warnings
   warnings.warn("frontend_module.windows is deprecated, use frontend_module.widgets.windows", DeprecationWarning, stacklevel=2)
   from multiprocess_framework.modules.frontend_module.widgets.windows import LoadingWindow
   __all__ = ["LoadingWindow"]
   ```
5. `make check` + тесты.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.widgets.windows import LoadingWindow` работает
- [ ] `from multiprocess_framework.modules.frontend_module.windows import LoadingWindow` работает с `DeprecationWarning`
- [ ] `make check` зелёный

**Out of scope:**
- Не трогать прото `frontend/windows/main_window.py` — это другой пакет
- Не создавать дополнительные окна

**Edge cases:**
- `windows/__init__.py` re-export shim не должен вызывать circular import —
  проверить что `widgets/windows/` не импортирует из `windows/`.

**Dependencies:** Task 3.3 (разделение core/) должно быть завершено для чистоты импортов
**Module contract:** public-api-change

---

### Task 3.5 — Scaffold CLI: `python -m frontend_module.scaffold`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** снизить boilerplate первого виджета. CLI генерирует 4-5 файлов из
`widgets/_template/` с переименованием классов под переданное имя.
**Context:** `widgets/_template/` содержит 5 файлов: `model.py`, `panel_widget.py`,
`presenter.py`, `schemas.py`, `__init__.py` — полный skeleton MVP-виджета.
Сейчас копирование ручное. Scaffold CLI делает это за секунды.
**Module contract:** new-lite (новый публичный single-file модуль)

**Files:**
- `multiprocess_framework/modules/frontend_module/scaffold/__main__.py` — создать
- `multiprocess_framework/modules/frontend_module/scaffold/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/scaffold/templates/` — создать
  (перенести из `widgets/_template/` с `.tmpl`-расширением или использовать `jinja2`-minimal)
- `multiprocess_framework/modules/frontend_module/docs/WIDGET_COOKBOOK.md` — создать/обновить

**Steps:**
1. Изучить `widgets/_template/` — список файлов, паттерны именования классов
   (`TemplateWidget`, `TemplatePresenter`, `TemplateModel`, `TemplateSchemas`).
2. Определить стратегию шаблонизации: простой `str.replace("Template", PascalCase(name))`
   без внешних зависимостей (Jinja2 — опционально если уже есть в dev-deps).
3. Реализовать `__main__.py`:
   ```
   python -m frontend_module.scaffold my_widget --target path/to/widgets/
   ```
   Аргументы:
   - `widget_name` — имя в snake_case, конвертируется в PascalCase
   - `--target` — целевая директория (дефолт: `./widgets/`)
   - `--dry-run` — показать что будет создано без записи
4. Генерация: создать папку `my_widget/`, скопировать 5 шаблонных файлов с заменой
   `Template` → `MyWidget` в именах классов и импортах.
5. Написать тест: `test_scaffold_creates_files` — вызов через `subprocess` или прямой
   вызов функций, проверить что 5 файлов созданы с правильными именами.
6. Обновить `WIDGET_COOKBOOK.md`: раздел "Быстрый старт через scaffold".

**Acceptance criteria:**
- [ ] `python -m frontend_module.scaffold demo_widget --dry-run` выводит список 5 файлов без ошибок
- [ ] `python -m frontend_module.scaffold demo_widget --target /tmp/test_scaffold/` создаёт 5 файлов
- [ ] В `DemoWidget/presenter.py` класс называется `DemoWidgetPresenter` (не `TemplatePresenter`)
- [ ] `test_scaffold_creates_files` проходит
- [ ] `WIDGET_COOKBOOK.md` содержит раздел scaffold

**Out of scope:**
- Не добавлять Jinja2 в зависимости если не нужен (str.replace достаточен)
- Не генерировать тесты (только 5 боевых файлов)
- Не делать интерактивный режим (wizard)

**Edge cases:**
- `widget_name` может прийти в CamelCase или snake_case — нормализовать оба варианта.
- Целевая директория уже существует — спросить или падать с ошибкой (не молча перезаписывать).

**Dependencies:** Tasks 3.1–3.4 должны быть завершены (scaffold должен генерировать
виджеты под новую структуру пакетов)
**Module contract:** new-lite

---

## Acceptance criteria всего плана

### Фаза 1
- [ ] `python scripts/validate.py` зелёный
- [ ] `python scripts/run_framework_tests.py` зелёный
- [ ] `make gate` (ruff + pyright + bandit + pytest) зелёный
- [ ] `mcp__sentrux__check_rules` — 0 новых нарушений boundary `framework → prototype`
- [ ] `from multiprocess_framework.modules.frontend_module.bridge import WireConfig, CommandSender, WireStatusMonitor, CommandValidator` работает
- [ ] `from multiprocess_prototype.frontend.bridge import WireConfig, CommandSender` работает (re-export)
- [ ] `from multiprocess_prototype.frontend.bridge.command_sender import CommandSender` работает (прямой импорт из подмодуля)
- [ ] `from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator, CrudTable` работает (re-export)
- [ ] Все файлы прото-прототипа (14 файлов, 42 точки bridge) работают без изменений
- [ ] `grep -r "from PySide6\." multiprocess_framework/modules/frontend_module/` выдаёт только `core/qt_imports.py`
- [ ] Coverage C1+C2+C3: каждый из трёх модулей ≥ 60%
- [ ] Smoke-test: запуск `python multiprocess_prototype/run.py` — приложение стартует, bridge подключается, wire_monitor рендерит без ошибок. Ручная проверка хотя бы одного primitive-виджета. (Если CI-friendly smoke-test отсутствует — создать follow-up task `C0: smoke-test script`.)
- [ ] **Inventory check перед мержем в main:** повторный grep `multiprocess_prototype/frontend/bridge/*.py` и `multiprocess_prototype/frontend/widgets/primitives/*.py` на новые файлы без зависимостей от прото. Если найдены — добавить в тот же PR или создать follow-up задачу.

### Фаза 2
- [ ] ADR-128 добавлен в `DECISIONS.md`, `python -m scripts.sync` зелёный
- [ ] `"Inspector"` удалён из `core/prefs_store.py`
- [ ] `pipeline/dag_utils.py` и `pipeline/layout.py` удалены из прото
- [ ] ADR-090 закрыт или имеет ссылку на реализацию
- [ ] `make gate` зелёный после всех 4 задач

### Фаза 3
- [ ] `from frontend_module.runtime import FrontendManager` работает
- [ ] `from frontend_module.contracts import FrontendManagerConfig` работает
- [ ] `from frontend_module.utils import diagnostics` работает
- [ ] `from frontend_module.widgets.windows import LoadingWindow` работает
- [ ] Все старые пути работают с `DeprecationWarning`
- [ ] `mcp__sentrux__dsm`: 0 новых циклов
- [ ] Scaffold: `python -m frontend_module.scaffold demo_widget --dry-run` без ошибок

---

## Стратегия отката

- **Фазы 1-2** выполняются в ветке `feat/frontend-extract-bridge-primitives`. Re-export shims
  обеспечивают обратную совместимость — откат через `git revert` серии коммитов, не ломает прото.
- **Фаза 3** выполняется в **отдельной** ветке `refactor/frontend-phase3`
  (не в `feat/frontend-extract-bridge-primitives`). Не мержится в main до:
  (a) полного прохождения acceptance criteria, (b) sentrux session_end delta — нет новых циклов,
  (c) quality score не упал относительно baseline Фазы 3.
  Если delta негативная — ветка закрывается без мержа, фаза переоткрывается с новым подходом.

---

## Риски и ограничения

### Фаза 1
1. **Re-export loop risk (A1):** fw-bridge не должен импортировать из прото.
   Mitigation: проверить через `mcp__sentrux__check_rules` после A1.

2. **GuiProcess Protocol (A1):** неправильная замена сломает pyright.
   Mitigation: не создавать новый Protocol — использовать существующий `IProcess`
   (`send_message(target: str, msg: dict[str, Any]) -> None`). Убрать только
   `TYPE_CHECKING` import `GuiProcess` и заменить аннотацию `"GuiProcess | IProcess"` → `IProcess`.

3. **Тесты bridge в прото (A1):** 9 тестовых файлов работают через re-export.
   Mitigation: явно прогнать все 9 в шаге 6 A1.

4. **primitives: неполный __all__ (A2):** `CardAction` должен быть в re-export.
   Mitigation: явно перечислен в Steps A2. Целевая директория — `components/primitives/`,
   не `widgets/primitives/` (которая не существует во фреймворке).

5. **qt_imports TYPE_CHECKING (B1):** `SignalInstance`, `QWheelEvent` — только под `TYPE_CHECKING`.
   Mitigation: отдельный `TYPE_CHECKING`-блок в `qt_imports.py`.

6. **pytest-qt для C1-C3:** нужна `qapp` fixture в `conftest.py`.
   Mitigation: добавить локально, не ломать существующие тесты.

7. **Параллельное A1||A2:** файловых конфликтов нет. B1 ждёт обоих.

### Фаза 2
8. **DeprecationWarning в тестах (2.1):** `warnings.warn` только в `__init__` класса,
   не на уровне модуля — иначе засорит всё тестирование.

9. **QSettings миграция (2.2):** дефолт `"frontend_module"` не прочитает старые
   настройки "Inspector". Прото должен явно вызвать `configure("Inspector")`.
   Mitigation: проверить через `mcp__qex__search_code "prefs_store"` всех потребителей.

10. **pipeline shims (2.3):** относительные импорты внутри pipeline-пакета могут
    ссылаться на shim-файлы косвенно. Mitigation: qex-поиск перед удалением.

11. **ADR-090 вилка (2.4):** teamlead выбирает вариант. Если вариант B — добавить
    отдельную задачу в следующий план.

### Фаза 3
12. **Самое масштабное изменение (3.3):** 15 файлов core/, ~1498 LOC. Высокий риск
    сломать импорты. Mitigation: сначала re-export shim, потом потребители.

13. **Scope drift Фазы 3:** состав `core/` к моменту выполнения изменится после
    Фаз 1-2. Teamlead обязан пересмотреть список файлов перед стартом Task 3.3.

14. **Scaffold зависимости (3.5):** scaffold генерирует под новую структуру пакетов —
    нельзя стартовать до 3.1-3.4.

15. <!-- T3: явный запрет feature-флагов -->
    **Feature-флаги не нужны:** не использовать environment-переключатели или runtime-флаги
    для выбора источника импортов. Re-export shims выполняют функцию обратной совместимости
    без дополнительных механизмов.

---

## Связь с другими планами

- <!-- V5: файл plans/columnar-tab-unify.md физически отсутствует в plans/. Статус неясен. -->
  Возможен будущий план `columnar-tab-unify` (упоминается как DRAFT в `docs/plans/`).
  Если он будет создан и пойдёт параллельно — `tab_layouts/` (3 файла из Task B1)
  является зоной горячего конфликта. **Acceptance criteria для B1:** "В `tab_layouts/`
  не должно быть незамерженных изменений из других веток перед началом B1."
  После создания плана `columnar-tab-unify`: B1 мёрджится первым, `columnar-tab-unify`
  применяется поверх.
- ADR-120 (Plugins/) — плагины не импортируют из `frontend_module.core` напрямую;
  Фаза 3 (переименование пакетов) не должна нарушить это правило.

---

## Commit-конвенция для задач плана

Каждый коммит по задачам плана:
```
<type>(<scope>): краткое описание

- что сделано (буллетами)

Why: мотивация
Layer: framework | mixed
Refs: plans/frontend-extract-bridge-primitives.md
```

| Задача | type | Layer |
|--------|------|-------|
| A1, A2 | `refactor` | mixed |
| B1, B2 | `refactor` | framework |
| B3 | `docs` | framework |
| C1, C2, C3 | `test` | framework |
| 2.1 | `docs` + `refactor` | framework |
| 2.2 | `refactor` | mixed |
| 2.3 | `refactor` | mixed |
| 2.4 | `docs` | framework |
| 3.x | `refactor` | framework |
| Создание/закрытие плана | `docs(plans):` | docs |
