# Передача: полоса Ф — L-9 остаток закрыт анализом, дальше Task 1.9 (стадия 0)

Сессия inspector-bottles-07, 2026-10-20. Координатор — inspector-bottles-fb (имя — в `machine.lock`).
Новой сессии: первое сообщение координатору — своё имя (первая строка ListAgents); первая строка ответов владельцу —
«Полоса Ф · Task 1.9 · <имя сессии>».

## Состояние (из git)

- Ветка `docs/lifecycle-l9-residual` (worktree `.claude/worktrees/l9-residual`), от `main a5485097a`, не влита:
  - `0da37ff28`, `856bb2e0c` — отчёт L-9 остатка + вердикт CTO:
    [`docs/reports/2026-10-20_lifecycle-stop-ownership_L-9-residual.md`](../reports/2026-10-20_lifecycle-stop-ownership_L-9-residual.md)
    (подробно — `_details.md`, доказательства — `2026-10-20_L-9-residual-evidence/`);
  - `e58944fc3`, `4b123bac3` — Task 1.9–1.11 в `plans/lifecycle-stop-ownership/tasks/T1.9.md`, `T1.10.md`, `T1.11.md`.
- Ветка `docs/gui-graceful-close-plan` (worktree `.claude/worktrees/gui-close-plan`), `dd624fa62` — план
  `plans/2026-10-20_gui-graceful-close/` (9 задач, Ф1 после слияния 1.9). Не влита.
- Слияние обеих веток в `main` — по «да» владельца (координатор спрашивает). Строки ORDER.md / defects.md L-9 обновил
  координатор (`419b96d07` в main).
- Worktree `.claude/worktrees/l9-control` (detached `a5485097a` + откат 4 файлов фикса) — контроль стенда; удалить,
  когда не нужен (`git worktree remove`).

## Итог анализа (числа)

- L-9 на main нет: 2 робота 0/10 (0,875–1,047 с), контроль без фикса 4/10 (5,06–5,08 с); по всем сериям 14/25 до, 0/19 после.
- Граница фикса (в): R × T ≥ 4096 — обрыв (замер на pipe Windows, точность 2×); стенд R × T ≈ 20–80.
- «30 КБ соседей» — фон ~10 сообщ/с, накопленный за глухоту PM; хвост devices — 12 сообщ / 3,8 КБ.
- PM глух всё ожидание стопа (до 7 с): relay GUI, backend_ctl, `system.shutdown` (+1,0 → +5,1 с).
- Вердикт CTO для T4.x: условие выполнено с условием — стоп робота только аварийный внутри `process.stop`.

## Решения владельца 2026-10-20 (не пересматривать)

1. Конечное состояние — (б) «отдел»: приёмный поток не ждёт никогда; ждущие команды — в `KeyedExecutor`
   (`worker_module/keyed_executor.py`, общий примитив), PM — первый потребитель (Task 1.9).
2. Ключ извлекает CommandManager из сообщения по регистрации (`key_from`), развилка «сам / исполнителю» — в
   CommandManager (T1.9 D1a, сильнее D2). PM в 1.9 — последовательно; параллель по ключам — потом, по замеру.
3. Task 1.10 (`outcome` exited/terminated/killed/survived/handed_over), Task 1.11 (окно стопа на ребёнка) — да.
4. «Домой» робота — команда устройству ДО `process.stop` (полоса Р2, T5.3e; координатор передал).
5. План GUI-закрытия — да. Роли-потоки по видам почты отвергнуты замером CTO (GIL: p99 10 → 31 → 190 мс).

## Ждёт ответа владельца

