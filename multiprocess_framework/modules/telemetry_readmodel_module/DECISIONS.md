# telemetry_readmodel_module — решения

Модуль появился при извлечении Qt-free ядра read-model телеметрии из GUI
`TelemetryViewModel` (план `backend-ctl-framework-module`, Task 2.3).

## Почему модуль существует (reuse-vs-own)

Полное решение и отвергнутые альтернативы — **FE-005** в
[`frontend_module/DECISIONS.md`](../frontend_module/DECISIONS.md). Кратко:
одно generic Qt-free ядро (снимок + история + тонкие инварианты) переиспользуют
и GUI (`TelemetryViewModel`, Qt-обёртка), и headless-драйвер диагностики
backend_ctl — чтобы не дублировать инварианты `snapshot`-boundary /
number-coercion / ring-window (дрейф двух копий).

## Границы модуля

- **Транспорт-агностично:** ядро принимает уже разобранную дельту
  (`ingest(path, value, deleted)`); разбор конверта (`state_delta` /
  `state.changed`) — у потребителя.
- **Без Qt и без IPC:** не импортирует PySide6, не создаёт подписок, не ходит на
  сервер (`get`/`snapshot`/`history` локальны — принцип ADR-136 «чтение локально»).
- **Живая история — в памяти; глубокая — вне модуля:** БД-сток телеметрии
  (час/день) читает `frontend_module.state.TelemetryHistorySource`.
