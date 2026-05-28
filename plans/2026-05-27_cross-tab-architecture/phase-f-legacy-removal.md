# Phase F — Удаление legacy и закрытие bridge-компромиссов

- **Slug:** cross-tab-architecture / phase-f
- **Дата:** 2026-05-28
- **Статус:** APPROVED (открытые вопросы Q-F1…Q-F4 решены владельцем 2026-05-28 — см. «Решения владельца»)
- **Ветка:** `refactor/cross-tab-architecture` (та же, что A–E; sub-branch создаётся только при параллельной работе двух агентов — см. правило волн)

## Решения владельца (2026-05-28)

| Вопрос | Решение | Эффект |
|---|---|---|
| **Q-F4** (ActionBus→commands) | **Вынесено в Phase G** | Phase F = только удаление legacy + Protocol; #9 НЕ планируется здесь. ActionBus bridge остаётся с TODO «Phase G». |
| **Q-F1** (runtime-deps) | **Вариант B — RuntimeDeps frozen dataclass by design** | F.9 вводит `RuntimeDeps`, `create(services, runtime)`. TODO снимаются как «accepted: runtime layer». |
| **Q-F2** (plugin_class) | **Вариант C — bridge accepted + порты в spec** | plugin_class остаётся bridge (sandbox), переквалификация TODO→«by design». PluginSpec расширяется `inputs`/`outputs`. |
| **Q-F3** (framework ctx) | **Вариант B — framework не трогать** | F.9 убирает только prototype-side AppContext-зависимость; framework `ctx: object` generic-слот остаётся. |

### Правки по итогам ревью Director'а (2026-05-28)

Code-grep подтвердил факты, меняющие декомпозицию:

1. **F.1 ПЕРЕНЕСЁН В PHASE G.** Посылка F.1 («снять HIGH-риск двойной нотификации») не подтверждается кодом: `CommandDispatcher.dispatch()` НЕ используется в production (табы мутируют через ActionBus-bridge `services.commands.action_bus()`), у EventBus **ноль** production-подписчиков (`dispatch()` публикует «в никого»), а единственный рабочий путь обновления UI — legacy `holder.on_changed` (Pipeline scene reload + IPC sync). «Двойной нотификации» в наблюдаемом смысле нет; активация `suppress_legacy_notify()` сейчас убрала бы единственный рабочий callback → регрессия. Проблема становится реальной только когда `dispatch()` станет путём мутаций И табы подпишутся на события — это и есть ActionBus→commands, вынесенный в Phase G (Q-F4). **F.1 принадлежит Phase G, в связке с ActionBus.** Phase F становится чисто низкорисковой.
2. **F.2 РАЗДЕЛЁН на F.2a / F.2b.** F.2 смешивал мёртвый код (нулевой риск) и поведенческое изменение ([pipeline/presenter.py:269](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L269) `config.get("topology")` → `services.topology.load()` — смена источника, не уборка). F.2a = чистые удаления; F.2b = смена источника с тестом на эквивалентность данных.
3. **`domain/tests/_fakes.py` — общий collision-файл F.3–F.6** (единый файл, FakeDisplayCatalog/FakeRecipeStore/FakePluginCatalog/FakeAuthFacade). `domain/protocols/` пофайловый (раздельно), а `_fakes.py` и `protocols/__init__.py` — последовательно (см. правило волн).
4. **Тест-стратегия в acceptance каждого Fi:** мигрированные тесты используют builder/Fake, НЕ `MagicMock(spec=AppContext)` (история ложного green — память `feedback_qt_mcp_smoke_verification`).
5. **Sentrux-цель F.10 переформулирована:** не «восстановить к 7161», а «замерить дельту + объяснить» (Protocol/adapter-код Phase C/D гнал complex functions вверх, удаление bridge убирает не сложные функции, а `getattr` — рост возможен).

---

## Назначение

Детализированный subplan Phase F master-плана `cross-tab-architecture`.
После завершения Phase E (E.1–E.6 все DONE — 6 табов мигрированы на AppServices DI)
накопился временный legacy-слой и набор задокументированных bridge-компромиссов
(Q1–Q7 Phase C + per-tab TODO Phase F из E.1–E.6). Phase F:

1. Удаляет неиспользуемый legacy-код (`ctx.extras["topology"]`/`config["topology"]`,
   4 неподключённые dataclass-обёртки, dead alias).
2. Закрывает HIGH-риск double-notification (активирует `suppress_legacy_notify()`).
3. Закрывает bridge-компромиссы расширением Protocol'ов там, где это оправдано
   реальным покрытием (урок E.4/E.5: Protocol только если adapter покрывает API).
4. Убирает legacy `ctx`-параметр из фабрик/базовых классов.
5. Переводит DeprecationWarning → error в тестах (forcing-функция против регрессии).

**Что НЕ входит в Phase F (явный scope cut):**
- Полное удаление `TopologyHolder` и замена `holder.on_changed` broadcast → typed
  domain events — **остаётся Phase G** (PipelinePresenter/TopologyBridge/RecipeApplyHandler
  всё ещё зависят от holder для batch scene reload; typed events для нод/wire не готовы).
  Phase F редуцирует роль holder до derived store с подавлением legacy-нотификаций,
  но не удаляет его.
- ActionBus → domain commands полностью — **вынесено в отдельную под-фазу / Phase G**
  (см. раздел «Рекомендация: вынести ActionBus→commands» и открытый вопрос Q-F4).
- `bindings` (GuiStateBindings) → AppServices — Phase G (Q4 Phase D).
- Live runtime snapshot (PID/FPS/метрики) — Phase G.

---

## Источники истины

| Документ | Что содержит |
|---|---|
| [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) разд. 5 (стр. 313–322), 7 (Success criteria), 8 (антипаттерны) | Brief Phase F, критерии, запрет big-bang |
| [`plans/2026-05-27_cross-tab-architecture/phase-e-per-tab-migration.md`](phase-e-per-tab-migration.md) | Per-tab решения E.1–E.6, какие bridge остались, какие TODO Phase F помечены |
| [`multiprocess_prototype/adapters/README.md`](../../multiprocess_prototype/adapters/README.md) | decisions Q1–Q7, compromises, что упрощается в Phase F |
| [`docs/refactors/2026-05_phase_e_migration_guide.md`](../../docs/refactors/2026-05_phase_e_migration_guide.md) | Паттерн presenter-сигнатуры, edge cases, маппинг extras→AppServices |

> **Правило:** перед стартом каждой задачи Fi — `grep -rn "TODO Phase F"` по
> `multiprocess_prototype/` для актуального списка call-sites (на момент планирования — 34 в 26 файлах)
> и перечитать соответствующий per-tab раздел phase-e плана.

---

## Реальный inventory call-sites (на 2026-05-28)

`grep "TODO Phase F"` → **34 совпадения в 26 файлах**. Агрегировано по направлениям:

