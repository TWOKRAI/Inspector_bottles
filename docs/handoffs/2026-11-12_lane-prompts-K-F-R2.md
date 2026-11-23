# Стартовые промпты полос К, Ф (run-state) и Р2 (координатор inspector-bottles-2e, 2026-11-12)

Состояние сверено по `main` (`db74bde58`) и по веткам, а не по `ORDER.md`: он отстаёт. Вставлять в новый чат целиком; первая строка — вкладка.
Цель: до железа (≈ 2026-11-22) сделать всё, что не требует робота и MVS. Не больше трёх писателей одновременно — это три полосы ниже.

## Что в git на самом деле (расхождения с ORDER.md и с прежним ответом координатора)
- run-state Task 1.1 (строка 14а) — код **уже написан** на `feat/run-state-1.1` (`a8a8d19d4`, слепой набор 232 passed), не влит; стадии 3–5 не сделаны.
- T5.3e.6 (строка 7) — **готова на ветке** `feat/robot-v2-t53e6` (`3c8223980`): инъекции 14 из 14, правки ревью р.1 закоммичены; не влита, `validate.py` на ветке не гонялся.
- Камеры: W2 (1.6, 1.8, 2.1, 2.2) не начата, коммитов нет.
- Пульт 15–17: коммитов нет.

## Полоса Ф — run-state Task 1.1: добить стадии 3–5 и влить

```
ВКЛАДКА: Полоса Ф · run-state 1.1 (стадии 3–5, слияние), затем 1.2
ROLE: lead of lane Ф, plan plans/2026-10-27_system-run-state/plan.md, Task 1.1 (код на ветке feat/run-state-1.1; статус из git, не из шапок).
READ FIRST: docs/handoffs/2026-11-09_operator-run-state-1.1-paused.md (целиком — там что не сделано и открытое 1–10);
  plans/2026-10-27_system-run-state/tasks/1.1.md, design.md §3.2, reports/1.1.tester.md, reports/1.1.teamlead.md.
GOAL: Task 1.1 в main: `run_gate: true` → после boot кадров нет; `system.run.start` — идут; `system.run.stop` — стоят; `system.run.status` показывает ready/running.
ACCEPTANCE: блок ACCEPTANCE в tasks/1.1.md; 232 прогона слепого набора + test_t54_* зелёные после rebase на main; стенд (стадия 4) — числа cycles как в handoff «Не сделано».
PIPELINE: стадии 0–2 пройдены, tester второй раз НЕ запускать. Остаётся: (1) закрыть инъекцию публикации (снимок state до замка публикации — тест остался зелёным): дополнение лид пишет сам, слепой tester не правит;
  (2) стадия 3: предсказания лида отдельным коммитом ДО прогона, матрицу гонит haiku (BRIEF-OVERRIDE), откат инъекции — cp, не git checkout; (3) стадия 4: стенд на macOS (`--headless`, backend_ctl; источник, робот не нужен);
  (4) стадия 5: reviewer sonnet, run_in_background: false; (5) rebase на main, validate.py, слияние `git merge --no-ff -F файл` в detached worktree, тема feat(...). Учитель teamlead `ad6334d07840ecdf4` (~0,21M) — для правок по ревью, если жив; иначе свежий teamlead по handoff.
  Затем Task 1.2: сначала сверка устаревших посылок плана с кодом (handoff, пункт 3: pre_stop.py уже в main, 2.1 FILES гадает app.yaml и т.д.), потом стадия 0.
BOUNDARIES: framework (process_manager_module, process_module) по FILES задачи. Не трогать plans/queue/ORDER.md (его правит сессия Атласа). Основной чекаут может стоять на чужой ветке: работа в worktree, перед коммитом git branch --show-current.
LOAD: координатор — inspector-bottles-2e; первое сообщение ему — своё имя сессии (первая строка твоего ListAgents). Машина — Mac, machine.lock нет: тесты через machine_gate.sh (абсолютный путь основного чекаута).
  На этой macOS полный прогон process_manager_module/tests + process_module/tests кончает POSIX-семафоры (OSError 28): гонять по файлам; вердиктом не считать.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-27_system-run-state/plan.md; stage явных путей; слияние отдельным коммитом, тема feat(...).
LIMITS: 2 итерации на петлю, на третьей вверх; не больше трёх писателей по всем полосам; субагенты — диагностика и файлы, коммитит лид.
REPORT: по-русски, числа, непустое «что осталось открытым», таблица agentId; файл docs/reports/<дата>_system-run-state_1.1.md; в конце handoff и /clear.
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: В10 — индикатор «нет диска» (блокирует только п.6 Task 2.2; рекомендация лида — (а)).
ДОБАВЛЕНИЕ ВЛАДЕЛЬЦА 2026-11-12 (Task 1.1 НЕ расширять — она написана и ждёт слияния; это отдельные задачи плана):
  ТРЕБОВАНИЕ: (1) при старте прототипа — окно начальной загрузки со шкалой 0–100 %; (2) шкала загрузки рецепта; (3) легко модернизировать и подвязать: любой узел
  может сообщить прогресс, и он виден. Только прототип показывает окно; бэкенд headless (принцип 6), проценты видны и без GUI через backend_ctl `state_get`.
  ЧТО УЖЕ ЕСТЬ (проверено git grep 2026-11-12): `frontend_module/windows/loading_window.py` — `LoadingWindow` (QProgressBar, слот `update_progress(percent)`), LEGACY Gen-1 FROZEN, 0 потребителей
  (принцип 3 владельца: заморожено ≠ удалено — разморозить и обобщить, не писать второе окно); в PM — старт волнами `_plan_boot_waves` (depends_on, топосорт) и барьер `_wait_processes_ready`
  (process_manager_process.py, ADR-PMM-034) — готовый источник «сколько процессов поднято из скольких».
  ЧЕРНОВОЙ ДИЗАЙН (лид решает на стадии 0, не принимать как решённый): контракт — листы state `system.progress.<id>` = `{percent: int 0..100, label: str, stage: str, done: bool}`,
  `id` ∈ `boot`, `recipe_load`, … открытый набор; помощник `ProgressReporter(id, steps=[(имя, вес), …])` — шаги с весами, процент монотонный (не мигает назад); модернизация = добавить шаг или новый `id`,
  без правки окна. Издатели: PM — `boot` (волны + барьер готовности, позже агрегат Task 1.3) и `recipe_load` (чтение → валидация → применение топологии → подъём → готовность); любой плагин — через помощник.
  Окно — тонкий подписчик глоб-подписки `system.progress.**` (слой prototype: `frontend/windows/loading/`, конфиг уже предусмотрен ADR frontend_module, DECISIONS.md:880), закрывается на `ready`.
  ВОПРОСЫ СТАДИИ 0: где в коде читается/применяется рецепт (шаги и их веса); кто стартует раньше — GUI-процесс или PM-стор (до первой дельты показывать 0 % / «подключение»); не добавить ли лишний слой
  (принцип 4: меньше слоёв) — например, `ProgressReporter` как тонкая функция записи в стор, без класса; где контракт живёт (framework — `state_store_module`/`process_manager_module`, прототип — только окно).
  КУДА В ПЛАН: контракт и издатель `boot` — рядом с Task 1.3 (агрегат готовности даёт честные данные), `recipe_load` и окно — новая задача Ф2 (предложение: Task 2.6, после 1.3, рядом с 2.3 GUI);
  оформить амендментом `amendments.md` + стадия 0 reviewer sonnet; одна строка в `plans/queue/inbox/` (registry: ORDER.md) уже положена координатором. Слияние 1.1 это не задерживает.
```

