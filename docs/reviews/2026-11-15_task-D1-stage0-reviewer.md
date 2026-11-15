# Стадия 0, Task D1 (путь реестра device_hub) — ревью брифа

Режим: `MODE: plan` на Task-файле. Читал: `plans/r2-env-isolation-defects/{plan.md,tasks/D1.md,tasks/D1.acceptance.md}`,
`Plugins/hub/device_hub/{plugin.py,config.py,registers.py,DECISIONS.md,tests/*}`, `Services/device_hub/{manager.py,registry/store.py}`,
`Plugins/tests/test_no_silent_swallows.py`, `backend_ctl/harness.py`. Ничего не запускал, кроме чистого разрешения пути (без записи).
memory hits: не запускал (`search.py` не вызывался).

## Вердикт: CHANGES REQUESTED (итерация 1 из 2)

## Ответы на 6 вопросов

1. **parents[3] / parents[4] — верно.** `Path("Plugins/hub/device_hub/plugin.py").resolve().parents`: [0]=device_hub, [1]=hub,
   [2]=Plugins, [3]=корень checkout, [4]=выше. Воспроизведено: в этом worktree `_PROJECT_ROOT` =
   `.../Inspector_bottles/.claude/worktrees`, `_resolve_registry_path("data/devices.yaml")` =
   `.../.claude/worktrees/data/devices.yaml` (файл существует, 680 Б). В главном checkout [4] = `/Users/twokrai/Project_code`,
   там `data/devices.yaml` тоже есть (1107 Б, 13 нояб.). Остальные `parents[N]` в `Plugins/`, `Services/ml_*`, `model_picker.py`,
   hikvision `presenter.py` пересчитал — ошибок нет.
2. **Потребители пути.** Единственная точка вывода — `plugin.py:185` (`RobotDataStore(resolved.parent / "robot")`): калибровка
   и параметры робота (T5.3c) идут от `resolved`, DESIGN их покрывает без правок. `git grep` по `data/robot|resolved.parent|
   devices.yaml|_PROJECT_ROOT` — других читателей реестра нет; `apps/line_sim/README.md:82,139` и `registers.py:25`
   («отн. от корня проекта») уже описывают путь «в репозитории» — правка приводит код к документированному контракту.
   `backend_ctl/harness.py` и живые тесты `INSPECTOR_DATA_DIR` не ставят: после правки они пишут в `<repo>/data/` (в git не идёт,
   `.gitignore:135`), раньше — выше репозитория; не регрессия.
3. **Развилка предупреждения — не готова** (замечания 1, 4, 7, 10, 11 ниже).
4. **Существующие тесты.** `test_device_hub_plugin.py:611-615` (`"data" in str(p)`) и `:617-625` проходят и после правки; остальные
   тесты плагина ставят абсолютный `tmp_path`. **Ломает один гейт вне радиуса брифа:** `Plugins/tests/test_no_silent_swallows.py`
   (замечание 3).
5. **REDS / ACCEPTANCE / FILES — недостаточны** (замечания 2, 4, 5, 6).
6. **Данные владельца.** Прежний файл не трогается и не копируется — потери нет. Риск — невидимость: WARNING только в логе
   процесса (`ctx.log_warning`), GUI пуст, пока реестр не перенесён. Достаточно как механизм, недостаточно без явной строки
   владельцу в записке слияния (замечание 12).

## Замечания (path:line — что править в тексте)

1. **[spec/tests, блокер] `D1.md:30-32` (DESIGN п.3).** Прежнее место считается внутри функции от `__file__.parents[4]` — шва
   для теста нет. Единственный способ получить «прежний файл есть» — создать его на настоящем месте
   (`/Users/twokrai/Project_code/data/devices.yaml` — реестр владельца, существует; в worktree — `.claude/worktrees/data/devices.yaml`).
   Тест либо затрёт файл владельца, либо не пишется. Заодно п.3 вводит второй «магический» `parents[4]`, хотя п.1 выбирает
   отказ от него. Заменить текст п.3: «прежнее место = `_PROJECT_ROOT.parent / raw_path` (ничего от `__file__`);
   `_warn_legacy_registry(resolved: Path, legacy: Path, log_warning: Callable[[str], None]) -> None`; вызывать только если
   `resolved == _PROJECT_ROOT / raw_path` (корневая ветка резолвера: покрывает абсолютный путь, `INSPECTOR_DATA_DIR` и пустое
   значение env — резолвер `plugin.py:74` `if data_dir:` считает "" незаданным); предупреждать, если `legacy` существует,
   а `resolved` — нет». Тесты патчат `monkeypatch.setattr(plugin_module, "_PROJECT_ROOT", tmp_path / "repo")`, прежний файл —
   `tmp_path / "data" / "devices.yaml"`. Строку `ACCEPTANCE` про `git grep "parents\[4\]"` заменить: «`git grep -n "parents\[4\]"
   -- Plugins/hub/device_hub/plugin.py` — пусто».
