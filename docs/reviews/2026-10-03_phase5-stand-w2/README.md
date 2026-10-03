# Стенд волны 2 фазы 5 — 2026-10-03

Лид transport-f5, сессия f4. Дерево `.claude/worktrees/stand`, detached на `978377d7d` (`feat/transport-f5`: волна 2 + 5.5). Контроль — тот же стенд на `003264912` (main до волны 2). Замок `stand.lock`, режим measure, соседи подтвердили тишину. Отчёт с выводами — [`../2026-10-03_phase5-stand-w2.md`](../2026-10-03_phase5-stand-w2.md).

## Файлы
| Файл | Что это |
|---|---|
| `stand5.py` | один кейс стенда; наследник `stand47d.py` (4.7d-5): `--transit-ms`, `get_stats` робота, время старта и первого кадра, дренаж с шагом 50 мс. Журнал читает только `messages.log` (исправлено после прогонов — см. ниже) |
| `analyze5.py` | разбор: `python analyze5.py <tag>` — таблица 4.7d; `python analyze5.py --p5 <tag> ...` — пороги фазы 5 |
| `predictions.md` | предсказания до замера |
| `raw/*.json` | сырьё: `D100_{1,2,3}` (`transit_ms=100`), `P10_{1,2}` (пауза исполнителя processor 10 с), `E0_<sha>_{1,2}` (контроль, `transit_ms=0`) |
| `fixtures/green_D100.json`, `fixtures/red_E0_old.json` | фикстуры для тестов `scripts/stand_gate` (Task 5.6): `raw/D100_3` и `raw/E0_003264912_1` с ключом `journal`, пересчитанным по `messages.log`; старый ключ сохранён как `journal_raw_stand5_buggy` |
| `fixtures/green_P10.json` | **синтетика**: `raw/P10_2` + журнал по `messages.log` + вписанные лидом `pause.drain_s: 0.05`, `pause.drain_poll_period_s: 0.02` (старым способом дренаж не измерим; замеренное — в `pause.drain_s_measured_old_method`) |

Запуск кейса: cwd = PYTHONPATH = меряемое дерево, `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen`, интерпретатор проекта: `python stand5.py --overflow every --secs 30 [--transit-ms 100] [--pause-secs 10] --out case.json`.

## Схема JSON кейса
Верхний уровень:
- `overflow`, `secs`, `reject_delay_ms`, `transit_ms`, `case_dir` (временная папка с логами; после перезагрузки машины её нет);
- `start_s` — время `BackendHarness.start()`; `first_frame_after_ready_s` — первый ненулевой `cycles` камеры после ready (опрос 20 мс);
- `s0` (ready + 10 с), `s1` (конец окна 30 с), `s2` (после паузы камеры и тишины) — снимки всех процессов;
- `camera_before_pause`, `camera_pause`, `camera_after_pause` — снимок камеры до паузы, ответ `worker.pause_all`, снимок после (после паузы камера на `introspect` не отвечает: 0 циклов);
- `rc_s1`, `rc_s2` — ответ `get_stats` у inspector (`RobotControlPlugin`), внутри — `actuation_*`, `total_inspected`, `total_not_inspected`, `verdicts_written`; ответ обёрнут драйвером, искать dict с ключом `total_inspected`;
- `hz_median` — медиана `hz` из `system_overview` за окно;
- `journal` — `rows`, `distinct`, `dup`, `markers`, `verdicts`, `actions`, `marker_origins`, `file`;
- только у `P10`: `pause_worker_names`, `pause_stop`, `pause_mid`, `pause_start`, `pause` = `{worker, stopped_s, rss0, rss1, drain_s, drain_trace, after}`.

Снимок процесса (`s0[<процесс>]`): `workers.<воркер>.<ключ>` (ключи: `lag_dropped_items`, `lag_dropped_total`, `not_inspected_lag`, `not_inspected_stale_restore`, `not_inspected_stale_exec`, `not_inspected_handled`, `queue_wait_ms`, `effective_hz`, `cycles`; есть только у воркеров, где счётчик заведён), `rs.<ключ>` (`frame_stale_drops`, `frame_torn_reads`, `frame_restore_failures`, `door_drops`, `not_inspected_door`, `queue_data_evicted`, `frame_loan_exhausted`, `errors_delivery_failed`, `deferred_closes` — кто есть), `rs_all` (все ненулевые числовые статистики роутера), `queues` (ответ `introspect_queues`, внутри `chain_queue.size`).

## Известные дефекты инструмента (найдены в этом замере)
- **Журнал по `observability.db`.** До исправления скрипт выбирал «самый полный» файл и читал бинарный SQLite как текст: ложных дублей 95–462 на прогон. В `raw/*.json` ключ `journal` — старый (ошибочный); правильные числа даёт `analyze5.py` (читает `messages.log`) или `fixtures/`.
- **Дренаж.** Опрос — полный снимок (три команды), первый опрос приходит через ~0.17 с. Порог 5.3 «≤ 0.1 с» этим способом не доказуем.
