# Ревью ветки `integ/lane-D` перед слиянием в `main` (Opus, совокупный дифф)

Ревьюер: `reviewer` (Opus), xhigh. Ветка `integ/lane-D` = `708491c84`. Сначала ревью шло против `main` = `ecf291411`, потом `main` ушёл до `4a73cdc9e` (W3 `28720c500`, run-state 2.3). `git merge-tree --write-tree integ/lane-D main` — rc 0, конфликтов нет. Отчёт сохранён лидом по ответу reviewer (у роли нет `Write`).

**Вердикт: APPROVED WITH CONDITIONS.** Блокирующих и крупных находок нет; условия относятся к записям в реестры и проверкам после слияния, код ветки не меняют.

## 1. Взаимодействие трёх правок

- **C-91 не меняет старт процесса.** Все `create_worker(..., auto_start=True)` (system_threads `message_processor`/`heartbeat_sender`, `KeyedExecutor` keyed_executor.py:152, WorkerPoolExecutor, plugins/base.py) идут по состоянию C — `True`, как раньше. `start_all_workers()` в `run()` (process_module.py:1490) для уже запущенных — состояние A, `True`. Новое одно: воркер в состоянии B (`ERROR` в окне авто-рестарта или `finally` обёртки) при старте процесса даёт WARNING «старт … отклонён»; `start_all_workers` результат игнорирует — косметика.
- **Замок и импорт (C-92 × C-91): цикла нет.** Под `_start_lock` — только `threading.Thread(...)`, `registry.update_status` (лист без колбэков, worker_registry.py:113-116) и `thread.start()`; ни одного импорта, лог вне замка.
- **Hammer 15 с** (4 потока: `start_worker`, `stop_worker(0.2)`, `restart_worker(0.2)`, `stop_all_workers(0.2)`; цель бросает с p=0,5, `restart_on_failure=True`; скрипт `scratchpad/scripts/repro_stop_all.py`):

| Дерево | Зависших | Операций | Живых потоков после финального stop |
|---|---|---|---|
| ветка | 0 | 8 063 435 | 0 |
| main | 0 | 6 849 154 | 0 |

- **`stop_all_workers` против `_restart_worker_internal`** (60 итераций: цель падает через 20 мс, `max_restarts=10**9`, `stop_all_workers(0.5)` через 0–120 мс, проверка потока через 250 мс):

| Дерево | Живой поток после stop_all | Макс. время stop_all |
|---|---|---|
| ветка | 0 из 60 | 0,10 с |
| main | 49 из 60 | 0,10 с |

  Остаётся окно в микросекунды: фаза 1 `stop_all` читает `info["stop_event"]` между проверкой E1 и подменой полей в `_spawn_thread_locked` → T2 с E2 живёт, `stop_all` ждёт до дедлайна и пишет `STOPPED` при живом потоке. Поток daemon; задержка shutdown ограничена `timeout`. Окно выведено чтением кода и за 60 итераций не попалось.
- **F3 с C-91/C-92 не пересекается** (только `recipe_devices.py` в прототипе).

## 2. Совместимость с main

- С `60e1deb42` до `main` во framework изменился только `process_manager_process.py` и его тесты. Поиск `start_worker|stop_worker|restart_worker|_restart_worker_internal` в добавленных строках — пусто.
- `start_worker` в `process_manager_process.py:3353-3370` — локальная переменная потока `ready-gate-*`, не API воркеров.
- `run-fault-stop` (`b74783413`) идёт через `_submit_run_sequence` (`pm-lifecycle` или одноразовый `Thread`); `start_worker`/`stop_worker`/`restart_worker` не зовёт. `False` в состоянии B до run-state не доходит.
- W3 (`28720c500`) в `Services/camera_device/session.py` добавил только `set_cycle`; пути `start_worker` не менялись.
- Слитое дерево `d6482defa` (`camera_device/tests` + `test_v2_real_worker_manager` + `worker_module/tests`): 321 passed, 1 failed — `test_plugin_base.py::test_потоки_база_не_создаёт_потоков_и_allowlist_G6_не_тронут`, артефакт метода (`git grep` в дереве из `git archive`).

## 3. Прогоны (через `machine_gate medium D`, последовательно)

`scripts.sync --check` rc 0; `validate.py` «Ошибок нет». База main — `git archive ecf291411`.

