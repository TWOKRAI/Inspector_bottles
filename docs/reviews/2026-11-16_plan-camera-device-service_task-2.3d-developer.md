# Task 2.3d, developer: `_ensure_port`, `list_devices`, `describe_params`, `trigger_software`, сторож `call`

Дерево `cam-2-3d-dev`, ветка `feat/camera-2-3d`, база `2958ae084`. Не коммитил (по брифу). Итерация 1 из 2.
Путь импорта (из того же cwd, что pytest): `multiprocess_framework/__init__.py` и `Services/camera_device/__init__.py` лежат внутри `.claude/worktrees/cam-2-3d-dev`.
memory hits: `search.py camera session call watchdog` -> релевантных уроков нет (watchdog Windows, project_hikvision_aspect_ratio — другое).
Слепой файл `test_plugin_device_commands.py` не правил.

## Что сделано (DESIGN / ACCEPTANCE)

- `plugin_base.py`:
  - `_CALL_TIMEOUT_S = 2.0` рядом с `_START_TIMEOUT_S`; `_NOT_GRABBING = "сеанс не в захвате"`; импорт `PortError`.
  - `_ensure_port()` (берёт `_session_lock`) + `_port_locked()` (вариант без захвата, его зовёт `_ensure_session` изнутри замка: вложенного захвата `Lock` нет). Порт присваивается в `self._port` сразу; сеанс, мост логов, воркеры не создаются; отказ `create_port` оставляет `_port is None` (повтор возможен).
  - `software_trigger_binding(self) -> Binding` (умолчание `Binding("genicam", "TriggerSoftware", "command")`) рядом с `bindings()`.
  - Раздел `# Команды Р7` расширен ниже `_log_apply`, выше `cmd_get_status` (место под readiness Ф ниже `cmd_get_status` не тронуто): `_port_or_refusal`, `_call_owner`, `cmd_list_devices` (+ `_enumerate_here`), `cmd_describe_params` (+ `_describe_node`), `cmd_trigger_software`. Словарь `commands`, docstring класса и модуля — только добавление строк.
  - `list_devices`: путь по `session.device_held` (нет сеанса или `not device_held` -> `acquire`, затем `enum_devices` и `release` в `finally` потоком команды; иначе `session.call(enum_devices)` — не `grabbing` даёт `"сеанс не в захвате"` самим `call`, порт не зовётся). Ответ `{"success": True, "devices": [{"kind","value","name"}]}`; отказ -> `{"success": False, "error": describe_error(exc)}`.
  - `describe_params`: порт -> нет `node_describe` -> `{"success": True, "params_meta": {}}` без вызова порта -> один `call` по всем `bindings()`; узел с `None`/`PortError` -> `null`; `entries` — `list`.
  - `trigger_software`: порт -> нет `software_trigger` -> `"нет capability software_trigger"` -> `call(execute(software_trigger_binding()))`.
  - Логи: `list_devices path=owner|command n= ms=`, `describe_params n= ms=`, `trigger_software ok=`.
- `session.py`: `call()` ставит в ящик `lambda: self._port_call("call", fn)`; `_execute` и `_TIMED` не тронуты.
- `testing/fake_port.py`: замок `_refs_lock` на `refs` в `acquire`/`release` (журнал и поведение прежние).
- Тесты: `tests/test_live_apply_hazards.py` (+2 теста сторожа; `_Rig.make` получил `timeout_ms`, `watchdog_s`, `on_stall` -> `rig.stalls`; умолчания прежние), `tests/test_plugin_device_commands_hazards.py` (новый, 12 тестов).
- Документы (README, DECISIONS, STATUS, sync/validate) не трогал.

## Прогоны (через `machine_gate.sh light`, `PYTHONPATH=<дерево>`, `.venv/bin/python`)

