# Plugins/io/otel_export — STATUS

**Состояние: приём работает, отправки нет.** Плагин принимает хвост наблюдаемости, ставит
отметку приёма, отбрасывает числовую плоскость, приводит записи к модели OTel и считает
восемь величин. **Наружу не ушла ни одна запись** — `LogExporter` приходит в Ф2.2/2.4.

**Обновлено:** 2026-09-07 — Task 2.1 плана [`plans/otel-export.md`](../../../plans/otel-export.md),
ветка `feat/otel-export`.

| Что | Состояние |
|---|---|
| `plugin.py` — `OtelExportPlugin` | **есть**: намерение брокеру через `request_async` (`MAX_ATTEMPTS = 3`), хендлер `observability.record`, `stamp_observed`, `split_exportable`, `coerce_attributes`, пул `Resource`, счётчики в двух плоскостях, `otel_export.status` / `otel_export.flush`, снятие намерения в `shutdown` |
| `registers.py` — `OtelExportRegisters` | есть; производная от `Services.otel_export.config.OtelExportConfig`, дефолт `endpoint = ""` переопределён (Task 0.5), остальные поля не переобъявлены |
| `config.py` — `OtelExportPluginConfig` | есть; identity + `register_bindings` |
| отправка записей наружу | **нет**, Ф2.2/2.4 — записи копятся в кольце `max_queue_size`, переполнение считается `otel_export.dropped_overflow` |
| фрагмент топологии `otel_export.yaml` | **нет**, Ф3.1 |
| адаптер `ObservabilityPort` над `ctx` | **не понадобился**: сервису контекст не передаётся, вся наблюдаемость у хоста. Станет условием, когда голосить начнёт `LogExporter` (ADR-OTEL-004) |

**Тесты:** `tests/test_registers_acceptance.py` (3 приёмочных, Task 0.4),
`tests/test_register_default_hazard.py` (3 авторских, Task 0.5),
`tests/test_f2_task21_acceptance.py` (27 приёмочных независимого тестера, Task 2.1 — писались
ДО реализации, в worktree на pre-implementation коммите),
`tests/test_f2_task21_hazards.py` (19 авторских на опасные места механизма).

## Состояния плагина

`ready` / `degraded` / `error` — **свои**, а не `PluginState` фреймворка (Р-13): у того пять
значений и ни `error`, ни `degraded` в нём нет. Читаются командой `otel_export.status`
вместе с полем `reason`.

* `error` — пустой/невалидный `endpoint` либо отсутствие extra `[otel]`. `configure()` при
  этом **не бросает** (Р-14): процесс обязан подняться, а причина обязана быть спрашиваемой.
  В этом состоянии `start()` не регистрирует хендлер и не объявляет намерение.
* `degraded` — брокер не подтвердил намерение за три попытки. Инцидент в плоскости ошибок
  ровно один (`health.report_error`, он же голос ERROR — один разъём на ветку, ADR-PM-030).

## Что стоит знать перед следующей задачей

**Долг двери конфига, найденный прогоном в Task 2.1.** `_init_register` применяет overrides
фрагмента **поле за полем** через `setattr` с `validate_assignment=True`, а порядок берёт из
`model_fields`, где `max_queue_size` идёт РАНЬШЕ `max_export_batch_size`. Фрагмент топологии
с `max_queue_size: 2` отвергается кросс-полевым валидатором на промежуточном состоянии
(«батч 512 больше очереди 2») — **в любом порядке ключей во фрагменте**. Задеть это способна
Ф3.1. Долг чужой (`plugin_orchestrator` / `_init_register`), здесь не чинился.

**Подключать фрагмент топологии до Ф3.1 незачем:** принимать записи, которые никуда не
поедут, значит платить процессом за одни счётчики.
