# C-60 — плагин узнаёт о стопе процесса раньше, чем стоп ждёт воркеров и исполнителей

**Дата:** 2026-11-01. **Лид:** inspector-bottles-ca (в начале сессии -aa, имя сменилось после лимита). **Ветка:** `fix/lifecycle-c60` от `da3febe8e`, main влит дважды (`ad72450c1`, `d4e0822d5`). Push не делался.
**Бриф и стадии:** `plans/lifecycle-stop-ownership/tasks/C-60.md` (+ `C-60_design_notes.md`, `C-60_tester_excerpt.md`, `C-60_injection_predictions.md`), отчёты `plans/lifecycle-stop-ownership/reports/C-60.*`.

## Итог

В `ProcessModulePlugin` появился необязательный хук `request_stop(ctx)` (по умолчанию пусто). Фреймворк зовёт его первым шагом закрытия процесса — до ожидания воркеров и исполнителей и до `shutdown` плагина; плагины идут в порядке, обратном загрузке. Хук запускает остановку и возвращается. `shutdown` остался на прежнем месте.

Дефект «по чтению» воспроизведён до кода. База на `da3febe8e`: у плагина метки `request_stop` нет, `shutdown` приходит через 1,000–1,016 с (R1) и 3,000–3,015 с (R1b) после начала закрытия, т.е. плагин узнаёт о стопе ровно к концу срока `work` (`W`).

## Числа

| Что | Результат |
|---|---|
| Слепой тестер (до кода) | R1, R1b, R3, R4 красные, R2, R5 зелёные; база R1 1,000–1,016 с (полоса [0,95; 1,30]), R1b 3,000 / 3,015 с (полоса [2,95; 3,30]) |
| После: приёмка + hazards H1–H9 + root_acceptance + root_hazards + shutdown_order | 50 passed → после r1 и H9 — hazards 14 passed |
| Матрица инъекций | I1–I14, красные совпали с прогнозом, записанным до прогона (расширения у I1/I4/I8/I9/I11 — журнал целиком; `reports/C-60.injections.md`) |
| Стенд S8, база n=3 | `shutdown − t_send` 3,016 / 3,016 / 3,078 с; метки `request_stop` нет |
| Стенд S8, после n=5 | `request_stop` 0,031–0,094 с (литерал ≤ 0,6), `shutdown` 3,047–3,109 с (литерал [3,0; 3,6]); ответ `process.stop` +0,062 с к базе (литерал ≤ 0,3); `exited`/`True` во всех 8 |
| Стенд S8w, n=1 (`W` = 7,0) | база `shutdown` 7,093 с; после `request_stop` 0,062 с, `shutdown` 7,078 с |
| `validate.py` | ошибок и предупреждений нет |
| Framework suite (без PM, `--deselect` C-78) на итоговом состоянии `d4e0822d5` | 12610 passed, 46 skipped, 1 xfailed, 1 failed за 26 мин 24 с |
| `process_manager_module/tests` | 1455 passed, 32 skipped, 0 failed, 6 мин 45 с |

Единственный красный — `tests/test_declarations_leak_order_independence.py::test_statistics_then_process_module_order_matches_the_reverse_order` (вложенный pytest). Внутренний упавший тест — `statistics_module/tests/test_bucket_cost_bench.py::TestCost::test_guard_cost_on_the_hot_path_measured_as_a_delta` (бенч по времени, `OPEN_QUESTIONS.md` п.4 «шумный»); отдельно на HEAD 3 из 3 passed. К C-60 не относится; имя внутреннего теста раньше не было известно (`OPEN_QUESTIONS.md`, п.3).

## Находка по ходу: регрессия, пойманная только полным suite

Первая версия правки `base.py` вместо вставки заменила блок `def shutdown` на `request_stop` и удалила штатный `ProcessModulePlugin.shutdown`. Плагин без своего `shutdown` падал в `_do_shutdown` с `AttributeError`: на первом прогоне 7 красных (5 в `test_f2_acceptance_writer_retraction.py` + вложенный leak_order + известный C-4). Ни тесты автора, ни приёмка, ни ревью двух раундов, ни матрица I1–I11 этого не видели: у всех тестовых плагинов `shutdown` свой. Исправлено `3464f5f3b`, добавлен сторож H9 (плагин на одних умолчаниях закрывается чисто; умолчания объявлены в базе), инъекция I14 (удалить default `shutdown`) краснит оба H9 и пять f2.

## Для Р2 (C-60.b) — условие приёмки

