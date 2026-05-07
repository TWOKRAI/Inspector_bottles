# state_store_module — Статус компонентов

**Статус:** STABLE (перенесён из прототипа в Фазе 2.1, 2026-04-30; рефакторинг 2026-05-07)

Модуль реактивного иерархического дерева состояния для многопроцессных приложений. Состояние управляется server-side в ProcessManager (StateStoreManager), клиенты работают через StateProxy с локальным кэшем и подписками. Подписки доставляют дельты адресно через IPC.

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| **core/** | | | |
| TreeStore | core/tree_store.py | Готов | Иерархическое дерево (`get`, `get_subtree`, `set`, `merge`, `delete`, `transaction`, `snapshot`, `restore`) |
| Delta | core/delta.py | Готов | Иммутабельная единица изменения (path, old/new, source, timestamp, transaction_id) |
| Transaction | core/delta.py | Готов | Batch с единым transaction_id + `coalesce()` для сжатия |
| MISSING | core/delta.py | Готов | Singleton-sentinel для «значения нет» |
| SubscriptionManager | core/subscription_manager.py | Готов | Подписки с glob-style matching + lru_cache на разборе паттернов |
| match_pattern, split_pattern | core/subscription_manager.py (re-export через core/__init__) | Готов | Публичные хелперы glob-матчинга (ADR-SS-004) |
| **manager/** | | | |
| StateStoreManager | manager/state_store_manager.py | Готов | Server-фасад: TreeStore + SubscriptionManager + DeltaDispatcher + 7 IPC-handlers |
| DeltaDispatcher | manager/delta_dispatcher.py | Готов | Адресная рассылка дельт подписчикам через `targets`, дедупликация по subscriber |
| **proxy/** | | | |
| StateProxy | proxy/state_proxy.py | Готов | Client-прокси: локальный кэш + IPC + per-pattern фильтрация callbacks (ADR-SS-012) |
| GuiStateProxy | proxy/gui_state_proxy.py | Готов | Qt-safe: callbacks через `QMetaObject.invokeMethod(QueuedConnection)`, ленивый PySide6 |
| **middleware/** | | | |
| StateMiddleware (ABC) | middleware/base.py | Готов | Базовый класс middleware |
| MiddlewarePipeline | middleware/base.py | Готов | Цепочка middleware (нулевой overhead на пустом pipeline) |
| ThrottleMiddleware | middleware/throttle.py | Готов | Дебаунс/блокировка по паттернам путей |
| ValidationMiddleware | middleware/validation.py | Готов | Валидация type / min / max / enum |
| LoggingMiddleware | middleware/logging_mw.py | Готов | Логирование изменений + exclude_patterns |
| MetricsMiddleware | middleware/metrics.py | Готов | Счётчики операций, источники, last_operation_time |
| **selectors/** | | | |
| Selector | selectors/selector.py | Готов | Вычисляемое значение с зависимостями (паттерны) |
| SelectorRegistry | selectors/selector.py | Готов | Регистр selectors + автопересчёт через `handle_delta` |
| **devtools/** | | | |
| StateInspector | devtools/inspector.py | Готов | inspect / subscriptions / history (ring buffer) / stats / summary |
| **health/** | | | |
| HealthMonitor | health/monitor.py | Готов | Pull-based watchdog: register / record_activity / check |
| WatchedProcess | health/monitor.py | Готов | Внутреннее состояние одного процесса |
| **persistence/** | | | |
| PersistenceManager | persistence/persistence_manager.py | Готов | Debounced YAML save **с конфигурируемым file_mapping и предикатами (ADR-SS-011)** |
| PersistenceMiddleware | persistence/persistence_manager.py | Готов | Middleware-хук, помечает dirty по after_set / after_merge |
| **recipes/** | | | |
| RecipeEngine | recipes/recipe_engine.py | Готов | save / load / list / delete / diff / is_dirty + миграции через callbacks (ADR-SS-003) |
| migrations/ | recipes/migrations/ | Готов (заглушка) | Место для generic-миграций — пока пусто, README описывает контракт |
| **testing/** | | | |
| InMemoryRouter | testing/in_memory_router.py | Готов | Mock IRouter для unit-тестов прикладного кода (ADR-SS-010) |

**Тестов:** **421 unit-тест в `tests/`** (после рефакторинга 2026-05-07: было 415, добавлено 4 теста на per-pattern фильтрацию + 2 на конфигурируемый PersistenceManager).

---

## Статус интеграции

| Компонент | Интеграция | Статус |
|-----------|------------|--------|
| **interfaces.py** | IRouter (Protocol) | Готов (ADR-SS-001) |
| | IStateStore (ABC) | Готов (ADR-SS-009) |
| | IStateProxy (ABC) | Готов (ADR-SS-009) |
| | IStateStoreManager (ABC) | Готов (ADR-SS-009) |
| **server_target в StateProxy** | Параметр конструктора | Готов (ADR-SS-002), default="ProcessManager" |
| **Публичные хелперы** | match_pattern, split_pattern из core/ | Готов (ADR-SS-004) |
| **GuiStateProxy без top-level import** | Ленивый импорт PySide6 | Готов (ADR-SS-005) |
| **RecipeEngine миграции** | Callback-и migration_fn / migration_check_fn | Готов (ADR-SS-003) |
| **PersistenceManager — file_mapping и предикаты** | Параметры конструктора | Готов (ADR-SS-011) |
| **DeltaDispatcher** | targets = [subscriber], адресная доставка | Готов (ADR-SS-008) |
| **exclude_self логика** | Subscription.exclude_sources в DeltaDispatcher | Готов (ADR-SS-007) |
| **Per-pattern фильтрация callbacks** | StateProxy._sub_patterns + _filter_deltas_by_pattern | Готов (ADR-SS-012) |
| **Авто-регистрация state.changed** | TODO Фаза 4 (ADR-SS-006) | ❌ Не реализовано (изменение в ProcessModule) |

---

## TODO

### TODO Фаза 4 (ADR-SS-006)

**Авто-регистрация handler-а `state.changed` в ProcessModule.** Сейчас каждый процесс явно вызывает:

```python
router.register_message_handler("state.changed", proxy.on_state_changed)
```

В Фазе 4 (рефакторинг ProcessModule): регистрация станет автоматической, если proxy задан в конструкторе ProcessModule. Связано с базовым классом фреймворка, поэтому откладывается за пределы этого модуля.

### TODO Фаза 4 (ADR-SS-002)

**Убрать default `server_target="ProcessManager"`** — параметр станет обязательным, чтобы прикладной код не зависел от имени, заданного по умолчанию.

---

## Известные ограничения

- **`StateInspector.inspect(path)`** не поддерживает glob-паттерны — для них есть `TreeStore.snapshot([patterns])`.
- **`TreeStore.merge`** при глубоких структурах работает за O(N²) (каждый лист проходит навигацию от корня). Для типичных конфигов (десятки ключей) — pernebrejmo. Кандидат на оптимизацию (Этап 2 рефакторинга).
- **Glob-walker** для дерева повторён в трёх местах (`tree_store._collect_matching`, `selector._walk`, `subscription_manager._match_pattern`). Можно унифицировать в `core/glob_walker.py`. Кандидат на Этап 2.
- **`StateStoreManager.shutdown` и `StateInspector.subscriptions`** обращаются к приватным атрибутам `SubscriptionManager._lock` / `_subscriptions`. Кандидат на введение публичного `SubscriptionManager.subscribers()` (Этап 2).

---

## История выпусков

| Дата | Событие | Статус |
|------|---------|--------|
| 2026-04-30 | Перенос из прототипа во фреймворк (Phase 2.1) | ✅ Стабилен |
| 2026-04-30 | `interfaces.py`: IRouter + IStateStore + IStateProxy + IStateStoreManager | ✅ Готово |
| 2026-04-30 | `InMemoryRouter` экспортирован в публичный API (ADR-SS-010) | ✅ Готово |
| 2026-04-30 | Документация: README.md + STATUS.md + DECISIONS.md | ✅ Готова |
| **2026-05-07** | **ADR-SS-011: PersistenceManager — доменно-нейтральный (file_mapping, предикаты)** | **✅ Готово** |
| **2026-05-07** | **ADR-SS-012: StateProxy — per-pattern фильтрация callbacks** | **✅ Готово** |
| **2026-05-07** | **README.md / STATUS.md приведены в соответствие с реальным API** | **✅ Готово** |

---

## Статистика модуля

- **Файлов Python (без тестов):** ~22
- **Строк кода (без тестов):** ~3300
- **Файлов тестов:** 16
- **Строк тестов:** ~4500
- **Тестов:** 421 (все зелёные, ~3.8 с)
- **Зависимости:** stdlib, `pyyaml`, `multiprocess_framework.modules.base_manager`, опционально `PySide6` (lazy)
- **Внутренние ADR:** 12
