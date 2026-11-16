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

---

# Раунд 2 (последний)

Проверен коммит `506883f14` (код и тесты автора); `20c933444` — docs. `Services/` после `506883f14` не менялся, `session.py` и `profiles.py` не тронуты.
Вердикт: **APPROVED**. Блокеров нет. Остались: nit J9 (нужен тест, 10 строк) и два пункта «открытого» (5, 6), у пункта 6 есть потребитель — хаб 4.6a.

## Закрытие пунктов раунда 1

| П. | Было | Стало (вход -> наблюдаемый результат) | Статус |
|---|---|---|---|
| 1 | мутанты выживали, мост и уровни без тестов | 10 новых тестов (6 -> 16). Мутанты `-p mutplug`: см. таблицу ниже, все целевые красные | закрыт |
| 2 | `profile="rest"` при отказе открытия | busy -> `release`: дерево `state=closed profile=None`, порт `['acquire','enum_devices','open','release']` (scratch `D state closed profile None`); штатный цикл: `run` на grabbing, `rest` после release (тест автора) | закрыт |
| 3 | `shutdown` без `try/finally`, мост можно повесить дважды | `shutdown` в `try/finally`; `_attach_log_bridge` при `_log_bridge is not None` выходит. Тест `test_мост_снимается_даже_если_release_бросил`; мутанты `no_finally`, `no_attach_guard` красные | закрыт |
| 4 | докстринг противоречил себе | `plugin_base.py:6` и `:22-25` переписаны: уровни без `merge`, прямой `merge` только у событий | закрыт |

Остаточное по п. 3: плагин создан и `_ensure_session` вызван, `shutdown` не вызван -> handler остаётся (scratch `GLEAK ... 3`). Защита от этого — только вызов `shutdown`; код так и задуман.

## Мутанты (тот же `mutplug.py`, `Services/camera_device/tests/test_plugin_observability.py`, 16 тестов)

| Мутант | Результат | Красные тесты |
|---|---|---|
| контроль: убран `flight_dump` в `_on_stall` | `1 failed, 15 passed` | `test_on_stall_вызывает_flight_dump_owner_stall` |
| снят diff (`_published` не запоминается) | `3 failed` | `test_сверка_без_смен_не_даёт_merge`, `test_ушедшие_ключи_словарей_снимаются_delete`, `test_настоящий_StateProxy_ушедший_ключ_снят_из_дерева` |
| заглушён `proxy.delete` | `2 failed` | `test_ушедшие_ключи...`, `test_настоящий_StateProxy...` |
| убран цикл `param_errors` в инцидентах | `1 failed` | `test_новый_ключ_param_errors_один_инцидент_param` |
| сверка из `_tick` отключена | `1 failed` | `test_тик_сверяет_события_без_on_state` |
| handler не снимается в `shutdown` (J11) | `2 failed` | `test_мост_логгера_доводит_строки_сеанса_до_ctx_и_снимается`, `test_мост_снимается_даже_если_release_бросил` |
| `shutdown` без `try/finally` | `1 failed` | `test_мост_снимается_даже_если_release_бросил` |
| без защиты `_attach_log_bridge` | `1 failed` | `test_мост_снимается_даже_если_release_бросил` |
| `profile` по старой формуле | `1 failed` | `test_профиль_при_отказе_открытия_не_rest_...` |
| `dropped` сброшен в 0 | `1 failed` | `test_битый_кадр_виден_в_dropped_и_уровни_несут_значения` |
| **J9: `health.set_status("ok")` -> pass** | **`16 passed` (выжил)** | — |

## J9 — nit; тест нужен

Выживает честно: ни один тест не проверяет выход из отказа. Свойство при этом названо автором («иначе `degraded` залипает») и проверяемо. Мой scratch-тест (`scratchpad/rev23b/test_j9.py`, не в дереве) без мутанта зелёный (`1 passed`), с J9 красный: после `release` статус остаётся `degraded`, `degraded_reason: 'camera_device: busy'`. Текст теста (10 строк) — для автора:

```python
def test_выход_из_отказа_снимает_degraded_но_не_чужую_заявку(make):
    rig = make(port=make_port(busy_for_s=60.0), real=True)
    hs = get_or_create_health_state(rig.services)
    assert rig.take()["device_state"] == "busy"
    assert hs.snapshot()["status"] == "degraded"
    rig.plugin.cmd_release_device({})
    time.sleep(0.2)
    assert hs.snapshot()["status"] == "ok", hs.snapshot()
    hs.degraded("other down", owner="other_plugin")
    rig.plugin.cmd_take_device({}); rig.plugin.cmd_release_device({}); time.sleep(0.2)
    snap = hs.snapshot()
    assert snap["status"] == "degraded" and "other down" in snap["degraded_reason"], snap
```
(`time.sleep(0.2)` лучше заменить на ожидание `rig.plugin._session.state == "closed"` с дедлайном.) Не блокер.

## Прогоны через gate

