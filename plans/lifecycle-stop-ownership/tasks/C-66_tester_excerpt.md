# C-66 — выжимка для слепого тестера

> Единственный вход тестера. Тестер работает в worktree от main `dcf7bc22c`, где брифа нет; лид передаёт этот текст
> в промпте. Как устроена правка, тестеру не известно и не проверяется.

## Что должно стать правдой

Здоровье процесса — один агрегат на процесс, но у деградации бывает несколько источников: плагины и автомат ошибок
(breaker). Источник снимает только свою деградацию. Закрытие breaker снимает только причину breaker. `ok()` плагина
снимает только причину этого плагина. `failed` важнее `degraded` любого источника.

Наружу по-прежнему одна строка `degraded_reason`. Среди активных причин одной тяжести показывается самая поздняя.

## Публичное API (не меняется)

```python
from multiprocess_framework.modules.process_module.health import HealthState, HealthReporter
hs = HealthState(clock=clock)         # clock — вызываемый объект, тест двигает время сам
A = HealthReporter(hs, source="A")    # методы: degraded(reason), failed(reason), ok(), set_status(status, reason)
B = HealthReporter(hs, source="B")
hs.report_error(RuntimeError("x"), context="load")   # 5 подряд открывают breaker (порог по умолчанию)
hs.poll(); hs.record_success()
hs.snapshot()    # dict: "status", "degraded_reason", "breaker", "errors", ...
hs.take_dirty()  # dict | None
```

**Закрытие breaker по тишине:** часы +62 с, `hs.poll()` (→ `half_open`), часы +62 с, `hs.poll()` (→ `closed`). Сдвиг нужен перед **каждым** `poll`.
**Закрытие по успеху:** `hs.record_success()`.

Переменная окружения порога и cooldown не задаётся; значения по умолчанию: порог 5, cooldown 30 с.

## Тесты (`multiprocess_framework/modules/process_module/tests/test_health_claims_acceptance.py`)

Ожидаемые значения — литералы. `(status, degraded_reason, breaker)`. Запись «содержит X» — проверка вхождения.

- **R1 `test_plugin_degraded_survives_breaker_close_by_silence`** — `A.degraded("assets")`, 5×`report_error`: `degraded`, содержит `breaker open`, `open`. Закрытие по тишине: `("degraded", "assets", "closed")`. Затем `A.ok()`: `("ok", None, "closed")`. На main красный: после закрытия `("ok", None, "closed")`.
- **R2 `test_plugin_degraded_survives_breaker_close_by_success`** — `A.degraded("assets")`, 5×`report_error`, `hs.record_success()`: `("degraded", "assets", "closed")`. На main красный: `("ok", None, "closed")`.
- **R3 `test_degraded_after_breaker_open_survives_close`** — 5×`report_error`, `A.degraded("assets")`: `("degraded", "assets", "open")`. Закрытие: `("degraded", "assets", "closed")`. На main красный: `("ok", None, "closed")`.
- **R4 `test_failed_not_lowered_by_breaker`** — `A.failed("fatal")`, 5×`report_error`: `("failed", "fatal", "open")`. Закрытие: `("failed", "fatal", "closed")`. На main красный: `degraded` с причиной breaker, затем `ok`.
- **R5 `test_plugin_ok_does_not_hide_open_breaker`** — 5×`report_error`, `A.ok()`: `degraded`, содержит `breaker open`, `open`. Закрытие: `("ok", None, "closed")`. На main красный: `("ok", None, "open")`.
- **R6 `test_plugin_ok_does_not_clear_neighbour`** — `A.degraded("a-reason")`, `B.ok()`: `("degraded", "a-reason", "closed")`. `A.ok()`: `("ok", None, "closed")`. На main красный: `("ok", None, "closed")` после `B.ok()`.
- **R7 `test_published_snapshot_after_close_keeps_reason`** — как R1 до закрытия; `hs.take_dirty()`; закрытие; `hs.take_dirty()` не `None`, в нём `status` `degraded`, `degraded_reason` `assets`, `breaker` `closed`. На main красный: `ok`.

Стражи (зелёные до и после):

- **S1 `test_breaker_only_degradation_clears_on_close`** — 5×`report_error`, закрытие: `("ok", None, "closed")`.
- **S2 `test_own_ok_clears_own_degraded`** — `A.degraded("x")`, `A.ok()`: `("ok", None, "closed")`.

Команда (cwd и `PYTHONPATH` — корень worktree, основной `.venv`, без `uv sync`):
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-5e
<.venv python> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_health_claims_acceptance.py`

Python subprocess с `"bash"` уходит в WSL: при необходимости писать `C:/Program Files/Git/bin/bash.exe`.

## Запрещено читать

`plans/lifecycle-stop-ownership/tasks/C-66*.md` (кроме этой выжимки), `plans/lifecycle-stop-ownership/reports/C-66*`,
строку C-66 в `plans/queue/defects.md`; реализацию: `multiprocess_framework/modules/process_module/health/state.py`,
`Services/ml_inference/plugin/plugin.py`, `Services/ml_inference/tests/test_preflight_c55b_hazards.py`. Можно: `process_module/health/README.md`, `health/schema.py`,
`health/breaker.py`, существующие тесты `process_module/tests/test_health_state.py`, `test_health_breaker_integration.py` как образец.
Не коммитить, не пушить.
