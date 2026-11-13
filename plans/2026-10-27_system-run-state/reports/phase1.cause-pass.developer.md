# Ф1 run-state — проход «причина вместо симптома»: отчёт разработчика

Дерево `.claude/worktrees/rs-1.2`, HEAD `67c3fa2bf`. Не коммитил, `main` не вливал. Поведение не менялось, кроме C10 (отказ без смены состояния больше не пишет причины). Тесты — по одному файлу через `machine_gate.sh medium`, основной `.venv` + `PYTHONPATH=<корень worktree>`.

## Изменённые пути (коммитит лид)

- `multiprocess_framework/modules/process_manager_module/process/run_state.py` (C6)
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (C6, C10)
- `multiprocess_framework/modules/process_manager_module/tests/test_run_state.py`, `test_run_state_auto_restart.py`, `test_run_state_restarting.py`, `test_run_auto_restart_hazards.py` (C6, механически)
- `multiprocess_framework/modules/process_manager_module/tests/test_run_refusal_keeps_reasons_hazards.py` (новый, C10)
- `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py` (C4)
- `multiprocess_framework/modules/process_module/tests/test_requires_unmet_reason_hazards.py` (C4)
- этот отчёт. `phase1.known-compromises.md` — правка лида, не моя.

## C6 — объект входа `EvalInput`

`run_state.EvalInput` — frozen dataclass (`slots=True`): обязательные `expected, leaves, alive, now, stale_s` + контекст с умолчаниями прежнего поведения (`running=False, auto_restart, down_since, grace_s=30.0, given_up, restarting`). Сигнатуры: `evaluate(inp: EvalInput)`, `restart_window(inp: EvalInput)`; внутренние `_process_reasons(name, inp)` и `_restarting(name, silent, reasons, inp)` потеряли по 3–5 аргументов. В PM `_evaluate_run_readiness` собирает один `EvalInput`; для тика окно перезапуска дополняется `dataclasses.replace(inp, down_since=...)`, `_advance_restart_window(inp)` вместо 8 позиционных аргументов. Литералы ожиданий в тестах не менялись; правились только вызовы: обёртка `_evaluate` (test_run_state, test_run_state_auto_restart) и 4 прямых вызова.

Одна механическая оговорка: слепой параметр `down_since=None` («омитнут») в `test_run_state_auto_restart.py` обёртка теперь превращает в «ключ не передан» (в новом API «не передан» = умолчание, `None` — не значение поля); смысл и ожидание теста те же. Слепой тест по смыслу не правился, красных нет.

Прогон после C6: test_run_state 213, _hazards 23, test_run_state_auto_restart 20, test_run_state_restarting 10, test_run_auto_restart 12, _hazards 19, test_run_commands 20, test_run_ack 15 / 7, test_run_stop 11 / 13, test_run_admission_margin 7, test_run_apply_gate 11 / 11, test_run_restart_incarnation 11 / 15 — все passed.

## C4 — `_skipped_requires` без имени-ключа и без чтения под замком

Решение: **неизменяемый кортеж `((index, name, text), ...)`, заменяемый целиком**, читатель замка не берёт. Почему это проще и честнее теста на замок: (1) чтение ссылки на кортеж атомарно, читатель видит либо старое, либо новое значение целиком; замок вокруг `list(dict.items())` защищал только от «изменение словаря во время итерации», а этого у кортежа быть не может; (2) честный тест «замок нужен читателю» невозможен — наблюдаемого отличия нет (мутация h поэтому и не ловилась). Писателям замок оставлен: `boot()` дописывает (`(*old, new)` — чтение-замена), `_clear_skipped_requires` сбрасывает; это единственное место, где замок что-то сериализует, и он описан в комментарии. Ключ — индекс плагина в рецепте (`enumerate(self._early_plugins)`), поэтому два плагина с одним именем дают две причины.

Тест: `test_two_plugins_with_same_name_both_report_their_unmet_requires` (два класса с `name = "rh_dup"` и разными недостающими REQUIRES -> две причины в порядке рецепта, литералы). Мутация «ключ = имя» (дописывание с вытеснением записи с тем же именем) -> красный именно этот тест (1 failed, 6 passed). Параллельный hazard «снимки против повторных boot()» (был) остаётся зелёным: 7 passed в `test_requires_unmet_reason_hazards.py`; `test_requires_unmet_reason.py` 5, `test_plugin_orchestrator.py` 16 — passed.

## C10 — отказ без смены состояния не пишет причины

Сначала hazard (красный, 2 из 3): `test_run_refusal_keeps_reasons_hazards.py` — START в `running` при листе возрастом 12 с (удержание держит, допуск строже) и START в `fault` после прихода свежего листа: статус раньше менял причины (на «нет отчёта о готовности» / на пустые); охранный: отказанный START, сменивший состояние (`ready` -> `not_ready`), причины по-прежнему пишет. Правка — в точке записи, `_run_apply`: причины заменяются, только если `code is None or new is not prev`; без флагов и обходов, действует на все события, которые несут `reasons` (START, ack: `fault_stopping`, `no_fault`...). После правки 3 passed; радиус (23 файла PM, список в конце) — зелёный.

## C1 — `_admission_stale_s` после 1.7c: анализ (код не менял)

**Что делает порог.** Допуск (`ack`/START) требует лист не старше `stale_s − heartbeat_interval` = 10 с при `stale_s` = 15 с; удержание — до 15 с. Это ровно «один пропущенный heartbeat запаса»: лист, принятый в возрасте `a`, заменит следующий heartbeat не позднее чем через `interval`; если `a + interval ≥ stale_s`, лист может протухнуть до замены, и работа уйдёт в `fault` сразу после допуска. Число не подобрано, а выведено из интервала heartbeat.