| Команда | Итог |
|---|---|
| слепой `test_plugin_device_commands.py` (до кода 28 красных, 2 зелёных) | 30 passed (3 прогона по ходу работы, флейков нет) |
| `test_plugin_device_commands_hazards.py` (мой) + `test_live_apply_hazards.py` | 42 passed в 4 прогонах из 5; 1 прогон — 1 failed `test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing` (см. «Открытое») |
| `Services/camera_device/tests` — прогон 1 / 2 / 3 | 364 passed, 1 failed, 10 skipped — все три раза, одинаково (красный — устаревший страж 2.3c, ниже) |
| `Services/hikvision_camera/tests` | 287 passed, 15 skipped |
| `multiprocess_framework/modules/tests/test_one_connector_per_point.py` | 19 passed |
| `ruff check` / `ruff format --check`: `plugin_base.py`, `session.py`, `fake_port.py`, оба моих тестовых файла | чисто |
| `git grep -nE "threading\.Thread|KeyedExecutor|ThreadPoolExecutor" -- plugin_base.py commands.py` | пусто, rc=1 |

## Красные тесты

1. Слепые 2.3d: красных нет (30/30), правок теста нет.
2. **Красный X: `Services/camera_device/tests/test_plugin_commands.py::test_страж_набор_команд_плагина_три_прежних_и_три_новых`** (тест 2.3c, не 2.3d). Он требует `CameraDevicePlugin.commands == {6 команд}` и `vars(CameraDevicePlugin)` с шестью `cmd_*`. Вход: плагин после 2.3d -> наблюдаемый вывод: `commands` содержит 9 команд (три новые: `list_devices`, `describe_params`, `trigger_software`). Это не ошибка кода: тест 2.3c привязан к составу команд ДО 2.3d, а набор в 9 команд — требование ACCEPTANCE 2.3d (слепой тест 2.3d `test_набор_команд_плагина_девять_команд_р7` зелёный). Файл вне моего FILES, тест не правил. Решение лида: обновить ожидание стража 2.3c на 9 команд (или снять сравнение с точным набором), 1 строка `expected` и 3 новых ключа.

## Таблица: гарантия моих hazard-тестов -> мутация, которая её ломает (прогноз; кроме отмеченных «проверено»)

Файл `test_plugin_device_commands_hazards.py` и два теста в `test_live_apply_hazards.py`.