## Полоса Р2 — T5.3e.6: закрыть и влить, затем пульт (план, smoke)

```
ВКЛАДКА: Полоса Р2 · T5.3e.6 слияние, затем пульт 15–17
ROLE: lead of lane Р2, plans/robot-protocol-v2/plan.md Task T5.3e.6 и plans/pult-control-panel.md (статус из git main).
READ FIRST: docs/reports/2026-11-11_robot-protocol-v2_T5.3e.6.md (на ветке feat/robot-v2-t53e6, worktree .claude/worktrees/robot-v2-t53e6, `git show feat/robot-v2-t53e6:<путь>`);
  plans/robot-protocol-v2/tasks/T5.3e.6.md и .injections-result.md; plans/pult-control-panel.md; design.md release-1.0 §3 β8.
GOAL: (1) T5.3e.6 в main. Ветка `3c8223980`: код, инъекции 14 из 14, правки ревью р.1 закоммичены. Проверить по ветке, было ли ревью р.2 (в тексте итога р.2 нет); если нет — р.2 тому же reviewer `a1bd98325108f3055` (если жив) или свежему sonnet. Затем rebase на main, validate.py, тесты вкладки (`robot/tests` + test_staleness_indicator), слияние `--no-ff -F файл`, тема feat(...).
  (2) Пульт: шаг 1 — smoke пульта на текущем main (`pult_demo`, `action` к `device_hub`; Haiku; qt-mcp в сессии координатора не подключился — проверить у себя, иначе smoke через backend_ctl и тесты вкладки). Шаги 2–3 (monitor; поле «Слово»→`word_layout.target_word`, старт/стоп ленты, «Домой», статус) — план числится закрытым: сначала `/dev:plan` новой фазой, на approve — владельцу, код не писать.
ACCEPTANCE: (1) числа: слепой файл 15/15, robot/tests + test_staleness_indicator зелёные, validate.py rc 0, `git diff --quiet main -- Plugins Services multiprocess_framework multiprocess_prototype/frontend/state` rc 0; (2) результат smoke и новая фаза плана с задачами (Task X.Y, ACCEPTANCE).
PIPELINE: как в .claude/CLAUDE.md «Task launch convention»; для T5.3e.6 стадии 0–3 пройдены, tester второй раз не нужен. Субагенты — диагностика и файлы; коммитит лид (protect-branch).
BOUNDARIES: файлы вкладки робота (`multiprocess_prototype/frontend/widgets/tabs/services/robot/`), для пульта — только план и smoke. Не трогать: Services/device_hub/*, plans/queue/ORDER.md, calibration/controller.py:117 и vfd/controller.py:126 (дефект подписки — отдельная задача, вопрос В3). Основной чекаут может стоять на чужой ветке: работа в worktree, перед коммитом git branch --show-current.
LOAD: координатор — inspector-bottles-2e; первое сообщение ему — своё имя сессии. Mac, machine.lock нет: тесты через machine_gate.sh.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md (для пульта — plans/pult-control-panel.md); stage явных путей; слияние отдельным коммитом.
LIMITS: 2 итерации на петлю, на третьей вверх; не больше трёх писателей по всем полосам.
REPORT: по-русски, числа, «что осталось открытым»; файл docs/reports/<дата>_robot-protocol-v2_T5.3e.6.md; в конце handoff и /clear.
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА (список, не решать): (а) шаг pre_stop Оператора `{"process":"devices","command":"robot_park_all","args":{},"timeout_s":35}` — уже в main через 1.4m, нужно подтвердить; (б) принять потерю второго рисунка на v2; (в) robot_draw_abort на v2 нет; (г) запись контракта наблюдаемости `status` в OPEN_QUESTIONS.
```

