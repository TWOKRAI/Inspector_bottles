# Frontend Module — конструктор: рефакторинг и эволюция

- **Slug:** frontend-extract-bridge-primitives
- **Дата:** 2026-05-23
- **Статус:** DRAFT (v4 — раздроблен на phase-файлы)
- **Ветка:** feat/frontend-extract-bridge-primitives (создаётся отдельно после мержа пилота)
- **Автор:** Manager (Sonnet)

---

## Структура плана

Multi-phase план разбит на 5 файлов. Этот `plan.md` — обзор. Детали задач — в phase-файлах.

| Файл | Что внутри | Статус |
|------|------------|--------|
| [`phase-1a.md`](phase-1a.md) | A1 (bridge → fw), A2 (primitives → fw), B2 (EntityTreeWidget), B3 (README), C1/C2/C3 (тесты менеджеров) | **READY** — можно стартовать сейчас |
| [`phase-1b.md`](phase-1b.md) | B1 (qt_imports консолидация) | **DONE 2026-05-24** |
| [`phase-2.md`](phase-2.md) | 2.1 (ADR-128 + deprecated стек), 2.2 (prefs_store), 2.3 (graph/), 2.4 (ADR-090) | PENDING — после Фазы 1B |
| [`phase-3.md`](phase-3.md) | 3.1 (BaseWidget+auth), 3.2 (contracts/), 3.3 (core → runtime/utils), 3.4 (windows влить), 3.5 (scaffold CLI) | PENDING — после стабилизации прото |

---

## История ревизий

- **v2 (2026-05-23)**: Применены правки ревьюера — K1/K2/K3 (критичные), V1-V8 (важные), T1-T4 (тактические). Подробности в комментариях к каждой задаче.
- **v3 (2026-05-23, вечер)**: Синхронизация с реальностью. Параллельно стартовал пилот миграции вкладок на `BaseListNavTab` / `BaseTreeNavTab` + `DiffScrollTabLayout` в ветке `refactor/recipes-columnar-pilot` (8 коммитов: recipes → processes → services → plugins → pipeline → displays). План `columnar-tab-unify` создан как DRAFT (commit `137c5cb`). Текущий план **не стартовал** — Tasks A1/A2/B*/C* всё ещё впереди. Изменения v3:
  - Task B1 переведён в Phase 1B (после мержа пилота) — `widgets/tabs/` сейчас hot-conflict zone.
  - Tasks A1, A2, B2, B3, C1, C2, C3 выделены в Phase 1A (могут стартовать сейчас, независимы от вкладок).
  - Раздел «Связь с другими планами» обновлён — `columnar-tab-unify` стал реальностью.
  - Добавлен раздел «Состояние на 2026-05-23».
- **v4 (2026-05-23, ночь)**: Перевод на multi-phase формат `plans/<slug>/{plan,phase-*}.md`. Содержание задач не менялось — только структура. Локальные риски и acceptance вынесены в phase-файлы; в `plan.md` остался общий acceptance и стратегия отката.

---

## Состояние на 2026-05-23 (snapshot)

| Артефакт | Статус | Где смотреть |
|----------|--------|--------------|
| `multiprocess_framework/modules/frontend_module/bridge/` | **не создан** | (Task A1 не выполнен) |
| Дополнения в `components/primitives/` (StatusIndicator, EntityCard, CrudTable, MasterDetailLayout) | **не созданы** | (Task A2 не выполнен) |
| Прямые `from PySide6.*` в fw | **40 файлов** | `grep -r "from PySide6\." frontend_module/` — не сократилось |
| Миграция вкладок прото на `DiffScrollTabLayout` | **6 из ~8** | recipes, processes, services, plugins, pipeline, displays готовы; settings уже на шаблоне; processing/sources не мигрированы |
| Rename `DiffScrollTabLayout → ColumnarTabLayout` (columnar-plan Phase 1) | **не сделан** | пилот идёт впереди rename'а |
| `view_mode_toggle.py` в framework (columnar-plan Task 1.0) | **не перемещён** | живёт в `prototype/frontend/forms/` |
| Tasks Фазы 1 текущего плана | **0 / 9** выполнено | — |

