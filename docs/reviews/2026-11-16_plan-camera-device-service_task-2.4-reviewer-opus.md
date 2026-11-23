# Task 2.4 (2.4a + 2.4b): ревью Opus после задачи (стадия 5)

**Дерево:** `cam-2-4b-dev`, ветка `feat/camera-2-4b`, HEAD `291a76817`. Коммиты 2.4: `c4af315e2` (2.4a), `a72e250d1` (2.4b); слепые тесты `6d511ca57`, `d67e1617c`.
**Роль:** reviewer (opus), только чтение. Ничего не коммитил и не правил, кроме этого отчёта.
**memory hits:** `search.py owner mailbox regrab subscribe --module camera_device` -> нет; `search.py subscribe register callback state tree` -> 8 уроков, ни один не про этот механизм.
**Репродукции:** `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/422fbc6b-1296-4c1b-8072-6402b3628f21/scratchpad/rev24/` (`repro_plugin.py`, `repro_session.py`, `test_rev_order.py`, `mut_nosort.py`, `mut_noreset.py`, `full.*.log`). Все запуски шли через gate, сессия `inspector-bottles-20`, python главного `.venv`, `PYTHONPATH=<дерево>`.

## Вердикт

**CHANGES REQUESTED (итерация 1 из 2).** Блокеров нет: механизм ящика, перезахват, состояние для readiness лида Ф и подписка работают. Две important-правки малы (одна итерация developer). Третья important — решение лида (её можно отдать следующей задачей).

## Находки

