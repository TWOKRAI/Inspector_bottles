# Ревью Task 1.2a (gui-graceful-close), итерация 2 из 2, стадия 5 — reviewer

**Вердикт: APPROVED.** Ветка `feat/gui-close-1.2a`, HEAD `38333f9fc`. Код не менялся, ничего не коммитилось.
Тесты и репро шли через `machine_gate.sh light inspector-bottles-ac`, PYTHONPATH = корень worktree, cwd
`multiprocess_framework/modules`; путь импорта проверен: `.../op-1.2a/multiprocess_framework/__init__.py`.
Инъекции — на копии закоммиченного дерева (`git archive HEAD` в scratchpad), рабочее дерево не тронуто
(`git status` — только 3 untracked-файла исполнителя).

## Прогон приёмки

`pytest -q --tb=short test_supervision_status_system_stop_hazards.py test_supervision_status_system_stop.py`
→ `42 passed, 1 warning in 15.40s`.

## Пункты задания

### 1. done для выживших — закрыто
- Репро итерации 1 против нового кода:
  - `survivor_rig.py` → `system_stop dict after root close: {'phase': 'done', ...}`; записи стора
    `[phase children, mode, initiator, started_at, phase done]`.
  - `survivors_scope.py` (настоящая область, `join_result=False`) → журнал `... group.kill, group.join_until,
    store:system.stop.phase=done`; `phase after scope close: done`.
- Край-проверки на `_Light` (`tools/edge_light.py`):
  - `join_until -> False` до kill: `phase=children`, записей done 0 (ложного done нет).
  - после `kill()`: `join_until -> False` → `phase=done`, записей done 1; второй `join_until` + два `close()` → done
    по-прежнему 1.
  - путь «все дети остановились»: `join_until -> True` → done 1, `close()` ничего не дописывает.
- `kill()` зовёт только область (`_phase3`); `git grep` по `_killed`/`.kill()` вне тестов — других вызовов нет,
  значит `self._killed` не бывает True до фазы 3.
- Гонка: `stress.py` (300 итераций, команда + корень + 2 опросчика) → `bad = 0`; свой `stress_survivor.py`
  (то же + force-эскалация + путь kill/join False/close) → `bad = 0`, ровно одна запись done в сторе.
- Break-injection I4 (`if stopped or self._killed` → `if True`, «done на любом возврате join_until») — красный
  `test_done_phase_set_before_message_processor_and_state_store_close[child-needs-terminate]`: ложный done до
  смерти детей поймал тест порядка, не слепой.

### 2. initiator — закрыто
- `forge_sender.py` → `envelope -> gui`, `envelope-no-sender -> unknown`, `direct -> unknown`.
- Путь реальный: `_handle_process_command` зарегистрирован в роутере (`process_manager_process.py:349,355`),
  кладёт `_EnvelopeSender` → `command_manager.handle_command` → `_cmd_system_shutdown`. Тип не теряется на
  этом пути: инъекция I2c (убрать обёртку) → 7 красных (`test_initiator_from_envelope_gui`,
  `test_shutdown_command_records_initiator_from_real_sender[gui|backend_ctl]` и др.), штатный код — зелёный.
- Обрезка 64: I2b (убрать срез) → красный только `test_initiator_truncated_64`.
- `str(_EnvelopeSender)[:64]` — в стор уходит обычный `str`.
- Предел метки: любой код внутри PM-дерева процессов может импортировать приватный `_EnvelopeSender`; это метка
  происхождения от поля `data` клиента, не граница доверия. Через сокет backend_ctl/IPC-dict подделать тип нельзя.

### 3. rejected/error стора — закрыто
- `rejected.py` → `calls: 4`, после второй публикации `8`, `warnings logged: 8` (ключи не помечены, повтор есть).
- Шума нет: `_publish_system_stop` зовут только `_cmd_system_shutdown` и `_announce_phase`. При постоянно
  отвергающем сторе целый graceful-стоп даёт 16 попыток и 16 WARNING (`tools/noise.py`); 500 опросов
  `supervision.status` → 0 дополнительных попыток и 0 WARNING.
- Словарь статусов настоящего `handle_state_set` (`state_store_manager.py:181-214`): `ok` / `rejected` / `error` —
  совпадает с проверкой.

### 4. Изменённое утверждение слепого теста — оправдано
`mid["phase"] != "done"` → `== "done"` после `kill()` и второго `join_until -> False`. Оправдано: область не зовёт
`close()` при `False` (`lifetime.py::_finish_stoppable`:528-536, `_close_entries`), прежняя модель была неверной,
H11 на живом Rig это показывает. Часть теста после `close()` не тронута. Замечание F3 ниже: утверждение
«до kill done нет» теперь держит только param-тест порядка (I4 выше), в самом слепом тесте его нет.

