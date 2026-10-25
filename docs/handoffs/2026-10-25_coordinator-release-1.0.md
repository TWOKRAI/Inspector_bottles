# Передача координатора — 2026-10-25: очередь под прототип 1.0

Уходит: inspector-bottles-bc (после `/clear` — та же вкладка). Сменяет `2026-10-21_coordinator-evening.md` (её «Порядок работы
координатора» остаётся в силе). Ниже пять стартовых промптов: координатор, Ф, Р2, Д, план `release-1.0`.

## Что решено 2026-10-25 (не пересматривать)

- **Цель — прототип 1.0** (решения 23, 24 в `plans/queue/decisions.md`). Очередь владельца в `plans/queue/ORDER.md`:
  строки 1–27 — 1.0, ниже — 2.0. Коммиты `327ac06c2`, затем `docs(queue): сценарий 1.0 …`.
- **Сценарий 1.0:** вводят слово → по одному кидают диски с буквами → подходящая буква: камера считывает угол, слежение по ленте,
  робот берёт, поворачивает, кладёт в ячейку слова; неподходящая едет дальше. Брака нет.
  Веха **α** (сим): журнал поимённо показывает букву, угол, ячейку и задание `CVT_JOB`; пропуск неподходящих.
  Веха **β** (железо): то же на MVS и настоящем роботе, робот берёт и кладёт.
- **Камеры в 1.0:** одна MVS, сразу на ядре `camera_device` (механизмы на будущее: выбор по serial, контракты команд).
  **ID3013 в 1.0 не участвует** — `qr-code-reader` и W5 камер в 2.0.
- **Экран оператора 1.0:** Qt-GUI прототипа + вкладка «Пульт» (`Services/control_panel`) вместо робота Ф6 (T6.x → 2.0).
- **В 2.0:** GUI- и фронтенд-конструктор, `gui-service`, робот Ф6, горячая смена рецепта, `framework-architecture-rework`, В3–В6.

## Цепочка 1.0 и разрывы

Рецепт `letter_robot_sim` (сим) / `hikvision_letter_robot` (MVS): камера → `vision` → `recog` (буква + угол, `pixel_to_robot`)
→ `layout.word_layout` → `robot_io` → `devices` → робот v2. Разрывы: T5.5 (`robot_io` → `CVT_JOB` на v2); `word-layout` P3 +
`robot-place-pose` P3 (задание = съём + укладка + доворот: `angle_deg` не доходит до `robot_io`, тот ждёт `place_*_mm`, `place_rz_deg`);
прошивка T4.1 (ось `R`/`RZ`) после T0.3.

## Полосы

| Полоса | Путь | Промпт |
|---|---|---|
| Ф | 1.9b → 1.10 → 1.11 → gui-graceful-close 0.1, 1.1–1.4 → пульт (smoke, `monitor`, пульт оператора) | ниже |
| Р2 | C-29 → SPI хаба → T5.3e → T1.4 → T5.5 → word-layout P3 + place-pose P3 → P4 (веха α) → T5.4 → T4.0 → T4.x | ниже |
| Д → К | C-24 → C-25 + C-28 → C-21(б) → камеры MVS: влить 6.2 → W1b → W2 → W3 → W4 | ниже (Д); промпт К — когда Д закроет C-21(б) |
| план 1.0 | `plans/release-1.0/plan.md` — только документы, параллельно полосам | ниже |
| владелец | день с железом №1: T0.3 + камеры 0.5 + запись реальных кадров дисков; день №2: F7 → веха β | — |

## Открыто

- Умеет ли line-sim подавать диски с заданными буквами по порядку — первый вопрос плана `release-1.0`.
- Камеры 4.2a стоит после 3.2 (ID3013) — решает лид К на стадии 0, с числами.
- Строки очереди 3, 4, 15–17 скрипт не видит (`--queue`: `known: false` / план пульта закрыт) — задачи заводят лиды.
- Q-1, Q-2, Q-4 сверки 2026-10-25 (`plans/queue/defects.md`) не тронуты; Q-2 — решение владельца.
- В основной копии висит незакоммиченный `multiprocess_prototype/app.yaml` (симптом C-21) — не стейджить.