**Ключевой вывод:** пилот вкладок и текущий план не конфликтуют по файлам **кроме Task B1** (qt_imports консолидация). B1 трогает `widgets/tabs/*`, которые пилот активно правит, и которые будут переименованы планом `columnar-tab-unify`. Поэтому B1 откладывается в Фазу 1B.

---

## TL;DR

Три фазы рефакторинга `frontend_module` (Фаза 1 разделена на 1A и 1B после старта пилота вкладок):

- **Фаза 1A** (можно стартовать сейчас, не зависит от пилота вкладок) — вынос созревших элементов (`bridge/`, primitives), тесты менеджеров, рефакторинг `EntityTreeWidget`, README подпакетов. → [`phase-1a.md`](phase-1a.md)
- **Фаза 1B** (после мержа пилота `refactor/recipes-columnar-pilot` и Phase 1 плана `columnar-tab-unify`) — консолидация `qt_imports` по всем 40 файлам, включая `widgets/tabs/`. → [`phase-1b.md`](phase-1b.md)
- **Фаза 2** — small wins реорганизации: deprecated мёртвый стек, убрать хардкод, завершить миграцию `graph/`, закрыть ADR-090. → [`phase-2.md`](phase-2.md)
- **Фаза 3** — реструктуризация пакетов (13 → 7), scaffold CLI (отложено до стабилизации прототипа). → [`phase-3.md`](phase-3.md)

---

## Контекст и обоснование

Аудит `frontend_module` выявил:

- **6 файлов `bridge/`** (wire_protocol, diff_engine, system_commands, wire_monitor, command_sender, command_validator) — pure Python, 0 зависимостей от прото; готовы к переносу во фреймворк.
- **4 primitive-виджета** — pure PySide6, 0 зависимостей от прото; также готовы к переносу.
- **40 файлов** делают прямые `from PySide6.*` вместо `core/qt_imports` — консолидация. На момент v3 список НЕ сократился (повторный grep подтвердил).
- **Декларативный стек** (`WidgetRegistry`, `layout_composer`, `default_factories`, `widget_descriptor`) — 0 потребителей в прото после 4+ месяцев. Канонический путь — императивный BaseWidget.
- **`_ORG = "Inspector"`** в `prefs_store.py` — утечка домена прото в framework.
- **`graph/`** — уже перенесён в framework ранее (dag_utils + layout), прото использует re-export shims (`pipeline/dag_utils.py`, `pipeline/layout.py`). Требует завершения: обновить потребителей на прямой импорт.
- **ADR-090** (координаторы) — в прото нет ни одного файла с `coordinators/`; концепция не реализована и требует резолюции.
- **Параллельный трек (v3):** пилот `refactor/recipes-columnar-pilot` мигрировал 6 вкладок прото на `BaseListNavTab` / `BaseTreeNavTab` + `DiffScrollTabLayout`. План `columnar-tab-unify` (DRAFT в commit `137c5cb`) предусматривает rename `DiffScrollTabLayout → ColumnarTabLayout` и перенос `view_mode_toggle` в framework. Это меняет состав `widgets/tabs/` и `widgets/tabs/tab_layouts/`.
- **Фаза 3** (структурная реорганизация 13 → 7 пакетов, scaffold CLI) — отложено до стабилизации прото.

---

## Порядок выполнения

