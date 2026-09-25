# Task 1.4 (lifecycle-stop-ownership) — отчёт teamlead

**Статус:** DONE_WITH_CONCERNS — 5 из 7 RED зелёные; 2 теста тестера, по моему замеру, не может пройти корректная реализация (ниже вход → наблюдаемый выход). Тесты тестера не правил.

## Что сделано (по DESIGN, три звена)

1. `launcher/process_tree_guard.py` — `ProcessLookupError` из `getpgid` → `pgid = pm_pid` → `killpg`; проверка «группа launcher'а» вынесена ПОСЛЕ обеих веток; `kill_tree` после сработавшего примитива всегда зовёт `_sweep_snapshot(fallback_procs)` (SIGKILL живым членам снимка, `is_running()` сверяет create_time, свой pid пропускается). Остаточный риск переиспользования pid назван в комментарии и в ADR.
2. `core/process_registry.py` — `TERMINATE_GRACE_S = 1.0`, `KILL_CONFIRM_S = 1.0`, поведение не менялось. `launcher/spawner.py` — `PM_TEARDOWN_MARGIN_S = 1.5`, `outer_stop_budget(g) = g + 1.0 + 1.0 + 1.5`; `shutdown_timeout` в конфиг PM = `stop_timeout`, если `orchestrator_config` его не задал; join на PM = `outer_stop_budget(бюджет PM)`; явный `stop(timeout=X)` → `outer_stop_budget(X)`.
3. `backend_ctl/harness.py` — `_union` снимков после готовности и в `stop()` перед shutdown (ранний снимок сохраняется); `_kill_orchestrator_group` — `killpg(pm_pid, SIGKILL)` последним шагом `_force_kill_tree` на POSIX (своя группа — пропуск). Выбор `killpg`, а не `process_iter`: один syscall против обхода всей таблицы, риск переиспользования pid одинаковый.
4. ADR-PMM-031 + `python -m scripts.sync` (одна строка индекса в `multiprocess_framework/DECISIONS.md`), `scripts/validate.py`: «Ошибок нет!».

## Бюджеты (числа)

- Внешний join PM по умолчанию: 5.0 → **8.5 с**; внутренний потолок эскалации 7.0 с.
- Худший случай spawner'а: 8.5 + terminate-join 3.0 + guard 0.5 = **12.0 с** < watchdog harness'а 15.0 с — не поднимал.
- Замер (scratch, launcher + зависший ребёнок, `stop_timeout=5.0`, после правки): `PM_DEAD_AT=6.31s EXITCODE=0 STOP_TOTAL=6.31s`.
- Обычный стоп (QuickChild, 3 прогона): до правки 0.24 / 0.27 / 0.22 с, после 0.25 / 0.24 / 0.23 с.

## Прогоны

- Оба acceptance-файла: `2 failed, 6 passed in 43.19s`.
- Весь радиус (8 файлов брифа + `test_pm_marks_gone_reader_*` + hazards): `2 failed, 114 passed, 3 skipped in 65.40s`; красные — только два теста ниже.
- `ruff check` чисто; `ruff format` применён к spawner.py; pyright на трёх файлах: `0 errors`, 5 предупреждений были и до правки.
- После последнего прогона `ps -eo pid,ppid,command | grep -E 'spawn_main|multiprocessing'` — пусто. (Во время промежуточного прогона там были resource_tracker и shm-читатель с родителем `9133 python -m pytest` — чужая сессия, не мой прогон.)

## Два теста тестера, которые считаю ошибочной моделью

1. `test_outer_wait_survives_past_inner_escalation_budget_6_5s` требует, чтобы PM был ЖИВ на t=6.5 с. В модели внутренняя эскалация = ровно 5+1+1 = 7.0 с. На деле `_stop_many` выходит из окна kill, как только смерть подтверждена (SIGKILL — миллисекунды). Наблюдение: «did not stop in 5.0s» 18:44:12.624 → «Force killing» 18:44:13.626, PM вышел сам через 6.31 с с exitcode 0. В том же прогоне `test_pm_completes_own_escalation_before_spawner_would_intervene` (exitcode == 0) зелёный. Пройти можно, только замедлив PM (держать окно kill целиком) — это изменение поведения stop_many, вне scope. Предложение: проверять exitcode == 0, либо ставить отметку на t=5.5.
2. `test_sigint_to_main_pid_leaves_no_orphan` строит `psutil.Process(hung_pid)` ПОСЛЕ выхода подпроцесса. После правки ребёнок уже мёртв → `psutil.NoSuchProcess: process PID not found (pid=8203)` на строке 285 теста; в логе видна эскалация PM «did not stop in 5.0s … Force killing process 'hung'». Пройти можно, только если ребёнок пережил stop(). Предложение: считать NoSuchProcess при построении за «ушёл», или строить psutil.Process до SIGINT.

## Hazard-тесты автора и break-injection (скрипт в scratch, предсказания записаны до прогона, все совпали)

| Инъекция | Упало |
|---|---|
| I1 убрать `shutdown_timeout = stop_timeout` в launch | `test_pm_receives_spawner_graceful_budget_by_default` |
| I2 `is None` → `True` (перетирать явный) | `test_explicit_orchestrator_shutdown_timeout_wins_and_drives_join` |
| I3 бюджет PM игнорирует orchestrator_config | тот же |
| I4 join = голый graceful (как до правки) | explicit_orchestrator, default_stop_join, explicit_stop_timeout |
| I5 `PM_TEARDOWN_MARGIN_S = 0` | literal, strictly_exceeds ×5, три join-теста |
| I6 проверка своей группы только в ветке успешного getpgid | `test_guard_never_killpg_launcher_group_when_leader_reaped` |
| I7 убрать `_sweep_snapshot` | `test_guard_sweeps_snapshot_member_outside_group_when_primitive_succeeds` |
| I8 убрать `pid != me` в sweep | `test_guard_sweep_skips_own_pid` |
| I9 вернуть `return True` на ProcessLookupError | `test_guard_never_killpg_..._leader_reaped` (побочно: по возвращаемому значению; главный сторож — A3 тестера) |

