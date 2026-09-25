# Task 1.6 — приёмка тестера (RED, до кода)

Ветка `test/lifecycle-1.6` @ `dbeb9110`, worktree `.claude/worktrees/lso-1.6-tester`.
Контракт — только «Контракт записи» из брифа лида (`plans/lifecycle-stop-ownership.md`
→ Task 1.6). Implementation, план целиком (кроме раздела Task 1.6) и авторские тесты
НЕ читались — запрещены заданием.

## Файл

`backend_ctl/tests/test_stop_summary_live.py` — 3 теста, порты 9810–9812 (диапазон
9810–9829 не выходит).

## Прогон (полная команда из брифа)

```
PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest \
  backend_ctl/tests/test_stop_summary_live.py --backend-live -q --tb=short
```

```
backend_ctl/tests/test_stop_summary_live.py FFF                          [100%]
=========================== short test summary info ============================
FAILED backend_ctl/tests/test_stop_summary_live.py::test_normal_stop_writes_one_stop_summary_record
FAILED backend_ctl/tests/test_stop_summary_live.py::test_stop_summary_numbers_match_stderr_lines
FAILED backend_ctl/tests/test_stop_summary_live.py::test_killed_child_is_reported_false_and_warning
============================== 3 failed in 21.46s ==============================
```

Три из трёх — RED, все AssertionError на отсутствие записи, не ошибка стенда/сбора.

### 1. `test_normal_stop_writes_one_stop_summary_record`

```
AssertionError: ожидалась РОВНО одна запись сводки стопа (process='ProcessManager',
message startswith 'stop summary:'), найдено 0: []
assert 0 == 1
```

Обычный стоп `inspection_full` (2.0s лёгкого трафика, `harness.stop()`), запись стора
после — ни одной строки `stop summary:` от `ProcessManager`. Ровно то, что механизм ещё
не существует.

### 2. `test_stop_summary_numbers_match_stderr_lines`

```
AssertionError: ожидалась РОВНО одна запись сводки стопа, найдено 0: []
assert 0 == 1
```

Та же причина — до сверки чисел со stderr дело не доходит, запись отсутствует.

### 3. `test_killed_child_is_reported_false_and_warning`

Первая попытка упала не там, где нужно — на `pid is not None` (баг теста: читал
`reply.get("processes")` вместо `reply["result"]["processes"]` — форма ответа
`system_command` несёт полезную нагрузку под ключом `result`). Исправлено, пере-прогон:

```
2026-09-25 23:00:46,438 [WARNING] [ProcessManager] ProcessManager: [supervisor] renderer: crashed — exitcode=-9
2026-09-25 23:00:46,438 [ERROR] [ProcessManager] ProcessManager: Process 'renderer' crashed (exitcode=-9), авто-рестарт отключён — процесс оставлен в состоянии crashed
...
AssertionError: ожидалась РОВНО одна запись сводки стопа, найдено 0: []
assert 0 == 1
```

`FW_AUTORESTART=0` сработал буквально — лог PM сам подтверждает: «авто-рестарт
отключён, процесс оставлен в состоянии crashed» (не воскрешён). RED по той же причине —
записи нет вовсе.

## Как сделан детерминизм убитого ребёнка (Task 3)

- `monkeypatch.setenv("FW_AUTORESTART", "0")` ДО `harness.start()` — отключает
  `RestartPolicy` PM целиком на уровне спавна (`process_manager_process.py`:
  `is_enabled("FW_AUTORESTART")`), а не таймингом после kill. Гонка с авто-рестартом
  исключена структурно.
- pid `renderer` снят живым запросом `drv.system_command({"cmd": "supervision.status",
  "process": "renderer"})` — команда подтверждена грепом диспатч-таблицы PM (`"supervision.status":
  (self._cmd_supervision_status, ...)`), а не угадана.
- `os.kill(pid, signal.SIGKILL)`, затем 1.0s ожидания (>> `monitor_poll_interval` дефолт
  0.5s) — дать PM время увидеть смерть до `harness.stop()`; живой прогон подтвердил:
  PM заметил exitcode=-9 и явно залогировал отказ от рестарта.

## Ловушка env `INSPECTOR_LOG_DIR` (найдена при исследовании, не в тестах)

`SystemBuilder.build()` (`multiprocess_prototype/backend/launch.py:669`) фиксирует
`INSPECTOR_LOG_DIR` через `os.environ.setdefault(...)` — ПЕРВЫЙ `harness.start()` в
процессе pytest замораживает его для всех последующих запусков в том же процессе.
`resolve_default_db_path()` (`observability_store.py:131`) читает `MULTIPROCESS_LOG_DIR`
СИЛЬНЕЕ `INSPECTOR_LOG_DIR` — каждый тест здесь ставит `MULTIPROCESS_LOG_DIR` обычным
`monkeypatch.setenv` (не `setdefault`) на свой `tmp_path` до `start()`, снимая ловушку
независимо от порядка тестов. Проверено эмпирически: три прогона дали три разных пути
`.../run_normal/observability.db`, `.../run_stderr/observability.db`,
`.../run_kill/observability.db` — коллизии нет.

## Контрактные точки, которые не удалось покрыть / выглядят неоднозначно

- **`kind` записи не назван в брифе.** Я фильтрую по `process='ProcessManager'` +
  префикс `message`, не по `kind` — контракт не говорит, `kind='log'` это или что-то
  своё. Если реализация выберет другой `kind`, мой фильтр всё равно найдёт запись
  (не завязан на это поле) — риск ложного PASS от постороннего совпадения
  `process=='ProcessManager'` + случайного сообщения с этим префиксом расцениваю как
  пренебрежимый.
