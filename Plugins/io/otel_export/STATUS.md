# Plugins/io/otel_export — STATUS

**Состояние: `contract`** — дверь конфига объявлена, плагина нет.

**Обновлено:** 2026-09-05 — Task 0.4 плана [`plans/otel-export.md`](../../../plans/otel-export.md),
ветка `feat/otel-export`.

| Что | Состояние |
|---|---|
| `registers.py` — `OtelExportRegisters` | есть; производная от `Services.otel_export.config.OtelExportConfig`, дефолт `endpoint = ""` переопределён (Task 0.5), остальные поля не переобъявлены |
| `config.py` — `OtelExportPluginConfig` | есть; identity + `register_bindings` |
| `plugin.py` — `OtelExportPlugin` | **нет**, Ф2.1 (подписка, приём, `stamp_observed`, счётчики, команды, `shutdown`) |
| фрагмент топологии `otel_export.yaml` | **нет**, Ф3.1 |
| адаптер `ObservabilityPort` над `ctx` | **нет**, Ф2.1 — обязателен: `PluginContext` не несёт `report_error` (ADR-OTEL-004) |

**Тесты:** `tests/test_registers_acceptance.py` — 3 приёмочных теста независимого тестера
(набор полей регистров == набор полей конфига; `readback()` маскирует секрет; `readback()`
не равен сырому `model_dump()`).

**Блокер перед Ф2.1 — закрыт вердиктом CTO (Task 0.5).** `endpoint` обязателен в
`OtelExportConfig` (критерий B1 проверяет его именно там); `plugin_orchestrator` по-прежнему
строит managed-регистр без аргументов (`instance = reg_item()`), но `OtelExportRegisters`
теперь несёт дефолт `endpoint = ""` — регистр строится, GUI-дверь и `register_update`
работают. Пустое значение отвергается на шаге позже: в `configure()` плагина (Ф2.1), где
`OtelExportConfig(**self.model_dump())` вернёт `ValidationError` с именем ключа. Механизм и
альтернативы — ADR-OTEL-003 в [`Services/otel_export/DECISIONS.md`](../../../Services/otel_export/DECISIONS.md).
Долг closure (не в этой фазе): строить managed-регистр из значений фрагмента топологии, а
не из голых дефолтов — репродукция `plugin_orchestrator.py:325` там же.

**Проверить перед подключением фрагмента топологии:** процесс не поднимется, пока нет
`plugin.py`. Фрагмент подключается строкой в `app.yaml → base:` и по умолчанию отсутствует —
кто не подключил, не платит ни процессом, ни строками golden-снимков рецептов.
