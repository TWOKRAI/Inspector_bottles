# Task 1.4 — часть драйвера (backend_ctl system_shutdown): отчёт исполнителя

Ветка `feat/gui-close-1.4d`, worktree `op-1.4d`, коммит `6fb83337e`. Часть PM не трогал.
Импорт из worktree: `backend_ctl.driver.__file__` = `.../worktrees/op-1.4d/backend_ctl/driver.py`.

## Что сделано
- `backend_ctl/driver.py::BackendDriver.system_shutdown` — `wait_timeout: float | None = None`, `pm_name`; `accepted = reply.get("accepted", reply.get("success"))`
  (timeout -> `None`; `already_stopping` -> опрос; прочий `False` и `wait=False` -> без опроса, `outcomes/unconfirmed None`, `timed_out False`).
- `backend_ctl/driver.py::BackendDriver._poll_shutdown_outcomes` (новый) — опрос `supervision_status` каждые 50 мс, `_leaf_result`,
  порядок такта: снимок -> «у всех итог» / `done` -> `connection_lost`; объединение последних не-null по имени; срок 20,0 -> `max(20, deadline_at - time.time() + 12)`
  от снимка; ожидание сокета `min(остаток, 3,0)`; часы только через `time.*`.
- `backend_ctl/mcp_tools.py` — `_system_shutdown` пробрасывает `wait_timeout`; описание ToolSpec без «outcomes=null», поля `outcomes/unconfirmed/timed_out`; схема `wait_timeout`.
- `backend_ctl/AGENTS.md` — строка `system_shutdown` (:147).
- Стражи: `test_system_shutdown_driver.py` (docstring, фикстура `_driver` с подменой `supervision_status`, `outcomes == {"a": None}`, `unconfirmed`, `timed_out`, :119 + `status_calls >= 3`,
  сигнатура и ответ `_RecordingDriver`), `_driver_author.py` (+ `unconfirmed is None`, `timed_out False`), `force_live.py:196` (`outcomes` dict + `timed_out is False`; `pm_gone is True` не тронут).

## DR 8 (test_system_shutdown_driver_outcomes.py, 1 тест, ячейки внутри)
| ячейка | результат |
|---|---|
| (а) объединение, нет ProcessManager, ждём сокет, pm_gone True | зелёный |
| (а') сокет не закрыт, wait_timeout 1,0: pm_gone False, timed_out False, elapsed <= 1,2 | зелёный |
| (б) разрыв: outcomes[b] None, unconfirmed [b], pm_gone True | зелёный |
| (в) wait_timeout 0,3: timed_out True, pm_gone False | зелёный |
| (г) already_stopping: опрос >= 2 снимков, accepted False | зелёный |
| (д) ответ-ошибка: без опроса | зелёный |
| (е) None: now+30 -> [42,0; 42,5]; now+1 -> [20,0; 20,5] | зелёный |
| (ж) wait=False: None/None/False, статус не вызван | зелёный |

Стражи: `test_system_shutdown_driver.py` 4 passed; `_driver_author.py` 2 passed; `test_system_shutdown_force_live.py` 5 skipped (без `--backend-live`, FL 9–10 собираются: 5 собранных); `test_system_shutdown_live.py` 2 skipped.
Соседи: `test_mcp_full_and_rules_doc_parity.py` 1 passed; `test_mcp_server_sdk.py` 51 passed.

## Прогоны
Гейт `machine_gate.sh light op-1.4d`, pytest по файлу, `PYTHONPATH=<worktree>`, `.venv/bin/python`. `ruff check` по 5 файлам — All checks passed; `ruff format --check` — 5 files already formatted.
`python scripts/validate.py`: ОШИБОК 2 — известные (память: теги; индекс BY-MODULE устарел). Новых нет.
Коммит: хук предупредил, что тема длиннее 72 знаков (92), блокировки не было.

## Что осталось открытым / ненадёжно
- Живой прогон (FL 9–10, L-smoke) не гонял: нужен стенд (`--backend-live`, heavy). Поведение против реального PM (форма `supervision.status`, `system_stop`, закрытие сокета) подтверждено только фейками DR.
- Допущение, что итог в записи — `stop_outcome` (так в тесте тестера). Часть PM должна публиковать `stop_outcome` в `supervision.status` и `system_stop.deadline_at`; с моей стороны это не проверено.
- Предел ADR-042/044: итог последнего медленного ребёнка может не успеть в опрос — имя уйдёт в `unconfirmed` (в docstring и AGENTS.md сказано).
- Снимок, где у PM нет ни одного ребёнка, кончает опрос сразу («у всех» по пустому набору). На реальном графе не бывает; тестом не закрыто.
- Ответ `{"success": False}` без `error`/`reason` читается как отказ (`accepted False`, без опроса). Это моё прочтение DESIGN 3; PM-часть может иначе отвечать на повтор `graceful`.
- Break-injection (мутации драйвера из ACCEPTANCE п. 11–13, 17–18) не гонял: это работа лида по своим предсказаниям.
- Кандидат-ошибка вне FILES: нет (чужие баги не замечены).
