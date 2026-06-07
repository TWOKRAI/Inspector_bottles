# Plan: Дисплеи как часть рецепта

- **Slug:** displays-in-recipe
- **Дата:** 2026-06-07
- **Статус:** DONE (2026-06-07) — Phase 0-5 реализованы; reviewer Opus APPROVED; коммиты `e7829660` (план), `9a59ed92` (Phase 0), `f4d9d82a` (Phase 1-5)
- **Ветка:** feat/displays-in-recipe (создаётся Director)
- **Refs-trailer (обязателен во всех коммитах):** `Refs: plans/displays-in-recipe/plan.md`

## Обзор

Рецепт становится самодостаточным: определения дисплеев (размер, формат, render-параметры)
переезжают из глобального `displays.yaml` внутрь рецепта (новая top-level секция `displays`),
а переключение рецепта автоматически переналивает `DisplayRegistry` через транзакцию
`apply_topology`. Добавляется render-pipeline (crop → scale → rotate → flip → fit) для
окна превью и recipe-scoped вкладка «Дисплеи».

**Главный источник истины:** [`docs/direction/displays-in-recipe.md`](../../docs/direction/displays-in-recipe.md)
(все 12 разделов; продуктовые решения зафиксированы 2026-06-07 в разделе 11 — НЕ переосмысливать).

---

## Статус hard prerequisite

**Hard prerequisite (раздел 5 спеки): `recipe-orchestrator-unify` Phase 2 (`PM.apply_topology`) — DONE.**

