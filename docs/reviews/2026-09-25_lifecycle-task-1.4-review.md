# Ревью Task 1.4 — «сирот нет после любого пути стопа» (lifecycle-stop-ownership)

**Вердикт: APPROVE_WITH_NOTES**
Диапазон: `02d1db2c..0efb72ce`, ветка `fix/lifecycle-1.4`, worktree `.claude/worktrees/lso-1.4-dev`. Ревьюер: reviewer (Opus), 2026-09-25.
Специализации: architecture, concurrency/lifecycle, security (класс «убить чужой процесс»). qex не использовался (Ollama выключен) — Grep/Read.

## Что прогнано (воспроизведение)

| Проверка | Команда / сценарий | Результат |
|---|---|---|
| 4 новых тест-файла | `pytest -q multiprocess_framework/.../test_no_orphans_{acceptance,hazards}.py backend_ctl/tests/test_harness_no_orphans_{acceptance,hazards}.py` | `32 passed in 60.06s` |
| ruff по изменённым файлам | `ruff check -q <файлы диапазона>` | 2 замечания в тестах (E731, F401) — см. minor-3 |
| (b) два стенда в одном процессе | scratchpad `two_stands.py`: реальный прототип, A на 9711, B на 9712, `A.stop()` | A.stop 1.05 с; из 9 процессов B мёртвых 0 сразу и 0 через 3 с; `introspect_status("ProcessManager")` у B — `True` ×3; resource_tracker хозяина жив; B.stop 0.82 с; `spawn_main` с PPID 1/хозяин — 0 |
| (a) переиспользование pid | scratchpad `pid_reuse.py`+`cycler.py`: «PM» с `setsid` собран, pid 11933 отдан чужому лидеру сессии после полного оборота pid | см. minor-1 |
| (d) второй SIGINT во время стопа | scratchpad `sigint_twice.py`: `SystemLauncher.run()` + HungChild, SIGINT в t=3.01, второй в t=4.01 | вложенный `spawner.stop` (глубина 2) + третий вызов из `finally` в `run()`; сирот 0; см. note-4 |

## Находки (по убыванию)

### minor-1 [security/lifecycle] Устаревший pid PM используется без сверки личности ещё в трёх новых местах
Вход: PM собран (`waitpid`), его группа пуста, pid переиспользован чужим лидером сессии.
Наблюдение (реальный прогон, macOS): fake-PM pid 11933 собран; циклер получил 11933 после 83 261 fork'а за 1807 с
(полный оборот PID_MAX 99 999); чужой V=11933 (`ppid 1, pgid 11933, sid 11933`) + 2 члена группы. Затем:
- `spawner._snapshot_descendants()` (новое, корень = `psutil.Process(self._process.pid)`) → `[11933, 11938, 11943]` — чужие;
  дальше `_sweep_snapshot` их убил бы (`is_running()` истинно — снимок только что снят);
- `harness._subtree(11933)` → те же три (новый досъём в `stop()`, `harness.py:488`; старый — в `_force_kill_tree`);
- `harness._kill_orchestrator_group(11933)` → лог `killpg(11933, SIGKILL): добиты остатки группы PM`; живых из чужой группы — `[]`.
- путь guard'а `os.getpgid(11933)` → `11933` (≠ группы хозяина 13751) → `killpg` чужой группы — **этот путь был и на базе**.

