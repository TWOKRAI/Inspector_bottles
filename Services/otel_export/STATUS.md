# Services/otel_export — STATUS

**Состояние: `contract`** — объявлен контракт, реализации экспорта нет.

**Обновлено:** 2026-09-05 — Task 0.4 (контракт до кода) + Task 0.2 шаг 2 (ленивый импорт SDK)
плана [`plans/otel-export.md`](../../plans/otel-export.md), ветка `feat/otel-export`.

## Что есть

| Файл | Что в нём |
|---|---|
| `interfaces.py` | пять `Protocol` (`RecordMapper`, `ResourceResolver`, `LogExporter`, `ObservabilityPort`) и четыре типа контракта (`MappedRecord`, `Resource`, `ExportOutcome`, `FlushOutcome`) |
| `config.py` | `OtelExportConfig(SchemaBase)` — **единственное** объявление параметров, валидация границы, `to_dict`/`from_dict`, `readback()` |
| `exporter.py` | только `sdk_available() -> tuple[bool, str]`; ленивый импорт SDK |
| `README.md` | Purpose / Public API / Usage / Counters / Boundaries / Stability + словарь счётчиков литералами |
| `DECISIONS.md` | ADR-OTEL-001..005 |
| `tests/` | 24 приёмочных теста независимого тестера (A/B/D/E) + авторские тесты опасных мест |

## Чего нет — и это по плану, а не забыто

| Чего нет | Чья задача |
|---|---|
| `mapping.py` — display-запись → OTel, фильтр числовых родов | Ф1.1, Ф1.3 |
| `resources.py` — пул `Resource`, LRU, `host.name` | Ф1.2 |
| реализация `LogExporter` (`BatchLogRecordProcessor` + `OTLPLogExporter`) | Ф2.2, Ф2.4 |
| `Plugins/io/otel_export/plugin.py` — подписка, счётчики, команды, останов | Ф2.1 |
| фрагмент топологии `backend/topology/otel_export.yaml` | Ф3.1 |

## Открытые вопросы фазы

1. **`ObservabilityPort` и `PluginContext` расходятся на один метод.** `PluginContext` даёт
   `log_info` / `log_warning` / `log_error` / `record_metric`, но `report_error` живёт на
   `ctx.health.report_error`, а не на самом контексте. То есть
   `isinstance(ctx, ObservabilityPort)` сегодня **False**, и Ф2 обязана передать сервису
   тонкий адаптер. См. ADR-OTEL-004.
2. **`declare_metric` не принимает точку в имени** — дословная строка плана «счётчики через
   `declare_metric` + `record_metric`» даст `ValueError` на старте плагина. Разбор — в
   README, раздел `Counters`.
3. **`export_timeout_ms` действует не там, где кажется** — SDK игнорирует его у батчера,
   таймаут работает только у `OTLPLogExporter`. См. ADR-OTEL-005.
3a. **Отказ конфига нельзя печатать как `str(exc)`** — pydantic 2.13 выводит входное
   значение целиком, и отвергнутый токен уехал бы в `system.log`. Печатать через
   `format_validation_error(exc)`. Найдено авторским тестом, см. ADR-OTEL-005.
4. **Ни одна запись ещё не отправлена.** Всё, что здесь есть, — контракт и проверка наличия
   SDK; «работает» будет уместно сказать не раньше Ф4.1.
5. **БЛОКЕР Ф2.1/Ф3.1: обязательный `endpoint` несовместим с тем, как фреймворк строит
   регистры.** `plugin_orchestrator` создаёт managed-регистр **без аргументов**
   (`instance = reg_item()`), значения фрагмента туда не попадают вовсе — значит у плагина
   с обязательным полем регистра **не будет** ни GUI-двери, ни `register_update`, а
   `_init_register` упадёт в `configure()`. Воспроизведено прогоном; три варианта решения и
   рекомендация — в [`docs/claude/OPEN_QUESTIONS.md`](../../docs/claude/OPEN_QUESTIONS.md),
   запись от 2026-09-05. **Решение принимает владелец плана до старта Ф2.1.**