| Направление | Файлы | Тип работы |
|---|---|---|
| #1 `ctx.extras["topology"]`/`config["topology"]` | `app.py:177`, `pipeline/presenter.py:269` | Удаление (read-only fallback) |
| #2 TopologyHolder / suppress / double-notify | `command_dispatcher.py`, `topology_repository.py`, `topology_holder.py` | **Senior+** — активация suppress |
| #3 4 dataclass-обёртки | `frontend/{topology,state,plugins,actions}_context.py` | Удаление (нигде не импортируются) |
| #4 DeprecationWarning → error | `pytest.ini`, `_deprecated_extras.py` (опц.) | Конфиг + фикс fallout |
| #5a DisplayStore writable Protocol | `displays/tab.py`, `adapters/.../display_catalog.py`, `domain/protocols/` | **Middle+** Protocol |
| #5b RecipeStore rich API | `recipes/tab.py`, `pipeline/presenter.py`, `pipeline/inspector_panel.py`, `adapters/.../recipe_store.py`, `domain/protocols/` | **Senior** Protocol |
| #5c PluginCatalog rich entry | `plugins/{presenter,sandbox,sandbox_presenter,_sections}.py`, `pipeline/presenter.py`, `domain/.../plugin.py` | **Senior** Protocol/spec |
| #5d AuthFacade permission gating | `services/_sections.py`, `pipeline/tab.py`, `processes/tab.py`, `plugins/_sections.py` | **Middle+** Protocol |
| #5e CommandDispatcher.action_bus() | `services/tab.py`, `pipeline/tab.py`, `plugins/tab.py`, `_sections.py` | связано с #9 |
| #6 `ctx=None` + factory без AppContext | 6 prototype tabs + framework `Base{List,Tree}NavTab` + `tab_factory.py` + `register_all_tabs` | **Senior+** cross-layer |
| #7 runtime-deps вне AppServices | `processes/tab.py`, `plugins/tab.py`, `pipeline/presenter.py:843`, `displays/tab.py` | **Архитектурное решение** (см. Q-F1) |
| #8 Recipe YAML v2→v3 | `domain/entities/recipe.py`, `domain/tests/test_entities_roundtrip.py`, `recipes/*.yaml` | **Middle** |
| #9 ActionBus → domain commands | `pipeline/{tab,presenter}.py`, `plugins/{tab,_sections}.py`, `services/tab.py` (11+ TODO) | **Senior+** — кандидат в Phase G |

---

## КЛЮЧЕВОЕ архитектурное ограничение (читать до декомпозиции)

**TopologyHolder остаётся в Phase F.** Три prod-подписчика на `holder.on_changed` /
`holder.set_topology`:

1. `app.py:225` — `topology_holder.on_changed(topology_bridge.on_topology_changed)` (IPC sync)
2. `pipeline/presenter.py:74` — `holder.on_changed(self._on_topology_changed_external)` (scene reload)
3. `actions/handlers/recipe_handler.py` — `RecipeApplyHandler.set_topology()` (recipe apply/undo)

Замена `holder.on_changed` broadcast на typed domain events (`ProcessAdded`,
`WireConnected`...) **явно отложена на Phase G** (Phase E plan стр. 91, Out of scope E.1).
Поэтому Phase F по направлению #2 делает НЕ удаление holder, а:
- активирует `suppress_legacy_notify()` в `CommandDispatcherOrchestrator.dispatch()`,
  чтобы убрать **двойную** нотификацию (legacy callbacks + EventBus), оставив одну;
- но holder продолжает жить как derived store до Phase G.

Это снимает HIGH-риск Q7 (double-notification), не ломая scene reload.

**Урок E.4/E.5 для всех #5-задач:** bridge закрываем Protocol'ом ТОЛЬКО если adapter
реально покрывает нужный API. Если presenter использует `entry.plugin_class` /
`register_classes` (которых нет в spec) — Protocol-расширение требует РАСШИРЕНИЯ spec
(domain entity), а не косметики. Где расширение spec нецелесообразно (over-engineering,
антипаттерн brief §8) — bridge остаётся by design, TODO снимается с пометкой «accepted».

---

## Граф зависимостей задач

```
F.2a (dead code: #3,alias,extras) ──┐
F.2b (topology source switch)     ──┼──> F.7 (DeprecationWarning→error) ──> F.10 (cumulative)
                                    │                                          ^
F.3 (DisplayStore Protocol) ───┐    │                                          │
F.4 (RecipeStore Protocol)  ───┼────┼──> (закрытие bridge, независимы) ────────┤
F.5 (PluginCatalog spec)    ───┤    │                                          │
F.6 (AuthFacade Protocol)   ───┘    │                                          │
                                    │                                          │
F.8 (Recipe YAML v2→v3) ─────────────────────────────────────────────────────┤
                                                                               │
F.9 (ctx=None + factory cleanup) ──── зависит от F.3–F.6 ──────────────────────┘
                                       (presenter'ы должны быть на Protocol до удаления ctx)

F.1 (suppress) ─────────> ПЕРЕНЕСЁН В PHASE G (посылка не подтверждена кодом — см. ревью)
ActionBus→commands ─────> ВЫНЕСЕНО В PHASE G (Q-F4)
```

**Порядок безопасности (критично, big-bang запрещён — антипаттерн brief §8):**
1. **F.2a ПЕРВОЙ** — чистые удаления неиспользуемого кода (нулевой риск, разблокирует чистый grep).
2. **F.2b** — смена источника топологии в Pipeline-presenter (поведенческое, с тестом эквивалентности).
3. **F.3–F.6** — закрытие bridge через Protocol (каждый независим, presenter переходит на Protocol).
4. **F.9 ПОСЛЕ F.3–F.6** — удаление `ctx=None` и `create(ctx)` bridge только когда presenter'ы
   больше не зависят от ctx через bridge (иначе сломаем runtime-доступ).
5. **F.7 ПОСЛЕ F.2–F.6 + F.9** — `error::DeprecationWarning` включаем последним, когда extras-доступов
   в production не осталось (иначе тесты падают преждевременно).
6. **F.8** — независимая (YAML формат), можно в любой волне.
7. **F.10** — финальная cumulative-проверка + Qt-MCP smoke (ручной перед merge).
8. **F.1 (suppress) — НЕ в Phase F**, перенесён в Phase G к ActionBus→commands.

---

## Волны выполнения (макс 2 параллельных агента — commit race, см. память)

| Волна | Задачи | Параллелизм | Обоснование |
|---|---|---|---|
| **Wave 1** | F.2a → F.2b | Последовательно | F.2a — чистые удаления (нулевой риск). F.2b — смена источника топологии (тот же presenter, поведенческое). |
| **Wave 2** | F.3 + F.4 | 2 агента, НО `_fakes.py`/`protocols/__init__.py` — последовательный merge | Разные Protocol-файлы. Общие `domain/tests/_fakes.py` и `protocols/__init__.py` коммитит один агент, второй ребейзится. |
| **Wave 3** | F.5 + F.6 | 2 агента, та же оговорка по `_fakes.py` | Разные Protocol-файлы. |
| **Wave 4** | F.8 | 1 агент | Независимая, YAML/domain. Можно как 2-й агент в Wave 2/3 (трогает recipe.py + _fakes.py — координировать). |
| **Wave 5** | F.9 | 1 агент (Senior+) | После F.3–F.6. Cross-layer, нельзя параллелить. Вводит RuntimeDeps (Q-F1=B). |
| **Wave 6** | F.7 | 1 агент | После F.2–F.6, F.9. error:: + fallout. |
| **Wave 7** | F.10 | 1 агент (director/teamlead) | Финал: cumulative acceptance + ручной Qt-MCP smoke. |

