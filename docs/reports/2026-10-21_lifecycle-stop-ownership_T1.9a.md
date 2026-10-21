# Отчёт: Task 1.9a — `KeyedExecutor` и развилка «на месте / исполнителю» в `CommandManager`

Полоса Ф, лид — сессия inspector-bottles-48, 2026-10-21. План — [`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md),
бриф — [`T1.9a.md`](../../plans/lifecycle-stop-ownership/tasks/T1.9a.md). Ветка `feat/lifecycle-keyed-executor`, голова `02c5f6a2b`
(перебазирована на `main 231e99cbf`). Подробности: реализация — [`_impl.md`](2026-10-21_lifecycle-stop-ownership_T1.9a_impl.md),
матрица — [`_injections.md`](2026-10-21_lifecycle-stop-ownership_T1.9a_injections.md).

## Что сделано

- `worker_module/keyed_executor.py` — `KeyedExecutor` (протокол `OrderedExecutor` в `worker_module/interfaces.py`, `Stoppable`):
  порядок по ключу-множеству, `None` = «все ключи», `serial`, потолок `max_pending=64` → `executor_busy`, `reply` ровно раз
  (в том числе при `BaseException` из `action` и из `reply` при снятии очереди), `inline_if_idle`, повторный вход,
  `should_reject` (и в цикле ожидания), постоянный пул SYSTEM-воркеров через `WorkerManager`. ADR-WRK-005.
- `CommandManager.register_command(..., executor=, key_from=, targets=)`, `handle_command(message, *, reply=None)`, сентинел
  `DEFERRED`, отказ `key_missing`, отказы регистрации, учёт исхода после исполнения и при отказе исполнителя. ADR-CMD-006.
- `RouterManager._dispatch_command` — `reply` только команде с `metadata.executor`; `DEFERRED` → без авто-ответа. ADR-RTR-015.
- Поведение PM не меняется: ни одна команда не помечена (это Task 1.9b).

## Числа

| Что | Итог |
|---|---|
| Стадия 0 (Opus, 2 раунда) | 18 + 9 правок брифа |
| Слепой тестер (Sonnet) | 15 тестов R1–R13, R2b, R12b: 15 RED до кода → 15 зелёных |
| Hazard + контракт (teamlead) | H1a–H11 + 21 контрактный; R/H + сторож логгера — 114 passed, 2 skipped |
| Матрица И1–И12 (`78ff43760`) | база 188 passed; 12/12 поймано; 1 находка (имя теста), 6 красных сверх прогноза — объяснены |
| Радиус (medium, `8e7cf6a7a`) | router 724, command 64, worker 96, PM 1229, console 105, frontend 658, backend_ctl 797 — 0 красных |
| `Services/robot_comm/tests` (heavy) | 1577 passed |
| Framework suite (heavy, `78ff43760`) | 2 failed / 11955 passed: logger-guard от ветки (`keyed_executor.py:127`, исправлено в `510af2ead`); C-20 (`test_t45b_plugin_ms_excludes_pre_hook_time` во вложенном прогоне, реестр) |
| `validate.py` на rebase | 0 FAIL / 0 WARN |
| `multiprocess_prototype/backend/tests` на rebase | 1 failed / 155 passed — `test_build_matches_snapshot[hikvision_letter_robot]` (C-16, реестр) |
| `sentrux check .` | All rules pass |
| Ревью задачи (Sonnet) | р.1 CHANGES REQUESTED (1 major: `BaseException`) → р.2 APPROVED |
| Ревью ветки (Opus) | р.1 CHANGES REQUESTED (2 блокера: непокрытые правки, `_reject_all`) → р.2 APPROVED |

## Сигнатуры (предупреждение координатору отправлено до слияния)

`handle_command` получил keyword-only `reply=None` (`CommandManager`, `ICommandManager`); `register_command` — `executor`, `key_from`,
`targets` с умолчанием `None`. Прежние параметры и умолчания на месте. Новый громкий отказ регистрации — сочетания с `executor`
и `key_from`/`targets` без `executor`; AST-скан репо: 0 вызовов с этими именами. Р2 подтвердила: в `device_hub` совпадений нет.

## Решения владельца (действуют, не пересматривались)

1. Конечное состояние — «отдел»: приёмный поток не ждёт; ждущие команды — в `KeyedExecutor` (2026-10-20).
2. Ключ извлекает `CommandManager` по `key_from`; развилка в `CommandManager`, не в роутере (2026-10-20).
3. Роли-потоки по видам почты отвергнуты замером CTO (2026-10-20).
4. Ревью задачи — Sonnet; Opus — стадия 0 Senior+, ревью ветки, живые дефекты (2026-10-21).
5. «Да» на слияние 1.9a — владелец через координатора, 2026-10-21 10:10.

## Что осталось открытым

- Для стадии 0 Task 1.9b (из ревью ветки Opus): верхняя граница `max_workers` у `_ready_gate_executor` (число детей меняет
  `topology.apply`); `inline_if_idle` проверяет только свободу ключа, не готовность ребёнка; `shutdown` внутри
  `_ChildrenStop.request_stop()` блокирует фазу 1 и может пробросить `BaseException` — обернуть в `try/finally`, чтобы стоп
  детей шёл всегда; `processed` после `DEFERRED` живёт на двух потоках (безопасно, пока обработчик не меняет `data`).
- Окно гонки «inline против `request_stop`» стрессом не задето (`refused=0`); прочие режимы — 300×12, 0 потерь и дублей.
- Нет метрики исхода у операции, завершившейся `BaseException`; конверт ошибки при сбое учёта внутри `action`
  (`{"success": False, ...}`) отличается от синхронного (`{"status": "error", ...}`).
- Тайминговые тесты (R2, R2b, R6, H2, H6, H7) гонялись по разу на тихой машине — под нагрузкой возможен ложный красный.
- Вывод `executor`/`key_from`/`targets` в карточку `introspect.capabilities` (`builtin_commands.py:866-870`) — вне 1.9a;
  перед правкой спросить координатора (там может быть правка полосы Д).
- C-17 (join → fanin молча) — в полосе Д вместе с C-16 (файлы отданы координатором).

## Агенты (адрес — agentId)

| Роль | Модель | agentId | Итог |
|---|---|---|---|
| reviewer, стадия 0 (2 раунда) | Opus | a1364d63a5c4addde | 18 + 9 правок |
| tester, слепые R | Sonnet | a8354e721c223973e | 15 RED, `ae29414ec` |
| teamlead, реализация + правки + скрипт матрицы | Opus | ac57a75b75f0f608f | `1ee00f9ea` … `02c5f6a2b`, ~340k |
| reviewer, ревью задачи (2 раунда) | Sonnet | a8631eab9f28159dc | APPROVED |
| reviewer, ревью ветки (2 раунда) | Opus | a43932ec9e8fc2922 | APPROVED |
