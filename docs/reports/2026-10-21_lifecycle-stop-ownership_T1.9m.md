# Отчёт: Task 1.9m — `ExecutorManager` (полоса Ф, 2026-10-21)

Сессия inspector-bottles-48. План — [`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md),
задача — [`T1.9m.md`](../../plans/lifecycle-stop-ownership/tasks/T1.9m.md) (+ [`T1.9m_facts.md`](../../plans/lifecycle-stop-ownership/tasks/T1.9m_facts.md)).
Ветка `feat/lifecycle-executor-manager`, перебазирована на main `29a00f99a`.

## Итог

`ExecutorManager(BaseManager)` — подмодуль `worker_module/executor_manager.py`, есть в каждом процессе.
- Исполнители заводятся двумя путями: из ключа конфига процесса `executors` или регистрацией готового `OrderedExecutor` по имени.
- Остановка — в scope `work` после `plugins`.
- Интроспекция — команда `introspect.executors`.
- `register_command(executor=)` принимает объект или имя; имя разрешается при регистрации, ошибка — сразу.
- Без исполнителей — ноль потоков и ноль строк лога.
- Ядро `keyed_executor.py` (1.9a) не тронуто.

Решение владельца 2026-10-21 (через координатора) — ADR-WRK-006. Рядом ADR-CMD-007, ADR-PM-055, абзац в ADR-BM-008
(публичный `check_scope_name`).

## Цикл

| Стадия | Кто | Итог |
|---|---|---|
| Спека | manager Opus | `T1.9m.md` + `_facts.md` |
| Стадия 0 | reviewer Opus | р.1 — 12 правок; р.2 — APPROVED, 3 текстовые правки лида |
| Слепой тестер | tester Sonnet, worktree на `43b8e763a` | R1–R10: собрано 10, красных 10, у каждого своя причина |
| Реализация | developer Sonnet | Б1 (коды 1–6 + H1–H8), Б2 (коды 7–8) |
| Документы | tech-writer Sonnet | README, три ADR, карты, OPEN_QUESTIONS; `scripts.sync` |
| Инъекции | Haiku, отдельный detached worktree | И1–И13, сошлось после разбора (ниже) |
| Ревью задачи | reviewer Sonnet | р.1 — 1 major + 2 minor; р.2 — APPROVED |
| Ревью ветки | reviewer Opus | р.1 — шов «конфиг → команда» не закреплён; р.2 — APPROVED |
| Окно лида | лид | suite нашёл 2 регрессии 1.9m — исправлены в `e7b6508a9` |

## Матрица инъекций (прогнозы записаны до прогона)

База: 49 тестов, все зелёные (на 617fc0a72 — 51).

| # | Поломка | Красные (факт) | Прогноз | Разбор |
|---|---|---|---|---|
| И1 | имя не найдено → регистрация синхронной | R7 | R7 | — |
| И2 | `register` отдаёт объект во владение | R3 | R3 | — |
| И3 | свой срок вместо общего | 0 → после переноса на верное место: R4 | R4 | 1-й прогон: Haiku внёс поломку в цикл `_unowned`; И3' в `_OwnedExecutor.join_until` — R4 («закрытие заняло 2.01 с») |
| И4 | без проверки своего потока | R5 | R5 | — |
| И5 | `load_config` без try на запись | R2 | R2 | — |
| И6 | нет записи в scope `work` | R8, R9 | R8, R9 (+H2 вероятно) | H2 слабый: зовёт `reply` напрямую, не через роутер |
| И7 | `describe()` по конфигу | H3, H5 | R2 | прогноз по имени теста неверен; в слепом наборе нет теста `describe()` с исполнителем не из конфига |
| И8 | исполнитель по умолчанию | R10 | R10 | — |
| И9 | `metadata["executor"] = obj.name` | R6 | R6 | — |
| И10 | `build()` не снимает пустой ключ | R10 | R10 | — |
| И11 | `is_worker_protected` без ветки SYSTEM | H7 + `test_is_worker_protected_by_system_type` | то же | C-23(а): IPC-путь закрыт защитой SYSTEM, H7 — страж |
| И12 (лид) | `describe()` без лока | 0 → после усиления H5: H5 3/3 (`dictionary changed size during iteration`) | H5 | H5 переписан (Barrier, 5 раундов) |
| И13 (лид) | ветка `late` не снимает резерв | 0 → после H9b: H9b | H1 | ветка не была покрыта; H9b после ревью задачи — по публичному `register` |
| suite | `register_all` без `getattr` | новый тест + `test_register_all_wires_observation_...` | то же | регрессия 1.9m, найдена в окне |

## Числа на ветке

- Тесты задачи и швы (gate light): 63 зелёных.
- Мутанты ревью ветки M1 / M2: красных 2 / 1.
- Окно heavy 15:43–16:07, HEAD `98dfe2d09`:
  - `validate.py` — 0 ошибок, 0 предупреждений;
  - `multiprocess_prototype/backend/tests` — 237 зелёных;
  - `backend_ctl/tests` — 797 зелёных, 70 пропущено;
  - framework suite — 12 045 зелёных, 4 красных, 1 ошибка (19 мин 46 с).
- Красные suite поимённо:
  1. `test_registering_introspect_commands_yields_exactly_the_known_ten` — регрессия 1.9m. Литерал теперь 11 имён, с причиной в тесте.
  2. `test_register_all_wires_observation_alongside_logger_stats_error` — регрессия 1.9m. Исправлено через `getattr`, добавлен тест и инъекция.
  3. `test_declarations_leak_order_independence` — следствие 1 и 2.
  4. `test_event_manager_exit::test_child_with_5000_unread_events_exits_within_2s` — не 1.9m: отдельным прогоном зелёный на main и на ветке. В реестре C-26.
  5. ERROR `test_f1_task10_acceptance::test_line_sim_overview_lists_robot` — не 1.9m, то же. В реестре C-27.
- C-4, C-5, C-20, C-24 в этом прогоне зелёные.

## Что осталось открытым / ненадёжно

- **H2 слабый** (`reply` напрямую). Сильная форма — `test_real_process_command_by_executor_name_runs_on_executor_thread`: ответ на потоке `pw1_keyed-io-0`.
- **H5 вероятностный.** 5 из 5 и 3 из 3 на этой машине; под другой нагрузкой число может отличаться.
- **Поздний `load_config` (M2)** ловит только тест наследника. Если команду регистрируют после `initialize()`, порядок не проверяется.
- **Процесс без корня** (`work is None`) оставляет живые рабочие потоки и `message_processor`. Воспроизведено ревью ветки. Это общий путь, не 1.9m; в продукте недостижим: корень открывается шагом 0 `initialize()`.
- **Хвост 1.9a.** При провале на втором рабочем потоке первый остаётся в `WorkerManager`. Найдено только чтением.
- **У `KeyedExecutor` нет публичного `stats()`**, поэтому `introspect.executors` отдаёт `unavailable = ["pending_depth", "running_keys"]`. Строка в `OPEN_QUESTIONS.md`.
- **C-23(а)** — гипотеза, опровергнута стражем H7 и инъекцией И11. C-23(б) — путь не найден, H8 записывает факт.
- **Developer видел матрицу инъекций** до того, как написал свои H-тесты. Вес их красноты ниже; опора — слепой набор.
- **Вложенный `test_declarations_leak_order_independence` после правки** — в коротком окне перед слиянием.

## Агенты (адрес — agentId)

| Роль | Модель | agentId | Итог |
|---|---|---|---|
| manager, спека | Opus | aa1804b3b28806f03 | 256k |
| reviewer, стадия 0 | Opus | a1d38a18307b59441 | р.2 APPROVED, 248k |
| tester, слепые R | Sonnet | aafdd75ddeec107cd | 10 RED, 154k |
| developer, Б1/Б2/правки | Sonnet | ad1e9ccc81ea9736b | 227k |
| tech-writer, документы | Sonnet | ac161af832a157163 | 129k |
| Haiku, матрица И1–И13 | Haiku | a4c5c91ddac05d40c | 101k |
| Haiku, перепрогон + радиус | Haiku | a2655c8ef07456a68 | 89k |
| reviewer, ревью задачи | Sonnet | a0daa68483cde5e56 | р.2 APPROVED, 254k |
| reviewer, ревью ветки | Opus | a3d64a7f625211f0a | р.2 APPROVED, 224k |
