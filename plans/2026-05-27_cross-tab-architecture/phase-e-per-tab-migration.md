# Phase E — Per-tab migration: AppContext → AppServices DI

- **Slug:** cross-tab-architecture / phase-e
- **Дата:** 2026-05-28
- **Статус:** E.1 DONE (APPROVED), E.2 DONE, E.3 DONE, E.4 DONE, E.5 DONE, E.6 READY (last)
- **Ветка:** `refactor/cross-tab-architecture` (та же ветка что Phase A–D; sub-branch не нужен — D.5 Settings tab коммитился прямо в неё, и Pipeline аналогично; отдельные sub-branch'и создаются только если параллельная работа по нескольким табам одновременно, что исключено правилом «таб за заходом»)

---

## Назначение

Этот файл — детализированный subplan Phase E master-плана `cross-tab-architecture`.
Phase E мигрирует каждый из 6 оставшихся табов с `AppContext` (legacy) на `AppServices` DI:
**Pipeline → Processes → Recipes → Services → Plugins → Displays**.

Settings tab уже мигрирован в D.5 и служит образцом паттерна. Каждый таб мигрируется
последовательно, в рамках одной ветки, со своими тестами. Старый `ctx`-код остаётся
нетронутым до Phase F (удаление legacy). Детализация задач E.2–E.6 откладывается
до approval E.1 (правило master-плана: phase-N+1 не детализируется до approval N).

---

## Источники истины

| Документ | Что содержит |
|---|---|
| [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) разд. 5 | Brief Phase E — очерёдность, принцип «таб за заходом» |
| [`docs/refactors/2026-05_phase_e_migration_guide.md`](../../docs/refactors/2026-05_phase_e_migration_guide.md) | **Главный образец:** паттерн до/после, маппинг extras→AppServices, EventBus подписки, тестовый builder, edge cases, follow-ups |
| `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py` | Образец мигрированного таба (D.5) |
| [`plans/2026-05-27_cross-tab-architecture/plan.md`](plan.md) | Master-план, фазы A–G, история коммитов |

> **Правило:** перед стартом каждой задачи Ei — перечитать migration guide целиком.
> Там паттерны presenter-сигнатуры, замена action_bus, EventBus-подписки, edge cases, тесты.

---

## Таблица задач Phase E

| Task | Tab | Файлов | Сложность | Assignee | Зависимости | Статус |
|------|-----|--------|-----------|----------|-------------|--------|
| **E.1** | Pipeline | ~14 | Senior+ | teamlead | D done | **DONE (APPROVED)** |
| **E.2** | Processes | 6 | Middle | developer | E.1 approved | **DONE** |
| **E.3** | Recipes | 3 | Middle | developer | E.2 | **DONE** |
| **E.4** | Services | 4 | Middle | developer | E.3 | **DONE** |
| **E.5** | Plugins | 11 | Middle+ | developer | E.4 | **DONE** |
| **E.6** | Displays | ~3 | Junior | developer | E.5 | READY (last) |

**Почему Pipeline = Senior+:** 21 из 40 топологических чтений в кодовой базе. Пять слоёв
взаимодействия: `tab.py` → `presenter.py` → `inspector/inspector_panel.py` → `palette/` → `telemetry/wire_metrics_controller.py`.
Presenter читает `topology_holder`, `action_bus`, `plugin_registry`, `registers_manager` — 4 разных сервиса.
Inspector Panel дополнительно: `registers_manager`, `form_context`. Итого ~14 изменяемых файлов,
scene-reload с позициями узлов, undo/redo chain.

**Почему Plugins = Middle+ (не Junior):** 25 точек legacy-доступа в 11 файлах (presenter + sandbox + _sections + тесты), `plugin_manager()` и `plugin_registry()` смешаны.

**Почему Displays = Junior:** 0 точек legacy `ctx.extras[]` / `ctx.topology_holder()` найдено при grep. Таб уже близок к self-contained паттерну; потребует минимального рефактора `create()` factory.

---

## Acceptance Criteria Phase E (cumulative)

После завершения E.6:

- [ ] `grep -r "ctx\.extras\[" multiprocess_prototype/frontend/widgets/tabs/ --include="*.py"` → 0 результатов (или только явные `# TODO Phase F:` комментарии с обоснованием)
- [ ] `python -m pytest multiprocess_prototype/frontend/widgets/tabs/ -W always::DeprecationWarning 2>&1 | grep "_deprecated_extras"` → 0 строк
- [ ] Все 7 табов (Settings + 6 мигрированных) проходят Qt-MCP smoke: рендер без Qt warnings, базовые interactions (click toolbar, navigate nav)
- [ ] Sentrux score ≥ baseline **7161/10000** (зафиксирован Phase D, коммит `94983ed2`)
- [ ] 0 ad-hoc `MagicMock()` без spec в тест-файлах табов — везде `make_test_app_services()` builder из `multiprocess_prototype/domain/tests/_fakes.py`
- [ ] Все checkbox'ы задач E.1–E.6 в этом файле отмечены `[x]` с хешами коммитов

---

## Phase D follow-ups — обязательный checklist

Из [migration guide строки 267–286](../../docs/refactors/2026-05_phase_e_migration_guide.md):

- [x] **Split ConfigStore decision** принят и задокументирован (Task E.1 review iteration 1): Pipeline только **читает** config через `services.config.get(...)` (topology, process_manager_proxy) — не пишет через `set()`. Текущий split (`Config(initial_data=dict(ctx.config))`) безопасен для E.1: read-only consumer не вызовет рассинхрон. **Открытый вопрос для E.4 Services:** Services tab будет мутировать config (lifecycle / overrides) — там должен быть shared backend. Решение перенесено на старт E.4. **E.2 Processes (2026-05-28):** split-вопрос не применим — Processes вообще не использует `services.config`, topology читается через `services.topology.load()` (TopologyRepository поверх holder, не config). Read-only consumer.

> **РЕШЕНО на E.4 Services (2026-05-28):** предпосылка «Services мутирует config» оказалась **неверной**. Фактически Services — **read-only config consumer**: читает `services.config.get("discovery")` (get_service_paths), а изменения путей пишет напрямую в `user_overrides.yaml` (`_save_service_paths`), **не** через `services.config.set()`. Эффект применяется при следующем рестарте (существующее поведение, не введено миграцией). Split безопасен (как E.1). **Shared ConfigStore по-прежнему не нужен** — ни один мигрированный таб (E.1 Pipeline, E.2 Processes, E.3 Recipes, E.4 Services) не вызывает `services.config.set()` с требованием cross-tab видимости. Вопрос остаётся открытым только если такой таб появится (E.5 Plugins / Phase G).
- [ ] **ConfigStore `_firing: bool` guard** добавлен в `ConfigStore` impl — защита от бесконечной рекурсии при reactive chains (`set()` → subscriber.set() → ...). Добавить в том табе, который первым использует реактивные config-chains (ожидается E.3 Recipes или E.4 Services).
- [ ] **InterfaceSection `ctx=None` graceful degradation** — кнопка «Обновить UI» логирует warning при `ctx=None`. Решено в рамках расширения какого-то Protocol (например `ProcessControlProtocol`) либо явно отложено в Phase G с обоснованием. Зафиксировать решение здесь.

> **Split ConfigStore decision** (предварительная позиция для обсуждения): shared instance предпочтительнее, так как два независимых `Config` объекта будут рассинхронизированы при первом же `services.config.set()` из мигрированного таба, пока не-мигрированные табы читают `ctx.config`. Рекомендация: в `build_app_services()` передавать ссылку на тот же `Config` объект, что хранится в `AppContext`, а не создавать копию через `Config(initial_data=dict(ctx.config))`.

---

## Out of scope Phase E

- Удаление `ctx.extras` dict-bag и AppContext — Phase F
- Удаление 4 dataclass-обёрток (`TopologyContext`, `StateContext`, `PluginsContext`, `ActionsContext`) — Phase F
- Полная замена `holder.on_changed` broadcast → typed domain events — Phase G (требует расширения EventBus для нод/wire нотификаций)
- Удаление `topology_bridge` — Phase F
- `bindings` (GuiStateBindings) → AppServices — Phase G (ревизия по желанию)
- Live runtime snapshot (PID, FPS, метрики) — Phase G (отдельный aggregate)
- Расширение `AuthFacade` Protocol до Admin-уровня — при необходимости в E.4/E.5, иначе Phase G

---

## Порядок выполнения

### Phase E.1 — Pipeline tab [DONE] (2026-05-28, коммиты `8566f994` + `e7bd3d97`)

- **Module contract:** public-api-change
- **Review:** APPROVED (итерация 2/2 reviewer Opus)
- **Тесты:** 322 passed (pipeline), 54 passed (adapters), 11 passed (domain)
- **Sentrux:** 7141 (-20 vs baseline 7161, принято — bridges объективно нужны до Phase F)
- **Qt-MCP smoke:** deferred to cumulative после E.6 (multiprocess архитектура — MCP не достучался до GUI процесса)
- **TODO Phase F (8 items, все с явными комментариями в коде):** ActionBus→commands, RecipeManager raw dict, RegistersManager API, form_context, process_manager_proxy, AuthFacade.auth_state, PluginCatalog raw Ports, holder.on_changed→typed events (Phase G)

### Phase E.2 — Processes tab [DONE] (2026-05-28, коммит `be462f59`)

- **Module contract:** public-api-change
- **Тесты:** 50 passed (processes), 624 passed (все табы — регрессий нет)
- **Sentrux:** 7140 (−1 vs E.1 7141, уровень шума; acyclicity 10000 — новых циклов нет; гэп до baseline 7161 закроет Phase F при удалении bridges)
- **Реальный объём legacy:** 5 ctx-обращений в presenter (config/extras topology, plugin_registry, topology_bridge, command_sender) + 2 в _panels (bindings) — план оценивал «1 + 2», audit был устаревшим
- **Решения:**
  - topology читается через `services.topology.load()` (domain Topology entity), **не** через `services.config` — в production topology живёт в `ctx.extras["topology"]`/holder, а `build_app_services` оборачивает только `ctx.config`; config-путь дал бы регрессию (пустой список процессов). Удалён extras-fallback (единый источник = TopologyRepository).
  - category — через `services.plugins.resolve(name).category` (PluginCatalog Protocol), поведение сохранено.
  - **Runtime-deps вне AppServices** (command_sender, topology_bridge, bindings) — explicit kwargs (паттерн Settings `auth_ctx`). `create(ctx)` извлекает их из ctx. TODO Phase G: вынести в live-runtime aggregate.
- **TODO Phase F/G (3 items):** command_sender/topology_bridge → runtime aggregate (Phase G); topology_bridge accessor deprecated в create() bridge (Phase F удалит ctx); AuthFacade Protocol для permission gating (Phase F).

### Phase E.3 — Recipes tab [DONE] (2026-05-28, коммит `5f8c0a4e`)

- **Module contract:** public-api-change
- **Тесты:** 23 passed (recipes), 624 passed (все табы)
- **Sentrux:** 7139 (−1 vs E.2 7140, шум)
- **Объём:** 2 production-файла (только `tab.py` + новый `tests/_helpers.py`), 1 test-файл. **Presenter и его тесты не тронуты** — `RecipesPresenter(recipe_manager, view)` уже был декомпозирован от ctx (MVP).
- **Решения:**
  - RecipeManager берётся через `getattr(services.recipes, "_rm", None)` bridge — RecipeStore Protocol покрывает list/read→Recipe/write/delete/get_active/set_active, но **не** богатый legacy API (`read_recipe`→dict, `duplicate`, `recipes_dir`), который нужен presenter'у. TODO Phase F: расширить Protocol.
  - `BaseListNavTab` принимает `ctx=None` (паттерн Settings/Processes).
  - Follow-up #2 (`ConfigStore _firing guard`): **не применим** — Recipes вообще не использует `services.config`/reactive chains.

### Phase E.4 — Services tab [DONE] (2026-05-28, коммит `27c72f64`)

- **Module contract:** public-api-change
- **Тесты:** 24 passed (services), 623 passed (все табы; −1 vs 624 — удалён устаревший тест «registry=None», невозможный с обязательным ServiceManager в AppServices)
- **Sentrux:** 7138 (−1 vs E.3 7139, шум)
- **Объём:** 4 production-файла (tab.py, presenter.py, _sections.py + новый tests/_helpers.py), 1 test-файл.
- **Ключевое решение — Protocol вместо bridge:** presenter стал **тонким** — делегирует lifecycle в `services.services` (ServiceManager Protocol: start/stop/restart/get_lifecycle/list_services), оборачивая `DomainError → bool/None`. Кэш экземпляров и мутация `entry.lifecycle` **переехали в адаптер** `ServiceManagerFromRegistry` (он уже дублировал эту логику с Phase C.1.6 — migration note прямо это предписывала). Убрано дублирование логики инстанцирования сервисов presenter↔adapter.
- **Тесты lifecycle** переписаны на реальный `ServiceManagerFromRegistry` над stub-реестром (через `make_services_services()`) — проверяют настоящий Protocol-путь; `entry.lifecycle` и `services.services._instances` верифицируются вместо `presenter._instances`.
- **Sections (BaseTreeNavTab):** `build_services_sections(services)` — closures захватывают services, factory'и игнорируют ctx-арг (паттерн Settings `_make_factory`); `_ServiceSection`/`_ServicePathsSection` принимают services; auth через `services.auth._state`.

### Phase E.5 — Plugins tab [DONE] (2026-05-28, коммит `62279a85`)

- **Module contract:** public-api-change
- **Тесты:** 67 passed (plugins), 623 passed (все табы)
- **Sentrux:** 7137 (−1 vs E.4 7138, шум)
- **Объём:** 5 production-файлов (tab, presenter, sandbox, sandbox_presenter, _sections) + новый tests/_helpers.py; 6 тест-файлов переписаны.
- **Ключевое решение — bridge, а не Protocol (в отличие от E.4):** PluginCatalog Protocol объективно недостаточен — presenter/sandbox используют `entry.plugin_class` (инстанцирование плагина в sandbox), `entry.register_classes`, `entry.inputs/outputs` — ничего из этого нет в PluginSpec. Поэтому raw bridge:
  - `plugin_registry` → `getattr(services.plugins, "_registry")` (как Pipeline E.1)
  - `registers_manager` → `getattr(services.registers, "_rm")` (get_fields)
  - `service_registry` (sandbox webcam) → `getattr(services.services, "_registry")`
- **plugin_manager (discovery/hot-reload) — runtime-объект ВНЕ AppServices:** `build_app_services` оборачивает только `plugin_registry`, а `plugin_manager` отдельный в `ctx.extras`. Передаётся explicit-параметром `PluginsPresenter(services, *, plugin_manager=...)` / `PluginsTab(services, *, plugin_manager=...)`; извлекается в `create(ctx)` из `ctx.plugin_manager()`. Нужен только секции «Пути».
- **Прочее:** `form_context` → None (TODO Phase F, не покрыт Protocol); `auth` → `services.auth._state`; `action_bus` → `services.commands.action_bus` bridge; `log_warning` удалён (AppContext его не имел — всегда loguru). Sections: `build_plugin_sections(services, *, plugin_manager, open_sandbox_cb)` closures (паттерн Settings), кэш «Пути» по `id(services)`.
- **Урок:** bridge vs Protocol зависит от полноты Protocol. E.4 Services → Protocol (адаптер покрывал API). E.5 Plugins → bridge (PluginSpec не покрывает plugin_class/register_classes). Оба honest; решает реальное покрытие.

### Phase E.6 — Displays tab [PENDING] (зависит от E.5)

- **Module contract:** public-api-change

---

---

# Task E.1 — Pipeline tab migration to AppServices DI

**Level:** Senior+ (teamlead, Opus extended thinking)
**Assignee:** teamlead
**Goal:** Мигрировать `PipelineTab` + `PipelinePresenter` + `NodeInspectorPanel` с `AppContext` на `AppServices`, устранив все 21+ legacy-обращения к `ctx.topology_holder()`, `ctx.action_bus()`, `ctx.plugin_registry()`, `ctx.registers_manager()` в pipeline/*.py.
**Context:** Pipeline — крупнейший consumer legacy API (21 из 40 топологических чтений, 4 разных сервиса). Успешная миграция подтверждает архитектуру AppServices для сложнейшего случая и даёт шаблон для E.2–E.6. Основной риск: scene-reload должен сохранить позиции и selection; typed EventBus события для нод/wire откладываются на Phase G (пока остаётся `holder.on_changed` fallback).

**Files:**

| Файл | Изменение |
|---|---|
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` | Мигрировать `__init__` + `create()`, убрать `ctx.*()` |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` | Мигрировать на `services: AppServices` |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` | Убрать `ctx.registers_manager()`, `ctx.form_context()` |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/palette/palette_widget.py` | Проверить на ctx-зависимости, мигрировать при наличии |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_controller.py` | Обновить получение зависимостей (через services или отдельный параметр) |
| `multiprocess_prototype/frontend/tab_factory.py` | Обновить ветку `Pipeline` → `ctx.app_services` |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_pipeline_tab_integration.py` | Заменить `MagicMock` на `make_test_app_services()` |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_presenter_enhanced.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_save_recipe.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_inspector.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_presenter_inspector_integration.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_validation.py` | Аналогично |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_yaml_positions.py` | Аналогично |

**Шаги:**

1. **Pre-investigation (обязательно перед кодом):**
   - Запустить `grep -rn "ctx\." multiprocess_prototype/frontend/widgets/tabs/pipeline/ --include="*.py"` — получить актуальный полный список legacy-обращений (audit был на Phase A, могли добавиться новые)
   - Запустить `python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/ -W always::DeprecationWarning 2>&1 | grep "deprecated"` — зафиксировать список DeprecationWarning до миграции
   - Сверить каждое обращение с маппингом `_DEPRECATED_KEYS_MAP` в `multiprocess_prototype/frontend/_deprecated_extras.py` — убедиться, что все покрыты Protocol'ами AppServices
   - Для необнаруженного Protocol'а — оставить `ctx.extras` с явным комментарием `# TODO Phase F: расширить Protocol X` (см. migration guide, edge case «Фича не покрыта Protocol'ами»)

2. **`PipelineTab.__init__` — изменить сигнатуру:**
   ```python
   def __init__(self, services: AppServices, *, parent: QWidget | None = None) -> None:
   ```
   Обновить `create()` classmethod — паттерн из Settings tab:
   ```python
   @classmethod
   def create(cls, ctx: AppContext) -> "PipelineTab":
       assert ctx.app_services is not None, "AppServices не инициализирован (Task D.1)"
       return cls(ctx.app_services)
   ```
   Заменить в `tab.py`:
   - `ctx.action_bus()` → `services.commands` (для undo/redo передать в `enable_undo_redo`)
   - `self._ctx.plugin_registry()` в `_load_palette()` → `services.plugins.list()`
   - `self._ctx.auth` в `_can_edit()` и `_build_action_widget()` → `services.auth`
   - Undo/Redo: `bus.undo()` / `bus.redo()` — уточнить поддержку CommandDispatcher Protocol или оставить bridge (см. edge case ниже)

3. **`PipelinePresenter.__init__` — мигрировать на services:**
   - Заменить сигнатуру: `def __init__(self, services: AppServices) -> None:`
   - `ctx.topology_holder()` (строки 58–60) → `services.topology` + `services.events.subscribe(...)` для нотификаций (см. migration guide строки 117–142). **НО:** scene-reload через typed events (`ProcessAdded`, `WireConnected` и т.п.) откладывается на Phase G — оставить `holder.on_changed` через адаптер с `# TODO Phase G: перейти на typed events`
   - `self._ctx.registers_manager()` → `services.registers`
   - `self._ctx.action_bus()` → `services.commands`
   - `self._ctx.plugin_registry()` → `services.plugins`
   - `set_inspector(panel)` — передавать `services` в panel вместо `ctx`

4. **`NodeInspectorPanel` — обновить зависимости:**
   - `self._ctx.registers_manager()` (строка ~490) → `services.registers`
   - `self._ctx.form_context()` (строка ~503) → уточнить Protocol: если `form_context` не покрыт AppServices — оставить `ctx.extras` с TODO, не изобретать workaround

5. **`WireMetricsController` — telemetry bridge:**
   - Telemetry — live runtime, остаётся вне scope Phase E (см. Out of scope). Только обновить получение зависимостей если они передаются через ctx. Проверить сигнатуру; если WireMetricsController не использует ctx напрямую — изменений нет.

6. **`tab_factory.py` — обновить фабрику:**
   - Найти ветку создания `PipelineTab` в `tab_factory.py`
   - Изменить на `PipelineTab.create(ctx)` (внутри `create()` происходит `assert ctx.app_services is not None` и `cls(ctx.app_services)`)
   - Либо напрямую: `PipelineTab(ctx.app_services)` — аналогично Settings tab

7. **Тесты — заменить MagicMock на builder:**
   - Во всех 8+ тестовых файлах: заменить `ctx = MagicMock()` / `ctx.xxx.return_value = ...` на `services = make_test_app_services(...)` из `multiprocess_prototype/domain/tests/_fakes.py`
   - Создать `PipelinePresenter(services)` / `PipelineTab(services)` вместо `...(ctx)`
   - Тесты, проверяющие поведение action_bus (`test_add_process_with_action_bus` и т.п.) — использовать `FakeCommandDispatcher` или аналог из `_fakes.py`
   - Сохранить все assertion'ы без изменения логики тестов

8. **Phase D follow-up #1 проверка:**
   - Если Pipeline читает/пишет config через `services.config` — зафиксировать в checklist этого плана: нужен ли shared ConfigStore (см. follow-up #1)

**Acceptance criteria:**

- [ ] `PipelineTab.__init__(services: AppServices, *, parent: QWidget | None = None)` — `ctx` отсутствует в сигнатуре
- [ ] `PipelinePresenter.__init__(services: AppServices)` — `ctx` отсутствует в сигнатуре
- [ ] `grep -rn "ctx\." multiprocess_prototype/frontend/widgets/tabs/pipeline/ --include="*.py" | grep -v "# TODO Phase"` → 0 результатов в production-коде (не в тестах, не TYPE_CHECKING блоках, не в TODO-комментариях)
- [ ] `python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/ -W always::DeprecationWarning 2>&1 | grep "_deprecated_extras"` → 0 строк
- [ ] `python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/` → все тесты зелёные (test_pipeline_tab_integration, test_presenter_enhanced, test_launch_recipe, test_save_recipe, test_inspector, test_presenter_inspector_integration, test_wire_validation, test_yaml_positions, test_pipeline_scene + остальные)
- [ ] Ни один тест-файл Pipeline не содержит `MagicMock()` без spec — везде `make_test_app_services()` или `MagicMock(spec=SomeProtocol)`
- [ ] Qt-MCP smoke: `python -m multiprocess_prototype.run` → qt_snapshot → PipelineTab рендерится без Qt warnings; toolbar кнопки кликабельны; drag из palette на canvas не вызывает exception
- [ ] Phase D follow-up #1 (Split ConfigStore) — зафиксировано решение в checklist выше (shared или документированный split)
- [ ] `sentrux session_end` — modularity score не упал ниже 7161 (baseline Phase D)
- [ ] Commit: `feat(pipeline,adapters): Phase E / Task E.1 — Pipeline мигрирован на AppServices DI` + `Why:`, `Layer: prototype`, `Refs: plans/2026-05-27_cross-tab-architecture/phase-e-per-tab-migration.md`

**Out of scope E.1:**
- Удаление `AppContext` / `ctx.extras` — Phase F
- Полная замена `holder.on_changed` broadcast → typed domain events — Phase G
- Удаление `topology_bridge` — Phase F
- Undo/Redo архитектурная ревизия (action_bus vs CommandDispatcher) — явно задокументировать текущее решение как временное

**Risks:**

- **HIGH — scene reload теряет позиции/selection.** При переходе с `holder.on_changed` на typed events — если typed events не покрывают случай «полной перезагрузки топологии» (batch reload), scene может сбросить позиции узлов. Решение: оставить `holder.on_changed` для batch-reload с `# TODO Phase G:`, typed events использовать только для incremental add/remove.
- **MEDIUM — Palette/Inspector sub-presenter'ы.** `NodeInspectorPanel` получает `ctx` через `set_context(self._ctx)` в `set_inspector()`. После миграции нужно решить: передавать `services` в panel напрямую или держать `ctx` как bridge-параметр. Рекомендация: передавать `services` — это уберёт 2 оставшихся legacy-вызова в inspector_panel.py.
- **MEDIUM — `form_context()`.** `CardsFieldFactory.create()` принимает `form_ctx` — этот объект не покрыт AppServices Protocol'ами. Если убрать невозможно без Phase F — оставить `# TODO Phase F:` комментарий.
- **LOW — `WireMetricsController` telemetry.** Live runtime bridge остаётся; если controller не использует `ctx` напрямую — изменений нет. Проверить при pre-investigation.

**Module contract:** public-api-change

---

---

# Tasks E.2–E.6 — High-level (детализируются после approval E.1)

> Полная декомпозиция каждого таба пишется в отдельном phase-file или дополнении к этому файлу **только после approval предыдущей задачи**.

---

## Task E.2 — Processes tab

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Зависимости:** E.1 approved

**Основные файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/tab.py`
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` — 1 legacy-вызов `ctx.plugin_registry()`
- `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py` — 2 legacy-вызова
- `multiprocess_prototype/frontend/widgets/tabs/processes/tests/test_processes_tab.py`

**Ожидаемый объём:** ~3 production-файла, ~1 test-файл. Простейший consumer — read-only topology.

**Acceptance criteria (высокий уровень):**
- [x] `ProcessesTab.__init__(services: AppServices, *, ...)` без ctx (+ explicit runtime kwargs)
- [x] 0 legacy `ctx.plugin_registry()` / `ctx.topology_holder()` в production-коде
- [x] Все тесты зелёные (50 processes / 624 tabs), `make_processes_services()` builder поверх `make_test_app_services()`
- [x] 0 DeprecationWarning из `_deprecated_extras` (`pytest -W always::DeprecationWarning`)
- [ ] Qt-MCP smoke: ProcessesTab рендерится без warnings — **deferred to cumulative после E.6** (multiprocess: MCP не достучался до GUI-процесса, как в E.1)

**Module contract:** public-api-change

---

## Task E.3 — Recipes tab

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Зависимости:** E.2

**Основные файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_io.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_form.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_presenter.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_tab.py`

**Примечание:** grep при audit показал 0 legacy-вызовов в recipes/. Перед стартом — повторный grep для верификации (могли добавиться). Если 0 — E.3 сводится к обновлению сигнатуры и factory.

**Acceptance criteria (высокий уровень):**
- [x] `RecipesTab.__init__(services: AppServices, *, parent=...)` без ctx
- [x] ConfigStore follow-up #2 (`_firing` guard) — проверено: RecipesTab НЕ использует reactive config chains → guard не нужен
- [x] Все тесты зелёные (23 recipes / 624 tabs), `make_recipes_services()` builder
- [x] 0 DeprecationWarning из `_deprecated_extras`
- [ ] Qt-MCP smoke — **deferred to cumulative после E.6**

**Module contract:** public-api-change

---

## Task E.4 — Services tab

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Зависимости:** E.3

**Основные файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — 1 legacy-вызов
- `multiprocess_prototype/frontend/widgets/tabs/services/presenter.py` — 5 вызовов `ctx.service_registry()`
- `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py`
- `multiprocess_prototype/frontend/widgets/tabs/services/tests/test_services_tab.py` — 1 вызов

**Примечание:** `service_registry()` маппится на `services.services` (ServicesManager Protocol). Presenter мутирует lifecycle (start/stop/restart) — убедиться, что ServicesManager Protocol покрывает эти методы.

**Acceptance criteria (высокий уровень):**
- [x] `ServicesTab.__init__(services: AppServices, *, parent=...)` без ctx
- [x] 0 `ctx.service_registry()` в production-коде
- [x] ServiceManager Protocol покрывает все mutation-методы (start/stop/restart/get_lifecycle) — **покрывает**, presenter делегирует напрямую (DomainError→bool). Расширение Protocol не потребовалось.
- [x] Все тесты зелёные (24 services / 623 tabs), `make_services_services()` builder
- [x] 0 DeprecationWarning из `_deprecated_extras`
- [ ] Qt-MCP smoke — **deferred to cumulative после E.6**

**Module contract:** public-api-change

---

## Task E.5 — Plugins tab

**Level:** Middle+ (developer, Sonnet extended thinking)
**Assignee:** developer
**Зависимости:** E.4

**Основные файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — 1 вызов
- `multiprocess_prototype/frontend/widgets/tabs/plugins/presenter.py` — 8 вызовов (`plugin_registry`, `plugin_manager`, `registers_manager`)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py` — 3 вызова
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox_presenter.py` — 2 вызова
- `multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py` — 3 вызова
- `multiprocess_prototype/frontend/widgets/tabs/plugins/paths_subtab.py`
- Все 6 тест-файлов в `tests/`

**Примечание:** 25 legacy-вызовов в 11 файлах — самый объёмный таб после Pipeline. `plugin_manager()` и `plugin_registry()` оба маппятся на `services.plugins` (PluginCatalog Protocol), проверить точность маппинга перед стартом. Sandbox может использовать `plugin_manager` для lifecycle (install/uninstall) — уточнить Protocol покрытие.

**Acceptance criteria (высокий уровень):**
- [x] `PluginsTab.__init__(services: AppServices, *, plugin_manager=None, parent=...)` без ctx
- [x] 0 `ctx.plugin_registry()` / `ctx.plugin_manager()` в production-коде
- [x] Sandbox presenter+widget мигрированы (raw bridge `_registry` + явные TODO Phase F)
- [x] Все 6 тест-файлов зелёные (67 plugins / 623 tabs), `make_plugins_services()` builder
- [x] 0 DeprecationWarning из `_deprecated_extras`
- [ ] Qt-MCP smoke: catalog + sandbox — **deferred to cumulative после E.6**

**Module contract:** public-api-change

---

## Task E.6 — Displays tab

**Level:** Junior (developer, Haiku normal)
**Assignee:** developer
**Зависимости:** E.5

**Основные файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/displays/tab.py` — `create()` factory использует `ctx.display_registry` и `ctx.config_paths` через `getattr` фолбэк
- `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py`
- `multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_displays_tab.py`

**Примечание:** grep показал 0 legacy `ctx.xxx()` вызовов в displays/. Основная работа — обновить `create()` factory: заменить `getattr(ctx, "display_registry", None)` на `services.displays` и `getattr(ctx, "config_paths", None)` на путь из `services.config` или явный параметр.

**Acceptance criteria (высокий уровень):**
- [ ] `DisplaysTab.__init__(registry, yaml_path, *, parent=...)` или `DisplaysTab(services: AppServices, *, parent=...)` — убрать `ctx=ctx` параметр
- [ ] `create(ctx)` использует `ctx.app_services` а не `getattr` фолбэки
- [ ] Все тесты зелёные
- [ ] Qt-MCP smoke: displays CRUD без warnings
- [ ] После E.6: запустить полный Phase E cumulative acceptance criteria (grep по всем табам, sentrux)

**Module contract:** public-api-change

---

## Риски и ограничения Phase E

| Риск | Уровень | Митигация |
|---|---|---|
| Pipeline scene reload теряет позиции | HIGH | Оставить `holder.on_changed` fallback, typed events — Phase G |
| `form_context()` не покрыт Protocol'ами | MEDIUM | TODO Phase F комментарий, не workaround |
| Split ConfigStore рассинхронизация | MEDIUM | Принять решение на E.1/E.2, зафиксировать в follow-up checklist |
| Plugins sandbox lifecycle не покрыт `PluginCatalog` | MEDIUM | Уточнить Protocol на старте E.5 |
| Параллельная работа по двум табам одновременно | LOW | Запрещено: один таб за заход, одна ветка |
| Regression в не-мигрированных табах | LOW | Deprecation shim обратно совместим; `ctx.app_services` доступен |
