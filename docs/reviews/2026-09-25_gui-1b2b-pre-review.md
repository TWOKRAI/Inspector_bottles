# Ревью 1b.2b-pre — RegistersManager.from_catalog строит копии регистров

- Ревьюер: reviewer (Opus), синхронно, 2026-09-25
- Ветка: feat/gui-1b2b-precondition, HEAD 19591164 (код 44982249 + 3b9d1042), база main 273bd274
- Скрипты воспроизведения: scratchpad/{parity,anno,div,mut,dispatch}.py (запуск: `cd <worktree> && PYTHONPATH=$PWD .venv/bin/python <script>`)

## VERDICT: REQUEST_CHANGES (правки только в тексте; код по DESIGN корректен)

## Что подтверждено запуском

| Проверка | Команда | Результат |
|---|---|---|
| Тесты из брифа | `pytest registers_module + test_catalog_registers_editing_acceptance.py -q` | `97 passed in 1.80s` |
| ruff | `ruff check -q registers_module + файл приёмки` | exit 0 |
| Дрифт сводных ADR | `python -m scripts.sync --check` | exit 0 |
| Паритет снимка на реальном каталоге (payload через `json.loads(json.dumps(...))`, как на границе) | `parity.py` | 57 плагинов, 43 с регистром, 43/43 копии построены; `model_dump(mode="json")` копии и оригинала: **0 расхождений** |
| Цели dispatch и метаданные | `dispatch.py` | 374 поля: `target_diffs=0 metadata_diffs=0` |
| Запись текущих значений обратно | `dispatch.py` | 1 расхождение: `otel_export.endpoint ''` — оригинал отвергает собственный дефолт (валидатор), копия принимает; снимки после записи равны |
| Общие mutable-дефолты | `mut.py` (один и тот же dict payload в два менеджера, без JSON) | `A.default_line_color.append(999)` → B `[0, 255, 255]`, `FieldInfo.default` `[0, 255, 255]`, новый инстанс класса A `[0, 255, 255]` — не делятся |
| `object`/default_factory/register_dispatch в 43 регистрах | `parity.py`, `anno.py` | нет ни одного |

Итого для брифа: снимок `send_callback` у копии совпадает с оригиналом на всех 43 регистрах в состоянии по умолчанию и после записи валидных значений. Расходятся копия и оригинал на **записи** — пункты 1–2.

## Находки

### 1. [blocker, spec — утверждение в ADR и докстринге ложно] Копия не проверяет тип элементов контейнеров
Где: `DECISIONS.md` ADR-RM-007 «та же проверка типа/Literal/FieldMeta.min/max при setattr, что и на живом инстансе плагина»; `manager.py:33-36` (`_build_register_copy`) «setattr на копии проверяет тип/Literal/FieldMeta.min/max точно так же, как на живом инстансе».
Причина: кодек 1b.2a передаёт только теги `list`/`dict`, поэтому `list[int]`, `list[dict]` и `dict[str, str]` превращаются в голые `list`/`dict` (`anno.py`: `6 real: list[int] -> copy: list`, `3 real: list[dict] -> copy: list`, `1 real: dict[str, str] -> copy: dict`).
Вход → вывод (`div.py`), 10 полей в 7 регистрах:
```
blob_detector.contour_color_bgr=['x']: real=False copy=True | real value=[0, 255, 0] copy value=['x']
chain_executor.steps=[1]:              real=False copy=True | real value=[]          copy value=[1]
modbus_sink.payload=[1]:               real=False copy=True
overlay_draw.color_table=[1]:          real=False copy=True
otel_export.headers={'a': 1}:          real=False copy=True | real value={} copy value={'a': 1}
(+ center_crop.pad_color_bgr, circle_detector.circle_color_bgr, circle_draw.color_bgr,
   overlay_draw.default_line_color, overlay_draw.default_point_color — то же)
```
Сейчас оригинал в GUI (`from_registry`, `app.py:186`) такие значения отвергает, то есть с переходом на копию в 1b.2b фронтовая проверка этих полей станет слабее. Это надо записать как решение, а не оставлять незамеченным.
Исправление: сузить формулировку в ADR и докстринге. В «Ограничения» ADR-RM-007 добавить пункт: типы элементов `list[X]`/`dict[K, V]` не переносятся (кодек 1b.2a знает только теги `list`/`dict`), 10 полей / 7 регистров на 2026-09-25; туда же `unsupported → object`. Закрыть сам разрыв можно параметризованными тегами в `field_info.py`, но файл вне FILES — решение за лидом, место ему в 1b.2d. Желательно добавить тест с литеральным списком известных расхождений, чтобы закрытие разрыва было видно.