```
Фаза 1A:  A1 ║ A2  →  B2 ║ B3 ║ C1 ║ C2 ║ C3            (можно стартовать сейчас)
                  ↓
                  [ожидание мержа пилота вкладок + columnar-tab-unify Phase 1]
                  ↓
Фаза 1B:  B1                                              (qt_imports после стабилизации widgets/tabs/)
Фаза 2:   2.1 ║ 2.2 ║ 2.3 ║ 2.4                          (все параллельно, после Фазы 1B)
Фаза 3:   3.1  →  3.2  →  3.3  →  3.4  →  3.5            (последовательно, после стабилизации прото)
```
<!-- V8 (v2): C1-C3 зависят от B1 только в смысле стабильности импортов, но менеджеры
     (FrontendManager, WindowManager, ThemeManager) уже используют qt_imports.
     C1-C3 не ждут B1 — они идут параллельно с B2, B3.
     v3-уточнение: разделение Фазы 1 на 1A и 1B сокращает blocking-зависимости,
     A1+A2 не блокируются миграцией вкладок, потому что bridge/ и primitives/
     (карточки/таблицы/master-detail) не пересекаются с widgets/tabs/. -->

---

## Acceptance criteria всего плана

### Фаза 1A
- [ ] `python scripts/validate.py` зелёный
- [ ] `python scripts/run_framework_tests.py` зелёный
- [ ] `make gate` (ruff + pyright + bandit + pytest) зелёный
- [ ] `mcp__sentrux__check_rules` — 0 новых нарушений boundary `framework → prototype`
- [ ] `from multiprocess_framework.modules.frontend_module.bridge import WireConfig, CommandSender, WireStatusMonitor, CommandValidator` работает
- [ ] `from multiprocess_prototype.frontend.bridge import WireConfig, CommandSender` работает (re-export)
- [ ] `from multiprocess_prototype.frontend.bridge.command_sender import CommandSender` работает (прямой импорт из подмодуля)
- [ ] `from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator, CrudTable` работает (re-export)
- [ ] Все файлы прото-прототипа (14 файлов, 42 точки bridge) работают без изменений
- [ ] Coverage C1+C2+C3: каждый из трёх модулей ≥ 60%
- [ ] Smoke-test: запуск `python multiprocess_prototype/run.py` — приложение стартует, bridge подключается, wire_monitor рендерит без ошибок. Проверить **все 6 мигрированных вкладок** (recipes, processes, services, plugins, pipeline, displays) на корректное открытие после A1+A2. (Если CI-friendly smoke-test отсутствует — создать follow-up task `C0: smoke-test script`.)
- [ ] **Inventory check перед мержем в main:** повторный grep `multiprocess_prototype/frontend/bridge/*.py` и `multiprocess_prototype/frontend/widgets/primitives/*.py` на новые файлы без зависимостей от прото. Если найдены — добавить в тот же PR или создать follow-up задачу.

### Фаза 1B (DONE 2026-05-24)
- [x] `grep -r "from PySide6\." multiprocess_framework/modules/frontend_module/` выдаёт только `core/qt_imports.py` (источник) и `tests/*` (out of scope)
- [x] ruff + pyright + framework tests + validate.py — все зелёные
- [x] `mcp__sentrux__session_end` — quality 7159 → 7166 (+8), 0 циклов, 0 violations

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

- **Фаза 1A** выполняется в ветке `feat/frontend-extract-bridge-primitives` (создаётся после мержа пилота вкладок).
  Re-export shims обеспечивают обратную совместимость — откат через `git revert` серии коммитов, не ломает прото.
- **Фаза 1B** (Task B1) — отдельный sub-PR в той же ветке или новая ветка `refactor/frontend-qt-imports`
  после стабилизации `widgets/tabs/`. Чисто механическая замена импортов, легко откатывается.
- **Фаза 2** выполняется поверх Фазы 1A+1B, в той же ветке или последующей `refactor/frontend-phase2`.
- **Фаза 3** выполняется в **отдельной** ветке `refactor/frontend-phase3`
  (не в `feat/frontend-extract-bridge-primitives`). Не мержится в main до:
  (a) полного прохождения acceptance criteria, (b) sentrux session_end delta — нет новых циклов,
  (c) quality score не упал относительно baseline Фазы 3.
  Если delta негативная — ветка закрывается без мержа, фаза переоткрывается с новым подходом.

---

## Связь с другими планами

