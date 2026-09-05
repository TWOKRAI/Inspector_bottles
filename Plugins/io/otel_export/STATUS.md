# Plugins/io/otel_export — STATUS

**Состояние: `contract`** — дверь конфига объявлена, плагина нет.

**Обновлено:** 2026-09-05 — Task 0.4 плана [`plans/otel-export.md`](../../../plans/otel-export.md),
ветка `feat/otel-export`.

| Что | Состояние |
|---|---|
| `registers.py` — `OtelExportRegisters` | есть; производная от `Services.otel_export.config.OtelExportConfig`, своих полей нет |
| `config.py` — `OtelExportPluginConfig` | есть; identity + `register_bindings` |
| `plugin.py` — `OtelExportPlugin` | **нет**, Ф2.1 (подписка, приём, `stamp_observed`, счётчики, команды, `shutdown`) |
| фрагмент топологии `otel_export.yaml` | **нет**, Ф3.1 |
| адаптер `ObservabilityPort` над `ctx` | **нет**, Ф2.1 — обязателен: `PluginContext` не несёт `report_error` (ADR-OTEL-004) |

**Тесты:** `tests/test_registers_acceptance.py` — 3 приёмочных теста независимого тестера
(набор полей регистров == набор полей конфига; `readback()` маскирует секрет; `readback()`
не равен сырому `model_dump()`).

**БЛОКЕР перед Ф2.1 — решить до кода.** `endpoint` объявлен обязательным (критерий B1), а
`plugin_orchestrator` строит managed-регистр **без аргументов** (`instance = reg_item()`) —
значит регистра у этого плагина не будет вовсе: ни GUI-двери, ни `register_update`, а
`_init_register` упадёт в `configure()`. Воспроизведено прогоном; три варианта и рекомендация
— в [`docs/claude/OPEN_QUESTIONS.md`](../../../docs/claude/OPEN_QUESTIONS.md), запись
от 2026-09-05.

**Проверить перед подключением фрагмента топологии:** процесс не поднимется, пока нет
`plugin.py`. Фрагмент подключается строкой в `app.yaml → base:` и по умолчанию отсутствует —
кто не подключил, не платит ни процессом, ни строками golden-снимков рецептов.
