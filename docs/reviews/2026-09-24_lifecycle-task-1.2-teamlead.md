# Task 1.2 lifecycle-stop-ownership — отчёт teamlead (реализация)

**STATUS: DONE_WITH_CONCERNS** (два файла вне FILES, см. ниже)

## Что сделано (по DESIGN ведущего)

1. `shared_resources_module/queues/core/reader_gone.py` — `ReaderGoneQueue.clear_reader_gone()`,
   функция `set_reader_gone(queues, gone) -> int` (только `ReaderGoneQueue`, прочее пропускается);
   в docstring модуля написано, кто теперь ставит и снимает метку.
2. `process_manager_module/core/process_registry.py` — `stop_one` / `stop_many` / `stop_all` получили
   `*, mark_reader_gone=True`. Тела вынесены в `_stop_one` / `_stop_many` без изменений; обёртка маркирует
   имена с результатом `True` ПОСЛЕ подтверждающего join. `_set_reader_gone(name, gone)` — `queue_registry is None`
   → пропуск, исключение → WARNING, наружу не выходит. `create_and_register` снимает метку до `_create_process`.
3. `process/process_manager_process.py` — `stop_process(..., *, mark_reader_gone=True)` пробрасывает флаг в
   `stop_one`/`stop_all`; `restart_process` зовёт `stop_process(name, mark_reader_gone=False)`; хелпер
   `_spawn_refused_after_system_stop(what, name)` (getattr — у тестовых `__new__`-PM атрибута может не быть)
   стоит в `create_process` (→ `None`), `start_process` и первой строкой `restart_process` (→ `False`).
   `_topology_provision` не спавнит — проверки там нет; `_topology_start` идёт через `start_process`.
4. ADR-PMM-030 в `process_manager_module/DECISIONS.md`, строка-ссылка в ADR-SRM-016 «Границы»,
   `python -m scripts.sync` (обновил `multiprocess_framework/DECISIONS.md`), `scripts/validate.py` — 0/0.
5. `tests/test_pm_marks_gone_reader_hazards.py` — 5 авторских тестов.

## Вне FILES (вынужденно, механически)

- `process_manager_module/interfaces.py` — `IProcessRegistry.stop_all`/`stop_one` получили тот же kwarg (публичный Protocol).
- `process_manager_module/tests/conftest.py` — `MockProcessRegistry.stop_one`/`stop_many` принимают kwarg
  (без этого 18 тестов restart/wire_reissue/telemetry падали `TypeError: unexpected keyword argument`).
- `tests/test_process_manager_process.py:253` — ожидание `stop_one("TestProcess", 0.1)` → `..., mark_reader_gone=True`.

## Доказательства

- Tester + hazard: `pytest ...acceptance.py ...hazards.py` → `13 passed` (8 tester + 5 author).
- Радиус: `pytest -q process_manager_module/tests shared_resources_module/tests` → `1196 passed, 25 skipped`
  (база 1183 + 8 + 5).
- `ruff check -q` / `ruff format --check` на 7 тронутых .py — чисто; `sentrux check .` — `All rules pass`.
- Замер (скрипт на сценарии теста тестера №1, 5 прогонов на вариант): `mark=False` — писатель не вышел за 4 с
  0/5; `mark=True` — 5/5, 0.150 / 0.172 / 0.191 с.

### Самоинъекции (предсказание → факт; ведущий повторит независимо)

| Инъекция | Ожидал | Упало |
|---|---|---|
| A: метка до `_stop_one` | after_confirmed_death, survivor | ровно эти 2 |
| B: restart без `mark_reader_gone=False` | restart_never_exposes + tester #6 | ровно эти 2 (после переделки теста, см. ниже) |
| C: `except Exception` → `except ZeroDivisionError` | marking_failure | ровно он |
| D: маркировать все имена в stop_many | stop_all_straggler_survivor | ровно он |
| E: убрать снятие при рождении | tester #5 | ровно он |

Первая версия теста рестарта опрашивала метку фоновым потоком раз в 1 мс и под B **осталась зелёной**: окно
stop → create короче миллисекунды. Переделал на снимок метки на входе `create_and_register` (точка окна) — под B падает.
Шестой запланированный тест («create_and_register на новых очередях — no-op») удалён: ни одна правдоподобная
поломка его не красила (очередей на момент снятия ещё нет, исключение гасит try/except) — он был вакуумным.

## Что я интерпретировал, а не выполнил буквально

- «passes the flag to stop_one/stop_all» + «stop_all keeps delegating to stop_many with the default» — дал `stop_all`
  тот же keyword-only флаг (дефолт `True`, передаётся в `stop_many`).
- Отказ в `restart_process` стоит ПЕРВОЙ строкой — после системного стопа процесс не останавливается и не спавнится
  (его добьёт `stop_all` системного стопа, с меткой).
- Имена, отсутствующие в реестре, маркируются (по DESIGN «not in the process list» → True). Ловушка тестера
  (`get_process_by_name` матчит `Process.name`) значит: процесс, чьё `Process.name` не совпадает с именем в реестре очередей,
  получит метку, будучи живым. В PM `Process(name=name)` всегда совпадает — но это инвариант, не проверка.

