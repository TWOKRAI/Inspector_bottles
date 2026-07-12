# Статус модулей — MODULES_STATUS.md

Сводка по 25 модулям фреймворка. Источник истины по одному модулю — `modules/{name}/STATUS.md`.
Прикладные сервисы (`Services/`) — см. [`Services/STATUS.md`](../Services/STATUS.md).
Карта ответственности и границы (где что, чтобы не дублировать) — [`docs/MODULES_RESPONSIBILITY_MAP.md`](docs/MODULES_RESPONSIBILITY_MAP.md).

**Обновлено:** 2026-07-12 — C8 docs-sync: `recipe` дозаписан по факту C2/C3 (реестр step-миграций + generic `yaml_io`-writer, ADR-RCP-003/005; ~1400 LOC, 98 тестов).
**Ранее** 2026-07-11 — добавлен `recipe` (крыша над рецептами: RecipeEngine + RecipeManager + detect + format консолидированы; C1, ADR-RCP-001/002); счётчик 24 → **25**.
**Ранее** 2026-07-08 — сверка с фактом: в таблицу добавлены `actions_module` (carve-out из frontend, ADR-124) и `event_module` (carve-out из prototype, in-proc pub/sub); счётчик 20/22 → **24**; удалён cruft-каталог `modules/sql_module/` (пустой, только `.pyc` после Phase 4.1).
**Ранее** 2026-05-27 — добавлены `service_module` (Phase 3, ADR-129) и `display_module` (Phase 4, ADR-130); тесты 2904 passed (verification-report Phase 8).
Ранее 2026-05-10 — `sql_module` выехал в [`Services/sql/`](../Services/sql/) (Phase 4.1, ADR-121). `hikvision_camera` — в [`Services/hikvision_camera/`](../Services/hikvision_camera/) (Phase 4.2, ADR-122).
Ранее 2026-05-07 — `state_store_module` допилен (ADR-SS-011..013: доменно-нейтральный PersistenceManager, per-pattern фильтрация callbacks, публичные snapshot-методы SubscriptionManager); `chain_module` допилен (ADR-CHN-006/007: явный `IRemoteExecutable`, общая on_error политика, ObservableMixin для WorkerPoolDispatcher и LatencyTracker; коды ADR-CM-* переименованы в ADR-CHN-*).

| Модуль | Готовность | LOC | Тестов | Комментарий |
|--------|-----------|-----|-------:|-------------|
| `base_manager` | production | 2 188 | + | Основа: BaseManager, ObservableMixin, BaseAdapter |
| `data_schema_module` | production | 16 168 | + | Самый большой; SchemaBase, FieldMeta, FieldRouting |
| `message_module` | production | 2 616 | + | Message + MessageAdapter; Dict at Boundary |
| `dispatch_module` | production | 3 447 | + | 4 стратегии, ScenarioBuilder |
| `channel_routing_module` | production | 2 093 | + | CRM — база Logger/Error/Router/Stats |
| `logger_module` | production | 1 705 | + | Scope-based routing, BatchBuffer |
| `error_module` | production | 1 026 | + | Severity routing, наследник Logger |
| `config_module` | production | 2 393 | + | Тонкая обёртка над data_schema |
| `state_store_module` | stable | 3 300 | 421 | Реактивное дерево состояния; StateStoreManager, StateProxy, TreeStore, доменно-нейтральный PersistenceManager |
| `recipe` | stable | ~1 400 | 98 | Крыша над рецептами: RecipeEngine (snapshot/restore), RecipeManager (CRUD+state-sync, `yaml_io` writer по умолчанию), is_v3_recipe, normalize_recipe_v3_raw, реестр step-миграций `@migration`/`run_chain`; доменные пути и сами шаги-миграции инжектируются, assembler/planner НЕ в модуле (ADR-RCP-001…005) |
| `service_module` | stable | ~500 | 91 | ServiceRegistry singleton + lifecycle + scanner; ADR-129, ADR-SVC-001/002/003 |
| `display_module` | stable | ~300 | 12 | DisplayRegistry singleton + YAML persist; ADR-130, ADR-DM-001/002/003 |
| `console_module` | production | 2 877 | + | Три уровня: passive/active/God mode |
| `shared_resources_module` | production | 5 233 | + | PSR, ConfigStore, MemoryManager, Handle API |
| `router_module` | production | 3 225 | + | AsyncSender + AsyncReceiver, CRM-наследник |
| `command_module` | production | 1 220 | + | Тонкий фасад над dispatch |
| `worker_module` | production | 2 356 | + | LOOP/TASK режимы, lifecycle потоков |
| `chain_module` | stable | 1 610 | 67 | DAG/Chain execution engine; ChainRunnable, DagRunnable, ParallelChainRunnable, WorkerPoolDispatcher, LatencyTracker (все три долгоживущих сервиса — `BaseManager + ObservableMixin`) |
| `process_module` | production | 3 965 | + | ProcessModule — база дочернего процесса |
| `process_manager_module` | production | 4 612 | + | SystemLauncher, ProcessRegistry, Monitor |
| `registers_module` | production | 1 169 | + | Runtime вокруг экземпляров регистров |
| `statistics_module` | production | 1 500 | + | StatsManager, AggregationWindow |
| `frontend_module` | production | 12 039 | + | PySide6-виджеты с привязкой к регистрам |
| `actions_module` | stable | ~700 | + | Building-blocks undo/redo (ActionBus PATCH + SnapshotHistory SNAPSHOT); carve-out из frontend (ADR-124). Прод-undo сейчас через domain `CommandDispatcherOrchestrator`; модуль сохраняется (решение владельца 2026-07-08, ADR-COMM-002 не исполняется) |
| `event_module` | stable | ~150 | + | Generic typed in-proc pub/sub (EventBus по `type(event)`); carve-out из prototype. In-proc факты — не путать с cross-proc `EventManager` (SRM) |

**Итого framework:** 25 пакетов, ~75 850 LOC (с тестами).
**Прикладной слой (Services):** `sql` (~3 775 LOC), `hikvision_camera` — см. [`Services/STATUS.md`](../Services/STATUS.md).

**Тесты:** 2904 passed / 8 skipped / 0 failed (Phase 8 verification-report, 2026-05-27). Полный прогон:

```bash
python scripts/run_framework_tests.py
```

---

## Известные узкие места

См. [PROBLEMS.md](./PROBLEMS.md). Кратко:

1. `MemoryManager` — пропуск 15 тестов на macOS (`SharedMemory` платформенно нестабилен).
