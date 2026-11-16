# Task 2.3c — ревью Opus (код `2958ae084`, дерево `cam-2-3c-dev`, HEAD `537d736c0`)

Не коммитил, код не правил. Специализации: архитектура, контракт модуля (lite), конкурентность, безопасность.
memory hits: `scripts/memory/search.py camera apply_params register deepcopy stats lock` и `… probe copy partial write access_level validate` -> релевантных уроков нет (ближайший — `feedback_model_copy_does_not_validate.md`, про `model_copy(update=)`, не этот механизм).
qex не использовал: поиск — `git grep` по точным символам.
Скрипты: `scratchpad/rev23c/repro.py` (воспроизведения), `scratchpad/rev23c/mutate.py` (мои мутации M1, M9 на копиях `scratchpad/rev23c/m1`, `m9`).

## Вердикт

**CHANGES REQUESTED (итерация 1 из 2).** Блокеров (`security`/`spec`) нет. Две находки уровня major: пакет `apply_params` пишется частично без второго писателя (`architecture`); гарантию «журнал без значений» не держит ни один тест (`tests`, мутация выжила). Остальное — minor.

## Прогоны (все через `machine_gate.sh … inspector-bottles-20`, `PYTHONPATH=<дерево>`, `.venv/bin/python`)

| Команда | Итог |
|---|---|
| Путь импорта из того же cwd | `…/cam-2-3c-dev/Services/camera_device/{commands,plugin_base}.py`, `…/cam-2-3c-dev/multiprocess_framework/__init__.py`; pydantic 2.13.2 |
| `test_plugin_commands.py` + `test_plugin_commands_hazards.py`, 5 раз подряд (light) | `60 passed` ×5 (2,60–2,65 с) |
| `Services/camera_device/tests`, 2 раза (medium) | `321 passed, 10 skipped` ×2 (44,1 с / 43,9 с) |
| `ruff check -q` на 4 файлах | exit 0 |
| `sentrux check .` | `43 rules checked … ✓ All rules pass` |
| `secrets_audit.py --format json --root Services/camera_device` | exit 0, `"total": 0` |

## Блокеры

Нет.

## Находки (CHANGES REQUESTED)

