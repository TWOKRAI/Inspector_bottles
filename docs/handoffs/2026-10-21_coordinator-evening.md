# Передача координатора — вечер 2026-10-21 → утро 2026-10-22

Уходит: inspector-bottles-7f. Сменяет утреннюю передачу `2026-10-21_coordinator.md` (она устарела).
Утром владелец открывает новые вкладки. Ниже четыре стартовых промпта: координатор, Ф, Р2, Д.

## Что сделано за день (в main)

| Что | Коммит | Польза |
|---|---|---|
| C-11 | `a178e0b64` | лог робота через общий логгер, сторож зелёный |
| C-13 | `a1cd6f49e` | `validate.py` 0 FAIL — общая проверка снова говорит правду |
| C-16 + C-17 | `09a925a4b` | склейка кадра с оверлеем вернулась (была потеряна 6 дней); `Port.join` — новые плагины склеиваются сами |
| C-22 | `1e9e64b10` | `collector` без `mode` при невыведенном join — ошибка `check()`, а не тихая потеря |
| C-18 | `3dc5d534b`, `3a731176e` | `modbus_demo` удалён (заброшен), `robot_demo` собирается и под сторожем |
| Task 1.9a | `6c4fc762e` | `KeyedExecutor`: долгие команды — исполнителю, приёмный поток не ждёт (база для L-9) |
| Task 1.9m | `751ba0dfd` | `ExecutorManager(BaseManager)` — «сотрудник» любого процесса: исполнители из конфига, `introspect.executors` |
| T5.3g | `53b1e1564` | робот не «готов» после стопа посреди connect, ровно один SOFT |
| T5.3h | `6652ef88a` | SOFT при «Отключить» посреди connect; стенд: ручной путь и путь тика |
| правило ревью | `65d526319` | Sonnet по умолчанию, Opus — ветка перед слиянием, стадия 0 Senior+, живые дефекты |
| правило слияния | `d66f32946` | перед слиянием validate + backend/tests + framework suite; красный вне реестра блокирует |

На main зелёные: `validate.py`, `multiprocess_prototype/backend/tests`, `Services/device_hub/tests`. Framework suite —
только нестабильные из реестра (C-4, C-5, C-20, C-26, C-27); известный красный — C-24.

## Полосы на утро

| Полоса | Следующее | Передача |
|---|---|---|
| Ф | Task 1.9b — PM первый потребитель `ExecutorManager`; затем 1.10 → 1.11 → 1.9c → ServiceHost → GUI-закрытие Ф1 | `docs/handoffs/2026-10-21_lane-F-T1.9m-to-T1.9b.md` |
| Р2 | C-29 «Отключить» прерывает ручное подключение до SERVO/DO → SPI хаба → T5.3e | `docs/handoffs/2026-10-21_task-T5.3h-merged.md` + отчёт `docs/reports/2026-10-21_robot-protocol-v2_T5.3h.md` |
| Д | C-24, C-25 + C-28 (тот же `blueprint.py`), C-21(б), затем C-19, C-20 | `docs/handoffs/2026-10-21_lane-D-C22.md` |

## Решения владельца за день (не пересматривать)

- Ревью: Sonnet по умолчанию; Opus — ревью ветки перед слиянием, стадия 0 Senior+, живые дефекты.
- Исполнитель — «сотрудник» на `BaseManager` внутри процесса (не отдельный процесс), для любого процесса; 1.9m.
- Рецепты — универсальная вещь: правила сборки — во framework, не в прототипе (C-22, C-25, C-28).
- C-16: «как правильно, без костылей» → `Port.join`; `metadata.inspector` — deprecated.
- C-21: вариант (б) — «последний активный рецепт» в локальном файле состояния вне git; до правки стенд — через `INSPECTOR_MANIFEST` на копию `app.yaml`.
- C-28: deprecated `metadata` без `mode` при невыведенном join — ошибка `check()`.
- `modbus_demo` удалить; `robot_demo` оставить (пусконаладка робота и ПЧ).
- T5.3h: SOFT и при обычном «Отключить» посреди connect; 2 SOFT при пересечении с остановкой процесса — допустимо (ADR-DH-011, H19).
- C-29: «Отключить» прерывает ручное подключение — после T5.3h, перед SPI хаба, до T4.0.

## Порядок работы координатора (сложился за день)

- Окно на машине одно (gate). Timed `device_hub` рядом с чужим framework suite не пускать. Heavy — от ~1.5 ГБ свободной памяти.
- Слияния строго по одному: полоса шлёт «сливаю X», координатор отвечает «ок»; после ОТЧЁТА — итог в ORDER/defects и «rebase» остальным.
- Координатор не коммитит в основную копию, пока там идёт чужое слияние.
- «Да» владельца — на конкретные ветки; новая ветка — новое «да».
- Решения, отданные владельцем во вкладке полосы, сразу в реестр/очередь: полосы уходят на /clear.
- Стенд: окно — для прогона, не для подготовки (урок `feedback_a_stand_window_is_for_running_not_preparing.md`); timeout на каждой команде;
  с рецептом — копия манифеста; гашение — `system_shutdown`, у `BackendDriver` сначала `connect()`.
