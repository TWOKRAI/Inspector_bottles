# Task 2.3d — ревью Opus, раунд 1

Дерево `cam-2-3d-dev`, ветка `feat/camera-2-3d`, HEAD `656d33eb5`, диф `bb7ac56e5..HEAD -- Services/camera_device`.
Только чтение и запуск тестов. Код не правил, не коммитил. Мутации — в одноразовой копии
(`git worktree add --detach <scratchpad>/rev/wt HEAD`), после прогона копия удалена (`git worktree list` — 0 записей `rev/wt`).
memory hits: n/a (поиск по памяти не запускал: роль только читает, урок не пишу).

## Вердикт

**CHANGES REQUESTED (итерация 1 из 2).**

Код команд и `session.call` верен по DESIGN: инвариант Р1 соблюдён, дедлока `_session_lock` нет, контракт 1.8 и
Dict at Boundary соблюдены. Причины вердикта: (1) строка ACCEPTANCE «Документы» на HEAD не выполнена;
(2) тест сторожа автора не доказывает то, что обещает его имя (мутация M12 выжила, проба ревьюера её ловит 3 из 3).
Оба пункта короткие. Остальное — minor и advisory.

## Находки (по убыванию серьёзности)

### 1. [spec] Шаг «Документы» не сделан: строка ACCEPTANCE не выполнена

- Где: `Services/camera_device/README.md`, `DECISIONS.md` (ADR-CAM-002), `STATUS.md`; задача `tasks/2.3d.md:68-72`.
- Вход: `git grep -n "_CALL_TIMEOUT_S\|MV_CC_EnumDevices" -- Services/camera_device/README.md Services/camera_device/DECISIONS.md`.
- Наблюдаемый результат: пусто. Совпадения `list_devices` есть только в старом тексте (`DECISIONS.md:195`, `STATUS.md:27`).
  Остаточный риск `start()` из другого потока, блокировка приёма команд до ~7 с и открытый вопрос о межпроцессном
  `MV_CC_EnumDevices` записаны только в docstring и комментариях кода.
- Предложение: до закрытия задачи выполнить шаг `tech-writer` из раздела «ДОКУМЕНТЫ» (цепочка задачи ставит его ДО этого
  ревью), затем `python scripts/validate.py` и `python -m scripts.sync`. Код этот пункт не меняет.

### 2. [tests] Тест «сторож не срабатывает после быстрого fn из call» не проверяет `call`

- Где: `Services/camera_device/tests/test_live_apply_hazards.py:321`
  (`test_сторож_не_срабатывает_после_быстрого_fn_из_call_пока_владелец_вне_вызова_порта`).
- Механизм: флаг `slow` взводится ПОСЛЕ ответа `call`. Владелец до медленного `on_frame` всегда зовёт `get_frame`
  (`_port_call` перезаписывает `_current`), поэтому `_current` от `call` до медленного `on_frame` не доживает.
  Тест ловит D10 (сброс `_current` убран для всех вызовов), но не сброс именно после `call`.
- Вход: мутация M12 в `session.py::_port_call` — `self._current = None` только при `name != "call"`.
- Наблюдаемый результат: набор из четырёх файлов (`test_plugin_device_commands.py`, `..._hazards.py`,
  `test_live_apply_hazards.py`, `test_live_apply_session.py`) — `80 passed`, мутант выжил.
- Проба ревьюера (в копии, не в дереве): `fn` из `call` сам взводит флаг, медленный `on_frame` идёт для того же кадра
  сразу после `_poll_box`:
  ```python
  assert s.call(lambda: (slow.set(), "быстро")[1], 3.0) == (True, "быстро")
  time.sleep(1.0)
  assert stalls == []          # watchdog_s=0.2, timeout_ms=100, on_frame спит 0.8 с один раз
  ```
  Контроль: 3 из 3 зелёные. M12: 3 из 3 красные, `AssertionError: assert [('call', 0.2...)] == []`.
- Предложение: в тесте взводить флаг внутри `fn` (как в пробе), а не после ответа `call`. Тогда тест доказывает свойство
  для `call`; D10 он ловит по-прежнему.

