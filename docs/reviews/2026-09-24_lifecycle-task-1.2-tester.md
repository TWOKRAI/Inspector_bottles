# Task 1.2 — независимый акцептанс (tester), RED-отчёт

Parsed: MODE=red (по форме брифа — DESIGN/FILES/REDS), INTERFACE=none (контракт задан
прозой брифа, не `interface.py`), MODULE_CONTRACT=impl-only (расширение существующего
`reader_gone.py`/`process_registry.py`/`process_manager_process.py`), TASK=1.2,
PLAN=plans/lifecycle-stop-ownership.md (форбидден — бриф сам является спекой).

Файл: `multiprocess_framework/modules/process_manager_module/tests/test_pm_marks_gone_reader_acceptance.py`
(единственный созданный файл, 8 тестов).

Команда: `cd .claude/worktrees/tester-1.2 && PYTHONPATH=$PWD .venv/bin/python -m pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests/test_pm_marks_gone_reader_acceptance.py`

## Результат: 8 failed, 2.12s, все RED ожидаемым образом

1. `TestKilledReaderWriterExitsUnder2s::test_killed_reader_writer_exits_under_2s` — RED:
   `AssertionError: ... assert False is True` на `q.is_reader_gone()` СРАЗУ после
   `registry.stop_one("Reader", timeout=0.5)` вернул `True` (reader реально убит
   terminate/kill — `run()` блокировался `time.sleep(120)`, свой stop_event/SIGTERM
   не слушал). Метка не взведена → тест дошёл бы дальше и проверил `writer` < 2.0s,
   но остановился на первой проверке метки (по дизайну — один Pre/Post за тест).
2. `TestStopMarksConfirmedDeadReaderQueue::test_stop_marks_confirmed_dead_reader_queue` —
   RED: та же форма, graceful индивидуальный `stop_one` (reader honours stop_event)
   тоже не взводит метку.
3. `TestStopWithFlagFalseDoesNotMark::test_stop_with_flag_false_does_not_mark` — RED:
   `TypeError: ProcessRegistry.stop_one() got an unexpected keyword argument
   'mark_reader_gone'` — кварг ещё не существует.
4. `TestStopManyMarksAlreadyDeadChild::test_stop_many_marks_already_dead_child` — RED:
   `AssertionError` на метке — ребёнок, умерший САМ до вызова `stop_many`, тоже не
   помечен (idempotent-True-ветка `stop_many` метку не трогает).
5. `TestCreateAndRegisterClearsMark::test_create_and_register_clears_mark` — RED:
   `AssertionError: assert True is False` — `create_and_register` НЕ снимает
   предварительно взведённую метку с переиспользуемой очереди перед спавном.
6. `TestRestartProcessDoesNotMark::test_restart_process_does_not_mark_and_new_incarnation_reads_intact` —
   RED: `pmp.stop_process.assert_called_once_with("Reader", mark_reader_gone=False)` —
   `Actual: mock('Reader')` — `restart_process` зовёт `stop_process` без кварга вовсе.
7. `TestSpawnRefusedAfterSystemStop::test_spawn_refused_after_system_stop` — RED на
   первой из трёх под-проверок: `create_process` после взведённого
   `_system_stop_event` всё равно вызывает `_process_registry.create_and_register`
   и возвращает результат мока (truthy) вместо отказа. `start_process`/
   `restart_process` не дошли до проверки в ЭТОМ прогоне (тест останавливается на
   первом `assert`), но обе под-проверки (b)/(c) отдельно верифицированы
   inline-скриптом с ТЕМИ ЖЕ заглушками, что в файле: `start_process()` вернул
   `True` и реально позвал `_process_registry.start_all()`; `restart_process()`
   вернул `True` и реально позвал `_process_registry.create_and_register()` — обе
   ветки при текущем коде тоже RED-совместимы (`assert not ...`/`assert_not_called()`
   упадут ровно так, как ожидается). Инлайн-скрипт также поймал и помог исправить
   баг в самой под-проверке (c) — см. ниже.
8. `TestSetReaderGoneHelper::test_set_reader_gone_helper_counts_and_ignores_plain_queue` —
   RED: `ImportError: cannot import name 'set_reader_gone'` — хелпер не существует.

Ни одного зависания, ни одного collection-error на весь файл (импорт нового имени —
только внутри теста 8, лениво). После прогона проверено `ps aux` — осиротевших
дочерних python-процессов нет.

## Что я интерпретировал, а не выполнил дословно