- Оценку окна брать ×1,5 под нагрузкой (framework suite ~18–20 мин).
- Инъекции — поимённо против прогноза, не «каждая поймана хоть одним».

## Реестр — открытое (plans/queue/defects.md)

C-4, C-5, C-20, C-26, C-27 — нестабильные под нагрузкой; C-12 — хрупкий тайминг device_hub; C-14 — полный фикс к приёмке CTO;
C-19 — порядковая зависимость `phone_sketch`; C-21(б); C-24 — красный `test_letter_robot_sim_diff` (гипотеза `efc2612c3`);
C-25 — точка в имени процесса; C-28; C-29. Полоса Д берёт C-19…C-28 по своей передаче.

## Вопросов к владельцу нет

Не сделано: журнал дня `docs/sessions/2026-10-21.md` (эта передача его заменяет).

---

## Стартовые промпты на утро

### Координатор

```
ВКЛАДКА: Координатор
ROLE: координатор машины для параллельных сессий Inspector_bottles (навык coordinator). Окна нагрузки, очередь владельца
  (plans/queue/ORDER.md), реестр plans/queue/defects.md, связь между полосами. Сам полосы, тесты и стенд не ведёшь;
  в main не сливаешь — сливают полосы после «да» владельца.
READ FIRST: docs/handoffs/2026-10-21_coordinator-evening.md (целиком); D:\PROJECT_INNOTECH\Inspector_vision\machine.lock;
  навык coordinator (§3 классы, §4 сигналы, §5 шаблон промпта).
FIRST STEPS:
  1. ListAgents — своё имя. В machine.lock заменить только строку coordinator: на «coordinator: <имя> | since <дата время>».
  2. Полосы приходят сами с первым сообщением (имя сессии); записывать, отвечать границей файлов.
  3. Окна: bash scripts/machine_gate.sh grant|close <коорд> <сессия> heavy|quiet|stand <мин> <что>; очередь — строки waiting:.
  4. Отчёты полос — в ORDER.md / defects.md отдельными коммитами docs(queue) в main (git branch --show-current = main; явные пути;
     не во время чужого слияния).
RULES: ответы владельцу по-русски, коротко, числами; «Порядок работы координатора» из передачи — обязателен.
```

### Полоса Ф

```
ВКЛАДКА: Полоса Ф · Task 1.9b PM — первый потребитель ExecutorManager
ROLE: лид полосы Ф (фреймворк, L-9), план plans/lifecycle-stop-ownership.md, Task 1.9b
  (после 1.9a 6c4fc762e и 1.9m 751ba0dfd в main; статус — по git). Дальше 1.10 → 1.11 → 1.9c → ServiceHost, каждая своим циклом.
READ FIRST: docs/handoffs/2026-10-21_lane-F-T1.9m-to-T1.9b.md (целиком); бриф plans/lifecycle-stop-ownership/tasks/T1.9b.md
  (правка D1/D4 под ExecutorManager, затем стадия 0 р.2); карта docs/maps/keyed-executor-tools.md.
GOAL: PM исполняет команды жизненного цикла через ExecutorManager (ключ — имя процесса) и не глохнет на process.stop.
ACCEPTANCE: по брифу после стадии 0; живой стенд L-9 обязателен: 2 робота, до/после, числом (на 1.8 без фикса 4/10, с фиксом 0/10);
  на стенде — worker.stop по keyed-воркеру PM через backend_ctl получает отказ, PM жив.
PIPELINE: «Task launch convention»: стадия 0 Opus (Senior+), тестер вслепую в worktree, реализация, инъекции с прогнозом до прогона,
  ревью задачи Sonnet, ревью ветки Opus. Исполнители не коммитят в main и не пушат.
BOUNDARIES: свой worktree, ветка от main. Твоё — граница полосы Ф из handoff плюс multiprocess_prototype/orchestrator.py (регистрация recipe.activate).
  Чужие: Services/device_hub/**, Plugins/hub/device_hub/**, Services/robot_comm/** — Р2; process_manager_module/topology/blueprint.py,
  раздел ADR-PMM-017, рецепты, app_module (C-21) — Д; plans/queue/** — координатор. Смена сигнатуры/умолчаний register_command/handle_command — сначала координатору.
LOAD: координатор — имя в D:\PROJECT_INNOTECH\Inspector_vision\machine.lock; первое сообщение — своё имя сессии.
  Прогоны через machine_gate.sh; framework suite, матрица, стенд — в своём окне, оценку ×1,5; «ready for window» заранее.
  Стенд с рецептом — INSPECTOR_MANIFEST на копию app.yaml (C-21); каждая команда стенда с timeout; окно — для прогона, не подготовки.
COMMITS: Conventional Commits + Why:/Layer:/Refs:; перед слиянием rebase на main, validate + backend/tests + framework suite,
  красные поимённо против реестра. Слияние — после «да» владельца, «сливаю 1.9b», ждать «ок».
REPORT: docs/reports/<дата>_lifecycle-stop-ownership_T1.9b.md; координатору `ОТЧЁТ: Полоса Ф · Task 1.9b · <сессия> — <путь> · решение нужно: да|нет`.
LESSONS: handoff «Уроки» — в каждый бриф; suite ловит то, что ревью пропускает (1.9m: литерал introspect.* и getattr) — гонять до «сливаю».
```

