# camera-device-service, Task 4c — ключ `run_locked_commands` у камеры + хвосты (2026-11-20, лид К, сессия `inspector-bottles-e0`)

Ветка `feat/camera-4c` (worktree `Inspector_bottles--lane-K-4c`), основа `main` `ad3dc7b72`. В `main` НЕ слито: слияние делает координатор (`inspector-bottles-fb`); HEAD — в `docs/handoffs/2026-11-20_camera-4c-merge-request.md`. W4 (4.2a, 4.2b, 4.3, 4.4, 6.1, 6.3) не начата; выбор «stopping при auto_start» не решался.

## Таблица «готово / в работе / блокер»

| # | Задача брифа | Состояние | Подтверждение |
|---|---|---|---|
| 1 | Ключ `run_locked_commands: [release_device, take_device]` в рецептах узла камеры | **готово** в единственном рецепте с `CameraDevicePlugin` — `camera_device_demo.yaml`; в hikvision-рецептах НЕ ставится (старый плагин без этих команд, ключ даст ERROR «нет таких команд») — идёт с 4.3 (W4) | 13 слепых тестов + 2 hazard + 3 теста рецепта; ревью Opus: на настоящем стеке `PluginOrchestrator` + `CommandManager` + `RunFlag` 11 шагов со сменой флага — отказ ровно `{'status': 'error', 'error': 'running', 'message': 'сначала ОСТАНОВИТЬ'}` при взведённом флаге, исполнение при снятом |
| 1а | `apply_params` и видимый оператору отказ через relay GUI | **не решалось по брифу**; вопрос уже записан лидом Ф (`docs/claude/OPEN_QUESTIONS.md:2459`, ACCEPTANCE 2.7d); `apply_params` НЕ блокируется (решение владельца) | — |
| 2 | README/STATUS/DECISIONS `Services/camera_device`: readiness, числа | **готово**: `grep -ci "readiness\|готовност"` 0 -> 12 / 2 / 11 строк (DECISIONS / STATUS / README); ADR-CAM-005; числа STATUS поправлены по прогону (462 passed, 10 skipped) | Opus сверил 6–8 утверждений README/ADR с кодом по path:line — расхождений нет |
| 3 | Остатки: DEBUG-значение (`registers/manager.py:222`), `bindings()` вне `try` (`plugin_base.py:697`, сейчас `:726`) | **готово**, Б1 — частично по классу (см. «открыто») | 4 красных -> зелёных (Б2), 1 красный -> зелёный (Б1); мутанты Б1/Б2 воспроизведены ревьюером |
| 4 | Подготовка дня №1 без камеры | **готово**: `docs/handoffs/2026-11-20_day1-dry-run.md` (сухой прогон на синтетике: `saved_count` 20, `total_errors` 0, вход `saver` 24,92 Гц за окно 5,02 с; 3 расхождения с чек-листом §4; набор вопросов дня №1) | прогон один раз каждого сценария |
| 5 | W4; выбор «stopping при auto_start» | не начато / не решалось (по брифу) | — |

## Числа (прогон на ветке; повтор ревьюером Opus — совпало)

- `Services/camera_device/tests`: 462 passed, 10 skipped, 0 failed. До правок на коммите слепых тестов — 456 passed + 4 failed (Б2), 10 skipped; на самом `main` до 4c — 443 (вычитанием, не прогоном).
- `registers_module/tests`: 113 passed (до Б1 — 112 + 1 failed); `process_module/tests/test_run_locked_commands.py` — 14 passed; `multiprocess_prototype/registers/tests`: 14 passed.
- `multiprocess_prototype/recipes/tests`: 214 passed, 5 skipped (+3 теста рецепта).
- Тесты, перебирающие `recipes/*.yaml` (7 файлов): 406 passed у разработчика / 253 passed (6 файлов Gate) у ревьюера — разные выборки, красных нет.
- `sentrux check .`: 43 правила, все проходят (ревьюер Opus).
- Новых тестов 4c в `Services/camera_device/tests`: 13 + 2 + 4 = 19; ещё 1 (Б1) + 3 (рецепт).

## Конвейер («Task launch convention»)

| Стадия | Результат |
|---|---|
| 0. reviewer (sonnet) на тексте 4c | раунд 1: CHANGES REQUESTED (14 замечаний: противоречие scope/Layer/Gate, нужен настоящий `WorkerManager`, пустые предусловия REDS 3/5/6, нет `default_level` DEBUG и нейтрального поля в REDS 7, способ вызова в REDS 8); раунд 2: CHANGES REQUESTED (REDS 7/8, таблица И6/И11) — все правки внесены; **третьего раунда не было** (по протоколу после двух — эскалация; правки механические, воспроизведены ревьюером, пригодность текста подтверждена им в раунде 2) |
| 1. слепой tester (sonnet), worktree на `fe8318bb7` | 3 файла, 13 + 3 + 4 тестов; REDS 7/8 красные на HEAD, REDS 1–5 зелёные (Ф7); свои инъекции а–ж: предсказал/наблюдал 7 из 7 |
| 2. developer (sonnet) | рецепт, Б1, Б2, hazard 6a/6b, тест рецепта; красные до правки ровно те, что ожидались |
| 3. инъекции (haiku по предсказаниям лида, записанным в `4c.md` ДО прогона) | 11 инъекций (R1–R5 рецепт, P1–P6 продукт): 10 совпали; **R4 расходится**: помимо предсказанных (`reach_plugin_config` и «на уровне узла») красным стал и `every_locked_command_is_a_plugin_command` (KeyError: без ключа в конфиге плагина индекс падает) — находка по моему предсказанию, не по тесту |
| 5. ревью | Opus по ветке: **APPROVED WITH CONDITIONS**, блокеров и major нет; два условия (док-замечания 1 и 2) исправлены в этой же ветке; замечания 3 (Save), 4 (приватные имена слепого файла) — advisory |

