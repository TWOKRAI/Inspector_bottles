# Статус модулей — MODULES_STATUS.md

Сводка по 21 модулю фреймворка. Источник истины по одному модулю — `modules/{name}/STATUS.md`.

**Обновлено:** 2026-05-07 — `state_store_module` допилен (ADR-SS-011..013: доменно-нейтральный PersistenceManager, per-pattern фильтрация callbacks, публичные snapshot-методы SubscriptionManager); `chain_module` допилен (ADR-CHN-006/007: явный `IRemoteExecutable`, общая on_error политика, ObservableMixin для WorkerPoolDispatcher и LatencyTracker; коды ADR-CM-* переименованы в ADR-CHN-*).

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
| `sql_module` | production | 3 775 | + | SQLManager, Repository, UoW, QuerySet |
| `frontend_module` | production | 12 039 | + | PySide6-виджеты с привязкой к регистрам |

**Итого:** 21 пакет, ~77 269 LOC (с тестами), 670+ файлов `.py`.

**Тесты:** 2 465 passed / 29 skipped / 0 failed (см. PROBLEMS.md). Полный прогон:

```bash
python scripts/run_framework_tests.py
```

---

## Известные узкие места

См. [PROBLEMS.md](./PROBLEMS.md). Кратко:

1. `MemoryManager` — пропуск 15 тестов на macOS (`SharedMemory` платформенно нестабилен).
