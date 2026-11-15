# D1 — стадия 5, ревью кода (reviewer)

Код `988175aa0`, слепой файл `6d5660815`, ветка `fix/r2-devices-registry-path`. Только чтение; правок кода нет.

## Вердикт: APPROVED (с тремя минорными поправками до слияния, повторного ревью не нужно)

Блокирующих и major-замечаний нет. Все пункты DESIGN 1-5 выполнены дословно; `parents[4]` в `plugin.py` нет (`git grep -n "parents\[4\]" -- Plugins/hub/device_hub/plugin.py` пусто, rc 1).

## Замечания (вход -> наблюдаемый выход)

1. [plugin.py:205-207, DECISIONS.md ADR-PH-002] [quality] Комментарий и ADR говорят, что проверка зовётся «не для абсолютного пути».
   Вход: `registry_path` = абсолютный путь. Выход: условие `resolved == _PROJECT_ROOT / raw_path` истинно (pathlib: `root / "/abs/x" == "/abs/x"`),
   `_warn_legacy_registry` зовётся (spy: 1 вызов), предупреждений 0 (потому что `legacy == resolved`). Поведение верное, формулировка ложная
   (и в DESIGN п.4 тоже). Fix: переписать слова в комментарии и ADR («для абсолютного пути зовётся вхолостую: legacy == resolved, функция молчит»)
   либо добавить `and not Path(raw_path).is_absolute()` (тогда тест `silent_for_absolute_path` начнёт что-то доказывать: сейчас J2 его не краснит).
2. [plugin.py:101-105] [quality] Вход: на прежнем месте только каталог `data/robot/`, файла реестра нет (случай B6).
   Выход: «данные найдены по прежнему пути <прежний>/data/devices.yaml» — файла по этому пути нет, владелец ищет и не находит.
   Fix: добавить в текст `{legacy.parent}` («в каталоге …») при сохранении `str(legacy)` (слепой B5/B6 требует обе строки).
3. [plugin.py:99] [quality] Вход: `PermissionError` при проверке прежнего места. Выход: лог «…не удалась: PermissionError(13, 'Permission denied')» —
   repr `OSError` не содержит имени файла (проверено), владелец не узнает, какой путь не открылся. Fix: добавить `{legacy}` в текст.

## Проверки

- (1) DESIGN 1-5: п.1 `parents[3]` + цепочка в комментарии; п.2 резолвер не тронут (дифф); п.3 сигнатура, один `try`, `except OSError` с тегом на строке `except`,
  текст обработчика дословно; п.4 вызов сразу после `resolved`, условие из резолвера; п.5 `RegistryStore`/`RobotDataStore`/`config.py`/рецепты не тронуты (дифф: 4 файла).
- (2)-(3) Пробы на реальных tmp-деревьях через `configure` (`scratchpad/probe.py`): абсолютный путь — 0 предупреждений; `../data/devices.yaml` — предупреждение с
  прежним путём = `old_root / raw` (верно: ровно то, что резолвил старый код), пути в тексте не нормализованы (косметика); `data\devices.yaml` — работает;
  `INSPECTOR_DATA_DIR=<корень>/data` — предупреждает (как в DESIGN, безвредно); `registry_path=""` — предупреждения нет (resolved = каталог существует), а `configure`
  падает `IsADirectoryError` в `RegistryStore.load` — до правки так же (резолвер и хранилище не менялись). Функция только `exists/is_file/is_dir`: не создаёт, не копирует, не читает.
- (4) Второй потребитель пути выше репозитория: не найден. `git grep` по `devices.yaml|data/robot|INSPECTOR_DATA_DIR` вне docs/plans: единственный вывод каталога робота —
  `plugin.py:214`; `scripts/alpha_sim` читает только `data/logs`, `data/models`; `backend_ctl` реестр не трогает; README `apps/line_sim` и так пишет «`data/devices.yaml` в репозитории»;
  рецепты и `base.yaml` дают относительный `data/devices.yaml`. Стенд `docs/reports/…/stand_l9.py:624` делает `workdir/data` (устаревший комментарий «относительно cwd»), от пути выше репозитория не зависит.
  Следствие, не дефект D1: живые тесты `apps/line_sim/tests/test_f2_task22_live.py`/`…23_live.py` и alpha_sim запускают настоящий хаб без `INSPECTOR_DATA_DIR` — их реестр теперь `<дерево>/data/devices.yaml`
  (в основном чекауте это реестр владельца после переноса).
