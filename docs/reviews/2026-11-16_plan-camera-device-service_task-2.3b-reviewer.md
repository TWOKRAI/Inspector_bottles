# Task 2.3b — reviewer: наблюдаемость базы плагина камеры

Коммит `84e5bb600`, ветка `feat/camera-device-w3` (HEAD при ревью `941951acb`, `Services/` после `84e5bb600` не менялся).
Вердикт: **CHANGES REQUESTED (итерация 1 из 2)**. Блокеров нет; 1 важная правка кода, 1 пакет тестов, остальное мелочи.
Репродукции и скрипты: `scratchpad/rev23b/` (`test_rev23b.py`, `test_rev23b_g.py`, `mutplug.py`, `out1.txt`); в дерево не кладутся.

## Список (severity, путь:строка, вход -> наблюдаемый результат)

1. **[important][tests]** `Services/camera_device/tests/test_plugin_observability.py` — часть заявленных свойств не защищена.
   Прогнал мутанты через `-p mutplug` (контроль: убран `flight_dump` в `_on_stall` -> T3 красный, `1 failed, 5 passed`, механизм работает):
   - `_published` не запоминается (diff снят): `6 passed` (J3 лида);
   - `proxy.delete` ушедших ключей заглушён: `6 passed` (J8 лида);
   - `_report_incidents` без цикла по `param_errors`: `6 passed` (в прогнозах лида нет);
   - сверка событий из `_tick` отключена: `6 passed` (в прогнозах нет).
   Вообще не покрыты (grep по файлу тестов): `_SessionLogBridge` (строка `session state=` не доходит до `ctx.log_info` — нигде не проверено; снятие handler'а в `shutdown` = J11), значения уровней `errors/dropped/pending/param_errors_count/fps` (тест 6 сверяет только имена и `frames == 0`).
   Fix: тесты «N вызовов `_sync_events` без смен -> 0 новых merge», «ушедший ключ -> `delete`», «новый ключ `param_errors` -> 1 инцидент `camera_device.param`», «строка сеанса дошла до `ctx.log_*`, после `shutdown` handler снят», «битый кадр -> `dropped` > 0 в уровне».
   Один тест с настоящим `StateProxy` нужен и дёшев (~25 строк): `StateProxy(router=двойник send_async -> TreeStore.merge/delete)`. Мой scratch `test_I_real_stateproxy_roundtrip` прошёл: в дереве `state=grabbing`, `params`, `param_errors`, `device={"kind":"serial","value":"FAKE-0001","name":""}`, `last_error=None`; после сужения `params` ушедший ключ снят (`delete` до `merge` работает). `_FakeProxy` глубокий merge и `delete` не проверяет.

2. **[important][quality]** `plugin_base.py:62`, `:303` — `profile` врёт при отказе открытия.
   Вход: `make_port(busy_for_s=60.0)`, `cmd_take_device` -> `busy`, затем `cmd_release_device`. Наблюдаемо: в дереве `state=closed`, `profile="rest"`; журнал порта `['acquire','enum_devices','open','release']` — `set_param` не звался, rest в прибор не писался.
   Fix: `"profile": _PROFILE_OF_STATE.get(state) if device is not None else None` (+ тест). Остаточная неточность (повторный сбой открытия при `device` от прошлого цикла даёт `rest` — физически верно, прибор остался в rest) допустима.

3. **[nit][quality]** `plugin_base.py:218-222` — снятие handler'а не в `try/finally`.
   Вход: `cmd_release_device` бросает -> `removeHandler` не выполняется, handler держит `ctx`. Вход 2 (мой scratch): 3 плагина создано и `_ensure_session` вызван без `shutdown` -> `3` handler'а остались на `camera_device.session`.
   Fix: `try: self.cmd_release_device({}) finally: <снять мост>`; `_attach_log_bridge` не добавляет второй мост тому же `ctx`.

4. **[nit][quality]** `plugin_base.py:6` и `:24` — докстринг противоречит себе: стр. 24 «Публикация — `declare_metric("frames")` + `publish_metric` ..., **без прямого `merge`**», а новый абзац выше описывает прямой `state_proxy.merge` событий; стр. 6 «Публикация метрик, `device_held`, `last_error` — Task 2.3b» — устарело. Fix: переписать одно предложение.

5. **[nit][quality]** `plugin_base.py:314-327` — дедуп `param_errors` по ключу, не по циклу.
   Вход: `read_offset={"ExposureTime": 500.0}`, `exposure_time=1000` -> `param_errors={'exposure_time': 'не подтвердилось чтением'}`, take: инцидентов `camera_device.param` = 1; `release`; второй take с тем же отказом: инцидентов по-прежнему 1 (сводка scratch `E`: `after run1: 1 after run2: 1`). Причина: ключ остаётся в `_reported_param_errors`, потому что синхронизация на `opening` читает старый `param_errors` раньше `reset()` владельца. Чисто в FILES не чинится (нужен номер цикла из сеанса) — см. «Открытое».

6. **[nit][quality]** `plugin_base.py:303`/`_tick` — `device_held` в дереве отстаёт до `_TICK_S` после отказа.
   Вход: `busy_for_s=60`, take, `drive(0.3)`. Наблюдаемо: `tree state=busy, tree device_held=True | session.device_held=False`; после окна (1,2 с) `device_held=False` (scratch `C`). Причина: `session.py:458-462` — при состоянии из `_FAILED` `pending` пуст, `on_state` на снятие `_held` не зовётся. Дешёвое смягчение в FILES: в `produce()` звать `_sync_events()`, пока опубликован отказ и `device_held` True. Корень — в `session.py` (вне FILES).

## Проверено, находок нет (вход -> результат)

- **Мост, жизненный цикл.** attach в `_ensure_session` (после `DeviceSession(...)`, до присвоения `_session`: `create_port`/конструктор бросили -> моста нет). `shutdown` -> 0 лишних handler'ов (scratch `G handlers after close: 0`). `bridge.handle(...)` при `ctx.log_*`, бросающем `RuntimeError`: наружу ничего не вылетело, `handleError` печатает в stderr (`G2 ... raised = []`). Рекурсии нет: в `logger_module` нет root-handler'а stdlib -> framework (git grep `addHandler` по `multiprocess_framework`: ноль), `ctx.log_*` — `functools.partial(services.log_*)`.
- **Замки.** `_fire_states` во всех шести местах (`session.py:233,269,291,359,407,462`) зовётся после выхода из `with self._lock`; `on_stall`/`on_timing` — из потоков сторожа/владельца без замков; `_profile.lock` держится только на секциях `dict` (`profiles.py:_set/_fail/apply_*`), порт и логгер под ним не зовутся. Порядок: `_events_lock -> _profile.lock`, `_events_lock -> {HealthState._lock, breaker, send_async}`; обратных рёбер нет; `_timing_lock` и `_lock` плагина — листья. Инверсии нет. Стресс: `_TICK_S=0`, 1 поток `produce`, 3 потока `_sync_events`, 12 циклов take/release, join-дедлайн 60 с -> без зависания, 56 merge, последний `state`/`device_held` в дереве равны сеансу (`A ok: merges 56 state closed`).
- **produce не блокируется apply.** `set_param` с `sleep(0.4)`, `_TICK_S=0`: `take=0.41s`, 157 вызовов `produce`, худший `0.7 ms`. Замок профиля на время записи не держится.
- **Дедуп/общие объекты.** `session.params` -> `dict(...)`, `params_status` -> `{k: dict(v)}` (копия на 2 уровня), `param_errors` -> `dict(...)`, `capabilities` -> `sorted(...)` — свежие объекты каждый вызов; снимок в `_published` с сеансом общего не имеет; `TreeStore.set` копирует (`_deep_copy`); дальше снимок никто не меняет. Пропущенной смены из-за общего объекта нет.
- **Инциденты.** `busy -> closed -> busy` -> 2 инцидента `camera_device.session`, `degraded` 2 раза, `set_status("ok")` 1 раз (scratch `F`). `set_status("ok")` чужой degraded не снимает: у `HealthReporter` заявки по владельцу (`state.py:423-458`); чужая заявка `other_plugin` пережила выход из отказа: `F2 snapshot: degraded other-source down`. `_seen_state` и `_reported_param_errors` меняются только внутри `_events_lock`.
- **Потоки.** `git grep -n "threading.Thread\|KeyedExecutor\|ThreadPoolExecutor\|Thread(" -- Services/camera_device/plugin_base.py` -> exit 1, совпадений нет.
- **session.py не тронут.** `git diff 28720c500 HEAD --stat -- Services/camera_device/session.py Services/camera_device/profiles.py` пусто; `git grep readiness -- plugin_base.py` -> exit 1. `state`/`device_held`/`last_error` сеанса не менялись.
- **Единицы.** `open_ms`/`get_frame_ms` пишутся в секундах (`record_timing`, `plugins/base.py:720`), имя названо планом — известное расхождение имени и единицы, не находка.
- **Тесты.** `test_plugin_observability.py` через gate x5: `6 passed` в 4.44 / 4.35 / 4.37 / 4.35 / 4.38 с (5 из 5 зелёных).

## Что осталось открытым / ненадёжно

- **Перекрёстные строки журнала при 2+ сеансах в процессе** (вне FILES, решение лида). Scratch `GDUP`: журнал B получил 2 строки сеанса A (`B before: 2, after A starts: +2`). Мост на общем модульном логгере принципиально не различает сеансы. Штатный путь framework для stdlib-стиля — `get_std_logger` из `logger_module/adapters/std_facade.py` вместо `logging.getLogger` в `session.py` (один писатель, без моста и без жизненного цикла handler'а; у modbus — `propagate=False`, `Services/modbus/sdk/client.py:129-160`). Сейчас мост `propagate` не отключает и ставит уровень INFO навсегда: при root-handler'е (`basicConfig`) INFO-строки идут и в root — не воспроизводил.
- **Отказ rest (reopen) без инцидента** (вне FILES: в `session.py` нет хука; DESIGN 2.3b перечисляет «отказ rest»). Виден только в `errors` и WARNING. Исполнитель это раскрыл.
- **Корень находок 5 и 6** — `session.py` (нет номера цикла; нет `on_state` при снятии `_held` в отказе).
- **Не проверено:** (а) медленный `merge` под `_events_lock` блокирует `produce`: на двойнике с `sleep(0.2)` худший `produce` = `154 ms` (`B2`); в проде `StateProxy._send` -> `router.send_async` (fire-and-forget), не мерил на настоящем router. (б) Гипотеза без воспроизведения: ≥5 новых ключей `param_errors` за один `_sync_events` = 5 подряд `report_error` -> breaker процесса (порог `DEFAULT_FAIL_THRESHOLD = 5`, `breaker.py`) -> `degraded` до `record_success` из `source_producer.py:215`. (в) Тест 1 идёт на `frame_period_s=0.012` (~78 кадр/с), а не на номинальных 50: номинал на macOS даёт 84 кадра за 2 с < 90 (замер исполнителя, не перемерял); Windows (где живёт стенд) не проверял. (г) Стенд 6.1 (`state_get`, `telemetry_snapshot`) не выполнялся.
- **Мои мутанты** — 4 штуки + контроль, подмена методов класса через pytest-плагин; мехпрогон лида в `cam-2-3b-inj` не трогал и результата не видел. Совпало с прогнозом J3/J8; `param_errors`-инцидент и сверка из тика — сверх прогноза.
- **Стресс-тест** не доказывает отсутствие взаимоблокировок; доказательство — прочитанный порядок замков (выше) по `session.py` и `profiles.py`.
- README: запись про липкий `_item_error` и дедуп журнала (TRAPS) — вне FILES, не сделана.
