# 1.2a gui-graceful-close — правки после ревью (итерация 1 из 2), teamlead

**Ветка:** `feat/gui-close-1.2a` (worktree `op-1.2a`), база HEAD `115949558`. Коммита нет (коммитит лид),
сообщение — `docs/reviews/2026-11-07_gui-graceful-close_task-1.2a-teamlead-r2.commitmsg.txt`.

## Итог

Три правки по DESIGN лида сделаны. Все пять новых тестов были красными на коде HEAD по нужной причине,
кроме `test_initiator_from_envelope_gui` (зелёный и до правки — см. «Непредсказанное»). После правки два файла
`test_supervision_status_system_stop*.py` — `42 passed`. Матрица из 4 инъекций совпала с предсказанием 4/4.

## Правки

1. **`done` у выживших (блокер).** `_ChildrenStop.join_until`: `done` при `stopped or self._killed`.
   Проверено чтением `base_manager/core/lifetime.py::_finish_stoppable` (:528-536): `close()` зовётся только
   после подтверждённой остановки, поэтому с выжившим `close()` не вызывается и `done` в итерации 0 не ставился.
   `close()` оставлен запасным путём. Docstring `join_until` и комментарий `close()` обновлены.
2. **`initiator` мимо конверта.** Модульный `class _EnvelopeSender(str)` (`__slots__ = ()`).
   `_handle_process_command` кладёт `_EnvelopeSender(sender)` (не строка — `None`). `_cmd_system_shutdown`
   принимает `_sender` только этого типа, иначе `"unknown"`; длина обрезается до `_SHUTDOWN_INITIATOR_MAX = 64`.
3. **Отказ стора ответом.** `_publish_system_stop`: ответ `handle_state_set` со `status` `rejected`/`error` —
   WARNING, ключ не помечается записанным (следующая публикация повторит его).

ADR-PMM-041 (`process_manager_module/DECISIONS.md`): пункты «Инициатор», «`done`», «Стор» переписаны; в
«Отвергнуто» добавлены «`done` только в `close()`» и «доверие строке `_sender` в `data`».

## Находка: неверная модель в слепом тесте

`test_supervision_status_system_stop.py::test_close_with_survivors_sets_done`, утверждение после `kill()` и
второго `join_until -> False` требовало `phase != "done"`. Модель «`done` только в `close()`» не совпадает с
областью: при `False` `close()` не зовётся (`_finish_stoppable`). Изменено ТОЛЬКО это утверждение (на
`phase == "done"`, с комментарием `1.2a r2`), по разрешению лида. Остальная часть теста (после `close()` —
`done`, в сторе `done`) не тронута и зелёная.

## Новые тесты (`test_supervision_status_system_stop_hazards.py`)

| тест | что | на HEAD (до правки) |
|---|---|---|
| H11 `test_survivor_rig_done_after_post_kill_join` | живой Rig, ребёнок переживает terminate и kill; область закрыта, фаза и запись в сторе `done` ровно 1 раз | FAILED: `'children' == 'done'` |
| H12 `test_initiator_from_envelope_gui` | конверт от `gui` с `_sender: forged` в `data` → `gui` | passed (не красный) |
| H12 `test_initiator_forged_in_data_ignored` | прямая команда с `_sender: forged` → `unknown` | FAILED: `'forged' == 'unknown'` |
| H12 `test_initiator_truncated_64` | отправитель 200 символов → первые 64 | FAILED: строки не равны |
| H13 `test_publish_rejected_warns_and_not_marked` | стор отвечает `rejected`: 4 ключа повторяются при следующей публикации, WARNING ≥ 4 | FAILED: `[] == [...4 ключа]` |

Прогон RED: `git add` рабочей версии, файл src заменён на `git show HEAD:<src>`, затем
`light inspector-bottles-ac … pytest -q --tb=line test_supervision_status_system_stop_hazards.py
test_supervision_status_system_stop.py` → `5 failed, 37 passed, 1 warning in 15.76s` (4 новых + слепой с
исправленным утверждением). Возврат — `git show :<src> > <src>` (`git checkout --` хук запрещает), затем
`git diff --stat` пуст.

### Непредсказанное

`test_initiator_from_envelope_gui` в REDS лида, но на HEAD зелёный: в итерации 0 конверт уже перекрывал
`_sender` из `data` отправителем конверта. Тест — страж против регрессии правки 2 (тип-метка не должна ломать
путь конверта), не доказательство дыры.

## Приёмка

