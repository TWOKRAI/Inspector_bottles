# scripts/stand_gate — стенд-гейт фазы 5

Одна команда поднимает стенд (или читает готовые JSON), снимает счётчики тракта, проверяет пороги и выходит с кодом. Источник порогов — Task 5.6 в [`plans/transport-single-policy/phase-5.md`](../../plans/transport-single-policy/phase-5.md) («Определения», «Acceptance criteria», OWNER-8). Перенос `stand5.py` / `analyze5.py` из [`docs/reviews/2026-10-03_phase5-stand-w2/`](../../docs/reviews/2026-10-03_phase5-stand-w2/).

## CLI

```
python -m scripts.stand_gate [--profile quick] [--runs N] [--from-json PATH ...] [--no-throughput-gate] [--out-dir reports/stand]
```

- `--profile quick` — три кейса на `scripts/capacity_bench/recipes/stand.yaml`, 1080p@100, `extras.overflow: every` на `processor` и `inspector`, окно 30 с, прогрев 10 с: `E` (`transit_ms=0`), `D100` (`transit_ms=100`), `P10` (`transit_ms=0`, пауза `pipeline_executor` у processor на 10 с через 5 с после начала окна).
- `--from-json PATH ...` — стенд не поднимать, проверить готовые JSON (несколько путей через пробел). Отчёт тоже пишется в `--out-dir`.
- `--no-throughput-gate` — выключает ТОЛЬКО порог lag processor (число остаётся в отчёте). Окно lag@inspector проверяется всегда.
- Дополнительно (живой режим): `--port` (драйвер, по умолчанию 8775), `--lock` (путь замка, по умолчанию `<git-common-dir>/../../stand.lock` — родитель основного дерева, один файл на все worktree; сегодня `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock`), `--lock-token <сессия>` (**обязателен** в живом режиме), `--json-dir` (куда класть JSON кейсов, по умолчанию `--out-dir`).

Замок держит лид руками; строка файла — `сессия | время | режим | SHA | порты`. Живой прогон выходит с кодом 2, если нет `--lock-token`, нет файла, нет строки, у которой поле «сессия» равно токену (сравнение поля, не подстроки), режим этой строки не `measure` или в файле больше одной непустой строки (конфликт держателей).

## Коды выхода

| Код | Значение |
|---|---|
| 0 | все пороги зелёные |
| 1 | нарушен хотя бы один порог; в stdout строка `FAIL <имя порога>: <факт> vs <порог>`. Дренаж с шагом опроса > 0.1 с — `FAIL drain: NOT_MEASURED ...` |
| 2 | сбой прогона: стенд не поднялся; файл не читается / не JSON; нет обязательного ключа (`s0`, `s1`, `s2`, `rc_s2`, `camera_before_pause`, `journal`; у P10 — `pause.{rss0,rss1,drain_s,drain_poll_period_s,after}`); замок (см. выше); заказанная пауза не состоялась (`pause_error` в JSON или `tag: P10` без `pause`); снимок процесса с ключом `error` на `s0` / `s2` / `pause.after` |

## Пороги (литералы в `thresholds.py`)

Обозначения: `F` — Σ `cycles` камеры в `camera_before_pause`; `I`, `N` — `total_inspected`, `total_not_inspected` из `rc_s2`; `V` — `journal.verdicts`. `born/drops/own_in/handled` — по «Определениям» Task 5.6.

| Имя в строке FAIL | Условие | Кейсы |
|---|---|---|
| `queue_data_evicted` | `rs.queue_data_evicted == 0` у всех процессов на `s0`, `s2` (+ `pause.after`) | все |
| `errors_delivery_failed` | `rs.errors_delivery_failed == 0` там же | все |
| `formula born-drops[P]` | `born(P) − drops(P) == 0` на `s2`, P = processor, inspector | все |
| `neighbor handled-own_in-born(processor)[N]` | `handled(N) − own_in(N) − born(processor) == 0`, N = inspector, renderer | все |
| `solver ledger (I+N)-F` | `0 ≤ (I + N) − F ≤ 0.005 × F` | все |
| `journal dup trace_id` | дублей `trace_id` в `messages.log` = 0 | все |
| `stale_restore` | `Σ_P Σ_workers not_inspected_stale_restore ≤ 0.001 × F` (все процессы) | все |
| `lag processor lag_dropped_items` | `Σ_workers lag_dropped_items(processor) ≤ 0.01 × F`; под `--no-throughput-gate` — REPORT | все |
| `verdicts V` | `V ≥ 0.9 × (F − N)` | D100 |
| `lag@inspector window s1-s0` | `Σ not_inspected_lag(inspector, s1) − то же на s0 ≤ 100` | D100 |
| `pause rss growth` | `pause.rss1 − pause.rss0 ≤ 1048576` байт | P10 |
| `drain` | `pause.drain_poll_period_s > 0.1` → `NOT_MEASURED` (код 1); иначе `pause.drain_s ≤ 0.1` → PASS, больше — FAIL. `drain_lower_s` на вердикт не влияет | P10 |
| `start frame_stale_drops[P]` | `s0 rs.frame_stale_drops == 0` у процессов под every (processor, inspector); остальные — REPORT | все |

Числа в отчёте без порога: `actuation_fired_items/missed_items/late_fires/unscheduled_items` (5.2), `start_s`, `first_frame_after_ready_s` (5.4), lag processor, строки отпуска фидеров (живой режим).

Кейс определяется по JSON: есть `pause` → P10; иначе `transit_ms > 0` → D100; иначе E.

## Живой прогон: как снимаются числа

- Журнал — только файлы `messages.log`; `observability.db` не читается (бинарный SQLite даёт ложные дубли). Одинаковые строки в нескольких `messages.log` — не дубли: берётся самый полный файл.
- Дренаж P10 (ред. 4): `pause.backlog` = `chain_queue.size` в снимке `pause_mid`; `t0` берётся ДО отправки `worker.start`; опрос — один вызов `introspect_status(processor)`, шаг ≤ 20 мс, до роста `cycles` исполнителя на `backlog + 1` относительно `pause_mid`. В JSON: `drain_s` — от `t0` до опроса, увидевшего рост (верхняя граница); `drain_lower_s` — от `t0` до НАЧАЛА последнего опроса без роста (число для отчёта без порога: бэклог паузы при 5.3 уходит маркерами, которые `cycles` не пишут, поэтому нижней границей дренажа оно не является; `0.0`, если первый же опрос показал завершение); `drain_poll_period_s` — наибольший интервал между опросами, первый — от `t0` (включает ответ на команду). Заказанная пауза, которая не состоялась, — код 2.
- После `worker.pause_all` камера на `introspect` не отвечает — `F` снимается до паузы (`camera_before_pause`).

## Фикстуры тестов

`tests/fixtures/green_D100.json` и `red_E0_old.json` — копии `raw/D100_3.json` и `raw/E0_003264912_1.json` с журналом, пересчитанным по `messages.log`. `green_P10.json` — **синтетика**: `raw/P10_2.json` + вписанные `pause.drain_poll_period_s: 0.02`, `pause.drain_s: 0.05` (старым способом дренаж не измерим).

## Тесты

- `tests/test_t56_thresholds_acceptance.py` — слепая приёмка (72), чёрный ящик через `--from-json`.
- `tests/test_t56_author_hazards.py` — тесты автора: опрос дренажа (один вызов на опрос, шаг, NOT_MEASURED, потолок), журнал, отчёт, замок.

Запуск: `python -m pytest scripts/stand_gate/tests -q` (каталог в `testpaths`).
