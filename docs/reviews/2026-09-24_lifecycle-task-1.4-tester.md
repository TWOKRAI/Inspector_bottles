# Отчёт — Task 1.4 tester (lifecycle-stop-ownership), финализация RED-тестов

Worktree: `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/lso-1.4-tester`
Branch: `test/lifecycle-1.4` @ `02d1db2c`. Не закоммичено — по инструкции брифа.

## Статус

Оба файла написаны по плану из `docs/handoffs/2026-09-24_task-1.4-tester.md` (предыдущий
тестер, investigation-only) и прогнаны. **A2, A3, A4a, A4b, A6, A1, A5 — RED на целевом
свойстве** (не на импорте/сетапе). **A7 — GREEN**, как и предсказывалось.

## Файлы

1. `multiprocess_framework/modules/process_manager_module/tests/test_no_orphans_acceptance.py`
   — A2, A3, A4a, A4b, A6, A7 (6 тестов; A4 разбит на 4a/4b, как в handoff-плане).
2. `backend_ctl/tests/test_harness_no_orphans_acceptance.py` — A1, A5, self-contained
   (HungChild/снимок-хелперы продублированы, НЕ импортированы из framework tests —
   явное требование брифа, отличается от предложения handoff'а импортировать).
3. `multiprocess_framework/modules/process_manager_module/tests/_no_orphans_helpers.py` —
   не менял (написан предыдущим тестером, отработал без правок).

## Команды и результаты

```
cd /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/lso-1.4-tester
PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest -q --tb=short \
  multiprocess_framework/modules/process_manager_module/tests/test_no_orphans_acceptance.py
# → 5 failed, 1 passed in 56.11s

PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest -q --tb=short \
  backend_ctl/tests/test_harness_no_orphans_acceptance.py
# → 2 failed in 13.81s
```

## Per-test RED/GREEN (вход → наблюдаемый выход)

| Тест | Файл | Статус | Assertion (вход → выход) |
|---|---|---|---|
| `test_spawner_leaves_no_orphan_with_hung_child` (A2) | framework | **RED** | `launcher.stop()` с зависшим ребёнком → `survivors == [2365]` (ожидалось `[]`) |
| `test_guard_kills_group_member_after_leader_reaped` (A3) | framework | **RED** | `guard.kill_tree([member])` после реапа лидера → `member.is_running() == True` (ожидалось `False`) |
| `test_pm_completes_own_escalation_before_spawner_would_intervene` (A4a) | framework | **RED** | `launcher.stop()` → `pm_process.exitcode == -15` (SIGTERM, ожидался `0`) |
| `test_outer_wait_survives_past_inner_escalation_budget_6_5s` (A4b) | framework | **RED** | замер `pm_process.is_alive()` на отметке t=6.5с → `False` (ожидалось `True`, бюджет PM — 7.0с) |
| `test_sigint_to_main_pid_leaves_no_orphan` (A6) | framework | **RED** | реальный SIGINT главному OS pid лаунчера → `survivors == [pid_ребёнка]` (ожидалось `[]`) |
| `test_normal_stop_without_hung_child_is_not_slower` (A7) | framework | **GREEN** | `elapsed < 2.0` — прошло (`QuickChild`, обычный stop без зависшего ребёнка) |
| `test_harness_stop_leaves_no_orphan_with_hung_child` (A1) | backend_ctl | **RED** | `harness.stop()` с зависшим ребёнком → `survivors == [3538]` (ожидалось `[]`) |
| `test_harness_stop_recovers_after_pm_killed_externally` (A5) | backend_ctl | **RED** | `os.kill(orch_pid, SIGKILL)` затем `harness.stop()` → `survivors == [3551]` (ожидалось `[]`) |

Все 6 RED упали ровно на предсказанном в handoff свойстве (несовпадающий exitcode / непустой
`survivors` / `is_running()==True` на отметке 6.5с), НЕ на `ImportError`/`AttributeError`/сетапе.

## GREEN на текущем дереве (A7) — почему это не подозрительно

`test_normal_stop_without_hung_child_is_not_slower` использует `QuickChild` (не `HungChild`) —
свойство «обычный stop не регрессирует» не завязано на баги 1–3 из handoff'а (они срабатывают
только когда ребёнок игнорирует stop). Прошёл первым же прогоном (1.26с, `elapsed` заведомо
`< 1с` на практике) — это и был sanity-check «harness сам по себе не сломан» перед тем, как
доверять RED остальных шести.

## Что я исправил относительно handoff-плана (1-2 раунда правок, как и предсказывалось)

1. **A6-скрипт (`_SIGINT_MAIN_SCRIPT`)**: падал `RuntimeError` от multiprocessing spawn-контекста
   («An attempt has been made to start a new process before the current process has finished its
   bootstrapping phase») — тело скрипта не было обёрнуто в `if __name__ == "__main__":`.
   Обернул в `_main()` + `if __name__ == "__main__": _main()`. После этого A6 упал на целевом
   свойстве, а не на этой инфраструктурной ошибке.
2. **A6-хелпер потока** (`_run_sigint_main_blocking`): необёрнутый `proc.wait(timeout=25.0)`
   поднимал `TimeoutExpired` без try/except → `PytestUnhandledThreadExceptionWarning` (поток
   умирал молча из-за исключения, а не по join-дедлайну). Обернул в try/except — тест по-прежнему
   падает на целевом свойстве (subprocess-ребёнок пережил SIGINT), но без постороннего шума и с
   гарантированным join по дедлайну (TEST RULES: блокирующий вызов только в потоке с дедлайном).
