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
