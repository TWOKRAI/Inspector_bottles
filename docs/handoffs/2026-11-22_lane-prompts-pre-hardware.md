# Промпты полос «до железа» (координатор inspector-bottles-30, 2026-11-22)

> Железо (робот, камера) приходит 23.11; владелец несколько дней готовится. Цель этих дней — чтобы в день №1 и день №2 не искать, а исполнять: код К/Р2 готов, стенд на симе зелёный при `run_gate: true`, чек-листы свежие, числа «что должно получиться» записаны заранее.
> Порядок по решению владельца 2026-11-21: критический путь (К W4/R4, Р2, Пульт, release-1.0, дни с железом) — первым; observability, C-93, C-36/A — только на свободном слоте.

Состояние — по `git main` (`15858154e`, 2026-11-22 09:59), отчётам и заявкам 21–22.11. Других сессий на машине нет: все полосы стартуют заново, каждый блок вставлять в новый чат целиком. Mac, `machine.lock` нет: тесты — через `machine_gate.sh` (абсолютный путь: `git rev-parse --path-format=absolute --git-common-dir` + `/../scripts/machine_gate.sh`), стенд — только `scripts/stand_gate` (сам берёт `stand.lock`).

## Где мы (22.11)

| Полоса | В main | Не сделано |
|---|---|---|
| Ф (run-state) | P3r, R3c, S4b2, патч `--autostart`/`run_gate` в `bootstrap()`, **коммит B: `run_gate: true`** (`f32812114`) | RN1 (общий `read_node`, баг `io_debug_section.py:250`, `telemetry_view_model.py:258`), PS1 (`plan.md` 35 928 → ≤ 32 000 Б); файл PM (C-36/A) не тронут |
| Пульт (фаза 6) | 6.1–6.6; живая приёмка β8 на симе — механизм PASS, C-103 FAIL | **повторная проверка при `run_gate: true` не сделана** (критический путь); S6 одним прогоном через поле «Слово»; «Домой» при диске в полёте |
| К (камера) | W3, 4c, стадия 0 4.2a раунд 1 (CHANGES REQUESTED), ответы владельца по R4 | **кода W4 нет**: 4.2a → 4.2b, 4.3, 4.4 → R4 (3 коммита); ветка `feat/camera-w4`, дерево `Inspector_bottles--lane-K-w4` |
| Р2 (робот) | T1.4, T5.3e.1–6, C-56, T5.4, T5.5, T5.6; брифы А и Б (в main) | **А и Б не исполнены** (`git grep max_reconnect_attempts` в рецептах — пусто; `_clock` в сторожe — нет); C-72, C-104; T0.3 `[BLOCKED]` железом, T4.0–T4.6 после него |
| Д2 (дефекты) | C-99 закрыт | C-93 (нужен слот + Opus-ревью), C-36/A (шаг 0 — стенд, ждёт CTO Р1–Р5) — **не стартуем**, не критический путь |
| Н (observability) | срез 0.1–0.11 влит `15858154e` | 0.11b, 0.12, 0.12b, 0.13; C-106, C-107 (sentrux, `no_god_files`) — **стадия 0 без кода** до слова координатора |
| release-1.0 | 1.2 (α по механизму) | 1.1 по плану сверена? (проверить), **2.1 (готовность β) PENDING**, 2.2 (прогон β — день №2), 3.1 |
| letters-retrain | 0.2, 0.3 | **0.4 базовая линия — коммитов замера нет** (на симе — можно сейчас; на реальных кадрах — день №1) |

**Писатели кода (не больше трёх):** К (большой), Р2 (малый, часы), Ф (RN1, малый). Пульт — только стенд; «Готовность» — документы и замер; Н — документы. Слияния в `main` делает координатор по файлу-заявке `docs/handoffs/<дата>_<полоса>-merge-request.md`; полоса в `main` не коммитит.

**Очередь стенда (порты 8765/8766/5021/8091/8092 зашиты):** 1) Пульт (повторная проверка) → 2) Р2 (замер лога переподключения, бриф А) → 3) «Готовность» (замер 0.4 на симе, если нужен стенд). Все — через `scripts/stand_gate`, он не даст пересечься; кто закончил — пишет «стенд свободен» в отчёте.

**Golden-снапшот β** (`hikvision_letter_robot.build.json`) трогают К (R4) и Р2 (только `letter_robot_sim.yaml`, β — нет). Кто сливается вторым — пересобирает после rebase (`UPDATE_BUILD_SNAPSHOTS=1`, дифф просмотреть), вручную не мёржить.

**Главная ловушка дня №1 (решение владельца нужно, вопрос 1):** день №1 снимает кадры на **старом пути** (`Services.hikvision_camera`, чек-лист М1). 4.2b удаляет старый путь. Рекомендация: день №1 идёт с закреплённого коммита (`git worktree add ../Inspector_bottles--day1 15858154e`), W4 сливается в `main` независимо и день №1 не ломает.

---

## Полоса К — камера W4: 4.2a → 4.2b, 4.3, 4.4 → К4' одним коммитом; затем R4