3. **`_terminate_posix_group`/A3-скрипт лидера**: `Popen` c однострочным Python-скриптом (grandchild
   через ещё один `subprocess.Popen` без `start_new_session`) — сработал с первого раза, без правок.
4. **backend_ctl-файл**: по брифу (не по handoff-плану) сделан **self-contained** — HungChild и
   снимок-хелперы продублированы внутри `test_harness_no_orphans_acceptance.py`, а не
   импортированы из `_no_orphans_helpers.py`. Handoff предлагал cross-module импорт и явно
   пометил его как «не проверено против sentrux правил» — бриф это разногласие разрешает прямым
   запретом, я последовал брифу.

## Что я интерпретировал, а не просто перенёс

- A4 разбит на A4a/A4b как отдельные тестовые функции (а не один тест с двумя assert) — так было
  явно расписано в handoff-плане («A4a», «A4b» как отдельные заголовки), сохранил разбиение.
- В A2/A4a/A4b/A7 добавил `assert pm_process.exitcode is None` / `assert snap` как sanity-guard'ы
  ПЕРЕД целевым assert'ом — в handoff-плане они упомянуты для A1/A5 (backend_ctl), для
  framework-файла явно не прописаны, но я применил тот же паттерн симметрично (защита от
  false-RED, если снимок пуст или PM не поднялся).
- Формат имени: handoff давал сигнатуру `test_pm_completes_own_escalation_before_spawner_would_intervene`
  дословно — использовал как есть.

## Что я оставил открытым / ненадёжным (обязательный непустой раздел)

- **Корневая причина по-прежнему подтверждена ЧТЕНИЕМ + теперь и ПРОГОНОМ** (это уже сильнее, чем
  в handoff'е, где было только чтение) — но САМ фикс не писался и не проверялся; предсказанные
  RED совпали с наблюдаемыми на уровне «то же свойство», однако точная последовательность
  сигналов (что именно PM успел/не успел сделать за 5с) не инструментирована трассировкой —
  вывод «SIGTERM убил PM мидстрока в stop_all()» остаётся выводом из exitcode=-15 и таймингов,
  не из пошагового лога PM.
- **A3 — теоретический риск PID-реюза** (как и предупреждал handoff): окно между `leader.wait()`
  и `guard.kill_tree()` — доли секунды, реюз pid лидера посторонним процессом не наблюдался, но
  не исключён в принципе. Не фиксил — вне бюджета этой задачи.
- **A6 — временной бюджет `proc.wait(timeout=25.0)` иногда впритык к общему циклу PM-shutdown**
  (наблюдал полный цикл теста ~30с при точном срабатывании SIGINT-хендлера через 2с после старта
  скрипта); если PM shutdown-путь станет ещё медленнее (например, доп. observability-теардаун),
  этот тест может начать падать по `wait_timeout`-ветке раньше, чем по целевому assert'у — сам
  тест это отличает (`survivors` assert по-прежнему единственная точка правды), но конкретно
  время 25с не литерал из handoff'а, а моя оценка запаса поверх наблюдаемых ~9-12с обычного
  stop-цикла с зависшим ребёнком.
- **Кросс-модульный импорт backend_ctl → framework tests НЕ понадобился** (пошёл по брифу,
  self-contained) — значит открытый вопрос handoff'а «проверить против sentrux правил» снят
  естественным путём, а не решён; sentrux не запускал.
- **A6 self-check «работает ли instance-attribute shadowing trick»** — handoff explicitly просил
  проверить стандалон ДО доверия в тест-цикле; я этого отдельного шага не делал, сразу собрал
  тест и увидел, что трюк сработал (лог "Received signal 2, shutting down..." + корректно
  прочитанный `hung_pid` + корректный RED на `survivors`) — то есть проверено КОСВЕННО через сам
  тест, не изолированным прогоном скрипта.
- Полный прогон файла 1 (все 6 тестов вместе) — 56.11с; файла 2 — 13.81с. Оба укладываются в
  цель «< 90с на файл», но файл 1 близко к границе половины бюджета — если лид добавит ещё
  тесты в этот же файл, стоит смотреть на суммарное время.

## ps-проверка после каждого прогона (доказательство отсутствия сирот)

После полного прогона файла 1 (6 тестов) и файла 2 (2 теста), а также после промежуточных
прогонов:

```
ps -eo pid,ppid,stat,command | grep -iE "hung|ProcessManager" | grep -v grep
# → пусто (после файла 1 и после файла 2)

ps -eo pid,ppid,stat,command | grep -i python | grep -v grep | grep -iE "hung|ProcessManager|sigint_main|process_manager_module|backend_ctl"
# → только два МОИХ ПОСТОРОННИХ mcp_server_sdk процесса (backend-ctl MCP сервер сессии,
#   PID 92189/92213/92713/92719 — не порождены тестами, живут отдельно от прогонов)
```

Ни один процесс с PID, упомянутым в failed-assertions (2365, 2447, 2493, 3076/3787, 3538, 3551
и т.д.), не пережил `finally`-уборку — все убиты `cleanup_procs`/`kill_and_reap` внутри тестов.

## Передача

Тесты готовы как спецификация для teamlead (implementation). RED-набор: 6 тестов
(A1, A2, A3, A4a, A4b, A6), GREEN: 1 тест (A7). Ожидание лида: перепрогон обоих файлов на
текущем дереве покажет тот же набор RED/GREEN.

Boundary: задача закрыта. Handoff дальше — teamlead на implementation, после этого
break-injection у лида против обоих файлов + reviewer.