> **Правило волн:** внутри волны два агента работают над **непересекающимися файлами**.
> Общие файлы — последовательно: `domain/tests/_fakes.py` (единый, F.3–F.6 + F.8), `domain/protocols/__init__.py`, `adapters/__init__.py`, `adapters/catalogs/__init__.py`.
>
> **Тест-стратегия (acceptance каждого Fi):** мигрированные/новые тесты используют builder или Fake из `_fakes.py`, **НЕ** `MagicMock(spec=AppContext)` — иначе ложный green (память `feedback_qt_mcp_smoke_verification`).

---

## Открытые вопросы (требуют решения владельца до старта соответствующих задач)

### Q-F1 (БЛОКИРУЕТ F.9) — runtime-deps вне AppServices: судьба explicit kwargs

Из Phase E (E.2/E.5/E.6) накопились runtime-объекты, передаваемые как **explicit kwargs**
в `create(ctx)`, потому что они НЕ обёрнуты в AppServices (`build_app_services` оборачивает
только реестры/config):

| Объект | Где используется | Природа |
|---|---|---|
| `process_manager_proxy` | `pipeline/presenter.py:843` | IPC-прокси к ProcessManager (runtime) |
| `topology_bridge` | `processes/tab.py:116` | GUI↔Runtime IPC мост (runtime) |
| `plugin_manager` | `plugins/tab.py:152` | discovery/hot-reload (runtime singleton) |
| `command_sender` | `processes/tab.py` | IPC отправка команд (runtime) |
| `form_context` | `pipeline/inspector_panel.py:528`, `plugins/_sections.py:213` | сборка FormContext (UI runtime) |
| `router_manager` | `displays/tab.py` | preview SHM (runtime, в проде None) |

**Урок E.5 (память):** это **другой слой** — Qt-signal runtime state, не data-catalogs.
Попытка засунуть в Protocol = over-engineering (антипаттерн brief §8).

**Вопрос владельцу — выбрать стратегию (по умолчанию рекомендуется вариант B):**
- **A.** Расширить AppServices новым полем-агрегатом `runtime: RuntimeServices`
  (process_manager_proxy, topology_bridge, plugin_manager, command_sender).
  Минус: смешивает data-layer и runtime-layer в одном DI; противоречит «editor vs runtime» (brief §4.2).
- **B (рекомендация).** Оставить explicit kwargs **by design навсегда** — формализовать паттерн:
  отдельный frozen dataclass `RuntimeDeps` передаётся вторым параметром в `create()`.
  Снимает TODO с пометкой «accepted: runtime layer, не AppServices». Это и есть «editor state
  vs runtime state» разделение из brief §4.2 п.7.
- **C.** Отложить полностью в Phase G (live runtime snapshot aggregate) — тогда F.9 удаляет только
  `ctx=None`, а explicit kwargs остаются как есть с TODO Phase G.

> Без решения Q-F1 задача F.9 не может корректно убрать `create(ctx)` bridge — там извлекаются
> эти runtime-объекты из ctx. Рекомендация: **вариант B** — он честно фиксирует, что runtime-слой
> не часть AppServices, и не плодит премётивную абстракцию.

### Q-F2 (БЛОКИРУЕТ F.5) — PluginCatalog: расширять PluginSpec до `plugin_class`?

`sandbox.py`/`sandbox_presenter.py`/`presenter.py` используют `entry.plugin_class` (инстанцирование
плагина в sandbox), `register_classes`, `inputs/outputs`. PluginSpec этого не содержит (compromise C).
Варианты:
- **A.** Добавить `plugin_class: type` в PluginSpec → DisplayCatalog/PluginCatalog Protocol даёт
  богатую запись. Минус: domain spec начинает тащить Python-классы (нарушает «catalog = метаданные»).
- **B.** Ввести узкий `PluginInstantiator` Protocol только для sandbox (`instantiate(name) -> object`),
  оставив PluginSpec метаданными. Sandbox получает его как отдельный сервис.
- **C (default).** Принять bridge `services.plugins._registry` как permanent для sandbox-сценария,
  снять TODO с пометкой «accepted: sandbox требует live class, не catalog». Расширить spec только
  на `inputs/outputs` (порты — это метаданные, оправданно для Pipeline-валидации).

> Рекомендация: **C** для plugin_class (sandbox — единственный потребитель, не стоит ломать spec),
> но **расширить PluginSpec портами inputs/outputs** (направление #5c частично, нужно Pipeline для
> валидации wire — pipeline/presenter.py:468 TODO). Финальное решение — за владельцем.

### Q-F3 (влияет на F.9) — `ctx` в framework Base{List,Tree}NavTab

`BaseTreeNavTab`/`BaseListNavTab` (слой **framework**) прокидывают `ctx` в
`spec.factory(ctx)` и `spec.presenter_factory(ctx, section)`. Прототип передаёт `ctx=None`,
а section-factory'и замыкают `services` через closures. Варианты для F.9:
- **A.** Удалить `ctx`-параметр из framework базовых классов и `SectionSpec.factory` сигнатуры →
  чистый контракт, но это **framework-layer breaking change** (public-api-change модуля
  frontend_module, свои тесты, свой README/STATUS, потенциально другие приложения-потребители).
- **B (default).** Оставить framework `ctx: object` параметр как **generic-слот** (framework
  не знает про AppContext — это by design), а в прототипе просто прекратить передавать `ctx=None`
  как «legacy»: переименовать в нейтральный комментарий, factory'и продолжают игнорировать арг.
  Минус: косметика, `ctx=None` формально остаётся.

> Рекомендация: **B** — framework намеренно generic (`ctx: object`), его контракт не про
> AppContext. Удаление параметра из framework — отдельный framework-refactor, не входит в
> cross-tab scope (это prototype-рефакторинг). F.9 убирает prototype-side AppContext-зависимость,
> framework generic-слот не трогает. Если владелец хочет A — это +1 задача с module-contract
> `public-api-change` на framework и отдельным sentrux-замером.

### Q-F4 (БЛОКИРУЕТ планирование ActionBus) — выносить ли #9 в Phase G?

ActionBus → domain commands = 11+ TODO sites, undo/redo семантика, расширение
CommandDispatcher Protocol (`undo()`/`redo()`/`execute()`), затрагивает pipeline/plugins/services.
Это **самое крупное и рискованное** направление, сопоставимое по объёму со всей Phase E.

> **Рекомендация Manager'а: ВЫНЕСТИ из Phase F.** Причины:
> 1. Phase F — «1-2 дня» по brief (§5). ActionBus-миграция одна потянет на 3-5 дней.
> 2. Риск: undo/redo завязан на `V2ActionBuilder` и `ActionBus.execute` — это отдельная
>    подсистема, требует своего audit (как Phase A для топологии).
> 3. Brief §8 запрещает big-bang. Смешать «удаление legacy» (низкий риск) с «переписать undo/redo»
>    (высокий риск) в одной фазе = нарушение принципа атомарных фаз.
>
> **Предложение:** ActionBus→commands становится **Phase F.A** (отдельный subplan, детализируется
> после F.10) ИЛИ переносится в расширенную Phase G. До тех пор ActionBus bridge
> (`services.commands.action_bus`) остаётся с TODO, помеченным «deferred to Phase F.A / G».
> Владелец решает: F.A сразу после F.10 или G.

---

## Порядок выполнения

### Wave 1

---

### Task F.1 — [ПЕРЕНЕСЁН В PHASE G] Активировать suppress_legacy_notify в CommandDispatcher