```
ВКЛАДКА: Полоса К · камера W4 — 4.2a раунд 2 стадии 0 → код
ROLE: lead of lane К, plan plans/2026-10-18_camera-device-service/. Запрет W4 снят владельцем (docs/handoffs/2026-11-20_owner-decisions-after-cto-review.md). Ветка `feat/camera-w4`, дерево `Inspector_bottles--lane-K-w4`; перед началом rebase на текущий main (`15858154e`). Статус задач — из git, не из шапок.
READ FIRST: docs/handoffs/2026-11-20_camera-4.2a-stage0-round1.md (B1–B5, M1–M8, REDS R1–R12); docs/handoffs/2026-11-20_camera-w4-r4-owner-questions.md (ответы владельца по R4: `use_linear: false`, `first_y: -440`, драйвер `delta_v2` отдельным коммитом); plans/2026-10-18_camera-device-service/tasks/4.2a.md, 4.2b.md, 4.3.md, 4.4.md; ORDER строки 21–23; docs/handoffs/2026-11-15_day1-camera-checklist.md.
GOAL: 4.2a принят стадией 0 → 4.2a → 4.2b → 4.3 → 4.4, К4' ОДНИМ коммитом (старый test_plugin.py красный до 4.2b); затем R4 тремя коммитами в порядке: (1) камера на `camera_device`, (2) `use_linear: false` + `first_y: -440`, (3) драйвер `delta_v2` — последним и отдельно, чтобы откат был одним коммитом.
ЗАДАЧИ СЕЙЧАС:
  1. Переписать текст 4.2a по B1–B5 и M1–M8. M2 («всегда BGR», mono8 → GRAY2BGR) отклоняется от записи владельца 11-20 («gray для mono8»): писать с BGR и пометкой «ждёт владельца», одной строкой вынести в отчёт; кода пока нет.
  2. Раунд 2 стадии 0 — тому же ревьюеру (agentId `a9902a4701d40e5cd`, если жив; иначе свежий `reviewer` sonnet с файлом раунда 1). Если Task Level Senior+ — написать координатору (inspector-bottles-30) ДО стадии 0 и получить номер N/6 пилота «стадия 0 в тень» (счётчик 3/6 по шапке ORDER; протокол docs/reports/2026-10-26_stage0-eval.md); без номера — обычная стадия 0 на Sonnet.
  3. Дальше по конвейеру: слепой tester ОДИН раз (worktree на коммите до кода, REDS из текста), developer, инъекции с предсказаниями до прогона, Opus-ревью ветки перед main.
  4. Старый путь НЕ ломать до слова координатора о слиянии: день №1 может идти на нём (вопрос 1 владельцу). До слияния К4' сверь с координатором, что день №1 закреплён на коммите.
  5. Документом, параллельно: сверить чек-лист дня №1 (`2026-11-15_day1-camera-checklist.md`) и сухой прогон (`2026-11-20_day1-dry-run.md`) с main; что устарело после W4/R4 (рецепт записи, имена плагинов, разрешение 1624×1240 — вопрос лиду из §4.3) — списком в отчёт; чек-лист не переписывать без слова.
  6. 2.2c «stopping при auto_start»: ключ `readiness` в узле камеры — при R4, не сейчас.
ACCEPTANCE: стадия 0 APPROVED с литералами REDS; затем числа тестов и инъекций; R4: рецепт β собирается на `camera_device`, golden β перегенерирован (дифф просмотрен), `use_linear: false` без F7 даёт отказ/нули — ожидаемо, строка-комментарий в рецепте.
PIPELINE: «Task launch convention» (стадия 0 → tester → developer → инъекции → ревью); `effort` по сложности; субагенты не коммитят.
BOUNDARIES: твои — `Services/camera_device`, `Services/hikvision_camera`, рецепты узла камеры, `hikvision_letter_robot.yaml` + golden (R4). Не писать: PM/spawner/state_store (Ф), `Plugins/hub/device_hub` (Р2), блок `pult` (Пульт). Работать только в своём worktree; перед каждым коммитом `git branch --show-current` (не main). В основном дереве лежат чужие неотслеженные файлы — не трогать. MVS-SDK на Mac нет → всё на `driver: fake`/sim; что не проверено без железа — назвать в отчёте.
LOAD: координатор inspector-bottles-30; первое сообщение — имя своей сессии (первая строка твоего ListAgents). Первая строка каждого ответа владельцу — ВКЛАДКА + имя сессии. `machine_gate.sh` по абсолютному пути; heavy — по Mac-правилу (стенд только `scripts/stand_gate`).
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-18_camera-device-service/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; в main не коммитить, заявка файлом.
LIMITS: 2 итерации, на 3-й вверх; красный вне `plans/queue/defects.md` — регистрировать.
REPORT: docs/reports/<дата>_camera-device-service_W4.md ≤ ~15 строк, по-русски, непустое «Открыто»; agentId-таблица; в конце задачи — handoff и /clear.
LESSONS: порядок записи плана = порядок объявления полей (B2); `packet_size = 0` даёт ложный `param_errors` (B3); имена дебайера OpenCV инвертированы относительно GenICam (B5, проверен только RG); общий `git stash` на все worktree — только WIP-коммит.
```