### 3. [tests, вне дифа 2.3d] Механизм двух «нагрузочных» флейков найден: тест читает `rig.events` раньше `on_state`

Не блокирует 2.3d: оба теста из 2.4a, код 2.3d их путь не трогает. Но гейт каталога из-за них красный примерно 1 раз
из 3–4, и гипотезы автора (окно `open_delay_s`, опрос 5 мс) текстом ошибки опровергнуты.

- Тексты ошибок (сохранены):
  - `test_live_apply_session.py:178` — `assert rig.events == [("idle", "opening"), ("opening", "grabbing")]` ->
    `AssertionError: assert [('idle', 'opening')] == [('idle', 'op..., 'grabbing')]`. В захваченном логе той же
    попытки строка `session state=opening->grabbing` есть: переход был, `on_state` ещё не вызван.
    Видел 2 раза: прогон каталога 1 и прогон мутации M10 (M10 этот путь не трогает).
  - `test_live_apply_hazards.py:521` — `assert rig.events == [..., ("stopping", "closed")]` ->
    `AssertionError: assert [('idle', 'op..., 'stopping')] == [('idle', 'op...g', 'closed')]`. Видел 1 раз (прогон M10).
- Механизм (`session.py`): `_enter_grabbing` ставит `cmd.finish(True)` под замком (`:533`), а `_fire_states` — после
  замка (`:534`); `start()` возвращает `True` по `cmd.done` раньше `on_state("opening","grabbing")`. То же на выходе:
  `_held = False` и `exited.set()` под замком (`:592-593`), `_fire_states` — после (`:594`), поэтому `_await(closed and
  not device_held)` и `stop()` возвращаются раньше `on_state("stopping","closed")`.
- Детерминированная проба: `on_state` спит 0,2 с на `grabbing`; `s.start(5.0) is True`, снимок `events` сразу после ->
  `[("idle", "opening")]`. 3 из 3 подтверждено.
- Предложение (лиду, отдельная правка тестов 2.4a): сравнение `rig.events` — через `_await(lambda: rig.events == [...])`
  с дедлайном, а не сразу после `start()`/`stop()`. Код сеанса менять не нужно: порядок «итог, затем `on_state` вне
  замка» — решение 2.1/2.4a (docstring `_enter_grabbing`).

### 4. [quality] Ветка «`describe_param` дал `None` -> `null`» не покрыта тестом (M1 выжил)

- Где: `plugin_base.py:835-836` (`if info is None: return None`).
- Вход: мутация M1 — ветка удалена. Наблюдаемый результат: `80 passed`.
- Оценка: по контракту `interface.py:155-160` `None` бывает только без `node_describe`, а эту capability плагин
  проверяет раньше (`:816`). MVS (`hikvision_camera/driver.py:335-361`) `None` не возвращает: для нечитаемого узла даёт
  `ParamInfo(None, None, None, None, "NI")`. Ветка — защитная. Без неё порт, нарушающий контракт, уронил бы всю команду
  (`AttributeError` -> `{"success": False, "error": "AttributeError"}`), а не одно поле.
- Предложение: один тест с подменой `port.describe_param`, которая для одного ключа возвращает `None` ->
  `params_meta[поле] is None`, остальные заполнены. Либо убрать `None` из строки DESIGN и docstring.

### 5. [quality] «Один `call` на `describe_params`» не проверен (M10 выжил; автор это знал)

- Вход: мутация M10 — по одному `session.call` на каждую привязку. Наблюдаемый результат: целевые тесты зелёные
  (два красных прогона — флейки из п. 3, их путь M10 не трогает).
- Наблюдаемый признак без шпиона API: при одном `call` все записи `describe_param` в журнале порта идут подряд. При N
  вызовах владелец между ними возвращается в цикл и зовёт `get_frame` (следующий `call` ставится только после ответа
  предыдущего). Проверка: «между первой и последней записью `describe_param` нет `get_frame`».
- Предложение: добавить такую проверку в hazard-файл автора.

### 6. [quality] Расхождение имён файлов с текстом задачи