| # | Severity | Где | Вход -> наблюдаемый результат | Что сделать |
|---|---|---|---|---|
| 1 | important | `plugin_base.py:319-340` (`_tick`), `:342` (`_sync_events`), `:308-317` (`_on_timing`) | Настоящие `RegistersManager` + `StateProxy` (router-двойник -> `TreeStore`), `set_field_value("camera_device","exposure_time",900.0)`: `session.params` = 900 через **0,026 с**; дерево `...params.exposure_time` = 900 через **0,73 с**, если `produce()` зовётся каждые 20 мс. Без вызовов `produce()` за 3 с дерево = **10000.0** (старое значение); один вызов `produce()` -> 900.0. Путь публикации — только `_tick` из `produce()`: `on_state` при перезахвате не зовётся (так задумано), другого пути нет. Рецепт `camera_device_demo.yaml` не задаёт `run_gated: false`, поэтому при снятом `run_event` (система в `ready`/пауза) `SourceProducer` не зовёт `produce()` (`source_producer.py:157-163`) и дерево после живой правки **не обновляется никогда**. Стенд (ACCEPTANCE 9 2.4b) пройдёт только при системе в RUN. | Публиковать после применения правки из потока владельца: например, в `_on_timing` для `name in ("apply", "regrab")` звать `self._sync_events()` (merge только отличий; `_on_timing("apply")` приходит после снятия замка профиля, порядок замков не меняется). Либо решение лида: «только в RUN, не позже `_TICK_S`», и стенд обязан идти в RUN. Тест: дерево = 900 без вызовов `produce()`. |
| 2 | important (tests) | `session.py:719-724` (`_drain`, сортировка по позиции в `_run`) | Мутация «сортировки нет» (`mut_nosort.py`, подмена `DeviceSession._drain`): все 4 файла 2.4 — **41 passed** (ни одного красного). Мой тест `test_rev_order.py` (пакет: `trigger_source` пришёл раньше `trigger_mode`, исходно `TriggerMode=Off`): без мутации **1 passed**; с мутацией **1 failed**, `assert {'trigger_source': 'чтение не удалось: access'} == {}`. Свойство «родитель раньше потомка» несущее, но тестом не защищено. | Developer 2.4a: hazard-тест по образцу `test_rev_order.py` в `test_live_apply_hazards.py`. |
| 3 | important (решение лида; не блокер) | `plugin_base.py:217` (шаг только своего поля), `session.py:732-737` (`_replace_in_run`) | Фейк без `restart_regrab`, конфиг `trigger_managed: true, On, SelfTrigger, trigger_period_ms: 77`; `set_field_value(trigger_source, "Software")` -> перезахват пишет весь `_run`: `set_param` = `[TriggerMode On, TriggerSource Software, TriggerSelfTriggerPeriod 77, ExposureTime]`; `param_errors = {'trigger_period_ms': 'чтение не удалось: access'}` (узел периода закрыт при Source≠SelfTrigger). Это ложная ошибка узла и инцидент `camera_device.param`. Причина: шаг потомка в `_run` остался со `skip=None` от прежнего значения родителя. С `restart_regrab` ошибки нет (пишется только `TriggerSource`). Readiness лида Ф и стенд (фейк по умолчанию, `restart_regrab`) не затронуты. | Вариант: колбэк строит план своего поля И его потомков по `enabled_if` (с `skip`-шагами), чтобы `_replace_in_run` заменил и шаги потомков. Это расширение DESIGN 2.4b («шаг поля»), поэтому решает лид: сейчас или отдельной задачей до прибора без `restart_regrab` (ветка H1). |
| 4 | nit | `session.py:688-690` (`_execute`), `:574-592` (`_owner_main`) | `call(fn)`, где `fn` бросает наследника `BaseException`: ответ `(False, 'команда прервана')` за 0,011 с, но цикл завершается как штатный стоп: события `grabbing->closed`, `state=closed`, `device_held=False`, **`last_error=None`**. Readiness не отличит такой обрыв от `release_device`. Порт закрыт (`open_handles=0`). | Перед `raise` в `_execute` (или `except BaseException` в `_owner_main`) ставить `_last_error` и переход в `error`. Практически `BaseException` из `fn` бывает только при `KeyboardInterrupt`/`SystemExit`, поэтому nit. |
| 5 | nit | `plugin_base.py:308-317` | `_on_timing` обрабатывает `get_frame`, `open`, `apply`; `"regrab"` (его шлёт сеанс, `session.py:774`) отбрасывается: `grep -c -F '"regrab"' plugin_base.py` = 0. Длительность перезахвата не видна в наблюдаемости (OBSERVABILITY 2.4a). | `elif name == "regrab": self._ctx.record_timing("regrab_ms", seconds)` (имя — решение лида). |
| 6 | nit (tests) | `test_live_apply_plugin.py:328-356` (строка 7 слепого тестера) | Подтверждаю отчёт автора (M4): без `unsubscribe` в `shutdown` тест зелёный, потому что после `shutdown` сеанс в `closed` и `apply` и так отказывает. Свойство держит тест автора `test_после_shutdown_правка_не_доходит_даже_при_новом_захвате`. | Принять как есть; тестер в следующий раз проверяет `shutdown` с новым захватом. |

## Что проверено и держится (с числами)

1. **Ящик.**
   - `call` по сроку против владельца: 300 вызовов `call(fn, 0..9,5 мс)`: расхождений «ответ True <=> `fn` исполнена» — **0** (164 True, 136 «срок»).
   - `call` в цикле против `stop()`: 60 циклов, зависших `call` — **0**. Последний ответ приходит не позже возврата `stop()` (худший 0,0 мс). Ответы: «сеанс остановлен» 42, «сеанс не в захвате» 18.
   - Решение `committed`/`cancelled` принимают обе стороны под `self._lock` (`session.py:350-355`, `:668-674`). `_enqueue` после `_close_box` невозможен: и `box.closed`, и `state != grabbing` проверяются под тем же замком.
   - Исключение `fn` (`Exception`) цикл не роняет: тест автора зелёный. `BaseException` — находка 4.
2. **`_drain`/`_regrab`.**
   - Слияние (последнее значение), один `stop_grabbing` на пакет, живая запись без остановки, отказ `open`/`start_grabbing` -> `error` без лишних вызовов порта, `open_handles == 0`, стоп в окне перезахвата, `apply` в `opening`: всё это закрыто тестами тестера и автора. Все тесты зелёные (см. п.7).
   - Остаточное окно стопа (п.4 автора: стоп между проверкой и `start_grabbing`) — это микросекунды до `start_grabbing`, приемлемо.
   - Порядок групп `live` раньше перезахвата (п.6 автора) с текущим register'ом недостижим: единственное `live`-поле `exposure_time` не имеет `enabled_if`.