---

## Стартовые промпты

### Координатор (после `/clear` в этой же вкладке)

```
ВКЛАДКА: Координатор
ROLE: координатор машины для параллельных сессий Inspector_bottles (навык coordinator). Окна нагрузки, очередь владельца
  (plans/queue/ORDER.md), реестр plans/queue/defects.md, связь между полосами. Сам полосы, тесты и стенд не ведёшь;
  в main не сливаешь — сливают полосы после «да» владельца.
READ FIRST: docs/handoffs/2026-10-25_coordinator-release-1.0.md (целиком); «Порядок работы координатора» из
  docs/handoffs/2026-10-21_coordinator-evening.md; D:\PROJECT_INNOTECH\Inspector_vision\machine.lock; навык coordinator §3–§5.
FIRST STEPS:
  1. ListAgents — своё имя. В machine.lock заменить только строку coordinator: на «coordinator: <имя> | since <дата время>».
  2. Полосы приходят сами с первым сообщением (имя сессии); записать таблицу полоса ↔ вкладка ↔ имя, ответить границей файлов.
  3. Окна: bash scripts/machine_gate.sh grant|close <коорд> <сессия> heavy|quiet|stand <мин> <что>; очередь — строки waiting:.
  4. Отчёты полос — в ORDER.md / defects.md отдельными коммитами docs(queue) в main (git branch --show-current = main;
     явные пути; не во время чужого слияния; app.yaml не стейджить).
RULES: ответы владельцу по-русски, коротко, числами; одно окно на машине; слияния строго по одному («сливаю X» → «ок»).
```

### Полоса Ф

```
ВКЛАДКА: Полоса Ф · Task 1.9b PM — первый потребитель ExecutorManager
ROLE: лид полосы Ф (фреймворк, L-9), план plans/lifecycle-stop-ownership.md, Task 1.9b (после 1.9a 6c4fc762e и 1.9m 751ba0dfd
  в main; статус — по git, не по шапке: у плана два счётчика, Q-1). Дальше по очереди владельца: 1.10 → 1.11 → gui-graceful-close
  0.1, 1.1–1.4 → пульт (строки 15–17 ORDER), каждая своим циклом.
READ FIRST: docs/handoffs/2026-10-21_lane-F-T1.9m-to-T1.9b.md (целиком); бриф plans/lifecycle-stop-ownership/tasks/T1.9b.md
  (правка D1/D4 под ExecutorManager, затем стадия 0 р.2); карта docs/maps/keyed-executor-tools.md;
  цель 1.0 — docs/handoffs/2026-10-25_coordinator-release-1.0.md.
GOAL: PM исполняет команды жизненного цикла через ExecutorManager (ключ — имя процесса) и не глохнет на process.stop.
ACCEPTANCE: по брифу после стадии 0; живой стенд L-9 обязателен: 2 робота, до/после, числом (на 1.8 без фикса 4/10, с фиксом 0/10);
  на стенде — worker.stop по keyed-воркеру PM через backend_ctl получает отказ, PM жив.
PIPELINE: «Task launch convention» (.claude/CLAUDE.md): стадия 0 Opus (Senior+), тестер вслепую в worktree на коммите до реализации,
  реализация, инъекции с прогнозом до прогона, ревью задачи Sonnet, ревью ветки Opus. Исполнители не коммитят в main и не пушат.
BOUNDARIES: свой worktree, ветка от main. Твоё — command_module, process_module, worker_module, process_manager_module (кроме
  topology/blueprint.py), multiprocess_prototype/orchestrator.py (регистрация recipe.activate); позже — frontend (закрытие по крестику),
  Services/control_panel. Чужие: Services/device_hub/**, Plugins/hub/device_hub/**, Services/robot_comm/**, Plugins/io/robot_io/**,
  Plugins/processing/word_layout/** — Р2; blueprint.py, раздел ADR-PMM-017, рецепты, app_module (C-21) — Д; plans/queue/** — координатор.
  Смена сигнатуры/умолчаний register_command/handle_command — сначала координатору.
LOAD: координатор — имя в D:\PROJECT_INNOTECH\Inspector_vision\machine.lock; первое сообщение — своё имя сессии (первая строка своего
  ListAgents). Первая строка каждого ответа владельцу: «Полоса Ф · Task 1.9b · <имя сессии>». Прогоны через
  bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"; framework suite, матрица, стенд — в своём окне,
  оценку ×1,5; «ready for window: …» заранее. Имя сессии — в каждый бриф агента.
COMMITS: Conventional Commits + Why:/Layer:/Refs: (.claude/COMMIT_GUIDE.md); явные пути; открытие/закрытие плана — отдельный docs(plans).
  Перед слиянием: rebase на main, validate.py + multiprocess_prototype/backend/tests + framework suite (heavy, своё окно); каждый красный
  поимённо против plans/queue/defects.md. Слияние — после «да» владельца, «сливаю 1.9b», ждать «ок».
LIMITS: 2 итерации на цикл, на 3-й — на уровень выше; решения владельца — списком, не угадывать.
REPORT: по-русски, числами; непустое «что оставил открытым»; таблица agentId. Файл docs/reports/<дата>_lifecycle-stop-ownership_T1.9b.md
  (шаблон coordinator §5), координатору одной строкой: «ОТЧЁТ: Полоса Ф · Task 1.9b · <сессия> — <путь> · решение нужно: да|нет».
  В конце задачи — handoff и /clear, не /compact.
LESSONS: «Уроки» handoff — в каждый бриф; suite ловит то, что ревью пропускает (1.9m: литерал introspect.* и getattr) — гонять до
  «сливаю»; стенд с рецептом — INSPECTOR_MANIFEST на копию app.yaml (C-21), timeout на каждой команде, окно — для прогона, не подготовки;
  гашение — system_shutdown, у BackendDriver сначала connect().
```

