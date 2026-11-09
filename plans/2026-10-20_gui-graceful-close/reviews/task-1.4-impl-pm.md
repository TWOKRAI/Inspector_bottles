# Task 1.4 — часть PM: отчёт исполнителя (teamlead)

Worktree `op-1.4`, ветка `feat/gui-close-1.4`. Коммит кода: `d07132bbf`; второй коммит (вынос шага, документы) — см. `git log`.
Импорт из worktree: `PYTHONPATH=<worktree> python -c "import multiprocess_framework as m; print(m.__file__)"` →
`.../.claude/worktrees/op-1.4/multiprocess_framework/__init__.py`.

## Что сделано

- `process/pre_stop.py` (новый, lite): `PreStopStep`, `parse_pre_stop` (ошибки одной строкой на запись, поле — только
  известное имя из `loc[0]`), `run_pre_stop_step` (реестр → готовность → `request_async` → ожидание; срезы 0,05 с;
  синхронный отказ — по `threading.get_ident()` колбэка), константы `PRE_STOP_*`.
- `process_manager_process.py`: `_setup_pre_stop` (из `initialize`), `_pre_stop_cancel_flag` (ленивое),
  `_pre_stop_cancel_source`, `_pre_stop_rejected`, `_cancel_pre_stop`, `_lifecycle_rejected` (предикат `pm-lifecycle`),
  `_pre_stop_graceful_s`, `_exit_pre_stop_locked`, `_leave_pre_stop`, `_finish_pre_stop`, `_run_pre_stop`,
  `_run_pre_stop_step`, `_pre_stop_step_outcome` (обёртка); `_begin_system_stop(window_s=)`; `_set_system_stop_phase`
  при выходе из `pre_stop` = `_leave_pre_stop`; `_cmd_system_shutdown` + `_shutdown_graceful`, `_system_stop_phase`,
  `_set_stop_events`.
- Стражи PM-стороны: `test_system_shutdown_force.py:160`, `test_system_shutdown_force_author.py:87/92/114/124/132` —
  прежние литералы + новые поля. `:254` без правки.
- ADR-PMM-044, строки в ADR-038 (е) и ADR-041 (дополнение), отметка долга в ADR-042; `python -m scripts.sync`.
  README модуля (строка `system.shutdown`, абзацы «Итог стопа ребёнка» и «Шаги `pre_stop`»). `design.md:175` — сверка.

## Отклонение от буквы DESIGN 3 (сказать лиду)

Повтор `graceful` ВНЕ фазы `pre_stop` взводит события (идемпотентно) и несёт `message`. Причина — страж Task 0.2
`test_system_shutdown_force.py:254-255`: после `_ChildrenStop.request_stop()` (ход стопа есть, событий нет) graceful
обязан взвести события. В фазе `pre_stop` — как в брифе: ранний ответ без событий и публикации (SM 4 зелёная).

## Таблица

| Ячейка | Итог |
|---|---|
| SM 1–7 (`test_system_shutdown_pre_stop.py`) | зелёные: 7 passed (18,9 с); повтор 3 раза — 7/7 каждый |
| h1 нет `executor_manager` | зелёный; инъекция «нет ветки `manager is None`» → красный |
| h2 опоздавший ответ | зелёный; инъекция «общий слот ответа на шаги, без проверки `closed`» → красный |
| h3 гонка force/finally | зелёный; инъекция «`_leave_pre_stop` без проверки фазы» → красный |
| h4 двойник из `__new__` | зелёный; инъекция «флаг отмены без `setdefault`» → красный |
| контракт `test_pre_stop_contract.py` | зелёный (32 passed вместе с h1–h4: 36 passed) |
| стражи force + force_author | 21 passed |
| радиус PM (14 файлов: supervision/system_stop, lifecycle, stop_wave, root/stop_outcome, parent_death) | 198 passed (203,9 с), до и после выноса шага |

Команды: `bash ".../scripts/machine_gate.sh" medium|light op-1.4 .venv/bin/python -m pytest -q --tb=short <файл>`; по файлу.

## Проверки

- `ruff check -q multiprocess_framework/modules/process_manager_module/` — чисто; `ruff format` — без изменений.
- `scripts/validate.py` — 2 FAIL (известные «память: теги» и «индекс BY-MODULE»), других нет.
- `sentrux check .` в worktree — 1 нарушение `min_equality 0.5997 < 0.6000`. Не от правки: копия `git archive`
  до правки (`cd4961222`) — 6070, без нарушений; копия с правкой — 6069, без нарушений. Значит, нарушение дают
  неотслеживаемые файлы worktree. В основном дереве — 6010, без нарушений.
- G6 R4: новых `.kill()`/`.terminate()` нет (`git diff | grep -F`). Широкие `except Exception` — два, на границе шага и
  потока шагов (DESIGN 1), не в кадровых циклах. Тексты WARNING/ERROR — без значений `args` и ответа ребёнка.

## Что осталось открытым / ненадёжно

- Break-injection лида (1)–(16) по ACCEPTANCE не прогонял — это работа лида по закоммиченному коду.
- `lifecycle-guards`: «G4 threads without scope path»: 47 после SM, 186 после радиуса (тесты без `pre_stop`).
  Счётчик общий для старых тестов; что рабочие `pm-pre-stop` в нём есть — не исключено, не проверял.
- Тайминговые ячейки SM (0,05 / 0,1 / 0,3 с) зелёные 4 из 4 прогонов на этой машине; под нагрузкой не мерил.
- Причина `отменён` из словаря DESIGN 1 в коде не используется: отмена логируется INFO `прерван (<force|event>)`.
- Порог Σ сравнивается с допуском 1e-9 (сумма 1200 × 0,1 принимается) — в брифе допуска нет.
- Подсказка фазы `pre_stop` в `_pre_stop_graceful_s` читается без лока; при гонке «begin pre_stop ↔ смена фазы» срок
  не перебазируется (окно теоретическое, не воспроизводил).
- Живые FL 9–10 и драйвер — не мои (op-1.4d / окно лида).
