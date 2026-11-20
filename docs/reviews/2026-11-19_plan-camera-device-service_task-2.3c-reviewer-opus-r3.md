# Task 2.3c — ревью Opus, раунд 3 (код `bb7ac56e5`, дерево `cam-2-3c-dev`)

Свежий ревьюер. Прежний (`ad3e1c8a3f510004f`) недоступен: продолжаю по его отчёту `…2.3c-reviewer-opus.md` (раунды 1–2).
Не коммитил, код не правил. Дерево не правил: все мутанты — в копиях пакета в scratchpad.
Специализации: архитектура, контракт модуля (lite), безопасность (журнал без значений), часы и окно `fps`.
memory hits: `scripts/memory/search.py clock resolution windows monotonic fps` -> `project_monotonic_resolution_windows.md`
(шаг 15,625 мс; замер `sleep(0.05)` на Windows — 0,047 / 0,062 с), `feedback_global_clock_patch_flake.md` (подмену часов
ставлю только на один тест).
qex не использовал: символы точные, поиск — `git grep`.

Скрипты (каталог `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/57a482d2-9b1b-4236-b7a9-37da99c55136/scratchpad/r3/`):
`mutate3.py` (11 случаев; прогнозы записаны в файл до первого прогона, 23:08), `plug/quantclock.py` (плагин pytest:
`time.monotonic` с шагом 15,625 мс), `plug/pathproof.py` (печатает путь импорта из того же процесса pytest),
`repro_access.py` (вход -> ответ для находки 1). Каждая копия: `Services/camera_device`, `Services/__init__.py`,
`pyproject.toml`, `conftest.py` дерева; `multiprocess_framework` и `scripts` — из дерева через `PYTHONPATH`.

## Вердикт

**APPROVED.** Task 2.3c закрыта. Все находки раундов 1–2 закрыты, каждая подтверждена запуском. Тест окна `fps` от шага
часов больше не зависит. Новых дефектов в диффе `2958ae084..bb7ac56e5` не нашёл.

## Прогоны (через `machine_gate.sh light inspector-bottles-4c`, `.venv/bin/python` 3.12.13, `PYTHONPATH=<дерево>`)

| Команда | Итог |
|---|---|
| путь импорта из cwd дерева | `…/cam-2-3c-dev/Services/camera_device/{plugin_base,commands}.py`, `…/cam-2-3c-dev/multiprocess_framework/__init__.py` |
| `test_plugin_commands.py` + `test_plugin_commands_hazards.py` | `63 passed` (2,60 с) |
| тест окна `fps`, 3 раза подряд, настоящие часы | `1 passed` ×3 (0,68 / 0,72 / 0,70 с) |
| тест окна `fps`, 3 раза подряд, `-p quantclock` | `1 passed` ×3; `[quantclock] … on_grid=True` в каждом прогоне |
| `mutate3.py` (11 случаев, копии) | 11 из 11 совпали с прогнозом (таблица ниже) |
| `ruff check -q` (4 файла), `ruff format --check -q` (3 файла) | rc 0 / rc 0 |
| `sentrux check .` | `43 rules checked … ✓ All rules pass`, rc 0 |
| `secrets_audit.py --format json --root Services/camera_device` | rc 0, `"total": 0` |
| `git status --short` после всех прогонов (до записи этого отчёта) | пусто |

Путь импорта мутантов: `pathproof` в каждом из 11 прогонов печатает `…/scratchpad/r3/<случай>/Services/camera_device/plugin_base.py`
и тестовый модуль из той же копии.

## Сверка находок раундов 1–2 (вход -> наблюдаемый вывод)

