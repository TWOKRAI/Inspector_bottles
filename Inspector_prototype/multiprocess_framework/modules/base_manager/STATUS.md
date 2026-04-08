# base_manager — STATUS

**Статус:** ✅ Стабильный

**Последнее обновление:** 2026-04-08 (документация, Шаг 5)

**Рефакторинг:** ✅ Завершён (Шаги 4.0–4.6)  
**Документация:** ✅ Завершена (Шаг 5)

## Краткое описание

Фундамент для всех менеджеров фреймворка. Предоставляет:
- **`BaseManager`** — жизненный цикл и управление адаптерами.
- **`ObservableMixin`** — наблюдаемость (логирование, метрики, ошибки) через единый интерфейс.
- **`BaseAdapter`** — базовый класс адаптеров.

## Публичный API

```python
from base_manager import BaseManager, ObservableMixin, BaseAdapter, BaseManagerConfig
from base_manager.interfaces import IBaseManager, IBaseAdapter, IObservableMixin
```

## Метрики рефакторинга (Шаг 4)

- **Файлов:** 17 (было 29, −12)
- **LOC:** 1474 (было 2425, −39%)
- **Тесты:** 52 passed, 2 skipped (было 69, −10 удалённых plugin/events-тестов, −5 __getattr__-тестов)
- **Удалено:** PluginRegistry, ObservableDecorators, MethodCache, simple_mode, on_event/emit_event, __getattr__ magic, no-op method stubs.

## Документация (Шаг 5)

- **`README.md`** — переписан по новому правилу (10 разделов: назначение, API, быстрый старт, два режима, адаптеры, состояние, структура, потребители, конфиг, тесты).
- **`docs/OBSERVABLE_ARCHITECTURE.md`** — новый файл: почему два режима наблюдаемости, почему методы класса (не `types.MethodType`), гарантии pickle для Windows spawn.
- **`docs/INTERFACES_USAGE.md`** — актуален (примеры использования IBaseManager, IBaseAdapter, IObservableMixin).
- **ADR-114…117** в `DECISIONS.md` — причины удаления плагинов, декораторов, __getattr__ magic, on_event/emit_event.
- **`ARCHITECTURE.md` §6.1** — заполнена роль и диаграмма base_manager в общей архитектуре фреймворка.