| Гарантия | Тест | Мутация |
|---|---|---|
| Путь `list_devices` по `device_held`, а не `state`: медленный `close` + `stop(0.05)` -> `"сеанс не в захвате"`, счётчики `acquire`/`enum_devices`/`release` не растут | `..._при_медленном_close_после_stop_отказывает_и_порт_не_зовётся` | `path = "command" if session is None or session.state in ("idle","closed")` (**проверено запуском: красный**, `success True` вместо отказа); `device_held` заменён на `state != "grabbing"` для выбора пути 2 — красный там же |
| После выхода владельца тот же вызов идёт потоком команды (`acquire, enum_devices, release`) — контроль, что путь выбирается по `device_held` | тот же тест (хвост) | путь 2 навсегда запрещён при существовавшем сеансе (`session is None` вместо `not device_held`) -> красный хвост |
| Отказное открытие + `release_device` -> путь 2, `refs == 0` | `..._после_отказа_открытия_и_release_идёт_потоком_команды` | выбор пути по `state in ("busy","not_found","error")` как «владелец есть» -> красный (`NOT_GRABBING` вместо списка) |
| `call` против `stop` (12 итераций): ответ `LISTED` или литерал `срок`/`сеанс остановлен`/`сеанс не в захвате`, без зависания, `refs == 0` | `..._при_захвате_против_stop_отвечает_и_не_виснет` | `call` без ответа остановленному ящику (убрать `_close_box`-ответ «сеанс остановлен») -> зависание до дедлайна; ответ-исключение вместо `(False, ...)` -> красный. **Слабость:** без мутации гонка срабатывает не каждый раз |
| `release` НЕ зовётся после падающего `acquire`; журнал `["acquire"]` | `test_отказ_acquire_release_не_зовётся` | `sdk.acquire()` внутрь `try`, `release` в `finally` -> журнал `["acquire","release"]`, ответ `RuntimeError` вместо `PortError` -> красный |
| `release` в `finally` при отказе `enum_devices`; `refs == 0`; текст отказа | `test_отказ_enum_devices_без_захвата_отпускает_acquire` | убрать `try/finally` (release после enum без finally) -> нет `release` в журнале, `refs == 1`; `except PortError` не ловит -> исключение наружу |
| Отказ `release` -> ответ-отказ, не исключение | `test_отказ_release_после_перечисления_...` | узкий `except` (`except KeyError`) или его отсутствие -> исключение летит из команды |
| Отказ `create_port` -> ответ-отказ (`ValueError` — свой текст, `OSError` — тип), порт не залип, повтор создаёт | `test_отказ_create_port_...` | присвоить `self._port` до вызова хука/кэшировать неудачу; `str(exc)` для не-`ValueError`; не ловить исключение |
| Один порт при 4 параллельных командах (`create_port` == 1), `acquire` == `release` == 4 | `test_параллельные_list_devices_создают_один_порт_...` | `_ensure_port` без `_session_lock` -> `create_port_calls > 1` (окно 0,1 с в `create_port`); `release` вне `finally` на одном из путей -> `refs != 0` |
| `take_device` после `list_devices` не виснет на `_session_lock` | `test_take_device_после_list_devices_не_виснет_...` | `_ensure_session` зовёт `_ensure_port()` (с замком) изнутри захвата -> зависание, красный по дедлайну |
| Срок: команда с занятым владельцем отвечает `"срок"` за < 0,7 с и НЕ исполняется позже (`execute`/`describe_param` в журнале не растут), две команды параметризовано | `test_команда_по_сроку_отвечает_срок_и_позже_не_исполняется[trigger_software\|describe_params]` | `_CALL_TIMEOUT_S` не читается (`call(fn, 5.0)`) -> `elapsed >= 0,7`; убрать `cmd.cancelled = True` в `session.call` -> команда исполняется после зависания, счёт журнала растёт; обход `call` прямым вызовом порта из потока команды -> ответ не `"срок"` |
| Замок `refs` фейка: 6 потоков x 3000 пар `acquire`/`release`, `refs == 0` | `test_refs_фейка_не_теряет_счёт_...` | убрать `_refs_lock` — **проверено запуском: тест остался зелёным** (под GIL 3.12 гонка не поймана), т.е. тест слабый, мутацию он НЕ ловит |
| Сторож `call`: `fn` в `call` дольше `watchdog_s` -> один `on_stall("call", >= watchdog_s)` | `test_сторож_видит_зависший_fn_из_call` | `call` ставит `fn` вместо `_port_call("call", fn)` — **проверено запуском: красный** (`[] == ['call']`); перенос обёртки в `_execute` (вложенный `_port_call` из `_drain` сбросит `_current`) не ловится этим тестом |
| Сторож не срабатывает на быстрый `fn` | `test_сторож_не_срабатывает_на_быстрый_fn_из_call` | `_current` не сбрасывается в `finally` `_port_call` -> `on_stall` на каждом `call` (ложный сторож); без такой мутации зелёный всегда (контроль) |

## Отклонения от текста задачи

- Порядок обработки «сеанс не в захвате» для `describe_params`/`trigger_software`/пути 3 `list_devices` отдан самому `session.call` (он отвечает литералом при не-`grabbing` и закрытом ящике), отдельной проверки `state` в плагине нет: наблюдаемый ответ и «порт не вызван» те же; нет сеанса — `_call_owner` отвечает тем же литералом. Для `list_devices` путь 3 (`opening`/`stopping`/отказ при живом владельце) — тот же `call`.
- `except Exception` в `list_devices` (а не только `PortError`): неожиданное исключение хука/SDK не вылетает из команды (контракт 1.8), текст — `describe_error` (тип), в журнал `log_error`. Для `PortError` текст как в DESIGN.
- `_ensure_session`: старый комментарий про «порт не залипает на неудачной попытке» удалён — порт теперь по замыслу присваивается сразу (DESIGN), залипание порта намеренное; сеанс по-прежнему не залипает на отказе `DeviceSession`.
- Тест «одного `call` на `describe_params`» отдельно не написан (журнал не различает `call`); косвенно — слепой тест (счёт `describe_param` == числу привязок, потоки == поток `open`).
- Сообщение лиду `DESIGN / FILES / starting edits` перед первой правкой `src/` не отправил: в моём наборе нет инструмента отправки сообщений (SendMessage — отложенный, не вызывал); DESIGN и FILES взяты целиком из брифа.
- Файлы тестов именованы по брифу (`test_plugin_device_commands*.py`), в тексте задачи они назывались `test_plugin_commands_port*.py`.
- `_START_TIMEOUT_S` / `_STOP_TIMEOUT_S` по-прежнему мёртвые константы (замечание 2.3c, не менял).

