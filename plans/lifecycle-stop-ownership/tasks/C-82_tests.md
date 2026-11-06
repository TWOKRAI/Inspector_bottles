# C-82 — hazard автора, матрица инъекций, стенд

> Вынесено из [`C-82.md`](C-82.md) (размер файла). DESIGN, FILES, ACCEPTANCE — там.

## Hazard автора (`teamlead`)

Каждый тест, который может зависнуть, — вызов в daemon-потоке с `join(deadline)`.

- **H1 P1:** фейковый подъём, `stop_event` взведён внутри `super().initialize()` (подмена шага базы) → `_configure_runtime`
  0 вызовов, watcher не создан, `initialize()` → `True`, INFO P1 дословно.
- **H2 P5:** `_configure_runtime` подкласса сам взводит `stop_event` → watcher не создан, INFO P5 дословно; без стопа —
  watcher создан (страж).
- **H3 хук, три точки** (`ProcessManagerProcessApp` или фейк с `boot_stop_requested`, `app_discover` подменён
  через `monkeypatch` на `multiprocess_framework.modules.app_module.discover`): (а) стоп до хука → `discover` 0 вызовов,
  `_topology_manager.configure` 0; (б) фейковый `discover` взводит стоп внутри → `discover` 1 вызов, `configure` 0,
  INFO P4; (в) стоп не взведён → `discover` 1, `configure` 1. Оркестратор без `boot_stop_requested` → (в).
- **H4 P6:** `_run_lifecycle` с фейк-процессом, оба события по отдельности (`own` / `system`) → `run` 0 вызовов, `stop`
  ровно 1, возврат за < 0,5 с; строка `Stop signal received before run() — run() skipped` (и `(system-wide)` для одного
  `system`).
- **H5 предикат:** только `stop_event` → `boot_stop_requested()` `True`; только `_system_stop_event` → `True`;
  `_children_stopping = True` без событий → `True`; ничего → `False`; PM из `__new__` без атрибутов → `False` без
  исключения.
- **H6 повторный shutdown:** во время подъёма (стоп в P1) два `system.shutdown` — `graceful`, затем `force`
  `deadline_s=1.0` → `close_root` 1 раз, срок `force` применён (ответ `mode: "force"`), второй `force` —
  `already_set: True`.
- **H7 порядок:** стоп взведён после возврата `initialize()`, но до `run()` (точка между `:420` и `_run_lifecycle`) →
  P6 ловит, `run` 0; стоп после старта `run()` → старый путь (цикл `:191-198`), `run` 1, `stop` 1.
- **H8 настоящие объекты:** `run_process_function` в `multiprocessing` (spawn) с подклассом `GenericProcessManagerApp`
  из тестового модуля, один настоящий ребёнок (`LifecycleChild` из тестов PM, стоп 0,5 с) и `_configure_runtime` = сон
  6,0 с; системный стоп взводится, когда ребёнок `alive` и PM ещё в `initialize()` (`boot_ready_timeout_s` выше
  времени готовности ребёнка не нужен — стоп по метке файла ребёнка) → ребёнок выходит сам, `exitcode` 0, раньше PM; PM
  выходит за < 3,0 с от стопа, `exitcode` 0, строки `survivors after root close` нет.
- **H9 не провал подъёма:** прерванный подъём → в `messages.log` PM нет `Process initialization failed`, состояние
  процесса не `error`.
- **H10 TRAP 1 (первым, на базе):** ребёнок `GenericProcess` с фейк-плагином, у которого `boot`/ресурс открывается в
  `initialize()` процесса: стоп до `run()` → ресурс плагина закрыт (`do_shutdown` или его аналог вызван ровно раз).
  Сначала выяснить по коду, где ребёнок поднимает плагины (`initialize()` или `run()`), и записать `файл:строка` в
  отчёт.

## Матрица инъекций — прогноз (записан до прогона; вердикт лида)

| # | Свойство / инъекция | Ожидаемо красные |
|---|---|---|
| И1 | снять проверку P1 | R1, R2, R6, H1, H8 |
| И2 | снять проверку P5 | H2 |
| И3 | снять проверку P2 | R7, H3(а) |
| И4 | снять проверку P4 | H3(б) |
| И5 | снять проверку P6 | R3, H4, H7(первая половина) |
| И6 | P6 пропускает `run()`, но не зовёт `stop()` | R4, H4 |
| И7 | P1 возвращает `False` вместо `True` | R9, H9 (и R1/R2 остаются зелёными) |
| И8 | предикат без `stop_event` (только `_pm_stopping()`) | H5(первая строка); R1/R6 — если тестер взводит только `stop_event` (проверить по его файлу, записать до прогона) |
| И9 | после ветки P6 не `return`, а провал в цикл ожидания | R4, H4 (`stop` 2 раза) |

Совпадение — каждое; расхождение — находка о силе теста, разбор в отчёте.

## Стенд (бриф 2)

- **S5 → warm.** Каждый прогон (не только первый) ждёт `wait_full_boot(be)` (`stand_l9.py:1620`) + 2,0 с перед
  снимком и `system.shutdown`. Порог `THRESHOLDS["S5"]` (`:51`) не меняется. Прогон 1 — рестарты и `recipe.activate`, как
  был (`:1288-1340`).
- **S5b (новый, рядом с `run_s5`, `:1278`).** `REPEATS["S5b"] = 3` (`:63`), флаг `--only S5b` рядом с `allowed`
  (`:2035`). Прогон: `Backend.start()` (выход — `devices` alive), сразу снимок supervision и `system.shutdown`
  `graceful`. Мерить от `t_send` (monotonic перед отправкой): выход **каждого** PID снимка, PM и лаунчера — через
  `watch_pid_exit` (OpenProcess(SYNCHRONIZE) + WaitForSingleObject), без `tasklist` и psutil. PID PM **не** из
  `introspect_status` (в early PM ещё не в `run()` и не отвечает — `pm None` 3/3 у investigator): из PID-реестра
  (`MULTIPROCESS_PID_FILE`, `register_self`) или из записи `ProcessManager` в supervision, если она есть — автор
  проверяет и пишет источник в отчёт. Плюс признаки из `logs/ProcessManager/messages.log` прогона: есть ли строка P1/P4,
  есть ли `discover:`, `Stop signal received before run()`. Логи прогона сохранять в каталог результата (`runs/`).
- **Вердикт S5b:** `THRESHOLDS["S5b"] = {"max_pm_exit_s": None}` → `MEASURE` (числа без PASS/FAIL), пока лид не
  впишет порог; с порогом — `PASS`, если все прогоны ниже. `test_stand_l9_verdict.py`: оба случая.
- Стенд — только через шлюз, в окне лида: `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy inspector-bottles-56 <python> docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_l9.py --only S5b`.