### Полоса Р2

```
ВКЛАДКА: Полоса Р2 · C-29 «Отключить» прерывает подключение → SPI хаба → T5.3e
ROLE: лид полосы Р2 (робот v2, device_hub), план plans/robot-protocol-v2/plan.md. Дальше по очереди владельца: T1.4 → T5.5 →
  word-layout P3 + robot-place-pose P3 одной задачей → word-layout P4 (веха α) → T5.4 → (железо) T4.0 → T4.6, T4.1 → T4.5.
READ FIRST: docs/handoffs/2026-10-21_task-T5.3h-merged.md (целиком); отчёт docs/reports/2026-10-21_robot-protocol-v2_T5.3h.md («Открыто»);
  строка C-29 в plans/queue/defects.md; ADR-DH-009, ADR-DH-011 (Services/device_hub/DECISIONS.md);
  цель 1.0 и цепочка — docs/handoffs/2026-10-25_coordinator-release-1.0.md.
GOAL: (1) C-29 — «Отключить» во время ручного connect прерывает его до sync_params/SERVO/DO; сейчас device_disconnect ждёт в очереди
  супервизора devices конца device_connect (стенд: 90–114 с при задержке симулятора 300 мс). Направление (владелец): connect проверяет
  desired_connected между шагами и до SERVO/DO, механизм прерывания — как у request_stop в T5.3g.
  (2) SPI хаба — register_command(executor=) по имени из конфига, CommandManager(executors=) (1.9m в main).
  (3) T5.3e — «домой» командой устройству до process.stop (условие D1 L-9).
ACCEPTANCE C-29: по брифу после стадии 0; стенд: «Отключить» посреди ручного connect → SERVO/DO не отправлены, ровно 1 SOFT, если связь поднята.
PIPELINE: «Task launch convention»: стадия 0 Opus (гонки, жизненный цикл устройства), тестер вслепую, реализация, инъекции поимённо
  против прогноза, ревью задачи Sonnet, ревью ветки Opus, живой стенд. Исполнители не коммитят в main и не пушат.
BOUNDARIES: свой worktree. Твоё — Services/device_hub/**, Plugins/hub/device_hub/**, Services/robot_comm/**, plans/robot-protocol-v2/**;
  с T5.5 — Plugins/io/robot_io/**, Plugins/processing/word_layout/**, plans/word-layout.md, plans/robot-place-pose.md.
  Чужие: command_module/**, process_module/**, worker_module/**, process_manager_module/** — Ф; blueprint.py, рецепты, app_module — Д
  (правка рецепта letter_robot_sim под P3 — назвать координатору до правки); plans/queue/** — координатор.
LOAD: координатор — имя в machine.lock; первое сообщение — своё имя сессии. Первая строка ответа владельцу:
  «Полоса Р2 · <Task> · <имя сессии>». device_hub — timed: только в своём окне. Стенд — сухой прогон скрипта до окна, timeout на каждой
  команде, INSPECTOR_MANIFEST на копию app.yaml, симулятор v2 — скриптом (SimRobotServer + RobotSimCoreV2), обрыв — команда симулятора drop.
COMMITS: как у Ф: трейлеры, явные пути; перед слиянием rebase, полный device_hub, validate, backend/tests, framework suite в своём окне,
  красные против реестра; «сливаю X», ждать «ок».
LIMITS: 2 итерации, на 3-й — выше; T4.x (настоящий робот) — только после T0.3 владельца и T1.4.
REPORT: файл docs/reports/<дата>_robot-protocol-v2_<task>.md; координатору: «ОТЧЁТ: Полоса Р2 · <Task> · <сессия> — <путь> · решение нужно: да|нет».
  В конце задачи — handoff и /clear.
LESSONS: окно стенда — для прогона, не подготовки; инъекции судить поимённо, не «каждая поймана хоть одним»; 2 SOFT при пересечении
  с остановкой процесса допустимы (ADR-DH-011, H19).
```

