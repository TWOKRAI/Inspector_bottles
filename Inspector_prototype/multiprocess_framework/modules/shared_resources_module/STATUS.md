# shared_resources_module — Статус рефакторинга

## Текущий этап: 8 / 8 ✅

## Оценки (0-10)

| Критерий | До | После | Комментарий |
|----------|-----|-------|-------------|
| Код (читаемость, стандарты) | 6 | **9** | Чёткое разделение ответственностей, типизация, DRY |
| Тесты (покрытие) | 3 | **8** | 50+ тестов: types, config, PSR, SRM, QR, EM, MM |
| Документация (README, interfaces) | 4 | **9** | README, ARCHITECTURE.md, ADR-017..021, interfaces.py |
| Связанность (меньше = лучше) | 4 | **8** | Фасад-делегатор, нет god object, чёткие границы |
| Дублирование | 7 | **9** | _safe_close_shm DRY, PSR source of truth |
| Работоспособность | 7 | **9** | Pickle-safe, reinitialize_in_child, register_process |

## Чеклист рефакторинга

- [x] Этап 1: types/ — ProcessStatus, ResourceType, EventType, TypedDict
- [x] Этап 2: core/interfaces.py — ISharedResourcesManager, IConfigStore, IQueueRegistry, IEventManager, IMemoryManager, IProcessStateRegistry
- [x] Этап 3: ConfigStore + ProcessData (ProcessStatus enum) + PSR (logger вместо print)
- [x] Этап 4: SharedResourcesManager — register_process(), reinitialize_in_child(), properties
- [x] Этап 5: EventManager (reinitialize), QueueRegistry (PSR source of truth), MemoryManager (shm names)
- [x] Этап 6: adapters/data_schema_adapter.py, registry/ → обратная совместимость
- [x] Этап 7: 50+ тестов (types, config_store, process_data, PSR, SRM, QR, EM, MM)
- [x] Этап 8: README.md, STATUS.md 8/8, ARCHITECTURE.md, __init__.py, DECISIONS.md

## Ключевые изменения

### Архитектурные (ADR-017..021)
- **ADR-017**: ConfigStore отдельно от ProcessData (статика vs динамика)
- **ADR-018**: `register_process()` — единая точка регистрации
- **ADR-019**: SharedMemory по именам (pickle-safe)
- **ADR-020**: `reinitialize_in_child()` для восстановления после unpickle
- **ADR-021**: Прямой pickle SRM вместо ad-hoc bundle dict

### Технические
- `ProcessStatus` enum вместо строковых констант
- `print()` → `logging.Logger` в ProcessStateRegistry
- PSR — единственный source of truth для Queue/Event ссылок
- `_safe_close_shm()` — DRY для close/unlink SharedMemory
- `typing_extensions.TypedDict` для Dict at Boundary контрактов

## Обновление 2026-03-30 (ADR-102)

- **`IProcessStateRegistry.register_process`**: удалён неиспользуемый параметр `config`; полезная нагрузка — в `initial_state.custom`.
- **`register_process_state`**: больше не принимает `config`; аргумент `queue_names` по-прежнему игнорируется (совместимость вызова).
- Документация: [../../docs/CONFIG_PATHS.md](../../docs/CONFIG_PATHS.md).

## Известные ограничения

- **configs/:** `SharedResourcesManagerConfig` (SchemaBase); **config_store/** — рантайм-хранилище (`ConfigStore`), не путать со схемами
- MemoryManager.reinitialize_handles() открывает shm по именам — требует чтобы owner process ещё не сделал unlink
- QueueRegistry.registered_queues — локальный кэш (дублирует PSR для broadcast); в следующей итерации можно убрать

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-13 | Полный рефакторинг по плану shared_resources_refactoring_7edae960 | 8 |
| 2026-03-15 | clear_queue(): учёт асинхронности multiprocessing.Queue на macOS (повторный проход drain) | 8 |
| 2026-03-15 | ADR-026: _create_shm_blocks stale cleanup, print fallback в write_images/_validate_memory_access | 8 |
| 2026-03-15 | memory: рефакторинг на подмодули (format, platform_ops, validation, types), README, STATUS, тесты | 8 |
| 2026-03-15 | events, queues: рефакторинг по примеру memory (core/, interfaces, ManagerStatsMixin, README, STATUS) | 8 |
| 2026-03-15 | Проверочный рефакторинг: документация data_schema_module, ARCHITECTURE, INTERFACES_GUIDE, DataSchemaAdapter | 8 |
| 2026-03-15 | Интерфейсы раскиданы по подмодулям: config/, state/, queues/, events/, memory/interfaces.py; core — ISharedResourcesManager + re-export | 8 |

## Проверочный рефакторинг (2026-03-15)

- **Документация**: ARCHITECTURE.md — актуальная файловая структура, раздел «Связь с data_schema_module»
- **README.md**: секция о разделении ответственностей с data_schema_module
- **DataSchemaAdapter**: уточнён docstring — делегирует в data_schema_module, без дублирования логики
- **INTERFACES_GUIDE.md**: исправлены пути (memory/core/manager.py, state/process_state_registry.py)
