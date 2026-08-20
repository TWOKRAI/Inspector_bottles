# STATUS — telemetry_readmodel_module

**Состояние:** активный. Введён при извлечении Qt-free ядра read-model из GUI
`TelemetryViewModel` (план `backend-ctl-framework-module`, Task 2.3).

## Что готово

- `TelemetryReadModel` — снимок `path → value` + кольцевые буферы истории;
  envelope-agnostic `ingest`; `get`/`snapshot`/`history`.
- `export_history`/`import_history` + инъектируемый `clock` (D.4 flight recorder):
  аддитивно, дефолт `clock=time.time` бит-в-бит (характеризационный пин).
- `write_seq` + `ingest_poll_snapshot(values, *, requested_at_seq)` (S-1, нога B):
  **второй инвариант ядра — порядок записи**. Ответ опроса, отправленный до
  push'а и пришедший после него, больше не воскрешает снятое значение; судится
  каждый путь отдельно, номер, а не время (Windows-сетка `monotonic` 15.6 мс).
- `ITelemetryReadModel` (Protocol) — контракт (включая `write_seq` и влив опроса).
- Поддержка ВТОРОЙ формы адреса `…state.plugins.<писатель>.<метрика>` (Ф1 «порта
  наблюдений», Task 1.4): один и тот же `tracked_suffixes` покрывает и плоский
  агрегат, и лист в поддереве писателя; ключ кольца остаётся полным путём, так
  что два писателя одноимённой метрики не слипаются. Опасности свёртки —
  `tests/test_plugin_subtree_history_hazards.py` (15 тестов).
- Unit-тесты (`tests/test_telemetry_read_model.py`), без Qt; опасности сторожа
  порядка — `tests/test_write_seq_ordering_hazards.py` (18 тестов): граница
  `>` против `>=`, чистка словаря номеров при удалении узла, реентерантность,
  пересоздание ядра под висящими запросами.

## Потребители

- `frontend_module.state.TelemetryViewModel` (Qt) — композирует ядро.
- `backend_ctl` driver (headless) — композирует ядро, наполняет `state.changed`.

## Границы / вне охвата

- Qt-обёртки и коалесинг сигналов — у потребителя, не в ядре.
- Разбор транспортного конверта (`state_delta` / `state.changed`) — у потребителя.
- Глубокая БД-история — `frontend_module.state.TelemetryHistorySource`.

## Будущее

- Пост-codemod (layer-grouping): модуль остаётся framework-уровнем; backend_ctl
  переезжает в `tooling/` и продолжает импортировать это ядро.