**Что показывает A/B 1.7b (`1.7b.ab.stand.md`).** Вариант 1 (заморозка 18 с, CONT, ack, start) — 0 повторных fault из 16 на обоих коммитах, 0 отказов `ack`: порог не меняет исход этого сценария, а повторные fault прошлого стенда совпадали с перезапуском супервизором (то есть с классом, который закрыла 1.7c идентичностью воплощения). Вариант 2 (ребёнок заморожен, лист ~11 с, START): до 1.7b 8 из 8 принято, после — 8 из 8 отказано «нет отчёта о готовности», система возвращается в `ready` за 0,12–0,47 с после CONT. Значит порог закрывает **другое** событие: замороженный ребёнок БЕЗ решения супервизора (до 15 с супервизор ещё не объявил `unresponsive`).

**Что 1.7c закрыла и что нет.** 1.7c убрала допуск по листу воплощения, приговорённого к перезапуску (помеченное имя, чужой pid), — это и был исходный дефект «ack/START по листу старого воплощения -> fault после исполнения рестарта». Для замороженного ребёнка без решения pid тот же, пометки нет: 1.7c его не видит. Если убрать `_admission_stale_s`, ломается вариант 2: START принимается по листу 10–15 с замороженного ребёнка, `fault` через ≤ 5 с, оператор получает сначала `running`, потом аварию (8 из 8 до 1.7b). Эффект на повторный fault в сценарии «заморозка/CONT/перезапуск» порог не оказывает (вариант 1: 0 и 0).

**Вывод.** Порог перестал быть лечением исходной находки (её лечит 1.7c) и остался страховкой от узкого, но реального сценария — допуска по устаревающему снимку. Причина этого сценария — латентность снимка (до интервала heartbeat 5 с + период потока снимка 0,5 с), а не пороги: честное лечение — C1 из списка: внеочередной снимок по запросу PM перед допуском (`readiness.refresh` с дедлайном; не ответил — отказ), тогда лист при допуске моложе ~0,5 с, а гистерезис не нужен или остаётся запасом. До этого порог оставить: он дёшев, выведен из интервала heartbeat, зафиксирован A/B (8 из 8 против 0). Не удалять до появления refresh; в known-compromises формулировку C1 стоит уточнить: «страховка от допуска по устаревающему снимку; не лечение повторного fault (это 1.7c)». Стенд 1.7c (P) я не видел — вывод по коду и A/B 1.7b; если стенд P покажет ack/START по листу >10 с без решения супервизора и без повторного fault, довод не меняется (допуск пройдёт «по везению»).

## Гейты

- `ruff check` по `process_manager_module` и `process_module` — чисто; `ruff format --check` по всем 9 изменённым `.py` — чисто (в дереве есть 7 прежних файлов, которые format хотел бы перепечатать, — не мои).
- `python -m scripts.atlas check`: 0 new blocking, 0 new warning, 0 new info. `sentrux check .`: 43 правила, все проходят.
- Размеры: `run_state.py` 311 строк (было 311), `process_manager_process.py` 6488 (было 6507: C6 убрал ~23 строки, C10 добавил 4), `plugin_orchestrator.py` 831, `process_monitor.py` 1861 (не трогал).
- Прогон PM по файлам (все passed): test_run_refusal_keeps_reasons_hazards 3, test_run_state 213, _hazards 23, test_run_commands 20, test_run_ack 15 / 7, test_run_stop 11 / 13, test_run_admission_margin 7, test_run_apply_gate 11 / 11, test_run_auto_restart 12 / 19, test_run_state_auto_restart 20, test_run_state_restarting 10, test_run_restart_incarnation 11 / 15, test_boot_progress 6 / 10, test_process_monitor 76, test_process_manager_process 36, test_run_event_wiring 4, test_run_publish_snapshot_hazard 3; process_module: requires_unmet 5 / 7, plugin_orchestrator 16.

## Что я оставил открытым / ненадёжным

1. C4: у читателя замка больше нет, и это не доказывается тестом (наблюдаемого отличия нет) — довод только в комментарии и в этом отчёте. Писательский замок защищает «`boot()` дописывает против `_clear`»; параллельного boot/shutdown в жизненном цикле нет, так что и он страхует гипотетическое.
2. C6: `EvalInput` держит `expected` как `Sequence`, `leaves/alive/down_since` как `Mapping` — frozen защищает атрибуты, не содержимое; вызывающий не должен мутировать словари после сборки (в PM они собираются заново на каждую оценку).
3. C6: слепой тест `down_since=None` пришлось подогнать обёрткой (см. выше) — одна строка в обёртке, не в самом тесте; если лид не принимает, нужно решение, как слепой параметр «омитнут» выражается в новом API.
4. C10: правило `code is None or new is not prev` включает и отказ со сменой состояния (`ready` -> `not_ready`): причины пишутся. Оно не отличает «отказ, сменивший состояние, потому что причины его же и вызвали» от остального; сейчас это верно для всех строк таблицы переходов, но при новой строке, где состояние меняется по отказу без причин, нужно перечитать условие.
5. C1: стенд P (1.7c) я не видел; анализ — по коду и `1.7b.ab.stand.md`, не по живым числам; `readiness.refresh` не прототипировался — оценка его цены (RTT к замороженному ребёнку, дедлайн) не проверена.
6. Не трогал C11, C12 и `phase1.known-compromises.md`.