`test_guard_on_normal_path_does_not_sleep_when_group_empty` правку не сторожит — это страж стоимости штатного стопа (нет `sleep(0.5)` на пустой группе).

## Что я истолковал, а не выполнил дословно

- «Бюджет PM» для join = явный `shutdown_timeout` оркестратора, иначе `stop_timeout`; зеркалит чтение PM `get_config(...) or 5.0` (0 → 5.0).
- Явный `stop(timeout=X)` идёт через формулу буквально, даже если X меньше бюджета PM (тогда внешний join снова короче внутреннего; спасает guard по группе). Продакшн-вызовов `spawner.stop(timeout=...)` grep не нашёл.
- Досъём снимка в harness — сразу после `wait_until_ready`, до пробы драйвера.
- `_sweep_snapshot` — сразу SIGKILL, без SIGTERM: сюда доходят только выжившие после killpg SIGTERM+SIGKILL.
- Hazard-тесты harness'а в файл 5 не положил: `.sentrux/rules.toml` запрещает импорт framework → backend_ctl. Спросил лида; ответа до коммита не было.

## Что оставил открытым / в чём не уверен

- Два красных теста тестера — нужно решение лида (см. выше).
- **Звено 3 (harness) не сторожит НИ ОДИН тест.** Инъекцией: убран вызов `_kill_orchestrator_group` → `backend_ctl/tests/test_harness_no_orphans_acceptance.py`: `2 passed`; убраны оба `_union`-досъёма → `2 passed`. Оба harness-теста тестера зеленеют за счёт звеньев 1+2 (guard spawner'а бьёт группу после сбора PM). Звено 3 — второй предохранитель; чтобы его покрасить, нужен тест, где guard spawner'а не срабатывает (например, `launcher.shutdown()` зависает и отпускает watchdog). Авторский тест не написан: framework-тесты не могут импортировать backend_ctl, а отдельный файл в backend_ctl/tests не был в FILES — вопрос лиду отправлен.
- Окно переиспользования pid (pgid пустой группы) не измерял.
- Живой стенд `inspection_full` не поднимал — это этап лида.
- Windows не проверялся (sweep после Job Object — добавочный, путь Job не менялся).

## Итерация 2 (после решений лида)

### Блокер лида: снимок брал всех потомков процесса-хозяина

`spawner._snapshot_descendants` был `Process(os.getpid()).children(recursive=True)`, а `_sweep_snapshot` из первого коммита добивал его безусловно, поэтому штатный стоп убивал чужих детей хозяина. Исправлено: корень снимка — PM (`[PM] + PM.children(recursive=True)`, если PM уже нет — пусто); `_kill_via_psutil` берёт только снимок, без `children()` хозяина (тот же дефект был в старом fallback-пути). Скрипт лида `bystander.py` после правки, 3 прогона: `STOP=0.62s / 0.22s / 0.61s`, `BYSTANDER_ALIVE=True`, 0 трассировок `KeyError: '/mp-'`. `_subtree` в harness строит снимок от PM (`psutil.Process(orchestrator_pid)` + потомки), killpg бьёт только группу PM, так что host-wide шаблона в harness нет.

### Break-injection (предсказания записаны до прогона, все совпали; прогон на обоих hazard-файлах, 23 теста)

| Инъекция | Упало |
|---|---|
| J1 harness: убрать `_kill_orchestrator_group` | `test_group_member_absent_from_snapshots_dies_via_killpg` |
| J2 harness: убрать досъём после готовности | `test_setsid_child_dies_via_post_readiness_snapshot` |
| J3 harness: убрать досъём в `stop()` | `test_late_setsid_grandchild_dies_via_stop_refresh` |
| J4 harness: `_union` теряет ранний снимок | `test_setsid_child_dies_via_post_readiness_snapshot`, `test_union_keeps_early_entries_first_and_drops_duplicates` |
| J5 harness: убрать защиту своей группы | `test_group_sweep_never_targets_own_group` |
| J6 spawner: снимок от хозяина | `test_normal_stop_leaves_host_bystander_alive`, `test_hung_child_stop_leaves_host_bystander_alive` |
| J7 guard: fallback добавляет детей хозяина | `test_psutil_fallback_does_not_touch_host_children` |

Радиус после итерации 2: `2 failed, 122 passed, 3 skipped in 82.10s`. Красные — те же два теста тестера, их правит лид.

### Что по-прежнему не сторожится

- Ветку `ProcessLookupError` в `_kill_orchestrator_group` и `killpg` на уже пустой группе не проверяет ни один тест.
- Сценарии T1/T3 в harness держатся на паузе 2.5 с: внук должен родиться после досъёма по готовности. Если это не так, срабатывает предусловие («сценарий вакуумен»), а не ложная зелень.
- Что в T2 ребёнка нет в раннем снимке (сразу после `launcher.start()`), проверено только косвенно: J2 его покрасил.
- Окно переиспользования pid не измерялось; Windows не проверялся.
