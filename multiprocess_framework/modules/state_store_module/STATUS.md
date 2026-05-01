# state_store_module — Статус компонентов

**Статус:** STABLE (перенесён из прототипа в Фазе 2.1, 2026-04-30)

Модуль реактивного иерархического дерева состояния для многопроцессных приложений. Состояние управляется server-side в ProcessManager (StateStoreManager), клиенты работают через StateProxy с локальным кэшем и подписками. Подписки доставляют дельты адресно через IPC.

---

## Таблица компонентов

| Компонент | Статус | Тесты | Описание |
|-----------|--------|-------|----------|
| **core/** | | | |
| TreeStore | Готов | ~20 | Иерархическое дерево состояния (get, get_subtree, set, merge, delete) |
| Delta | Готов | ~15 | Единица изменения (path, old_value, new_value, source, timestamp) |
| Transaction | Готов | ~8 | Batch для атомарных изменений нескольких путей |
| SubscriptionManager | Готов | ~25 | Управление glob-подписками, поиск по паттерну |
| match_pattern, split_pattern | Готов | ~10 | Публичные алиасы хелперов для glob-паттернов (ADR-SS-004) |
| **manager/** | | | |
| StateStoreManager | Готов | ~40 | Server фасад (TreeStore + SubscriptionManager + DeltaDispatcher + IPC-handlers) |
| DeltaDispatcher | Готов | ~35 | Адресная рассылка дельт подписчикам через `targets` |
| **proxy/** | | | |
| StateProxy | Готов | ~50 | Client прокси (локальный кэш, подписки, синхронные get/set через IPC) |
| GuiStateProxy | Готов | ~15 | StateProxy с поддержкой PySide6 (ленивый импорт) |
| **middleware/** | | | |
| StateMiddleware (ABC) | Готов | ~5 | Базовый класс для middleware |
| MiddlewarePipeline | Готов | ~10 | Pipeline обработки дельт через middleware |
| ThrottleMiddleware | Готов | ~12 | Дебаунс дельт (группировка на delay) |
| ValidationMiddleware | Готов | ~8 | Валидация типов перед применением |
| LoggingMiddleware | Готов | ~6 | Логирование всех изменений |
| MetricsMiddleware | Готов | ~8 | Сбор метрик (количество операций, время ответа) |
| **selectors/** | | | |
| Selector | Готов | ~8 | Вычисляемое представление состояния |
| SelectorRegistry | Готов | ~10 | Регистр селекторов (кэширование результатов) |
| **devtools/** | | | |
| StateInspector | Готов | ~12 | Инспектор для отладки (inspect, subscriptions, history, stats) |
| **health/** | | | |
| HealthMonitor | Готов | ~15 | Watchdog по обновлениям путей в состоянии |
| WatchedProcess | Готов | ~5 | Описание контролируемого пути (паттерн, timeout, callback) |
| **persistence/** | | | |
| PersistenceManager | Готов | ~18 | Сохранение/загрузка состояния в YAML (debounce) |
| **recipes/** | | | |
| RecipeEngine | Готов | ~25 | Снимки (snapshot) и восстановление (restore) через Transaction |
| migration_fn, migration_check_fn | Готов | ~8 | Callback-и для доменных миграций (ADR-SS-003) |
| migrations/ | Готов | — | Место для generic миграций (README.md, пока пусто) |
| **testing/** | | | |
| InMemoryRouter | Готов | ~20 | Mock IRouter для unit-тестов (ADR-SS-010) |

**Итого:** ~415 unit-тестов + интеграционные в прототипе.

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
| **RecipeEngine миграции** | Callback-и migration_fn/migration_check_fn | Готов (ADR-SS-003) |
| **DeltaDispatcher роутинг** | targets = [subscriber], адресная доставка | Готов (ADR-SS-008) |
| **exclude_self логика** | Subscription.exclude_sources в DeltaDispatcher | Готов (ADR-SS-007) |
| **Avto-регистрация state.changed** | TODO Фаза 4 (ADR-SS-006) | ❌ Не реализовано (деталь в ProcessModule) |

---

## TODO и известные проблемы

### TODO Фаза 4 (ADR-SS-006)

**Авто-регистрация handler-а state.changed в ProcessModule**

Текущий подход: каждый рабочий процесс явно вызывает:
```python
router.register_message_handler("state.changed", proxy.on_state_changed)
```

В Фазе 4 (при рефакторинге ProcessModule): регистрация станет автоматической при инициализации ProcessModule, если proxy задан. Это упростит интеграцию в прикладных процессах.

Связано с: `process_module` (базовый класс фреймворка)

### TODO Фаза 4 (ADR-SS-002)

**Убрать default значение server_target**

Текущий default:
```python
server_target: str = "ProcessManager"
```

В Фазе 4: `server_target: str` (без default), обязательный параметр. Сейчас default оставлен для обратной совместимости.

Зафиксировано в: [DECISIONS.md](DECISIONS.md) (ADR-SS-002)

---

## Известные проблемы

Нет критических проблем. Все компоненты работают.

---

## История выпусков

| Дата | Событие | Статус |
|------|---------|--------|
| 2026-04-30 | Перенос из прототипа во фреймворк (Phase 2.1) | ✅ Стабилен |
| 2026-04-30 | Добавлены interfaces.py (IRouter, IStateStore, IStateProxy, IStateStoreManager) | ✅ Готов |
| 2026-04-30 | Экспорт InMemoryRouter в публичный API (ADR-SS-010) | ✅ Готов |
| 2026-04-30 | Документация README.md, STATUS.md, DECISIONS.md | ✅ Готова |

---

## Статистика модуля

- **Файлов Python:** ~30
- **Строк кода:** ~2500 (основной код)
- **Строк тестов:** ~3800
- **Зависимости:** только stdlib + опционально PySide6
- **Интеграция:** IRouter Protocol, TestInMemoryRouter встроен