### 2. [blocker, spec — план] Список задачи 1b.2d указывает не на те регистры
Где: `phase-1b-recipe-service.md`, пункт 1b.2d: «Питоновские валидаторы `blur` (`kernel_size` нечётный) и `line_filter`».
- У `blur` регистра нет: `blur Plugins.processing.blur.plugin.BlurPlugin []` (register_classes пуст). Валидатор `kernel_size` висит на `BlurPluginConfig(PluginConfig)`, копия и форма регистра его не видят в принципе.
- Не упомянут `otel_export`: `VALIDATORS otel_export field: ['_endpoint_not_blank', '_endpoint_carries_signal_path', '_level_is_known', '_headers_only_env_placeholders'] model: ['_batch_fits_queue']`. Один из валидаторов **нормализует** значение, поэтому копия расходится с бэкендом не только на отказе:
```
otel_export.endpoint='  http://127.0.0.1:4318/v1/logs  ': real=True copy=True | real value='http://127.0.0.1:4318/v1/logs' copy value='  http://127.0.0.1:4318/v1/logs  '
otel_export.endpoint='http://127.0.0.1:4318': real=False copy=True
otel_export.endpoint='   ': real=False copy=True
```
- Контракт-тест 1b.2d «краснеет на регистре с `field_validator`/`model_validator`» покраснеет на `otel_export` в первый же день. Правила strip, «путь сигнала в URL» и «в headers только env-плейсхолдеры» вряд ли выразимы закрытым словарём `FieldMeta`.
- Фраза «расходятся только на питоновском model_validator» буквально верна для `line_filter`, но читается как общая; пункт 1 её опровергает для 7 регистров.
Исправление: в 1b.2d заменить `blur` на `otel_export` (5 валидаторов, из них один нормализующий), добавить типы элементов контейнеров из пункта 1, а у фразы про замер указать, что он сделан на `line_filter`.

### 3. [major, observability] Отказ сборки копии без `logger=` не виден нигде
Вход: payload с одной записью `field_name='model_dump'`; `RegistersManager.from_catalog(p)` без `logger=`, на корне stdlib logging стоит DEBUG-хендлер.
Вывод: строки `from_catalog: не удалось построить копию…` нет ни в одном приёмнике: `_call_manager_result` при пустом слоте `logger` возвращает `(True, None)` молча, это один из «трёх тихих допусков». Форма поля при этом видна (`fields: ['model_dump']`), а `set_field_value('bad','model_dump',1)` → `(False, "Регистр 'bad' не найден")`. Получается ровно тот тихий симптом, который задача устраняла, только теперь ещё и без диагностики. Единственный боевой образец конструктора, `app.py:186`, `logger=` не передаёт.
Исправление (одно на выбор): в ветке `except` дублировать в `get_std_logger(__name__).warning(...)`; или копить отказы в `manager.catalog_build_failures: dict[str, str]`, чтобы 1b.2b показал их оператору. Минимум — в ADR написать «пишется в лог только при переданном `logger=`» и внести передачу логгера в предусловия 1b.2b.

### 4. [nit] Докстринг `_build_register_copy` утверждает, что поле с ведущим `_` бросает исключение. Это неверно
Вход: поля `[('_secret','int',1), ('ok','int',2)]`, `connection_map={'p':'proc'}`, шпион на `send_callback`.
Вывод:
```
get_fields: ['_secret', 'ok']      model_fields: ['ok']        # поле молча стало private-атрибутом
set _secret=abc -> (True, None) stored: 'abc'                  # int-поле приняло строку, проверки нет
send_callback args: [('control_proc', 'p', '_secret', 'abc', {'ok': 2})]
```
Из настоящего каталога так не получить: `extract_fields` поле `_x` не отдаёт, pydantic делает его private. Опасность только для чужого или битого payload.
Исправление: поправить докстринг. Можно добавить защиту `if fi.field_name.startswith("_"): raise ValueError(...)`, тогда поломка уйдёт в ту же изоляцию per-plugin.

### 5. [nit] Докстринг hazard-теста (a): «имя из namespace `model_*` бросает ValueError» верно только частично
Вход: `_build_register_copy('p', [FieldInfo('p', n, int, 1)])` на pydantic 2.13.2.
Вывод: `model_dump`/`model_validate` → `ValueError … conflicts with member`; `model_fields`, `model_extra`, `model_copy`, `model_json_schema`, `model_computed_fields` → `built, in fields: True` (только UserWarning). Сам тест корректен, он использует `model_dump`.
Исправление: в докстринге назвать конкретные имена, которые конфликтуют с методами `BaseModel`.

