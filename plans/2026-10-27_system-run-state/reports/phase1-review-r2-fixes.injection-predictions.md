# Правки ревью Ф1 раунда 2 (fix-B2/B2b) — предсказания инъекций (лид, 2026-11-15, ДО прогона)

Код: ветка `fix/run-state-phase1-review`, HEAD `fb2dfa008`. Каталог тестов: `multiprocess_framework/modules/process_manager_module/tests/`.

| № | Файл | Инъекция | Предсказание красных | Если иначе |
|---|---|---|---|---|
| K1 | `monitor/process_monitor.py` | в `mark_restarting` убрать строку `self._last_heartbeat.pop(process_name, None)` | ровно `test_heartbeat_between_baseline_reset_and_mark_is_not_recovery`; первый тест N1 зелёный (его прикрывает pop в `_try_auto_restart`) | факт: исполнитель уже прогнал — `1 failed, 6 passed`, совпало |
| K2 | `process/process_manager_process.py` | в `_run_auto_restart_flags` убрать условие protected: `if name not in protected:` → `if True:` | два теста `test_global_flag_protected_process_down_is_failure_not_restart_window` и `test_global_flag_protected_process_crash_in_running_goes_to_fault_at_once`; `test_global_flag_unprotected_process_down_gets_restart_window` зелёный | иначе — дыра в N2 |
| K3 | `monitor/process_monitor.py` | в `_admit_heartbeat` запись времени вынести из-под замка: строку `self._last_heartbeat[sender] = stamp` перенести после `with`-блока (перед `return True`) | **красных нет** (поправка лида до прогона: обёртка вызывает решение уже ПОСЛЕ возврата допуска, время к тому моменту записано; замок против настоящей гонки потоков детерминированный тест не проверяет) — ожидаемая дыра: атомарность под замком держится ревью и чтением, не тестом | если красные есть — модель неверна |

Ожидаемая дыра (не инъекция): тест `test_graceful_shutdown_from_running_without_steps_refused_executor_still_shuts_down` не отличает обход M1 от `finish` (сам исполнитель показал: инъекция `refusals=("INJECTED-none",)` его не краснит). Записано в OPEN_QUESTIONS.

## Результат (прогон исполнителем fix-B, 2026-11-15)

K1 — `1 failed, 6 passed`, красный ровно `test_heartbeat_between_baseline_reset_and_mark_is_not_recovery` (совпало). K2 — `2 failed, 54 passed`, красные ровно два теста protected (совпало). K3 — `56 passed`, красных нет (совпало с поправленным предсказанием: ожидаемая дыра). Подробности — `docs/reviews/2026-11-15_fix-B2.md`.
