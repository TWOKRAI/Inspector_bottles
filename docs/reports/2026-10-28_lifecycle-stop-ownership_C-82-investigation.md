# C-82: кто держит выход дерева ≈ 5 с на `system.shutdown` (S5, `region_pipeline`)

Дата: 2026-10-28. Роль: investigator (read-only), сессия `inspector-bottles-aa`. HEAD основного дерева `17d7777c7` (main).
Код не менялся. Прогоны шли через гейт, в окне heavy (`request` → GRANTED → `release`).

## Итог

1. Последний живой процесс дерева — **сам `ProcessManager`**. Так было в 6 прогонах из 6. Это не `camera_0`:
   `camera_0` выходит раньше PM на 0,6–2,7 с.
2. PM не выходит, потому что `system.shutdown` пришёл, когда PM **ещё не закончил `initialize()`**. Остаток
   инициализации PM не проверяет флаг стопа. Это runtime-хук прототипа `configure_topology_engine`:
   `discover` 65 плагинов, по дороге грузится Hikvision SDK. Он идёт ещё 4,1–7,2 с после команды. Только
   после него runner доходит до проверки `stop_event`.
3. S5 стенда в прогонах 2–10 шлёт `system.shutdown` сразу после того, как `devices` стал alive. Полной
   загрузки он не ждёт. Поэтому каждый такой прогон попадает в это окно. Прогон 1 (рестарты + activate + 2,0 с)
   дал 2,92 с. R2-C (T1.10) ждал полную загрузку + 2,0 с и дал `pm_exit` 1,08–1,67 с.
4. Две фразы строки C-82 не подтверждены:
   - «PM не выходит сам, дерево сносит Job Object» — **неверно**. Строку `TerminateJobObject: дерево
     оркестратора снесено` спавнер пишет при **каждой** остановке, после `join` PM
     (`spawner.py:231` → `spawner.py:250` → `process_tree_guard.py:231`). В замере она идёт в ту же
     миллисекунду, что выход PM (+4,972 против +4,969). `did not stop in` — 0. PM выходит сам.
   - «значение ≈ `stop_process_timeout` 5,0» — **совпадение**. S5 идёт с override 8,0/8,0
     (`stand_l9.py:64-65`, `summary.json`: `stop_process_timeout: 8.0`). Примерно 5 с — это длина хвоста
     загрузки PM на этой машине, а не окно стопа.

## Метод

Пробник: скрипт `c82_probe.py` в scratchpad, вне репозитория. Он берёт только средства стенда из
`docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_l9.py`: `Backend`, `watch_pid_exit`
(OpenProcess(SYNCHRONIZE) + WaitForSingleObject, без psutil и tasklist), `wait_full_boot`, `pm_pid_of`,
`send_async`, `pm_msg`. Окна те же, что в S5 (override 8,0/8,0). Рецепт по умолчанию `region_pipeline`.

- Плечо **early** = как S5 прогоны 2–10: `Backend.start()` (выход — `devices` alive), сразу снимок
  supervision и `system.shutdown` (graceful).
- Плечо **warm** = как R2-C: `wait_full_boot` (строка `registration summary` PM) + 2,0 с, затем то же.
- PID каждого процесса берётся из снимка supervision. Для каждого — поток ожидания выхода. Лаунчер
  ждётся через `proc.wait`. Время отсчитывается от `t_send` (monotonic перед отправкой). Строка
  `System shutdown requested via command` в логе PM идёт через +0,005…+0,027 с после `t_send`, поэтому
  отсчёт от неё отличается не больше чем на 0,03 с.
- Плечи чередовались: early, warm, early, warm, early, warm. Повторов: 3 + 3. Логи процессов прогона —
  `<scratchpad>/c82/run1/runs/<arm>_<i>/logs/`, сырьё — `<scratchpad>/c82/run1/probe.json`
  (scratchpad = `C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/06552cd7-4f9e-4751-8346-c77d32de826d/scratchpad`).
- Машина под нагрузкой: перед окном свободно 1070 МБ ОЗУ, загрузка CPU 56 %. Прогон early_5 явно медленнее
  остальных (его дети выходили 3,7–7,3 с).