## Полоса Р2 — брифы А, Б, затем C-104, C-72; сверка дня №2

```
ВКЛАДКА: Полоса Р2 · А (reconnect 0) + Б (C-101) + C-104, подготовка дня №2
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md. T1.4, T5.3e.1–6, T5.4–T5.6 уже в main; T0.3 `[BLOCKED]` (нужен робот), T4.0–T4.6 после него. Брифы в main (`61e8f24f0`).
READ FIRST: docs/handoffs/2026-11-20_R2-briefs-reconnect-and-C101.md, 2026-11-20_R2-recipe-diff-reconnect.md, 2026-11-20_R2-params-path-test.py.txt; docs/reports/2026-11-15_R2_lane.md; plans/queue/defects.md (C-72, C-101, C-104); docs/handoffs/2026-11-15_day2-robot.md (с «Сверкой 2026-11-19/20»); Plugins/hub/device_hub; ORDER строки 7–9, 24–25.
GOAL: две малые правки + C-104 в main, сверка визита с main — день №2 исполняется по бумаге.
ЗАДАЧИ (по порядку):
  1. Бриф А: тест через `DeviceHubPlugin.start()` (`recipe_devices` с `params: {max_reconnect_attempts: 0}` → `driver.max_reconnect_attempts == 0`, литерал); затем правка рецептов 1.0 с `robot_main`/`vfd_belt` (`letter_robot_sim.yaml` и др.); `hikvision_letter_robot.yaml` НЕ трогать — К, R4; передать К строкой в отчёте, что туда нужно то же. Замер на сим-стенде (`scripts/stand_gate`, очередь: после Пульта): число строк лога «connect» в минуту при «без лимита»; `upsert` заменяет `params` целиком — оговорку в отчёт.
  2. Бриф Б (C-101): `Services/device_hub/tests/test_no_private_driver_state.py` — литерал 71, запись `"_clock": 1` в `_SEAMS` с комментарием; solo допустимо (1 файл, < 20 строк) — сказать вслух; инъекции (i)–(iii) из брифа с предсказаниями ДО запуска; ожидание `6 passed`.
  3. C-104 (тихий отказ задания после «Домой», пока серво OFF; ложное «слово собрано») — это сценарий оператора на настоящем роботе («Домой» → слово → диски). Сделать громким: лог/ошибка в журнале и видимый статус в `robot_io`/`layout` (где именно — решение лида на стадии 0, reviewer sonnet на тексте). Решение «что показать оператору в Пульте» (блок `pult` в рецепте) — не твоё, оформить вопросом владельцу. Если лид решит, что это не блокирует сценарий — записать причину и перенести в OPEN_QUESTIONS.
  4. C-72 (`test_robot_client_reads_growing_encoder`: «энкодер не вырос: first=0, second=0», повторён на Mac): `line_sim` передан тебе — investigator (haiku-инвентарь → opus), ТОЛЬКО диагноз, правка отдельным слотом.
  5. T5.3e.5 (`robot_park_all` для `pre_stop`, C-60.b): `git grep` — влито ли; если нет — бриф. Также из OPEN_QUESTIONS: `RobotDriverV2.tick` может бросить наружу (`driver.py:639`) — оценить, нужен ли до дня №2.
  6. Сверка дня №2: `2026-11-15_day2-robot.md` против main (`pc_probe.py all`, что принести, порядок дня); `devices.yaml` не копировать, REVIEW-5 не запускать без слова владельца. Результат — список «устарело/добавить».
ACCEPTANCE: `Plugins/hub/device_hub/tests` и `Services/device_hub/tests` зелёные (числа); инъекции совпали с предсказаниями или расхождение объяснено; C-104 — тест на литерал «отказ виден».
PIPELINE: «Task launch convention»; для п.1 и п.3 — стадия 0 reviewer sonnet на тексте, слепой tester; п.2 — стадии 3 и 5 обязательны; субагенты не коммитят.
BOUNDARIES: твои — Plugins/hub/device_hub, Services/device_hub, Plugins/sim/robot_host, вкладка робота, line_sim (C-72 — диагноз). Не писать: PM/spawner/state_store (Ф), Services/camera_device и β-рецепт (К), блок `pult` (Пульт). Свой worktree; перед коммитом `git branch --show-current`.
LOAD: координатор inspector-bottles-30; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути; стенд — `scripts/stand_gate`.
COMMITS: feat/fix/test/docs + Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; числа замеров, не «успеем».
REPORT: docs/reports/<дата>_R2_lane.md ≤ ~15 строк, по-русски, непустое «Открыто»; agentId; в конце — handoff и /clear.
LESSONS: `devices.yaml` делят стенды разных worktree (`.claude/worktrees/data/devices.yaml`); `upsert` заменяет `params` целиком; фейк без нужного атрибута делает тест зелёным по другой причине — утверждать причину.
```