> **СТАТУС: ПЕРЕНЕСЁН В PHASE G — НЕ выполнять в Phase F.**
> Ревью Director'а (2026-05-28) установил code-grep'ом: `CommandDispatcher.dispatch()` не используется
> в production (мутации идут через ActionBus-bridge), у EventBus ноль production-подписчиков, единственный
> рабочий путь обновления UI — legacy `holder.on_changed`. «Двойной нотификации» в наблюдаемом смысле нет;
> активация suppress сейчас = регрессия (убрала бы единственный рабочий callback). Проблема реальна только
> после ActionBus→commands (Phase G). Спецификация ниже сохранена как заготовка для Phase G.

**Level:** Senior+ (teamlead, Opus extended thinking)
**Assignee:** teamlead (в Phase G)
**Goal:** Устранить двойную нотификацию (legacy `holder.on_changed` + EventBus) при
`dispatch()`, активировав `suppress_legacy_notify()` вокруг `topology_repo.save()`, сохранив
работоспособность scene reload через EventBus-путь.
**Context:** HIGH-риск Q7 из investigator-ревью Phase B/C. Сейчас `CommandDispatcherOrchestrator.dispatch()`
вызывает `topology_repo.save()` (триггерит legacy callbacks) И публикует events — подписчики
обновляются дважды. `suppress_legacy_notify()` (Q6) уже реализован в `topology_repository.py`,
но НЕ применяется. Активация требует, чтобы подписчики, которым нужен sync, получали его через
EventBus, а не через legacy callback.

**Files:**
- `multiprocess_prototype/adapters/dispatch/command_dispatcher.py` — обернуть `save()` в `suppress`
- `multiprocess_prototype/adapters/stores/topology_repository.py` — проверить cm (готов)
- `multiprocess_prototype/frontend/topology_holder.py` — `_suppress_notify` flag (готов)
- `multiprocess_prototype/adapters/tests/test_command_dispatcher.py` — обновить тесты (legacy callback НЕ вызывается)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — проверить: scene reload должен идти через EventBus, а не legacy callback (иначе scene не обновится при dispatch)

**Steps:**
1. **Pre-investigation:** определить, кто из подписчиков `holder.on_changed` зависит от
   нотификации при `dispatch()`-командах (НЕ при recipe_apply):
   - `topology_bridge.on_topology_changed` (app.py:225) — нужен ли ему callback при dispatch?
     Скорее НЕТ — IPC-команды идут отдельно. Проверить.
   - `pipeline/presenter.py:74` `_on_topology_changed_external` — scene reload. Это КРИТИЧНО.
     Сейчас работает через legacy callback. После suppress нужно убедиться, что Pipeline
     получает обновление через EventBus-подписку ИЛИ оставить именно этот callback незаподавленным.
2. Решение по стратегии suppress (выбрать на основе pre-investigation):
   - **Вариант A:** обернуть `topology_repo.save()` в `with self._topology_repo.suppress_legacy_notify():`
     в `dispatch()` — подавляет ВСЕ legacy callbacks при command-dispatch. Требует, чтобы
     Pipeline scene reload шёл через EventBus (typed events). Но typed events — Phase G! → риск.
   - **Вариант B (рекомендация):** suppress только `topology_bridge` callback (IPC не нужен при
     GUI-edit dispatch), оставить Pipeline scene-reload callback активным до Phase G. Реализовать
     через селективную отписку/флаг, а не глобальный suppress.
3. Реализовать выбранный вариант. Если B — возможно нужен per-callback suppress (расширить
   TopologyHolder или фильтровать в dispatch). Документировать решение в DECISIONS / adapters README.
4. Обновить `test_command_dispatcher.py`: проверить, что при `dispatch()` legacy-callback
   (тот, что подавлен) НЕ вызывается, а EventBus events публикуются.

**Acceptance criteria:**
- [ ] При `dispatch(command)` целевой legacy callback НЕ вызывается дважды (проверено тестом)
- [ ] Pipeline scene reload продолжает работать (smoke: dispatch AddProcess → нода появляется)
- [ ] Решение (вариант A/B и почему) задокументировано в `adapters/README.md` (обновить Q7)
- [ ] `python -m pytest multiprocess_prototype/adapters/` зелёные
- [ ] `mcp__sentrux__check_rules` 9/9 pass, acyclicity 10000
- [ ] Commit с `Refs: plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md`, `Layer: prototype`

**Out of scope:** удаление TopologyHolder; замена `holder.on_changed` на typed events (Phase G).
**Edge cases:** recipe_apply path (`RecipeApplyHandler.set_topology`) — НЕ через dispatch, suppress
не должен его затронуть. Двойной suppress (recursive) — cm не reentrant (single-thread Qt — OK).
**Dependencies:** нет (первая задача).
**Module contract:** impl-only

---

### Task F.2a — Удалить dead legacy: extras["topology"], 4 dataclass-обёртки, dead alias

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Goal:** Удалить заведомо мёртвый код нулевого риска: `ctx.extras["topology"]` запись,
4 неподключённые dataclass-обёртки, `ServiceCatalogFromRegistry` alias. **Без поведенческих изменений.**
**Context:** Success criteria brief §7 — «ctx.extras["topology"] удалён». Эти объекты нигде не читаются
в production (verified grep). Чистая уборка → разблокирует чистый grep для последующих задач.

**Files:**
- `multiprocess_prototype/frontend/app.py:177` — удалить `ctx.extras["topology"] = _topology_dict`
  (живой источник — holder/TopologyRepository; этот ключ — «обратная совместимость», dead)
- `multiprocess_prototype/frontend/topology_context.py` — **удалить файл** (нигде не импортируется)
- `multiprocess_prototype/frontend/state_context.py` — **удалить файл**
- `multiprocess_prototype/frontend/plugins_context.py` — **удалить файл**
- `multiprocess_prototype/frontend/actions_context.py` — **удалить файл**
- `multiprocess_prototype/adapters/catalogs/service_catalog.py:248` — удалить
  `ServiceCatalogFromRegistry = ServiceManagerFromRegistry` alias + из `__all__`
- `multiprocess_prototype/adapters/__init__.py`, `adapters/catalogs/__init__.py` — убрать re-export alias
- `multiprocess_prototype/adapters/tests/test_catalogs.py` — удалить тесты alias (`TestServiceCatalogFromRegistry`)
- `multiprocess_prototype/adapters/README.md` — убрать упоминание alias

**Steps:**
1. **Pre-investigation:** `grep -rn 'extras\["topology"\]'` и
   `grep -rn "TopologyContext\|StateContext\|PluginsContext\|ActionsContext\|ServiceCatalogFromRegistry"`
   — подтвердить 0 production-импортов кроме перечисленных.
2. Удалить `ctx.extras["topology"]` в app.py (оставить `topology_holder` ключ — он живой).
3. Удалить 4 файла `*_context.py` целиком.
4. Удалить alias `ServiceCatalogFromRegistry` (оставить только `ServiceManagerFromRegistry`),
   обновить все `__all__` и README. Тесты alias удалить.
5. Прогнать тесты adapters + frontend.

**Acceptance criteria:**
- [ ] `grep -rn 'extras\["topology"\]' multiprocess_prototype/ --include="*.py" | grep -v tests` → 0
- [ ] 4 файла `*_context.py` удалены; `grep TopologyContext` → 0
- [ ] `ServiceCatalogFromRegistry` отсутствует в коде и `__all__`; импорт `from adapters import ServiceCatalogFromRegistry` падает
- [ ] `python -m pytest multiprocess_prototype/adapters/ multiprocess_prototype/frontend/` зелёные
- [ ] Commit с Refs, `Layer: prototype`