## Что я оставил открытым / ненадёжно

- **Красный стража 2.3c** (выше): не мой файл, решение лида; пока не обновлён, `Services/camera_device/tests` даёт 1 failed во всех трёх прогонах.
- **Один незавоспроизведённый флейк:** `test_live_apply_hazards.py::test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing` (тест 2.4a, не мой) упал в одном из пяти запусков пары «мой файл + `test_live_apply_hazards.py`»; текст ошибки не сохранил. 25 повторных запусков этого теста по отдельности и три полных прогона каталога — зелёные. Мои правки его файла (`_Rig.make`: `timeout_ms`/`watchdog_s`/`on_stall` с прежними умолчаниями) к `stop`/`apply` в `opening` отношения не имеют; связь с моим кодом не доказана и не опровергнута.
- **Замок `refs`:** тест `test_refs_фейка_...` слабый (мутация проверена запуском — не ловится). Детерминированного способа поймать `+= 1` без замка под GIL не нашёл. Реальное доказательство — hazard-тест, в котором `acquire` приходят из потока команды и потока владельца одновременно с задержкой внутри `acquire` (требует хука в фейке, вне FILES). Замок в фейке есть и охраняет арифметику.
- **Один `call` на `describe_params`** прямо не проверен (нет шпиона, запрет имени API); проверен только счёт вызовов `describe_param` и поток.
- **Блокировка приёма команд до срока** (`_CALL_TIMEOUT_S` + `watchdog_s` ≈ 7 с в худшем случае), `register_update` и `state.changed` ждут срока: вывод стадии 0 по чтению, в живом процессе не запускал; тестов на неё нет.
- **Гонка `start()` из другого потока** против `acquire` на пути 2 (остаточный риск из DESIGN) не проверена и не закрыта замком; в docstring `cmd_list_devices` указана, в README/ADR — шаг tech-writer.
- **`call` против `stop`**: проверяет `call`, не боевой порядок (в живом процессе команды идут одним системным потоком); 12 итераций — гонку ловит не каждый раз.
- **`describe_params` без захвата с capability** отказывает `"сеанс не в захвате"` без вызова порта — по DESIGN и допущению слепого тестера №3; в моих hazard-тестах отдельно не повторено.
- Break-injection (по брифу) полностью не делал; «проверено запуском» в таблице — три точечные проверки (путь по `state`, `call` с `fn` без обёртки, снятие замка `refs`), остальное — прогноз по чтению кода.
- Новые файлы не закоммичены: в рабочем дереве `test_plugin_device_commands_hazards.py`, правки `plugin_base.py`, `session.py`, `fake_port.py`, `test_live_apply_hazards.py` и этот отчёт (слепые `test_plugin_device_commands.py` и отчёт тестера остаются untracked от тестера).

## Итерация 2: флейк `test_list_devices_при_медленном_close_после_stop_...` и два разовых красных соседей

Дерево `cam-2-3d-dev`, HEAD `3ecd9dd47`. Не коммитил.

**Причина красного моего теста — ошибка самого теста, не кода.** Воспроизвёл под нагрузкой (6 процессов с пустым циклом рядом): 1 красный из 3 запусков файла. Вывод: хвост теста ждал выход владельца по `rig.port.sdk.refs == 0`, затем звал `list_devices` и ждал `LISTED`; пришёл `{"success": False, "error": "сеанс не в захвате"}` (ожидался список). Механизм: владелец в `_cleanup` вызывает `release` (`refs` -> 0), затем `_stop_watchdog()` (join сторожа, до `watchdog_s`), и только потом под замком снимает `_held` (`device_held` -> False). В окне между `release` и снятием `_held` `refs == 0`, но владелец ещё жив, и `list_devices` по `device_held` правильно отказывает. Код (`session.py`, `plugin_base.py`) верен: это ровно та гарантия, которую тест проверяет в первой половине. Полный прогон каталога чаще попадает в окно (потоки соседних тестов, дольше `_stop_watchdog`).