## Полоса Ф — RN1 и PS1 (малый писатель), затем стоп

```
ВКЛАДКА: Полоса Ф · RN1 «чтение узла» + PS1 (plan.md ≤ 32 КБ)
ROLE: lead of lane Ф, plan plans/2026-10-27_system-run-state/plan.md. В main: P3r, R3c, S4b2, патч headless-старта и коммит B (`run_gate: true`, `f32812114`). Стенд R3c и условия B сняты (отчёт docs/reports/2026-11-21_system-run-state_lane-f-stand.md).
READ FIRST: plans/2026-10-27_system-run-state/tasks/RN1.md, PS1.md; handoff docs/handoffs/2026-11-21_system-run-state_lane-f-stand-patch-b-handoff.md; OPEN_QUESTIONS (записи Ф 2026-11-21).
GOAL: RN1 — общий помощник «чтение узла» в `telemetry_readmodel_module` и починка двух вызывающих мест (`io_debug_section.py:250`, `telemetry_view_model.py:258`; баг после П3, до 1.0); PS1 — `plan.md` в бюджет 32 000 Б без потери содержимого (вынести в plan-done/tasks).
ЗАДАЧИ:
  1. RN1: бриф без стадии 0 → стадия 0 reviewer sonnet (Opus-замечание: помощник НЕ в приватном модуле `backend_ctl`), слепой tester один раз, developer, инъекции с предсказаниями до прогона, ревью. Level Senior+? — напиши координатору (inspector-bottles-30) ДО стадии 0 за номером N/6.
  2. PS1 — документ; haiku/docs-writer по точному списку переносов, лид проверяет `scripts/plans_ledger.py`/`plans_progress --check`.
  3. Файл PM (`process_manager_process.py`, C-36/A), `launcher/spawner.py`, `state_proxy.py` — НЕ трогать до слова координатора (решения владельца/CTO Р1–Р5).
  4. После RN1: «входы без `--autostart`» из OPEN_QUESTIONS (`alpha_sim`, `AGENTS.md:85`, `run_sim_all.ps1:21`, `main.py __main__`) — составить список с рекомендацией владельцу; чинить только по слову.
ACCEPTANCE: RN1 — литералы из брифа, оба вызывающих места читают узел одним помощником, красных из-за RN1 нет; PS1 — `plan.md` ≤ 32 000 Б (число), `plans_progress --check` без новых находок.
PIPELINE: «Task launch convention»; тесты — через machine_gate; стенд не нужен; субагенты не коммитят.
BOUNDARIES: твои — PM, spawner, state_store_module, `telemetry_readmodel_module`, run-state виджеты. Не трогать: Services/camera_device (К), device_hub и вкладку робота (Р2), блок `pult` (Пульт), файлы Н (`logger_module/adapters/std_facade.py`, `logger_core.py`, `log_channel.py`, `state_store_module/core/freshness.py` — полоса Н влила их 22.11; перед правкой `git log -3 -- <файл>`). Свой worktree; `git branch --show-current` перед коммитом.
LOAD: координатор inspector-bottles-30; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-27_system-run-state/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; красный вне реестра — регистрировать.
REPORT: docs/reports/<дата>_system-run-state_lane-f-RN1.md ≤ ~15 строк, по-русски, непустое «Открыто»; agentId; в конце — handoff и /clear.
LESSONS: ложного «ready» без кадров за PASS не считать; тест, вызывающий `frontend/run.py launch()`, оставляет `INSPECTOR_PRESENTATION` в env; классификатор прав отклоняет агентный `git rebase`/`--amend` — rebase лид делает сам.
```

## Полоса Пульт — повторная проверка при `run_gate: true` (без кода)

