# Промпты на продолжение полос (координатор inspector-bottles-2b, 2026-11-21)

> **Порядок «к железу» (владелец 2026-11-21: сначала самое важное, потом остальное):** 1) К W4 → R4; 2) Р2: брифы А/Б, T0.3, T4.x; 3) Пульт: повторная проверка при `run_gate: true` (окно стенда); 4) `release-1.0`; 5) только потом observability (Н), C-93, C-36/A, RN1/PS1. Н идёт на свободном слоте и уступает К и Р2 на границе задачи.

Состояние — по `git main` (`96fb1ea59`), `ORDER.md`, отчётам и заявкам 20–21.11. Других сессий на машине нет: все полосы стартуют заново, каждый блок ниже вставлять в новый чат целиком. Mac, `machine.lock` нет: тесты и прогоны — через `machine_gate.sh` по абсолютному пути (`git rev-parse --path-format=absolute --git-common-dir` + `/../scripts/machine_gate.sh`), стенд — только через `scripts/stand_gate` (сам берёт `stand.lock`: два стенда одновременно невозможны).

## Где мы (21.11, после слияний Ф 1→4 и Пульт 6.1–6.4)

| Полоса | В main | Не влито / ждёт |
|---|---|---|
| Ф (run-state) | P3r, R3c, S4b2, OQ3 (`7ea6e8709`) | `feat/run-state-2-1-commit-b` (`run_gate: true`) — ждёт живого стенда; стендовый замер R3c не снят; файл PM (C-36/A) не тронут |
| Пульт (фаза 6) | 6.1, 6.1b, 6.1c, 6.2, 6.3, 6.4 | 6.5 живая приёмка β8 (окно стенда), 6.6 README/STATUS; шапки плана отстают от git |
| К (камера) | W3, 4c (`run_locked_commands`) | W4: 4.2a на стадии 0, раунд 1 CHANGES REQUESTED (`feat/camera-w4`, 1 коммит; ответы владельца по R4 — `docs/camera-w4-prep`, 2 коммита; не влиты, merge чистый) |
| Р2 (робот) | T1.4 (07.11), T5.3e.1–6, C-56, D1/D2 | брифы А (`max_reconnect_attempts: 0`) и Б (C-101) — `docs/r2-visit-prep-1120`, 2 коммита, не влиты; T0.3 `[BLOCKED]` (железо), T4.0 после него |
| Д2 (дефекты) | брифы C-99, C-93, C-36/A (стадия 0 пройдена) | писатель не выдан; шаг 0 теста условия отмены C-36/A — окно стенда |
| Н (observability-signal-contracts) | план APPROVED, ответы В-1…В-4, зона 1.0 (`a781e1061`) | кода нет; ORDER строка 30, «последняя в зоне 1.0» |

**Писатели сейчас (не больше трёх): К, Р2 (малый, часы), Д2 (C-99, только тесты).** Ф и Пульт кода не пишут — у них стенд, по очереди: **сначала Ф, потом Пульт 6.5**. Н до слова координатора — только стадия 0 и слепой tester, без кода. Слияния в `main` делает координатор по файлу-заявке `docs/handoffs/<дата>_<полоса>-merge-request.md`; полоса в `main` не коммитит. Golden-снапшот β (`hikvision_letter_robot`) трогают Ф (коммит B), Пульт (влито) и К (R4): кто сливается вторым — пересобирает после rebase (`UPDATE_BUILD_SNAPSHOTS=1`, дифф просмотреть), вручную не мёржить.

Решения владельца, нужные полосам (списком, чтобы никто не угадывал): см. раздел «Вопросы владельцу» в конце.

---

## Полоса Ф — стенд на сим-линии: R3c, коммит B 2.1