## (а) Таблица: процесс → выход, с от `system.shutdown`

Жирным — процессы, живые через 2,0 с.

| процесс | early_1 | early_3 | early_5 | warm_2 | warm_4 | warm_6 |
|---|---|---|---|---|---|---|
| devices | 0,891 | 0,375 | **4,266** | 0,672 | 0,860 | 0,469 |
| gui | 0,891 | 0,437 | **3,719** | 0,641 | 0,797 | 0,344 |
| preprocessor | 1,250 | 0,593 | **4,657** | 0,594 | 0,828 | 0,391 |
| region_splitter | 1,594 | 0,812 | **5,469** | 0,516 | 0,828 | 0,375 |
| process_negative | 1,813 | 1,031 | **5,422** | 0,547 | 0,828 | 0,438 |
| process_grayscale | 1,875 | 1,281 | **5,485** | 0,500 | 0,828 | 0,453 |
| process_flip | **2,141** | 1,500 | **5,860** | 0,563 | 0,828 | 0,391 |
| stitcher | **2,313** | 1,562 | **6,016** | 0,500 | 0,813 | 0,453 |
| camera_0 | **3,953** | **2,937** | **7,328** | 0,907 | 1,157 | 0,719 |
| **ProcessManager** | **4,969** | **5,609** | **8,047** | 1,625 | **2,110** | 1,344 |
| launcher (stand_backend.py) | **5,469** | **6,125** | **8,594** | **2,172** | **2,766** | 1,860 |

Разброс:
- early: PM — 4,97–8,05 с, лаунчер — 5,47–8,59 с. PM выходит на 0,72–2,67 с позже `camera_0`.
- warm: PM — 1,34–2,11 с, лаунчер — 1,86–2,77 с. PM выходит на 0,63–0,95 с позже `camera_0`.
- Лаунчер выходит через 0,50–0,66 с после PM во всех 6 прогонах.

Ранее сохранённых логов процессов для S5 нет. В `docs/reports/2026-10-28_lifecycle-stop-ownership_1.11-stand/`
лежат только `raw.json`/`results.md`/`summary.json`, каталогов `runs/` нет. Поэтому таблица собрана из
своих прогонов.

## (б) Где ждёт последний процесс (PM)

Лента early_1. Смещение — от `t_send`, строки из `ProcessManager/messages.log` и `launcher/messages.log`:

```
+0.005 PM   System shutdown requested via command
+0.044 PM   готовность будет объявлена в конце run() — после регистрации команд PM   <- последняя строка initialize() PM-базы
+0.310 L    system_stop_event взведён — инициирую остановку системы / spawner: Stopping system...
+1.213…+2.722 PM  дети running -> stopped (devices … stitcher)
+1.645 PM   S.h.sdk.bindings: Hikvision SDK загружена: MvCameraControl.dll               <- импорт плагинов в PM
+4.081 PM   PluginRegistry.discover: найдено 65 новых плагинов (всего 65)
+4.110 PM   Process initialized                                                            <- process_runner.py:420
+4.148 PM   Stop signal received                                                           <- process_runner.py:195
+4.257 PM   Process «ProcessManager» shut down successfully
+4.972 L    TerminateJobObject: дерево оркестратора снесено                                <- после join PM
+4.980 L    System stopped
```

early_3 и early_5 — та же последовательность:
- `discover` в +4,779 / +7,234;
- `Stop signal received` в +4,833 / +7,282;
- выход PM в +5,609 / +8,047.

В warm-прогонах строки `готовность будет объявлена…` после команды нет. `Stop signal received` идёт через
+0,065…+0,107 с.

Цепочка в коде:
1. `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:822-825` —
   `system.shutdown` взводит `_system_stop_event` и `stop_event` и возвращает ответ.
   Инициализацию это не прерывает.
2. `multiprocess_framework/modules/app_module/orchestrator.py:73-76` — `initialize()` = `super().initialize()`
   (заканчивается строкой `process_manager_process.py:368`), затем **`self._configure_runtime()`** (строка 75)
   и `_start_observability_watcher()`. Между ними флаг стопа не проверяется.