| Набор | ветка | main |
|---|---|---|
| worker_module/tests | 133 passed | 116 passed |
| robot_host test_v2_real_worker_manager | 3 passed | 3 passed |
| recipe/tests | 436 passed | 61 failed (артефакт архива: `git ls-files` exit 128) |
| frontend/forms + recipes | 319 passed | 3 failed: `test_qr_reader_sdk*` (чинит ветка) |
| tabs/services (Qt offscreen) | 443 passed | 416 passed |
| Services/camera_device/tests | 148 passed, 10 skipped | 148 passed, 10 skipped |
| process_module/tests | 3648 passed | 3624 passed |
| process_manager_module/tests, полный | 140 failed, 5 errors, 2210 passed | то же |
| 17 красных файлов PM, повтор по одному | 2 failed, 244 passed, ENOSPC 0 | то же |

- Полный PM-прогон: 141 строка `OSError: [Errno 28]` в `multiprocessing/synchronize.py` — исчерпан лимит семафоров (`kern.posix.sem.max=10000`); множества красных на обеих сторонах совпадают (`comm`: 0 и 0).
- Повтор: красные одни и те же и старые — `test_dotted_process_name::test_a5_recipe_set_has_the_literal_count_and_robot_demo` и `test_unapplied_metadata_check::test_m10_recipe_set_is_the_known_22` (23 рецепта вместо 22).
- **Новых красных относительно main нет.**
- `sentrux check .`: ветка — 43 правила, «All rules pass», Quality 6899; архив main — «All rules pass», 6965 (числа несравнимы: 9768 против 4901 файла).

## 4. Границы и состав

- Обратных импортов нет (`git diff main..HEAD -- multiprocess_framework` без `multiprocess_prototype|Services|Plugins`).
- Файлы четырёх слияний не пересекаются; `BY-MODULE*` правит только `63d6305db`. Запрещённых планом C-92 файлов нет.
- ADR-PM-060 и ADR-WRK-007 свободны (main и 162 локальные ветки). Номера C-91 и C-92 в `plans/queue/defects.md` на main не заняты.

## 5. Откат

Каждое слияние откатывается отдельно: `git revert -m 1 <merge>` (повторное влитие — revert-of-revert). Безопаснее всего F3 `31a1104a9`; затем C-92 `bf09e038a` (вернёт дедлок импорта); `63d6305db` (вернёт красные validate и qr_reader). Рискованнее всего C-91 `708491c84`: `Services/camera_device/session.py:344` опирается на честный `False`; без него возвращаются вечный `held` и два писателя H2.

## Условия слияния

1. Полный прогон `make gate` на слитом `main`; PM-набор гонять одиночно (лимит семафоров).
2. Записи в реестры: `defects.md` (C-91, C-92, F3; новые — `stop_all_workers` без `_start_lock` и D2d; дополнение к C-36); `OPEN_QUESTIONS` п. 1–9 из итогового отчёта полосы.
3. Передать К и Р2 устаревшие комментарии: `Services/camera_device/session.py:334-335` и `:534` (К); `Plugins/sim/robot_host/plugin.py:481-482`, `tests/test_v2_real_worker_manager.py:8,203-204` (Р2).
4. Стенд C-91 на реальной камере (драйвер mvs теперь в main): циклы `release/take` и shutdown.
5. Замер Ф2: стенды полосы Ф на `process_module/` с C-92 тем же набором.

Мелкое (не блокирует): `multiprocess_framework/DECISIONS.md:2655` — строка `process_module` говорит «ADR-PM-001…044», `sync --check` это не ловит; в итоговом отчёте полосы устареет фраза «ничего не влито… main d859338e0».

## Что осталось открытым / ненадёжно

- Окно `stop_all_workers` (микросекунды) выведено чтением кода и не воспроизведено; отсутствие попаданий его не исключает.
- База main собрана через `git archive`: тесты, которым нужен git (recipe 61, страж G6 в camera), красные по методу; страж G6 на слитом дереве не проверен.
- Полный PM-прогон упирался в ENOSPC: красные доказаны повтором 17 файлов (246 тестов), остальные 2210 прошли под давлением на лимит.
- FILES планов C-91 и F3 построчно не сверялись; сверены списки файлов слияний и запреты плана C-92.
- Без qex и codegraph (вызывающих искал `git grep`); qt-mcp не подключился — живые слоты F3 проверил sonnet-ревьюер.
- Проба семафоров ревьюера на доли секунды занимала до 9606 штук (могла задеть соседей); больше не повторять.
- Живая статистика C-92 слабая (2 из 240 против 0 из 202); замок в `_restart_worker_internal` чёрным ящиком не доказан; Windows и Orin не проверялись.
- Урок `.claude/memory/feedback_global_rollback_breaks_import_time_state.md` лежит во втором хранилище; видит ли его `search.py`, не проверялось.
