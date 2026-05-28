# Plan: Cross-tab architecture refactor (master)

- **Slug:** cross-tab-architecture
- **Дата:** 2026-05-27
- **Статус:** Phase A/B/C/D/E DONE; Phase F PLANNED (детализирован); G — high-level
- **Ветка:** `refactor/cross-tab-architecture`
- **Brief (документ с фазами и target-архитектурой):** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) — 398 строк, разделы 4 (target) и 5 (фазы) — обязательны к прочтению.

## Назначение этого файла

Индекс / манифест плана. **Не дублирует brief.** Brief описывает «зачем, что и почему». Этот файл — карта «как идём», ссылки на детализированные phase-планы по мере их создания.

Конвенция (см. [`CLAUDE.md`](../../CLAUDE.md)): multi-phase план хранится в папке `plans/<date>_<slug>/`, внутри — `plan.md` (этот файл) + `phase-X.md` по одному на фазу. Каждый phase-файл детализируется отдельно, только когда подходит его очередь (избегаем premature planning).

## Источник фаз

Brief, раздел 5 — `## 5. Scope / план фаз`. Здесь дублируется только заголовок и статус каждой фазы. Детали (что делает, deliverables, ожидаемая длительность) — в brief'е и в соответствующих `phase-X.md`.

## Фазы