```
ВКЛАДКА: Пульт · повторная проверка при run_gate: true (S6, лента, «Домой», «Серво ВКЛ»)
ROLE: lead of lane Пульт, plan plans/pult-control-panel-phase6.md. 6.1–6.6 в main. Приёмка 6.5 шла при `run_gate: false`; Ф влил `run_gate: true` (`f32812114`) — теперь рецепт 1.0 после подъёма стоит в `ready`, нужна кнопка ЗАПУСТИТЬ. Код пульта не пишешь: стенд и отчёт.
READ FIRST: docs/reports/2026-11-21_pult_6.5.md и …_pult_6.5_tester.md; docs/handoffs/2026-11-21_pult-6.5.md; plans/queue/defects.md (C-103, C-104, C-105); docs/reports/2026-11-21_system-run-state_lane-f-stand.md §2 (какие входы без START встают в `ready` без кадров).
GOAL: повторить приёмку 6.5 на `main` `15858154e` с `run_gate: true`, дойти до того, чего в первый раз не сделали, и дать числа «до/после» против отчёта 21.11.
ЗАДАЧИ:
  1. До окна — предсказания лида письменно (что увидим на мониторах после ЗАПУСТИТЬ, как поведёт себя C-103 под `run_gate: true`); опись haiku по стенду §2.1 design.md.
  2. Окно стенда (`scripts/stand_gate`, твой слот — первый в очереди; qt-mcp у координатора `CONNECTION_CLOSED` — проверь своё подключение, иначе backend_ctl + тесты вкладки, непроверенную GUI-часть назвать): рецепт 1.0 поднять → «ready» → кнопка ЗАПУСТИТЬ → S6.
  3. Недоделанное в первой приёмке: S6 ОДНИМ прогоном через поле «Слово» + Enter + диски (а не регистром); «Домой» при диске в полёте; «Серво ВКЛ» после «Домой»; фокус-аут «Слова», «✕», «Добавить контрол»; C-105 (GUI `terminated` 5,9 с) — воспроизведение с числом.
  4. C-103 («Лента стоп» → `belt_mm_s 0` не ≤ 1 с, а 0,37…4,65 с): замерить ещё раз под `run_gate: true`; решение «что мерим — ленту или публикацию метрики сима» — вопрос владельцу (в отчёт), не твоё.
  5. По окончании в отчёте строка «стенд свободен» (порты, процессы, `stand.lock`).
ACCEPTANCE: таблица S6-через-пульт с числами (форма как в отчёте 21.11, колонка «было → стало»); красные — по defects.md; что не проверено — списком.
PIPELINE: стенд — независимый `tester` (слепой, предсказаний лида не видит), инъекции только при коде; субагенты не коммитят.
BOUNDARIES: вкладка «Пульт», `Services/control_panel` — твои (но кода не пишешь). Не писать: PM/spawner/state_store (Ф), Services/camera_device и β-рецепт (К), Plugins/hub/device_hub (Р2). «Домой»/«Серво ВКЛ» в β — только после R4.
LOAD: координатор inspector-bottles-30; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` и `scripts/stand_gate` — абсолютный путь.
COMMITS: docs + Why:/Layer:/Refs: plans/pult-control-panel-phase6.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; число-замер, не «успеем».
REPORT: docs/reports/<дата>_pult_recheck-run-gate.md ≤ ~15 строк, по-русски, непустое «Открыто»; handoff и /clear.
LESSONS: tester стенда 21.11 — `a4b4b92c9a8104e7d` (sonnet, ~207k токенов — при ~400k не re-summon, а свежий с файлом отчёта); `INSPECTOR_PID_FILE` и `BACKEND_CTL_PORT` — свои; общий `devices.yaml` делят стенды разных worktree.
```

## Полоса «Готовность» — release-1.0 2.1/2.2, паспорт дней №1–№2, letters-retrain 0.4 на симе

```
ВКЛАДКА: Готовность · release-1.0 2.1 + паспорт дней с железом + letters 0.4 (сим)
ROLE: lead of lane «Готовность», plans release-1.0/plan.md, letters-retrain/plan.md. Документы и замер; кода приложения не пишешь (скрипты анализа в scripts/ — можно, новые файлы, без правок чужих). Слот писателя кода НЕ занимаешь.
READ FIRST: plans/release-1.0/plan.md, design.md §3 (чек-лист β), tasks/2.1.md, 2.2.md, 1.2.result.md; docs/handoffs/2026-11-15_day1-camera-checklist.md, 2026-11-20_day1-dry-run.md, 2026-11-15_day2-robot.md; plans/letters-retrain/plan.md (Task 0.4); scripts/capture_baseline.py, scripts/day1_capture_check.py; ORDER строки 4, 23–27.
GOAL: к вечеру владелец держит один лист «что делаю в день №1 и день №2, что должно получиться числами, что ещё не готово и кто это закроет».
ЗАДАЧИ:
  1. release-1.0 Task 2.1 (инвентаризация по git, таблица β1–β10 → строка ORDER → задача → SHA в main или «нет, ждёт чего»); шапкам плана не верить; `git merge-base --is-ancestor`. Task 1.1 — сверить, что закрыта по git. Developer sonnet.
  2. Паспорт готовности (docs/handoffs/2026-11-22_hardware-readiness.md, ≤ 2 страниц): по каждому дню — что нужно принести/установить (MVS-SDK, прошивка, кабели — из существующих чек-листов, не переписывать), порядок шагов, критерий PASS числами, ЧТО ИЗМЕНИЛОСЬ с 15.11 (W4/R4, `run_gate: true` и кнопка ЗАПУСТИТЬ, Пульт, журнал обмена T5.6, observability-срез 0), «какой рецепт и на каком коммите запускать» — по git, без угадывания. Расхождения между чек-листами и main — таблицей. Если для дня №1 нужен закреплённый коммит (вопрос 1) — написать команду worktree.
  3. letters-retrain Task 0.4 на симе: базовая линия текущей сети (`defect_rate 0`, смещение ±10–20 px; точность, доля ниже порога, полнота по буквам, угол против истины сима) — только если сеть и среда запускаются на этой машине; иначе назвать, чего не хватает (GPU/модель/данные) и готовить скрипт под запуск на машине владельца. Скрипт параметризовать каталогом кадров, чтобы в день №1 прогнать тот же замер по реальным кадрам (`scripts/day1_capture_check.py` — не дублировать, сверить). Стенд, если нужен, — `scripts/stand_gate` после Пульта.
  4. Предсказания лида для дня №1: что покажет `day1_capture_check` на реальных кадрах и что считать провалом (порог узнавания букв с MVS — ORDER 27); записать ДО дня.
