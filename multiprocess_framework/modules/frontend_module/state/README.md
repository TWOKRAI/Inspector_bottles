# frontend_module.state — GUI read-model телеметрии

Generic read-сторона состояния для GUI-оболочек фреймворка. Реализует принцип
плана телеметрии: **«запись — всегда, чтение — локально, история — по запросу»**.

Backend публикует телеметрию постоянно в дерево StateStore; GUI держит ОДИН
локальный read-model, наполняемый ОДНИМ wildcard-потоком дельт. Виджеты читают
только локально — без блокирующего похода на сервер за снимком.

## Публичный API

| Символ | Назначение |
|--------|-----------|
| `TelemetryViewModel` | Локальный read-model: снимок (`snapshot`/`get`) + история в кольцевых буферах (`history`). Батч-сигнал `updated` на пачку дельт (коалесинг). |
| `DEFAULT_TRACKED_SUFFIXES` | Суффиксы штатных gated-метрик фреймворка (дефолт для истории VM). |
| `TelemetryHistorySource` | Read-only диапазонная выборка из SQLite-таблицы стока телеметрии с даунсемплом. |

Импорт — через `interfaces.py` модуля либо напрямую:

```python
from multiprocess_framework.modules.frontend_module.state import (
    TelemetryViewModel, TelemetryHistorySource, DEFAULT_TRACKED_SUFFIXES,
)
```

## Границы (generic)

Модуль **не знает** прикладного слоя:

- `TelemetryViewModel` не держит ссылок на router/state-proxy — питается только
  входящими dict-сообщениями (`on_state_delta`). НЕ создаёт серверных подписок
  и не делает блокирующий IPC (инвариант — под тестом).
- Набор путей для истории (`tracked_suffixes`) — параметр конструктора; дефолт
  покрывает штатные метрики фреймворка (`GATED_METRICS`).
- `TelemetryHistorySource` не хардкодит имя таблицы, whitelist метрик и путь БД —
  всё передаётся приложением (тонкая конфигурация стока телеметрии).

Слой импортов: `frontend_module` НЕ импортирует `multiprocess_prototype.*`.
Приложение конфигурирует read-model в своём composition root.

## Late-binding

`snapshot(prefix)` / `get(path)` возвращают актуальный снимок сразу — вкладка,
созданная ПОСЛЕ публикации разовой дельты, читает текущее значение без
повторной подписки. Это снимает нужду в отдельном «replay последнего значения»
на стороне биндингов: read-model — единый источник late-binding-снимка.

## Dict-at-Boundary

`TelemetryViewModel` ест dict-сообщение (не live `SchemaBase`) — граница
процессов соблюдена.