- (5) Тесты: expected-литералы (`parents[3]` берётся в тесте, строки «перенесите вручную» — литералы); `_PROJECT_ROOT` -> `tmp_path`, `INSPECTOR_DATA_DIR` снят. Снимок `<репо>/data`, `.claude/worktrees/data`,
  `<worktree>/data`, `/Users/twokrai/Project_code/data` до/после: меняется только `agent-journal.jsonl` (хуки SubagentStart/Stop), `git status --short` пуст.
  Мои мутанты рантайм-плагином (`scratchpad/mutplug/revmut.py`, файлы репозитория не тронуты): M1 `parents[4]` -> красные ровно 4 (R 2 + A b1,b2); M2 ранний выход без проверки `robot/` нового места -> красный
  только `test_silent_when_new_robot_dir_exists` (в слепом файле такого случая нет); M4 (`resolved.exists()` и `resolved.parent/robot` вне `try`) и M5 (`(legacy.parent/"robot").is_dir()` вне `try`) -> 59 passed, выжили.
  M4/M5 поведенчески эквивалентны: `RegistryStore.load` зовёт `resolved.exists()` и упадёт на том же `PermissionError`, а любой отказ на `legacy.parent/robot` даёт тот же `EACCES` на `legacy.is_file()` раньше;
  свойство «все проверки под одним try» тестами не закреплено — advisory, не требование.
- (6) ADR-PH-002: номер свободен (в репозитории только ADR-PH-001 того же файла), формат как у ADR-PH-001; `python -m scripts.sync --check` rc 0 (дрейфа нет). Содержание верно, кроме фразы про абсолютный путь (замечание 1).
  `python scripts/validate.py`: 2 ошибки памяти (теги, индекс BY-MODULE) — прежние.
- (7) Прогон: `test_device_hub_plugin.py` + `test_registry_root_acceptance.py` + `Plugins/tests/test_no_silent_swallows.py`: **59 passed, 1 failed** (gate medium).
  Красный `test_no_silent_swallows` — не от правки: гейт-логика (`_scan_file`) на `git show main:Plugins/hub/device_hub/plugin.py` даёт те же 2 нарушения (main:388, main:907 — `except Exception` в `_on_scope_report` и `request_disconnect`), на HEAD они же на 417 и 936 (+29 строк добавлено выше);
  остальные 3 (`frame_saver/plugin.py:343`, `word_layout/plugin.py:279,339`) в файлах, идентичных main. Новый `except OSError` с тегом гейтом принят (не в списке). Итого 5 нарушений и там, и там.
  `ruff check -q Plugins/hub/device_hub` rc 0; `ruff format --check` по трём файлам правки чисто.

## Что не проверил / ненадёжно

- Живой стенд и реальный лог процесса: что `log_warning` доходит до видимого владельцу журнала, не смотрел (только мок и чтение `PluginContext`). Предупреждение однократно по построению (после первого сохранения реестр есть) — пропустить его легко; GUI покажет пустой реестр до ручного переноса.
- Windows не запускался: `is_absolute()` для `\data\x` и диска, регистронезависимое сравнение `resolved == _PROJECT_ROOT / raw_path` — только чтением.
- Инъекции J1-J9 лида не перезапускал (9 из 9 в `D1.injections-result.md`, предсказания закоммичены раньше); сделал свои M1, M2, M4, M5 только на уровне функции/константы, не правкой файла.
- `Plugins/hub/device_hub/tests` целиком и `Services/device_hub/tests` (7 файлов с `DeviceHubPlugin`): результат — в разделе ниже.

## Прогон каталога (gate medium)

`Plugins/hub/device_hub/tests` целиком + `Services/device_hub/tests/{test_c29_disconnect_acceptance,test_c29_probe,test_exchange_log,test_spi_contract,test_t56_exchange_log_acceptance,test_robot_v2_draw}.py`:
**720 passed, 1 warning, 285.85 s, exit 0**; G3 unclosed roots 0, G4 threads without scope path 0. Снимок `data/`-каталогов до/после: новых файлов нет
(`<worktree>/data/devices.yaml` не появился, `.claude/worktrees/data/devices.yaml` и `/Users/twokrai/Project_code/data/devices.yaml` не изменились), меняется только `agent-journal.jsonl` (хуки).