**Out of scope:** смена источника топологии в presenter (F.2b); удаление `topology_holder` ключа (живой); AppContext (F.9).
**Edge cases:** нет (чистые удаления).
**Dependencies:** нет (первая задача Phase F).
**Module contract:** public-api-change (удаление публичного alias из adapters `__init__`)

---

### Task F.2b — Pipeline-presenter: config["topology"] snapshot → services.topology.load() (живой источник)

**Level:** Middle+ (developer, Sonnet extended thinking)
**Assignee:** developer
**Goal:** Заменить чтение устаревшего стартового snapshot `config["topology"]` на живой источник
`services.topology.load()` — «топология читается в одном месте» (Success criteria §7). **Поведенческое
изменение** — с тестом на эквивалентность данных.
**Context:** [pipeline/presenter.py:269](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L269)
`self._services.config.get("topology", {})` — это anti-pattern из brief §2.2: `config["topology"]` пишется
один раз на старте и НЕ обновляется, тогда как TopologyRepository — живой. Возможен рассинхрон.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:269` — заменить на
  `services.topology.load()` (domain Topology entity; если нужен dict — `.to_dict()`, Dict at Boundary)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_yaml_positions.py:70` — обновить
  тест под новый источник (НЕ оставлять старый путь `config.get("topology")`)
- builder/`_helpers.py` pipeline — если требуется заполнить TopologyRepository в тесте

**Steps:**
1. Pre-investigation: проверить, что именно presenter делает с результатом (читает processes/wires?) —
   подтвердить, что `services.topology.load()` даёт эквивалентную структуру.
2. Заменить источник. Если формат отличается (Topology entity vs raw dict) — адаптировать использование.
3. Обновить тест: наполнять TopologyRepository (builder), а не `config["topology"]`. **НЕ MagicMock(spec=AppContext).**
4. Smoke: убедиться, что Pipeline рендерит ноды (через builder-тест; полный GUI-smoke — F.10).

**Acceptance criteria:**
- [ ] `grep -rn 'config.*\["topology"\]\|config.get("topology"' multiprocess_prototype/frontend/widgets/tabs/` → 0 (включая тесты)
- [ ] presenter читает топологию через `services.topology.load()`
- [ ] Тест на эквивалентность: данные из нового источника == ожидаемая топология
- [ ] `python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/` зелёные
- [ ] Commit с Refs, `Layer: prototype`

**Out of scope:** удаление dead alias/обёрток (F.2a); RecipeStore (F.4).
**Edge cases:** пустая топология (свежий проект) — `services.topology.load()` должен вернуть пустой Topology, не падать.
**Dependencies:** F.2a желательно раньше (чистый grep), не строго.
**Module contract:** impl-only

---

### Wave 2–3 (Protocol-расширения, до 2 агентов параллельно)

---

### Task F.3 — DisplayCatalog → writable DisplayStore Protocol

**Level:** Middle+ (developer, Sonnet extended thinking)
**Assignee:** developer
**Goal:** Закрыть bridge `services.displays._registry` в `displays/tab.py`, расширив
DisplayCatalog (read-only) до writable DisplayStore Protocol (CRUD + DisplayEntry).
**Context:** E.6 решение — bridge, т.к. DisplayCatalog покрывает только `list_displays`/`resolve`,
а presenter'у нужен `register`/`unregister`/`persist`/`__contains__` (полный CRUD). Урок E.4:
Protocol оправдан, т.к. adapter (`DisplayCatalogFromRegistry`) уже оборачивает DisplayRegistry,
который умеет CRUD — расширить adapter, а не плодить.

**Files:**
- `multiprocess_prototype/domain/protocols/` (display catalog protocol) — добавить методы writable store
- `multiprocess_prototype/adapters/catalogs/display_catalog.py` — реализовать CRUD-делегирование в DisplayRegistry
- `multiprocess_prototype/frontend/widgets/tabs/displays/tab.py:116` — заменить `getattr(services.displays, "_registry")` на Protocol-методы
- `multiprocess_prototype/frontend/widgets/tabs/displays/tests/_helpers.py` — обновить fake (убрать `_registry` bridge)
- `multiprocess_prototype/domain/tests/_fakes.py` — FakeDisplayCatalog → реализовать новые методы
- `multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_displays_tab.py` — обновить

**Steps:**
1. Pre-investigation: `grep -n "_registry" displays/` — собрать все методы DisplayRegistry, которые
   реально вызывает presenter (register/unregister/persist/__contains__/get/list).
2. Решить: расширить существующий `DisplayCatalog` Protocol до `DisplayStore` ИЛИ ввести отдельный
   `DisplayStore` Protocol (рекомендация: расширить — один потребитель, нет смысла дробить).
3. Добавить методы в Protocol + реализовать в adapter (делегирование DisplayRegistry).
4. Заменить bridge в tab.py на Protocol-вызовы. Убрать TODO Phase F.
5. Обновить Fake + builder + тесты.

**Acceptance criteria:**
- [ ] `grep "_registry" displays/tab.py` → 0
- [ ] `displays/tab.py` использует только `services.displays.<method>`
- [ ] `python -m pytest .../displays/ multiprocess_prototype/adapters/ multiprocess_prototype/domain/` зелёные
- [ ] TODO Phase F в `displays/tab.py:116` снят
- [ ] Commit с Refs

**Out of scope:** router_manager (runtime kwarg, Q-F1); auth gating (F.6).
**Edge cases:** `__contains__` через Protocol — добавить `has(display_id)` метод (Protocol не поддержит `in`).
**Dependencies:** нет.
**Module contract:** public-api-change (domain protocols + adapters)

---

### Task F.4 — RecipeStore Protocol: rich API (read_recipe→dict, duplicate, recipes_dir, replace_blueprint, deactivate)

**Level:** Senior (teamlead, Opus normal)
**Assignee:** teamlead
**Goal:** Закрыть bridge `services.recipes._rm` в recipes/pipeline, расширив RecipeStore Protocol
до rich API, требуемого presenter'ами; устранить обращение `set_active(None)` к private `engine._active_name`.
**Context:** E.3 решение — bridge `getattr(services.recipes, "_rm")`, т.к. RecipeStore покрывает
list/read→Recipe/write/delete/get_active/set_active, но НЕ `read_recipe`→dict / `duplicate` /
`recipes_dir` / `replace_blueprint`. Compromise C (README): `set_active(None)` лезет в private
`engine._active_name` — Phase F даёт public `deactivate()`.

