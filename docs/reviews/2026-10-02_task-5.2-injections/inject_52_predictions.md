# 5.2 — предсказания до прогона (лид)
Ветка feat/transport-t52, HEAD b2ab22ff1. Наборы: F (cwd multiprocess_framework/modules) — test_actuation_scheduler.py, test_t52_plugin_context_scheduler.py, test_no_blocking_in_plugin_process.py (тестер), test_actuation_scheduler_hazards.py (автор); P (cwd корень) — Plugins/control/robot_control/tests (тестер + изменённые).
BASE: зелёный.
M1 missed-цель всё равно ставится и стреляет → красные: тесты missed у тестера (schedule→"missed", pending 0), robot missed. ≥ 2.
M2 стреляет дважды на окно (due + due) → красные тесты «ровно один выстрел» (тестер, авторская гонка 2000 целей). ≥ 2.
M3 tolerance записи игнорируется (tol = 0.020) → красные: границы tolerance у тестера (0.25), авторский «два плагина с разным допуском». ≥ 2.
M4 fired_items += 1 вместо count → красные: тесты fired_items с count>1, gap 1078. ≥ 1.
M5 фронт сломан (front = True) → красные: test_verdict_documents (документ на каждый reject). ≥ 1.
M6a time.sleep(transit) в process() → красные: страж на Plugins/ + p99 + t47d4 < 1 мс. ≥ 2.
M6b time.sleep(transit) в _actuate (не process/_process_*) → страж ЗЕЛЁНЫЙ (дыра покрытия стража), красные p99 и t47d4. Если страж зелёный — находка: страж охраняет имена функций, а не путь вызова.
M7 pending() всегда 0 → красные тесты pending у тестера и t47d4. ≥ 3.
M8 auto_start=False → красный тест настоящего WorkerAdapter/WorkerManager (выстрел ≤ 0.2 с). ≥ 1 (по параметризации 2).
M9 планировщик на ctx, не на services (setattr на self) → красные «один объект на два плагина», возможно гонка. ≥ 1.
M10 без замка get-or-create → красная гонка 8 потоков (тестер: с switchinterval 5/5). Может проскочить — тогда флейк, не находка.
M11 нет ветки unscheduled (capture_ts None → float(None)) → красные тесты unscheduled. ≥ 1.

## Итог прогона (лид, HEAD b2ab22ff1) — 12 из 12 по предсказанию
BASE: F `62 passed`, P `121 passed`.
| инъекция | F красных | P красных |
|---|---|---|
| M1 missed-цель ставится | 6 | 3 |
| M2 два выстрела на окно | 15 | 6 |
| M3 tolerance записи игнорируется | 4 | 0 |
| M4 fired_items += 1 | 2 | 0 |
| M5 фронт сломан | 0 | 11 (verdict_documents 4, flight_dump 2, t47d4_author 2, t52 2, wide_event 1) |
| M6a sleep в process() | 1 (страж) | 4 (p99 и др.) |
| M6b sleep в _actuate | **0 — страж зелёный** | 8 (p99, t47d4) |
| M7 pending() = 0 | 10 | 15 |
| M8 auto_start=False | 7 (настоящий WorkerAdapter/WorkerManager) | 0 |
| M9 планировщик на ctx | 5 | 14 |
| M10 без замка get-or-create | 1 (гонка 8 потоков) | 0 |
| M11 нет ветки unscheduled | 0 | 4 |
**Находка (M6b):** страж AST охраняет имена функций (`process`/`_process_*`), а не путь вызова: `sleep` в помощнике `_actuate`, который зовёт `process()`, страж пропускает. Свойство держит только p99-тест (живой замер). Вопрос ревьюеру: расширять страж на транзитивные вызовы внутри класса или принять p99 как охрану.

## Раунд 2 (HEAD 79a923432, правки ревью) — предсказания до прогона
M6b (тот же) → теперь КРАСНЫЙ страж `test_plugins_tree_has_no_sleep_in_process` (F ≥1) + p99/t47d4 в P как раньше.
M12 обход self-вызовов выключен (`for callee in []`) → красные 1–2 самотеста транзитивности (follows / shortest chain); страж по дереву зелёный.
M13 база сброса пустая (`self._sched_baseline = {}`) → красные 2 теста reset в test_t52_author.
M14 вызов `_warn_deprecated_alias` в process() снят → красные 2–3 теста алиаса (контракт 100 браков, author 100 pass, «не повторяется»).

## Итог раунда 2 (лид) — 4 из 4 по предсказанию
BASE: F `65 passed`, P `126 passed`.
| Заплата | F (фреймворк) | P (robot_control) |
|---|---|---|
| M6b sleep в `_actuate` | **1 — страж `test_plugins_tree_has_no_sleep_in_process` (дыра закрыта)** | 10 (контракт 8, t47d4 1, author 1) |
| M12 обход self-вызовов выключен | 1 — `test_guard_follows_self_method_calls_from_process_and_names_the_chain` | 0 |
| M13 база сброса пустая | 0 | 2 — оба reset в test_t52_author |
| M14 предупреждение алиаса снято | 0 | 3 — контракт 100 браков, author «не повторяется», author 100 pass |