| Фаза | Название | Статус | Файл | Зависимости |
|------|----------|--------|------|-------------|
| **A** | Audit (read-only inventory) | DONE (2026-05-27, commit `bdfccd50`) | [`phase-a-audit.md`](phase-a-audit.md) | — |
| **B** | Domain skeleton (`multiprocess_prototype/domain/`) | **DONE** (2026-05-27, коммиты `83274ef8` → `e65f7158`, 233 теста, APPROVED) | [`phase-b-domain.md`](phase-b-domain.md) | A done |
| **C** | Adapters (9 классов + расширения) | **DONE** (2026-05-27, 9/9 Tasks, коммиты `1f1d28ff`…`2884b971`, 113 adapter + 240 domain тестов) | [`phase-c-adapters.md`](phase-c-adapters.md) | B done |
| **D** | `AppServices` DI + QtEventBus + ConfigStore + deprecation shim + Settings PoC | **DONE** (2026-05-27, 7/7 Tasks, коммиты `bfc71c10`, `12f57c44`, `7dfc27fd`, `79639cc3`, `931461a2`, `a876f73e`, `94983ed2` + D.6) | [`phase-d-app-services.md`](phase-d-app-services.md) | C done |
| **E** | Per-tab migration (Pipeline → Processes → Recipes → Services → Plugins → Displays) | **DONE** (2026-05-28, E.1–E.6 все DONE; коммиты E.1 `8566f994`+`e7bd3d97`, E.2 `be462f59`, E.3 `5f8c0a4e`, E.4 `27c72f64`, E.5 `62279a85`, E.6 `fc533dcb`) | [`phase-e-per-tab-migration.md`](phase-e-per-tab-migration.md) | D done |
| **F** | Удаление legacy + закрытие bridge-компромиссов (dead code, Protocol-расширения, ctx removal) | **APPROVED** (2026-05-28; после ревью Director'а: F.2a/F.2b/F.3–F.10; F.1 suppress + ActionBus→commands вынесены в Phase G) | [`phase-f-legacy-removal.md`](phase-f-legacy-removal.md) | E done |
| **G** | UX-фишки + suppress_legacy_notify (F.1) + ActionBus→domain commands (#9, undo/redo) | NOT PLANNED | — | F done |

**Правило:** phase-N+1 не детализируется до approval'а deliverable phase-N. Например, `phase-b-domain.md` пишется ТОЛЬКО после ревью отчёта Phase A.

## Текущая позиция

- Phase A — DONE. Deliverable: [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md), 380 строк. Коммит `bdfccd50`.
- recipe_manager double-contract — закрыт hotfix `85eec097` (presenter.py:730,803 + 2 теста).
- **Phase B — DONE (2026-05-27).** Все 6 Tasks выполнены последовательно (B.1 review iteration → B.2 → B.3 → B.5 → B.4 APPROVED → B.6). Deliverable: `multiprocess_prototype/domain/` — 7 frozen-entities, 14 events, 14 commands, 9 Protocols, EventBus + AppServices, builder + _fakes.py. 233 теста зелёных, 0 ruff errors, 0 запрещённых импортов. Коммиты: `83274ef8`, `d3c812de`, `f53b828c`, `c8ec137b`, `c6e697e9`, `24d1fc3f`, `e65f7158`.
- **Phase C — DONE (2026-05-27).** 9/9 Tasks выполнены. 10 adapter-классов, 113 adapter + 240 domain тестов, ruff 0, 0 запрещённых импортов. Q1-Q7 + 7 documented compromises. Коммиты: `1f1d28ff`…`2884b971`. Изначальные 7 Tasks расширены до **9** после investigator-ревью реальных call sites:
  - **C.0 DONE** (`1f1d28ff` + `210f21a1`): domain hot-fixes — Wire.description, Process.metadata, lazy register_domain_schemas. 240 tests.
  - **C.1 DONE** (`551ebdad`): 3 read-only catalog adapters (Plugin/Service/Display). 30 tests + 2 skipped.
  - **C.1.5 NEW** (Middle, developer): backport PluginSpec.description + PortSpec.optional/shape + DisplayRegistry.load(yaml) в app.py. Reason: investigator выявил, что без этих полей PluginCatalog покрывает только 14% call sites.
  - **C.1.6 NEW** (Senior, teamlead): ServiceCatalog → **ServiceManager** Protocol (+start/stop/restart/get_lifecycle). Reason: read-only ServiceCatalog покрывает 0% prod call sites — ServicesPresenter мутирует lifecycle.
  - **C.2** (Junior+): AuthFacade.
  - **C.3** (Middle+): TopologyRepository + suppress_legacy_notify cm (доступен, но НЕ используется по умолчанию).
  - **C.4** (Middle+): RegistersBackend (variant A — knows Topology+PluginCatalog).
  - **C.5** (Senior): RecipeStore (variant A — denormalize meta→top-level).
  - **C.6** (Senior): CommandDispatcher без suppress_legacy_notify (double notification до Phase F — осознанный компромисс).
  - **C.7** (Middle): adapters/__init__.py + README + integration smoke.
- **Phase D — DONE (2026-05-27, 7/7 Tasks).** AppServices factory + QtEventBus + ConfigStore Protocol + ProjectHolder + deprecation shim + Settings PoC + migration guide + sentrux baseline. Qt-MCP smoke прошёл: MainWindow + SettingsTab рендерятся, 25 widgets, no Qt warnings. ~1981 тест passed, 3 skipped (macOS SHM — known). Коммиты: D.2 `bfc71c10`, D.3 `12f57c44`, D.2b `7dfc27fd`, D.4 `79639cc3`, D.1 `931461a2`, D.5 `a876f73e` + `94983ed2`, D.6 текущий коммит. **Pipeline = первый Phase E** (главный consumer, валидирует архитектуру end-to-end).
- **Phase E — DONE (2026-05-28, E.1–E.6 все DONE).** Все 6 табов мигрированы на AppServices DI: E.1 Pipeline (`8566f994`+`e7bd3d97`, Senior+, APPROVED), E.2 Processes (`be462f59`, Middle), E.3 Recipes (`5f8c0a4e`, Middle), E.4 Services (`27c72f64`, Middle, Protocol вместо bridge), E.5 Plugins (`62279a85`, Middle+, bridge by design), E.6 Displays (`fc533dcb`, bridge by design). Cumulative: grep `ctx.extras[` по табам = 0 в production; 0 `_deprecated_extras` DeprecationWarning; sentrux **7136** (−25 vs baseline 7161, монотонный −1/таб от bridges, acyclicity 10000, check_rules 9/9). Qt-MCP smoke deferred к ручной проверке перед merge (multiprocess GUI в дочернем процессе). 34 TODO Phase F помечены в коде (26 файлов). Урок E.4/E.5: bridge vs Protocol зависит от полноты Protocol — НЕ каждый bridge надо закрывать; runtime-объекты (plugin_manager, command_sender, topology_bridge, router_manager) остаются explicit kwargs by design.
- **Phase F — PLANNED (2026-05-28).** Детализирован subplan: [`phase-f-legacy-removal.md`](phase-f-legacy-removal.md). 10 задач F.1–F.10 в 7 волнах (макс 2 параллельных агента). Порядок безопасности: F.1 suppress_legacy_notify (снять HIGH-риск double-notify) ПЕРВОЙ → F.2 dead code → F.3–F.6 Protocol-расширения → F.9 ctx removal (ПОСЛЕ Protocol) → F.7 DeprecationWarning→error → F.10 cumulative + ручной Qt-MCP smoke. ActionBus→domain commands (#9) ВЫНЕСЕН из Phase F в Phase F.A/G (Q-F4, рекомендация Manager: слишком крупно, big-bang риск). TopologyHolder НЕ удаляется в Phase F — typed events заменят `holder.on_changed` в Phase G (3 prod-подписчика). 4 открытых вопроса требуют решения владельца: Q-F1 (runtime-deps стратегия), Q-F2 (plugin_class spec), Q-F3 (framework ctx), Q-F4 (ActionBus вынос).
- Архитектурный обзор Phase B (investigator-ревью 2026-05-27): 3 главных риска — двойная нотификация TopologyHolder+EventBus (HIGH), SchemaRegistry name collision (MEDIUM), RecipeStore adapter complexity (MEDIUM). Все учтены в Phase C/D планах.

## Известные ограничения и риски (вне Phase A)

Этот раздел растёт по ходу выполнения, фиксируя то, что нашлось в audit'е и требует внимания позже.

- ~~**Recipe_manager double contract**~~ — закрыт hotfix'ом до старта Phase B: presenter.py:730,803 переведён на property-доступ, тесты приведены к атрибутному моку (48/48 pipeline-рецепт тестов зелёные). Кейс остаётся примером того, что Phase D обязана исправить тестовой стратегией (strict `MagicMock(spec=AppContext)` или builder), иначе подобный рассинхрон контракта легко вернётся.
- **DisplayRegistry — 8-й реестр**, не в `extras`. Доступ через `getattr` всегда возвращает `None` в production (Inventory 3). Phase D должна это исправить.
- **4 параллельные dataclass-обёртки** (`TopologyContext`, `StateContext`, `PluginsContext`, `ActionsContext`) — созданы, не подключены. Phase D решит: либо подключить, либо удалить.
- **Pipeline tab — крупнейший consumer** (21 из 40 топологических чтений). Phase E начинает с него.
- **53 ad-hoc MagicMock в 39 тест-файлах** — 0 strict-моков `MagicMock(spec=AppContext)`. Phase D потребует тестовой стратегии — builder вместо MagicMock.
- **Audit делался на ветке `refactor/cross-tab-architecture`** (без cross-tab create feature). Файлы `feat/cross-tab-process-create` — отдельные consumers тех же anti-patterns; при мерже feature-ветки потребуется delta-audit для новых файлов.

## Ссылки

- [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) — brief / problem statement / target.
- [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md) — Phase A deliverable.
- [`phase-f-legacy-removal.md`](phase-f-legacy-removal.md) — Phase F детальный план (F.1–F.10, волны, открытые вопросы).
- [`docs/refactors/2026-05_phase_e_migration_guide.md`](../../docs/refactors/2026-05_phase_e_migration_guide.md) — паттерн миграции (база для Phase F).
- [`CLAUDE.md`](../../CLAUDE.md) — правила проекта, plan conventions.
- [`.claude/modes/dev.md`](../../.claude/modes/dev.md) — режим работы Dev-команды.