1. **[Services/camera_device/plugin_base.py:673-679] [architecture, major]** — Проблема: фаза до записи не повторяет все проверки писателя. `set_field_value` сначала зовёт `validate_field_value(access_level=0)` (`registers_module/core/manager.py:202`; `FieldMeta.validate_value` -> `can_modify`, `field_meta.py:407`), а проба `model_copy(deep=True).apply_values` права доступа не проверяет. Шаг (4) смотрит только `meta.readonly`. Поле из `bindings()` с `FieldMeta(access_level=1)` проходит пробу и падает на записи — после записи предыдущих полей, без всякого второго писателя.
   Воспроизведение (`repro.py access`, подкласс register'а с привязанным `gain: FieldMeta(access_level=1, apply="live")`):
   `{"params": {"exposure_time": 900.0, "gain": 2.0}}` -> `{'success': False, 'error': 'Недостаточно прав доступа: требуется уровень 1, передан 0', 'applied': ['exposure_time']}`, `reg.exposure_time after: 900.0`.
   Ложны docstring (`:657`), README «Команды» («при отказе ничего не записано»; «остаточный случай: значение … изменил другой писатель») и строка DESIGN (то же). Сегодня скрыто: у 4 полей `FAKE_BINDINGS` `access_level=0`. Вендорский register (5.x) это откроет.
   Исправление: в шаге (4) проверять `meta.can_modify(0)` вместо `meta.readonly`: readonly -> прежний текст `поле только для чтения: <имя>`; `access_level > 0` -> свой текст без значения (например `поле требует уровень доступа <N>: <имя>`). Тест: подкласс как выше; ответ без `applied`, `reg.exposure_time == 10000.0`, шпион `set_field_value` пуст. Это пробел DESIGN (там названо только `readonly`): лиду — поправить строку (4) задачи.

2. **[Services/camera_device/tests/*] [tests, major]** — Проблема: гарантию OBSERVABILITY и DESIGN «лог `apply_params fields=[…] ok=` без значений полей» не держит ни один тест. Моя мутация M9 (`self._log_apply(applied, True)` -> `self._ctx.log_info(f"… fields={params} ok=True")`, в журнал идут значения) -> `60 passed` (прогноз до прогона: все зелёные). Исправление: тест-шпион на `ctx.log_info`/`log_error`: пакет `{"exposure_time": 123456.0}` (и отказ `{"trigger_mode": "SECRET-42"}`) -> в строках журнала есть `apply_params fields=['exposure_time'] ok=True`, нет `123456` и `SECRET-42`.

## Замечания (minor, не держат вердикт сами по себе)

3. **[tests, низкий вред] окно `fps` после сброса** — мутация M1 (в `cmd_reset_stats` убрано `self._tick_t0 = time.monotonic()`) -> `60 passed` (прогноз: все зелёные). Слепой тест сам ставит `_tick_t0` после сброса и этим маскирует строку. Вред мутанта: первое окно после сброса делит кадры после сброса на время с прошлого окна — `fps` занижен, но `>= 0`. Тест без подмены часов (урок `feedback_global_clock_patch_flake.md`): `_tick_t0 = monotonic() - 100` до сброса, `reset_stats`, один кадр, `monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)`, `produce()` -> `fps > 0.5` (мутант даёт ~0,01).

4. **[plugin_base.py:643, 492] [quality] гонка публикации `frames`** (открытый пункт автора) — воспроизведено детерминированно (`repro.py publish_race`: публикация `("frames", 1)` из `produce()` задержана, между ней — `reset_stats`): порядок публикаций `[0, 1]`, при этом `_frames = 0`, `reg.frames = 0`; следующий `produce()` без созревшего окна значение не правит (`[0, 1]`). В дереве — устаревшее `1` до следующего учтённого кадра (~20 мс при 50 кадрах/с) или до окна `_TICK_S` (≤ 1 с), если `produce()` идёт; в паузе процесса — до возобновления. `get_status`, `reg.frames` и счётчик согласованы (0). Вред малый: уровень, не событие; сборщик тика публикует последнее значение. Рекомендация: принять, строка в README «Команды» («метрика `frames` после `reset_stats` может до одного кадра/окна показать прежнее число»). Перенос `publish_metric` под замок дёшев (запись — одна вставка в dict под замком, `plugins/base.py:908`), но противоречит DESIGN и тесту H3 — решать лиду, не автору.

5. **[plugin_base.py:68-70] [quality] мёртвые константы** — `_START_TIMEOUT_S`/`_STOP_TIMEOUT_S` больше никто не читает: `git grep -n "_START_TIMEOUT_S\|_STOP_TIMEOUT_S" -- . ':!.claude/worktrees'` -> только определения `plugin_base.py:69-70`, строка docstring `commands.py:16` и отчёты. Комментарий «Срок ожидания `start`/`stop` в командах плагина» теперь ложен; умолчание живёт в двух местах (`Field(5.0…)` и константа). Исправление: константы перенести в `commands.py` и взять их умолчаниями `Field(_START_TIMEOUT_S, …)` (`plugin_base` уже импортирует `commands`, цикла нет), либо удалить и сослаться на `commands.py`. Учесть 2.3d: её `_CALL_TIMEOUT_S` планировали «рядом с `_START_TIMEOUT_S`».

6. **[quality] `on_device: True` без записи на прибор** — по формуле DESIGN верно, но имя обещает больше. Воспроизведение (`repro.py on_device`, при захвате): то же значение `{"exposure_time": 10000.0}` -> `on_device: True`; `{"trigger_mode": "On"}` при `trigger_managed=False` -> `on_device: True`; `set_param` после обоих: `[]`. Тест H11 закрепляет второй случай как `True`. Исправление: строка в README («`on_device` не обещает записи: шаг, не меняющий план (то же значение, закрытый `enabled_if`), прибор не трогает; итог — `read_params`»). Код не менять без решения лида.

7. **[framework, вне FILES, существовало до задачи] значение в тексте отказа диапазона** — `repro.py access`: поле `black: FieldMeta(max=20)` из `bindings()`, `{"black": 77777.0}` -> `{'success': False, 'error': "Value error, Поле 'black': значение 77777.0 больше максимального 20"}`. Источник — `data_schema_module/core/schema_base.py:88,90` (и `field_meta.py:411,413`), вопреки собственному ADR-DS-010 («текст без введённого значения»). Только числа (`isinstance(int, float)`): строка-секрет в этот текст не попадает, класс SECRET-42 не задет. У привязанных полей базового register'а `min`/`max` нет — сегодня скрыто. Ещё: `set_field_value` пишет значение в DEBUG (`manager.py:222`). Для 2.3c: сузить фразу README «введённое значение в ответ и в журнал не попадает» до модели аргументов; framework — отдельной строкой в `docs/claude/OPEN_QUESTIONS.md` (лиду).

## Проверено и верно (с воспроизведением)

- **Единственный путь на прибор.** В `cmd_apply_params` нет `session.apply`, `self._reg.x = v`, порта и ящика (чтение `:654-697`). H10 + L1 (лид) это держат. `apply_params` зовёт `ctx.registers.set_field_value` -> `_notify_observers` -> `_on_field_update`. `PluginOrchestrator._on_register_update` — путь `register_update` GUI, не этой команды; отход слепых тестов от слова ACCEPTANCE оправдан, тесты не вакуумны (журнал получает `set_param`).
- **Порядок проверок** модель -> `ctx.registers` -> `bindings()` -> `readonly` -> проба — по коду и H8.
- **Проба на копии** (`repro.py copy_cost`): 12,1 мкс на вызов, оригинал `exposure_time=10000.0`, подписчик менеджера от пробы — `[]`. У `SchemaBase` нет приватных атрибутов и замков (`schema_base.py:56-61`), подписчики живут в `RegistersManager`, не в register'е: deep-копия безопасна и дешёва. Пробу и запись ведёт одна и та же последовательная `apply_values`: промежуточные состояния межполевых правил совпадают.
- **R2-1 не сломан** (`repro.py retry`, фейк `read_offset`): отказ подтверждения записан; тот же `900.0` через `apply_params` -> `on_device: True`, ровно один `set_param(ExposureTime, 900.0)`, ошибка снята.
- **Гонка «проба — запись»**: теряется только остаток пакета, ранее записанное остаётся (H7). Подмену `__dict__` pydantic при параллельных присваиваниях разных полей проверил (`repro.py dict_swap`, 20000 итераций, `setswitchinterval(1e-6)`): потерь `0`.
- **`_stats_lock` — листовой замок.** Под ним только целые и `self._reg.frames = …` (присваивание pydantic + `_check_field_constraints`, замков и подписчиков нет). Его берут `produce`/`_tick`/`_drop_frame` (поток процесса, других замков не держит) и `cmd_reset_stats` (системный поток). Вложенности с `_events_lock`, `_timing_lock`, `_plan_lock`, `_lock`, замком профиля нет ни на одном пути; `publish_metric`/`log_*` вне замка (H3 и чтение).
- **`reset_stats`**: `seq_id` продолжает счёт (6 и 7), `errors` сеанса не трогается, `get_status().frames == reg.frames == 0` (слепые тесты, H1).
- **`read_params`**: `session.params`/`param_errors` отдают копии под замком профиля (`session.py:205-217`). `repro.py read_params_mut`: правка ответа (`exposure_time = -1`, `param_errors["x"]`) -> следующий ответ прежний `{'exposure_time': 10000.0}`, `{}`.
- **`timeout_s`** (`repro.py timeout`): `"SECRET-42"` -> `{'status': 'error', 'device_state': 'closed', 'error': 'timeout_s: Input should be a valid number, unable to parse string as a number'}`; `nan`, `inf` -> отказ; `data=None` -> `ok`. Мягкий режим pydantic принимает `True` -> `1.0`, `"5"` -> `5.0`, `1e-9` — вреда нет, отмечаю.
- **Совместимость**: словарь `commands` и docstring класса дополнены только добавлением; раздел «Команды Р7» после `cmd_release_device`; ниже `cmd_get_status` не тронуто; собственных `cmd_` ровно 6 (+ унаследованный `cmd_set_config`); новых потоков нет (страж). `_tick` сдвигает окно до публикаций — поведение 2.3b не ломается (321 passed).
- **README «Команды»** сверен с кодом: формы ответов, `read_params`, `reset_stats`, `set_config` (`plugins/base.py:1839`, `apply_values`) верны; неверны две фразы — п. 1 и п. 7.

## Break-injection: сверка с отчётом лида (`…2.3c-injections.md`)

- L1, L3, L4, L5, L6 — согласен.
- L2 — согласен с объяснением расхождения, проверил по коду: одиночное `"abc"` отвергает `apply_values` внутри `set_field_value` (ответ отказа записи с `applied: []`); `SECRET-42` верхнего уровня отвергает модель; `params0` (`nope`) и H8 отсекаются раньше пробы. «Всё или ничего» держат смешанный слепой пакет и H5 `params1`/`params2`.
- Не согласен с выводом «выживших мутаций, оставляющих гарантию без теста, нет»: выжили мои M1 (окно `_tick_t0`, п. 3) и M9 (журнал без значений, п. 2). Прогнозы записаны до прогона: оба «все зелёные», совпало (`60 passed` у каждого; импорт из копии подтверждён путём `…/scratchpad/rev23c/m1|m9/Services/camera_device/plugin_base.py`).

## Что я оставил открытым / ненадёжно

- П. 1 и п. 7 воспроизведены на подклассе register'а, не на вендорском: настоящего register'а с `access_level`/`min`/`max` у привязанного поля в дереве нет. Насколько вероятен он в 5.x — не знаю.
- Гонку подмены `__dict__` не воспроизвёл (0 из 20000). Это не доказательство отсутствия: pydantic-core может отпускать GIL иначе на другой версии и платформе. Проверено только на macOS, pydantic 2.13.2.
- Вред гонки п. 4 в живом дереве (`state_get …camera_device.frames`) на стенде не смотрел; оценка — по коду `publish_metric` (`plugins/base.py:889-910`) и одной детерминированной пробе.
- `on_device` в состоянии `opening` и при `busy`/`error` руками не прогонял (только `grabbing`, после `release`, без сеанса).
- `sentrux` MCP `test_gaps`, codegraph и qt-mcp не использовал (qt-mcp не подключён; GUI не задет).
- Hazard-тесты на ожидании `join(0.2)` для «замок держит» детерминированы в зелёную сторону; в красную (мутант) зависят от планировщика — для доказательства мутаций лида этого хватило (L3: 5 красных).

## Для лида

- `docs/claude/OPEN_QUESTIONS.md`: «`SchemaBase._check_field_constraints` и `FieldMeta.validate_value` печатают введённое число в тексте отказа (`schema_base.py:88,90`, `field_meta.py:411,413`) вопреки ADR-DS-010; `set_field_value` пишет значение в DEBUG (`manager.py:222`)» — задача framework, не 2.3c.
- Строку (4) DESIGN 2.3c поправить: «не `readonly`» -> «`meta.can_modify(0)`» (п. 1).

## Раунд 2 (код `f0657174c`, 2026-11-17)

Не коммитил, код не правил. Скрипты раунда: `scratchpad/rev23c/r2/mutate2.py` (мутанты на копиях `r2/m1`, `r2/m9`, `r2/macc`, `r2/fix`, `r2/fixm1`) и `scratchpad/rev23c/r2/quantclock.py` (плагин pytest: `time.monotonic` с шагом 15,625 мс).

### Вердикт раунда 2

**CHANGES REQUESTED (итерация 2 из 2), одна находка.** Находки 1, 2, 5 закрыты, 3 закрыта по сути. Новый тест окна `fps` зависит от разрешения часов: при грубых часах он красный без всякой мутации. Это `tests` (major). Правка — две строки теста. После неё блокирующих находок нет.

### Прогоны (через `machine_gate.sh … inspector-bottles-20`)

| Команда | Итог |
|---|---|
| `test_plugin_commands.py` + `test_plugin_commands_hazards.py` ×5 (light) | `63 passed` ×5 (2,57–2,83 с) |
| `Services/camera_device/tests` ×2 (medium) | `324 passed, 10 skipped` ×2 (43,4 с / 43,6 с) |
| `ruff check -q` (4 файла), `ruff format --check -q` (3 файла) | rc 0 / rc 0 |
| `git grep -n "_START_TIMEOUT_S\|_STOP_TIMEOUT_S" -- Services Plugins multiprocess_framework multiprocess_prototype` | только `commands.py:16,31,32,40,46`; в `plugin_base.py` — 0 |

### Сверка по находкам раунда 1

| # | Как проверено | Итог |
|---|---|---|
| 1 (права поля) | `repro.py access`: `{"exposure_time": 900.0, "gain": 2.0}` -> `{'success': False, 'error': 'недостаточно прав для поля: gain'}`, `reg.exposure_time after: 10000.0`. Мутант `macc` (убрана проверка `can_modify(0)`) -> красный ровно `test_apply_params_поле_с_уровнем_доступа_отвергается_до_первой_записи` (62/1). Прогноз до прогона: тот же один тест | закрыта. Теперь шаги до записи повторяют все проверки `set_field_value`: `validate_field` = `can_modify` + `min`/`max`; `min`/`max` проверяет проба (`_check_field_constraints`) |
| 2 (журнал без значений) | мутант `m9` -> красный ровно `test_apply_params_журнал_без_значений_полей` (62/1); прогноз совпал | закрыта |
| 3 (окно `fps`) | мутант `m1` -> красный ровно `test_reset_stats_сдвигает_окно_fps_без_подмены_часов_после_сброса` (62/1); прогноз совпал | гарантия покрыта, но тест хрупок — находка R2-1 ниже |
| 4 (гонка `frames`) | README: строка «до одного кадра … или окна `_TICK_S` … прежнее число `frames`» | принято, как я рекомендовал |
| 5 (константы) | `git grep` выше; `Field(_START_TIMEOUT_S…)`, `Field(_STOP_TIMEOUT_S…)` | закрыта: одно место правды |
| 6 (`on_device`) | README: «`on_device` не обещает записи …» | закрыта |
| 7 (framework) | `OPEN_QUESTIONS.md` — строка от 2026-11-17; README сужен до модели аргументов и называет исключение `min`/`max`. `repro.py access`: текст `black` прежний (вне задачи) | закрыта для 2.3c |

Поправка в `…2.3c-injections.md` (M1, M9) и строка (4) DESIGN в `tasks/2.3c.md` на месте.

### Находка раунда 2

R2-1. **[Services/camera_device/tests/test_plugin_commands_hazards.py, `test_reset_stats_сдвигает_окно_fps_без_подмены_часов_после_сброса`] [tests, major]** — Проблема: между сбросом и вторым `produce()` проходят микросекунды. При часах с шагом 15,625 мс `elapsed == 0.0`, ветка `if elapsed > 0` (`plugin_base.py:389`) не публикует `fps`, тест красный на неизменённом коде. Такие часы — у `time.monotonic()` на Windows до Python 3.13 (`GetTickCount64`; в 3.13 переход на `QueryPerformanceCounter`). Проект закреплён на 3.12 (`pyproject.toml:5`, `>=3.12,<3.13`), команда TESTS задачи — `.venv/Scripts/python.exe`, то есть Windows.
Воспроизведение (симуляция грубых часов, не прогон на Windows): дерево `f0657174c` + `-p quantclock`, только этот тест -> `1 failed`, `assert ([])` (`fps` не опубликован).
Исправление: после `monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)` вставить `time.sleep(0.05)`, порог `fps[-1] > 0.5` заменить на `> 0.1`. Проверено на копии `r2/fix`: с грубыми часами `1 passed`, с настоящими `1 passed`; с мутацией M1 (`r2/fixm1`) — `1 failed` в обоих режимах (`assert ([0.00999531469623614] and 0.00999531469623614 > 0.1)`). Запас: оригинал краснеет, только если между сбросом и окном пройдёт больше 10 с; мутант даёт ~0,01.
Закрытие проверяется одним прогоном этого теста на Windows или здесь с `-p quantclock`, плюс мутантом M1.

### Что я оставил открытым / ненадёжно (раунд 2)

- R2-1 доказана симуляцией часов, не прогоном на Windows. Разрешение `time.monotonic()` в Windows/3.12 (15,6 мс) я знаю по документации CPython («What's New in 3.13», модуль `time`). Запуском на этой машине не проверял.
- Остальные тесты с порогами времени в этом файле на грубых часах я не гонял: под `quantclock` запускал только тест окна `fps`. Глобальная подмена часов задела бы `WorkerManager` и дала бы ложные красные (урок `feedback_global_clock_patch_flake.md`).
- Пункты «открыто» раунда 1 в силе: вендорского register'а с `access_level`/`min`/`max` у привязанного поля в дереве нет; гонку подмены `__dict__` не воспроизвёл (0 из 20000); `on_device` в `opening`/`busy`/`error` руками не гонял.
- Лид закоммитил мой отчёт раунда 1 в `f0657174c`. Этот раздел — правка рабочего дерева, не закоммичена.
