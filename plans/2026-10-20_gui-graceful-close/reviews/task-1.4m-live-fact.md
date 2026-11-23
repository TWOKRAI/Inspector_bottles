# Task 1.4m — живая проверка пути PM → devices → PM для шага pre_stop (стадия 4)

Дата: 2026-11-09. Дерево: worktree op-1.4m, ветка feat/gui-close-1.4m, коммит f1f904d6e. Код не правился, не коммитился.

## Как запускалось
- Бэкенд: `python -m multiprocess_prototype.main recipes/robot_demo.yaml --headless` (`BACKEND_CTL=1`, `INSPECTOR_HEADLESS=1`, cwd = корень worktree, `PYTHONPATH` = корень worktree, основной .venv). Каждый прогон = отдельный старт и остановка (старт до готовности 2,5–3,0 с).
- Драйвер: `backend_ctl.driver.BackendDriver.system_shutdown(...)` из worktree (путь модуля проверен печатью). Опрос `supervision.status` делает сам драйвер (50 мс); обёртка писала снимки `system_stop` с метками времени. Скрипт: scratchpad/live14m/live_run.py, выводы R*.out там же, копия журналов PM — scratchpad/live14m/PM_logs_copy.
- Гейт `machine_gate.sh medium op-1.4m-live` — запуск прошёл (machine.lock в основной копии нет, код 0 везде).
- Состав процессов (supervision): ProcessManager, camera_0, devices, gui, robot. Камера не открылась (ERROR `capture.start: не удалось открыть камеру 0`), `vfd_belt` не подключён (носитель `robot_main` не подключён) — шум не по задаче, на pre_stop не влияет.

## Таблица прогонов
t_cmd — метка команды; INFO/WARNING — метки из журнала PM (messages.log / system.log).

| № | режим / override | elapsed драйвера | фазы `system_stop.phase` (снимков всего) | снимков с `pre_stop_step` | INFO `pre_stop: шагов` | WARNING шага |
|---|---|---|---|---|---|---|
| R1a | graceful, настоящий system.yaml | 0,533 с (PM ушёл +0,99 с) | pre_stop, children (8) | 1 (`devices.robot_park_all`, на +0,009 с) | 16:43:09,278 (t_cmd 09,270, +8 мс): «шагов 1 — события стопа после них» | нет |
| R1b | то же | 0,528 с (+1,15 с) | pre_stop, children (5) | 1 (на +0,019 с) | 16:43:30,706 (t_cmd 30,689, +17 мс) | нет |
| R1c | то же | 0,379 с (+0,87 с) | pre_stop, children, done (5) | 1 (на +0,011 с) | 16:43:36,762 (t_cmd 36,754, +8 мс) | нет |
| R2 | graceful, шаг `args:{timeout_s:0}, timeout_s:5` | 0,349 с (+0,85 с) | pre_stop, children (5) | 1 (на +0,016 с) | 16:44:37,131 (t_cmd 37,118, +13 мс) | 16:44:37,146 `pre_stop: шаг 'devices.robot_park_all' — ошибка ответа`; Δ от INFO = 15 мс. Параллельно в devices/busy.log 16:44:37,143 `Command 'robot_park_all' failed: None` |
| R3a | force, deadline 1,0 | 0,333 с (+0,84 с) | children (5) | 0 | нет | нет |
| R3b | force, 1,0 | 0,384 с (+0,84 с) | children (5) | 0 | нет | нет |
| R3c | force, 1,0 | 0,486 с (+0,93 с) | children (6) | 0 | нет | нет |
| R4 | graceful, `pre_stop: []` | 0,414 с (+0,87 с) | children (6) | 0 | нет (в журнале ни одной строки `pre_stop`) | нет |
| R5 | graceful, 2 шага (devices.robot_park_all 35 + no_such_process.x 3) | 0,495 с (+1,00 с) | pre_stop, children (7) | 1 (на +0,014 с) | 16:46:02,166: «шагов 2 — события стопа после них» | 16:46:02,191 `pre_stop: шаг 'no_such_process.x' — процесс не найден` (+25 мс от INFO); шага devices — нет. Стоп прошёл, rc=0 |

Во всех 9 прогонах код выхода бэкенда 0, `accepted=true`, `timed_out=false`, `pm_gone=true`. В force `deadline_at` = `started_at + 1,0` (по снимкам).