3. `multiprocess_prototype/orchestrator.py:46` → `multiprocess_prototype/backend/orchestrator_hooks.py:26`
   `configure_topology_engine`. В нём импорты сборки прототипа и **`app_discover(plugin_paths=…)`**
   (`orchestrator_hooks.py:78-80`). Здесь PM проводит 4,0–7,2 с после команды.
4. `multiprocess_framework/modules/process_manager_module/runner/process_runner.py:414-420` — только после
   возврата `initialize()`. Затем `_run_lifecycle` (`process_runner.py:188-195`) зовёт `run()` —
   `process_module.py:1320-1392`: старт воркеров, регистрация команд, heartbeat. Только потом цикл видит
   `stop_event` → `stop()`.
5. Лаунчер: `system_launcher.py:500-508` видит `system_stop_event` → `spawner.stop()` → `join(PM)`
   (`spawner.py:231`). Он ждёт ровно выхода PM. После — `kill_tree` (`spawner.py:250`), который пишет строку
   TerminateJobObject безусловно (`process_tree_guard.py:85`, `:231`).

## (в) Факт и гипотеза

**Факт.** Наблюдение: 6 прогонов этой сессии, разброс выше.
- В 6/6 прогонах последний процесс дерева приложения — PM. `camera_0` в 6/6 — последний из детей.
- В 3/3 early PM получил команду до конца `initialize()`. Строка `готовность будет объявлена…` идёт после
  `System shutdown requested`. Между ними и `Stop signal received` в логе PM только `discover` / Hikvision
  SDK / `Process initialized`.
- В 3/3 early `pm_pid_of` (introspect PM) вернул `None`: PM ещё не в `run()`, команды не зарегистрированы.
  В 3/3 warm он вернул PID.
- Лаунчер выходит сам через 0,50–0,66 с после PM. Строки `did not stop in` нет ни в одном прогоне.
- Строка `TerminateJobObject` есть в каждом прогоне, в том числе в warm с PM 1,34 с. Значит, по ней нельзя
  судить, вышел ли PM сам.

**Вывод по старым данным S5** (`s5_main/raw.json`), уверенность СРЕДНЯЯ-ВЫСОКАЯ, это не прямое наблюдение:
- В прогоне 1 `n_pids = 11`, в прогонах 2–10 `n_pids = 10`. S5 добавляет PID PM к снимку, только если
  ответил `introspect_status` (`stand_l9.py:1343-1352`).
- 10 вместо 11 — тот же признак «PM ещё не в `run()`», что у моих early (`pm None` в 3/3).
- Значит, все 9 «≈5 с» прогонов S5 на main и на ветке Ф — тот же механизм. Прогон 1 = warm-случай (2,92 с).

**Гипотеза, не проверена:**
- Почему `camera_0` в early выходит поздно (2,9–7,3 с). Вероятно, она тоже ещё в `initialize()`
  (Hikvision SDK, перечисление устройств). Её лог по шагам не разбирался.
- Что именно дорого внутри `configure_topology_engine`: `discover` 65 плагинов, импорт
  `multiprocess_prototype.backend.assembly`/`launch` или загрузка SDK. Профиля нет, есть только две строки
  лога по краям участка.
- Чем занят PM 0,55–0,95 с между последней строкой лога (`shut down successfully`) и выходом процесса, и
  лаунчер 0,5–0,66 с после PM. Возможные причины: финализаторы multiprocessing, выход интерпретатора,
  закрытие логгеров. Не исследовано.

## (г) Рекомендация fix-forward (без правки)

1. **Framework, `process_runner` / `ProcessModule`.** Стоп, пришедший во время `initialize()`, обязан
   прерывать подъём, а не ждать его конца. Минимум: в `run_process_function` после `initialize()` проверить
   `stop_event`/`system_stop_event`. Взведён — не звать `run()`, сразу идти в `stop()`/закрытие корня.
   Лучше: в `GenericProcessManagerApp.initialize()` (`orchestrator.py:73-76`) не входить в
   `_configure_runtime()` и `_start_observability_watcher()`, если стоп уже взведён.
   Ожидаемый эффект (оценка, не замер): выход PM в early ≈ выход последнего ребёнка + teardown PM. Это
   ~3,5–4,5 с на этой машине, а не < 2,0, потому что `camera_0` в early сама выходит в 2,9–7,3 с.
   Одного этого мало для порога S5.