- `tasks/2.3d.md:6,41,44,66`: `test_plugin_commands_port.py`, `test_plugin_commands_port_hazards.py`. В ветке:
  `test_plugin_device_commands.py`, `test_plugin_device_commands_hazards.py` (по брифу лида, отчёт developer, строка 69).
  Вне FILES правлен `tests/test_plugin_commands.py` (страж набора команд: 6 -> 9), это решение лида.
- Предложение: обновить FILES, Gate и TESTS в файле задачи, чтобы гейт по тексту задачи находил файлы.

### 7. [advisory] Мелочи без воспроизведения дефекта

- M11 («`call` в `_TIMED`») выжил: свойство «`on_timing` не пишет `call`» тестом не закреплено. Плагин неизвестные
  имена в `_on_timing` пропускает, поэтому наблюдаемого эффекта у плагина нет.
- `cmd_describe_params`: `self.bindings()` (`:818`) — вне `try`. Хук вендора, бросивший исключение, выйдет из команды
  наружу (контракт 1.8). Сегодня хуки таблицы не бросают.
- Отказ `port.execute` в `trigger_software` пишет полный след через `logger.exception` в `session._execute`
  (поведение 2.4a). При ~2 Гц и постоянном отказе журнал растёт быстро.

## Что проверено и верно (чтением, с указанием места)

- Р1, путь `list_devices`: выбор по `session.device_held` (`plugin_base.py:775`). `_held` снимается владельцем после
  `_cleanup` (последний вызов SDK — `release`) и `_stop_watchdog` (`session.py:586-592`). После этого владелец SDK не
  зовёт: остаётся `_fire_states` -> `_on_state` -> `_sync_events`, а там только чтение свойств сеанса и
  `port.capabilities`. Ветка отказа `_launch_owner` (`:479-482`) снимает `_held`, пока прежний владелец может быть жив,
  но в этот момент он уже прошёл `_cleanup` (на нём `_held` уже был `False`).
- Остаточный риск «`start()` из другого потока»: в живом процессе НЕ воспроизвёл и, по чтению, на сегодня он
  недостижим. `session.start()` зовёт только `cmd_take_device` (`plugin_base.py:627`). Её вызывают (а) хук `start(ctx)`
  при `auto_start` (`:347-349`) из `PluginOrchestrator.boot()`, а `boot()` идёт в `_init_application_threads()`
  (`process_module.py:292`) ДО `_init_system_threads()` (`:312`), то есть до запуска `message_processor`; (б) сами
  команды в `message_processor`. `pause/resume` плагин не переопределяет. Это вывод по чтению, без запуска.
- `release` только после успешного `acquire` (`plugin_base.py:800-804`): `acquire` стоит вне `try`.
- `_session_lock`: захватывают только `_ensure_port` (`:557`) и `_ensure_session` (`:567`); из-под замка зовётся
  `_port_locked` без захвата. Вложенного захвата `Lock` нет.
- `session.call`: срок `_CALL_TIMEOUT_S`; отмена до взятия командой (`cancelled`); после `committed` ожидание ещё до
  `watchdog_s` (`session.py:350-361`). Худший случай — 2,0 + `watchdog_s`, как в DESIGN. Ответ остановленному ящику —
  «сеанс остановлен» (`_close_box`); не `grabbing` — «сеанс не в захвате» (`_enqueue`). Обёртка `_port_call("call", fn)`
  — в `call`, а не в `_execute`; `_drain` идёт мимо неё.
- Контракт 1.8: отказы `create_port`, `acquire`/`enum_devices`/`release`, `call` и `execute` приходят ответом. Тексты:
  `ValueError` — свой текст, иначе `describe_error`; в логах только `path`, `n`, `ms`, `ok` и текст отказа, без
  серийников и значений полей.
- Dict at Boundary: `params_meta` — `dict`, `entries` — `list` (`:837`; у MVS в `ParamInfo` кортеж). `devices` — список
  словарей из строк. У MVS границы — `int`/`float` Python.
