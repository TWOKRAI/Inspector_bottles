# Plan: Phase A — Audit cross-tab архитектуры (read-only)

- **Slug:** cross-tab-architecture / phase A
- **Дата:** 2026-05-27
- **Статус:** DONE (deliverable создан — см. ниже)
- **Ветка:** `refactor/cross-tab-architecture`
- **Master plan:** [`plan.md`](plan.md)
- **Brief:** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md)
- **Deliverable:** [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md) (380 строк, создан investigator-агентом 2026-05-27)

## Контекст

Прототип вырос до 7 табов, каждый таб самостоятельный MVP, но между ними нет общей доменной
модели. Обмен идёт через ad-hoc-точки: `AppContext.extras`, `TopologyHolder.on_changed`,
raw-dict копии topology. Brief зафиксировал картину «как есть» на уровне симптомов
(см. разделы 2-3 brief'а). Перед тем как проектировать domain layer (Phase B), нужен
**фактологический inventory**: где и как реально используются эти точки сейчас.

Phase A — это read-only аудит. Никаких правок кода, никаких рекомендаций (рекомендации
уже есть в brief, разделы 4 и 8). Только факты вида `файл:строка:роль` с короткими
цитатами. Цель — закрыть для автора Phase B вопрос «а где ещё это используется».

## Цели

- Получить **6 инвентаризаций** (см. brief, раздел 5) — каждая отдельной секцией в
  audit-документе с таблицей `файл:строка → роль → краткий контекст`.
- Получить **summary** с топ-3 узкими местами (по числу occurrences) — для приоритезации
  Phase B (какой таб мигрировать первым, какой extras-ключ удалять первым и т.п.).
- Зафиксировать **scope frontend'а целиком**: все 7 табов + AppContext + bridge/* + TopologyHolder.а
- Зафиксировать **минимальный framework**: только intersection с frontend (где TopologyHolder
  создаётся, где registries имеют интерфейсы, кто owner).

## Out of scope

- Любые правки кода (включая опечатки и docstring'и).
- Рекомендации «как переделать», варианты архитектуры, оценки сложности рефакторинга —
  это уже зафиксировано в brief (раздел 4: target architecture, раздел 5: phases).
- Аудит за пределами `multiprocess_prototype/frontend/` и тонкого среза
  `multiprocess_framework/` (только tracing TopologyHolder/registries/ActionBus).
- Аудит `Services/` и `Plugins/` — только если оттуда что-то **читает** frontend.
- Backend (`multiprocess_prototype/backend/`) — out of scope, кроме случаев когда GUI
  напрямую импортирует backend-объекты.
- `multiprocess_prototype_backup/` — игнорировать полностью (см. CLAUDE.md, CRITICAL).
- Графвиз/csv-артефакты — НЕ делать (brief упоминает их опционально, мы выбираем
  markdown с таблицами как единственный deliverable).

## Phase 1: Audit

**Цель фазы:** собрать deliverable `docs/refactors/2026-05_cross_tab_audit.md` —
read-only inventory из 6 секций + summary.

### Task A.1: Inventory всех 6 точек cross-tab связи

- **Статус:** [DONE] — 2026-05-27, investigator-агент (Opus), session a59c5abdd3d66c84a; deliverable [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md) (380 строк, 8 реестров, 16 extras ключей, 20 raw-dict, 40 topology чтений, 6 callback типов, 53 MagicMock в 39 файлах)
- **Level:** Senior (Opus, extended thinking)
- **Assignee:** investigator
- **Module contract:** n/a (read-only audit, не правка модулей)

**Goal:** Создать файл `docs/refactors/2026-05_cross_tab_audit.md` с шестью таблицами
инвентаризации + summary, после прочтения которого автор Phase B не задаст вопросов
«а где ещё это используется».

**Context:** Эта задача — единственная Task в Phase A. Phase A целиком — одна итерация
работы investigator'а: систематический проход по frontend'у с фиксацией occurrences.
Vertical slice не нужен (это не multi-layer фича, а read-only inventory).

**Файлы для чтения (минимум):**

*AppContext и точка сборки:*
- `multiprocess_prototype/frontend/app_context.py` — `extras` field, все
  property/method accessors (~15 шт. согласно brief 2.1).
- `multiprocess_prototype/frontend/app.py` — `run_gui()`, где `extras[...] = ...`
  заполняется и где `config["topology"]` пишется (brief: app.py:142, app.py:174).
- `multiprocess_prototype/frontend/tab_factory.py` — как табы получают ctx.
- `multiprocess_prototype/frontend/startup_checks.py` — brief упоминает как
  consumer raw-dict topology.

*TopologyHolder и bridge:*
- `multiprocess_prototype/frontend/topology_holder.py` — `_callbacks` list, `on_changed`,
  `_notify` (brief 2.4).
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` — proxy к runtime через IPC.
- `multiprocess_prototype/frontend/bridge/command_catalog.py`, `command_sender.py`,
  `wire_monitor.py`, `wire_protocol.py`, `system_commands.py`, `diff_engine.py`,
  `command_validator.py` — bridge слой целиком.
- `multiprocess_prototype/frontend/topology_context.py`,
  `multiprocess_prototype/frontend/topology_holder.py` (уже выше),
  `multiprocess_prototype/frontend/state_context.py`,
  `multiprocess_prototype/frontend/plugins_context.py`,
  `multiprocess_prototype/frontend/actions_context.py`,
  `multiprocess_prototype/frontend/auth_context.py` — другие dataclass-аксессоры.

*Все 7 табов (presenter + view + model):*
- Pipeline: `multiprocess_prototype/frontend/widgets/tabs/pipeline/{presenter.py,
  model.py, io.py, tab.py, layout.py, dag_utils.py}` + `inspector/` + `palette/` + `graph/`
  + `tests/`.
- Processes: `multiprocess_prototype/frontend/widgets/tabs/processes/{presenter.py,
  tab.py, _panels.py, data.py}` + `tests/`.
- Recipes: `multiprocess_prototype/frontend/widgets/tabs/recipes/{presenter.py, tab.py,
  view.py, recipe_form.py, recipe_io.py}` + `tests/`.
- Services: `multiprocess_prototype/frontend/widgets/tabs/services/{presenter.py, tab.py,
  _sections.py, paths_subtab.py}` + `tests/`.
- Plugins: `multiprocess_prototype/frontend/widgets/tabs/plugins/{presenter.py,
  detail_panels.py, paths_subtab.py}` + `tests/`.
- Displays: `multiprocess_prototype/frontend/widgets/tabs/displays/{presenter.py, view.py,
  tab.py}` + `tests/`.
- Settings: `multiprocess_prototype/frontend/widgets/tabs/settings/{presenter.py, view.py,
  tab.py, yaml_io.py, _nav_tree.py, _sections.py}` + sub-sections (`appearance/`,
  `system/`, `history/`, `administration/`, `interface/`) + `tests/`.

*Dialogs и shared widgets (cross-tab triggers):*
- `multiprocess_prototype/frontend/widgets/dialogs/` — особенно
  `create_process_dialog.py` (новый, вчерашний cross-tab trigger из git status).

*Минимально framework (только intersection):*
- `multiprocess_framework/modules/registers_module/__init__.py` — публичный API
  RegistersManager.
- `multiprocess_framework/modules/service_module/registry.py`,
  `interfaces.py` — ServiceRegistry.
- `multiprocess_framework/modules/display_module/registry.py`,
  `interfaces.py` — DisplayRegistry.
- `multiprocess_framework/modules/process_module/plugins/manager.py` — PluginManager
  (singleton owner).
- `multiprocess_framework/modules/actions_module/bus.py` — ActionBus (упомянут в
  brief 2.7 как параллельный mutation путь).
- `multiprocess_framework/modules/frontend_module/forms/form_context.py` — FormContext
  (собирается из `ctx.registers_manager() + ctx.action_bus()`).
- `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py` — где
  RecipeEngine, что он отдаёт через `recipe_manager`.

*Корневые узлы prototype recipes:*
- `multiprocess_prototype/recipes/manager.py` — owner `recipe_manager`.

**Steps (6 инвентаризаций + summary):**

1. **Inventory 1 — потребители topology.** Найти все occurrences паттернов:
   - `topology.get("processes", ...)`, `topology.get("displays", ...)`,
     `topology.get("services", ...)`, `topology.get("connections", ...)`;
   - `topology["..."]` (subscript access);
   - `ctx.config["topology"]` (стартовый snapshot);
   - `ctx.extras["topology"]` (legacy fallback);
   - `holder.topology`, `TopologyHolder.topology`, `topology_holder().topology`.

   Формат таблицы: `файл:строка | role (read | write | both) | краткий контекст
   (1 строка кода или комментарий)`. Минимум 5 примеров; ожидаем 30-50.

   Linkback: соответствует brief п. 2.2 + 2.3.

2. **Inventory 2 — ключи `ctx.extras[...]`.** Найти:
   - все места записи (`extras[k] = v`, `extras.update(...)`, `build_app_context(... extras=...)`);
   - все места чтения (`extras.get(k)`, `extras[k]`, через property/method accessor'ы
     `AppContext.topology_holder()` и т.д.).

   Формат таблицы (одна строка на уникальный ключ):
   `ключ | тип значения (по аннотации или factory) | owner (где записан) | consumers
   (список файлов:строк) | через accessor (да/нет)`.

   Известные ключи (из app_context.py): `auth_manager`, `auth_state`, `audit_storage`,
   `registers_manager`, `plugin_registry`, `bindings`, `action_bus`, `topology_holder`,
   `topology_bridge`, `command_catalog`, `plugin_manager`, `service_registry`,
   `recipe_manager`, `topology` (legacy). Допускается, что найдутся ещё.

   Linkback: brief п. 2.1.

3. **Inventory 3 — реестры (registries).** Семь реестров из brief 2.5:
   PluginRegistry, ServiceRegistry, DisplayRegistry, RegistersManager, RecipeManager,
   TopologyHolder, TopologyBridge.

   Формат таблицы (одна строка на реестр):
   `реестр | класс (модуль) | где создаётся (файл:строка) | как табы получают
   (ctx accessor / direct import / singleton) | write consumers (кто меняет) |
   read consumers (кто читает)`.

   Linkback: brief п. 2.5 + 2.7.

4. **Inventory 4 — callback'и и observable.** Найти:
   - все вызовы `holder.on_changed(...)`, `topology_holder().on_changed(...)`,
     `set_topology(...)` (триггеры);
   - все Qt signal/slot connections относящиеся к cross-tab (если есть);
   - любые pub-sub точки: `ActionBus.dispatch`, ActionBus subscribers,
     `RecipeEngine` callbacks (если есть), GuiStateBindings observers.

   Формат: одна таблица на тип события. Колонки: `событие/триггер | dispatcher
   (файл:строка) | subscribers (список файлов:строк) | payload type
   (по сигнатуре callback'а)`.

   Linkback: brief п. 2.4 + 2.6.

5. **Inventory 5 — raw-dict операции в presenter'ах.** Паттерны вида
   `for proc in topology.get("processes", []):` и аналогичные итерации/доступы к
   полям без типов. Brief 2.3 утверждает их 10+.

   Формат таблицы: `файл:строка | паттерн (короткий код) | какие поля dict читаются
   (process_name, plugins, config, target_process, description, protected, ...)`.

   Дополнительно: пометить, использует ли строка `isinstance(x, dict)` /
   `getattr(x, ..., default)` defensive-проверки (brief 2.3 приводит такой
   anti-pattern).

   Linkback: brief п. 2.3 + 2.8.

6. **Inventory 6 — тесты с MagicMock-ctx.** Найти:
   - `ctx = MagicMock()` / `MagicMock(spec=AppContext)`;
   - ad-hoc fixture'ы типа `make_ctx(...)` / `build_test_context()` / fixture'ы
     возвращающие SimpleNamespace вместо реального AppContext;
   - тесты, которые подменяют `ctx.topology_holder()` / `ctx.recipe_manager()` /
     `ctx.service_registry()` через `MagicMock(return_value=...)`.

   Формат таблицы: `тестовый файл:строка | тестируемый presenter/tab | что
   замокано | риск (комментарий: что может скрыть)`.

   Linkback: brief п. 6.6 + симптом 1.5 (вчерашний кейс: тесты проходили, в GUI
   не работало).

7. **Summary + топ-3 узких места.** Финальная секция аудит-документа:
   - Топ-3 узких места по числу occurrences (например, «extras['topology_holder']
     читается в 23 местах», «for proc in topology.get('processes') — 14 копий»).
   - Карта зависимостей между табами (текстовая или mermaid, если получается просто):
     какой таб через какие точки связан с каким.
   - Прямые цифры: сколько ключей в extras, сколько подписчиков on_changed, сколько
     MagicMock-тестов, сколько raw-dict паттернов. Для Phase B это позволит
     приоритезировать.
   - Без рекомендаций решения — только метрики.

**Acceptance criteria:**

- [ ] Создан файл `docs/refactors/2026-05_cross_tab_audit.md`.
- [ ] Шесть секций инвентаризаций присутствуют, каждая отдельным `##` заголовком в
      указанном выше порядке (1-6).
- [ ] В каждой секции — markdown-таблица с минимум **5 примерами** `файл:строка`
      (где они есть в коде; если по факту меньше 5 — явно зафиксировать
      «найдено N occurrences, все ниже»).
- [ ] Summary-секция в **начале** документа (после titel/intro, до Inventory 1)
      с топ-3 узкими местами по числу occurrences.
- [ ] Linkback на brief в **каждой** инвентаризационной секции (например:
      «Соответствует п. 2.2 brief'а: `docs/refactors/2026-05_cross_tab_architecture.md`»).
- [ ] Ни одной фразы вида «нужно сделать X», «рекомендую Y», «предлагается заменить
      на Z». Только описательные формулировки «сейчас X», «в коде встречается Y».
- [ ] Документ покрывает все 7 табов (Pipeline, Processes, Recipes, Services,
      Plugins, Displays, Settings) — каждый явно упомянут хотя бы в одной таблице
      (если таб не использует cross-tab точки — это тоже факт, зафиксировать
      «Settings tab не использует TopologyHolder»).
- [ ] Размер документа в диапазоне 300-600 строк (если меньше — investigator
      должен пояснить почему; если больше — допустимо).
- [ ] В git коммит входит ровно один файл: новый
      `docs/refactors/2026-05_cross_tab_audit.md`. Никаких правок других файлов.

**Out of scope (повторение для investigator'а):**

- Никаких правок кода. Read-only режим investigator-агента строгий.
- Никаких рекомендаций «как переделать». Брать формулировки только описательные.
- Не делать графвиз/csv артефакты — только markdown с таблицами.
- Не аудитить backend / `multiprocess_prototype_backup/` / `Services/` (кроме как
  для tracing того что читает frontend).

**Edge cases (на что обратить внимание):**

- Pipeline tab имеет 3 уровня вложенности: `pipeline/inspector/`, `pipeline/palette/`,
  `pipeline/graph/` — каждый может содержать raw-dict операции и subscribers.
- Settings tab имеет 5 sub-tabs (`appearance`, `system`, `history`, `administration`,
  `interface`) — каждая со своим presenter'ом. Brief ожидает, что Settings меньше
  всего пересекается с topology, но это нужно подтвердить фактом, а не пропустить.
- `multiprocess_prototype/frontend/topology_context.py`,
  `state_context.py`, `plugins_context.py`, `actions_context.py`, `auth_context.py` —
  это вспомогательные dataclass'ы поверх `extras`. Возможно они уже выполняют часть
  работы, которую brief предлагает в `AppServices`. Зафиксировать как **факт**:
  какие из них активно используются, какие — пустые / legacy.
- Тесты в `multiprocess_prototype/frontend/widgets/tabs/*/tests/` могут использовать
  как реальный AppContext, так и MagicMock. Разделить.
- Файлы `multiprocess_prototype/frontend/widgets/dialogs/create_process_dialog.py`
  и `tests/test_create_process_dialog.py` — **новые** (не в git, но из status видно).
  Investigator должен их прочитать как часть актуального состояния (что
  затрагивается cross-tab триггером из брифа п. 1.5 «создал процесс → виден в Pipeline»).
- Из git status видно изменённые presenter'ы во всех 7 табах + новые тесты
  `test_cross_tab_process_create.py`, `test_create_dialog_integration.py` —
  состояние **на сейчас**, до commit. Investigator должен читать файлы as-is с диска.

**Dependencies:** нет (Phase A — стартовая фаза, ничего не блокирует).

**Refs:** `docs/refactors/2026-05_cross_tab_architecture.md` (brief, разделы 2-3, 5, 7).

## Открытые вопросы

- [ ] Нужны ли инвентаризации для backend-кода (`multiprocess_prototype/backend/`)?
  — **Решение по умолчанию:** нет, только если GUI напрямую импортирует. Подтвердить
  на review плана.
- [ ] Включать ли в audit `multiprocess_prototype/recipes/manager.py` отдельной
  строкой в Inventory 3 (как owner RecipeManager)? — **Решение по умолчанию:** да,
  это правильное место для tracing'а.

## Решения (decisions log)

- **2026-05-27:** Phase A = single Task A.1 (одна итерация investigator'а, не дробить
  на под-шаги). Каждая инвентаризация — отдельная секция в одном deliverable'е, не
  отдельный файл. Investigator оптимально работает в одном контекстном окне с
  единым проходом по коду.
- **2026-05-27:** Format = markdown с таблицами. Brief упоминал graphviz/csv как
  опцию, но для read-only inventory таблиц достаточно; graphviz/csv добавляют
  поддержку артефактов которые никто потом не пересоздаст.
- **2026-05-27:** Scope ограничен `multiprocess_prototype/frontend/` +
  `multiprocess_framework/` (только intersection). Services/Plugins вне scope —
  они catalog-providers, не consumers cross-tab точек.

---

> **Хранение:** `plans/2026-05-27_cross-tab-audit.md` (single plan, дата ISO в имени).
>
> **Workflow дальше:** после approval плана Director вызывает investigator с этим планом
> как ТЗ. Investigator производит deliverable
> `docs/refactors/2026-05_cross_tab_audit.md` и коммит в ветку
> `refactor/cross-tab-architecture` с trailer `Refs: plans/2026-05-27_cross-tab-audit.md`.
> Phase B/C/D/E/F/G стартуют отдельными планами после approval audit-документа.