2. **[tests, блокер] `D1.acceptance.md:14-18` (B1), `:26-27` (B7).** Допускает «создать файлы в `<корень>/data/` и удалить в
   `finally`». В главном checkout `data/` — рабочий каталог (atlas.sqlite, журналы); после переноса реестра владельцем этот
   тест его затрёт или удалит. Вариант «подменить корень на tmp» ничего не доказывает про индекс `parents[N]`. Переписать B1:
   «Без записи в `<корень>/data/`. `_resolve_registry_path("data/devices.yaml")` (его импортирует существующий тест, `:14`) равен
   литералу `Path(<модуль плагина>.__file__).resolve().parents[3] / "data" / "devices.yaml"`; B2 — `resolved.is_relative_to(<тот же
   литерал корня>)`». Для B3/B4/B7 уточнить наблюдаемое: файл реестра появляется при первом `_save` (upsert/remove/`shutdown`:
   `manager.py:261-271,457,497`), а не в `configure`; каталог `robot/` не создаётся конструктором (`Services/robot_comm/store.py:188`),
   а при первой записи данных робота — проверять «после `cmd_device_upsert` / `shutdown(ctx)`» и «после записи точки как в
   `test_robot_v2_commands_acceptance.py`». Иначе слепой тестер напишет «файл есть сразу после configure» — красный и после правки.
3. **[quality/tests, major] `D1.md:32` («Любое исключение — проглотить»), `:51` (TESTS).** `Plugins/tests/test_no_silent_swallows.py:76-82`
   валит CI на `except` без `report_error`/`raise`/тега `# no-health:` — вне радиуса `Plugins/hub/device_hub/tests`. Дописать:
   «ловить `OSError` (не `Exception`); на строке `except` — `# no-health: проверка прежнего места реестра — не должна ронять
   запуск`»; в TESTS добавить `Plugins/tests/test_no_silent_swallows.py`.
4. **[tests, major] `D1.md:41-47` (REDS).** `test_silent_when_new_exists`, `test_silent_with_data_dir_env`,
   `test_never_copies_or_creates_legacy` до правки зелёные по пустоте (предупреждения нет вообще); красными они станут только
   `ImportError` от несуществующего `_warn_legacy_registry` — и тогда красен весь модуль, а не 6 тестов. Исправить: тесты
   через `configure` и `ctx.log_warning.call_args_list` (в `conftest.py:60-70` `ctx` — `MagicMock`); красные до правки —
   `test_relative_path_is_inside_repo_root`, `test_relative_path_not_above_repo`, `test_warns_once_when_only_legacy_exists`
   (+ `test_warning_names_both_paths_and_manual`). Остальные — защищаются инъекцией; дописать предсказания: убрать
   `resolved.exists()` → красный `silent_when_new_exists`; убрать проверку корневой ветки → `silent_with_data_dir_env`
   (+ новый `silent_with_absolute_path`); `shutil.copy2` вместо предупреждения → `never_copies` (+ B5); убрать `try/except` при
   `legacy.is_file` → бросающем `PermissionError` → новый `test_warning_failure_does_not_break_configure`.
   Добавить: `test_second_configure_silent_after_registry_created` (настоящая однократность, см. п.7).
5. **[tests, major] `D1.acceptance.md:22-25` (B5/B6).** «Запись уровня WARNING» без канала: `caplog` ничего не увидит, плагин
   пишет через `ctx.log_warning`. Дописать: «наблюдаемая запись — вызов `ctx.log_warning(...)` фейкового контекста
   (`make_ctx`, `MagicMock`); считать вызовы, содержащие строку прежнего пути; пути в тексте — `str(Path)` как есть (не `as_posix`,
   не `repr`)». То же в DESIGN п.3: «пути в f-строке без `repr`».