## Что я оставил открытым и что в моей работе ненадёжно
- Break-injection не делал: матрица I1–I6 за лидом, я её не перепроверял. Широкий радиус 1855 тестов не запускал.
- Границу моделировал через `json.loads(json.dumps(payload))`, настоящий транспорт хаб → GUI не поднимал, живой стенд тоже.
- Не проследил, что происходит с расходящимся значением копии дальше: читает ли его сохранение рецепта или undo (`builders_binding._rm_old_value`, `registers_backend.get_value`). Пока нет 1b.2c (откат по вердикту бэкенда), GUI после отказа бэкенда хранит отвергнутое значение. Порча сохранённых данных не воспроизведена и не опровергнута.
- `TopologyBridge._validator.validate_field_command` не прослеживал: может быть, он ловит часть контейнерных случаев раньше бэкенда.
- qex не звал, свежесть индекса не проверял; все числа посчитаны скриптами и grep. Время `from_catalog` не перемерял, цифры 22.9/24.4/58.0 мс взяты у лида.

## Итерация 2 (2026-09-26, HEAD e8a06ee8; новые коммиты 65d1ac3f, e8a06ee8)

### VERDICT: REQUEST_CHANGES (итерация 2 из 2). Код принят, остались только текстовые правки, каждая проверяется грепом
Отдельный третий проход ревьюера не нужен: лид закрывает по командам приёмки в конце раздела. Если правки не пройдут, по правилам — эскалация к teamlead.

Тесты: `pytest registers_module + test_catalog_registers_editing_acceptance.py -q` → `98 passed in 1.80s`.

### (1) Находки итерации 1: что закрыто
Повторный прогон `div.py`, поля, где копия приняла значение, а оригинал отверг или переписал: `blob_detector.contour_color_bgr, center_crop.pad_color_bgr, chain_executor.steps, circle_detector.circle_color_bgr, circle_draw.color_bgr, modbus_sink.payload, otel_export.endpoint ×3, otel_export.headers, overlay_draw.color_table, overlay_draw.default_line_color, overlay_draw.default_point_color`. Каждое из них названо в ADR или в разделе плана (грепом: `center_crop`, `circle_*` и «путь адреса» есть в плане, остальное в обоих; «10 полей в 7» есть в обоих).
- №1 (контейнеры): **закрыто**, в ADR «Ограничения» и в докстринге `_build_register_copy`.
- №2 (план 1b.2d): **в фазовом файле закрыто, в `plan.md` нет.** `plans/2026-09-22_gui-service/plan.md:217` по-прежнему: «все правила регистра — описанием в `FieldMeta` (`blur`, `line_filter`)». Это противоречит `phase-1b-recipe-service.md:180` («`blur` сюда не входит»), а `otel_export` в строке нет.
- №3 (лог без `logger=`): **закрыто в коде.** Тест (f) проверяет наблюдаемый вывод; инъекцию лида I7 ревьюер не повторял. Побочный эффект описан в п.(3) ниже.
- №4, №5 (докстринги про `_` и `model_*`): **закрыто по существу**, но с новой абсолютной формулировкой, см. (2b).

### (2) Новые или оставшиеся ложные утверждения
Команда: `git diff 3b9d1042..e8a06ee8 -- . ':!docs/reviews' | grep '^+' | grep -iE 'идентич|точно так же|гарантир|невозможн|cannot|не может|недостижим|физически|никогда'`
- **(2a) [blocker, ADR] «`from_catalog` никогда не бросает наружу из-за одной записи»** (`DECISIONS.md:145`). Фраза стояла уже в итерации 1, я её тогда пропустил; в 65d1ac3f строка переписана. `FieldInfo.from_dict` вызывается ВНЕ `try`.
  Вход: payload из двух плагинов, у `bad` одно поле без ключа `type` → `RAISE KeyError 'type'`, и здоровый сосед `good` тоже не построен: менеджера нет вовсе. Поле-строка `'oops'` → `RAISE TypeError string indices must be integers`.
  Исправление (на выбор): сузить до «сбой `create_model`/инстанцирования одной записи не роняет сборку; битый `FieldInfo`-dict роняет»; или перенести `FieldInfo.from_dict` внутрь per-plugin `try`. Второй вариант — правка кода, по нему нужна инъекция лида.