**Правка:** признак выхода владельца — `release_device` отвечает `status: ok` (он проверяет `not session.device_held`); `_await(lambda: cmd_release_device({})["status"] == "ok", ..., 6.0)`, затем `assert refs == 0`. Слепой файл не трогал.

**Прогоны после правки:** мой файл под нагрузкой — 8 из 8 зелёные (до правки 1 красный из 3 в тех же условиях); без нагрузки — зелёный. Полный каталог `Services/camera_device/tests`: 3 прогона подряд без нагрузки — 368 passed, 10 skipped, 3 из 3; плюс 2 прогона под нагрузкой — 368 passed, 10 skipped. `ruff check` / `ruff format --check` на файле — чисто.

**Разовые красные `test_live_apply_hazards.py::test_apply_в_opening_и_сразу_stop_закрывает_без_start_grabbing` и `test_live_apply_session.py::test_restart_без_restart_regrab_переоткрывает_порт_state_остаётся_grabbing`.** Связь с моей правкой `call()` не вижу, доводы:
- Изменение `call()` (`self._enqueue(lambda: self._port_call("call", fn))`) затрагивает только путь `session.call`. Оба теста идут через `start`, `apply`, `stop` (`_drain`, `_regrab`, `_cleanup`): ни `call`, ни его обёртка там не исполняются, `_port_call` не менялся.
- Правки моего файла `test_live_apply_hazards.py` — только `_Rig.make` (параметры с прежними умолчаниями, `on_stall` пишет в список; `watchdog_s` по умолчанию 5,0, сторож в тесте не срабатывает) и два новых теста.
- Воспроизвести не удалось: эти два файла вместе — 8 запусков под нагрузкой (8 процессов с пустым циклом), 8 из 8 зелёные (38 passed); раньше 25 повторов одного из тестов — 0 красных; координатор: 25 прогонов двух файлов — 0 красных на main и у меня. Значит, оба красных нагрузочные/временные (тесты опираются на окна `open_delay_s`, `sleep`), а не следствие `call()`. Это вывод по рассуждению и по отсутствию воспроизведения, не доказательство: текст ошибок этих двух падений у меня не сохранён.

## Итерация 3: дыра D10 и флейки соседних тестов

Код `d16a0442c`. Не коммитил. Мутацию D10 применял только в одноразовой копии (`git worktree` в scratchpad, после прогона удалена); `cam-2-3d-dev` не мутировался.

### 1. D10 (`_port_call` без `self._current = None` в `finally`)

**Почему старый тест не ловил.** `test_сторож_не_срабатывает_на_быстрый_fn_из_call` ждал после быстрого `fn` просто паузу. Владелец при этом крутит `get_frame` каждые ~10 мс: каждый новый `_port_call` перезаписывает `_current`, застрявшее значение не доживает до `watchdog_s`. Мутация видна, только когда владелец долго НЕ зовёт порт (в реальном коде это `on_frame`/`on_state` — колбэки в потоке владельца).

**Правка.** Тест заменён на `test_сторож_не_срабатывает_после_быстрого_fn_из_call_пока_владелец_вне_вызова_порта` (`test_live_apply_hazards.py`): `watchdog_s=0.2`, `timeout_ms=100`; быстрый `fn` через `call` -> `(True, "быстро")`; затем первый кадр после взвода флага стоит в `on_frame` 0,8 с (не вызов порта); пауза 0,9 с; ожидание `rig.stalls == []`.

**Запуск (одноразовая копия коммита `d16a0442c` + новый тест, `-k сторож`):**
- контроль без мутации: `2 passed, 28 deselected`;
- D10: `1 failed, 1 passed`; `AssertionError: assert [('get_frame', 0.247407041999395)] == []` (ложный `on_stall("get_frame")` от застрявшего `_current`; без `finally`-сброса сторож принимает `on_frame` за зависший вызов порта).
Набор A (три файла) на `cam-2-3d-dev`: `72 passed`. `ruff check` и `ruff format --check` на файле — чисто.