### Полоса Д

```
ВКЛАДКА: Полоса Д · C-24 → C-25 + C-28 → C-21(б)
ROLE: лид полосы Д (дефекты main), реестр plans/queue/defects.md. После C-21(б) полоса становится К (камеры MVS на ядре) —
  промпт К выдаст координатор.
READ FIRST: docs/handoffs/2026-10-21_lane-D-C22.md (целиком); строки C-19…C-28 в plans/queue/defects.md;
  цель 1.0 — docs/handoffs/2026-10-25_coordinator-release-1.0.md (letter_robot_sim — рецепт сценария 1.0).
GOAL: C-24 — test_letter_robot_sim_diff зелёный с причиной (сим разошёлся намеренно → тест с причиной; дрейф → вернуть; гипотеза efc2612c3);
  C-25 и C-28 — одной правкой blueprint.py / ADR-PMM-017 (точка в имени процесса; deprecated metadata без mode — ошибка check(), «да» владельца);
  C-21(б) — «последний активный рецепт» в локальном файле состояния вне git, app.yaml — умолчание (framework app_module + прототип;
  проверить сценарий «headless-бэкенд + отдельно запущенный GUI»).
ACCEPTANCE: C-24 — тест зелёный, причина записана в реестре; C-25/C-28 — check() даёт ошибку на обоих путях, тесты по образцу C-22;
  C-21(б) — после «Загрузить» рабочее дерево git чистое, перезапуск поднимает последний рецепт.
PIPELINE: по handoff. C-21(б) — новый механизм framework: стадия 0 Opus, тестер вслепую. C-25/C-28 — стадия 0 Sonnet по образцу C-22.
  Ревью ветки перед слиянием — Opus (framework). Рецепты универсальны — правила во framework, не в прототипе.
BOUNDARIES: blueprint.py, раздел ADR-PMM-017, process_module/tests/test_blueprint_wire_collector.py, рецепты прототипа и их тесты,
  app_module (C-21) — назвать координатору до правки. Чужие: Ф — command/process/worker/process_manager (кроме blueprint.py);
  Р2 — device_hub, robot_comm, robot_io, word_layout; plans/queue/** — координатор (строки реестра — через координатора).
LOAD: координатор — имя в machine.lock; первое сообщение — своё имя сессии. Первая строка ответа владельцу: «Полоса Д · <C-NN> · <имя сессии>».
  Прогоны через machine_gate.sh (абсолютный путь); heavy, timed, stand — в своём окне. Стенд с рецептом — INSPECTOR_MANIFEST на копию app.yaml.
COMMITS: трейлеры, явные пути; перед слиянием rebase, validate + backend/tests + framework suite, красные против реестра; «сливаю X», ждать «ок».
LIMITS: 2 итерации, на 3-й — выше.
REPORT: файл docs/reports/<дата>_defects_<C-NN>.md на каждый дефект; координатору одной строкой «ОТЧЁТ: …»; в конце — handoff и /clear.
LESSONS: BackendDriver — сначала connect(); стенд C-16 на letter_robot_sim — урок в docs/handoffs/2026-10-21_lane-D-C22.md.
```