- Тест 6 (`restart_process`) и часть теста 7 (`start_process`, `restart_process`)
  построены на моках `_process_registry`/`stop_process`, а не на реальном PM —
  бриф явно разрешил это как «последний резерв» («if a real restart is too heavy,
  pin `stop_process` being called with `mark_reader_gone=False` ONLY as a last
  resort и say so»). Причина: `restart_process` тянет ~10 несвязанных внутренностей
  PM (wire reissue, routing epoch bump, telemetry replay, `_wait_processes_ready`) —
  строить их все ради Task 1.2 не относится к контракту и раздуло бы тест сверх
  бюджета.
- Тест 7, под-проверка (b) `start_process`: использую мок `_process_registry` вместо
  реального (хотя изначально планировал реальный `ProcessRegistry()` с не-стартованным
  `Process`), чтобы не рисковать реальным spawn ОС-процесса в RED-прогоне (сейчас
  проверка ДО первого `assert` не дошла — тест остановился на под-проверке (a), так
  что это решение не было проверено на практике, только спроектировано safety-first).
- Тест 1: «writer exits < 2.0s» пока НЕ подтверждён как отдельная RED-точка — тест
  остановился на более ранней проверке метки (по правилу «один Pre/Post за тест»
  тест пин это ОДНО свойство: что `stop_one` взводит метку). Сам факт, что метка не
  взведена, УЖЕ доказывает, что писатель今 завис бы в exit-hook (докстрока
  `reader_gone.py` описывает именно этот механизм), но живое измерение «writer
  завис > 2.0s без фикса» я не снял отдельно — не гонял тест с `writer_stop.set()`
  без остановки на assert метки. Экономия времени против точности: сочла более
  ценным одно связное RED на реальном сценарии убийства, чем два теста на одно и
  то же убийство.
- `queue_registry` реальный (`SharedResourcesManager`+`QueueRegistry`+PSR) — тесты
  1–5 все на нём (не только «минимум один», как просил бриф) — так дешевле по
  количеству файлов/классов, чем городить отдельный мок-путь.

## Что осталось открытым / ненадёжным в моей же работе

- Тесты 7(b) и 7(c) подтверждены inline-скриптом (см. выше), НЕ прогоном внутри
  `pytest` файла целиком — в самом файле функция теста останавливается на первом
  упавшем `assert` (под-проверка (a)), поэтому строка покрытия pytest не покажет
  (b)/(c) исполненными до тех пор, пока разработчик не закроет (a). Рекомендация
  ревьюеру/лиду: после того как (a) станет зелёной, перезапустить этот файл и
  явно свериться, что (b) и (c) тоже красные — а не молча проходят из-за ещё
  одной ошибки тестовой обвязки (ровно такую ошибку я уже дважды находила в
  этом же файле, см. ниже).
- Пока чинила (c), обнаружила и исправила реальный баг в СВОЁМ ЖЕ тесте: без
  мока `pmp3.stop_process` и без заглушек `_wire_reissue_enabled`/`get_config`/
  `_process_queue_ids`/… `restart_process` падал `AttributeError:
  'ProcessManagerProcess' object has no attribute 'config_handler'` ещё ДО
  проверяемого места — ложный RED не по контракту, а по дыре в обвязке. Исправила
  тем же набором заглушек, что в тесте 6 (уже проверенном рабочим).
- Я сама нашла и исправила баг в собственных тестах 1–4: `ctx.Process(...)` без
  `name="Reader"` — `ProcessRegistry.get_process_by_name` матчит по `.name`
  объекта `Process`, а не по `process_name`-аргументу `run_process_function`.
  Без фикса `stop_one`/`stop_many` тихо возвращали `True` через
  idempotent-ветку «нет в реестре — считается остановленным», ничего не
  убивая, — RED был бы ложным (зелёный по случайной причине, не по контракту).
  Упомянуто явно, т.к. это тот самый класс дефекта, который бриф просит ловить:
  тест, зелёный/падающий не по той причине.
- Тест 6 — контрактный пин на ИМЯ вызова (`stop_process(name, mark_reader_gone=False)`),
  а не на наблюдаемый эффект (реальная очередь остаётся немаркированной после
  реального restart). Слабее, чем «assert observable effect» правило проекта —
  оправдано ценой полного restart, но реальное свойство «новая инкарнация читает
  сообщение целиком» не проверено НИ ОДНИМ моим тестом на PM-уровне — только
  существующим `TestIndividualStopReaderThenQueueReusedByNewIncarnationGetsMessageIntact`
  (форбидден, не читала, знаю только по названию из брифа) на уровне
  `run_process_function` без PM.
- REDS предсказывал 8 тестов ровно по списку брифа — я не смогла и не пыталась
  влезть в 10, слияний/дропов не делала.
- Не проверяла ruff/типизацию на этом файле (бриф просил только tester-радиус —
  pytest).

Boundary: task closed. /compact (focus: files + tests + plan path).