- Слепой набор (30): неверной модели тестера не нашёл. Ожидания — литералы таблицы фейка. Окна `opening`/`stopping`
  перепроверяются после команды (`state == ...`), поэтому ложно-зелёного нет. Hazard-набор автора (12): пустых
  утверждений и проверок по имени шпиона API нет. `test_refs_фейка_...` — известная слабость (D9), автор её записал.

## Что я проверил запуском

Все команды — через `machine_gate.sh <class> inspector-bottles-20`, `PYTHONPATH=<корень дерева или копии>`,
`.venv/bin/python -m pytest -q -p no:cacheprovider`.

| Команда | Итог |
|---|---|
| `medium`: `Services/camera_device/tests` (дерево `cam-2-3d-dev`) | `1 failed, 367 passed, 10 skipped`, rc=1. Красный — флейк п. 3 (`test_live_apply_session.py:178`), текст сохранён |
| `medium`: `Services/hikvision_camera/tests` + `multiprocess_framework/modules/tests/test_one_connector_per_point.py` | `306 passed, 15 skipped`, rc=0 |
| `medium`, копия, контроль: 4 файла (слепой, hazard автора, `test_live_apply_hazards.py`, `test_live_apply_session.py`) | `80 passed` |
| то же под M1 (`describe_param` -> `None` без проверки) | `80 passed` — выжил |
| то же под M9 (`describe_params` только по полям без `skip` в плане; DESIGN: по ВСЕМ привязкам) | 4 красных слепых (`:265`, `:273`, `:294`, `:328`) — пойман |
| то же под M10 (по `call` на привязку) | `2 failed, 78 passed`: оба красных — флейки п. 3, целевые тесты зелёные — выжил |
| то же под M11 (`"call"` в `_TIMED`) | `80 passed` — выжил |
| то же под M12 (сброс `_current` не для `call`) | `80 passed` — выжил |
| `light`, копия: проба ревьюера (2 теста), контроль x3 | `2 passed` x3 |
| то же под M12 x3 | `1 failed, 1 passed` x3: `assert [('call', 0.2...)] == []` |
| `secrets_audit.py --format json --root Services/camera_device` | rc=0, `total: 0` |
| `ruff check -q` на 6 файлах дифа | rc=0 |
| `git grep -nE "threading\.Thread|KeyedExecutor|ThreadPoolExecutor" -- Services/camera_device/plugin_base.py` | пусто, rc=1 |

Скрипт мутаций лида `inj_23d.py` (D1–D10) повторно не гонял: факт прогона уже в `…-injections-run.md`. Свои мутации M1,
M9–M12 — по одной, каждая заменой ровно в одном месте (проверено `assert count == 1`), после каждой `git checkout`.

## Что оставил открытым / ненадёжно

- Гонку «`start()` из другого потока» против `acquire` на пути 2 не запускал. Вывод «недостижима сегодня» — по чтению
  порядка инициализации процесса (`process_module.py:291-312`). Новый вызов `cmd_take_device` не из
  `message_processor` (например, авто-переподключение в будущем) откроет окно снова. Защиты замком в коде нет.
- Hazard-тест `test_параллельные_list_devices_...` гоняет путь 2 из четырёх потоков одновременно, то есть SDK фейка
  зовут параллельно. Для теста это допустимо, но боевой SDK так не вызывается. Безопасность `MV_CC_EnumDevices` при
  открытом handle в другом процессе — не измерена (вопрос из DESIGN, стенд).
- Блокировку `message_processor` до ~7 с (`register_update`, `state.changed` ждут) в живом процессе не проверял.
- Флейки п. 3: механизм подтверждён пробой и текстом ошибок, но правку тестов не делал и не проверял. Других причин тех
  же падений не исключал.
- Каждая мутация — один прогон, кроме M12 (3 прогона). Контроль четырёх файлов — один прогон.
- Каталог `Services/camera_device/tests` гонял один раз (красный флейк); второй прогон каталога не делал. Ожидание брифа
  «368 passed» на этом прогоне не подтверждено. Без флейка счёт совпадает: 367 + 1.
- Проба ревьюера живёт только в удалённой копии; в дерево её не вносил.