Граница проверки: мутация D10 проверена только на тестах `-k сторож` в копии, полный набор A под D10 не гонял (каталог 2.3d-прогон Haiku: красный D10 был в `test_live_apply_session.py`, вне набора A).

### 2. Флейки `test_apply_в_opening_и_сразу_stop_...` и `test_restart_без_restart_regrab_...`

**Не воспроизведены ни разу — текста ошибки нет.** Сделал, как просили: `test_live_apply_hazards.py` + `test_live_apply_session.py` с `--tb=short`, вывод каждого прогона в файл (scratchpad `flake_mine/runN.txt`, `flake_main/runN.txt` и т. д.). Итоги (все 38 passed у меня, 36 passed на main, так как у меня на 2 теста больше):

| Условие | Дерево | Прогонов | Красных |
|---|---|---|---|
| плоский повтор | у меня (код `d16a0442c` + новый тест) | 20 | 0 |
| плоский повтор | main, `e925ddb85` (одноразовая копия) | 20 | 0 |
| чистый кэш байткода перед каждым прогоном + 4 процесса нагрузки | у меня | 6 | 0 |
| 20 процессов нагрузки (пустые циклы) | у меня | 5 | 0 |
| 20 процессов нагрузки | main `e925ddb85` | 5 | 0 |
| (итерация 2) 6–8 процессов нагрузки, оба файла | у меня | 8 | 0 |
| (итерация 2) 25 повторов одного теста | у меня | 25 | 0 |

Итого: у меня 64 прогона пары файлов, на main 25 — 0 красных. Ни одного красного в моём дереве за эту и прошлую итерации, кроме двух разовых наблюдений до итерации 3 (мой разовый красный в «моём файле + `test_live_apply_hazards.py`», текст не сохранён; красный в контроле Haiku, 1 из 4, текст в отчёте Haiku не приведён).

**Вывод по различию «main/мои правки».** Различий в поведении, которые могли бы дать этот красный, не вижу: тесты не вызывают `session.call`, а моя правка в `session.py` — только `call`; `fake_port.py` — замок `refs` (тесты `open_handles` его не читают); `_Rig.make` — параметры с прежними умолчаниями. Но «воспроизвелось на main» или «не воспроизвелось» доказать не могу: красный не пойман ни в одном дереве. Это не доказательство отсутствия связи — это отсутствие воспроизведения.

**Гипотезы механизма (не проверены, красного для них нет).**
1. `test_apply_в_opening_и_сразу_stop`: ждёт `open` (`_await_opening`, `open_delay_s=0.3`), затем `apply(restart)` и `stop(2.0)` и сразу ожидает `"set_param(TriggerSelfTriggerPeriod,61)" not in names` и `"start_grabbing" not in names`. Если поток-владелец при нагрузке уже дошёл от `open` до `_commit`/`start_grabbing` раньше, чем придёт `stop`, `start_grabbing` попадёт в журнал, а тест ждёт обратного. Окно решается только `open_delay_s=0.3` против времени двух вызовов `_call`; под очень сильной паузой планировщика (> 0,3 с) тест красный. Правка теста (предложение, не делал): держать владельца в `open` детерминированно (`open` блокируется на `threading.Event` фейка, а не на сне), либо поднять `open_delay_s`.
2. `test_restart_без_restart_regrab_...`: опрос окна перезахвата с шагом 5 мс (`while ... time.sleep(0.005)`), окно `close -> второй start_grabbing` длится `open_delay_s=0.3` с; красный `"окно перезахвата ... не наблюдалось"` возможен только при паузе опроса > 0,3 с. Тоже временное окно.
Оба предположения — рассуждение по коду, не текст ошибки.

### Что я оставил открытым / ненадёжно (итерация 3)

