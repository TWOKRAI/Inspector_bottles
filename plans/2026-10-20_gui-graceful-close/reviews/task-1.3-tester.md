# Task 1.3 — отчёт слепого тестера (MODE: red)

Заголовок разобран: MODE=red, INTERFACE=none, MODULE_CONTRACT=public-api-change, TASK=1.3,
PLAN=plans/2026-10-20_gui-graceful-close/plan.md. Источник контракта: критерии приёмки и публичные имена из брифа
(interface.py нет, «testing against spec text only»). DESIGN/FILES/TRAPS задачи, reviews/*, чужие worktree и handoffs не читались.

Файл: `multiprocess_framework/modules/process_manager_module/tests/test_stop_wave_last.py` (12 прогонов pytest-ячеек:
10 REDS, REDS 2 параметризован двумя вариантами). Прогон 2 раза подряд: `11 failed`, результат тот же.

Команда: `machine_gate.sh medium op-1.3-tester .venv/bin/python -m pytest -q --tb=short <файл>`.

## Результат по тестам (до реализации все красные)

| REDS | тест | итог | причина (первая упавшая строка) |
|---|---|---|---|
| 1 | test_last_wave_child_not_signalled_until_main_done | красный | `AssertionError` стр. 212: stop_event last взведён на 1,00 с раньше выхода main (last: 0,002 с от старта) |
| 2 | test_hung_main_child_does_not_terminate_last_child[main-dies-on-terminate] | красный | `AssertionError` стр. 247: main не получил terminate (старый путь без окон: сигналов до kill() нет) |
| 2 | ...[main-ignores-terminate-killed-at-6] | красный | то же, стр. 247 |
| 3 | test_budget_adds_2s_only_with_last | красный | `ImportError` стр. 280: нет `LAST_WAVE_S` в core/stop_budget.py |
| 4 | test_blueprint_stop_wave_roundtrip_to_proc_dict | красный | `AssertionError` стр. 325: `proc_dict.get("stop_wave")` = None, ожидалось `'last'` |
| 5 | test_presentation_overlay_marks_gui_last | красный | `AssertionError` стр. 352: у `gui` после overlay нет `stop_wave` |
| 6 | test_no_last_children_keeps_old_budget_literals | красный | `TypeError` стр. 299: `stop_budget() got an unexpected keyword argument 'has_last'` |
| 7 | test_main_child_4s_then_last_child_2s_both_exited_through_pm_area | красный | `TypeError` стр. 404 (`WaveRig.__init__`, `stop_budget(..., has_last=True)`) |
| 8 | test_phase_last_wave_visible_between_last_signal_and_done | красный | `TypeError` там же |
| 9 | test_last_child_stop_deadline_null_until_signalled_then_from_own_signal | красный | `TypeError` там же |
| 10 | test_invalid_stop_wave_ignored_with_warning_without_value | красный | `AssertionError` стр. 384: в логе реестра нет WARNING про `stop_wave` |

REDS 7, 8, 9 падают ДО тела теста (на построении бюджета с `has_last=True`) — допустимый TypeError по брифу, но тело
в этом прогоне не исполняется. Чтобы показать, что обвязка живая и тела красные по смыслу, я прогнал эти три теста
скретч-скриптом (вне репозитория, `stop_budget` в модуле теста подменён обёрткой, игнорирующей `has_last`) на СТАРОМ
коде. Результат (3 failed, причины по смыслу):
- REDS 7: `AssertionError` стр. 489: stop_event last в 0,013 с от старта, раньше выхода main (4,0).
- REDS 8: `AssertionError`: опросов в окне [1,7; 2,9] — 0 (старый PM закончил стоп к ~1,5 с, фазы `last_wave` нет).
- REDS 9: `AssertionError` стр. 568: `stop_deadline_at(gui)` число, а не null до сигнала (gui сигналлен на старте).
Обвязка (двойник ОС-процесса + настоящий Rig PM + настоящие `create_and_register` / `children_stop` /
`supervision.status`) исполняется до конца без поломок, PM поднимается, root закрывается.

## Допущения о контракте (проверьте при реализации; не угадывались молча)

1. Бюджет `has_last=True` для PM в REDS 7/8/9 кладётся через `pm.attach_stop_budget(stop_budget(5.0, has_last=True))`.
   Если PM по контракту сам выводит `has_last` из реестра, это безвредно; если читает только присланный словарь —
   обязательно.
2. Класс чертежа в коде — `ProcessConfig` (в брифе `ProcessBlueprint`). REDS 4/10 идут через `SystemBlueprint.model_validate`
   -> `build_configs()` -> `cfg.build()` (там же `as_generic_config`); поле у процесса — `stop_wave`.
3. REDS 10: проверка «в логе реестра» — логгер `ProcessRegistry(logger=...)` (методы `_log_warning`); WARNING должен
   называть `stop_wave` и имя процесса (`worker1`), значения `late` в логе нет. Проверка идёт на пути
   `registry.create_and_register(name, class, proc_dict)` (как PM зовёт реестр с `proc_dict`).
   Если blueprint сам отсеет `late` и промолчит — реестр WARNING не напишет, и тест красный: в приёмке WARNING именно реестра.
4. REDS 9, окно имени `last`: в приёмке «сигнал last + окно имени», число окна не названо. Тест допускает 5,0 (окно g)
   ИЛИ 2,0 (`last_wave_s`) с допуском 0,3; ошибка «сигнал main + окно» (main сигналлен на 1,5 с раньше) даёт 3,5 / 0,5 и
   отвергается обоими. ВОПРОС ЛИДУ: какое окно у `last`-имени в `stop_deadline_at`? Когда ответ известен, сузить до одного
   литерала.
5. REDS 2: `D = старт + 7,0`; окно main 5,0 задаётся умолчанием реестра (`stop_budget(5.0)`).

## Что осталось открытым / ненадёжно

- **Не покрыто отдельным тестом:** публичные `wave: str` и `set_wave_listener(cb)` группы (колбэк `cb("last", D)` —
  смысл `D` в брифе неясен: срок `join_until` или новый срок; не угадывал; косвенно живёт в REDS 8 через фазу `last_wave`);
  поле `stop_wave` в ответе `supervision.status` (старый геттер возвращает `"main"` всегда); внешний join спавнера и
  `outer_s` с `last_wave_s`; `signalled_at(name)` на уровне реестра без PM (покрыто только через статус, REDS 9);
  `ChildProcessStop.poll(deadline)` не вызывается напрямую (бриф даёт его как имя, критерия на него нет).
- **Слабое место:** REDS 7/8/9 в красном состоянии падают в конструкторе (см. выше); содержательная красность
  подтверждена скретч-прогоном, не самим файлом.
- **Двойники:** ОС-процесс заменён двойником (патч `Process` в `process_registry`): настоящая гонка `terminate`/`kill`
  реального процесса, `exitcode`, reader-gone меток очередей и спавн-границы не проверены. Нужен стенд / тест на
  настоящем spawn-ребёнке (в `test_per_child_stop_window_acceptance.py` есть образец `LifecycleChild`).
- **Флак-риски (macOS):** допуски 0,1 с в REDS 1/2 (опрос группы 50 мс + опрос двойника 2 мс; запас ~0,04 с);
  REDS 8 окно [1,7; 2,9] зависит от задержки начала стопа PM (измерено ~0,01 с на этой машине; если исполнитель/монитор
  задержат сигнал main больше чем на ~0,2 с, `last_wave` начнётся позже 1,7 с — это допуск из приёмки, не расширял).
  REDS 8 требует >= 6 опросов в окне; REDS 9 спит 0,5 с и 0,3 с фиксированно (main живёт 1,5 с, last 3,0 с).
  Две прогонки подряд дали одинаковый результат, зелёной реализации для замера флака нет.
- **Слой:** REDS 5 импортирует `multiprocess_prototype.backend.launch` из фреймворкового теста (бриф назвал именно этот
  путь; прецедент: `test_dotted_process_name.py`). Импорт ленивый, внутри теста.
- **Нестабильные имена:** `WaveRig` трогает приватные места PM (`pm._process_configs`, `pm._incarnations`,
  `pm._routing_lock`, `pm._ensure_routing_state`, `pm._cmd_supervision_status`, `pm._system_stop_snapshot`) — как
  существующие `test_supervision_status_system_stop*.py`; переименование их сломает обвязку, не контракт.
- Break-injection своего файла не делался (по брифу — у лида).