### План release-1.0 (отдельная вкладка, только документы)

```
ВКЛАДКА: План 1.0 · release-1.0 — приёмка прототипа
ROLE: лид плана release-1.0; пишешь план и приёмку, кода не пишешь. Исполнитель плана — manager (/dev:plan), ревью плана — reviewer
  model: "sonnet" (MODE: plan), синхронно.
READ FIRST: docs/handoffs/2026-10-25_coordinator-release-1.0.md (сценарий, вехи α/β, цепочка, разрывы); решения 23, 24 в
  plans/queue/decisions.md; строки 1–27 plans/queue/ORDER.md; рецепты multiprocess_prototype/recipes/letter_robot_sim.yaml и
  hikvision_letter_robot.yaml; plans/word-layout.md, plans/robot-place-pose.md, plans/robot-protocol-v2/tasks-2.md (T5.4, T5.5),
  plans/line-sim/plan.md.
GOAL: plans/release-1.0/plan.md — проверяемое определение «1.0 готово»: сценарий владельца (слово → диски по одному → подходящая буква:
  угол, слежение, робот берёт, поворачивает, кладёт в ячейку; неподходящая едет дальше) как приёмка вех α (сим, журнал) и β (железо).
ACCEPTANCE: (1) веха α — скрипт через backend_ctl: холодный старт рецепта → ввод слова → последовательность дисков (литералом, например
  слово «МИР», диски «А М Б И Р») → ожидаемые записи журнала поимённо (буква, угол, ячейка, CVT_JOB) и пропуски — литералами;
  чистый стоп, «домой». (2) веха β — чек-лист железа (MVS, робот, лента, калибровка F7). (3) Ответ, умеет ли line-sim подавать диски
  с заданными буквами по порядку; если нет — задача в план. (4) Сверка robot-calibration F4/F5 со сценарием: поглощена или нужна.
  (5) Каждая задача плана ссылается на строку очереди или на Task другого плана; новых механизмов план не вводит.
PIPELINE: /dev:plan → manager; ревью плана Sonnet; план открывается отдельным коммитом docs(plans) в ветке docs/release-1.0-plan.
BOUNDARIES: пишешь только plans/release-1.0/**. Код, рецепты, чужие планы — только читаешь; находки чужим планам — координатору.
LOAD: координатор — имя в machine.lock; первое сообщение — своё имя сессии. Тестов и стенда не запускаешь (нужен прогон — через координатора).
COMMITS: docs(plans) + Why:/Layer: docs/Refs:; слияние в main — после «да» владельца, «сливаю release-1.0 plan», ждать «ок».
LIMITS: 2 раунда ревью плана, на 3-й — выше; вопросы владельцу — списком (не больше 2–3).
REPORT: файл docs/reports/<дата>_release-1.0_plan.md; координатору одной строкой «ОТЧЁТ: План 1.0 · plan · <сессия> — <путь> · решение нужно: да|нет».
LESSONS: посылка плана — гипотеза: проверять по коду, не по шапкам планов (шапки врали минимум в пяти планах).
```