**Files:**
- `multiprocess_prototype/domain/protocols/` (recipe store protocol) — добавить методы
- `multiprocess_prototype/adapters/stores/recipe_store.py` — реализовать `deactivate()`, `duplicate()`,
  `read_recipe_dict()`, `recipes_dir`, `replace_blueprint()`; убрать обращение к `engine._active_name`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py:95` — заменить `_rm` bridge на Protocol
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:738,814` — заменить `_rm`
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py:410` — заменить
- `multiprocess_prototype/domain/tests/_fakes.py` — FakeRecipeStore + новые методы
- соответствующие `tests/_helpers.py` recipes/pipeline + тесты

**Steps:**
1. Pre-investigation: `grep -n "_rm\b" recipes/ pipeline/` — собрать ВСЕ методы RecipeManager,
   вызываемые presenter'ами. Сопоставить с текущим RecipeStore Protocol.
2. Для каждого недостающего метода решить: добавить в Protocol (если semantically «recipe store»)
   ИЛИ оставить bridge (если это runtime/UI-специфика). `recipes_dir` (путь) — спорно, может быть
   config-доступ. `read_recipe`→dict vs →Recipe — предпочесть Recipe entity (Dict at Boundary).
3. Реализовать `RecipeManager.deactivate()` public метод (фреймворк/prototype recipes engine),
   убрать private-доступ из adapter.
4. Расширить Protocol + adapter + Fake. Заменить bridge в 4 call-sites.

**Acceptance criteria:**
- [ ] `grep "services.recipes._rm\|_rm\b" recipes/tab.py pipeline/presenter.py inspector_panel.py` → 0
- [ ] `set_active(None)`/`deactivate()` не обращается к `engine._active_name` (public API)
- [ ] `python -m pytest .../recipes/ .../pipeline/ .../adapters/ .../domain/` зелёные
- [ ] 4 TODO Phase F (recipes/tab.py:95, pipeline/presenter.py:738,814, inspector_panel.py:410) сняты
- [ ] Commit с Refs

**Out of scope:** Recipe YAML v2→v3 формат (F.8 — отдельно); ActionBus recipe_apply (Phase F.A/G).
**Edge cases:** `replace_blueprint` с rollback (ADR-131/132) — сохранить транзакционную семантику.
`recipes_dir` — если это просто путь, рассмотреть `services.config` вместо RecipeStore.
**Dependencies:** нет (но делит `domain/protocols/__init__.py` с F.3 — НЕ параллелить с F.3 на одном файле,
координировать через волны).
**Module contract:** public-api-change

---

### Task F.5 — PluginCatalog: расширить PluginSpec портами (inputs/outputs), решить судьбу plugin_class

**Level:** Senior (teamlead, Opus normal)
**Assignee:** teamlead
**Goal:** Закрыть максимум bridge `services.plugins._registry` в plugins/pipeline через расширение
PluginSpec портами; для `plugin_class`/`register_classes` принять решение по Q-F2 (bridge accepted vs Protocol).
**Context:** E.5 урок — bridge by design, PluginSpec не покрывает `plugin_class` (sandbox
инстанцирование), `register_classes`, `inputs/outputs`. Часть закрываема (порты = метаданные,
нужны Pipeline для wire-валидации pipeline/presenter.py:468), часть — нет (plugin_class = live class).

**Files:**
- `multiprocess_prototype/domain/entities/plugin.py` (PluginSpec) — добавить `inputs`/`outputs` порты
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py` — заполнять порты из registry
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:468` — wire-валидация через Protocol
- `multiprocess_prototype/frontend/widgets/tabs/plugins/presenter.py:44,47` — оценить, что закрываемо
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py:220`, `sandbox_presenter.py:74` —
  по Q-F2: оставить bridge с «accepted» ИЛИ узкий PluginInstantiator Protocol
- `multiprocess_prototype/domain/tests/_fakes.py` + plugins/pipeline `_helpers.py` + тесты

**Steps:**
1. **БЛОКЕР Q-F2** — дождаться решения владельца (plugin_class: bridge accepted / Protocol / spec).
2. Pre-investigation: `grep -n "plugin_class\|register_classes\|inputs\|outputs\|_registry" plugins/ pipeline/`.
3. Расширить PluginSpec портами inputs/outputs (метаданные, оправдано). Adapter заполняет из PortSpec
   (уже есть `PortSpec.direction` из E.1, `optional`/`shape` из C.1.5).
4. Pipeline wire-валидация (presenter.py:468) → через `services.plugins.resolve(name).outputs/inputs`.
5. plugin_class по Q-F2: если C — оставить bridge + комментарий «accepted: live class, не catalog»,
   снять «TODO Phase F» → заменить на «# By design: sandbox требует Python-класс».

**Acceptance criteria:**
- [ ] PluginSpec содержит `inputs`/`outputs` (или подтверждённое решение не добавлять)
- [ ] Pipeline wire-валидация не использует raw `_registry` для портов
- [ ] Оставшиеся bridge (`plugin_class`) помечены «accepted by design» (Q-F2), TODO Phase F сняты/переквалифицированы
- [ ] `python -m pytest .../plugins/ .../pipeline/ .../adapters/ .../domain/` зелёные
- [ ] Commit с Refs

**Out of scope:** plugin_manager runtime (Q-F1, F.9); ActionBus в _sections (Phase F.A/G).
**Edge cases:** PortSpec уже расширен в E.1/C.1.5 — переиспользовать, не дублировать поля.
**Dependencies:** Q-F2 решён. Делит `domain/` с F.3/F.4 — координировать волны.
**Module contract:** public-api-change

---

### Task F.6 — AuthFacade Protocol: runtime permission gating

**Level:** Middle+ (developer, Sonnet extended thinking)
**Assignee:** developer
**Goal:** Закрыть bridge `services.auth._state` в табах (services/pipeline/processes/plugins),
расширив AuthFacade Protocol методом runtime permission gating (`has_permission` уже есть — добавить
то, что табы реально используют для gating через `_state`).
**Context:** E.4/E.5/E.6 — табы используют `services.auth._state` для permission gating кнопок/секций.
AuthFacade Protocol покрывает `has_permission`/`current_user`, но gating лезет в `_state` (AuthState)
напрямую. Migration guide (AuthContext vs AuthFacade): возможно нужен `AdminAuthContext` Protocol.

**Files:**
- `multiprocess_prototype/domain/protocols/` (auth facade) — добавить gating-методы
- `multiprocess_prototype/adapters/auth/auth_facade.py` — реализовать
- `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py:166`
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:185`
- `multiprocess_prototype/frontend/widgets/tabs/processes/tab.py:215`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py:222`
- `multiprocess_prototype/domain/tests/_fakes.py` (FakeAuthFacade) + тесты табов

**Steps:**
1. Pre-investigation: `grep -n "auth._state\|auth\.state\|has_permission\|access_context" tabs/` —
   собрать конкретные паттерны gating (что именно проверяется: permission key? access level?).
2. Если все случаи сводятся к `has_permission(key)` — оно уже в Protocol → заменить `_state.access_context.has_permission`
   на `services.auth.has_permission(key)`. Если нужен access_level/role — добавить узкий метод.
3. Реализовать в adapter (делегирование AuthState.access_context). Заменить 4 bridge-site.

**Acceptance criteria:**
- [ ] `grep "auth._state\|auth\.state\." services/_sections.py pipeline/tab.py processes/tab.py plugins/_sections.py` → 0 (или обоснованный остаток)
- [ ] 4 TODO Phase F (permission gating) сняты
- [ ] `python -m pytest .../services/ .../pipeline/ .../processes/ .../plugins/ .../adapters/` зелёные
- [ ] Commit с Refs

**Out of scope:** полный AdminAuthContext (если не требуется — Phase G); audit storage.
**Edge cases:** Fake без `_state` (E.6) → no-op gate; сохранить это поведение в новом Protocol.
**Dependencies:** нет. Делит `domain/protocols/` — координировать волны.
**Module contract:** public-api-change

---

### Wave 4

---

