# Фаза 2 — Small wins реорганизации

- **Родительский план:** [`plan.md`](plan.md)
- **Статус:** PENDING — стартует после полного завершения Фаз 1A и 1B
- **Содержание:** 2.1 (ADR-128 + deprecated стек), 2.2 (prefs_store), 2.3 (graph/), 2.4 (ADR-090)

Все задачи фазы выполняются параллельно — файловых конфликтов нет.

---

## Task 2.1 — ADR-128 + `@deprecated` на мёртвый декларативный стек

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

## Task 2.2 — Убрать app-specific хардкод из framework (`prefs_store`)

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

## Task 2.3 — Завершить миграцию `graph/`: удалить re-export shims в прото

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
- **v3:** pipeline tab был мигрирован пилотом — после мержа пилота относительные импорты
  внутри pipeline могли измениться. Проверить ещё раз через `mcp__qex__search_code`.

**Dependencies:** нет (параллельно с 2.1, 2.2, 2.4)
**Module contract:** impl-only

---

## Task 2.4 — Резолюция ADR-090 (координаторы)

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

## Локальные риски Фазы 2

1. **DeprecationWarning в тестах (2.1):** `warnings.warn` только в `__init__` класса,
   не на уровне модуля — иначе засорит всё тестирование.

2. **QSettings миграция (2.2):** дефолт `"frontend_module"` не прочитает старые
   настройки "Inspector". Прото должен явно вызвать `configure("Inspector")`.
   Mitigation: проверить через `mcp__qex__search_code "prefs_store"` всех потребителей.

3. **pipeline shims (2.3):** относительные импорты внутри pipeline-пакета могут
   ссылаться на shim-файлы косвенно. Mitigation: qex-поиск перед удалением.
   **v3-уточнение:** после мержа пилота вкладок (pipeline tab был мигрирован)
   относительные импорты могли измениться — проверить заново.

4. **ADR-090 вилка (2.4):** teamlead выбирает вариант. Если вариант B — добавить
   отдельную задачу в следующий план.