- **Флейки `test_apply_в_opening_и_сразу_stop_...` и `test_restart_без_restart_regrab_...` я не воспроизвёл ни на моём дереве, ни на main.** Текста ошибки (assert-строк) у меня нет; гипотезы механизма выше — по чтению кода. Просили не делать правку теста 2.4a без сигнала — не сделал. Чтобы поймать красный: запускать полный каталог (красные видели в полном прогоне и в прогонах Haiku, а не в паре файлов) и сохранять `--tb=short` в файл при первом красном; у меня полный каталог с итерации 2: 5 прогонов зелёных (368 passed).
- **D10-тест проверяет `_current` сторожа через `on_frame`, а не через `call`**: он ловит сброс `_current` в `finally` вообще (любого вызова порта), `call` в нём — прелюдия. Мутацию «убрать сброс только для `name == "call"`» он не отличит от D10 (проверять не стал).
- Один прогон D10 на копии, не серия.
- D5/D6 (Haiku): набор красных одинаков; различить мутации (`_CALL_TIMEOUT_S` не читается и `cmd.cancelled = True` убран) моим набором нельзя — разделение не делал.
- D9 выжил (по отчёту Haiku, набор A без красного); не разбирал, не в задаче этой итерации.
- Замок `refs`: тест слабый (прежняя запись).

## Итерация 4 (ревью Opus)

Код `656d33eb5` + правки ниже. Не коммитил. Мутации — в одноразовой копии (`git worktree`, после прогона удалена); скрипты `inj_23d.py` (D1–D10) и `inj_23d_r4.py` (M1, M10, M12) в scratchpad.

### Что исправлено

1. **Находка 2 (сторож `call`).** В `test_live_apply_hazards.py` тест `test_сторож_не_срабатывает_после_быстрого_fn_из_call_пока_владелец_вне_вызова_порта` взводит флаг `slow` внутри `fn`: `session.call(lambda: (slow.set(), "быстро")[1], 3.0)`. Теперь `on_frame` стоит 0,8 с сразу после ответа `call`, `_current` последнего вызова порта (`call`) не успевает затереться `get_frame`.
2. **Находка 3 (флейки 2.4a, механизм ревьюера).** `on_state` приходит после замка, где `start()`/`stop()` уже вернулись. Исправлены оба теста через `_await(...)` с дедлайном, литералы ожидания прежние:
   - `test_live_apply_session.py` (`test_restart_без_restart_regrab_...`): `_await(lambda: rig.events == [("idle","opening"),("opening","grabbing")], ...)` вместо `assert` сразу после `start()`.
   - `test_live_apply_hazards.py` (`test_apply_в_opening_и_сразу_stop_...`): `_await(lambda: rig.events == [("idle","opening"),("opening","stopping"),("stopping","closed")], ...)` вместо `assert`.
   Это тесты 2.4a вне дифа 2.3d; правка отдельная. Другие `assert rig.events == [...]` в этих двух файлах (`test_live_apply_hazards.py:185, 230, 274, 483, 504`, `test_live_apply_session.py:214`) не трогал: они стоят после ожидания дальнейших действий владельца (запись, перезахват, отказ), а не сразу после `start()`/`stop()`; по механизму ревьюера они тоже теоретически гонятся, но красных там не видели.
3. **Находка 4 (`describe_param` -> `None`).** Выбран вариант «оставить защитную ветку и добавить тест»: `test_describe_params_describe_param_вернул_none_даёт_null_только_для_этого_поля` (подмена `port.describe_param`: `None` для `ExposureTime` при `node_describe`; `exposure_time is None`, `trigger_mode` — литерал `{"min": None, "max": None, "inc": None, "entries": ["Off","On"], "access": "RO"}`, остальные поля не `None`). Ветка по контракту `interface.py:155-160` недостижима при проверенной capability; тест фиксирует защиту от порта, нарушающего контракт.
4. **Находка 5 (один `call`).** `test_describe_params_все_describe_param_идут_подряд_одним_call`: между первой и последней записью `describe_param` в журнале нет других вызовов (нет `get_frame`), а число записей равно числу полей ответа.
5. **Advisory (хук `bindings`).** `cmd_describe_params`: `self.bindings()` под `try/except Exception` -> `{"success": False, "error": describe_error(exc)}` + `log_error` (код `plugin_base.py`). Тест `test_describe_params_исключение_хука_bindings_отвечает_отказом_а_не_исключением` (`RuntimeError` -> `{"success": False, "error": "RuntimeError"}`, `describe_param` в журнале нет).