## Вердикты
- L1a — выполнено: 3/3 прогона с INFO `pre_stop: шагов 1` (+8…+17 мс после команды), 0 WARNING шага (grep по всем логам `pre_stop|park` после R1c — ровно 3 INFO-строки). Снимок с `pre_stop_step` в каждом прогоне — 1 (из 5–8). Elapsed 0,379–0,533 с — справочно: фазы `children` ≈ 0,3–0,5 с (рецепт `robot_demo`, процессы выходят быстро), не 5 с.
- L1c — выполнено: WARNING с причиной «ошибка ответа» через 15 мс после INFO (<1 с); причина не `timeout` (5 с не ждали). Настоящий конверт ответа ребёнка дошёл до PM и разобран.
- L2 — выполнено: в 3/3 force-прогонах нет INFO `pre_stop: шагов`, фаза `pre_stop` ни разу не принималась (все снимки `children`), elapsed 0,333/0,384/0,486 с ≤ 2,5 с. Порядок соблюдён: R3 после R1 (R1 дал маркер).
- L3 — выполнено: при `pre_stop: []` ни одной строки `pre_stop` в журнале, фаза `pre_stop` не принималась, graceful 0,414 с, rc=0.
- R5 (бонус) — выполнено: второй шаг дал WARNING «процесс не найден», стоп завершился.
- L1b (итог `park` робота до `process.stop devices`) и L4 (шаг, прерванный `force` посреди ходьбы) — НЕ проверены: нет v2-симулятора по TCP; у `robot_main` протокол `delta_universal3` (v1), ответ `skipped/not_v2` в журнал не попадает (успех молчит).

## Состояние репозитория и реестра
- `git status --short` в worktree после прогонов — пусто.
- `data/devices.yaml` до прогонов не существовало и после не создано — `device_list` снимать было нечего. `user_overrides.yaml` до не было; три временных создавал и удалял (после R2, R4, R5), после — отсутствует.
- Прогоны создали ИГНОРИРУЕМЫЕ git файлы; удалены мной: `data/documents.db`, `multiprocess_prototype/app.state.yaml` (содержал `pipeline: recipes/robot_demo.yaml` — состояние активного рецепта!), `multiprocess_prototype/app.yaml.lock`. Оставлен `logs/prototype_2/` (журналы прогонов, игнорируется git; до прогонов каталог был пуст) — удалить вручную, если мешает; копия PM-журналов в scratchpad.
- Остатки процессов: 0 (`ps` по `multiprocess_prototype.main|live_run.py|spawn_main` — 0 после последнего прогона); порт 8765 свободен (`lsof` — 0 строк).

## Что оставил открытым / ненадёжно
- Фаза `pre_stop` видна ровно одним снимком (+0,009…+0,019 с), следующий — `children` на +0,076…+0,085 с: шаг на v1 длится ≈ 60–70 мс. Опрос 50 мс могла бы пропустить и фазу короче; поэтому «pre_stop принималась» в R1/R2/R5 доказана, а «не принималась» в R3/R4 держится на 5–6 снимках с шагом ~60 мс и на отсутствии INFO в журнале — слабее первого, но журнал PM независим от опроса.
- Прямого свидетельства «devices выполнил `robot_park_all` и ответил `skipped/not_v2`» нет: успех молчит, в devices-журналах строки про park на успехе нет. Путь «PM → роутер → devices → ответ» доказан косвенно: снимок `pre_stop_step`, быстрый переход к `children` (не 35 с таймаута) и, главное, R2: devices выполнил команду и вернул отказ, PM разобрал его за 15 мс.
- `outcomes` драйвера: `devices: null` (unconfirmed) в 8 из 9 прогонов (`exited` только в R1c; в R2 не подтверждены все четыре ребёнка, в R1b — devices и robot). Это предел драйвера (транспорт PM закрывается быстро), но на реальных данных он частый — для GUI/подтверждения итогов не опора. Не расследовалось.
- Камера не открылась, `vfd_belt` не подключён — окружение macOS без железа; к pre_stop отношения не имеет, но robot_demo «без камеры/ПЧ» не воспроизводит рабочий стенд.
- Прогон «с v1-симулятором» не делался (по тексту 1.4m он убран: симулятор v1 ничего не меняет).
- Параллельно в соседнем worktree (op-1.4m-inj) шёл pytest через тот же гейт; конфликтов за порт 8765 не было.
