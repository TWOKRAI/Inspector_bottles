# base_manager — STATUS

**Статус:** ✅ Стабильный

**Последнее обновление:** 2026-04-08 (рефакторинг, Шаг 4)

## Кратко

Базовые классы всех менеджеров: `BaseManager`, `ObservableMixin`, `BaseAdapter`, `BaseManagerConfig`.

## Публичный API

```python
from base_manager import BaseManager, ObservableMixin, BaseAdapter, BaseManagerConfig
from base_manager.interfaces import IBaseManager, IBaseAdapter, IObservableMixin
```

## Метрики (после рефакторинга Шаг 4)

- **Файлов:** ~17 (было 29, −12)
- **Тестов:** 52 passed, 2 skipped
- **Изменения:** Удалены PluginRegistry, ObservableDecorators, MethodCache, simple_mode, on_event/emit_event, __getattr__ magic, no-op methods stubs.