3. **Состояние для readiness лида Ф.**
   - Новых значений `state` нет. Перезахват `state` не меняет и `on_state` не зовёт (тест «окно перезахвата»).
   - Сброс `_last_error` в `start()` идёт только при создании нового цикла (`session.py:271-279`), под замком. Ошибку текущего цикла он не стирает: `get_frame`/`_fail`/`_cleanup` пишут её после сброса.
   - Мутация «сброса нет» (`mut_noreset.py`) -> **1 failed** (`test_live_apply_session.py:365`: `assert 'PortError kind=busy: open: busy' is None`). Смысл `device_held`, `errors`, `params` не изменился.
4. **Замки** (порядок построен чтением).
   - Колбэк подписки берёт только `session._lock` (коротко, без вызовов наружу).
   - Владелец: `session._lock` и `_profile.lock` — листовые. Под ними не зовутся колбэки, лог `ProfileRunner._fail` идёт после `with`.
   - Плагин: `_events_lock -> _profile.lock` (через `session.params/param_errors`); `_timing_lock` и `_lock` (слот) — листовые. Обратного порядка нет, инверсии нет.
   - Замер на фейке без `restart_regrab`, `open_delay_s=0.3`, правка `trigger_period_ms=60`: колбэк **0,08-0,10 мс**; `produce()` за окно перезахвата n=119-120, **худший 0,18-0,19 мс**, p99 0,11-0,12 мс (и при `_TICK_S=1.0`, и при `0.02`).
5. **Подписка 2.4b.**
   - Отдельные замыкания: свой `partial` на поле и на `configure`. `unsubscribe` идемпотентен: список обнуляется до снятия, `RegistersManager.unsubscribe` глотает `ValueError`. Повторный `configure` снимает старые подписки. `ctx.registers is None` -> один WARNING.
   - Колбэк идёт в потоке вызывающего `set_field_value`. Порт из потока колбэка, `produce` и теста не зовётся (тест строки 6).
   - Исключение колбэка -> `health.report_error(throttle=30.0)`, наружу не уходит.
   - `trigger_managed` (без привязки) не подписан. Проверено: `set_field_value(trigger_managed, True)` прибор не трогает. Следующие правки `trigger_mode/source/period` пишутся одним перезахватом (слились): `stop_grabbing, TriggerMode On, TriggerSource SelfTrigger, TriggerSelfTriggerPeriod 55, start_grabbing`. Обратное переключение (`false`) оставляет группу в приборе как есть до следующего `take_device`.
   - Для 1.0 этого достаточно при строке в README («флаг группы действует со следующей правки поля группы или со следующего `take_device`»). Полный план группы на смену флага — отдельная задача, если её попросит GUI.
6. **Сквозной путь до дерева:** см. находку 1 (0,73 с при `produce()` каждые 20 мс; без `produce()` — никогда).
7. **Тесты.**
   - Весь `Services/camera_device/tests`, 3 прогона подряд через gate (`medium`): **245 passed, 10 skipped** × 3 (38,0-38,1 с). Красных и флейков **0 из 3**.
   - Тайминговые тесты 2.4 за эти прогоны не падали. Флейк W2 `test_старт_прерван_стопом` (отчёт автора 2.4a) за мои 3 прогона не проявился.
8. **Потоки.** `git grep -nE "threading\.Thread|KeyedExecutor|ThreadPoolExecutor" -- session.py plugin_base.py`: 4 строки, все в `session.py` (155, 172, 259, 455). Все четыре — аннотации типов. В `plugin_base.py` — 0. ALLOWLIST G6 не тронут: коммиты 2.4 не трогают `scripts/`.
9. **Чужие файлы.** `git diff 97e419e4c...HEAD --name-only`: вне `Services/camera_device/`, `docs/`, `plans/` — **0** файлов. По каталогам: `Services/camera_device` 3, `testing` 1, `tests` 4, `docs/reviews` 5. Файлы лида Ф не тронуты.

## Что осталось открытым / ненадёжно