### Task F.8 — Recipe YAML v2→v3: убрать live-формат source/display в display_bindings

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Goal:** Поднять формат рецептов до v3, убрав поддержку устаревшего live-формата `source`/`display`
в `display_bindings` (нормализованный `node_id`/`display_id`), мигрировать существующий YAML.
**Context:** Q2 Phase C + recipe.py TODO Phase F (стр. 16, 66) + test_entities_roundtrip.py:143.
`Recipe.from_dict()` сейчас принимает ОБА формата через `_normalize_display_binding()`. Только
`demo_webcam_split_merge.yaml:47-50` использует `source`/`display` для display_bindings.

**Files:**
- `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` — мигрировать display_bindings
  `source/display` → `node_id/display_id`, поднять `version: 2` → `version: 3`
- `multiprocess_prototype/domain/entities/recipe.py:59-79` — удалить `_normalize_display_binding`
  legacy-ветку (или оставить с hard deprecation, по решению); обновить docstring (стр. 8-19, 66)
- `multiprocess_prototype/domain/entities/recipe.py:45` — `version` default 2 → 3 (если уместно)
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py:137-166` — обновить тест
  (live-формат больше не нормализуется ИЛИ тест на отказ)
- `multiprocess_prototype/adapters/stores/recipe_store.py` — write пишет v3 формат

**Steps:**
1. **ВНИМАНИЕ:** `source`/`display` в display_bindings ≠ wire `source` в topology. Только
   display_bindings секция. Wire `source:` в region_pipeline.yaml и topology — НЕ трогать.
2. Мигрировать `demo_webcam_split_merge.yaml` display_bindings на `node_id`/`display_id`, version: 3.
3. Удалить legacy-ветку `_normalize_display_binding` (если владелец согласен на hard cut) ИЛИ
   заменить на `EntityValidationError` при встрече старого формата (forcing-функция).
4. Обновить тест roundtrip: убрать «live-формат нормализуется», добавить «v3 формат».
5. Проверить, что recipe загружается/применяется в Pipeline (recipe activation).

**Acceptance criteria:**
- [ ] `demo_webcam_split_merge.yaml` — `version: 3`, display_bindings в `node_id`/`display_id`
- [ ] `_normalize_display_binding` legacy-ветка удалена (или hard-fail)
- [ ] TODO Phase F в recipe.py (стр. 16, 66) и test_entities_roundtrip.py:143 сняты
- [ ] `python -m pytest multiprocess_prototype/domain/ multiprocess_prototype/adapters/` зелёные
- [ ] Recipe activation в Pipeline работает (smoke в F.10)
- [ ] Commit с Refs

**Out of scope:** RecipeStore rich API (F.4); wire source-формат в topology.
**Edge cases:** `to_dict()` уже пишет нормализованный формат — проверить идемпотентность roundtrip.
**Dependencies:** нет (независима).
**Module contract:** public-api-change (domain entity behaviour change)

---

### Wave 5

---

### Task F.9 — Убрать AppContext-зависимость из фабрик: ctx=None + create(ctx) bridge

**Level:** Senior+ (teamlead, Opus extended thinking)
**Assignee:** teamlead
**Goal:** Убрать legacy `ctx=None` параметр (prototype-side) из 6 табов и перевести
`register_all_tabs()`/`TabFactory` на передачу AppServices напрямую, формализовав runtime-deps
(по решению Q-F1).
**Context:** Все 6 табов передают `ctx=None` в `Base{List,Tree}NavTab` (framework generic-слот) и
имеют `create(ctx)` bridge, извлекающий `ctx.app_services` + runtime kwargs. Это последний legacy-мост
к AppContext. Direction #6 + #7. Зависит от Q-F1 (runtime-deps стратегия) и Q-F3 (framework ctx).

**Files:**
- `multiprocess_prototype/frontend/tab_factory.py` — `create_settings_tab`/`create_pipeline_tab`
  и `LazyTabWidget` lambda → передавать `ctx.app_services` (+ runtime deps по Q-F1)
- `multiprocess_prototype/frontend/widgets/tabs/__init__.py` `register_all_tabs()` — `Tab.create`
  принимает AppServices, не AppContext
- 6 табов: `{settings,recipes,processes,services,plugins,displays}/tab.py` — `create()` classmethod
  принимает то, что решено Q-F1 (AppServices + RuntimeDeps), убрать `ctx=None` хак
- `multiprocess_prototype/frontend/app.py:461` — `TabFactory(ctx, ...)` остаётся (TabFactory нужен ctx
  для permissions через `ctx.auth`), но фабрики табов получают services. Уточнить разделение.
- framework `Base{List,Tree}NavTab` — по Q-F3: вариант B (не трогать generic ctx) или A (framework change)
- тесты всех табов + `test_tab_factory.py` + `test_phase10/15_smoke.py`

**Steps:**
1. **БЛОКЕРЫ Q-F1 + Q-F3** — дождаться решений владельца.
2. Pre-investigation: `grep -rn "ctx=None\|create(ctx)\|def create" tabs/` + как TabFactory передаёт ctx.
3. По Q-F1 ввести (если вариант B) `RuntimeDeps` frozen dataclass; `create()` принимает
   `(services, runtime)` вместо `(ctx)`. TabFactory собирает RuntimeDeps один раз из ctx.
4. По Q-F3: если B — оставить framework `ctx: object` слот, прототип передаёт нейтральное значение
   (не «legacy ctx=None» — переименовать комментарии). Если A — отдельная framework-задача.
5. Убрать `# BaseListNavTab legacy параметр (Phase F удалит)` хаки.
6. Обновить тесты: builder + RuntimeDeps fake.

**Acceptance criteria:**
- [ ] `grep -rn "Phase F удалит\|ctx=None.*legacy" tabs/` → 0
- [ ] `register_all_tabs()` фабрики не зависят от AppContext (принимают AppServices [+ RuntimeDeps])
- [ ] Решение Q-F1 (runtime-deps) реализовано и задокументировано
- [ ] Решение Q-F3 (framework ctx) задокументировано (B — не трогаем / A — отдельная задача)
- [ ] `python -m pytest multiprocess_prototype/frontend/` зелёные (все табы + factory + smoke)
- [ ] `mcp__sentrux__check_rules` 9/9 pass
- [ ] Commit с Refs

