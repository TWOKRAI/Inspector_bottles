# Проход «причина вместо симптома» (C6/C4/C10) — предсказания матрицы инъекций (лид, 2026-11-13; до прогона)

Код `c561d977d`. Запуск скриптом (worktree `rs-1.3-inj`, detached), откат копией. Набор: `test_run_refusal_keeps_reasons_hazards.py`, `test_run_state.py`, `test_run_state_auto_restart.py`, `test_run_state_restarting.py`, `test_run_auto_restart_hazards.py`, `test_run_auto_restart.py`, `test_run_apply_gate_hazards.py`, `test_requires_unmet_reason_hazards.py`, `test_requires_unmet_reason.py`.

| № | Инъекция | Предсказание |
|---|---|---|
| V1 | `_run_apply`: условие записи причин `reasons is not None and (code is None or new is not prev)` → `reasons is not None` (C10 снят) | красных ровно 2: `test_start_in_running_does_not_replace_status_reasons`, `test_start_in_fault_does_not_replace_status_reasons`; охранный (`refused_start_that_changes_state`) зелёный |
| V2 | то же условие → `reasons is not None and code is None` (отказ со сменой состояния причины не пишет) | красный `test_refused_start_that_changes_state_still_writes_reasons` (минимум он; допустимы соседние тесты `run_apply` на отказ со сменой) |
| V3 | `boot()`: запись пропуска дедуплицируется по имени плагина (`s[1] != plugin.name`) — ключ снова «имя» | красный ровно один: тест двух плагинов с одним именем в `test_requires_unmet_reason_hazards.py` |
| V4 | `_advance_restart_window`: `restart_window(inp)` без `replace(inp, down_since=self._run_down_since)` (окно не накапливается между тиками) | красные только среди `test_run_auto_restart_hazards.py` / `test_run_auto_restart.py` (окно, «только тик ведёт окно», независимые окна); `test_run_state*.py` (чистая функция) зелёные |
| V5 | `EvalInput.grace_s` умолчание 30.0 → 3.0 | красные в `test_run_state_auto_restart.py`, где окно проверяют без явного `grace_s`; если красных нет — дыра: умолчание чистой функции не закреплено литералом (ошибка предсказания фиксируется) |

Критерий: расхождение — находка; дыра закрывается тестом, не правкой предсказания.