- **`extra["stop_summary"]` как ТОП-УРОВНЕВЫЙ ключ, а не вложенный в `extra["context"]`.**
  Прочитанный нормализатор (`record_display.hub_record_to_display`) кладёт в `extra`
  ЛЮБОЙ ключ входной записи, кроме конверта (`kind/module/process/ts/severity/message/
  observed_ts`) — БЕЗ вложения под `context` (это подтверждено чтением кода стора,
  не implementation задачи; путь чтения, а не implementation-файл механизма 1.6). Если
  разработчик выберет писать запись через путь, который заворачивает произвольные
  kwargs в `context` (как делает типовой `logger.info(msg, **kwargs)` хелпер лога), то
  `extra["stop_summary"]` в проде окажется по факту `extra["context"]["stop_summary"]`
  — мой тест это НЕ примет (контракт лида буквально говорит `extra` несёт ключ
  `stop_summary`, не `extra.context.stop_summary`). Называю это явно: если у
  разработчика с реализацией разойдётся — это несовпадение моей буквальной трактовки
  брифа с удобным путём записи, а не мой домысел из чужого кода — сам код записи (Task
  1.6) не читался.
- **Что считается «стоп, реализуемый как `PM.shutdown()`».** Я использую
  `harness.stop()` — тот же самый системный путь, что Task 1.1 сделала общим для
  `system.shutdown`/`harness.stop()`/SIGINT (см. `test_system_shutdown_live.py`). Не
  проверял отдельно `system.shutdown`-путь и путь SIGINT — бриф не просил
  дублировать все три пути, «ровно одна запись на `PM.shutdown()`» подразумевает один
  и тот же метод независимо от триггера (это уже приёмка Task 1.1, а не 1.6).
- Не тестировал: несколько подряд стопов в одном pytest-процессе (нет ли утечки/дубля
  записи между несколькими `ObservabilityStore` открытиями одного файла — каждый тест
  открывает СВОЙ файл, так что это вне периметра теста); поведение при `history.enabled=False`
  (бриф не называет этот случай).

## Что интерпретировал, а не выполнял буквально

- Порядок ключей словаря `stop_summary` не проверяю (Python dict, JSON round-trip) —
  контракт не называет порядок значимым.
- `severity` сравниваю регистронезависимо (`.upper() == "WARNING"/"INFO"`) — контракт
  пишет литералы заглавными, но колонка в сторе исторически хранит severity в нижнем
  регистре (см. `test_observability_store.py`); не хочу пиновать регистр как часть
  контракта, которого бриф не называл явно.
- `test_normal_stop_writes_one_stop_summary_record` проверяет правило severity не
  литералом, а независимой реализацией того же правила из брифа
  (`_expected_severity`) — числа берутся из ТОЙ ЖЕ записи (`extra.stop_summary`), не
  из независимого источника (при лёгком трафике реальные `released/buffered_dropped`
  не предсказуемы литералом заранее). Это кросс-полевая проверка (severity согласуется
  с extra), не self-fulfilling — умышленно слабее, чем `test_killed_child_...`, где
  ожидание WARNING литеральное и не зависит от значений.

## Что осталось непроверенным / ненадёжным (обязательный раздел)

- Гонка A1 из Task 1.3 (`reader_gone.py`: feeder ещё жив между `close()` и своим
  выходом → ложное «отпущено» без потери) может изредка дать `released>0` для
  ребёнка без реальной потери даже при лёгком трафике — тогда
  `test_stop_summary_numbers_match_stderr_lines` НЕ флакует (числа сверяются с
  реальной stderr-строкой этого же прогона, не с ожиданием «всегда 0»), но
  `test_normal_stop_writes_one_stop_summary_record`'s `reported is True` держится
  всегда — гонка её не касается.
- Task 1.4 упоминает нестабильность признака `(system-wide)` в `process_runner.py:39`
  (`test_system_shutdown_children_exit_hook_in_system_stop_mode`, до 1/14 — 4/23
  прогонов). Механизм 1.6 транспортирует данные из ТОГО ЖЕ хука выхода — если гонка
  срывает сам факт входа в системный хук, `reported` может внезапно стать `false` у
  ребёнка, который на деле остановился штатно. Не воспроизводил это специально
  (дорого — требует много прогонов), только называю риск для развития
  `test_normal_stop_writes_one_stop_summary_record` в CI.
- `test_killed_child_is_reported_false_and_warning` — единичный прогон (kill дорог:
  полный подъём/останов ~10s). Единичный green после фикса не доказывает отсутствие
  собственных гонок этого теста (например, если PM успевает увидеть смерть renderer'а
  ПОСЛЕ входа в `stop_all`, а не до — контракт не уточняет таймаут этого перехода).
- Не проверял, что записи стора отдельных детей (`kind='log'`/`'stats'` от самих
  camera_0/processor/... ) НЕ содержат случайно ключ `stop_summary` у себя — фильтр
  по `process='ProcessManager'` должен это исключить структурно, но отдельного
  негативного теста «у детей такого ключа нет» я не писал (не входит в REDS брифа).

## Коммит

`64f9c022` — `test(framework): [RED] lifecycle 1.6 — приёмка сводки стопа`

Boundary: задача 1.6-tester закрыта. Дальше — `/dev:implement Task 1.6` (developer) в
своём worktree `.claude/worktrees/lso-1.6-dev`, branch `fix/lifecycle-1.6`; при переносе
файла теста в дерево разработчика — не редактировать логику, только копия per «Carry
the file back into the main tree afterwards» (owner's decision, `.claude/CLAUDE.md`).