- **`plans/columnar-tab-unify/plan.md`** (статус DRAFT, ветка `refactor/columnar-tab-unify`, commit `137c5cb`). Цель: rename `DiffScrollTabLayout → ColumnarTabLayout`, перенос `view_mode_toggle` в framework, удаление `StandardTabLayout`. **Порядок относительно текущего плана:**
  1. Сначала: пилот `refactor/recipes-columnar-pilot` мёрджится в main (6 коммитов миграции вкладок).
  2. Затем: `columnar-tab-unify` Phase 0-1 (формализация rename + ADR-128).
  3. Затем: Tasks A1, A2, B2, B3, C1-C3 (Фаза 1A текущего плана) — могут идти параллельно с шагом 2, файлов не пересекают.
  4. После завершения шагов 1-3: Task B1 (Фаза 1B) — консолидация qt_imports по стабильному `widgets/tabs/`.
- **`refactor/recipes-columnar-pilot`** (текущая ветка) — пилотная миграция 6 вкладок прото. **Hot-conflict zone:** `widgets/tabs/base_*.py`, `widgets/tabs/tab_layouts/*.py`, `widgets/tabs/nav_tree_utils.py`, `widgets/tabs/current_page_stack.py`. Tasks A1, A2, B2, B3, C1-C3 не пересекают эти файлы (см. таблицу).
- **ADR-120** (Plugins/) — плагины не импортируют из `frontend_module.core` напрямую; Фаза 3 (переименование пакетов) не должна нарушить это правило.

### Карта пересечения файлов с пилотом вкладок

| Task | Файлы | Hot-conflict с пилотом? |
|------|-------|--------------------------|
| A1 | `frontend_module/bridge/*` (новые) + `prototype/frontend/bridge/*` (shim'ы) | НЕТ |
| A2 | `frontend_module/components/primitives/*` + `prototype/frontend/widgets/primitives/*` | НЕТ |
| B1 | `widgets/tabs/*`, `tab_layouts/*`, `tab_layout_protocol.py`, `section_protocol.py`, `base_list_nav_tab.py`, `base_tree_nav_tab.py`, `base_columnar_tab.py` | **ДА — отложено в Фазу 1B** |
| B2 | `widgets/entity_editor/entity_tree_widget.py` | НЕТ |
| B3 | `application/`, `widgets/`, `managers/`, `core/`, `schemas/`, `configs/` (README) | НЕТ (только новые `README.md`) |
| C1 | `tests/test_frontend_manager.py` (новый) | НЕТ |
| C2 | `tests/test_window_manager_unit.py` (новый) | НЕТ |
| C3 | `tests/test_theme_manager.py` (новый) | НЕТ |
| 2.1 | `core/widget_registry.py`, `core/layout_composer.py`, `core/default_factories.py`, `schemas/widget_descriptor.py` (deprecated) | НЕТ |
| 2.2 | `core/prefs_store.py` + прото-инит | НЕТ |
| 2.3 | `prototype/frontend/widgets/tabs/pipeline/dag_utils.py`, `layout.py` (shim'ы) | **возможен** (pipeline tab был мигрирован — проверить relative imports после мержа пилота) |
| 2.4 | `DECISIONS.md`, `MODULE_CONTRACTS.md` | НЕТ |

---

## Глобальные риски

Локальные риски — в каждом phase-файле. Здесь — общие.

1. **Feature-флаги не нужны** (T3): не использовать environment-переключатели или runtime-флаги
   для выбора источника импортов. Re-export shims выполняют функцию обратной совместимости
   без дополнительных механизмов.
2. **Scope drift между фазами**: каждая фаза должна актуализировать свой ориентировочный список
   файлов перед стартом — состав репозитория к моменту выполнения изменится.
3. **Тестовый smoke перед мержем**: после Фазы 1A обязательная ручная проверка всех 6 мигрированных
   вкладок (см. acceptance Фазы 1A).

---

## Commit-конвенция для задач плана

Каждый коммит по задачам плана:
```
<type>(<scope>): краткое описание

- что сделано (буллетами)

Why: мотивация
Layer: framework | mixed
Refs: plans/frontend-extract-bridge-primitives/plan.md (или конкретный phase-*.md)
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