### Полоса Р2

```
ВКЛАДКА: Полоса Р2 · C-29 «Отключить» прерывает подключение → SPI хаба → T5.3e
ROLE: лид полосы Р2 (робот v2, device_hub), план plans/robot-protocol-v2/plan.md.
READ FIRST: docs/handoffs/2026-10-21_task-T5.3h-merged.md (целиком); отчёт docs/reports/2026-10-21_robot-protocol-v2_T5.3h.md
  («Открыто», стенд); строка C-29 в plans/queue/defects.md; ADR-DH-009, ADR-DH-011 (Services/device_hub/DECISIONS.md).
GOAL: (1) C-29 — «Отключить» во время ручного connect прерывает его до sync_params/SERVO/DO; сейчас device_disconnect ждёт
  в очереди супервизора devices конца device_connect (на стенде 90–114 с при задержке симулятора 300 мс). Направление (владелец):
  connect проверяет desired_connected между шагами и до SERVO/DO, механизм прерывания — как у request_stop в T5.3g.
  (2) SPI хаба — 1.9m в main: register_command(executor=) по имени из конфига, CommandManager(executors=). (3) T5.3e — «домой» до process.stop.
ACCEPTANCE C-29: по брифу после стадии 0; стенд: «Отключить» посреди ручного connect → SERVO/DO не отправлены, ровно 1 SOFT, если связь поднята.
PIPELINE: стадия 0 Opus (гонки, жизненный цикл устройства), тестер вслепую, реализация, инъекции поимённо против прогноза,
  ревью задачи Sonnet, ревью ветки Opus, живой стенд. Исполнители не коммитят в main и не пушат.
BOUNDARIES: Services/device_hub/**, Plugins/hub/device_hub/**, Services/robot_comm/**, plans/robot-protocol-v2/**.
  Чужие: command_module/**, process_module/**, worker_module/**, process_manager_module/** — Ф; blueprint.py, рецепты, app_module — Д;
  plans/queue/** — координатор.
LOAD: координатор — имя в machine.lock; первое сообщение — своё имя сессии. device_hub — timed: только в своём окне.
  Стенд — сухой прогон скрипта до окна, timeout на каждой команде, INSPECTOR_MANIFEST на копию app.yaml, симулятор v2 — скриптом
  (SimRobotServer + RobotSimCoreV2), обрыв — команда симулятора drop.
COMMITS / REPORT: как прежде; перед слиянием rebase, полный device_hub, validate, backend/tests, framework suite; «сливаю X», ждать «ок»;
  `ОТЧЁТ: Полоса Р2 · <Task> · <сессия> — <путь> · решение нужно: да|нет`.
```

### Полоса Д

```
ВКЛАДКА: Полоса Д · C-24 → C-25 + C-28 → C-21(б) → C-19, C-20
ROLE: лид полосы Д (дефекты main), реестр plans/queue/defects.md.
READ FIRST: docs/handoffs/2026-10-21_lane-D-C22.md (целиком); строки C-19…C-28 в plans/queue/defects.md.
GOAL: C-24 — test_letter_robot_sim_diff зелёный с причиной (сим разошёлся намеренно → тест с причиной; дрейф → вернуть; гипотеза efc2612c3);
  C-25 и C-28 — одной правкой blueprint.py / ADR-PMM-017 (точка в имени процесса; deprecated metadata без mode — ошибка check(), «да» владельца);
  C-21(б) — «последний активный рецепт» в локальном файле состояния вне git, app.yaml — умолчание (framework app_module + прототип;
  проверить сценарий «headless-бэкенд + отдельно запущенный GUI»).
PIPELINE: по handoff. C-21(б) — новый механизм framework: стадия 0 Opus, тестер вслепую. C-25/C-28 — стадия 0 Sonnet по образцу C-22.
  Ревью ветки перед слиянием — Opus (framework). Рецепты универсальны — правила во framework, не в прототипе.
BOUNDARIES: blueprint.py, раздел ADR-PMM-017, process_module/tests/test_blueprint_wire_collector.py, рецепты прототипа и их тесты,
  app_module (C-21) — назвать координатору до правки. Чужие: Ф — command/process/worker/process_manager (кроме blueprint.py); Р2 — device_hub, robot_comm.
LOAD: координатор — имя в machine.lock; первое сообщение — своё имя сессии. Прогоны через machine_gate.sh; heavy, timed, stand — в своём окне.
  Стенд с рецептом — INSPECTOR_MANIFEST на копию app.yaml.
COMMITS / REPORT: как в handoff; слияние — «сливаю X», ждать «ок»; в конце — ОТЧЁТ одной строкой.
```
