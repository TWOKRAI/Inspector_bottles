# base_manager — Статус рефакторинга

## Текущий этап: 6 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 8 | Чистый, без дублирования. Методы класса вместо `types.MethodType`-замыканий. |
| Тесты | 8 | 69 тестов, 100 % pass. Pickle, плагины, интеграция покрыты. |
| Документация | 8 | README полный: API-таблицы, примеры, pickle, checklist, архрешения. |
| Связанность | 8 | `BaseManager` → `IBaseManager`; `ObservableMixin` → `IObservableMixin`. Единый контракт. |
| Работоспособность | 9 | Pickle-корректен на Windows spawn. Все 12 downstream-модулей совместимы. |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены
  - [x] `_call_manager_func` перезаписывался 3 раза → убран, заменён на прямой `_call_manager`
  - [x] Pickle-несовместимые замыкания (`types.MethodType` с локальными функциями) → заменены методами класса
  - [x] `__setstate__` не восстанавливал `_registry` → исправлено
  - [x] `BaseManager.__getattr__` возвращал `_noop` для всех proxy-имён → убран ложный fallback
- [x] Этап 1: Интерфейсы
  - [x] `IBaseManager` расширен (все публичные методы)
  - [x] `IObservableMixin` объединён в единый файл `interfaces.py` (убрано дублирование с `mixins/interfaces.py`)
  - [x] `BaseManager` наследует `IBaseManager`
  - [x] `ObservableMixin` наследует `IObservableMixin`
  - [x] `isinstance(manager, IBaseManager)` → True для всех 12 потомков ✓
- [x] Этап 2: Код
  - [x] `_noop` убран из публичного API (`__init__.py`)
  - [x] `LoggingMethods`, `StatsMethods`, `ErrorMethods` упрощены (no-op, методы на классе)
  - [x] `LoggerPlugin.create_proxy_methods` теперь создаёт методы только при наличии 'logger' (согласованность с `StatsPlugin`, `ErrorPlugin`)
  - [x] Приоритет stats: `'stats'` → `'statistics'` согласован в `_record_metric` и `StatsPlugin`
- [x] Этап 3: Тесты
  - [x] `test_base_manager.py` — полное покрытие (24 теста)
  - [x] `test_observable_mixin.py` — полное покрытие (25 тестов, pickle)
  - [x] `test_mixin_integration.py` — интеграция нескольких менеджеров (8 тестов)
  - [x] `test_plugin_system.py` — плагины встроенные и кастомные (12 тестов)
  - [x] Удалён `test_refactored_mixin.py` (содержал `sys.path.insert`, нарушение правил)
  - [x] Итого: 69 тестов, 69 passed, 0 failed
- [x] Этап 4: Документация
  - [x] README полностью переписан по эталону `router_module`
  - [x] Архитектурные решения задокументированы
  - [x] Checklist интеграции нового менеджера
- [ ] Этап 5: Декораторы
  - [ ] `ObservableDecorators.logged/timed/monitored` — проверить pickle-совместимость (сейчас создаются как замыкания, не pickle-совместимы, отключены по умолчанию)
- [ ] Этап 6: `types/` subpackage — определить и реализовать типы данных (сейчас пустой)
- [ ] Этап 7: Интеграционные тесты с реальными downstream-модулями
- [ ] Этап 8: Performance-профилирование (MethodCache hit rate)

## Известные проблемы

- `ObservableDecorators` (`logged`, `timed`, `monitored`) используют замыкания — НЕ pickle-совместимы. Отключены по умолчанию (`enable_decorators=False`). Если декораторы нужны в multiprocessing — требуется рефакторинг аналогичный тому, что был сделан для `_log_*`.

- `types/__init__.py` пустой — планируется для типовых алиасов (`ManagerConfig`, `AdapterName` и т.д.).

- После pickle/unpickle owners (ProcessModule, WorkerManager и т.д.) должны вручную вызвать `register_manager()` для восстановления логгера и stats. Это корректно (managers держат ресурсы), но требует документирования в каждом downstream-модуле.