```
ВКЛАДКА: Полоса Ф · run-state: стенд R3c + коммит B 2.1 (run_gate: true)
ROLE: lead of lane Ф, plan plans/2026-10-27_system-run-state/plan.md. Статус из git, не из шапок. В main влиты P3r, R3c, S4b2, OQ3 (`7ea6e8709`).
READ FIRST: docs/reports/2026-11-21_system-run-state_lane-f-p3r-r3c-s4b2.md (особенно §4 «Открыто»); docs/handoffs/2026-11-21_system-run-state_lane-f-merge-request.md; docs/claude/OPEN_QUESTIONS.md (записи Ф 2026-11-21).
GOAL: снять на живом стенде числа по R3c и по `heavy`-условиям коммита B; при PASS слить B на новый main.
ЗАДАЧИ (по порядку):
  1. Стенд R3c на сим-линии: WARNING «diverged» за 25 с против базы 106–111; числа, не прилагательные; контроль на `main` до R3c — тем же способом.
  2. `heavy`-условия коммита B (ветка `feat/run-state-2-1-commit-b`, `1fbefc6d8`): `recipe_service` ×2, `test_frame_bridge_live`, `start_run` до `apply`. Нефатально: пути, берущие yaml напрямую (`run_alpha.py` без `--autostart`, пробы `backend_ctl/probes/*`, `tools/otel_stand/*`, `test_recipe_service_*_live.py`) встанут в `ready` без кадров — перечислить, какие чинить сейчас, какие в OPEN_QUESTIONS.
  3. Если п.2 PASS: rebase ветки B на текущий main, golden перегенерировать (`UPDATE_BUILD_SNAPSHOTS=1`, в диффе только `run_gate`; Пульт 6.2–6.4 уже поменяли рецепты), `backend/tests`, `recipes/tests`, `stand_gate/tests` на слитом дереве, заявка на слияние файлом. Слово координатора на слияние B = эта заявка с числами п.1–2; PASS по п.2 без п.1 тоже достаточно для B (п.1 — отдельная строка).
  4. Брифы, не код (слот писателя занят К/Р2/Д2): (а) общий помощник «чтение узла» в framework + починка `io_debug_section.py:250` и `telemetry_view_model.py:258` (баг после П3, до 1.0; Opus: помощник не в приватном модуле `backend_ctl`); (б) разбить `plan.md` (35 КБ при бюджете 32 КБ); (в) замечание `RobotDriverV2.tick` может бросить наружу (`driver.py:639`) — файл Р2, передать им записью в OPEN_QUESTIONS.
  5. Файл PM (`process_manager_process.py`, C-36/A) НЕ трогать: слот по слову координатора после дня №1 и после ответов владельца/CTO Р1–Р5.
ACCEPTANCE: таблица «до / после» по R3c и по условиям B с числами и командами; ссылка на запрос слияния; открытые решения — списком владельцу.
PIPELINE: «Task launch convention»; стенд — твоё окно, `scripts/stand_gate`, свои `INSPECTOR_PID_FILE` и `BACKEND_CTL_PORT`; Пульт 6.5 ждёт твоего окна — после стенда напиши в отчёте «стенд свободен»; субагенты не коммитят.
BOUNDARIES: твои — PM, spawner, state_store_module, run-state виджеты. Не трогать: `Services/camera_device` (К), `Plugins/hub/device_hub` и вкладку робота (Р2/Пульт), `hikvision_letter_robot.yaml` кроме `run_gate` (К, R4).
LOAD: координатор inspector-bottles-2b; первое сообщение — своё имя сессии (первая строка твоего ListAgents). Первая строка каждого ответа владельцу — ВКЛАДКА + имя сессии. `machine_gate.sh` — абсолютный путь.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-27_system-run-state/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; `git branch --show-current`; в main не коммитить.
LIMITS: 2 итерации, на 3-й вверх; красный, которого нет в `plans/queue/defects.md`, регистрировать.
REPORT: `docs/reports/<дата>_system-run-state_lane-f-stand.md`, ≤ ~15 строк по шаблону, по-русски, непустое «Открыто»; agentId-таблица; в конце — handoff и /clear.
LESSONS: ложного «ready» без кадров не принимать за PASS; общий `.claude/worktrees/data/devices.yaml` делят стенды разных worktree (находка Р2).
```

## Полоса Пульт — Task 6.5 (живая приёмка β8 на симе), 6.6

```
ВКЛАДКА: Пульт · 6.5 живая приёмка β8 на симе + 6.6 документы
ROLE: lead of lane Пульт, plan plans/pult-control-panel-phase6.md. В main влито 6.1–6.4 (шапки плана ещё пишут PENDING — синхронизируй по git в 6.6). Код пульта больше не пишешь: остались стенд и документы.
READ FIRST: docs/reports/2026-11-21_pult_6.4.md («Открыто»), 6.3, 6.2; план, Task 6.5 (ACCEPTANCE: «МИР» → журнал §2.5, 5 строк дисков, 3 `CVT_JOB`, `jobs_emitted 12`; «ПЕРЕМИРИЕ» без перезапуска → §2.6; лента стоп/пуск, «Домой», «Серво ВКЛ»).
GOAL: живая приёмка β8 с числами; пока стенд у Ф — подготовка (опись haiku, предсказания лида).
ЗАДАЧИ:
  1. До окна: инвентарь haiku по стенду §2.1 design.md; предсказания лида записать ДО прогона (что увидим на мониторах, как покажется bool «Слово собрано»).
  2. Окно стенда — после Ф (он напишет «стенд свободен» в своём отчёте; `scripts/stand_gate` не даст пересечься). qt-mcp в этой сессии у координатора `CONNECTION_CLOSED`: проверь своё подключение, иначе backend_ctl + тесты вкладки; GUI-часть, которая не проверена, назвать в отчёте.
  3. Проверить живьём то, что 6.4 назвал непроверенным: как пульт рисует 10 контролов; что лежит по `devices.state.robot_main.conn`; «Домой» → `park.state == "done"`; «Серво ВКЛ» после «Домой» принимает задания; `vfd_stop` → `belt_mm_s 0`.
  4. 6.6: README/STATUS `Services/control_panel` (дубль «Известные ограничения v1» убрать), строка ORDER, шапки плана по git; метки мониторов по-русски («Слово собрано»: Да/Нет, а не True/False) — только если решишь, что это не новый код; иначе в OPEN_QUESTIONS.
ACCEPTANCE: таблица S6-через-пульт с числами; красные — по `defects.md`.
PIPELINE: стенд — слепой/независимый tester для приёмки (Level Senior), инъекции с предсказаниями до прогона, Opus-ревью только если появится код; субагенты не коммитят.
BOUNDARIES: вкладка «Пульт», `Services/control_panel` — твои. Не писать: PM/spawner/state_store (Ф), `Services/camera_device` (К), `hikvision_letter_robot.yaml` (К, R4: «Домой»/«Серво ВКЛ» в β только после R4), `Plugins/hub/device_hub` (Р2).
LOAD: координатор inspector-bottles-2b; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` и `scripts/stand_gate` — абсолютный путь.
COMMITS: `feat`/`docs` + Why:/Layer:/Refs: plans/pult-control-panel-phase6.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; число-замер, не «успеем».
REPORT: `docs/reports/<дата>_pult_6.5.md`, по-русски, непустое «Открыто»; handoff и /clear.
```

## Полоса К — камера W4: 4.2a, затем 4.2b, 4.3, 4.4 → К4' одним коммитом; R4

```
ВКЛАДКА: Полоса К · камера W4 — 4.2a раунд 2 стадии 0
ROLE: lead of lane К, plan plans/2026-10-18_camera-device-service/. Запрет W4 снят владельцем (`docs/handoffs/2026-11-20_owner-decisions-after-cto-review.md`). Ветка `feat/camera-w4` (`6015c56c6`); дерево `Inspector_bottles--lane-K-w4`.
READ FIRST: `docs/handoffs/2026-11-20_camera-4.2a-stage0-round1.md` (в ветке `feat/camera-w4`; B1–B5, M1–M8, REDS R1–R12); `docs/handoffs/2026-11-20_camera-w4-r4-owner-questions.md` (в `docs/camera-w4-prep`: ответы владельца по R4 — `use_linear`, `first_y`, `delta_v2`); `plans/2026-10-18_camera-device-service/tasks/4.2a.md`; ORDER строки 22–29.
ПЕРЕД НАЧАЛОМ: docs-ветки К и Р2 уже влиты в main (`bbd64697f`, `72f7b404b`, `61e8f24f0`) — читай файлы из main и сделай rebase своей ветки `feat/camera-w4` на main.
GOAL: текст 4.2a принят стадией 0 (APPROVED), затем 4.2a → 4.2b → 4.3 → 4.4, К4' ложится ОДНИМ коммитом (старый `test_plugin.py` красный до 4.2b); после — R4 тремя коммитами (камера на ядре; `use_linear: false` + `first_y: -440`; драйвер `delta_v2` — последним, отдельно).
ЗАДАЧИ СЕЙЧАС:
  1. Переписать текст 4.2a по блокерам B1–B5 и major M1–M8 раунда 1. Решения лида К принять как предложены, КРОМЕ M2 («всегда BGR», mono8 → GRAY2BGR — отклоняется от записи владельца 11-20 «gray для mono8»): взять BGR как рекомендацию, но вынести владельцу одной строкой в отчёт; пока ответа нет — текст пишется с BGR и пометкой «ждёт владельца», кода нет.
  2. Раунд 2 стадии 0 — тому же ревьюеру (agentId `a9902a4701d40e5cd`, если жив; иначе свежий reviewer sonnet с файлом раунда 1); ≤ 2 итераций, дальше `ESCALATION -> teamlead`.
  3. Затем по конвейеру: слепой tester в worktree на коммите до кода (REDS из текста), developer, инъекции с предсказаниями до прогона, Opus-ревью перед main.
  4. Параллельно, документом: подготовка дня №1 (задача 0.5, ORDER 25): чек-лист + что записывать — `docs/handoffs/2026-11-15_day1-camera-checklist.md`, сухой прогон `docs/handoffs/2026-11-20_day1-dry-run.md` уже есть; что устарело — поправить.
  5. 2.2c «stopping при auto_start»: вариант CTO (б), ключ `readiness` в узле камеры — при R4, не сейчас.
ACCEPTANCE: стадия 0 → APPROVED с литералами REDS; после — числа тестов и инъекций.
PIPELINE: «Task launch convention» (стадия 0 → tester → developer → инъекции → ревью); `effort` по сложности.
BOUNDARIES: `Services/camera_device`, `Services/hikvision_camera`, рецепты узла камеры, `hikvision_letter_robot.yaml` (R4) — твои. Не писать: PM/spawner/state_store (Ф), `Plugins/hub/device_hub` (Р2), блок `pult` в рецептах (Пульт). Дерево `Inspector_bottles--lane-K-4c` содержит ЧУЖИЕ правки C-100 (`telemetry_chart.py`, `test_telemetry_chart.py`) — не трогать, ждут слова владельца.
LOAD: координатор inspector-bottles-2b; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути; heavy — только в своём окне.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-18_camera-device-service/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; в main не коммитить.
LIMITS: 2 итерации; красный не из реестра регистрировать.
REPORT: `docs/reports/<дата>_camera-device-service_W4.md`, по-русски, непустое «Открыто»; agentId-таблица; handoff и /clear.
LESSONS: порядок записи плана = порядок объявления полей (B2); `packet_size = 0` даёт ложный `param_errors` (B3); имена дебайера OpenCV инвертированы относительно GenICam (B5, проверен только RG, железа нет).
```

## Полоса Р2 — брифы А и Б (малые), затем визит

```
ВКЛАДКА: Полоса Р2 · max_reconnect_attempts: 0 + C-101 (малые правки), потом визит
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md. T1.4 уже в main (07.11), T5.3e.1–6 влиты. T0.3 `[BLOCKED]` железом, T4.0 после него. Брифы уже в main (`61e8f24f0`): docs/handoffs/2026-11-20_R2-*.md.
READ FIRST: `docs/handoffs/2026-11-20_R2-briefs-reconnect-and-C101.md`, `2026-11-20_R2-recipe-diff-reconnect.md`, `2026-11-20_R2-params-path-test.py.txt` (из той ветки); `docs/reports/2026-11-15_R2_lane.md`; plans/queue/defects.md (C-72, C-101); Plugins/hub/device_hub, ORDER строки 8, 26, 27.
GOAL: две малые правки в main + сверка визита.
ЗАДАЧИ:
  1. Бриф А: тест через `DeviceHubPlugin.start()` (`recipe_devices` с `params: {max_reconnect_attempts: 0}` → `driver.max_reconnect_attempts == 0`, литерал); затем правка рецептов 1.0 (`letter_robot_sim.yaml` и другие, где есть `robot_main`/`vfd_belt`; `hikvision_letter_robot.yaml` НЕ трогать — К, R4) и ACCEPTANCE 2.2. Оговорки брифа (спам `connect` при «без лимита» — замерить число строк лога в минуту на сим-стенде; `upsert` заменяет `params` целиком) — в отчёт.
  2. Бриф Б (C-101): `Services/device_hub/tests/test_no_private_driver_state.py` — литерал 71 + запись `"_clock": 1` в `_SEAMS` с комментарием; solo допустимо (1 файл, < 20 строк) — сказать вслух; инъекции (i)–(iii) из брифа с предсказаниями ДО запуска; ожидание `6 passed`.
  3. Красный C-72 (`test_robot_client_reads_growing_encoder`: «энкодер не вырос: first=0, second=0», повторён на Mac): Д2 передала тебе/владельцу `line_sim`; причина не искалась — investigator (haiku-инвентарь, затем opus), только диагноз, правку — отдельным слотом.
  4. T5.3e.5 (`robot_park_all` для `pre_stop`, C-60.b): сверить `git grep`, влито ли; если нет — бриф.
  5. Визит к роботу (если состоится): сверить `docs/handoffs/2026-11-15_day2-robot.md` с main; `devices.yaml` не копировать и REVIEW-5 не запускать без слова владельца.
ACCEPTANCE: `Plugins/hub/device_hub/tests` и `Services/device_hub/tests` зелёные (числа); инъекции совпали с предсказаниями или расхождение объяснено.
PIPELINE: «Task launch convention»; для п.1 — стадия 0 reviewer sonnet на тексте брифа, слепой tester; для п.2 стадии 3 и 5 обязательны; субагенты не коммитят.
BOUNDARIES: `Plugins/hub/device_hub`, `Services/device_hub`, `Plugins/sim/robot_host`, вкладка робота — твои. Не писать: PM/spawner/state_store (Ф), `Services/camera_device` (К), `hikvision_letter_robot.yaml` (К), блок `pult` (Пульт).
LOAD: координатор inspector-bottles-2b; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути.
COMMITS: `feat`/`fix`/`test`/`docs` + Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить, заявка файлом.
LIMITS: 2 итерации; без обещаний «успеем» — числа замеров.
REPORT: `docs/reports/<дата>_R2_lane.md` (≤ ~15 строк), по-русски, непустое «Открыто».
```

## Полоса Д2 — C-99 (первый слот писателя), затем C-93; C-36/A ждёт

```
ВКЛАДКА: Полоса Д2 · C-99 (утечка env в тестах), слот писателя выдан
ROLE: lead of lane Д2 (дефекты), реестр plans/queue/defects.md. Стадия 0 брифов C-99, C-93, C-36/A пройдена (`docs/reports/2026-11-21_lane-D2_stage0.md`, в main).
READ FIRST: docs/reports/2026-11-20_lane-D2_brief-C-99.md; docs/reports/2026-11-21_lane-D2_owner-questions-and-stand-task.md; docs/reports/2026-11-20_lane-D2_brief-C-93.md.
GOAL: C-99 в ветке и в заявке на слияние; C-93 и C-36/A подготовлены к слотам.
ЗАДАЧИ:
  1. C-99 — слот писателя ВЫДАН (только тесты и `conftest`, без пересечения с Ф/К/Пульт/Р2): слепой tester один раз ДО кода (бриф, 18 ключей env включая `MPF_APP_NAME`, `_WRITERS_RAN`), developer, инъекции с предсказаниями до прогона (17 из 18 на тексте брифа совпали), Opus-ревью перед main не нужен для тестовой правки — Sonnet-ревью, verdict с воспроизведением. Заодно строка в `docs/claude/OPEN_QUESTIONS.md` и дефект на утечку `INSPECTOR_LOG_DIR`/`INSPECTOR_PID_FILE` из `test_minimal_app_boots_headless` (`make test-fw`).
  2. C-93 (`std_facade._CACHE`, framework `logger_module`): R1+R2 одобрены (7 тестов), R3 (перенос `collect_now(refreeze=True)` в `pytest_runtest_logfinish`) — решение владельца В2; кода НЕ писать, пока Ф не освободил стенд и нет слота; Opus-ревью перед main.
  3. C-36/A: шаг 0 теста условия отмены CTO (`backend_ctl/probes/probe_c36_cancel_condition_live.py`, класс heavy, окно стенда ПОСЛЕ Ф и Пульт 6.5) — скрипт не написан; пишешь только после того, как CTO утвердил пороги (Р5) и F посчитана ДО прогона. PM-файл (`process_manager_process.py`) не трогать.
  4. Откат правок C-100 в дереве К (`Inspector_bottles--lane-K-4c`) — по слову владельца, не трогать.
ACCEPTANCE: C-99 — 66 passed, 2 skipped на радиусе брифа (число из брифа, пересчитать); красные вне реестра — регистрировать.
PIPELINE: «Task launch convention»; свой подкаталог в scratchpad на каждого агента (память `feedback_parallel_agents_need_own_scratch_dir`); субагенты не коммитят.
BOUNDARIES: не писать в `process_manager_process.py`, `launcher/spawner.py` (Ф), `Services/camera_device` (К), `Services/device_hub`, вкладку робота (Р2/Пульт).
LOAD: координатор inspector-bottles-2b; первое сообщение — имя сессии; ВКЛАДКА + имя; `machine_gate.sh` по абсолютному пути, heavy только в своём окне.
COMMITS: `test(...)`/`docs(defects)`, Why:/Layer:/Refs: plans/queue/defects.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; в main не коммитить, заявка файлом.
LIMITS: 2 итерации.
REPORT: `docs/reports/<дата>_lane-D2_C-99.md`, по-русски, непустое «Открыто».
```

## Полоса Н — observability-signal-contracts, срез 0 (только стадия 0 до слова координатора)

```
ВКЛАДКА: Полоса Н · observability-signal-contracts 0.1–0.3 (три контракт-теста), стадия 0
ROLE: lead of lane Н, plan plans/2026-11-21_observability-signal-contracts/ (APPROVED 2026-11-21, ветка `refactor/observability-signal-contracts`, ORDER строка 30: зона 1.0, «последняя в зоне»). Ответы В-1…В-4 даны (`a781e1061`).
READ FIRST: plan.md (цели 1–16), design.md §5 «Таблица владения» (вариант A, решение владельца) и «Пересечения» с `gui-service` 2.2, tasks/0.1–0.3, amendments.md, docs/reports/2026-11-21_observability-review.html (51 находка).
GOAL: контракт-тесты I1 «исход», I2 «свежесть», I3 «причинность» (12 passed во фреймворке, 10 passed в `backend_ctl`) — красные до починки экземпляров.
ДО СЛОВА КООРДИНАТОРА (слот писателя занят К, Р2, Д2): стадия 0 reviewer sonnet на тексте 0.1–0.3; если Task Level Senior+ — написать координатору (inspector-bottles-2b) ДО стадии 0 и получить номер N/6 пилота «стадия 0 в тень» (счётчик по шапке ORDER 3/6; сверить `docs/reports/2026-10-26_stage0-eval.md`), без номера — обычная стадия 0 на Sonnet; слепой tester ОДИН раз на механизм, worktree на коммите до кода. Кода в основных деревьях нет.
ПОСЛЕ слова: developer по 0.1 → 0.2 → 0.3, затем 0.4–0.13 по плану; heavy — только в окне.
ACCEPTANCE: литералы целей 1–16 плана; каждое свойство — break-injection с предсказаниями до прогона.
PIPELINE: «Task launch convention»; три роли авторов тестов; субагенты не коммитят.
BOUNDARIES: по таблице владения design.md §5; не трогать файлы Ф (`process_manager_process.py`, `launcher/spawner.py`, `state_store_module/state_proxy.py`), `gui-service` 2.2 — через `amendments.md` и вопрос владельцу; `plans/queue/ORDER.md` — не править (координатор).
LOAD: координатор inspector-bottles-2b; первое сообщение — имя сессии; ВКЛАДКА + имя в первой строке; `machine_gate.sh` по абсолютному пути.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-11-21_observability-signal-contracts/plan.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; в main не коммитить.
LIMITS: 2 итерации.
REPORT: `docs/reports/<дата>_observability-signal-contracts_0.1-0.3-stage0.md`, по-русски, непустое «Открыто».
```

---

## Вопросы владельцу (список с рекомендацией; решает владелец, где написано — CTO)

| # | Вопрос | Рекомендация координатора |
|---|---|---|
| 1 | Влить в main три docs-ветки: `docs/camera-w4-prep` (ответы по R4), `docs/r2-visit-prep-1120` (брифы Р2), `feat/camera-w4` (стадия 0 4.2a)? `git merge-tree` чисто у всех трёх | Да, одним заходом координатора; без них К и Р2 не видят свои исходные данные |
| 2 | День №1 / визит (≈ 22.11): состоится ли, есть ли железо (MVS, робот)? От этого зависят ORDER 25–28 | Подтвердить дату; без железа К и Р2 готовят документы и работают на симе |
| 3 | К, M2: камера отдаёт всегда BGR (mono8 → GRAY2BGR) вместо «gray для mono8» из записи 20.11 | Да, BGR: тип выхода — атрибут класса, проверяется до открытия камеры |
| 4 | C-36/A, Р1–Р5 (`docs/reports/2026-11-21_lane-D2_owner-questions-and-stand-task.md`): Р1 — O1 только после зелёного шага 0; Р2 — расходятся Д2 (WARNING при `reuse=false`) и CTO (ERROR) — решает CTO; Р3 — да; Р4 — сейчас ничего; Р5 — пороги относительно контроля утверждает CTO ДО прогона | Принять рекомендации Д2; Р2 и Р5 — к CTO |
| 5 | Откат правок C-100 в дереве К (`Inspector_bottles--lane-K-4c`, есть патч-копия) | Откатить после влития K-веток; сказать слово |
| 6 | Ф: Р1 (подпись пульта при `run_gate: false`), Р2 (`stop_allowed` для `None`, `""`, `0`, `[]`), В10, уровень WARNING «diverged» и защита собственных записей клиента, 2.2c (вариант CTO (б)) | Ответы дать до слияния коммита B; не блокируют стенд |
| 7 | Помощник «чтение узла» в framework + починка `io_debug_section.py:250`, `telemetry_view_model.py:258` до 1.0 | Да, задача Ф следующим слотом писателя (баг после П3) |
| 8 | Когда освобождать слот писателя полосе Н (observability, 16 задач среза 0): сейчас стадия 0 без кода, код — когда Р2 или Д2 закончит малую правку | Так, как записано в промте Н |
| 9 | Рабочее дерево: около 190 worktree (`agent-*`, `rs-*-tester`, `lane-f-*`, `cam-*`, `atlas-*`), часть грязная | Не удалять самим; отдельный проход с инвентарём — только по вашему слову |

## Что осталось открытым / ненадёжно

- Состояние собрано по git, ORDER и отчётам; ORDER отстаёт (строка 16, шапки Пульта), числа Ф и Д2 взяты из их отчётов, не пересчитаны.
- Ответы владельца по R4 в `docs/camera-w4-prep` я не открывал целиком (только список файлов и `--stat`); К читает сам.
- Стенд на Mac — `stand_gate` без `machine.lock`: очередность «Ф, затем Пульт, затем Д2 шаг 0» держится на их отчётах, не на замке.
- Пилот стадии 0 «в тень»: счётчик 3/6 взят из шапки ORDER от 27.10, свежее значение не проверял.