Оценка достижимости: окно «сбор PM → killpg/снимок» на штатных путях ≈ 1 с (A.stop целиком 1.05 с), а оборот pid даже при
форсированном fork занял 30 мин — на штатных путях недостижимо. Достижимо при ДЛИННОМ окне: PM умер задолго до `stop()`
(session-фикстура harness'а, краш PM), дети тоже ушли, pid переиспользован. Регрессии исхода относительно базы нет: на базе
тот же чужой процесс убивают `_force_kill_tree._subtree(P)` и `getpgid(P)`-путь guard'а. Но ADR-PMM-031 «Принятый риск»
называет только killpg по лидеру пустой группы; новые пути (`_snapshot_descendants`, `_sweep_snapshot`) расширяют риск до
«pid достался ЛЮБОМУ процессу».
Fix (дёшево, follow-up): (1) `_snapshot_descendants` → `[]`, если `self._process.exitcode is not None` (PM уже собран);
(2) harness: личность PM из раннего снимка (`self._descendants[0].create_time()`), перед `_subtree`/`killpg` —
`NoSuchProcess` → killpg допустим, другой `create_time` → пропуск; (3) дописать в ADR «Принятый риск» все четыре потребителя.
Подтверждение того, что путь реально исполняется: в (d) третий `spawner.stop` из `finally` в `run()` зовёт
`_snapshot_descendants` по уже собранному PM на каждом стопе по SIGINT (окно — миллисекунды).

### minor-2 [architecture] Инвариант «худший случай spawner'а < watchdog harness'а» держится только при graceful ≤ 8 с (ADVISORY — арифметика, не прогон)
Худший случай spawner'а (PM сам завис) = `outer_stop_budget(g)` + terminate-join 3.0 + guard 0.5 = `g + 7.0`; < 15.0 только при
`g < 8.0`. `system.stop_timeout` в схеме `min=1.0, max=30.0` (`multiprocess_prototype/backend/config/schemas.py:28`), и теперь
он же — graceful PM (`spawner.py:102-103`). Вход `stop_timeout=30` → spawner до 37 с, watchdog harness'а 15 с срабатывает
посреди стопа, а daemon-поток shutdown продолжает работать после возврата `harness.stop()`. Сегодня прод передаёт 5.0
(`system.yaml:8`); `stop(timeout=…)` и `orchestrator_config["shutdown_timeout"]` в проде не передаёт никто (grep:
единственный вызов `system_launcher.py:574` без аргумента). Побочный эффект связки: при `stop_timeout=30` зависший ребёнок
добивается PM через ~31 с вместо ~6 с до правки (PM раньше всегда брал 5.0). Fix: либо watchdog harness'а выводить из
`outer_stop_budget(...) + 3.5 + запас`, либо записать в ADR границу `g ≤ 8` и поведенческое изменение для нестандартного `stop_timeout`.

### minor-3 [quality] ruff в тестах диапазона
`backend_ctl/tests/test_harness_no_orphans_acceptance.py:125` E731 (lambda в переменной);
`multiprocess_framework/.../tests/test_no_orphans_acceptance.py:26` F401 (`alive_pids` не используется). Fix: `def factory()`, убрать импорт.

### note-4 [concurrency, pre-existing] Второй SIGINT — вложенный стоп, не «аварийный выход»
Наблюдение: `spawner.stop calls (depth, start, end): [(1, 3.01, 9.2), (2, 4.01, 9.2), (1, 9.2, 9.2)]`, `run()` вернулся
в t=9.20, зависший ребёнок мёртв, трассировок нет. Второй Ctrl+C не ускоряет выход; `on_shutdown` и `SRM.shutdown`
отработали трижды без ошибок. Структура (обработчик → `self.stop()`, плюс `finally: self.stop()` в `run()`) — до 1.4;
правка лишь расширила окно «Ctrl+C не действует» с 5.0 до 8.5 с (+3 с, если завис сам PM). Не блокер.

### note-5 (e) Windows — только чтение, машины нет
`_kill_orchestrator_group` пропускается на win32; `os.getpgid` на Windows не достигается. Изменения поведения на Windows:
после `TerminateJobObject` теперь всегда `_sweep_snapshot`; psutil-fallback (если job не создан) берёт только снимок
поддерева PM, без детей хозяина — для дерева PM эквивалентно (осиротевшие внуки и раньше не находились через `children()`
хозяина), для чужих детей хозяина — это и есть исправление. Не прогонялось.

## Что сделано хорошо
Разнесение звеньев и их независимые тесты; снимок, укоренённый в PM, закрыл найденный лидом удар по resource_tracker —
живой прогон (b) это подтверждает; константы `TERMINATE_GRACE_S`/`KILL_CONFIRM_S` связывают внешний бюджет с внутренним по построению.

## Что не проверял
- Break-injection не повторял (сделано лидом, I1–I5); живой inspection_full не повторял.
- (c) watchdog-гонку при `stop_timeout > 8` живьём не воспроизводил — только арифметика по константам.
- Linux (pid_max 4 194 304 — окно переиспользования там ещё реже) и Windows не прогонялись.
- sentrux CLI по границам слоёв не запускал (новых импортов между слоями нет: `spawner` → `core.process_registry` внутри модуля).

## What I left open / unreliable
- Достижимость minor-1 в реальной эксплуатации оценена рассуждением («PM умер задолго до stop»), конкретного теста или
  сценария прототипа, который так делает, я не нашёл и не искал исчерпывающе.
- Оборот pid получен искусственно (форсированный fork 30 мин); скрипт-обвязка упал после HIT (я сам убил V до его шага),
  поэтому результат снят вторым ручным прогоном по живому V=11933 — вывод процитирован выше, но это один прогон.
- (d) — один прогон с зазором 1.0 с; другие зазоры (SIGINT во время `guard.kill_tree` или `SRM.shutdown`) не пробовал.
- Утверждение ADR «пока группа не пуста, её pgid не выдаётся новому процессу» на macOS не проверял экспериментом.
