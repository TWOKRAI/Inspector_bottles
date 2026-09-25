# Task 1.5 — тестер, acceptance-тесты «ребёнок не переживает PM» (RED before implementation)

Ветка `test/lifecycle-1.5`, worktree `.claude/worktrees/lso-1.5-tester`, база `main@31ddc570`.
Контракт (C1-C7) получен в брифе ведущего; `plans/lifecycle-stop-ownership.md` и
`docs/handoffs/2026-09-25_lifecycle-stop-ownership-after-1.4.md` НЕ читались (форбидден).

## Файлы

1. `multiprocess_framework/modules/process_manager_module/tests/test_parent_death_acceptance.py` — C1-C4, C7-restart
2. `multiprocess_framework/modules/process_manager_module/tests/_parent_death_helpers.py` — host-скрипт (`python -m ... <сценарий>`)
3. `backend_ctl/tests/test_harness_parent_death_acceptance.py` — C6, C7-stop
4. Этот отчёт

## Дизайн (кратко)

Для C1-C4 «родитель» — отдельный OS-хост-процесс (не pytest), который строит
`ProcessRegistry(logger=None)` + `create_and_register` + `Process.start()` — тот же
путь, каким PM спавнит детей на старте/рестарте. Хост печатает JSON-строку(и) с pid'ами
в stdout (flush), затем засыпает на 600с — умирает только от SIGKILL теста, никогда сам.
`QuickChild`/`HungChild` **импортированы** из `_no_orphans_helpers.py` (Task 1.4), не
продублированы — файл читался только (изменений нет). Чтение stdout — в daemon-потоке с
join-дедлайном (никакой блокирующий вызов без потолка). Хост-родитель реапается
`proc.wait(timeout=...)` в `_kill_host`, дети — `kill_and_reap` из `_no_orphans_helpers`.

Для C6 — `BackendHarness` тем же паттерном, что Task 1.4
(`backend_ctl/tests/test_harness_no_orphans_acceptance.py`): self-contained файл,
дублирует `HungChild`/`QuickChild`/снимок-хелперы (тот же прецедент дублирования, не
импорт из framework tests). Порт — строго `[9800, 9899)` (не bind(0) ephemeral) — бронь
8860-8910 занята gui-service. C6 добавляет zombie-aware снимок живости
(`_alive_pids_zombie_aware`), т.к. контракт явно требует считать зомби «ушедшим», а
`psutil.is_running()` для зомби возвращает `True`.

## RED/GREEN — точное совпадение с предсказанием

Команда: `PYTHONPATH=$PWD .venv/bin/python -m pytest -q --tb=short <оба файла>`. 9 тестов,
25.69с, 4 упали / 5 прошли — **ровно** предсказанный REDS-набор, расхождений нет.

| Тест | Контракт | Факт | Падение (реальная строка) |
|---|---|---|---|
| `test_child_exits_after_parent_sigkill` | C1 | **RED** | `AssertionError: ребёнок pid=59898 пережил SIGKILL родителя (PM) дольше 2.0с (C1)` |
| `test_hung_child_exits_after_parent_sigkill` | C2 | **RED** | `AssertionError: зависший ребёнок pid=59912 пережил SIGKILL родителя дольше 2.0с (C2)` |
| `test_child_exits_when_parent_dies_during_boot` | C3 | **RED** | `AssertionError: ребёнок pid=59922 пережил гибель родителя во время своего boot дольше 2.0с от момента наблюдения pid (C3)` |
| `test_children_stay_alive_while_parent_alive` | C4 | **GREEN** | — (родитель жив → дети живут ≥5.2с, ложных срабатываний нет) |
| `test_child_started_from_short_lived_thread_survives` | C4 | **GREEN** | — (ребёнок переживает выход спавнившего потока на ≥3.2с) |
| `test_restarted_child_survives` | C4 | **GREEN** | — (пересозданный под тем же именем — жив) |
| `test_restart_time_not_worse` | C7 | **GREEN** | — (0.43-0.45с < потолка 1.0с) |
| `test_kill9_pm_leaves_no_children` | C6 | **RED** | `AssertionError: дети PM пережили kill -9 PM дольше 2.0с (C6): [60019]` |
| `test_harness_stop_time_not_worse` | C7 | **GREEN** | — (1.18с < потолка 2.0с) |

Механизм всех трёх C1-C3/C6 падений один и тот же (подтверждено чтением `runner/process_runner.py`
и `core/process_registry.py`, БЕЗ обращения к запрещённым путям): `_run_lifecycle` опрашивает
ТОЛЬКО `stop_event`/`system_stop_event`/`should_stop()` — наблюдателя смерти родителя (PPID)
сегодня нет ни в одном пути. `create_and_register`/`_create_process` этот механизм тоже не
заводят. Ожидаемо RED «по конструкции», не по случайности окружения.

## C7 — baseline-числа (замерено на ЭТОМ дереве, до реализации Task 1.5)

- **Рестарт одного процесса** (`stop_one` → `remove_process` → `create_and_register` → `start`,
  in-process, ProcessRegistry напрямую), 5 прогонов throwaway-скриптом (не сам тест):
  `0.434s / 0.448s / 0.441s / 0.431s / 0.446s` (макс. 0.448с) → потолок в тесте **1.0с**
  (литерал, запас ~2.2x худшего замера).