## Что получилось отметить для владельца

- Ключ стоит в рецепте плоско в элементе `plugins`. Проверено запуском (ревьюер): ключ доходит до `orchestrator_config`/`ctx.config`, на уровне узла его нет, Save рецепта без правок байт-в-байт, после правки поля — ключ остаётся, но появляется копия во вложенном `config`, и она перекрывает плоскую строку (`plugin_orchestrator.py:164-166`) — записано в README.
- Отказ через relay GUI оператору не виден (только WARNING в журнале ребёнка) — прежнее открытое, не закрыто.

## Что осталось открытым / ненадёжно

- **Стенд ACCEPTANCE не выполнен** (Mac, `machine.lock` нет, окна нет): конверт роутера `{"success": False, "result": {...}}`, `run_start`, `run_gate: false`, кадры идут — не проверены; отказ подтверждён только на уровне `cm.handle_command` с настоящим `PluginOrchestrator` и фейком порта. Камеры нет.
- **Класс «значение поля в журнале» открыт**: Б1 закрыл одну строку `manager.py:222`; по ревью остаются `plugin_orchestrator.py:881-882` (INFO при каждой правке регистра), `multiprocess_prototype/frontend/app.py:902` (DEBUG) и `:884-889` (WARNING при отказе), плюс точки `manager.py` `:239, :256, :264, :269, :400, :411` и число в тексте отказа по диапазону. Логгер маскирует значения по секретным именам полей, нейтральные имена — нет. Запись в `OPEN_QUESTIONS.md`.
- **Ф3**: `start()`/`shutdown()` идут прямым вызовом и охрану минуют; рестарт ребёнка супервизором в `running` (откроет камеру по `auto_start`) не воспроизводился, владельцу не показывалось.
- **Инъекции 6a/6b**: красный под мутантами «`start`/`shutdown` через `handle_command`» получен, но почему в P5 состояние осталось `closed`, а в P6 переход `grabbing -> closed` появился в логе позже (возможно асинхронное исполнение), — не выяснено; 6b может быть чувствителен к времени, если мутант асинхронен (в рабочем коде вызов прямой, прогон 5 раз подряд — 15 passed за ~0,9 с).
- **Хрупкость**: hazard-тест 6a/6b импортирует приватные `_pdef, _Rig, _scenario` из слепого файла (переименование — громкий ImportError, не ложный зелёный).
- **Стадия 0**: третьего раунда не было (см. таблицу); ревьюер Opus по ветке принял итог.
- **Не гонялось ревьюером**: инъекции И1–И7, И9, И11 повторно; вкладка Pipeline (`PipelineModel`) и настоящий GUI-редактор свойств узла (Save проверен на доменной `Topology`); `backend_ctl/tests` (живой тест, вне Gate); `python scripts/validate.py` и `infra:validate` целиком — не запускались.
- **Сухой прогон дня №1**: синтетика, не камера — порядок каналов, дебайер, Windows/MVS не проверены; пороги `day1_capture_check.py` на синтетике не калибруются; остановка стенда `kill <pid PM>` дала `332 leaked semaphore objects` и `16 leaked shared_memory objects` — записи в `plans/queue/defects.md` про остановку стенда не нашёл (есть C-93, другой вход; штатный `system_shutdown` не пробовал); `Capabilities.processes` в драйвере пусто, данные только в `raw` — не расследовано.
- **Инцидент с общим `git stash`**: правки доков камеры были сняты `pop`-ом в чужом worktree (Д2); восстановлено патчем (`16346` Б, совпал с копией координатора), закоммичено (`e0eeedd61`). В моём дереве остаются ДВЕ ЧУЖИЕ незастейдженные правки Д2 (`frontend_module/widgets/telemetry_chart.py`, `…/tests/test_telemetry_chart.py`): откат мне запретили, не обходил; в коммиты они не попали (стейдж явными путями). В worktree Д2 лежат мои три `Services/camera_device/{README,DECISIONS,STATUS}.md` как незакоммиченные правки — откатить должен Д2. `git stash` в этой сессии больше не используется.
- **Таблица agentId (сессия e0)** — для повторного вызова: stage0 reviewer `a35b2c2705c870ff2`; blind tester `a89e101b11318f1ef`; docs `acdd9ae421094cb96`; developer `a9e34ff4be3ea032d`; инъекции `a28359caa5f72320e`; dry-run `a6df0cc231bd9162f`; Opus reviewer `adb0d23f1fc266e96`.
- Временные worktree не удалялись: `Inspector_bottles--lane-K-4c`, `Inspector_bottles--tester-4c` (detached `fe8318bb7`).
- **MEMORY LESSONS не записаны** (кандидаты): «общий `git stash` на все worktree: pop может снять чужой stash — вместо него WIP-коммит»; «тест значения в журнале: у `LoggerManager` default_level INFO, DEBUG-строки не пишутся, а секретные имена полей логгер маскирует сам — брать нейтральное имя»; «исключение вендорского хука через `cm.handle_command` глотает диспетчер — тест „не бросает“ звать прямым методом».