2. **Prototype, `configure_topology_engine`.** `discover` в PM нужен только для `apply`/switch рецепта
   (`orchestrator_hooks.py:68-75`). Его можно вынести с пути загрузки: лениво при первом `apply_topology`
   или в фоновый поток с ожиданием в `apply`. Функция сохраняется (принципы владельца 2 и 3), загрузка PM
   короче на ~2,5–4 с. Решение — архитектурное, для lead/cto.
3. **Стенд и критерий.** S5 в прогонах 2–10 меряет «выход дерева во время загрузки», R2-C — «выход из
   установившегося состояния». Это разные величины. Даже в warm лаунчер выходит за 1,86–2,77 с: в 2 из 3
   прогонов это не меньше 2,0. Порог `< 2,0` до выхода лаунчера + опроса `tasklist` в S5 не проходит и без
   гонки загрузки. Что требует критерий (выход PM или лаунчера, с какой точки), решает владелец критерия,
   не этот отчёт. Ослаблять S5 под зелёный нельзя.
4. Поправить строку C-82 в `plans/queue/defects.md`: «PM не выходит сам, сносит Job Object» и «≈
   stop_process_timeout 5,0» не подтверждены (см. «Итог», п. 4).

## Что осталось открытым / ненадёжно

- **Повторов мало.** 3 early + 3 warm на нагруженной машине (ОЗУ свободно ~1 ГБ). Механизм один и тот же в
  3/3, но разброс времён (4,97–8,05 с для PM) — это наблюдение, не распределение. Для числа «до/после» нужна
  серия от 10 повторов на каждое плечо.
- **Перенос на старые 10 прогонов S5** — это вывод по признаку `n_pids = 10`. Логов процессов тех прогонов
  нет: стенд их не сохранил в отчёт.
- Хвосты teardown не разобраны: PM после последней строки лога (0,55–0,95 с) и лаунчер после PM
  (0,50–0,66 с). Они решают, достижим ли `< 2,0` в warm.
- Поздний выход `camera_0` в early не разобран по её логу (гипотеза «ещё в `initialize()`»).
- Эффект рекомендаций 1–2 — оценка, не замер. Реальная проверка: то же плечо early ×10 до/после правки,
  метрика — выход PM и лаунчера по `WaitForSingleObject`, плюс строка `Stop signal received` PM раньше
  `discover`.
- Почему в early дети выходят лесенкой с шагом ~0,5 с (`status changed … -> stopped` по 0,5 с) — не
  выяснено. Похоже на период опроса монитора, а не на реальное время выхода. Времена в таблице сняты по
  WaitForSingleObject, а не по этим строкам.

## Эскалация

```
ESCALATION -> cto
Question: S5 «выход дерева < 2,0 с» должен мерить выход из установившегося состояния (ждать полную загрузку, как R2-C) или выход во время загрузки (как сейчас в прогонах 2–10) — и до выхода PM или лаунчера?
Tried: 3 early + 3 warm прогона пробником на средствах stand_l9.py; early: PM 4,97–8,05 с (ждёт конца initialize: configure_topology_engine/discover), warm: PM 1,34–2,11 с, лаунчер 1,86–2,77 с.
Blocked on: выбор критерия определяет, какая правка закрывает C-82 (прерывание init стопом / ленивый discover / хвост teardown).
Files: multiprocess_framework/modules/process_manager_module/runner/process_runner.py, multiprocess_framework/modules/app_module/orchestrator.py, multiprocess_prototype/backend/orchestrator_hooks.py, docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_l9.py
```

memory hits: `scripts/memory/search.py shutdown boot initialize discover tree exit` → 8 файлов, по теме C-82
ни одного (ближайший — `feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop.md`, про плагин, не про PM).
