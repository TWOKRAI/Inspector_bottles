# Статус модулей — MODULES_STATUS.md

Сводка по 20 модулям фреймворка. Источник истины по одному модулю — `modules/{name}/STATUS.md`.
Прикладные сервисы (`Services/`) — см. [`Services/STATUS.md`](../Services/STATUS.md).

**Обновлено:** 2026-05-27 — добавлены `service_module` (Phase 3, ADR-129) и `display_module` (Phase 4, ADR-130); счётчик 22 пакета; тесты 2904 passed (verification-report Phase 8).
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

**Итого framework:** 22 пакета, ~74 294 LOC (с тестами).
**Прикладной слой (Services):** `sql` (~3 775 LOC), `hikvision_camera` — см. [`Services/STATUS.md`](../Services/STATUS.md).

**Тесты:** 2904 passed / 8 skipped / 0 failed (Phase 8 verification-report, 2026-05-27). Полный прогон:

```bash
python scripts/run_framework_tests.py
```

---

## Известные узкие места

См. [PROBLEMS.md](./PROBLEMS.md). Кратко:

1. `MemoryManager` — пропуск 15 тестов на macOS (`SharedMemory` платформенно нестабилен).
