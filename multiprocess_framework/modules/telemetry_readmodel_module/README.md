# telemetry_readmodel_module

Generic **Qt-free** ядро локальной read-model телеметрии: одна проекция состояния
(`path → value`) + кольцевые буферы истории по ключевым метрикам, наполняемые
ОДНИМ потоком уже разобранных дельт.

Принцип **«запись — всегда, чтение — локально, история — по запросу»** (ADR-136):
backend публикует телеметрию постоянно (троттлинг у источника) в дерево
StateStore; потребитель держит один локальный read-model и читает снимок/историю
локально — **0 IPC на чтение**.

## Зачем отдельный модуль

Ядро транспорт-агностично и не зависит от Qt, поэтому переиспользуется РАЗНЫМИ
потребителями без дублирования тонких инвариантов (граница префикса snapshot,
приведение к числу, окно истории):

| Потребитель | Слой | Обёртка над ядром |
|---|---|---|
| GUI `TelemetryViewModel` | `frontend_module` (Qt) | конверт `state_delta` + коалесинг сигнала `updated` (`QTimer`) |
| Драйвер диагностики `backend_ctl` | tooling (headless) | push `state.changed` из сокета → `telemetry_snapshot`/`telemetry_history` агенту |

Прямой reuse GUI-VM в headless-драйвере невозможен: `TelemetryViewModel` —
`QObject`, а `frontend_module`/`state_store_module` тянут PySide6 через package
`__init__`. Извлечённое ядро живёт вне Qt-цепочки импортов — импортируется и из
GUI-слоя, и из headless-tooling. ADR — `frontend_module/DECISIONS.md` и
`backend_ctl` DECISIONS (reuse-vs-own).

## Публичный API

```python
from multiprocess_framework.modules.telemetry_readmodel_module import (
    TelemetryReadModel, DEFAULT_TRACKED_SUFFIXES, ITelemetryReadModel,
)

m = TelemetryReadModel(tracked_suffixes=(".state.fps",), window_sec=600, sample_hz=1.0)
m.ingest("processes.cam.state.fps", 25.3)              # разобранная дельта
m.ingest("processes.cam.state.fps", None, deleted=True)  # удаление узла
m.get("processes.cam.state.fps")                       # текущее значение
m.snapshot("processes.cam")                            # снимок поддерева
m.history("processes.cam.state.fps", since=ts)         # спарклайн (ts, value)
```

- `ingest(path, value, *, deleted=False)` — envelope-agnostic: обёртка парсит свой
  конверт и передаёт уже разобранные `(path, value, deleted)`.
- `snapshot(prefix)` — граница по точке-разделителю (`processes.cam` не течёт в
  `processes.cam2.*`); пустой prefix → весь снимок.
- `history(path, since)` — кольцевой буфер (fixed-size deque, `maxlen =
  ceil(window_sec * sample_hz)`), ts — wall-clock (Unix-epoch, единая ось с БД-историей).

## Инварианты

- НЕ создаёт серверных подписок, не держит router/proxy, не делает блокирующий IPC.
- История копится только для числовых значений отслеживаемых суффиксов
  (`tracked_suffixes`; `bool` числом не считается).
- Generic: имён процессов и прикладного набора метрик не знает — параметры
  конструктора.

## Границы

- `tracked_suffixes` по умолчанию (`DEFAULT_TRACKED_SUFFIXES`) отражают штатные
  gated-метрики фреймворка (`process_module` — `build_worker_telemetry`), но это
  набор ИСТОРИИ, а не зеркало publish-gate `GATED_METRICS`.
- Глубокая история (час/день) — вне модуля: read-сторона SQLite-стока —
  `frontend_module.state.TelemetryHistorySource`.

Тесты: `tests/test_telemetry_read_model.py` (unit, без Qt).