## Что оставлено открытым / ненадёжно

- **Switch и rollback** (`_topology_stop_all`, rollback `stop_many`) идут с дефолтом `True` и потом пересоздают
  процессы; если имя осталось зарегистрированным, очереди переиспользуются — тот же класс «оборванный кадр в
  переиспользуемом pipe», что и принятый риск индивидуального стопа. Записан в ADR-PMM-030 → Task 3.2. Живьём не проверял.
- `_boot_create_and_start` и `_topology_create` зовут `create_and_register` напрямую, без проверки системного стопа.
  Boot идёт до стопа, `_topology_create` без `_topology_start` не запускает процесс — но Process-объект после стопа
  создаться может (и снимет метку при рождении!). Это окно: create после стопа снимет метку с переиспользуемых очередей.
  Не закрыто — вне списка DESIGN; кандидат для Task 1.4.
- Гонка «спавн прошёл проверку до взвода system_stop_event» проверкой не закрывается (check-then-act без лока) —
  остаточный риск из «Открыто до старта» остаётся за Task 1.4 (процесс-дерево).
- Тест «метка только после подтверждённой смерти» смотрит pid через `os.kill(pid, 0)` из фонового потока с опросом 1 мс;
  инъекцию A он ловит, но метку, поставленную между terminate и join (зомби), он тоже считает нарушением — это строже
  DESIGN, намеренно.
- Живой стенд не гонял (стадия ведущего).

## Итерация 2 — порядок метки в stop_many (находка живого стенда)

- Причина: `stop_many` маркировал после всей эскалации, писатели ждали в хуке метку мёртвого `gui` до terminate.
- Правка (`core/process_registry.py`): `_stop_many(names, timeout, mark_reader_gone)`, `confirmed_dead(name)` маркирует
  в момент подтверждения; уже мёртвые/отсутствующие — на шаге (a), до ожидания; graceful/terminate/kill —
  `wait_until(deadline)` опросом `STOP_POLL_S = 0.05` вместо последовательного join; общий дедлайн сохранён;
  выживший и `mark_reader_gone=False` не маркируются. ADR-PMM-030 п.1 дополнен.
- Новый авторский тест `test_stop_many_unblocks_writer_of_dead_reader_gracefully` (3 варианта: мёртвый читатель
  первым / последним / читатель выходит по stop и стоит последним). До правки: 3 failed, `exitcode=-15`
  (писателя терминировали), ~5.5 с на вариант (16.6 с на три). После: 3 passed, вызов теста 0.67 с включая 0.5 с подготовки.
- Инъекции: F (метка в конце эскалации) → 3 новых варианта + tester #4 (последний — артефакт инъекции: ранний
  `return` при пустом `procs` обходил вставленную в конец метку); G (последовательный join вместо опроса) → ровно
  `reader-exits-on-stop-listed-last`, как предсказано.
- Радиус: `1199 passed, 25 skipped` (1196 + 3). ruff/format чисто.
- Ненадёжно: опрос добавляет до 50 мс задержки на выход каждого graceful-процесса; `stop_all` с бессмертным
  фейком теперь реально ждёт 1+1 с (раньше join фейка был no-op) — тест 2.0 с. Живой стенд после правки не гонял.

## Итерация 3 — ревью REQUEST_CHANGES (TOCTOU рестарта + метка чужому воплощению)

- Правка (`core/process_registry.py`): отказ в спавне после системного стопа — в `create_and_register` (единая точка,
  `None`, метки не трогаются, в реестр ничего не пишется); проверки PM на входе оставлены как ранний отказ.
  `_mark_confirmed_dead(name, observed)`: метит, только если под именем зарегистрирован тот же объект / никого / не живой;
  `stop_one` и `stop_many` передают наблюдённое мёртвым воплощение. ADR-PMM-030: п.4 переписан, п.5 новый,
  «Принятый риск» исправлен (switch/rollback очереди не переиспользуют; окно микросекунд check→start и ребёнок после
  снимка имён `stop_all` — класс сирот, Task 1.4).
- Красный до правки: `test_system_stop_mid_restart_refuses_the_spawn` — `restart_process после системного стопа вернул True`;
  `test_mark_skips_name_now_held_by_a_live_incarnation` — `stop_one: метка на очереди живого преемника`.
- После: оба теста + прежние 16 → `18 passed`. Скрипт ревьюера: `restart_process returned: False`,
  `new incarnation spawned after system stop: False`, метка стоит на очереди без живого читателя.
- Инъекции: H (снять проверку в `create_and_register`) → ровно `mid_restart`; I (метить по имени без сверки) → ровно
  `live_incarnation`. Предсказание совпало.
- Радиус: `1201 passed, 25 skipped` (1199 + 2). ruff/format чисто, validate 0/0.
- Ненадёжно: `refusal warnings: []` в скрипте ревьюера — отказ реестра пишет WARNING только при `logger`, а у реестра
  скрипта его нет (в PM логгер есть, живьём не проверял). Сверка «тот же объект» идёт без лока: преемник, зарегистрированный
  между сверкой и `set`, получит метку — окно микросекунд, поверх него снимет `create_and_register` только если он ещё не
  прошёл снятие. Живой стенд после правки не гонял.
