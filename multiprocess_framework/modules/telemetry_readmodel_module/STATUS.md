# STATUS — telemetry_readmodel_module

**Состояние:** активный. Введён при извлечении Qt-free ядра read-model из GUI
`TelemetryViewModel` (план `backend-ctl-framework-module`, Task 2.3).

## Что готово

- `TelemetryReadModel` — снимок `path → value` + кольцевые буферы истории;
  envelope-agnostic `ingest`; `get`/`snapshot`/`history`.
- `ITelemetryReadModel` (Protocol) — контракт.
- Unit-тесты (`tests/test_telemetry_read_model.py`), без Qt.

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