Доказательство из кода:
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1084`
  — метод `apply_topology(blueprint)` существует, реализует транзакцию
  `snapshot → pause monitor → apply → rollback-on-fail → resume`, с debounce
  (in-flight guard + cooldown). Docstring: «Единственный владелец побочных эффектов замены процессов».
- `_cmd_topology_apply` (там же, :408) маршрутизирует в `apply_topology`, не напрямую
  в `TopologyManager.apply` — точка для встройки `DisplayRegistry.reload` есть.

**Soft prerequisite: Phase 3 (развязка «активация ≠ применение») — DONE.**

Доказательство:
- `multiprocess_prototype/recipes/manager.py:234` — `set_active(slug)` = «чистый указатель,
  БЕЗ config/topology side-effect», делегирует в `engine.set_active`, НЕ вызывает `load()`.
- `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py:305` — то же
  на уровне engine.
- Недавний коммит `5956b74e` «set_active = чистый указатель (Task 3.1)» подтверждает.

**Вывод: оба prerequisite выполнены. Блокеров на старте нет.** Реализацию можно начинать.

---

## 🚀 Старт нового чата (как начать реализацию)

**Шаг 0 — прочитать (порядок важен):**
1. `docs/direction/displays-in-recipe.md` — спека (источник истины продуктовых решений, раздел 11 не переосмысливать).
2. Этот план целиком — особенно «Решения №1/№2» в Task 2.2 (архитектура SHM/reload **принята**, не пересматривать).
3. Memory-якоря: `project_display_registry` (ADR-130 generic), `project_recipes_manager` (Recipe v2), `project_recipe_hotswap` + `project_graceful_stop_debt` (горячий путь switch), `feedback_mvp_pattern`, `feedback_qt_mcp_smoke_verification`, `feedback_fix_framework_forward`.

**Шаг 1 — ветка:** `git checkout -b feat/displays-in-recipe` (от актуального `main` или текущей `fix/recipe-v3-engine-decouple`, если её ещё не влили — уточнить у владельца).

**Шаг 2 — закрыть 2 быстрых pre-start вопроса (≤15 мин):**
- **#4 grep:** подтвердить читателей `displays.yaml` — ожидается только `frontend/app.py:152-166` (preload) + `adapters/catalogs/display_catalog.py` (`_DEFAULT_YAML_PATH`). Если есть третий — учесть в Phase 2/3.
- **#2 именование:** подтвердить ключ границы `display_definitions` (list[dict]) для определений (чтобы не путать с `blueprint.displays` = привязки). Решение в плане — подтвердить у владельца одним словом.

**Шаг 3 — стартовать с Phase 0** (она независима и обязана закоммититься первой из-за `extra="forbid"`): запустить `/implement` на **Task 0.1** → 0.2 → 0.3, закоммитить Phase 0 отдельным коммитом с `Refs: plans/displays-in-recipe/plan.md`, прогнать тесты. Только потом Phase 1.

**Держать в голове (архитектурные инварианты, уже решены):**
- **SHM — в бэкенде** (SHM-frame ноды-продюсера); дисплей только read-only читает + рендерит копию. Отдельной «SHM дисплея» НЕ создавать. `bind_displays_to_blueprint` — мёртвый код, не воскрешать.
- **`DisplayRegistry.reload` — только метаданные**, generic (ADR-130). render-поля и SHM-логика во framework НЕ протаскивать.
- **Generic PM/TopologyManager не знают про `display_definitions`** — wire через prototype-слой.
- **MVP строго** для вкладки (presenter + view Protocol). После Phase 5 — **обязательный qt-mcp smoke** (`/run-proto` + `qt_snapshot`).
- **Мигратор только `update_yaml_preserving`** (НЕ `yaml.safe_dump` — потеряет комментарии).

**Готовое сообщение для нового чата** — см. конец плана (раздел «Промпт для старта»).

---

## КРИТИЧЕСКОЕ расхождение спеки и кода (читать до начала Phase 1)

Спека (раздел 2) описывает структуру YAML так:
- **top-level `displays`** — НОВАЯ секция определений (id, name, размер, render-параметры);
- **`blueprint.displays`** — СУЩЕСТВУЮЩАЯ секция привязок (`node_id → display_id`).

В реальном коде есть коллизия имён `displays` на разных уровнях:

| Уровень YAML | Domain-поле | Содержимое | Сейчас в коде |
|--------------|-------------|------------|---------------|
| `blueprint.displays` | `Topology.displays: tuple[DisplayInstance,...]` | привязки `node_id → display_id` (+ `display_name`) | **используется** демо-рецептами |
| top-level `display_bindings` | `Recipe.display_bindings: tuple[DisplayInstance,...]` | те же привязки (legacy/дубль) | объявлено, в демо-YAML **не используется** |
| top-level `displays` | **отсутствует** | определения дисплеев (НОВОЕ) | **нет** |

Факты из кода:
- `multiprocess_prototype/domain/entities/topology.py:42` — `Topology.displays` хранит
  `DisplayInstance` (привязки), это и есть `blueprint.displays` спеки.
- `multiprocess_prototype/domain/entities/recipe.py:74` — `Recipe.display_bindings` —
  отдельное top-level поле с теми же `DisplayInstance` (дубль роли `Topology.displays`).
- `multiprocess_prototype/recipes/color_inspect.yaml:112` и `region_pipeline.yaml:144` —
  привязки лежат в `blueprint.displays` с полем `display_name`.
- `multiprocess_prototype/backend/launch.py:54` — `unwrap_recipe` копирует
  `raw["display_bindings"]` в `bp["displays"]` только если `display_bindings` непуст
  (в демо пусто → ветка не срабатывает; работает `blueprint.displays`).

**Решение для этого плана (фиксируется здесь, не переосмысливать в задачах):**
1. НОВАЯ секция определений добавляется как **top-level `Recipe.displays: tuple[DisplayDefinition,...]`**.
   Имя поля в domain — `displays` (как в спеке), тип — НОВАЯ entity `DisplayDefinition`
   (НЕ `DisplayInstance`). Это не конфликтует с `Topology.displays`, т.к. они на разных
   уровнях вложенности (Recipe top-level vs Recipe.blueprint).
2. Секция привязок остаётся `blueprint.displays` (= `Topology.displays`, `DisplayInstance`).
   Phase 0 удаляет из `DisplayInstance` только поле `display_name`.
3. `Recipe.display_bindings` (legacy top-level дубль) — **НЕ трогаем** в этом плане
   (он пуст в демо, его чистка — отдельный долг). Зафиксировано в открытых вопросах.

> Каждая задача, создающая/меняющая поля, обязана явно различать `displays` (определения,
> `DisplayDefinition`) и `blueprint.displays`/`display_bindings` (привязки, `DisplayInstance`).

---

## Что УЖЕ существует (переиспользуем, НЕ создаём с нуля)

Разведка кода показала: значительная часть инфраструктуры готова — это **рефакторинг и расширение**,
а не greenfield. Не дублировать:

| Компонент | Путь | Состояние |
|-----------|------|-----------|
| `DisplayRegistry` (singleton) | `multiprocess_framework/modules/display_module/registry.py` | есть `register/unregister/clear/get/list/persist/load`; **нет `reload`** |
| `DisplayEntry` (dataclass) | `multiprocess_framework/modules/display_module/interfaces.py:28` | generic, БЕЗ render-полей (ADR-DM-001) |
| Вкладка «Дисплеи» (MVP) | `frontend/widgets/tabs/displays/{tab,presenter,view}.py` | работает с **глобальным** `displays.yaml` через `DisplayCatalog`, БЕЗ render-параметров, БЕЗ recipe-scope |
| `DisplayCatalog` Protocol + adapter | `domain/protocols/display_catalog.py`, `adapters/catalogs/display_catalog.py` | `DisplaySpec` БЕЗ render-полей; persist в глобальный YAML |
| Окно превью + render | `frontend/widgets/displays/preview_window.py` | `PreviewWindow` + `open_for_display`; numpy→QImage есть; **нет crop/scale/rotate/flip/fit** |
| blueprint binding (SHM) | `backend/displays/blueprint_binding.py` | **МЁРТВЫЙ КОД** — 0 прод-вызовов, пишет в несуществующий `ui_process`. НЕ воскрешаем. SHM дисплея = SHM-frame ноды-продюсера (backend), дисплей только читает |
| preload реестра при boot | `frontend/app.py:146-171` | грузит `displays.yaml` в singleton — **подлежит замене на recipe-driven** |
| YAML round-trip writer | `recipes/yaml_io.py:43` — `update_yaml_preserving(path, updates)` | top-level merge, сохраняет комментарии |
| Pipeline editor (read-side) | `frontend/widgets/tabs/pipeline/io.py:198` | **уже** резолвит `display_name` через `registry.get(id).name`, НЕ из YAML — частично готов к Phase 0 |
| `BaseListNavTab` | `multiprocess_framework/modules/frontend_module/widgets/tabs/base_list_nav_tab.py` | список + форма |
| `ProcessCard` | `frontend/widgets/tabs/processes/widgets/process_card.py` | паттерн карточки |
| `SectionedForm` | `frontend/widgets/primitives/sectioned_form.py` | секции формы |

---

## Карта затрагиваемых модулей по слоям

| Слой | Модуль / путь | Что меняется | Фаза |
|------|---------------|--------------|------|
| **framework** | `display_module/registry.py` | + метод `reload(entries: list[dict])` | Phase 2 |
| **framework** | `display_module/interfaces.py` | DisplayEntry остаётся generic; render-поля НЕ добавляются (ADR-130) | — (явный запрет) |
| **framework** | `process_manager_module/.../process_manager_process.py` | встройка `DisplayRegistry.reload` в `apply_topology` | Phase 2 |
| **prototype/domain** | `domain/entities/display.py` | удалить `display_name` из `DisplayInstance`; + новая entity `DisplayDefinition` | Phase 0 / Phase 1 |
| **prototype/domain** | `domain/entities/recipe.py` | + поле `Recipe.displays: tuple[DisplayDefinition,...]`; from_dict/to_dict | Phase 1 |
| **prototype/domain** | `domain/entities/__init__.py` | экспорт `DisplayDefinition` | Phase 1 |
| **prototype/adapters** | `adapters/stores/recipe_store.py` | `_denormalize` пропускает `displays` | Phase 1 |
| **prototype/adapters** | `adapters/catalogs/display_catalog.py` | `DisplaySpec` + render-поля; recipe-scoped persist | Phase 5 |
| **prototype/backend** | `backend/launch.py` | `unwrap_recipe` пробрасывает `displays` (list[dict]) | Phase 1 |
| **prototype/backend** | `backend/displays/blueprint_binding.py` | НЕ трогаем — мёртвый код (0 прод-вызовов, пишет в несуществующий `ui_process`); SHM = producer-frame. Удаление — отдельный долг | — |
| **prototype/frontend** | `frontend/app.py` | замена boot-preload `displays.yaml` на recipe-driven | Phase 2 |
| **prototype/frontend** | `frontend/widgets/displays/preview_window.py` | + render-pipeline (crop/scale/rotate/flip/fit) | Phase 4 |
| **prototype/frontend** | `frontend/widgets/tabs/displays/*` | recipe-scoped + render-форма + RecipeActivated | Phase 5 |
| **prototype/frontend** | `frontend/widgets/tabs/pipeline/{io,graph/display_node_item}.py` | резолв имени по `recipe.displays[].name` | Phase 0 |
| **data (YAML)** | `recipes/*.yaml`, `backend/config/displays.yaml` | миграция: убрать display_name; перенести определения | Phase 0, Phase 3 |

**ADR-130 явное разделение слоёв:** `DisplayRegistry`/`DisplayEntry` (framework) остаются
**generic** — render-параметры (`fit/scale/rotate/flip/crop/position`) НЕ протаскиваются во
framework. Render живёт в prototype: в `DisplayDefinition` (domain), в `DisplaySpec` (domain
adapter) и в `PreviewWindow` (frontend). Framework знает только SHM-описание
(width/height/format/fps/ring_buffer). Это сохраняет ADR-DM-001.

---

## Граф зависимостей фаз

```
Phase 0 (pre-migration: убрать display_name)   ← коммит + зелёные тесты ДО Phase 1
   │
   ▼
Phase 1 (domain: DisplayDefinition + Recipe.displays + boundary)
   │
   ├──────────────┬───────────────────────────┐
   ▼              ▼                             ▼
Phase 2        Phase 3                       Phase 4
(reload +      (мигратор displays.yaml       (render-pipeline
 apply_topology + → рецепты)                  в PreviewWindow)
 boot recipe-driven) [нужен Phase 1]          [нужен Phase 1: формат полей]
[нужен Phase 1]
   │              │                             │
   └──────────────┴──────────────┬──────────────┘
                                  ▼
                          Phase 5 (вкладка «Дисплеи» recipe-scoped)
                          [нужны Phase 1, 2, 4; Phase 3 желательно для данных]
```

- **Phase 0** — независим, должен закоммититься и пройти тесты первым (раздел 10 спеки).
- **Phase 1** — фундамент для всех остальных (domain-контракт).
- **Phase 2, 3, 4** — параллелизуемы после Phase 1 (но в одном чате — последовательно,
  макс 2 параллельных агента без worktree — см. memory `parallel_agents_commit_race`).
- **Phase 5** — финал, собирает всё вместе (vertical slice уже был в Phase 1).

---

## Перечень тестов на обновление/создание

| Тест | Путь | Действие | Фаза |
|------|------|----------|------|
| `test_entities_roundtrip` | `domain/tests/test_entities_roundtrip.py` | + round-trip `Recipe.displays`; убрать `display_name` из кейсов | 0, 1 |
| `test_recipe_store` | `adapters/tests/test_recipe_store.py` | `_denormalize` сохраняет `displays` | 1 |
| `test_demo_recipe` | `recipes/tests/test_demo_recipe.py` | демо-рецепты проходят новую схему (без display_name) | 0, 3 |
| `test_io_roundtrip` | `frontend/widgets/tabs/pipeline/tests/test_io_roundtrip.py` | резолв имени без `display_name` в YAML | 0 |
| `test_display_node_item` | `.../pipeline/tests/test_display_node_item.py` | подпись узла без `display_name`-поля YAML | 0 |
| `test_save_recipe` | `.../pipeline/tests/test_save_recipe.py` | save не пишет `display_name` | 0 |
| `test_registry` | `display_module/tests/test_registry.py` | + тесты `reload` (порядок 5 шагов) | 2 |
| `test_blueprint_binding` | `backend/displays/tests/test_blueprint_binding.py` | bind по новым определениям | 2 |
| `test_preview_window` | `frontend/widgets/displays/tests/test_preview_window.py` | + render-pipeline (crop/scale/rotate/flip/fit) | 4 |
| `test_displays_tab` | `frontend/widgets/tabs/displays/tests/test_displays_tab.py` | recipe-scoped + render-поля формы | 5 |
| qt-mcp smoke | вручную (`/run-proto` + `qt_snapshot`) | после Phase 5 (memory: обязательно после Qt-rewrite) | 5 |

---

## Порядок выполнения

### Phase 0: pre-migration — удаление display_name

> Раздел 10 спеки. `DisplayInstance` имеет `extra="forbid"` — удаление `display_name`
> без миграции YAML немедленно сломает загрузку демо-рецептов. Поэтому: сначала
> read-side editor → резолв имени по реестру, потом миграция YAML, потом удаление поля.
> **Phase 0 коммитится и проходит все тесты ДО старта Phase 1.**

- Task 0.1: Резолв имени дисплея в Pipeline editor без `display_name`-поля [DONE]
  - **Module contract:** impl-only
- Task 0.2: Миграция YAML — убрать `display_name` из `blueprint.displays` всех рецептов [DONE]
  - **Module contract:** n/a
- Task 0.3: Удалить `display_name` из `DisplayInstance` + обновить тесты [DONE]
  - **Module contract:** public-api-change

### Phase 1: domain — DisplayDefinition + Recipe.displays

- Task 1.1: **[VERTICAL SLICE]** определение → boundary → backend (минимальный E2E) [DONE]
  - **Module contract:** new-lite
- Task 1.2: Инвариант уникальности `id` + валидация ссылок `display_id` [DONE]
  - **Module contract:** impl-only
- Task 1.3: `_denormalize` + RecipeStore round-trip [DONE]
  - **Module contract:** impl-only

### Phase 2: DisplayRegistry.reload + lifecycle (apply_topology, boot)

- Task 2.1: Метод `DisplayRegistry.reload(entries)` (порядок 5 шагов) [DONE] (зависит 1.1)
  - **Module contract:** public-api-change
- Task 2.2: Встройка `reload` в `apply_topology` + boot recipe-driven [DONE] (зависит 2.1, 1.1)
  - **Module contract:** impl-only
- Task 2.3: GUI-подписка на `RecipeActivated` → перечитать реестр [DONE] (зависит 2.2)
  - **Module contract:** impl-only

### Phase 3: мигратор displays.yaml → рецепты

- Task 3.1: Разовый мигратор определений в секцию `displays` рецептов [DONE] (зависит 1.1)
  - **Module contract:** n/a

### Phase 4: render-pipeline в окне превью

- Task 4.1: Конвейер crop → scale → rotate → flip → fit в `PreviewWindow` [DONE] (зависит 1.1)
  - **Module contract:** impl-only

### Phase 5: вкладка «Дисплеи» recipe-scoped (Phase 1 UI спеки, MVP)

- Task 5.1: `DisplaySpec`/`DisplayCatalog` + render-поля, recipe-scoped persist [DONE] (зависит 1.1, 1.3)
  - **Module contract:** public-api-change
- Task 5.2: Форма + карточки + CRUD + превью с render-параметрами [DONE] (зависит 5.1, 4.1, 2.3)
  - **Module contract:** impl-only

---

## Задачи

### Task 0.1 — Резолв имени дисплея в Pipeline editor без display_name-поля

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Pipeline editor рисует подпись display-узла, резолвя имя по `display_id` из реестра/определений, не полагаясь на поле `display_name` в YAML.
**Context:** Подготовка к удалению `display_name` из `DisplayInstance`. Read-side (`io.py:198`) **уже** резолвит имя через `display_registry.get(display_id).name` — нужно убедиться, что write-side (`graph_to_blueprint`) НЕ пишет `display_name` в YAML, и `display_node_item.py` корректно работает, получая имя извне.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py` — проверить `graph_to_blueprint`: не сериализовать `display_name` в выходной dict привязок
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/display_node_item.py` — `DisplayNodeData.display_name` остаётся как UI-поле (заполняется из реестра при загрузке), но НЕ читается/пишется из YAML
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py` — метод `add_display(source, display_id, display_name)` сохраняем сигнатуру (имя приходит из резолва, не из YAML)

**Steps:**
1. Найти в `io.py` функцию `graph_to_blueprint` — убедиться, что в dict привязки пишутся ТОЛЬКО `node_id` + `display_id`, без `display_name`.
2. Убедиться, что `blueprint_to_graph` (`io.py:198`) резолвит `display_name` через переданный `display_registry` (уже так) — для recipe-scope позже будет резолв по `recipe.displays[].name`, но в Phase 0 достаточно реестра.
3. `DisplayNodeData.display_name` оставить как in-memory UI-поле (подпись узла), заполняемое при загрузке из реестра; fallback на `display_id` если пусто.
4. Прогнать `test_io_roundtrip`, `test_display_node_item`, `test_save_recipe`.

**Acceptance criteria:**
- [ ] `graph_to_blueprint` не пишет ключ `display_name` в dict привязки (grep по выходу = 0)
- [ ] Подпись display-узла = имя из реестра, fallback = `display_id`
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_io_roundtrip.py test_display_node_item.py test_save_recipe.py` зелёные

**Out of scope:** удаление поля из `DisplayInstance` (Task 0.3); миграция YAML (Task 0.2); резолв по `recipe.displays[].name` (Phase 5).
**Edge cases:** display_id есть в привязке, но дисплея нет в реестре → подпись = display_id; реестр пуст → подпись = display_id.
**Dependencies:** нет.
**Module contract:** impl-only

---

### Task 0.2 — Миграция YAML: убрать display_name из blueprint.displays

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Разовый скрипт-мигратор убирает поле `display_name` из всех записей `blueprint.displays` в файлах рецептов через ruamel round-trip, не теряя комментарии.
**Context:** `DisplayInstance` получит `extra="forbid"` без `display_name` (Task 0.3). Три файла точно содержат `display_name` и сломаются при загрузке: `color_inspect.yaml:115`, `modbus_demo.yaml:171`, `region_pipeline.yaml:147`. **Обязательно `update_yaml_preserving`** (был прецедент потери комментариев при `yaml.safe_dump`, раздел 10/11 спеки).
**Files:**
- `multiprocess_prototype/recipes/migrations/drop_display_name.py` — создать разовый мигратор
- использует `multiprocess_prototype/recipes/yaml_io.py` — `update_yaml_preserving`
- целевые: `multiprocess_prototype/recipes/*.yaml` (где есть `blueprint.displays[].display_name`)

**Steps:**
1. Создать `drop_display_name.py` рядом с `migrations/format_v1_to_v2.py` (паттерн существует).
2. Для каждого `recipes/*.yaml`: ruamel round-trip load, пройти по `blueprint.displays`, удалить ключ `display_name` из каждой записи (`del item["display_name"]` через CommentedMap).
3. Записать обратно через `update_yaml_preserving(path, {"blueprint": ...})` — НЕ `yaml.safe_dump`. (Внимание: `update_yaml_preserving` делает merge top-level ключей; для замены вложенного `blueprint` подгрузить весь `blueprint`, удалить поле, передать ключ `blueprint` целиком.)
4. Проверить вручную: комментарии-заголовки рецептов (`color_inspect.yaml:1-19`) сохранены.
5. Запустить мигратор; обновить `test_demo_recipe`.

**Acceptance criteria:**
- [ ] В `recipes/*.yaml` нет вхождений `display_name` (grep = 0)
- [ ] Комментарии-заголовки рецептов на месте (diff показывает только удаление display_name-строк)
- [ ] `pytest multiprocess_prototype/recipes/tests/test_demo_recipe.py` зелёный

**Out of scope:** перенос определений из `displays.yaml` (это Phase 3, Task 3.1); удаление поля из domain (Task 0.3).
**Edge cases:** рецепт без секции `blueprint.displays` → пропустить; запись без `display_name` → пропустить; файл с CRLF — сохранить как было.
**Dependencies:** нет (можно параллельно с 0.1).
**Module contract:** n/a

---

### Task 0.3 — Удалить display_name из DisplayInstance + обновить тесты

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Поле `display_name` удалено из entity `DisplayInstance`; адресация только по `display_id`; все тесты зелёные.
**Context:** Раздел 9.9 + 10 спеки. `DisplayInstance` (`display.py:35`) имеет `extra="forbid"` — после Task 0.2 (миграция YAML) удаление поля безопасно. Phase 0 коммитится целиком после этой задачи.
**Files:**
- `multiprocess_prototype/domain/entities/display.py` — удалить поле `display_name` и упоминание в docstring
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py` — убрать `display_name` из кейсов DisplayInstance
- `multiprocess_prototype/domain/tests/test_protocols.py`, `domain/tests/_fakes.py` — если ссылаются на `display_name` в DisplayInstance
- проверить `frontend/widgets/tabs/pipeline/inspector/inspector_panel.py`, `tab.py` — не конструируют ли `DisplayInstance(display_name=...)`

**Steps:**
1. Удалить строку `display_name: Annotated[...] = None` из `DisplayInstance` (`display.py:35`) и упоминание из docstring (`display.py:6`).
2. Grep по `DisplayInstance(` и `\.display_name` в domain/adapters — поправить все конструкторы/обращения, относящиеся к `DisplayInstance` (НЕ к `DisplayDefinition`/`DisplaySpec`, у тех имя остаётся).
3. Обновить тесты: round-trip без `display_name`.
4. Прогнать `pytest multiprocess_prototype/domain/`.

**Acceptance criteria:**
- [ ] `DisplayInstance` не имеет поля `display_name`; загрузка `color_inspect.yaml`/`region_pipeline.yaml` (после 0.2) проходит без ValidationError
- [ ] `pytest multiprocess_prototype/domain/ multiprocess_prototype/adapters/ multiprocess_prototype/recipes/` зелёные
- [ ] Phase 0 закоммичена отдельным коммитом с `Refs:` и зелёным CI

**Out of scope:** `DisplaySpec.display_name` (UI-имя в адаптере дисплеев — НЕ трогать, это другая сущность); чистка `Recipe.display_bindings`.
**Edge cases:** старый YAML с `display_name` (если остался) → ValidationError ожидаем и корректен (миграция в 0.2 обязана была пройти).
**Dependencies:** Task 0.1, Task 0.2 (оба должны быть выполнены до удаления поля).
**Module contract:** public-api-change

---

### Task 1.1 — [VERTICAL SLICE] DisplayDefinition + Recipe.displays + Dict-at-Boundary

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Сквозной минимальный срез: новая entity `DisplayDefinition` → поле `Recipe.displays` → from_dict/to_dict → проброс `displays` (list[dict]) в backend через `unwrap_recipe`/`merge_topologies` так, чтобы один дисплей из секции `displays` рецепта доехал до точки сборки топологии.
**Context:** Раздел 3 + 12 спеки. Это фундамент. Tracer bullet: после задачи можно загрузить рецепт с секцией `displays`, сериализовать обратно (round-trip), и убедиться, что определение пробрасывается как `list[dict]` на границе процесса (Dict-at-Boundary, инвариант 12). Архитектурное решение по разделению `displays` (определения) vs `blueprint.displays` (привязки) уже зафиксировано в шапке плана — следовать ему.
**Files:**
- `multiprocess_prototype/domain/entities/display.py` — добавить entity `DisplayDefinition` (frozen, SchemaBase, `extra="forbid"`)
- `multiprocess_prototype/domain/entities/recipe.py` — поле `Recipe.displays: tuple[DisplayDefinition,...] = ()`; field_validator (list→tuple, dict→DisplayDefinition); from_dict парсит top-level `displays`; to_dict сериализует
- `multiprocess_prototype/domain/entities/__init__.py` — экспорт `DisplayDefinition`
- `multiprocess_prototype/backend/launch.py` — `unwrap_recipe`: top-level `displays` рецепта пробросить в результат как `displays` (list[dict]); `merge_topologies` — суммировать определения (фундамент ⊕ pipeline)
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py` — round-trip с `displays`

**Steps:**
1. Создать `DisplayDefinition(SchemaBase)` с полями (раздел 2, таблица):
   - базовые: `id: str` (без default), `name: str = ""`, `width: int = 1280`, `height: int = 720`, `format: str = "BGR"`, `fps_limit: float = 30.0`, `ring_buffer_blocks: int = 3`;
   - render: `position: вложенный {x:int=0, y:int=0}` (отдельная frozen-модель `DisplayPosition` или dict), `fit: str = "contain"`, `scale: int = 100`, `rotate: int = 0`, `flip: str = "none"`, `crop: {x,y,w,h} | None = None` (отдельная frozen-модель `DisplayCrop` или None).
   - `model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")`.
   - `from_dict`/`to_dict` (паттерн как у других entity).
2. В `Recipe` добавить поле `displays: tuple[DisplayDefinition,...] = ()` + `field_validator("displays", mode="before")` (list[dict]→tuple[DisplayDefinition]). НЕ путать с `display_bindings`.
3. `Recipe.from_dict` — top-level `displays` уже попадёт в `model_validate` (top-level ключ не в meta-списке); убедиться, что он НЕ удаляется в шаге 2 from_dict (там удаляются только name/version/description/created_at).
4. `Recipe.to_dict` через `model_dump(mode="json")` — `displays` сериализуется автоматически (tuple→list).
5. Экспорт в `entities/__init__.py`.
6. `unwrap_recipe` (launch.py:40): после формирования `bp`, добавить `bp["displays_definitions"]` ИЛИ — решить, как назвать на границе, чтобы НЕ конфликтовать с `bp["displays"]` (привязки). **Решение:** на границе использовать отдельный ключ `display_definitions` (list[dict]) для определений, чтобы не пересекаться с `displays` (привязки в топологии). Зафиксировать в docstring.
7. `merge_topologies` — `merged["display_definitions"] = base + pipeline` (определения суммируются).
8. Round-trip тест: YAML с `displays:` → Recipe → to_dict → совпадает.

**Acceptance criteria:**
- [ ] `Recipe.from_dict({..., "displays": [{"id":"main",...}]})` создаёт `Recipe` с `displays[0].id == "main"`
- [ ] `recipe.to_dict()["displays"]` — list[dict], round-trip идемпотентен
- [ ] Граница: `display_definitions` присутствует в результате `unwrap_recipe`/`merge_topologies` как list[dict] (Dict-at-Boundary, не Pydantic)
- [ ] `DisplayDefinition` с лишним полем → ValidationError (extra="forbid")
- [ ] `pytest multiprocess_prototype/domain/tests/test_entities_roundtrip.py` зелёный

**Out of scope:** инвариант уникальности (Task 1.2); `_denormalize` (Task 1.3); реальное наполнение реестра (Phase 2); UI (Phase 5).
**Edge cases:** пустая секция `displays` → `()`; `crop: null` → None; `position` отсутствует → default {0,0}; `scale` вне 10..1000 — пока без enforce (Task 1.2 добавит).
**Dependencies:** Phase 0 (DONE целиком).
**Module contract:** new-lite (новая публичная entity DisplayDefinition в существующем файле display.py — расширение public API entities)

---

### Task 1.2 — Инвариант уникальности id + валидация ссылок display_id

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** На domain-уровне: `Recipe.displays[].id` уникальны; каждый `display_id` в привязках (`blueprint.displays`) присутствует в `recipe.displays`; `scale` ограничен 10..1000.
**Context:** Раздел 3 (уникальность), раздел 9.2 (валидация ссылок), раздел 9.11 (scale≥10). Валидация — `@model_validator`, не только YAML-парсинг.
**Files:**
- `multiprocess_prototype/domain/entities/display.py` — `DisplayDefinition`: field_validator для `scale` (clamp/raise 10..1000), `rotate` (0/90/180/270), `flip`/`fit`/`format` (enum)
- `multiprocess_prototype/domain/entities/recipe.py` — `@model_validator(mode="after")`: уникальность `displays[].id`; валидация ссылок `blueprint.displays[].display_id ∈ {displays[].id}`
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py` — тесты на дубль id, висячую ссылку, scale

**Steps:**
1. В `DisplayDefinition`: `field_validator` — `scale` в [10,1000] (ValueError с понятным текстом); `rotate ∈ {0,90,180,270}`; `flip ∈ {none,horizontal,vertical,both}`; `fit ∈ {contain,cover,stretch,none}`; `format ∈ {BGR,RGB,GRAY,RGBA}`.
2. В `Recipe`: `model_validator(mode="after")` — собрать set id из `displays`, при дубле raise `ValueError(f"Дубль display id: {id}")`.
3. Валидация ссылок: для каждого `binding.display_id` в `self.blueprint.displays` проверить наличие в id-set; при нарушении raise с указанием `display_id`.
4. Тесты: дубль id → ошибка; висячий display_id в привязке → ошибка; scale=5 → ошибка; scale=100 ок.

**Acceptance criteria:**
- [ ] `Recipe` с двумя `displays[].id == "main"` → ValueError с упоминанием `main`
- [ ] `blueprint.displays` ссылается на несуществующий `display_id` → ValueError
- [ ] `DisplayDefinition(scale=5)` → ValueError; `scale=100` ок
- [ ] `pytest multiprocess_prototype/domain/` зелёный

**Out of scope:** UI-валидация (Phase 5 QSpinBox minimum); enforce лимита числа дисплеев (раздел 9.8 — НЕ enforce'ить).
**Edge cases:** `displays` пуст + есть привязки → ошибка (висячие ссылки); привязок нет → ok (дисплей без привязки допустим, раздел 6.6).
**Dependencies:** Task 1.1.
**Module contract:** impl-only

---

### Task 1.3 — _denormalize + RecipeStore round-trip

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Сохранение рецепта через `RecipeStoreFromManager` не теряет секцию `displays` (определения).
**Context:** Раздел 3 спеки. `_denormalize` (`recipe_store.py:145`) распаковывает meta и делает `denormalized.update(result)` — `displays` пройдёт автоматически, НО нужно убедиться явным тестом и проверить порядок ключей (читаемость YAML: meta-поля → displays → blueprint).
**Files:**
- `multiprocess_prototype/adapters/stores/recipe_store.py` — `_denormalize`: явно убедиться, что `displays` входит в результат (whitelist-проверка не нужна, т.к. update(result), но добавить комментарий + при желании упорядочить `displays` перед `blueprint`)
- `multiprocess_prototype/adapters/tests/test_recipe_store.py` — тест round-trip с `displays`

**Steps:**
1. Прочитать `_denormalize` — подтвердить, что `displays` (как остальные поля Recipe) попадает через `denormalized.update(result)`.
2. (Опционально, для читаемости) упорядочить: вставлять `displays` сразу после meta-полей, перед `blueprint`.
3. Тест: `RecipeStoreFromManager.write(slug, recipe_with_displays)` → файл содержит top-level `displays`; `read(slug).displays` совпадает.

**Acceptance criteria:**
- [ ] `write` → `read` round-trip сохраняет `recipe.displays`
- [ ] В YAML `displays` — top-level (не внутри blueprint), порядок читаемый
- [ ] `pytest multiprocess_prototype/adapters/tests/test_recipe_store.py` зелёный

**Out of scope:** изменение `update_yaml_preserving`; миграция данных (Phase 3).
**Edge cases:** рецепт без `displays` → пустой список/отсутствие ключа (не ломать существующие YAML).
**Dependencies:** Task 1.1.
**Module contract:** impl-only

---

### Task 2.1 — DisplayRegistry.reload(entries)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Метод `DisplayRegistry.reload(entries: list[dict])` в framework: атомарно заменяет содержимое реестра по порядку из раздела 4 спеки.
**Context:** Раздел 4 спеки. Framework-слой, generic. **Render-поля НЕ протаскивать** в DisplayEntry (ADR-130) — `reload` принимает list[dict] и берёт только SHM-релевантные ключи (id/name/width/height/format/fps_limit/ring_buffer_blocks). Render-параметры в dict игнорируются на уровне реестра (они нужны только prototype-render-слою). Сигнал закрытия окон превью — через колбэк/наблюдателя, без импорта Qt во framework.
**Files:**
- `multiprocess_framework/modules/display_module/registry.py` — метод `reload(entries: list[dict], *, on_orphan: Callable[[str], None] | None = None)`
- `multiprocess_framework/modules/display_module/interfaces.py` — добавить `reload` в `IDisplayRegistry` Protocol
- `multiprocess_framework/modules/display_module/tests/test_registry.py` — тесты порядка
- `multiprocess_framework/modules/display_module/STATUS.md`, `DECISIONS.md` — ADR на reload + sync (`python -m scripts.sync` после правки DECISIONS)

**Steps:**
1. Реализовать `reload(entries)` под `self._lock`, порядок (раздел 4):
   1. вычислить orphan-id (в реестре, но не в entries) → вызвать `on_orphan(id)` для каждого (сигнал закрытия окон — prototype подставит колбэк, framework не знает про Qt);
   2. для orphan — `_cleanup_shm_channel(id)` (как сейчас, лог-предупреждение, фактический cleanup в prototype при рестарте);
   3. `self._registry.clear()`;
   4. зарегистрировать новые из `entries` (взять только SHM-поля, игнорировать render);
   5. SHM НЕ выделяется реестром: кадр дисплея = SHM-сегмент `frame` ноды-продюсера в бэкенде, аллоцируется штатной фазой `process.provision` (Решение №1 Task 2.2). Дисплей только read-only attach + рендер. Зафиксировать в docstring, что reload — метаданные only (ADR-DM-001/DM-003), `bind_displays_to_blueprint` obsolete (не используется).
2. При дубле id в `entries` — лог-предупреждение, пропуск (как `displays_config_to_registry`).
3. Добавить `reload` в Protocol `IDisplayRegistry`.
4. Тесты: orphan вызывает on_orphan; clear+register; дубль id; пустой entries → реестр пуст.
5. ADR в `DECISIONS.md` + `python -m scripts.sync`.

**Acceptance criteria:**
- [ ] `reload` заменяет реестр; orphan-id (отсутствующие в entries) → `on_orphan` вызван для каждого
- [ ] render-поля в dict (fit/scale/...) НЕ попадают в `DisplayEntry` (реестр generic)
- [ ] Дубль id в entries → пропуск + warning, без исключения
- [ ] `reload` идемпотентен: повторный `reload(same_entries)` даёт тот же реестр; `reload(old)` после `reload(new)` полностью восстанавливает старый набор (нужно для rollback в Task 2.2)
- [ ] `pytest multiprocess_framework/modules/display_module/tests/test_registry.py` зелёный
- [ ] `python scripts/validate.py` не ловит drift в DECISIONS

**Out of scope:** встройка в apply_topology (Task 2.2); реальная аллокация SHM (prototype); render (Phase 4).
**Edge cases:** entries пуст → все текущие = orphan, реестр пуст; `on_orphan=None` → шаг 1 пропускается.
**Dependencies:** Task 1.1 (формат list[dict] определений).
**Module contract:** public-api-change

---

### Task 2.2 — Встройка reload в apply_topology + boot recipe-driven

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** При `apply_topology` backend переналивает `DisplayRegistry` определениями активного рецепта; при boot реестр наполняется из рецепта, а не из глобального `displays.yaml`.
**Context:** Раздел 4 (ownership: backend в apply_topology, НЕ set_active) + раздел 3 (boot). `reload` вызывается после stop старых процессов и до start новых. Определения приходят на границу как `display_definitions` (list[dict], Task 1.1). Boot-preload (`app.py:146-171`) перестаёт читать `displays.yaml`.
**Files:**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — в `apply_topology`: извлечь `display_definitions` из blueprint dict, вызвать `DisplayRegistry().reload(defs, on_orphan=...)` в нужной точке транзакции (после snapshot/pause, синхронно с заменой процессов). **Внимание слою:** PM — framework; `DisplayRegistry` — framework; ок. on_orphan-колбэк (закрытие окон) — это GUI, передаётся НЕ из PM (PM в backend-процессе). Решение: reload в PM закрывает SHM (on_orphan=None или лог), а закрытие GUI-окон делает Task 2.3 по событию RecipeActivated.
- `multiprocess_prototype/frontend/app.py:146-171` — заменить безусловный preload `displays.yaml` на наполнение реестра из активного рецепта (через `recipe_store`/`display_definitions`); если активного рецепта нет — реестр пуст.
- `multiprocess_prototype/backend/launch.py` — boot-сборка пробрасывает `display_definitions` в blueprint, который уходит в PM.
- тесты: `test_launch_recipe`, новый тест на reload в apply_topology

**✅ Архитектурное решение №1 — ПРИНЯТО (расследование investigator + установка владельца «SHM в бэкенде, дисплей только читает», 2026-06-07):**

`DisplayRegistry.reload` = **только метаданные** (реестр generic, SHM не владеет — `_cleanup_shm_channel` = лог, `DisplayEntry` без SHM-объектов). Поэтому **шов внутри `apply_topology`/`TopologyManager` НЕ нужен** и НЕ создаётся (это нарушило бы ADR-130 — generic TopologyManager не знает про дисплеи).

- **SHM дисплеев отдельной НЕТ** (подтверждено: `bind_displays_to_blueprint` — мёртвый код, пишет в несуществующий `ui_process`; persistent-процесс называется `gui` и не пересоздаётся при свопе). Кадр в дисплей доезжает **по wire от ноды-продюсера**; SHM-сегмент `frame` принадлежит **non-protected процессу-продюсеру в бэкенде** и аллоцируется штатно в фазе `process.provision` стрима команд TopologyManager — что естественно соблюдает «после stop, до start». **Дисплей (окно превью) только read-only attach к этой SHM + рендер.**
- **Спека §4 шаг 5 («выделить SHM для новых») переформулируется:** SHM появляется как часть `provision` процессов-продюсеров нового рецепта — реестр SHM НЕ выделяет. Шаг 2 («остановить SHM старых») = штатный `process.cleanup` старых продюсеров. Зафиксировать это в `docs/direction/displays-in-recipe.md` §4 при реализации (правка спеки — отдельным docs-коммитом).
- **`bind_displays_to_blueprint` НЕ воскрешаем** в этом плане. Помечаем как obsolete (отдельный долг на удаление мёртвого кода — НЕ в этом плане).
- **Singleton-per-process разведён:** backend-реестр (в PM-процессе) — для telemetry через `display_state_adapter`; GUI-реестр — для вкладки. Общего инстанса между процессами нет и не нужно (спека §4 это уже подразумевает). Backend-реестр наполняется в `apply_topology`; GUI-реестр — по `RecipeActivated` (Task 2.3).

**Чистота framework (установка «что-то могло уйти во framework»):** `apply_topology` (generic PM core) НЕ должен хардкодить знание про `display_definitions`. Reload backend-реестра wire-ить через **prototype-слой бэкенда** (где композится PM / сиды), читая `display_definitions` из blueprint (Dict-at-Boundary, list[dict]) — либо как зарегистрированный pre-apply колбэк/сид (паттерн `_topology_provision`), либо в prototype-обёртке вокруг `apply_topology`. Framework PM остаётся display-agnostic. **Точный механизм (hook vs сид) — за teamlead, но знание про дисплеи НЕ протекает в generic PM-ядро.**

**✅ Архитектурное решение №2 — ПРИНЯТО (rollback реестра):** достаточно idempotent `reload(old_defs)` ТОЛЬКО метаданных. Отдельный snapshot SHM НЕ нужен — реестр SHM не владеет; SHM откатывается штатным `_restore_from_snapshot` (:629-663), который пересоздаёт процессы-продюсеры из snapshot вместе с их SHM. Механизм: снять `old_defs = registry.list()` ДО `reload(new_defs)`; при rollback вызвать `reload(old_defs)`.

**Steps:**
1. Backend-реестр: на пути `apply_topology` (через prototype-обёртку/сид — НЕ хардкод в generic PM) извлечь `display_definitions` (list[dict]) из blueprint и вызвать `DisplayRegistry().reload(defs)` ДО `manager.apply`. SHM при этом НЕ трогается (метаданные only).
2. Перед `reload` сохранить `old_defs`; при rollback (`_restore_from_snapshot`) вызвать `reload(old_defs)` — Решение №2.
3. SHM продюсеров нового рецепта создаётся штатной фазой `process.provision` (никаких новых SHM-вызовов в горячем пути switch — установка «SHM в бэкенде»).
4. SHM-cleanup orphan-дисплеев в reload отсутствует (реестр SHM не владеет) → graceful-stop долг (риск 10) не усугубляется; никаких синхронных join/timeout в стоп-фазе не добавлять.
5. В `app.py`: убрать чтение `displays.yaml`; вместо него — при наличии активного рецепта наполнить GUI-реестр определениями из рецепта (через `reload`).
6. Тесты: переключение рецепта (apply_topology) меняет содержимое backend-реестра; rollback при падении apply возвращает старый набор; boot без активного рецепта → реестр пуст.

**Acceptance criteria:**
- [ ] После `apply_topology` с `display_definitions=[{id:A},{id:B}]` реестр содержит A,B; повторный apply с `[{id:A}]` → реестр = {A}, B удалён
- [ ] При падении `manager.apply` (rollback) реестр возвращается к старому набору (повторный reload(old_defs))
- [ ] reload — только метаданные: НЕ выделяет/не освобождает SHM (grep: ни `create_memory_dict`/`release_process_memory`/`bind_displays_to_blueprint` в новом коде reload)
- [ ] Знание про `display_definitions` НЕ протекает в generic `TopologyManager`/PM-ядро (wire через prototype-слой/сид)
- [ ] `app.py` не читает `displays.yaml` при boot (grep `load_displays_config` в app.py = 0 в проде)
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py` зелёный + новый тест reload-в-apply
- [ ] qt-mcp smoke (если затронут UI boot) — реестр виден во вкладке после старта

**Out of scope:** GUI-подписка на RecipeActivated (Task 2.3); миграция данных (Phase 3); render (Phase 4).
**Edge cases:** `display_definitions` отсутствует в blueprint → reload([]) (пустой реестр) или no-op — выбрать no-op, чтобы сырые топологии без дисплеев не чистили реестр зря; rollback apply_topology → реестр тоже откатить (снять снапшот реестра до reload).
**Dependencies:** Task 2.1, Task 1.1.
**Module contract:** impl-only

---

### Task 2.3 — GUI-подписка на RecipeActivated → перечитать реестр

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** GUI по событию `RecipeActivated` перечитывает реестр и обновляет вкладку «Дисплеи»; окна превью обрабатываются по варианту А (раздел 11.4): orphan-окна закрываются, совпадающие id — переподключаются.
**Context:** Раздел 4 + 6.5 + 11.4. GUI НЕ наполняет реестр сам — backend это сделал в apply_topology (Task 2.2). GUI только реагирует на событие. Найти существующий `RecipeActivated` (memory: «RecipeActivated prod вариант A» в Phase G).
**Files:**
- найти подписку на `RecipeActivated` (grep) — вероятно в presenter рецептов или EventBus
- `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py` — обработчик: `load()` (перечитать список), управление окнами превью
- менеджер открытых окон превью (если есть) — закрыть orphan, переподключить совпадающие

**Steps:**
1. Найти точку эмита `RecipeActivated` и существующих подписчиков (grep `RecipeActivated`).
2. DisplaysPresenter подписывается (через services.event_bus) на `RecipeActivated` → вызывает `load()`.
3. Реестр открытых окон превью: **создание этого реестра (`{display_id: PreviewWindow}` менеджер) закреплено за ЭТОЙ задачей** — он впервые нужен здесь и переиспользуется в Task 5.2 (open_for_display регистрирует окно в нём). При событии закрыть окна дисплеев, которых нет в новом рецепте; для совпадающих id — переподписать на новый канал (unsubscribe/subscribe), окно не закрывать.
4. Тест presenter: эмит RecipeActivated → list обновлён; orphan-окно закрыто; совпадающее переподключено.

**Acceptance criteria:**
- [ ] `RecipeActivated` → DisplaysTab показывает дисплеи нового рецепта
- [ ] Окно дисплея, которого нет в новом рецепте, закрывается автоматически
- [ ] Окно дисплея с совпадающим id остаётся, переподписано на новый канал
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/displays/tests/` зелёный

**Out of scope:** render в превью (Phase 4); форма render-параметров (Phase 5).
**Edge cases:** нет активного рецепта → список пуст, все окна закрыты; событие до создания вкладки → ленивый replay при bind.
**Dependencies:** Task 2.2.
**Module contract:** impl-only

---

### Task 3.1 — Разовый мигратор displays.yaml → секция displays рецептов

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Разовый скрипт переносит определения из глобального `displays.yaml` в секцию `displays` каждого рецепта (только дисплеи, на которые есть ссылки в `blueprint.displays`), добавляет render-дефолты, через ruamel round-trip; `displays.yaml` → `.bak`.
**Context:** Раздел 10 Phase 1. **Обязательно `update_yaml_preserving`** (не `yaml.safe_dump`). Render-параметры с дефолтами (`fit: contain`, `scale: 100`, `rotate: 0`, `flip: none`, `position: {0,0}`).
**Files:**
- `multiprocess_prototype/recipes/migrations/displays_to_recipe.py` — создать
- `multiprocess_prototype/backend/config/displays.yaml` → переименовать в `.bak` после миграции
- целевые `recipes/*.yaml`
- использует `recipes/yaml_io.py`

**Steps:**
1. Прочитать `displays.yaml` (3 записи: main, debug, main_copy) → dict by id.
2. Для каждого `recipes/*.yaml`: собрать `display_id` из `blueprint.displays`; для каждого скопировать определение из displays.yaml; добавить render-дефолты.
3. Записать секцию top-level `displays` через `update_yaml_preserving(path, {"displays": [...]})` — merge, комментарии сохранены.
4. Переименовать `displays.yaml` → `displays.yaml.bak`.
5. Прогнать `test_demo_recipe` + загрузку рецептов через `Recipe.from_dict`.

**Acceptance criteria:**
- [ ] ВСЕ демо-рецепты с привязками получают секцию `displays`: `color_inspect.yaml`, `region_pipeline.yaml` И `modbus_demo.yaml` (последний ссылается на `display_id: main` → без секции уронит валидацию ссылок Task 1.2)
- [ ] Каждый перенесённый дисплей имеет render-дефолты (fit/scale/rotate/flip/position)
- [ ] Комментарии-заголовки рецептов сохранены (diff чистый)
- [ ] `displays.yaml` → `displays.yaml.bak`, в проде больше не читается
- [ ] `Recipe.from_dict(load(recipe))` проходит без ошибок (валидация ссылок Task 1.2 зелёная)
- [ ] `pytest multiprocess_prototype/recipes/tests/test_demo_recipe.py` зелёный

**Out of scope:** GUI-редактирование (Phase 5); удаление display_name (Phase 0 уже сделал).
**Edge cases:** рецепт ссылается на display_id, которого нет в displays.yaml → лог-warning, пропустить (или создать заглушку с дефолтами); displays.yaml отсутствует → no-op.
**Dependencies:** Task 1.1 (формат `displays`), Task 1.2 (валидация — данные должны её пройти).
**Module contract:** n/a

---

### Task 4.1 — Render-pipeline crop → scale → rotate → flip → fit в PreviewWindow

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Окно превью применяет к сырому SHM-кадру конвейер трансформаций через OpenCV/numpy в порядке `crop → scale → rotate → flip → fit` перед выводом; SHM-кадр не меняется.
**Context:** Раздел 7 + 11.3. Трансформации через OpenCV/numpy на сыром кадре (не Qt-transforms). Render-параметры приходят из `DisplayDefinition` (prototype-слой). `PreviewWindow` уже есть (`preview_window.py`); добавляем pipeline в `_update_frame_slot` и принимаем render-параметры в конструктор/фабрику `open_for_display`. **Архитектура (установка владельца):** окно превью — read-only потребитель SHM-сегмента `frame` ноды-продюсера (бэкенд владеет SHM); дисплей только читает кадр и применяет render к КОПИИ для отображения. SHM окно не выделяет и не мутирует (инвариант 4).
**Files:**
- `multiprocess_prototype/frontend/widgets/displays/preview_window.py` — render-pipeline; `open_for_display` принимает render-параметры (из DisplaySpec/DisplayDefinition)
- новый модуль (опц.) `frontend/widgets/displays/render_pipeline.py` — чистые функции трансформаций (тестируемы без Qt)
- `frontend/widgets/displays/tests/test_preview_window.py` + новый `test_render_pipeline.py`

**Steps:**
1. Чистые функции (numpy/cv2), тестируемые без Qt:
   - `apply_crop(arr, crop|None)` — slice по {x,y,w,h} (пиксели SHM-кадра), clamp границ;
   - `apply_scale(arr, scale_pct)` — `cv2.resize` по %;
   - `apply_rotate(arr, deg)` — `cv2.rotate` (0/90/180/270), w/h меняются местами при 90/270;
   - `apply_flip(arr, mode)` — `cv2.flip` (none/h/v/both);
   - `run_pipeline(arr, params)` — в порядке crop→scale→rotate→flip.
2. `fit` (contain/cover/stretch/none) — на этапе вывода в QLabel (раздел 7); contain=KeepAspectRatio с фоном, cover=обрезка, stretch=IgnoreAspectRatio, none=оригинал.
3. В `_update_frame_slot` прогнать `run_pipeline` до `_numpy_to_qimage`, затем применить fit.
4. Имя дисплея как надпись на окне (раздел 8 «Имя — везде подпись»): заголовок окна уже есть; добавить оверлей/title с `name` (fallback id).
5. Тесты pipeline на синтетических массивах (crop меняет shape, rotate 90 меняет w/h, flip корректен); бенчмарк-комментарий (1280×720 ≈ 1-2 мс, раздел 7).

**Acceptance criteria:**
- [ ] `run_pipeline` применяет crop→scale→rotate→flip в правильном порядке (юнит-тесты на shape)
- [ ] fit-режимы corretно вписывают (contain с полями, cover с обрезкой, stretch, none)
- [ ] SHM-кадр (входной array) не мутируется (трансформации возвращают новый массив)
- [ ] Имя дисплея отображается на окне (fallback id)
- [ ] `pytest multiprocess_prototype/frontend/widgets/displays/tests/` зелёный

**Out of scope:** форма редактирования параметров (Phase 5); position/canvas (Phase 2 UI); запись трансформаций в SHM (инвариант 4 — render только в preview).
**Edge cases:** crop=None → без обрезки; crop за границами кадра → clamp; scale=10 (мин); GRAY (2D) кадр; rotate 90 на неквадратном кадре.
**Dependencies:** Task 1.1 (формат render-параметров в DisplayDefinition).
**Module contract:** impl-only

---

### Task 5.1 — DisplaySpec/DisplayCatalog + render-поля, recipe-scoped persist

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** `DisplaySpec` расширяется render-полями; `DisplayCatalog`/adapter сохраняют определения в активный рецепт (`recipe_store.save`/write), а не в глобальный `displays.yaml`.
**Context:** Раздел 4 (персистентность: только рецепт) + раздел 8. Сейчас `DisplaySpec` (`display_catalog.py:19`) БЕЗ render-полей, persist в `_DEFAULT_YAML_PATH` (глобальный). Нужно: добавить render-поля; persist → активный рецепт через RecipeStore. Сохранить ADR-130 (framework generic) — render-поля живут в DisplaySpec (domain), НЕ в DisplayEntry.
**Files:**
- `multiprocess_prototype/domain/protocols/display_catalog.py` — `DisplaySpec` + render-поля (position, fit, scale, rotate, flip, crop); map ↔ `DisplayDefinition`
- `multiprocess_prototype/adapters/catalogs/display_catalog.py` — recipe-scoped: persist через RecipeStore (записать `recipe.displays`), а не в displays.yaml; list/resolve из активного рецепта
- связь DisplayCatalog ↔ RecipeStore/active recipe: adapter получает `recipe_store` + источник активного slug через **DI (AppServices)**, активный slug берётся из `RecipeManager.active`/`state.recipes.active` (НЕ из синглтона напрямую)
- `adapters/tests/test_catalogs.py` — обновить

**Steps:**
1. `DisplaySpec` + render-поля (зеркало `DisplayDefinition`); helper map `DisplaySpec ↔ DisplayDefinition`.
2. Adapter recipe-scoped: list/resolve берут `recipe.displays` активного рецепта; register/unregister/persist мутируют активный рецепт и пишут через `recipe_store.write(slug, recipe)` (or save).
3. Решить: реестр (DisplayRegistry singleton) остаётся источником для runtime/превью; вкладка «Дисплеи» работает с recipe-определениями (источник истины — рецепт), а реестр наполняется backend'ом при apply_topology. Зафиксировать: вкладка правит рецепт → save → (опц.) reload реестра локально для немедленного превью.
4. Тесты: register → recipe.displays содержит запись; persist пишет в файл рецепта; list из активного рецепта.

**Acceptance criteria:**
- [ ] `DisplaySpec` имеет render-поля; map в `DisplayDefinition` round-trip
- [ ] `catalog.persist()` пишет определения в файл активного рецепта (top-level `displays`), НЕ в `displays.yaml`
- [ ] `list_displays()` возвращает дисплеи активного рецепта
- [ ] `pytest multiprocess_prototype/adapters/tests/test_catalogs.py` зелёный

**Out of scope:** UI-форма (Task 5.2); canvas/position-drag (Phase 2 UI).
**Edge cases:** нет активного рецепта → list пуст, register → ошибка/no-op с сообщением; рецепт без секции displays → создать при первом register.
**Dependencies:** Task 1.1, Task 1.3.
**Module contract:** public-api-change

---

### Task 5.2 — Форма + карточки + CRUD + превью с render-параметрами

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Вкладка «Дисплеи» (recipe-scoped, MVP): карточки (паттерн ProcessCard/SectionedForm), форма с базовыми + render-параметрами, CRUD, кнопка «Открыть превью» с применением render-параметров; persist в рецепт.
**Context:** Раздел 8 (Phase 1 UI) + раздел 6. MVP строго: presenter + view Protocol (memory: MVP pattern preference). Переиспользовать существующую вкладку `tabs/displays/` (рефакторинг, не с нуля). Canvas/drag/наложение — Phase 2 UI, в Out of scope.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/displays/tab.py` — + render-секция формы (position, fit, scale, rotate, flip, crop + галочка «Обрезка включена»)
- `multiprocess_prototype/frontend/widgets/tabs/displays/view.py` — IDisplaysView: get_form_data/show_entry с render-полями
- `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py` — CRUD с render-полями; persist в рецепт (через services); on_open_preview передаёт render-параметры в open_for_display (Task 4.1)
- переиспользовать `frontend/widgets/primitives/sectioned_form.py` (секции «Базовые» / «Параметры отображения»)
- `frontend/widgets/tabs/displays/tests/test_displays_tab.py` — обновить

**Steps:**
1. Форма: секция «Базовые» (id/name/width/height/format/fps_limit/ring_buffer — уже есть) + новая секция «Параметры отображения» через SectionedForm (раздел 8 таблицы: QSpinBox position X/Y; QComboBox fit; QSpinBox scale 10..1000 шаг 10 default 100; QComboBox rotate; QComboBox flip; crop X/Y/W/H + галочка «Обрезка включена»).
2. Presenter: on_create/on_select/on_duplicate/on_delete работают с render-полями; persist через recipe-scoped catalog (Task 5.1).
3. on_open_preview: собрать render-параметры из DisplaySpec → `open_for_display(entry, render_params=...)` (Task 4.1).
4. Карточки: использовать паттерн ProcessCard (рамка StyledPanel + header с именем, fallback id) — НЕ изобретать новую рамку.
5. Список — только дисплеи активного рецепта; пуст если рецепта нет (раздел 8).
6. Тесты pytest-qt + **обязательный qt-mcp smoke** (memory: после Qt-rewrite — `/run-proto` + qt_snapshot, проверить реальную сборку вкладки).

**Acceptance criteria:**
- [ ] Форма имеет секции «Базовые» + «Параметры отображения» со всеми полями раздела 8
- [ ] scale QSpinBox: minimum=10, maximum=1000, singleStep=10, default=100
- [ ] CRUD пишет в активный рецепт (recipe-scoped persist), список = дисплеи рецепта
- [ ] «Открыть превью» применяет render-параметры (crop/scale/rotate/flip/fit)
- [ ] Список пуст при отсутствии активного рецепта
- [ ] `pytest .../tabs/displays/tests/` зелёный + qt-mcp smoke: вкладка собирается, форма видна

**Out of scope:** canvas-расстановка, drag-and-drop карточек, тумблер «Без наложения» (всё Phase 2 UI спеки); position-обновление при ручном перемещении окна (задел Phase 2).
**Edge cases:** дисплей без привязки (раздел 6.6) — отображается, превью пустое; permission `tabs.displays.edit` отсутствует → кнопка «Создать» disabled; галочка «Обрезка» off → crop=None.
**Dependencies:** Task 5.1, Task 4.1, Task 2.3.
**Module contract:** impl-only

---

## Риски и ограничения

1. **Коллизия имён `displays`** (КРИТИЧНО): `blueprint.displays` (привязки, `Topology.displays`) vs новая top-level `displays` (определения, `Recipe.displays`). План разводит их по разным уровням + на границе процесса определения идут под ключом `display_definitions` (Task 1.1). Каждый агент обязан различать привязку (`DisplayInstance`) и определение (`DisplayDefinition`).
2. **Legacy `Recipe.display_bindings`** (top-level дубль `Topology.displays`): в демо-YAML пуст, в плане НЕ трогаем. Возможна путаница — зафиксировано в открытых вопросах.
3. **ADR-130 (framework generic):** риск протащить render-поля во `DisplayEntry`/`DisplayRegistry`. Явный запрет в Task 2.1: render живёт только в prototype (DisplayDefinition/DisplaySpec/PreviewWindow).
4. **Потеря комментариев YAML:** мигратор обязан использовать `update_yaml_preserving` (ruamel), НЕ `yaml.safe_dump` (был прецедент). Касается Task 0.2, 3.1.
5. **Точка вызова reload — РЕШЕНО (Решение №1 Task 2.2):** reload = метаданные only, до `manager.apply`; SHM = producer-frame в бэкенде через штатный `process.provision`. Шов «после stop, до start» соблюдается естественно стримом команд. См. риск 11.
6. **Rollback apply_topology — РЕШЕНО (Решение №2 Task 2.2):** `reload(old_defs)` метаданных при `_restore_from_snapshot`; SHM откатывается пересозданием продюсеров из snapshot. См. риск 12.
7. **on_orphan и слои:** PM (backend-процесс) не может закрывать GUI-окна. Закрытие окон — в GUI по RecipeActivated (Task 2.3), не в reload PM. Разведено между Task 2.2 (SHM/реестр) и 2.3 (окна).
8. **Параллельные агенты:** макс 2 без worktree (memory: commit race). Phase 2/3/4 параллелизуемы по графу, но в одном чате — последовательно.
9. **qt-mcp smoke обязателен** после Phase 5 (memory: pytest-qt не доказывает реальную сборку).
10. **graceful-stop долг (memory `graceful_stop_debt`): 5с-ханг при switch/shutdown.** Phase 2 встраивает `reload` ровно в путь switch (`apply_topology`), который уже страдает от ханга. SHM-cleanup orphan-дисплеев (Task 2.1 шаг 1.2) в горячий путь switch НЕ должен добавлять синхронных join с таймаутом — иначе усугубит ханг. Зафиксировано в Task 2.2 step 4.
11. **Seam «после stop, до start» (полу-блокер ревью) — ✅ ЗАКРЫТ.** Расследованием установлено: шов внутри `apply_topology`/`TopologyManager` НЕ нужен. reload — только метаданные; SHM = producer-frame в бэкенде, аллоцируется штатной `process.provision` (Решение №1 Task 2.2). Generic TopologyManager не трогается (ADR-130 сохранён).
12. **Rollback реестра (полу-блокер ревью) — ✅ ЗАКРЫТ.** Idempotent `reload(old_defs)` метаданных (Task 2.2 step 2); SHM откатывается штатным `_restore_from_snapshot` (пересоздаёт продюсеров с их SHM). Отдельный SHM-snapshot не нужен.

## Открытые вопросы (выявлены при изучении кода)

> **Ревью (APPROVED WITH NITS, 2026-06-07):** до старта закрыть **#2** (именование `display_definitions`, нужно для Task 1.1) и **#4** (grep читателей `displays.yaml`, 5 мин, до Task 2.2/3.1). Вопросы **#1, #3, #5 — решаются по ходу**, на старт Phase 0/1 не влияют. Phase 0 и Phase 1 можно запускать без изменений.

1. **`Recipe.display_bindings` vs `Topology.displays`:** в коде две top-level/вложенные сущности с одинаковой ролью (привязки). Демо-YAML используют `blueprint.displays` (= Topology.displays), `display_bindings` пуст. Нужно ли в этом плане унифицировать (убрать `display_bindings`)? **Предложение:** НЕ в этом плане — отдельный долг чистки. Подтвердить у Director.
2. **Ключ на границе для определений:** план предлагает `display_definitions` (list[dict]), чтобы не конфликтовать с `displays` (привязки) в развёрнутой топологии. Альтернатива — оставить под `displays` top-level и не разворачивать в blueprint. Решение зафиксировано в Task 1.1; подтвердить именование.
3. **Источник истины для вкладки «Дисплеи»:** рецепт (через RecipeStore) vs DisplayRegistry singleton. План: рецепт — источник истины для редактирования; реестр наполняется backend'ом при apply_topology + локально для немедленного превью. Возможна рассинхронизация «отредактировал, но не активировал». Уточнить UX в Task 5.1/5.2 (раздел 4 спеки говорит «persist только рецепт» — следуем).
4. **`displays.yaml` после миграции:** план переименовывает в `.bak` (раздел 10). `app.py` перестаёт читать (Task 2.2). Подтвердить, что нет других читателей (grep показал только app.py preload + adapter `_DEFAULT_YAML_PATH` — последний меняется в Task 5.1).
5. **Pipeline editor резолв имени:** Task 0.1 резолвит по реестру; для recipe-scope корректнее резолвить по `recipe.displays[].name`. В Phase 0 реестр ещё глобальный — имя совпадёт. После Phase 2 (recipe-driven реестр) резолв по реестру = резолв по активному рецепту. Уточнить, нужен ли явный резолв по `recipe.displays` в Pipeline (вероятно нет — реестр уже recipe-scoped после Phase 2).

---

## Промпт для старта (скопировать в новый чат)

```
Реализуем фичу «Дисплеи как часть рецепта» по готовому плану.

Прочитай ПЕРЕД работой (порядок важен):
1. plans/displays-in-recipe/plan.md — план целиком, особенно раздел «🚀 Старт нового
   чата» и «Решения №1/№2» в Task 2.2 (архитектура SHM/reload УЖЕ принята — не пересматривать).
2. docs/direction/displays-in-recipe.md — спека (источник истины, раздел 11 не трогать).

Архитектурные инварианты (решены, держать в голове):
- SHM — в бэкенде (SHM-frame ноды-продюсера); дисплей только read-only читает + рендерит копию.
  Отдельную «SHM дисплея» НЕ создавать. bind_displays_to_blueprint — мёртвый код, не воскрешать.
- DisplayRegistry.reload — только метаданные, generic (ADR-130). render/SHM во framework не тащить.
- Generic PM/TopologyManager не знают про display_definitions — wire через prototype.
- MVP строго (presenter + view Protocol) для вкладки; после Phase 5 — qt-mcp smoke обязателен.
- Мигратор только update_yaml_preserving (НЕ yaml.safe_dump).

Сделай ДО кода (≤15 мин):
- ветка feat/displays-in-recipe;
- grep читателей displays.yaml (вопрос #4 плана);
- подтверди именование display_definitions на границе (вопрос #2) — спроси меня одним вопросом.

Затем стартуй Phase 0 (она первой из-за extra="forbid"): /implement на Task 0.1 → 0.2 → 0.3,
отдельный коммит Phase 0 с «Refs: plans/displays-in-recipe/plan.md», зелёные тесты. Потом Phase 1.

Коммиты — Conventional Commits + trailers Why:/Layer: (см. CLAUDE.md). Вывод — на русском.
```