ACCEPTANCE: 2.1.result.md с 10 строками и SHA; паспорт ≤ 2 страниц; 0.4 — числа на симе либо точный список блокеров.
PIPELINE: «Task launch convention»; developer sonnet для 2.1, haiku для инвентаризаций; tester не нужен (документы); субагенты не коммитят.
BOUNDARIES: твои — plans/release-1.0/*, новые файлы docs/handoffs и scripts для замера. Не править: ORDER.md (координатор), чек-листы К/Р2 (они свои правят — пиши им через отчёт), код любых модулей.
LOAD: координатор inspector-bottles-30; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути.
COMMITS: docs + Why:/Layer:/Refs: plans/release-1.0/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; незнание — в «Открыто», не догадка.
REPORT: docs/reports/<дата>_release-1.0_readiness.md ≤ ~15 строк, по-русски, непустое «Открыто»; в конце — handoff и /clear.
LESSONS: шапки планов отстают от git минимум в пяти планах; чек-лист дня №1 написан 15.11, до W4/R4 и `run_gate: true`.
```

## Полоса Н — observability, только стадия 0 (без кода до слова координатора)

```
ВКЛАДКА: Полоса Н · observability фаза 0, хвост: стадия 0 для 0.11b, 0.12, 0.12b, 0.13
ROLE: lead of lane Н, plan plans/2026-11-21_observability-signal-contracts/. Срез 0.1–0.11 влит в main `15858154e` (стенд — БЛОКЕРОВ 0). Остались 0.11b, 0.12, 0.12b, 0.13 и хвосты фазы 0. Статус зоны 1.0: «последняя, на свободном слоте, критический путь не задерживает».
READ FIRST: plan.md, amendments.md (поправка 8 — дрейф contract.lock), tasks/0.11b.md, 0.12.md, 0.12b.md, 0.13.md; docs/claude/OPEN_QUESTIONS.md блок «хвосты фазы 0»; plans/…/reports/phase0.branch-review-opus.md; docs/reviews/2026-11-22_stand-phase0.md.
GOAL: тексты 0.11b–0.13 готовы к коду (стадия 0 пройдена), слот писателя — по слову координатора, когда Р2 или Ф освободят.
ДО СЛОВА КООРДИНАТОРА: только стадия 0 reviewer sonnet на текстах; Senior+ — написать координатору (inspector-bottles-30) ДО стадии 0 за номером N/6 пилота; слепой tester ОДИН раз на механизм, worktree на коммите до кода. Кода нет.
ТАКЖЕ:
  1. Хвосты фазы 0 разобрать и отсортировать для владельца: что блокирует сценарий 1.0 (слово → диски → буквы → робот) — почти ничего; остальное — 2.0. Особо: `set_register_verified` отдаёт `success=True` при `vacuous` (читатель по одному `success` увидит ложный успех) — вопрос владельцу с рекомендацией; метка `processes.<p>._fresh` подузел под `processes.<P>` — подтверждение владельца.
  2. Решение по размеру Task для `contract.lock` (`PLAN_TOO_BIG`/`TASK_TOO_BIG`) — вопрос координатору с вариантами, не пиши в обход.
  3. C-107 (`sentrux`, `no_god_files`, `control_panel/tests/test_recipe_1_0.py`, fan-out 20) и C-106 (пять голых `logging.getLogger` в Services/hikvision_camera, camera_device/…) — файлы чужих полос (Пульт, К): передать строкой в их отчёты, не править.
ACCEPTANCE: стадия 0 APPROVED с литералами по каждой из 4 задач или CHANGES REQUESTED со списком; список вопросов владельцу.
PIPELINE: «Task launch convention»; три роли авторов тестов; субагенты не коммитят.
BOUNDARIES: по таблице владения design.md §5; не трогать файлы Ф (`process_manager_process.py`, `launcher/spawner.py`, `state_store_module/state_proxy.py`) — RN1 у Ф идёт сейчас; `std_facade` — C-93 (Д2), пересечение с `logger_core.py`/`log_channel.py`; ORDER.md не править. Свой worktree `Inspector_bottles--lane-N`, `git branch --show-current`.
LOAD: координатор inspector-bottles-30; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-11-21_observability-signal-contracts/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить.
LIMITS: 2 итерации.
REPORT: docs/reports/<дата>_observability-signal-contracts_0.11b-0.13-stage0.md ≤ ~15 строк, по-русски, непустое «Открыто».
LESSONS: дефекты полосы при слиянии перенумеровывают (C-106, C-107, номера 102–105 заняты); последний прогон — 485 красных против 483 на main, разница объяснена фейком router; исчерпание POSIX-семафоров macOS даёт ложный красный в `process_manager_module/tests` (C-93).
```

## Второй заход (14:30, после слияний К4', Р2, RN1/PS1)

В `main` с утра: Пульт-повтор `94bc1a729`, Р2 `95d496376`, PS1 `212c93f91`, RN1 `d221d9a9c`, К4' `6cb212213`. Пишут код: К (R4 — R4-1, R4-2 готовы в `feat/camera-r4`, R4-3 `delta_v2` впереди) и Н (0.12: слепые RED и рукопожатие в `feat/obs-0.12-handshake`). Свободны: Р2, Ф, Пульт. «Готовность» не стартовала — это главный пробел «до железа».

**Из вердикта Fable (`docs/reports/2026-11-22_fable-architecture-review/arch-review-07a-…`) в этот заход берём только то, что до β:** п. 1 — лист из пяти чисел и день №1 с закреплённого коммита (закреплён: `../Inspector_bottles--day1`); п. 2 — рамки: в ядро только блокеры сценария. Остальное (п. 3 карантин красных `make gate`, п. 4 версия IPC и заморозка контрактов, п. 5–10) — ПОСЛЕ β, решения владельца, в этот заход не стартуем. «Не делать до 1.0»: срезы наблюдаемости сверх 0.13, F9, Zenoh/iceoryx2, msgspec, смена стека GUI.

### Полоса «Готовность» — дополнение к блоку выше

К задачам блока «Готовность» добавить: **лист из пяти чисел для β** (Fable, п. 1) — в паспорт готовности вписать, как и чем снимается каждое число и что считать провалом ДО дня: (1) секунд на диск, (2) доля верных букв на реальных кадрах (то же, что letters-retrain 0.4 на кадрах дня №1), (3) «взял и положил» из N, (4) часы без сбоя, (5) время «Стоп → всё погашено» (`outcome` стопа процессов из журнала). Плюс видео 2 мин — кто и чем снимает. Источник для К-части сверки уже есть: `docs/reports/2026-11-22_day1-checklist-vs-main.md` (К, 22.11; не повторять, использовать), для Р2-части — `docs/handoffs/2026-11-22_R2-day2-recon.md`.

### Полоса Р2 — заход 2: сверка дня №2 в документ, C-72, строки для β

```
ВКЛАДКА: Полоса Р2 · день №2 в бумаге + C-72 + C-108
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md. Заход 1 слит `95d496376` (А, Б, C-104). Читать: docs/reports/2026-11-22_R2_lane.md, docs/handoffs/2026-11-22_R2-day2-recon.md (40 строк «ВЕРНО/УСТАРЕЛО/ДОБАВИТЬ»), docs/handoffs/2026-11-22_R2-merge-request.md («Открыто»), plans/queue/defects.md (C-72, C-104, C-108), docs/claude/OPEN_QUESTIONS.md (записи Р2 22.11).
GOAL: день №2 исполняется по одному актуальному документу; C-72 закрыт; снимок полей robot_io в каталоге регистров не красный.
ЗАДАЧИ:
  1. Применить сверку к docs/handoffs/2026-11-15_day2-robot.md: УСТАРЕЛО поправить, ДОБАВИТЬ вписать (pre_stop, C-104 «задание отказано — виден в журнале», лимит переподключения 0, `run_gate: true` и кнопка ЗАПУСТИТЬ, кнопки Пульта «Домой»/«Серво ВКЛ», `pc_probe.py all` на sim: rc 0, 40 ключей, 65 с). Дата визита — в вопросы владельцу, не писать от себя. Документ — docs-writer/haiku по списку лида, лид сверяет.
  2. C-72 (`test_robot_client_reads_growing_encoder`: тест читает энкодер клиентом v1 по `0x1112`, стенд на v2, энкодер в `0x104C`): правка по диагнозу investigator (вариант A из OPEN_QUESTIONS), стадия 0 не нужна (1 тест), стадии 3 и 5 обязательны; предсказания инъекции ДО прогона.
  3. C-108: полям `robot_io` (`last_dropped_job`, `forward_ok`) — строки в `catalog_register_fields.txt` (их владелец — ты); `multiprocess_prototype/frontend/forms/tests` — зелёный.
  4. Рецепты 1.0, где ещё есть `robot_main`/`vfd_belt` без лимита 0 (`phone_sketch`, `robot_demo`, `webcam_sketch`, `camera_robot_calibration`): НЕ править до слова владельца — они не в сценарии 1.0; список остаётся в вопросах.
ACCEPTANCE: day2-robot.md без расхождений с main (список «осталось»); C-72 тест зелёный на v2 и красный при инъекции (число); C-108 закрыт числом тестов.
PIPELINE / BOUNDARIES / LOAD / COMMITS / LIMITS / REPORT — как в блоке Р2 выше; β-рецепт и golden — К (R4 в работе), не трогать. REPORT: docs/reports/<дата>_R2_lane-2.md.
```

### Полоса Ф — диагноз C-105 (без кода)

```
ВКЛАДКА: Полоса Ф · C-105 диагноз (GUI gui terminated 5,9 с)
ROLE: lead of lane Ф, только диагноз. C-105 (Пульт, 5/5 воспроизведений): при `system_shutdown` GUI-прогона процесс `gui` завершается как `terminated` за 5,9 с (headless — `exited` 0,7–1,1 с). На сценарий 1.0 не влияет напрямую, но оператор закрывает окно после слова/дисков, и честный `outcome` стопа — ваша зона (1.10).
READ FIRST: plans/queue/defects.md (C-105), docs/reports/2026-11-22_pult_recheck-run-gate.md и …_pult_recheck_tester.md (воспроизведение), plans/2026-10-20_gui-graceful-close/plan.md (1.4 pre_stop влита), lifecycle-stop-ownership 1.10/1.11.
GOAL: причина C-105 с воспроизведением (вход → наблюдаемый выход), вариант правки и его цена; правку НЕ писать. investigator (haiku-инвентарь логов процессов GUI, затем opus), стенд — `scripts/stand_gate` короткий, `INSPECTOR_PID_FILE`/`BACKEND_CTL_PORT` свои. Файл PM — только чтение.
ACCEPTANCE: отчёт ≤ 1 страницы: причина, где 5,9 с уходит (какая фаза стопа, какое окно), правка (файл:строка), блокирует ли β (да/нет, почему).
BOUNDARIES/LOAD/COMMITS/REPORT — как в блоке Ф выше; docs/reports/<дата>_system-run-state_lane-f-C105.md.
```

## Не стартуем сейчас

- **Д2 (C-93, C-36/A):** не критический путь. C-93 — слот писателя и Opus-ревью, C-36/A — шаг 0 стенда после ответов CTO Р1–Р5 и порогов. Стартуют после дней с железом, по слову владельца.
- **Пилот «стадия 0 в тень»:** счётчик в шапке ORDER 3/6 (с 27.10, свежего значения нет); Senior+ задачи (4.2a, RN1, 0.12?) пишут мне за номером.

## Вопросы владельцу (с рекомендацией)

| # | Вопрос | Рекомендация |
|---|---|---|
| 1 | День №1 на старом пути: закрепить коммит (`git worktree add ../Inspector_bottles--day1 15858154e`), чтобы W4 (4.2b удаляет старый путь) не ломал запись кадров? | Да; W4 сливается независимо |
| 2 | На какой машине подключаете MVS и робота (Mac здесь, чек-лист дня №1 — Windows-стенд с MVS-SDK)? От этого зависят паспорт «Готовность» и что К может проверить без железа | Назвать машину; К и Р2 готовят всё на симе |
| 3 | К, M2: камера отдаёт всегда BGR (mono8 → GRAY2BGR) вместо «gray для mono8» из записи 20.11? | Да, BGR (тип выхода — атрибут класса, проверяется до открытия камеры) |
| 4 | C-103: что считаем критерием «лента стоп ≤ 1 с» — ленту сима или публикацию метрики `belt_mm_s`? | Метрику сима: драйвер отвечает за 0,012–0,037 с, лаг на стороне сима; критерий плана переписать |
| 5 | C-104: что показать оператору при заданиях в `servo OFF` — монитор в блоке `pult` рецепта (код пульта, не 1.0-блокер, но на реальном роботе «Домой» → задание не пойдёт молча)? | Громкий лог (Р2) сейчас; монитор в Пульте — после дня №2 |
| 6 | `set_register_verified`: `vacuous` при `success=True` — менять до 1.0? | Нет; читатель с `verdict` видит; в 2.0 |
| 7 | Ф: Р1, Р2, В10, уровень WARNING `diverged` (R3c), 2.2c; CTO Р1–Р5 по C-36/A | Не блокируют день №1/№2; ответы до C-36/A |
| 8 | ORDER (строка 30, шапки): синхронизировать по git (Ф и Пульт влиты, Н срез 0 влит) | Да, отдельным `docs(plans)` коммитом координатора, после слияния полос этой волны |

## Что осталось открытым / ненадёжно

- Состояние собрано по git, ORDER, отчётам и заявкам; числа красных (483/485), стенда Ф, Пульта взяты из их отчётов, не пересчитаны. Ответы владельца по R4 (`docs/camera-w4-prep`) прочитаны по сводной таблице.
- Дерево: неотслеженные файлы `docs/reports/2026-11-17_visual-constructor-research*.md`, изменённый `MEMORY.md` и `observability-review.html` в основном checkout — не мои; не коммитил. ~220 worktree (`agent-*`, `lane-*`, `rs-*`) не разбирались.
- `qt-mcp` не подключён, Ollama не запущена (qex недоступен) — поиск вёл `git grep`.
- Счётчик пилота «стадия 0 в тень» 3/6 — по шапке ORDER от 27.10, свежее значение не проверял.
- Подготовка дня №1/№2 опирается на чек-листы 15.11; что изменилось после W4/R4 — выяснит полоса «Готовность».