6. **[spec/architecture, major] `D1.md:39` (FILES п.3).** `Plugins/hub/device_hub/README.md` не существует (`ls` → No such file).
   «Короткий абзац» в новом README для существующего модуля тянет требования module-contract. Решение лида 1 пережило задачу
   (план, «Решения лида»). Заменить п.3: `Plugins/hub/device_hub/DECISIONS.md` — ADR-PH-002 «Путь реестра от корня checkout;
   миграция предупреждением, не копированием» (файл есть, ADR-PH-001 — образец); README не создавать.
7. **[spec, major] `D1.md:33` («`on_start`-ветке»).** В плагине нет `on_start`; вызов — в `configure` (`plugin.py:162-214`, строка
   180). Однократность — не свойство кода, а побочный эффект: `RegistryStore.save` создаёт файл при первом `shutdown`/`upsert`,
   затем условие «нового нет» ложно. Записать явно: «предупреждение — раз на запуск процесса, пока нового файла нет;
   перезапуск после первого `shutdown` молчит (принято)». Триггер сузить не по сути: сейчас только `devices.yaml`, а текст
   обещает «и каталог robot/»; калибровка (`robot/<id>/params.yaml`) ценнее реестра. Условие: `legacy.is_file() or
   (legacy.parent / "robot").is_dir()`.
8. **[quality] `D1.md:28-29` (DESIGN п.1).** «Вычислять от маркера, не от магического индекса» и тут же `parents[3]`. Заменить:
   «`parents[3]` от `__file__`, комментарий-расшифровка как `segmentation/plugin.py:37`; поиск маркера (`.git`/`pyproject.toml`) не
   вводить: меньше слоёв».
9. **[quality] `D1.md:14-15` (факт 4), `:5`.** Добавить: для worktree в `.claude/worktrees/<имя>` прежнее место —
   `.claude/worktrees/data/devices.yaml` (общий для таких worktree, существует), предупреждение сработает на первом старте каждого;
   текст предупреждения — «если это ваш реестр — перенесите вручную: …» (иначе совет копировать мусор). SHA `ec48d7bbc` в
   шапке устарел (main `a1996b24b`); строки сверил — совпадают.
10. **[spec] DESIGN п.3, «`INSPECTOR_DATA_DIR` не задан».** См. п.1: брать условие из резолвера (`resolved == _PROJECT_ROOT / raw_path`), а
    не пересчитывать env; на Windows `Path.is_absolute()` и разделители — тем же резолвером.
11. **[tests] acceptance B2 (`:19-20`).** «ни один родитель … не фигурирует как каталог» — не проверяется. Заменить на
    `is_relative_to` (п.2).
12. **[spec, риск] `plan.md:35-38`, `D1.md:56`.** Добавить в «Что осталось ненадёжным» и в REPORT: «WARNING виден только в
    логе процесса; в записку слияния — строка владельцу с командой переноса `Project_code/data/devices.yaml` →
    `Inspector_bottles/data/` (и `robot/`, если есть)». Без этого владелец увидит пустой список устройств.

## Остальной чек-лист (a)–(h), (i)–(iii)

- (a) acceptance-строки с командой/литералом: pytest и grep есть; grep нужно исправить (п.1). (c) `Files:` D1 (`Plugins/hub/device_hub/*`) и
  D2 (`multiprocess_framework/.../process_manager_module/*`) не пересекаются. (d) в `plan.md` у D1/D2 нет строки `Dependencies:`
  при слове «параллельно» (`plan.md:19`): дописать «Dependencies: none, файлы не пересекаются». (f) Out of scope не пуст и отличается от Goal.
  (g) в плане нет числа токенов (участники × ~56k + работа) — только «медленно/быстро»: дописать оценку. (i) п.2, п.4, п.5 DESIGN без причины.
  (ii) инварианты модуля (`ADR-PH-001`, «резолв от корня/env, не от CWD», `plans/_archive/device-hub.md:317`) не нарушены. (iii) тексты
  предупреждения несут пути (конфиг и ФС, не вход оператора) — допустимо для лога; `exc!r` в тексте ошибки пути не добавлять сверх этого.

## Что я не проверил / ненадёжно