Плагин получает стоп до join исполнителя. Место: `Plugins/hub/device_hub/plugin.py:295` (`self._manager.request_stop_all(deadline)` внутри `shutdown`). Переносить надо не только вызов:
(а) `request_stop_all` ждёт потоки стопа до срока (`manager.py:176-183`, ≈ 2,5 с) — хуку нужен вариант «запустить без ожидания», ожидание остаётся в `shutdown`; хук дольше `W` оставляет `workers` выжившими (H2b);
(б) `_shutting_down = True` (`plugin.py:292`) переезжает в хук, иначе супервизор переподключит робота посреди стопа;
(в) `self._scope = None`, `_report_unconfirmed_stops`, удаление воркеров и `scope.close` остаются в `shutdown`;
(г) `_stop_deadline` в менеджере защёлкивается первым вызовом (`manager.py:136-141`) — срок хука считать от момента хука тем же бюджетом;
(д) стоп роботам идёт потоками `scope.spawn`, а не через исполнитель `device_io`; подача операции из хука получает `system_stopping` (H1).

## Открыто / ненадёжно

- **Прямой пары меток `request_stop < op_end` на стенде нет:** `L` = 10 с > `W` = 3,0, ребёнок выходит на `W`. «Операция шла при `request_stop`» подтверждена косвенно (`op_start` ≤ `request_stop`, WARNING исполнителя «не остановлен к сроку» на 3,0 / 7,08 с позже метки). Дополнить вариантом S8-short (`L` = 2,0 с < `W`; ожидание после: `request_stop − t_send` ≤ 0,6, `op_end − request_stop` ≥ 0,9, `shutdown` не раньше `op_end`) в следующем окне стенда.
- Мерился только `process.stop`; системный стоп PM→ребёнок идёт тем же кодом (`process_runner.py:177`, `close_root` :477), но стендом не мерился. Код выхода ребёнка (76 при выживших) стенд не читает.
- Зависший навсегда хук тестом не покрыт (контракт «запускает и возвращается» — единственная защита, решение лида на stage 0): воспроизведено — хук 6 с → через 3 с `worker_exit` = `None`; под PM ребёнка добивает `terminate` по окну. Воркер, держащий замок до `stop_event`, + хук, берущий тот же замок → `proc.shutdown()` не вернулся за 4 с (r1, п.4).
- H1: гонка «соседний `submit` против `shutdown()`» на практике даёт 0 принято / 50 отказов; ветка «принято до закрытия приёма» не исполняется. Заменить двумя детерминированными случаями.
- H8 читает stderr через `capfd` — зависит от синхронности консольного стока логгера (флейка в 3 прогонах reviewer'а и моих нет, гарантии нет).
- Вне FILES: `ARCHITECTURE.md:695` и `PluginTestBench.request_stop()` (автору плагина приходится звать приватный `_do_request_stop`) — в C-60.b.
- Форматтер после Edit переписывает правки инъекций (`except Exception as e` → `except Exception:`); прогонялась отформатированная версия, семантика та же.
- Хук `SubagentStop`/`pre_report_gate` смотрит в системный python без pytest и предлагает `uv sync` (в worktree запрещён). Дефект инструмента, не C-60.
- Корневой suite (~56 мин) не гонялся: объём — framework suite + PM-тесты, как в 1.11.
- Строка C-60 в `defects.md` неточна: плагин лежит в `Plugins/hub/device_hub` (координатор поправил), и первым долгую операцию ждёт запись `workers`, а не `KeyedExecutor.join_until`.

## Поправка к C-82 (отдельный отчёт: `docs/reports/2026-10-28_lifecycle-stop-ownership_C-82-investigation.md`)

Корень не `camera_0` и не Job Object: последним из дерева выходит сам PM, потому что `system.shutdown`, пришедший во время `initialize()`, не прерывает подъём (`app_discover` 65 плагинов ещё 4,1–7,2 с). Три решения владельца — в ответе лида; C-82 остаётся в очереди после C-64/65/66/79.

## agentId

| Роль | agentId | Состояние |
|---|---|---|
| manager (бриф) | `a3326fd0de61de313` | закончил, 268k |
| reviewer sonnet (stage 0 р.1–р.2; stage 5 р.1–р.2) | `a28a4511f5a1f5bad`, `ab97bf148ff7cd969` | закончили, 258k / 247k |
| tester (слепой) | `a4fb767277ce8b166` | закончил, 113k |
| teamlead (реализация, правки r1, H9) | `a30768ed0662e9859` | закончил, 195k |
| junior (Haiku), матрица инъекций | `ae7ac1c6536e7c692` | закончил, 168k |
| developer, стенд S8 | `afb290f1c29104dc4` | закончил, 207k |
| investigator C-82 | `a98ec6b2ec4dd844b` | закончил, 182k |

Модели/окна: окна — quiet 16:2x–16:5x (стенд), heavy 17:24–17:58 (первый suite), heavy 18:4x–19:22 (повторный suite). Все heavy/стенд-запуски через `machine_gate.sh`.
