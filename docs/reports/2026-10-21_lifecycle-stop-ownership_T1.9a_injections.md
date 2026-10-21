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

Окно heavy 09:31–10:06, код `8e7cf6a7a` в отдельном detached worktree `keyed-exec-1.9a-inj` (`78ff43760`), скрипт
`scratchpad/inject_matrix.py`, сырой вывод — `scratchpad/inj_out/<id>.txt` сессии inspector-bottles-48 (`-q -rA --tb=line`,
без `-k`). После каждого отката `git status --porcelain --untracked-files=no` пуст.

**База:** collected 188, 188 passed (17,45 с).

| # | Итог прогона | Уверенные прогнозы | `?` | Сверх прогноза (красные) |
|---|---|---|---|---|
| И1 | 4 failed / 184 | R6 ✓, `busy_warns_once_per_episode` ✓ | `refusal_reaches_initiator` — зелёный | R4 (`:312`, точка «отказ» сделана через потолок), `contract_default_logger_name` (`:445`, WARNING потолка) |
| И2 | 7 failed / 181 | R1 ✓, R5 ✓, R6 ✓, R12 ✓, H1b ✓ | H2 — красный | R4 (та же точка «отказ» через потолок) |
| И3 | 3 failed / 185 | R3 ✓, R12b ✓ | H1a — зелёный | `contract_workers_are_permanent_system_workers` (`:313`, «рабочий должен быть ровно один») |
| И4 | 1 failed / 187 | R4 ✓ | — | — |
| И5 | 3 failed / 185 | R5 ✓, H2 ✓, `stop_all_workers_rejects_queue` ✓ | — | — |
| И6 | 3 failed / 185 | R7 ✓ | `refusal_reaches_initiator` — красный; `targets_all_orders` — зелёный | H4 (`:256`, «ответов: без исполнителя 1, с исполнителем 2» — H4 идёт через роутер) |
| И7 | 2 failed / 186 | R8 ✓, `erased_executor_metadata_runs_inline_through_router` ✓; **`deferred_with_reply_..._never_returns_deferred_without_reply` — зелёный ✗** | — | — |
| И8 | 2 failed / 186 | R9 ✓, `key_missing_through_router_gets_one_auto_reply` ✓ | — | — |
| И9 | 2 failed / 186 | R10 ✓ | `overwrite_command_makes_command_synchronous_again` — красный | — |
| И10 | 1 failed / 187 | H3 ✓ | — | — |
| И11 | 1 failed / 187 | R2b ✓ | `none_key_waits_for_earlier` — зелёный | — |
| И12 | 4 failed / 184 | `test_router_manager.py` ×2 ✓ (`mock.py:949 expected call not found`), `test_reply_success_honesty.py` ✓ (`:103`) | — | `contract_erased_executor_metadata_runs_inline_through_router` (`:423`, роутер отдал `reply` → CM отложил) |

**Вердикт лида.** Каждая из 12 поломок поймана хотя бы одним уверенно предсказанным тестом; каждый уверенный красный —
красный, кроме одного:

- **Находка (тест, minor):** `test_contract_deferred_with_reply_delivers_once_and_never_returns_deferred_without_reply`
  (`command_module/tests/test_command_executor_fork_hazards.py`) вызывает `handle_command` только с `reply` — вторая
  половина имени не проверяется. Прогноз лида строился по имени. Свойство «без `reply` никогда не `DEFERRED`» держит R8
  (красный под И7). Правка: имя по содержанию или вторая точка без `reply`.
- **Сверх прогноза — 6 красных, все объяснены по строке падения** (тест ходит к сломанному механизму вторым путём):
  точка «отказ» в R4 сделана через потолок (И1, И2); тест имени логгера ловит WARNING потолка (И1); число рабочих при
  `serial` (И3); H4 и `erased_executor_metadata` идут через настоящий роутер (И6, И12). Пробел модели лида, не дефект.