- **`harness.stop()`** (headless-стенд, QuickChild, без зависшего ребёнка), 3 прогона
  throwaway-скриптом: `1.178s / 1.175s / 1.180s` (макс. 1.180с) → потолок в тесте **2.0с**
  (литерал, запас ~0.82с/~70% сверх худшего замера — та же логика, что у framework-теста A7
  из Task 1.4).

Throwaway-измерители не сохранены (жили в scratchpad сессии, не в репозитории) — числа
зафиксированы здесь как единственный источник. Если ведущий захочет их воспроизвести — код
измерителей тривиален (та же последовательность вызовов, что в самих тестах, обёрнутая
циклом `for i in range(N)`).

## Что интерпретировано, а не продиктовано бриф

- **C4c (пересозданный ребёнок) не имеет числового порога в контракте** — только «остаётся
  жив». Взял тот же порядок величины, что C4b (~2с), с явной оговоркой в комментарии теста.
  Если ведущий имел в виду другое число — тривиально правится.
- **Сценарий `boot_race`**: контракт C3 говорит «child pid pid observable» — трактовал это как
  момент, когда хост печатает JSON-строку с pid (сразу после `start()`, без settle-окна). Дедлайн
  2.0с отсчитывается от этого момента, а не от момента SIGKILL (между ними — доли миллисекунд
  на чтение строки + сам syscall kill).
- **`ProcessRegistry(logger=None)` без `queue_registry`/`shared_resources`** — минимальный
  конструктор, подтверждённый существующим `test_process_registry.py::test_create_and_register_
  provides_ready_event`. Не изобретение — воспроизведение уже проверенного паттерна.
- **Порт-диапазон C6**: контракт дал `[9800, 9899)`; я написал собственный `_free_port()` с
  ретраем внутри диапазона (а не `bind(0)`, как в Task-1.4-файле) — bind(0) не гарантирует
  диапазон.

## Что осталось открытым / ненадёжным в моей же работе

- **C7 baseline — 3-5 прогонов на ОДНОЙ машине, throwaway-скриптом, не через сам pytest-тест.**
  Дисперсия внутри каждого набора мала (±0.017с / ±0.005с), но это один прогон набора замеров,
  не статистика по дням/нагрузке машины. На CI-машине с другим железом потолки (1.0с / 2.0с)
  могут оказаться и слишком тесными, и слишком щедрыми — это не проверено.
- **C4c (2.0с) — число не из контракта, а моя экстраполяция** (см. выше) — если ведущий ожидал
  другую величину или сам факт "жив" без временного порога, тест придётся поправить.
- **Порядок операций в `run_restarted_child`** — `stop_one(timeout=5.0)` перед `remove_process`.
  Контракт написал `stop -> remove -> create_and_register -> start`, я читаю `stop` как
  `registry.stop_one` (единственный метод, дающий «ensure stopped» с подтверждением смерти) —
  не пробовал альтернативную интерпретацию (например, прямой `stop_event.set()` без join).
- **Не проверял Linux/fork-контекст** (вне скоупа, POSIX/spawn — macOS here; brief исключает
  Linux/Docker явно) — все `pytestmark = skipif(win32)` предполагают, что POSIX-семантика
  SIGKILL/psutil одинакова между macOS spawn и Linux fork, но сам код не гонял.
- **`_read_json_lines`** при таймауте оставляет daemon-поток блокированным на `readline()` —
  не леденеет процесс (демон, умирает с интерпретатором), но если тест зависал бы регулярно,
  это накопило бы фоновые потоки за сессию pytest. В моём прогоне таймаутов не было.
- Не проверял поведение при **PID reuse** между наблюдением снимка и опросом `wait_until_gone` —
  переиспользуется тот же риск, что framework уже принял в `_no_orphans_helpers.py` (identity по
  `create_time()` у `psutil.Process`, не голый pid); я это унаследовал как есть, не добавлял
  дополнительной защиты.

## Утечки запрещённой информации

Не было. `plans/lifecycle-stop-ownership.md`,
`docs/handoffs/2026-09-25_lifecycle-stop-ownership-after-1.4.md`,
`.claude/worktrees/lso-1.5-dev/`, ветка `fix/lifecycle-1.5` — не читались, не грепались, git log
на чужую ветку не запускал. Единственный `grep`/поиск по процессам после прогона тестов —
`ps -axo pid,ppid,command | grep ...` для проверки leftover-процессов (TEST RULES), случайно
поймал НЕСВЯЗАННЫЙ процесс другой параллельной сессии (`stand.py` под другим scratchpad, pid
54005/60051) — не трогал его, только убедился, что мои собственные pid'ы (59898, 59912, 59922,
60019) среди живых процессов после прогона отсутствуют.

## Проверка leftover-процессов

`ps -axo pid,ppid,command | grep -E "_parent_death_helpers|59898|59912|59922|60019"` — пусто
(exit 1). Никаких `spawn_main` от моего прогона не осталось.