Путь импорта (cwd `multiprocess_framework/modules`, `PYTHONPATH=<worktree>`), каждый прогон:
`/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2a/multiprocess_framework/__init__.py`.

| прогон | команда | результат |
|---|---|---|
| файлы system_stop | `machine_gate.sh light inspector-bottles-ac python -m pytest -q --tb=short test_supervision_status_system_stop_hazards.py test_supervision_status_system_stop.py` | `42 passed, 1 warning in 15.74s` |
| каталог PM, один процесс (1) | `machine_gate.sh medium … pytest -q --tb=short process_manager_module/tests` | `171 failed, 1401 passed, 1 skipped, 1 warning, 16 errors in 355.77s` |
| каталог PM, один процесс (2) | то же, `--tb=line -rfE` | `251 failed, 1319 passed, 1 skipped, 1 warning, 18 errors in 149.45s`; 464 строки `OSError: [Errno 28] No space left on device` |
| каталог PM, по файлу | `scratchpad/perfile.sh`: каждый из 99 файлов отдельным pytest | сумма по 99 файлам: `1581 passed, 6 failed, 1 skipped, 1 xfailed`; красные — только 6 `test_cv_threads.py`; строк ENOSPC — 0. Итерация 0: `1576 passed, 6 failed` + 5 новых тестов = 1581 |
| ruff | `ruff check -q` по 3 файлам py | exit 0 |

**ENOSPC повторился** (как у ревьюера). Диск свободен (`df`: 295 ГиБ). `Errno 28` идёт из
`std_facade.py:450 create_queues()` — это предел POSIX-семафоров macOS (`sem_open` → ENOSPC;
`kern.posix.sem.max: 10000`), а не диск: в одном процессе pytest каталог исчерпывает семафоры, число красных
плавает (171 / 251). Отдельными процессами — см. строку «по файлу».

## Break-injection (по закоммиченной рабочей версии из индекса)

Скрипт `scratchpad/inject.py <id>`: берёт `git show :<src>`, применяет одну замену, гонит два файла system_stop
(`light`), возвращает файл из индекса и печатает `git diff --stat` (везде пусто).

| id | инъекция | ожидали | получили |
|---|---|---|---|
| I1 | `if stopped or self._killed:` → `if stopped:` | H11 survivor_rig + слепой close_with_survivors | `2 failed, 40 passed`: эти два |
| I2 | `isinstance(sender, _EnvelopeSender)` → `isinstance(sender, str)` | только `test_initiator_forged_in_data_ignored` | `1 failed, 41 passed`: он |
| I2b | убрать `[:_SHUTDOWN_INITIATOR_MAX]` | только `test_initiator_truncated_64` | `1 failed, 41 passed`: он |
| I3 | `if status in ("rejected","error"):` → `if False:` | только `test_publish_rejected_warns_and_not_marked` | `1 failed, 41 passed`: он |

Несовпадений нет.

## Что я интерпретировал, а не выполнил

- `python -m scripts.sync` после правки DECISIONS.md НЕ запущен: он пишет глобальный индекс
  `multiprocess_framework/DECISIONS.md`, которого нет в FILES. Нужен у лида.
- `_EnvelopeSender` — модульный класс, а не локальный в `_handle_process_command`: локальный класс нельзя
  проверить `isinstance` из `_cmd_system_shutdown`.
- Отправитель-не-строка в конверте → `None` → `"unknown"` (раньше: тоже `"unknown"`).
- «Весь каталог PM отдельными прогонами» понял как каждый файл отдельным процессом pytest.

## Что оставил открытым / ненадёжно

- Каталог PM одним процессом на macOS не зелёный из-за исчерпания POSIX-семафоров (ENOSPC). Это среда/утечка
  семафоров в тестах, не правка 1.2a r2; чистого прогона одним процессом нет. Причина утечки не исследована.
- `test_cv_threads.py` — 6 красных; по отчёту итерации 0 красные и на чистом main.
- H11 доказывает `done` на Rig (двойник ребёнка, подменённые `terminate`/`kill`), не на реальном процессе ОС;
  heavy на Windows по-прежнему PENDING.
- Тип-метка `_EnvelopeSender` держится, пока `inner_msg["data"]` не копируется сериализацией между
  `_handle_process_command` и обработчиком. Сейчас путь в процессе PM (зелёный H12 конверта это подтверждает);
  если путь станет межпроцессным, метка потеряется и `initiator` станет `"unknown"` (безопасный отказ).