- 8 вопросов плана GUI-закрытия (`plans/2026-10-20_gui-graceful-close/plan.md`, «Вопросы»); рекомендации лида —
  в чате 2026-10-20: 1 «Только отключиться», 2 черновик, 3 да для v1, 4 не молча — спросить, 5 да ~60 с,
  6 `%LOCALAPPDATA%\Inspector\recovery\`, 7 срок из окна стопа процесса, 8 да с предупреждением.

## Граница файлов полосы Ф (координатор inspector-bottles-fb, 2026-10-20, дословно по его записи)

- `multiprocess_framework/modules/process_manager_module/**`, `multiprocess_framework/modules/process_module/**`;
- `router_module` — ADR-RTR-014 и `pump_inbound`; в `router_module/core/router_manager.py` — только `_dispatch_command`
  (передача reply-колбэка);
- `command_module` — `register_command` и метаданные регистрации, `CommandManager.handle_command`;
- `multiprocess_framework/modules/worker_module/keyed_executor.py` (новый) с тестами.
- Развилку «сам / исполнителю» делает CommandManager по ключу из регистрации (`key_from`), отправители не меняются.
- Чужие, не трогать: `Services/device_hub/**`, `Plugins/hub/device_hub/**`, `Services/robot_comm/**`,
  `plans/robot-protocol-v2/**` (полоса Р2); `plans/queue/ORDER.md`, строки `defects.md` (координатор).
- Ловушка: camera-device-service Task 1.7 тоже правит `process_manager_module/launcher/spawner.py`; Р2 позже («SPI хаба»,
  OpSpec) заденет регистрацию команд — один писатель, при смене сигнатуры/умолчаний `register_command` предупредить
  координатора до слияния.

## Дальше (следующая сессия)

1. Стадия 0 — `reviewer` Opus, `MODE: plan`, на `T1.9.md`, синхронно; условия координатора: контракт по навыку
   `module-contract` (README/interfaces `worker_module`, ADR + `python -m scripts.sync`), R12 обратная совместимость.
   Стадия 0 сверяет D2 с решением D1a и решает деление 1.9a (исполнитель, роутер, регистрация) / 1.9b (PM, прототип):
   `T1.9.md` 39,7 КБ при бюджете 32, DESIGN 16,8 КБ.
2. Слепой тестер — worktree на коммите открытия задачи, окно у координатора заранее.
3. teamlead — реализация; инъекции — Haiku по прогнозам лида; ревью Opus; стенд S1–S5.

## Открыто

- Скрипт стенда `stand_t53r2.py` пишет `verdict: OK` у зависших — дефект инструмента (копия в scratchpad сессии 07).
- Почему `system.shutdown` даёт 0 зависаний без защиты — по чтению (самопометка ADR-SRM-016).
- `state.set` region_splitter (value 714 Б): поддерево или дельта — не установлено.
- Гипотеза плана GUI: GUI не видит стоп, начатый не из GUI (раннер ждёт события после `run()`) — проверит GUI 0.1.
- План `lifecycle-stop-ownership.md` ~83 КБ (бюджет 32) — деление Task 1.1–1.8 отдельной задачей.

## Агенты (все завершены; адрес — agentId)

| Роль | Модель | agentId | Токены | Итог |
|---|---|---|---|---|
| Explore, опись логов | Haiku | a70c1c96e049dfa4d | 136k | опись 1.8 |
| investigator, Q2/Q4/Q5 | Opus | ad9558c57e9e39574 | 253k | пробы P1–P3 |
| debugger, стенд + граница | Sonnet | afa3cab335c184b3d | 198k | 33 + 51 прогон |
| Explore, закрытие GUI | Haiku | a40ee087de43e4d83 | 55k | поведение крестика |
| cto, вердикт L-9 | Fable | a7c07cf59b8239161 | 182k | ACCEPT WITH CONDITIONS |
| cto, «отдел» | Fable | a005016caa8951b91 | 201k | ACCEPT WITH CONDITIONS |
| manager, Task 1.9–1.11 | Opus | a83adf180f1e072c8 | 259k | T1.9–T1.11 (спрос правок — ему) |
| manager, план GUI | Opus | a12187faf00c6bb7f | 276k | `2026-10-20_gui-graceful-close/` |

Контекст лида к концу ~170k (оценка) — поэтому передача, а не продолжение.