## Полоса К — W2 «ядро» камер

```
ВКЛАДКА: Полоса К · W2 ядро камер 1.6 ∥ 1.8, затем 2.1, 2.2
ROLE: lead of lane К, plan plans/2026-10-18_camera-device-service/plan.md, волна W2: Task 1.6, 1.8, 2.1, 2.2 (W1a/W1b влиты; статус из git main).
READ FIRST: plan.md «Режим исполнения — волны» и «W2»; wave-protocol.md; docs/handoffs/2026-11-01_К-W1b-merged.md;
  docs/reports/2026-11-01_camera-device-service_W1b.md; tasks/1.6.md, 1.8.md, 2.1.md, 2.2.md.
GOAL: ядро Services/camera_device: план записи (1.6), вертикальный срез `driver: fake` → item → дисплей → backend_ctl (1.8), поток-владелец (2.1), run/rest с проверкой чтением (2.2). Всё без железа (MVS вернётся ≈ 2026-11-22: 0.5 М1 уже сделана, 6.3 ждёт).
ACCEPTANCE: по tasks/*.md; шапки [PENDING] в plan.md обновлять только по git.
PIPELINE: режим волн плана (решение владельца 2026-10-18): Sonnet код и тесты; стадия 0 reviewer sonnet у 2.1 и 2.2 (у 1.6, 1.8 нет); слепой tester до кода у 2.1 и 2.2; break-injection только по механизмам 2.1 (поток-владелец) и 2.2 (проверка чтением, run/rest);
  Opus reviewer сразу после 2.1 и 2.2 и один на волну по общему diff. Порядок: 1.6 ∥ 1.8 (два писателя), затем 2.1 (после 1.5, 1.8), затем 2.2 (после 1.6, 2.1). Граница волны — handoff + /clear. После W2 — сверка токенов с оценкой (порог плана 14M; W1b ≈ 1,52M).
  Субагенты только диагностика и файлы; коммитит лид. ВНИМАНИЕ: «два писателя» внутри полосы К + Ф + Р2 = четыре — держи в К одного писателя, пока Ф и Р2 пишут (1.6, затем 1.8).
BOUNDARIES: Services/camera_device, Plugins камер (только по задачам). Задачи 1.3/1.4/1.7 — не W2; 1.7 строить поверх влитого 1.11 (spawner.py stop(), полоса Ф). ORDER.md правит сессия Атласа. Основной чекаут может стоять на чужой ветке: работа в worktree, перед коммитом git branch --show-current. Ветка feat/camera-device-service удалена: начинать новую от main.
LOAD: координатор — inspector-bottles-2e; первое сообщение — своё имя сессии. Жёстко: не больше трёх писателей по всем полосам; `--timed medium` — своё окно.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-18_camera-device-service/plan.md; stage явных путей; слияние отдельным коммитом, тема feat(...).
LIMITS: 2 итерации на петлю, на третьей вверх (cto только вердикт с SHA); вопросы владельцу — списком.
REPORT: файл docs/reports/<дата>_camera-device-service_W2.md по шаблону; открыто — непустое; в конце handoff и /clear.
LESSONS: W1b: стадия 0 нашла 5 blocker в 1.5 и 6 major в 1.1 — исправлять текстом до тестов; ревью ветки показало, что тесты не ловили `live` и порядок проверок; ложно красный стоп-хук pre_report_gate (запись в plans/queue/inbox/); PortContractSuite и фейк на железе не проверены (день с железом №1, Task 0.5).
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: брать ли в 1.0 драйвер `mvcr` (3.1, нужен как зависимость 4.2a → 3.2) — решает лид К на стадии 0 с числами; сообщить координатору.
```
