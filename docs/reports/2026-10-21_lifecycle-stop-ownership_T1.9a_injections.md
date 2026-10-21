# T1.9a — матрица инъекций И1–И12: прогнозы (до прогона) и факт

Лид полосы Ф, сессия inspector-bottles-48, 2026-10-21. Код — `8e7cf6a7a` (ветка `feat/lifecycle-keyed-executor`).
Прогнозы записаны и закоммичены **до** прогона; раздел «Факт» заполняется после окна сырым выводом
(`scratchpad/inj_out/<id>.txt` сессии), вердикт — по каждому тесту поимённо.

## Набор файлов (каждый прогон — один раз, без `-k`)

Из `multiprocess_framework/modules`:
`worker_module/tests/test_keyed_executor_acceptance.py` (R), `worker_module/tests/test_keyed_executor_hazards.py` (H + contract),
`command_module/tests/test_command_executor_fork_acceptance.py` (R), `command_module/tests/test_command_executor_fork_hazards.py`
(H + contract), `router_module/tests/test_router_manager.py`, `router_module/tests/test_reply_success_honesty.py`.
База — тот же набор без инъекции: все зелёные, collected — числом в `base.txt`.

## Части (для окна)

- **Часть A — исполнитель (`worker_module/keyed_executor.py`):** И1, И2, И3, И4, И5, И11.
- **Часть B — развилка и роутер (`command_manager.py`, `router_manager.py`):** И6, И7, И8, И9, И10, И12.

## Прогнозы

«Красные» — полный ожидаемый список; всё остальное в наборе — зелёное. `?` — неуверенный пункт (тест-контракт, чьих
входов лид не читал): его исход записывается, но расхождение по `?` — наблюдение, не находка. Расхождение по
уверенному пункту — находка, разбор до слияния.

| # | Поломка | Красные (уверенно) | `?` | Почему |
|---|---|---|---|---|
| И1 | `submit` ждёт места вместо `executor_busy` | R6, `contract_executor_busy_warns_once_per_episode` | `contract_executor_refusal_reaches_initiator_as_one_reply` | отказа по потолку нет; `submit` блокируется |
| И2 | `_overlaps(x, y)` → `False`, если оба ключа не `None` | R1, R5, R6, R12, H1b | H2 | `{a}`-операции идут параллельно на 4 рабочих: порядок R1 рушится, очередь R5/R6 не копится (рабочие разбирают), R12 исполняет на месте при занятом `{a}`, H1b `{a,b}` стартует до конца родителя. Поправка к прогнозу стадии 0 (там R5/R6 не названы) |
| И3 | `serial` игнорируется | R3, R12b | H1a | при 4 рабочих `{b}` идёт параллельно `{a}` |
| И4 | `reply` повторно в ветке исключения `action` | R4 | — | H4 зелёный: обёртка CM ловит исключение сама, до исполнителя оно не доходит |
| И5 | `request_stop` не снимает очередь | R5, H2, `contract_stop_all_workers_rejects_queue` | — | ждущие не получают `system_stopping`; R11 зелёный (очередь пуста) |
| И6 | роутер не выходит до авто-ответа при `DEFERRED` | R7 | `contract_executor_refusal_reaches_initiator_as_one_reply`, `contract_targets_all_orders_after_earlier_keyed_command` | второй ответ (авто-ответ с `DEFERRED`) |
| И7 | `handle_command` без `reply` возвращает `DEFERRED` | R8, `contract_deferred_with_reply_delivers_once_and_never_returns_deferred_without_reply`, `contract_erased_executor_metadata_runs_inline_through_router` | — | стёртая строка `executor` → роутер зовёт без `reply` → `DEFERRED` уходит в авто-ответ |
| И8 | нет поля ключа → `key=None` | R9, `contract_key_missing_through_router_gets_one_auto_reply` | — | обработчик вызывается вместо отказа |
| И9 | ветка CM без исполнителя при переданном `reply` → `Thread(action).start(); return DEFERRED` | R10 | `contract_overwrite_command_makes_command_synchronous_again` | второй пункт R10 зовёт `reply=r` напрямую; роутер сам `reply` таким командам не передаёт — роутерные тесты зелёные |
| И10 | метрика длительности пишется при подаче | H3 | — | |
| И11 | рабочий берёт только голову `pending` | R2b | `contract_none_key_waits_for_earlier_and_holds_later` | `{b}` ждёт второй `{a}` |
| И12 | роутер передаёт `reply` всем командам | `test_router_manager.py` (тесты на `:1598`, `:1613` — `assert_called_once_with(msg)`), `test_reply_success_honesty.py` (TypeError подделки → error-конверт) | — | R7, R10 зелёные: настоящий CM принимает `reply` и игнорирует его без исполнителя |

## Факт

_(заполняется после окна)_
