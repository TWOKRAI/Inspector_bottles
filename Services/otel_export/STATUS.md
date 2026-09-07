# Services/otel_export — STATUS

**Состояние: частичная реализация.** Ф1 закрыта — маппер, резолвер `Resource`, фильтр
числовой плоскости и приведение атрибутов работают. На стадии `contract` остался ровно один
Protocol — `LogExporter`: **ни одна запись наружу ещё не ушла**, отправки в коде нет.

**Обновлено:** 2026-09-07 — Task 2.1 (`OtelExportPlugin`, `coerce_attributes`, правка Р-10 в
`mapping.py`) плана [`plans/otel-export.md`](../../plans/otel-export.md), ветка `feat/otel-export`.

## Что есть

| Файл | Что в нём |
|---|---|
| `interfaces.py` | пять `Protocol` (`RecordMapper`, `ResourceResolver`, `LogExporter`, `ObservabilityPort`) и четыре типа контракта (`MappedRecord`, `Resource`, `ExportOutcome`, `FlushOutcome`) |
| `config.py` | `OtelExportConfig(SchemaBase)` — **единственное** объявление параметров, валидация границы, `to_dict`/`from_dict`, `readback()` |
| `exporter.py` | только `sdk_available() -> tuple[bool, str]`; ленивый импорт SDK |
| `mapping.py` | `DisplayRecordMapper`, `split_exportable`, `coerce_attributes` (Ф1.1/1.3 + Task 2.1) |
| `resources.py` | `PooledResourceResolver` — пул `Resource`, LRU, счётчик вытеснений (Ф1.2) |
| `README.md` | Purpose / Public API / Usage / Counters / Boundaries / Stability + словарь счётчиков литералами |
| `DECISIONS.md` | ADR-OTEL-001..005 |
| `tests/` | приёмочные тесты независимого тестера (A/B/D/E, маппер, резолвер, ленивый SDK) + авторские тесты опасных мест |

## Чего нет — и это по плану, а не забыто

| Чего нет | Чья задача |
|---|---|
| реализация `LogExporter` (`BatchLogRecordProcessor` + `OTLPLogExporter`) | Ф2.2, Ф2.4 |
| фрагмент топологии `backend/topology/otel_export.yaml` | Ф3.1 |

## Открытые вопросы фазы

1. **`ObservabilityPort` и `PluginContext` расходятся на один метод.** `PluginContext` даёт
   `log_info` / `log_warning` / `log_error` / `record_metric`, но `report_error` живёт на
   `ctx.health.report_error`, а не на самом контексте. То есть
   `isinstance(ctx, ObservabilityPort)` сегодня **False**. См. ADR-OTEL-004.
   **Состояние после Task 2.1: адаптер НЕ понадобился и не написан** — сервису сегодня
   контекст вообще не передаётся, наблюдаемость целиком у хоста (`plugin.py` зовёт
   `ctx.record_metric` / `ctx.health.report_error` сам). Разрыв станет условием тогда, когда
   `LogExporter` (Ф2.2/2.4) начнёт голосить изнутри сервиса.
2. **`declare_metric` не принимает точку в имени** — дословная строка плана «счётчики через
   `declare_metric` + `record_metric`» дала бы `ValueError` на старте плагина. **Снято в
   Task 2.1:** имена разведены (`METRIC_PREFIX` в `plugin.py`), обе плоскости пишутся. Разбор
   — в README, раздел `Counters`; там же исправлено неверное утверждение прежней редакции о
   видимости stats-плоскости в `introspect_telemetry`.
3. **`export_timeout_ms` действует не там, где кажется** — SDK игнорирует его у батчера,
   таймаут работает только у `OTLPLogExporter`. См. ADR-OTEL-005.
3a. **Отказ конфига нельзя печатать как `str(exc)`** — pydantic 2.13 выводит входное
   значение целиком, и отвергнутый токен уехал бы в `system.log`. Печатать через
   `format_validation_error(exc)`. Найдено авторским тестом, см. ADR-OTEL-005.
4. **Ни одна запись ещё не отправлена.** Всё, что здесь есть, — контракт и проверка наличия
   SDK; «работает» будет уместно сказать не раньше Ф4.1.
5. **Блокер Ф2.1 закрыт (Task 0.5), но у двери конфига остался соседний дефект.**
   `OtelExportRegisters` несёт дефолт `endpoint = ""`, поэтому managed-регистр строится, а
   пустое значение отвергается на шаг позже — в `configure()` плагина, с именем ключа.
   Новое, найдено прогоном в Task 2.1: `_init_register` применяет overrides **поле за полем**
   через `setattr` с `validate_assignment=True`, а порядок берёт из `model_fields`, где
   `max_queue_size` идёт РАНЬШЕ `max_export_batch_size`. Значит фрагмент топологии,
   понижающий очередь ниже дефолтного батча (`max_queue_size: 2`), отвергается кросс-полевым
   валидатором на промежуточном состоянии — **в любом порядке ключей фрагмента**. Обойти
   можно только парой значений, согласованной с дефолтами. Это долг двери конфига
   (`plugin_orchestrator` / `_init_register`), а не плагина.