**Out of scope:** удаление AppContext класса целиком (если TabFactory всё ещё нужен ctx.auth для
permissions — AppContext редуцируется, но не удаляется в Phase F; полное удаление — Phase G);
framework Base-class ctx removal (Q-F3 вариант A — отдельно).
**Edge cases:** TabFactory `_apply_permissions` использует `ctx.auth.state` — это остаётся (permissions
не часть AppServices). Не сломать permission-filtering.
**Dependencies:** F.3–F.6 (presenter'ы должны быть на Protocol до удаления ctx bridge), Q-F1, Q-F3.
**Module contract:** public-api-change (+ возможно framework public-api-change если Q-F3=A)

---

### Wave 6

---

### Task F.7 — DeprecationWarning → error в тестах (forcing-функция)

**Level:** Middle (developer, Sonnet normal)
**Assignee:** developer
**Goal:** Перевести `DeprecationWarning` из `_deprecated_extras` с `ignore` на `error::` в pytest
конфигурации, починить любой fallout, чтобы любое будущее обращение к deprecated extras падало тестом.
**Context:** Q5 Phase D — `pytest.ini filterwarnings` сейчас `ignore` для `_deprecated_extras`,
чтобы тесты Phase D/E не падали. После F.1–F.6 production-обращений к deprecated extras не остаётся
→ можно включить `error::` как forcing-функцию против регрессии (Out of scope migration guide стр. 262).

**Files:**
- `pytest.ini` (или `pyproject.toml [tool.pytest.ini_options]`) — `filterwarnings` для
  `_deprecated_extras` DeprecationWarning: `ignore` → `error`
- `multiprocess_prototype/frontend/_deprecated_extras.py` — опционально: убрать, если extras очищены
  (НЕ удалять класс, если AppContext/extras ещё живёт — оставить как safety net)
- тесты, которые легитимно проверяют сам shim (`test_extras_deprecation.py`) — должны явно
  ловить warning через `pytest.warns`, не падать от `error::`

**Steps:**
1. Pre-investigation: запустить `python -m pytest multiprocess_prototype/ -W error::DeprecationWarning 2>&1 | grep deprecated`
   — собрать полный список fallout ПОСЛЕ F.1–F.6.
2. Для каждого падения: если legitimate shim-тест → обернуть в `pytest.warns(DeprecationWarning)`.
   Если production-обращение осталось → это пропущенный call-site, исправить (вернуться к F.3–F.6).
3. Изменить filter на `error::` (узко — только для `_deprecated_extras` модуля, не глобально).
4. Прогнать полный suite.

**Acceptance criteria:**
- [ ] `pytest.ini` фильтрует `_deprecated_extras` DeprecationWarning как `error`
- [ ] `python -m pytest multiprocess_prototype/` зелёные (нет необёрнутых deprecated-обращений)
- [ ] `test_extras_deprecation.py` использует `pytest.warns`, проходит при `error::`
- [ ] Commit с Refs

**Out of scope:** удаление `_DeprecatedExtrasDict` класса (safety net, пока AppContext жив).
**Edge cases:** глобальный `-W error` сломал бы сторонние warnings — фильтр должен быть узким
(`error::DeprecationWarning:multiprocess_prototype.frontend._deprecated_extras` или по message).
**Dependencies:** F.1–F.6 завершены (иначе тесты падают от живых обращений).
**Module contract:** n/a (конфиг)

---

### Wave 7

---

### Task F.10 — Cumulative acceptance Phase F + ручной Qt-MCP smoke

**Level:** Senior (teamlead, Opus normal)
**Assignee:** teamlead
**Goal:** Проверить Success criteria Phase F (brief §7), замерить восстановление sentrux,
выполнить cumulative grep, провести ручной Qt-MCP smoke перед merge.
**Context:** Финал фазы. Brief §7 Success criteria. Sentrux ожидается восстановление к ~7161
(baseline) после удаления bridges. Qt-MCP smoke deferred (multiprocess GUI недостижим для MCP).

**Files:** только проверки, без правок кода (кроме фиксов найденных регрессий).

**Steps:**
1. `sentrux session_start` в начале F.1 (baseline дельты) → `session_end` здесь.
2. Cumulative grep:
   - `grep -rn 'extras\["topology"\]\|config.get("topology")' --include="*.py" | grep -v tests` → 0
   - `grep -rn "TODO Phase F" multiprocess_prototype/` → только «accepted by design» остатки (Q-F1/Q-F2)
   - `grep -rn "TopologyContext\|ServiceCatalogFromRegistry" multiprocess_prototype/` → 0
3. `python scripts/run_framework_tests.py` + `python -m pytest multiprocess_prototype/` — всё зелёное.
4. `mcp__sentrux__check_rules` 9/9, `mcp__sentrux__health` — score vs 7161 baseline.
5. **Ручной Qt-MCP smoke** (multiprocess: запустить `python -m multiprocess_prototype.run`, qt_snapshot
   по 7 табам, проверить: рендер без warnings, dispatch создаёт ноду, recipe activation работает).
6. Обновить master plan (Phase F → DONE), память проекта, adapters README (убрать «Phase F:» заметки).

**Acceptance criteria (= Success criteria brief §7):**
- [ ] Запрос «где топология читается» → одно место (TopologyRepository)
- [ ] `ctx.extras["topology"]` / `config["topology"]` fallback удалён
- [ ] 4 dataclass-обёртки удалены
- [ ] DeprecationWarning → error активен, тесты зелёные
- [ ] bridge-компромиссы #5a–#5d закрыты Protocol'ом (или accepted by design с обоснованием)
- [ ] Все тесты зелёные (framework + prototype + adapters + domain)
- [ ] Sentrux: дельта замерена и объяснена (удаление bridge убирает `getattr`, но F.3–F.6 добавляют Protocol-методы + adapter-делегирование → возможен рост complex functions, как в Phase C/D 44→71; цель — НЕ обязательно 7161, а понятная дельта без новых циклов/god-files)
- [ ] check_rules 9/9, acyclicity 10000
- [ ] Ручной Qt-MCP smoke 7 табов пройден (рендер + dispatch + recipe activation)
- [ ] Master plan Phase F → DONE, память обновлена
- [ ] Commit `docs(plans,memory): Phase F DONE` с Refs

**Out of scope:** ActionBus→commands (Phase F.A/G), Phase G UX-фишки.
**Edge cases:** Qt-MCP может не достучаться до GUI-процесса (multiprocess) — тогда ручная визуальная проверка.
**Dependencies:** F.1–F.9 завершены.
**Module contract:** n/a

---

## Риски и ограничения Phase F

| Риск | Уровень | Митигация |
|---|---|---|
| suppress_legacy_notify ломает Pipeline scene reload (typed events = Phase G) | **HIGH** | F.1 вариант B: селективный suppress (только topology_bridge IPC callback), Pipeline callback оставить до Phase G |
| Big-bang: смешать удаление + ActionBus-миграцию | **HIGH** | ActionBus→commands вынесен (Q-F4), Phase F = только удаление/Protocol |
| Удаление ctx до миграции presenter'а на Protocol → runtime break | **MEDIUM** | F.9 строго ПОСЛЕ F.3–F.6 (граф зависимостей) |
| Framework Base-class ctx removal = cross-layer breaking change | **MEDIUM** | Q-F3 вариант B (не трогать framework generic-слот); A — отдельная задача |
| Protocol over-engineering (plugin_class в spec) | **MEDIUM** | Q-F2: bridge accepted by design для sandbox, расширять только порты |
| commit race при >2 параллельных агентах | **MEDIUM** | макс 2 агента/волна, непересекающиеся файлы; `domain/protocols/__init__.py` — последовательно |
| error::DeprecationWarning ловит чужие warnings | **LOW** | F.7: узкий фильтр по модулю `_deprecated_extras`, не глобальный `-W error` |
| Qt-MCP недостижим (multiprocess) | **LOW** | ручная визуальная проверка перед merge (как E.1–E.6) |

---

## Out of scope Phase F (явный scope cut)

- **ActionBus → domain commands** (#9) — вынесено в Phase F.A / Phase G (Q-F4, рекомендация Manager).
- **Полное удаление TopologyHolder** — Phase G (typed events заменят `holder.on_changed`).
- **Полное удаление AppContext класса** — Phase G (TabFactory ещё использует `ctx.auth` для permissions).
- **`bindings` (GuiStateBindings) → AppServices** — Phase G (Q4 Phase D).
- **Live runtime snapshot (PID/FPS/метрики)** — Phase G (отдельный aggregate).
- **Framework Base{List,Tree}NavTab `ctx` removal** — отдельный framework-рефактор, если Q-F3=A.
- **Phase G UX-фишки** (auto-reveal, real-time validation, cross-tab linking, diff-view).