- `pytest Services/camera_device/tests` (medium): `202 passed, 10 skipped, 2 warnings in 26.90s`.
- `test_plugin_observability.py` x5 подряд: `16 passed` во всех пяти (5.88 / 5.90 / 5.85 / 5.90 / 5.91 с).
- Остальные тесты каталога без файла наблюдаемости (186 passed, 10 skipped): handler'ов моста на конец сессии `0` (`BRIDGES LEFT AT END: 0`). Проверка нужна, потому что `test_мост_логгера...` утверждает `len(_bridges()) == 0` на входе: утечка из другого файла сломала бы его.
- Повтор репродукций раунда 1 на новом коде: A (стресс, 54 merge, состояние в дереве = сеансу), B (`produce` худший `0.2 ms` при `set_param` 0.4 с), F2 (чужая заявка жива) — без изменений; D теперь `profile None`; C и E красные намеренно (п. 5, 6).

## Пункты 5 и 6 — влияние на потребителей

- **`readiness(ctx)` лида Ф — не затронут.** `plans/2026-10-18_camera-device-service/amendments.md:162`: «хватает `state`, `device_held`, `last_error` (чтения без замков, `session.py`)» — читает свойства сеанса, не дерево. Код `readiness` ещё не существует (`git grep -i readiness -- Services/camera_device` пусто), поэтому подтверждено по плану, не по коду.
- **Хаб 4.6a — затронут (опровержение формулировки «на потребителей не влияет»).** `docs/reviews/2026-10-18_device-hub-camera-integration.md:200-205`: `connect()` = владелец найден и `device_held is True` в снимке ДЕРЕВА; `is_connected` — то же; проверки `state` в `connect()` нет. Воспроизведение п. 6 на новом коде (3 прогона `scratchpad/rev23b/test_win.py`): после отказа `busy` в дереве `state=busy` и `device_held=True` с +0.000 с, `device_held=False` в дереве на +1.004 / +1.003 / +1.005 с, `session.device_held=False` уже сразу. Окно ≈ `_TICK_S` = 1 с (и дольше, если `produce()` не вызывается). Итог для хаба: до секунды после отказа `connect()` вернёт `True` при `state=busy`. Для 2.3b — nit (переходное состояние, в том же снимке `state=busy`); для 4.6a — риск, который надо записать в его задачу: либо `connect()` требует `state` вне `{busy, not_found, error}`, либо плагин синхронизирует события из `produce()`, пока опубликован отказ и `device_held` True (одна проверка в `produce()` до `_tick`).
- Прецедент: у `code_reader` (`Services/code_reader/plugin/sdk_plugin.py:139-143, 203-205`) тот же дефект «дерево застревало с device_held True» уже ловился ревью 6.3 и закрыт публикацией по смене `device_held` из `produce()`. Здесь тот же приём не применён (корень — `session.py:458-462`).

## Что осталось открытым / ненадёжно

- **J9 без теста** (nit, текст теста выше). Пока теста нет, `set_status("ok")` защищён только ручным репро.
- **П. 6 (`device_held` в дереве отстаёт ≈1 с после отказа)** — для хаба 4.6a, не для `readiness`. Нужно решение лида: условие `connect()` по `state` в 4.6a ИЛИ плагинная синхронизация из `produce()` (в FILES 2.3b, но автор оставил намеренно). Хаб в коде ещё не реализован: поведение хаба не воспроизводилось, воспроизведено только состояние дерева.
- **П. 5 (дедуп `param_errors` по ключу, не по циклу)** — второй take с тем же отказом не даёт нового инцидента (scratch `E`: 1 -> 1). Корень: нет номера цикла в `session.py`. Не исправлено.
- **Мост логгера на общем модульном логгере**: при 2+ сеансах в процессе строки одного идут в журнал другого (раунд 1, `GDUP`); `propagate` не отключается; уровень INFO остаётся после `shutdown`. Штатная замена — `get_std_logger` в `session.py` (вне FILES). Не менялось.
- **Отказ rest (reopen) без инцидента** — вне FILES (в `session.py` нет хука), DESIGN 2.3b его перечисляет. Не менялось.
- Не проверено: медленный `merge` под `_events_lock` на настоящем router (двойник 200 мс даёт `produce` 150.5 мс, в проде `send_async` не блокирует); гипотеза «≥5 новых `param_errors` за один `_sync_events` открывают breaker процесса (порог 5)» — без воспроизведения; Windows и стенд 6.1 не гонялись; тест 1 по-прежнему на `frame_period_s=0.012`, не на номинальных 50 кадр/с.
- Мои мутанты — подмена методов класса из pytest-плагина, не правка файлов; мехпрогон лида в `cam-2-3b-inj` я не видел, сверять с ним нечего. Стресс-тест замков не доказывает отсутствие взаимоблокировок: доказательство — порядок замков из раунда 1.
- README: запись про липкий `_item_error` и дедуп журнала (TRAPS) по-прежнему не сделана (вне FILES).