- **(2b) [nit] «каталог физически не может произвести такое имя… сценарий недостижим через `from_catalog`»** (`DECISIONS.md:174-176`, `manager.py:58`, тест :15). Буквально неверно: в итерации 1 поле `_secret` прошло именно через `RegistersManager.from_catalog(p)` на ручном payload, `set_field_value('p','_secret','abc')` → `(True, None)`. Верно другое: команда `catalog.plugins` такое имя не выдаёт, потому что `extract_fields` читает `model_fields`. Исправление: «команда `catalog.plugins` не производит; чужой или битый payload — производит (воспроизведено ревью)».
- **(2c) [nit] Ссылка на `app.py`** (`manager.py:368`; тест :35, :258, :293). Там сказано «`app.py` строит catalog-менеджер без `logger=`». Проверка грепом: у `RegistersManager.from_catalog(` **0 боевых вызовов**, `app.py:186` зовёт `from_registry`. Исправление: «`app.py:186` строит `from_registry` без `logger=`; 1b.2b, скорее всего, повторит этот образец».
- **(2d) [nit] «форма из каталога видна, но пуста»** (`manager.py:372`, тест :36). Форма не пустая: `get_fields('bad')` → `['model_dump']`, поля показаны, не проходит только запись. Исправление: «форма видна, но правка не проходит».
- Слова «гарантия видимости» (ADR) и «НЕ гарантировано» (ADR :84) принимаю. Первое подкреплено тестом (f) и ранним буфером фасада (`std_facade.py:449`), второе — отрицание, подкреплённое пунктом 1.

### (3) `logger=` передан: двойная запись и исключение
Скрипт: `dbl.py` (случаи A и C) и `dbl_b.py` (случай B в отдельном процессе). Фейковый объект подставлен и как `logger=`, и как `LoggerManager._instance`.
- A: `logger=` передан, процессного LoggerManager нет → `raised: no`; 1 вызов `fake.warning` и 1 stdlib-запись `mpf.multiprocess_framework…manager`. Это два разных приёмника, не дубль.
- **B: `logger=` передан, и это тот же процессный LoggerManager (боевое сочетание в GUI) → `raised: no`, но запись ДВАЖДЫ в одном приёмнике:** `('warning', "from_catalog: не удалось…")` и `('log', WARNING, "from_catalog: не удалось…", 'multiprocess_framework…manager')`.
- C: `logger=` не передан, процессный LoggerManager есть → 1 запись `log`. Правильно.
- Побочное наблюдение: в общем процессе A→B ранняя запись из A слилась в LoggerManager из B при связывании (`_drain_early`). Это штатный механизм фасада, не дубль.
Оценка: [nit]. Одна строка на битый плагин при старте, исключения нет. Простейшее исправление: оставить один канал, `get_std_logger(__name__).warning(...)`. Фасад сам выбирает процессный LoggerManager, если он поднят, иначе stdlib и ранний буфер. `_log_warning` отличить «слота нет» от «доставлено» не может: `_log_checked` в обоих случаях возвращает `True`.

### Остаток находки 2
- **[blocker, план] `plan.md:217`**: заменить `(`blur`, `line_filter`)` на `(`line_filter`, `otel_export`; тип элементов `list`/`dict` — 10 полей)` так, как это уже записано в фазовом файле.

### Команды приёмки для лида (без третьего прохода ревьюера)
- `grep -n 'blur' plans/2026-09-22_gui-service/plan.md` → строка 217 не должна называть `blur` целью 1b.2d.
- `grep -n 'никогда не бросает' multiprocess_framework/modules/registers_module/DECISIONS.md` → 0 строк, или формулировка сужена до `create_model`/инстанцирования.
- `grep -rn 'недостижим\|физически не может\|но пуста\|строит catalog-менеджер' multiprocess_framework/modules/registers_module` → 0.
- Если `from_dict` перенесён внутрь `try`: вход с полем без `type` → `from_catalog` не бросает, `good` построен. Плюс инъекция лида.

### Что я оставил открытым и что в моей работе ненадёжно
- I7 не повторял; числа по нему взяты у лида.
- Двойную запись в (3) воспроизвёл на фейковом объекте, а не на настоящем `LoggerManager`. Попадают ли `warning()` и `log()` с разными `module` в один и тот же файл или только в общий scope-канал (`system.log`), не проверено.
- Фразу (2a) я пропустил в итерации 1. Значит, и другие абсолютные формулировки, которые стояли до 3b9d1042 и не попали в этот диф, могли остаться непрочитанными.
- Воспроизведения (2a) и (2b) идут на ручном payload. Команда `catalog.plugins` на хабе такого не выдаёт, поэтому по достижимости это нечастый случай: чужой или битый источник.