1. **Стенд ACCEPTANCE 9 2.4b не прогонялся** (ни мной, ни автором). Живой путь `_message_processing_loop` -> `_on_register_update` -> колбэк проверен только в тестах, где вызов идёт вручную. Ожидание стенда — находка 1: в RUN значение придёт не позже `_TICK_S` (~1 с); в паузе не придёт никогда.
2. **Атрибуция ошибок `SourceProducer`** (`source_producer.py:166-171`): итерация `produce()` считается неуспешной, если `health.error_count` вырос за время вызова. `report_error` из колбэка подписки (системный поток) может попасть в это окно и засчитаться чужой итерации `produce()` (корм breaker'а). Тот же класс уже есть у `_on_stall`/`_sync_events` из `on_state`. Не воспроизводил. Не проверял, увеличивает ли `report_error(throttle=30)` счётчик при подавлении.
3. Находку 3 проверил только для пары `trigger_source -> trigger_period_ms`. Обратный случай не воспроизводил: при `take_device` с `Software`, затем `SelfTrigger` период не пишется ни в одном режиме, и прибор работает со своим периодом, а не с register'ом. Причина та же.
4. Гонку «`cancelled` между `popleft` и `committed`» детерминированно не воспроизвести. 300 вызовов с малым сроком дали 0 расхождений: это статистика, не доказательство. Доказательство держится на замке (чтение кода).
5. `fn` из `call` не обёрнута `_port_call`: зависшая команда 2.3c не видна сторожу (п.5 автора). Это вопрос к 2.3c, не к 2.4.
6. qex не использовал (свежесть индекса не проверял): поиск шёл через `Grep`/`Read` по известным путям. `sentrux check .` не запускал: новые импорты только из stdlib (`collections.deque`, `functools`, `collections.abc`, `typing`), слои не меняются. Проверка границ — ручная.
7. `secrets_audit.py` не запускал: класс «секреты» в диффе не затронут (новых конфигов и ключей нет). Тексты ошибок колбэка значений не содержат: `skip=<причина>`, `report_error(exc)`.
8. Все замеры — на фейке и на одной машине (Mac). Реальный GigE `open` 1-3 с в перезахвате и `release_device` с `_STOP_TIMEOUT_S=2.0` (п.7 автора 2.4a) не проверены.

---

# Раунд 2 (HEAD `525e1d5ee`; правки `aabb32961`, тесты порядка `ed1d70e91` через слияние `37d15d5ff`)

**Скрипт репродукций:** `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/422fbc6b-1296-4c1b-8072-6402b3628f21/scratchpad/rev24/repro_r2.py`. Логи прогонов: `r2full.*.log` в том же каталоге. Все запуски шли через gate, сессия `inspector-bottles-20`.

## Вердикт раунда 2

**APPROVED.** Находки 1, 2, 3 и 5 раунда 1 закрыты, каждая подтверждена запуском. Правка находки 3 добавила одну новую important-находку (R2-1): повтор того же значения после отказа записи не доходит до прибора. Механизм, readiness лида Ф и стенд она не ломает, поэтому это не блокер. Рекомендую закрыть её одной строкой до ff main. Если не успеваете — внесите в `OPEN_QUESTIONS` или в следующую задачу.

## Проверка правок раунда 1

| # раунда 1 | Вход -> наблюдаемый результат | Итог |
|---|---|---|
| 1 (дерево) | Настоящие `RegistersManager` + `StateProxy` (router-двойник -> `TreeStore`). После публикации снимка `produce()` больше **не зовётся**. `set_field_value(exposure_time, 900.0)` -> дерево `params.exposure_time == 900.0` через **0,0028 с**, `params_status = {'verified': True, 'rc': None}`. Пауза системы для плагина — то же самое: `SourceProducer` не зовёт `produce()`. Поэтому публикация не зависит от паузы: дерево пишет поток владельца из `_on_timing`. | закрыто |
| 2 (порядок) | Мутация «сортировки нет» (`mut_nosort.py`) на 4 файлах 2.4: **2 failed, 53 passed**. Красные: `test_live_apply_hazards.py:591` (пакет с `restart_regrab`) и `:639` (режим раньше источника). Третий тест (`:604`, без `restart_regrab`) остаётся зелёным, и это **ожидаемо**: без `restart_regrab` `_regrab` пишет весь `self._run` (`session.py:763`), а порядок там держит позиция шага в плане (`_replace_in_run`). Сортировка пакета на эту ветку не влияет; тест сторожит другое свойство (порядок `run` после замены). | закрыто |
| 3 (родитель/потомок) | Без `restart_regrab`: SelfTrigger -> Software -> `set_param = [TriggerMode On, TriggerSource Software, ExposureTime]`, период в закрытый узел **не пишется**, `param_errors = {}`. Старт с Software (узел периода = 300) -> SelfTrigger -> пишется `TriggerSelfTriggerPeriod 77`, узел = 77, `param_errors = {}`. С `restart_regrab`, старт с Software -> SelfTrigger: `[TriggerSource SelfTrigger, TriggerSelfTriggerPeriod 77]`, `open = 0`. MVS-набор (`read_back, node_describe, software_trigger`): обе стороны в обоих стартах дают `param_errors = {}`, период пишется только при SelfTrigger. Там же `exposure_time = 1500.0` (live без `live_write`) -> один перезахват `stop_grabbing, close, open, весь run, start_grabbing`, `params.exposure_time = 1500.0`. | закрыто |
| 5 (`regrab_ms`) | `plugin_base.py:349` пишет `record_timing("regrab_ms", seconds)`. Тест `test_live_apply_wiring.py:263` его проверяет и зелёный во всех прогонах. | закрыто |

## Новые находки

| # | Severity | Где | Вход -> наблюдаемый результат | Что сделать |
|---|---|---|---|---|
| R2-1 | important (не блокер) | `plugin_base.py:221` (`_changed_steps`: `old.get(step.field) != step`), `:245-247` (`_seen_values[field] = value` до записи) | Фейк с `read_offset={"ExposureTime": 5.0}`. Первая правка `exposure_time = 900.0` -> `set_param` 1 раз, `param_errors = {'exposure_time': 'не подтвердилось чтением'}`. Затем сбой снят (`read_offset` очищен), правка того же `900.0` -> `set_param` **0 раз**, ошибка в `param_errors` остаётся. До раунда 2 повтор писал в прибор. Оператор не может повторить отказавшую запись тем же значением: нужно поставить другое значение и вернуть прежнее. Тот же класс — отказ узла в плане `run` при `take_device`, затем ввод того же значения. | Свой шаг поля включать, если `value != before` **или** поле есть в `session.param_errors`. Так повтор после отказа запишется, а дубль без отказа не вызовет лишнего перезахвата restart-поля (1-3 с на GigE). Тест: отказ -> повтор того же значения -> один `set_param`. |

## (6) Порядок замков после `_sync_events` из потока владельца

Порядок построен чтением кода и подтверждён замером:

- **Поток владельца.** `_on_timing("apply")` зовётся в `ProfileRunner.apply_step` после выхода из `with self._state.lock` (`profiles.py:146-147`). `_on_timing("regrab")` зовётся в `finally` блока `_regrab` (`session.py:774`), там `session._lock` не взят. `_drain` зовёт `_regrab` вне замка. Значит, владелец входит в `_events_lock`, не держа ни одного замка. Внутри берутся `_profile.lock` (лист, через `session.params/param_errors`), замки health и `StateProxy` — так же, как раньше из `on_state` владельца.
- **Поток `produce()` и командный поток** (`on_state` из `start`/`stop`): `_events_lock` -> `_profile.lock`, тот же порядок.
- **Обратного порядка нет.** Никто не берёт `_events_lock`, держа `_profile.lock` или `session._lock`. Ни один держатель `_events_lock` не ждёт владельца: `stop()` ждёт `exited` после выхода из `_sync_events`. Цикла нет, инверсии нет.
- **Замер** (фейк без `restart_regrab`, `open_delay_s=0.3`, `_TICK_S=0.02`, правка `trigger_period_ms=60`): `produce()` n=366, худший **0,49 мс**. `_sync_events` из потока владельца — 5 вызовов за перезахват, худший **0,09 мс**. Владелец ждёт `_events_lock` не дольше одного `merge` соседа: это задержка, а не блокировка.
- Проверка `session.state == "grabbing"` идёт без замка. Гонка с `_fail` безопасна: в худшем случае лишний `_sync_events`, который `merge` отличий схлопнет.

## (3) Трактовка автора `_seen_values`: согласен, дыры описаны

Сравнение двух полных планов (поле со старым и с новым значением при прочих текущих значениях register'а) верно отделяет шаги, которые меняет именно эта правка. Несвязанные поля с `apply` `None`/`config` в пакет не попадают. Дыры:

1. **R2-1** (выше): равенство планов глушит и повтор после отказа.
2. **Правка между `_plan()` и сбросом `_seen_values` в `cmd_take_device`** (`plugin_base.py:550-556`), если правка идёт из другого потока. План `run` собран без нового значения, `apply` в `idle`/`closed` отклонён, а `_seen_values` уже считает значение записанным. Повтор того же значения тогда не запишется (R2-1). Нужны два потока; в процессе `register_update` и команды идут одним потоком обработки сообщений. Не воспроизводил.
3. **Две правки одного поля из разных потоков.** Обмен `before`/`seen` атомарен под `_plan_lock`, но `_changed_steps` и `session.apply` идут вне замка. Порядок двух `apply` может перевернуться: прибор получит старое значение, а `_seen_values` — новое, и из-за R2-1 повтор не исправит. Тот же довод про один поток сообщений. Не воспроизводил.
4. **`set_cycle` отклонён** (`device_held`): `_seen_values` не сбрасывается. Это верно: план идущего цикла не менялся, а живые правки вошли в `_run` через `_replace_in_run`.

Правка R2-1 закрывает последствия пунктов 2 и 3 (повтор снова доходит до прибора), поэтому отдельных правок для них не прошу.

## (5) Прогоны

- `Services/camera_device/tests`, 3 раза подряд через gate (`medium`): см. таблицу ниже.
- Ожидание лида было 256 passed, наблюдаю 259. Разница +3 — тесты, пришедшие слиянием (`a7fd80144`, `ed1d70e91`): hazards 26 тестов, wiring 13. Это не дефект.

| Прогон | Результат |
|---|---|
| `Services/camera_device/tests`, прогон 1 | 259 passed, 10 skipped (41,16 с) |
| прогон 2 | 259 passed, 10 skipped (41,44 с) |
| прогон 3 | 259 passed, 10 skipped (41,15 с) |
| `Services/hikvision_camera/tests` | 287 passed, 15 skipped (2,62 с) |

Красных и флейков 0 из 3.

## Что осталось открытым / ненадёжно (раунд 2)

1. **R2-1 не исправлена.** Решение за лидом: одна строка до ff main или запись в `OPEN_QUESTIONS`.
2. **Стенд ACCEPTANCE 9 2.4b по-прежнему не прогонялся.** На плагинном уровне дерево обновляется за 0,003 с без `produce()`. Живой путь `_message_processing_loop` -> `_on_register_update` не проверен.
3. **Пункты 2 и 3 трактовки `_seen_values`** (гонки двух потоков) не воспроизводились. Довод «один поток сообщений» взят из докстринга сеанса (`session.py:17-20`), транспорт я не проверял.
4. **Атрибуция `report_error` в `SourceProducer`** (п.2 раунда 1) стала вероятнее. Новые ключи `param_errors` теперь шлют инцидент из потока владельца сразу после правки, то есть, возможно, во время вызова `produce()` соседним потоком. Не воспроизводил.
5. **Пауза системы проверена косвенно.** Я не вызывал `produce()`, а настоящий `SourceProducer` со снятым `run_event` не запускал.
6. **Мутацию R2-1 не прогонял:** теста на неё нет. Наблюдение основано на репродукции выше.
7. **Только фейк, одна машина (Mac).** Не повторял для раунда 2: qex, `sentrux check .`, `secrets_audit` (новых импортов нет: `Step` из `.params`).