- Не запускал ни одного теста (стадия 0, только чтение); «зелёный после правки» для `test_device_hub_plugin.py:611-625` — вывод чтением.
- Содержимое обоих `devices.yaml` не читал (только `ls`-метаданные: размер, дата).
- `test_spi_commands_acceptance.py:590` разбирает AST `plugin.py` — не проверил, не реагирует ли он на новую функцию.
- Windows: рассуждение по коду, машины нет (`D:\PROJECT_INNOTECH\...` — боевая).
- Не перебирал все живые тесты, поднимающие приложение без `INSPECTOR_DATA_DIR` (нашёл только `backend_ctl/harness.py`).
- Вне D1, но видно: `INSPECTOR_DATA_DIR=/x/mydata` + `data/devices.yaml` → `/x/data/devices.yaml` (`plugin.py:77-78`, `base.parent`),
  а не внутри каталога; `Plugins/io/robot_draw/registers.py:49` пишет `data/robot_points_preview.txt` от cwd. Обе — отдельные строки в реестр дефектов.

---

# Раунд 2 (последний) — бриф ред. 2, коммит 96d3627ad

Вердикт: **APPROVED с 4 обязательными правками текста** (D1.md / plan.md; повторного ревью не требую, лид сверяет `git grep`). `D1.acceptance.md` одобрен — слепого тестера можно запускать.

| № | Статус | Где |
|---|---|---|
| 1 шов `_PROJECT_ROOT` | закрыт | D1.md:30-35, acceptance:10 (патч `_PROJECT_ROOT`, прежнее место `<tmp>/data`), D1.md:51 (grep `parents[4]` — пусто) |
| 2 без записи в `data/` | закрыт | acceptance:7,15-16; создание файла при первом сохранении — acceptance:11, D1.md:14 |
| 3 OSError + тег + гейт | закрыт | D1.md:32, :51, :17 |
| 4 REDS | закрыт частично | D1.md:45-49; нет красного до правки теста для `robot/` (см. новое 1) |
| 5 канал лога, `str(Path)` | закрыт | acceptance:9, D1.md:31 |
| 6 README → ADR-PH-002 | закрыт | D1.md:41 |
| 7 `configure`, однократность, триггер `robot/` | закрыт | D1.md:21,30,35 |
| 8 «от маркера» | закрыт | D1.md:27-28 |
| 9 worktree-прежнее место, SHA, текст | закрыт | D1.md:4,15,31 |
| 10 условие из резолвера | закрыт | D1.md:33-34 |
| 11 B2 `is_relative_to` | закрыт | acceptance:16 |
| 12 строка владельцу, `plan.md` | НЕ закрыт | коммит 96d3627ad трогает только D1.md/D1.acceptance.md; `plan.md:35-38` и `D1.md:58` без строки про перенос; `Dependencies:`/оценка токенов в плане тоже не добавлены |

Новые дыры (мелкие):
1. D1.md:44-49: B6 (только `robot/` на прежнем месте) красный до правки, но в REDS его аналога нет. Добавить `TestLegacyRegistryWarning::test_warns_when_only_legacy_robot_dir_exists`.
2. D1.md:33-34: проверки `resolved.exists()` и `(resolved.parent/"robot").exists()` стоят в точке вызова вне защиты `OSError` — `PermissionError` на новом месте уронит `configure`. Перенести внутрь `_warn_legacy_registry` под тот же `try`; `raw_path` в п.4 назвать `self._reg.registry_path`.
3. D1.md:32: глотание `OSError` по тегу молчаливо — «лог ошибок, не глотать»: в обработчике `log_warning(... {exc!r})`. B9 это не ломает (проверяет только «configure дошёл до READY»).
4. Условие п.4 отсекает env не буквально: `INSPECTOR_DATA_DIR=<корень>/data` даёт `resolved == _PROJECT_ROOT/raw_path`, предупреждение пойдёт — безвредно (то же место), но фразу «отсекается INSPECTOR_DATA_DIR» заменить на «пока env указывает на другое место».

Достижимость без записи в настоящий `data/`: B1–B4 чистые; B5–B9 через `_PROJECT_ROOT -> tmp_path/"repo"` и файлы в `tmp_path` — достижимы. B9: подставить `OSError` избирательно (по пути прежнего места) через патч `Path.is_file`/`is_dir`/`os.stat`, не глобально. Базовая линия `validate.py` («2 ошибки памяти») проверена прогоном: 2 FAIL (теги памяти, индекс BY-MODULE).

Не проверил: тесты и реализацию (кода ещё нет); как слепой тестер выполнит избирательный `OSError` в B9 (осуществимость по знанию pathlib 3.12, не запуском); Windows.