### 5. Новые тесты H11–H13 — не вакуумны
| инъекция | предсказано красным | получено (`--tb=no`) |
|---|---|---|
| I1 `stopped or self._killed` → `stopped` | H11 + слепой close_with_survivors | `2 failed, 40 passed` — эти два |
| I4 → `if True` | ложный done до kill | `1 failed`: `done_phase_set_before...[child-needs-terminate]` |
| I5 убрать done из `close()` (запасной путь) | предсказал 0 | `42 passed` (путь недостижим для тестов) |
| I2 `isinstance(sender, str)` | `forged_in_data_ignored` | `1 failed`: он |
| I2b без среза | `truncated_64` | `1 failed`: он |
| I2c без обёртки | envelope-тесты | `7 failed` (список выше) |
| I2d убрать `and sender` | предсказал 0 | `42 passed` |
| I3 `if status in (...)` → `if False` | H13 | `1 failed`: `publish_rejected_warns_and_not_marked` |
| I3b только `("rejected",)` | предсказал 0 | `42 passed` |
| I3c убрать WARNING, оставить `continue` | H13 (по call_count) | `1 failed`: он |

H11 утверждает наблюдаемое: `child.is_alive()` (предусловие), `phase == done` в словаре, ровно одна запись
`("system.stop.phase","done")` в сторе. H12 forged/truncated красные по причине, `from_envelope_gui` — страж
(зелёный и до правки, исполнитель это указал).

### 6. Соседи PM
- `git grep` по `_ChildrenStop|system_stop|initiator|_handle_process_command|system.shutdown` в тестах PM: 24 файла.
  Прогнано по одному процессу, успели 6 (остальные не дождался, см. «Открыто»):
  `test_cv_threads` 6 failed / 9 passed, `lifecycle_command_classes` 23 passed, `lifecycle_fifo_acceptance` 10,
  `lifecycle_fifo_hazards` 13, `lifecycle_restart_reply` 2, `parent_death_hazards` 8 passed.
- 6 красных `test_cv_threads` воспроизведены на чистом `main` (`git archive main`, тот же набор из 6) — не от 1.2a.
- `multiprocess_framework/DECISIONS.md`: индекс несёт только заголовок ADR-PMM-041 (title не менялся в r2) —
  `scripts.sync` после правки текста ADR не требуется.
- `secrets_audit.py --root multiprocess_framework/modules/process_manager_module`: `total: 0`.

## Находки (не блокируют, F1–F4)

F1 [`process_manager_process.py:4927-4928` (done-условие — :4933), quality, minor] Нет группы детей (реестр упал в `_start`,
`_start_failed`): `join_until` выходит на `if self._group is None: return False` ДО строки с `or self._killed`.
Репро (`tools/edge_scope_nogroup.py`, настоящая область): `survivors ('pm-root/work/processes',)`, `errors
RuntimeError: registry boom`, `phase after scope close: children | store phase: children`. Стоп не доходит до
`done` — тот же класс дефекта, что блокер итерации 1, но только при сбое реестра (ERROR уже в логе и в отчёте
корня; потребитель ограничен `deadline_at`). Правка: объявить `done` при `self._killed` и в ветке `_group is None`
(в `join_until` до `return False`) + тест на этот путь. Спецификация этот путь не описывает — не блокер.

F2 [тесты, minor] Не охраняются: `("rejected","error")` — ветка `error` (I3b); пустой отправитель конверта →
`unknown` (I2d); запасной `done` в `close()` недостижим для тестов (I5). Правка: параметризовать H13 по
`status`, добавить конверт с `sender=""`. `close()` оставить (запасной путь, принцип «замораживать, не удалять»).

F3 [`test_supervision_status_system_stop.py:670`, quality, minor] Докстринг слепого теста всё ещё
«`done` только при закрытии области детей» — противоречит утверждению :678. Правка: переписать докстринг и
добавить `assert info()["phase"] != "done"` после первого `join_until -> False` (до `kill()`), чтобы тест держал
границу «done не раньше kill» сам, а не через I4-тест порядка.

F4 [тесты H13, minor] `_log_warning.call_count >= 4` не проверяет содержание WARNING (путь/статус). Инъекция I3c
он ловит (других WARNING в сценарии нет), но формулировку можно было бы закрепить.

## Что оставлено открытым / ненадёжно
- Регрессия соседей PM — только 6 из 24 файлов (каждый отдельным процессом; файлы идут по 10-40 с, цикл остановил
  по условию «долго не ждать»). Остальные 18 (`test_pm_responsive_during_children_stop`, `test_system_shutdown_force*`,
  `test_process_root_pm_*`, `test_process_manager_process` и др.) у меня не прогнаны; полный каталог одним
  процессом на macOS даёт ложный ENOSPC (POSIX-семафоры), это среда, не 1.2a.
- Живого процесса ОС нет: H11 — Rig с двойником ребёнка (`terminate`/`kill` подменены); heavy на Windows PENDING.
- `_EnvelopeSender` — метка происхождения внутри процесса PM; если путь станет межпроцессным (сериализация
  `data`), метка потеряется и `initiator` станет `unknown` (безопасный отказ). Подделка `sender` в самом конверте
  дочерним процессом (`msg["sender"]="gui"`) вне задачи и не проверялась.
- Слепой тест правился исполнителем (с разрешения лида); я проверил обоснование по `lifetime.py`, но не
  независимое подтверждение от `tester` не запрашивалось.
- Статические проверки (`sentrux check .`, `ruff`) не гонял: ruff — закрыт гейтом исполнителя (по его отчёту,
  exit 0), sentrux — изменений слоёв нет, но проверка не выполнена.