| # | Вход | Наблюдаемо | Итог |
|---|---|---|---|
| R1-1 права поля (major) | `repro_access.py`, register с привязанным `gain: FieldMeta(access_level=1, apply="live")`, пакет `{"exposure_time": 900.0, "gain": 2.0}` | дерево: `{'success': False, 'error': 'недостаточно прав для поля: gain'}`, вызовов `set_field_value` — `[]`, `exposure_time: 10000.0`, `gain: 1.0`. Копия `macc` (проверка `can_modify(0)` убрана): `{'success': False, 'error': 'Недостаточно прав доступа: требуется уровень 1, передан 0', 'applied': ['exposure_time']}`, `exposure_time: 900.0` — прежний дефект | закрыта; мутант `macc` -> красный ровно `test_apply_params_поле_с_уровнем_доступа_отвергается_до_первой_записи` (62/1) |
| R1-2 журнал без значений (major) | мутант `m9`: `fields={params}` в INFO успеха | красный ровно `test_apply_params_журнал_без_значений_полей` (62/1): `"apply_params fields={'exposure_time': 123456.0} ok=True"` | закрыта |
| R1-2, ветка отказа (мой новый мутант) | `m9r`: перед отказом пробы `ctx.log_warning(f"… rejected {params}")` | красный ровно тот же тест (62/1): `значение SECRET-42 попало в журнал` | тест держит и путь отказа |
| R1-3 окно `fps` (minor) | мутант `m1`: в `cmd_reset_stats` убрано `self._tick_t0 = time.monotonic()` | красный ровно `test_reset_stats_сдвигает_окно_fps_без_подмены_часов_после_сброса` (62/1): `('fps', 0.009994495664739273)` | закрыта |
| R1-4 гонка `frames` (принята) | `README.md:177-178` | «…может до одного кадра (порядка 20 мс) или окна `_TICK_S` показывать прежнее число `frames`…» | закрыта (принята лидом) |
| R1-5 мёртвые константы | `git grep -n "_START_TIMEOUT_S\|_STOP_TIMEOUT_S" -- Services Plugins multiprocess_framework multiprocess_prototype` | камерные — только `commands.py:16,31,32,40,46`; прочие попадания — другие имена (`_V2_STOP_TIMEOUT_S`, `_LISTENER_STOP_TIMEOUT_S`, `_DEFAULT_RUN_STOP_TIMEOUT_S`) | закрыта |
| R1-6 `on_device` | `README.md:187-188` | «`on_device` не обещает записи: шаг, не меняющий план … прибор не трогает; итог — `read_params`» | закрыта |
| R1-7 значение в тексте диапазона (framework) | `README.md:156-157`, `OPEN_QUESTIONS.md:2401` | README сужен до модели аргументов и называет исключение `min`/`max`; вопрос записан для framework | закрыта для 2.3c |
| R2-1 тест `fps` и шаг часов (major) | `-p quantclock`, только тест окна `fps` | с `time.sleep(0.05)`: `1 passed` ×3. Копия `q_nosleep` (строка сна убрана): `1 failed`, `[('frames', 1), ('errors', 0), …]` — `fps` не опубликован, как в раунде 2. Копия `q_m1`: `1 failed`, `('fps', 0.009993753903810118)`. Копия `r_nosleep` (без сна, настоящие часы): `1 passed` | закрыта: сон снимает зависимость от шага, мутант M1 краснеет и на грубых часах |

Строка (4) DESIGN в `tasks/2.3c.md:32` называет `can_modify(0)` и текст отказа; поправка в `…2.3c-injections.md` (M1, M9) на месте.

## Break-injection (прогнозы до прогона, файл `mutate3.py`)

| Случай | Прогноз (красные) | Факт | Совпало |
|---|---|---|---|
| `control` (оба файла, без мутации) | нет | `63 passed` | да |
| `macc` | тест прав доступа | он один, 62/1 | да |
| `m9` | тест журнала | он один, 62/1 | да |
| `m9r` | тест журнала | он один, 62/1 | да |
| `m1` | тест окна `fps` | он один, 62/1 | да |
| `q_control_1..3` (`quantclock`) | нет | `1 passed` ×3 | да |
| `q_nosleep` (`quantclock`) | тест окна `fps` | `1 failed` | да |
| `q_m1` (`quantclock`) | тест окна `fps` | `1 failed` | да |
| `r_nosleep` (настоящие часы) | нет | `1 passed` | да |

## Новые дефекты в диффе

Нет. Что проверил чтением и запуском:

- Шаг (4) `cmd_apply_params` (`plugin_base.py:672-680`): `readonly` идёт первым и сохраняет прежний текст; затем `can_modify(0)`.
  `set_field_value` проверяет те же метаданные (`SchemaMixin.get_field_meta` и `get_all_fields_meta` читают один
  `model_fields`), уровень `0` — тот же, что у `validate_field_value` по умолчанию (`manager.py:302`). Поле без `FieldMeta`
  пропускается — так же поступает `validate_field` (`schema_mixin.py:185-187`). `min`/`max` и `le_field` держит проба:
  `apply_values` пишет по одному полю, как и цикл записи (`schema_mixin.py:329-330`).
- Текст «недостаточно прав для поля: <имя>» значения не содержит.
- Константы сроков: только перенос в `commands.py`, умолчания `Field(...)` прежние (5.0 / 2.0); других читателей нет (grep выше).
- Тесты: подкласс `_GainRegisters`/`_GainPlugin` расширяет `FAKE_BINDINGS`, не меняет его; `reg_cls` у `_Rig` по умолчанию
  прежний. Тест журнала подменяет атрибуты `PluginContext` (`log_info`/`log_warning`/`log_error` — атрибуты экземпляра,
  `plugins/base.py:151-153`), плагин читает их при каждом вызове. Тест окна `fps` откатывает `_TICK_S` через `monkeypatch`.
- Слои: `sentrux check .` — все правила проходят; новый импорт теста (`data_schema_module.FieldMeta`) — Services -> framework.

## Замечания (не держат вердикт)

- `OPEN_QUESTIONS.md:2401` записывает только число в тексте отказа диапазона. Вторая половина совета раунда 1 в запись
  не вошла: `set_field_value` пишет значение в DEBUG при каждой успешной записи (`manager.py:222`,
  `f"set_field_value: {register_name}.{field_name} = {value!r}"`), а соседний комментарий ADR-RM-007 обещает, что секрет
  `headers` в журнал не уезжает. Это framework, вне 2.3c. Лиду: дописать в ту же строку или принять.

## Что осталось открытым / ненадёжно

- R2-1 закрыта симуляцией часов (`floor(t / 0.015625) * 0.015625`) на macOS, CPython 3.12.13. На Windows не запускал.
  Настоящие часы Windows ещё дрожат по фазе; запас теста это покрывает: нужен только `elapsed > 0` при сне 50 мс
  (три шага часов), а порог `> 0.1` ломается лишь при паузе больше 10 с между сбросом и вторым `produce()`.
- Ложный красный теста окна `fps` возможен при остановке процесса теста дольше 10 с. На обычной машине не наблюдал.
- Под `quantclock` гонял только тест окна `fps`. Остальные тесты файла с порогами времени на грубых часах не гонял
  (глобальная подмена задела бы `WorkerManager`, урок `feedback_global_clock_patch_flake.md`).
- Тест журнала ловит значения в `log_info`/`log_warning`/`log_error`. Мутант, который пишет значения в
  `ctx.log_debug` или `log_critical`, выживет. Гарантия DESIGN — про INFO-строку, поэтому это не находка.
- Проверку прав видел только на тестовом подклассе register'а с `access_level=1`. Вендорского register'а с таким
  привязанным полем в дереве нет.
- Полный каталог `Services/camera_device/tests` и `Services/hikvision_camera/tests` не гонял (по брифу его гоняет другой
  агент); его итога не видел. Радиус диффа в коде — `cmd_apply_params` и приватные константы `commands.py`.
- Конфликт слияния с `feat/camera-2-3d` на строках констант (`plugin_base.py`) не проверял: бриф ограничил работу этим деревом.
- Открытые пункты раундов 1–2 не перепроверял: гонка подмены `__dict__` (0 из 20000), `on_device` в `opening`/`busy`/`error`,
  гонка публикации `frames` на стенде.
- Свой agentId изнутри не вижу; лид видит его в уведомлении о запуске.
- После записи этого отчёта `git status --short` показывает только его: `?? docs/reviews/2026-11-19_…-reviewer-opus-r3.md`.