Не мои: находки 1 (документы) и 6 (имена файлов в тексте задачи) — их делает tech-writer/лид; находка 7 (M11, `logger.exception` при отказе `execute`) — advisory, не менял.

### Мутации на копии (набор: 4 файла — слепой, мой hazard, `test_live_apply_hazards.py`, `test_live_apply_session.py`; один прогон на мутацию)

Контроль без мутации: `83 passed`.

| Мутация | Ожидалось | Факт (красные, итог) | Совпало |
|---|---|---|---|
| D1 `call` кладёт `fn` | красный | `test_сторож_видит_зависший_fn_из_call` (`[] == ['call']`); 1 failed / 82 passed | да |
| D2 путь `list_devices` по `state` | красный | `..._при_медленном_close_после_stop_...` (список вместо отказа); 1 / 82 | да |
| D3 `release` вне `finally` | красный | `test_отказ_enum_devices_без_захвата_отпускает_acquire` (`['acquire','enum_devices']`); 1 / 82 | да |
| D4 `_ensure_port` без замка | красный (вероятностно) | `test_параллельные_list_devices_создают_один_порт_...`; 1 / 82 | да |
| D5 убран `cancelled = True` | красный | оба параметра `test_команда_по_сроку_...` (`1 == 0`, `5 == 1`) + `test_live_apply_session.py::test_call_результат_в_потоке_владельца_срок_и_closed`; 3 / 80 | да |
| D6 срок 5,0 вместо `_CALL_TIMEOUT_S` | красный | оба параметра `test_команда_по_сроку_...`; 2 / 81 | да |
| D7 `describe_params` без `call` | красный | `test_describe_params_каждый_describe_param_идёт_в_потоке_владельца`, `..._без_захвата_с_capability_отказывает`, `test_команда_по_сроку_...[describe_params]`; 3 / 80 | да |
| D8 нет проверки `software_trigger` | красный | `test_trigger_software_без_capability_отказывает_и_сеанс_не_создан`; 1 / 82 | да |
| D9 `refs` без замка | выживает | 83 passed | да (выжил) |
| D10 нет сброса `_current` | красный | `test_сторож_не_срабатывает_после_быстрого_fn_из_call_...` (`[('call', 0.2…)] == []`); 1 / 82 | да |
| M1 убрана ветка `describe_param -> None` | красный (новый тест) | `test_describe_params_describe_param_вернул_none_...`; 1 / 82 | да |
| M10 по `call` на привязку | красный (новый тест) | `test_describe_params_все_describe_param_идут_подряд_одним_call` (между записями `get_frame`); 1 / 82 | да |
| M12 сброс `_current` не для `name == "call"` | красный | `test_сторож_не_срабатывает_после_быстрого_fn_из_call_...` (`[('call', 0.2…)] == []`); 1 / 82 | да |

### Прогоны
- Каталог `Services/camera_device/tests`, 3 раза подряд: `371 passed, 10 skipped` (трижды).
- `ruff check Services/camera_device` — чисто; `ruff format --check` — 36 files already formatted.

### Что я оставил открытым / ненадёжно (итерация 4)
- Мутации — по одному прогону; D4 вероятностна, D9 выживает (замок `refs` тестом не проверяется).
- Тест сторожа и M12: доказано запуском только на мутациях D10 и M12; сброс `_current` для прочих имён вызовов (не `call`) отдельно не мутировал.
- Тест «один `call`» опирается на то, что между двумя `call` владелец успевает вызвать `get_frame` (`frame_period_s=0.02`); при очень длинной паузе планировщика между `call` теоретически возможен ложный зелёный на M10, ложного красного на коде нет.
- Исправление флейков 2.4a подтверждено механизмом ревьюера и тремя зелёными прогонами каталога, но флейк редкий: «не воспроизводится» — не доказательство; остальные `assert rig.events == [...]` в этих файлах (список выше) не переведены на `_await` и теоретически подвержены тому же.
- Тест на `None`-ветку проверяет защитный код, достижимый только при нарушении контракта порта.
- Документы (находка 1) и имена файлов в `tasks/2.3d.md` (находка 6) не делал: не мои по брифу.
