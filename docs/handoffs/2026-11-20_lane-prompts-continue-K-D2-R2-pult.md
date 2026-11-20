# Промпты на продолжение полос К, Д2, Р2, Пульт (координатор inspector-bottles-fb, 2026-11-20)

Ф работает в своей сессии (`inspector-bottles-f1`). Каждый блок ниже вставлять в новый чат целиком. Ограничение: не больше трёх писателей — сейчас Ф, К и Р2 (только T1.4); Д2 и Пульт без кода, пока не освободится слот. Статус — из `git main` (последний коммит координатора `11c200f95`), шапки планов и `ORDER.md` отстают.

Решения владельца 2026-11-20: 2.8 после стенда; W4 камеры не сейчас; Д2 только Opus-ревью и стенд; Р2 ждёт (рядом с владельцем нет робота, камера — только симулятор, симулятор использовать можно, REVIEW-5 не запускать, `devices.yaml` не копировать); пауза 2.2 — стоп роботам на каждом вызове (влито); `tick_fails_limit` = 3; `run_locked_commands` камеры = `release_device` и `take_device`; формат кадра и дебайер решает К по симулятору (BGR).

## Полоса К — ключ `run_locked_commands`, документы readiness, мелкие остатки

```
ВКЛАДКА: Полоса К · camera_device после W3: 4c (ключ run_locked_commands) + хвосты
ROLE: lead of lane К, plan plans/2026-10-18_camera-device-service/. Статус из git main. 2.3c, 2.3d (`fd1016cf9`), docs W3 и решения владельца по 4.2a (`4af06448c`) уже в main.
READ FIRST: plans/2026-10-18_camera-device-service/tasks/4.2a.md (решения владельца 11-20, BGR); docs/reports/2026-11-19_camera-device-service_W3.md («Не сделано»); plans/2026-10-27_system-run-state/tasks/2.7d.md (этап 2 — ключ в рецептах камеры); docs/claude/OPEN_QUESTIONS.md (записи Ф про readiness камеры, находки ревью 2.2c 2–4, «stopping при auto_start»).
GOAL: до визита ≈ 2026-11-22 в main ключ `run_locked_commands: [release_device, take_device]` у узла камеры (этап 2 задачи 2.7d), документы камеры описывают readiness, три мелких остатка закрыты; кода W4 нет.
ЗАДАЧИ:
  1. Ключ `run_locked_commands: [release_device, take_device]` в рецептах, где есть узел камеры; тест, что в `running` обе команды отказывают, а вне `running` проходят; если `apply_params` и видимый оператору отказ через relay GUI не решены — не додумывать, записать вопрос в OPEN_QUESTIONS и согласовать с лидом Ф (его имя — первая строка его `ListAgents`; файл, не сообщение, если сессии нет).
  2. README/STATUS/DECISIONS `Services/camera_device`: описать readiness (сейчас 0 строк по `grep -i "readiness\|готовност"`), числа в STATUS поправить по `grep -c "def test_"`.
  3. Мелкие остатки: утечка значения в DEBUG (`registers/manager.py:222`), `bindings()` вне `try` (`plugin_base.py:697`).
  4. Подготовка дня №1 без камеры: набор вопросов `docs/handoffs/2026-11-15_day1-camera-checklist.md`, сухой прогон записи кадров на симуляторе, команды и ожидаемый вывод — документом.
  5. W4 (4.2a, 4.2b, 4.3, 4.4, 6.1, 6.3) НЕ начинать: слово владельца «не сейчас». Выбор «stopping при auto_start» (ждёт владельца/CTO) не решать.
PIPELINE: «Task launch convention»: стадия 0 reviewer sonnet на тексте задачи 1, слепой tester один раз на механизм ДО кода, инъекции с предсказаниями до прогона, ревью (Opus только перед main), `effort` по сложности; субагенты не коммитят.
BOUNDARIES: `Services/camera_device`, `Services/hikvision_camera`, рецепты узла камеры — К. Не писать в `process_manager_process.py`, `launcher/spawner.py`, `state_store_module`, `bindings.py` (Ф); `Plugins/hub/device_hub`, вкладку робота (Р2/Пульт).
LOAD: координатор `inspector-bottles-fb` (проверь первую строку `ListAgents`); первое сообщение — своё имя сессии. Mac, `machine.lock` нет: тесты через `machine_gate.sh` по абсолютному пути из `git rev-parse --path-format=absolute --git-common-dir`, heavy только в своём окне; свой `INSPECTOR_PID_FILE`, `BACKEND_CTL_PORT`. В `main` не коммитить: слияние делает слот `lane-f-merge` по запросу файлом.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-18_camera-device-service/plan.md; `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; stage явных путей; `git branch --show-current` перед коммитом.
LIMITS: 2 итерации, на третьей вверх; красный, которого нет в `plans/queue/defects.md`, регистрировать.
REPORT: по-русски, числа, непустое «что осталось открытым / ненадёжно»; `docs/reports/<дата>_camera-device-service_4c.md`; таблица «готово / в работе / блокер».
```

## Полоса Д2 — диагностика C-36, реестр красных (без кода)

```
ВКЛАДКА: Полоса Д2 · C-36 диагностика и реестр, слот писателя не занят
ROLE: lead of lane Д2 (дефекты), реестр plans/queue/defects.md из main. В main: красные PM и prototype-тесты (`92e4a2250`), диагностика C-93 и C-99 (`2d656c491`).
READ FIRST: plans/queue/defects.md (C-36, C-91, C-92, C-93, C-99, C-100); docs/reports/2026-11-19_lane-D2_pm-tests-macos.md; docs/claude/OPEN_QUESTIONS.md.
GOAL: слот писателя занят Ф, К и Р2 — кода не пишешь. Подготовить правки так, чтобы любая шла в работу сразу, когда слот освободится или владелец скажет.
ЗАДАЧИ (только diagnose-and-report и документы):
  1. C-36 (system-очередь ребёнка гибнет после kill, ~0,4 % на kill; нужна для приёмки CTO фазы ProcessManager, ORDER 6а): investigator (haiku-инвентарь логов первым, потом opus) — воспроизвести детектором «routing.refresh … потеряна», отчёт с причиной; fix-forward в framework НЕ делать.
  2. C-99 (правка теста/conftest, `test_run_app_prototype.py:62-63`) и C-93 (`std_facade._CACHE` в framework `logger_module`) — написать брифы для developer: файлы, тест, ожидаемый красный до правки, break-injection. Не кодить.
  3. Две красные `Services/device_hub/tests/test_no_private_driver_state.py` (`test_tests_do_not_touch_driver_state_fields`, `test_seam_whitelist_is_literal`, литерал 64) занести в `plans/queue/defects.md` (красные и на базе, сейчас не зарегистрированы).
  4. Пересчёт C-100 (`values_at_x` читает `getData()`): бриф, не код.
  5. П.4 (контракт `PluginRegistry.discover()`) не открывать — владелец решил: только Opus-ревью и стенд.
PIPELINE: investigator (opus) для причины, haiku-агент для инвентаря; субагенты не коммитят.
BOUNDARIES: не писать в `process_manager_process.py`, `launcher/spawner.py` (Ф), `Services/camera_device` (К), `Services/device_hub`, вкладку робота (Р2/Пульт).
LOAD: координатор `inspector-bottles-fb`; Mac, `machine.lock` нет: тесты и прогоны через `machine_gate.sh` (абсолютный путь), heavy только в своём окне после окна Ф; свой `INSPECTOR_PID_FILE`.
COMMITS: только `docs(defects)`; Why:/Layer: docs/Refs: plans/queue/defects.md; `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; stage явных путей; слияние делает слот `lane-f-merge`.
LIMITS: 2 итерации; красный, которого нет в `defects.md`, регистрировать.
REPORT: `docs/reports/<дата>_lane-D2_<задача>.md`, по-русски, числа, непустое «что осталось открытым / ненадёжно».
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: слот писателя под C-99 и C-93 (рекомендация координатора: C-99 первым, как только слот свободен; C-93 после окна стенда Ф, Opus-ревью перед main).
```

## Полоса Р2 — T1.4 (код) и подготовка визита (документы)

```
ВКЛАДКА: Полоса Р2 · T1.4 диапазоны APARAM → codegen + подготовка визита к роботу (≈ 2026-11-22)
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md. Слот писателя — только под T1.4; остальное документы.
READ FIRST: docs/handoffs/2026-11-15_day2-robot.md, docs/reports/2026-11-15_R2_lane.md, docs/handoffs/2026-11-15_R2-T5.3e.6-merged.md, plans/robot-protocol-v2/plan.md (T0.3, T1.4, T4.0, T5.5); docs/claude/OPEN_QUESTIONS.md.
СЕЙЧАС: T5.3e.1–6, C-56, D1, D2 влиты; T0.3 `[BLOCKED]` (GATE-1 — `pc_probe.py all` на контроллере), T4.0 `[PENDING]`. Рядом с владельцем нет робота, камера — только симулятор; симулятор использовать можно. REVIEW-5 не запускать, `data/devices.yaml` и `robot/` не копировать — без слова владельца.
GOAL: к визиту комплект готов (команды, ожидаемый вывод, что записывать, что нельзя без владельца) и T1.4 в main (обязательно до T4.0, железа не требует).
ЗАДАЧИ:
  1. T1.4: диапазоны APARAM → codegen по плану; стадия 0 reviewer sonnet на тексте Task, слепой tester ДО кода, инъекции с предсказаниями, ревью (Opus перед main), стенд на симе числами.
  2. Сверить `docs/handoffs/2026-11-15_day2-robot.md` с `main` на 2026-11-20 (после слияний камеры W3, run-state 2.2/2.7/2.9, S5): что устарело — исправить документом.
  3. Проверить чтением, что хаб без переноса `devices.yaml` даёт понятную ошибку, а не молчит (стенд Ф 20.11 показал: реестр читается из `.claude/worktrees/data/devices.yaml`, стенды разных worktree его делят — записать находку).
  4. Остаток C-60.b / T5.3e.5 (`robot_park_all` для `pre_stop`): сверить по `git grep`, влит ли; если нет — бриф под слот писателя.
  5. Вход REVIEW-5 подготовить (по плану), запуск — только по слову владельца. Решения (а)–(д) из `docs/reports/2026-11-15_R2_lane.md` — список вопросов владельцу с рекомендацией каждого.
PIPELINE: «Task launch convention»; документы — `tech-writer` sonnet, инвентари — haiku; субагенты не коммитят.
BOUNDARIES: `Plugins/hub/device_hub`, `Plugins/sim/robot_host`, `Services/device_hub`, вкладка робота — их файлы; не писать в `Services/camera_device` (К), `process_manager_process.py`, `launcher/spawner.py` (Ф). Устаревший текст про `start_worker` (`Plugins/sim/robot_host/plugin.py:481-482`, `tests/test_v2_real_worker_manager.py:8,203-204`) — только вместе с кодовой задачей. Пауза 2.2 (стоп на каждом вызове, ADR-PH-004) — файл Ф/hub, не переделывать.
LOAD: координатор `inspector-bottles-fb`; Mac, `machine.lock` нет: тесты через `machine_gate.sh` (абсолютный путь); железо не трогать.
COMMITS: код T1.4 — `feat(...)`, документы — `docs(...)`; Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md; `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; stage явных путей; в `main` не коммитить, слияние делает слот `lane-f-merge`.
LIMITS: 2 итерации; не обещать «успеем» — только числа замеров на симе.
REPORT: `docs/reports/<дата>_R2_lane.md` (≤ ~15 строк), по-русски, непустое «что осталось открытым / ненадёжно».
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: слово на визит; перенос `devices.yaml`; REVIEW-5 у cto; решения (а)–(д).
```

## Полоса Пульт — фаза 6: ревью плана (без кода)

```
ВКЛАДКА: Пульт · фаза 6 «Пульт оператора 1.0» (ORDER 15–17, β8): ревью плана, код — после слова владельца
ROLE: lead of lane Пульт, plans/pult-control-panel.md Phase 6 — в ветке `docs/pult-operator-phase6` (`9ca6e0ead`, в main НЕ влита, отстаёт от main; читать `git show docs/pult-operator-phase6:plans/pult-control-panel.md`).
READ FIRST: Phase 6, «Связи», «Открытые вопросы», «Что осталось ненадёжно»; docs/reports/2026-11-15_R2_lane.md (smoke 6.0, backend-путь: 59 тестов зелёные); plans/release-1.0/design.md §3 β8; `Plugins/processing/word_layout`, `Plugins/io/robot_io`; в main уже есть S5 пульта (`b778b9503`: подпись «гейт выключен», ОСТАНОВИТЬ по `stop_allowed`, набор степеней из фреймворка) — сверь Phase 6 с ним.
ЭТАП 0 (код не писать, слот не занимает):
  а) Стадия 0 reviewer sonnet (`run_in_background: false`) на тексте Phase 6: DESIGN, FILES, REDS, зависимости; кнопки ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать — главное окно, полоса Ф, пульт их не дублирует (решение Ф по В4: «Квитировать» кнопкой в виджете, Task 2.3 сделано); рецепт β правит К.
  б) GUI-путь smoke 6.0 не проверен: qt-mcp `CONNECTION_CLOSED` — проверить подключение у себя, иначе backend_ctl + тесты вкладки.
  в) Список В1–В6 владельцу с рекомендацией каждого, коротко. План в main — отдельным `docs(plans):` по слову владельца.
ПОСЛЕ слова владельца: 6.0 → 6.1 вертикальный срез «Слово» → 6.2–6.6, когда освободится слот писателя.
BOUNDARIES: вкладка «Пульт», `Plugins/hub/device_hub` — свои; главное окно и кнопки run-state (Ф), `Services/camera_device` (К), рецепт β (К, R4) — не писать.
PIPELINE/LOAD/COMMITS/LIMITS/REPORT: как в блоке Р2 (только документы; `machine_gate.sh`; `docs(...)`; отчёт `docs/reports/<дата>_pult_<задача>.md`, по-русски, непустое «что осталось открытым / ненадёжно»).
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: В1–В6 плана; В4 (дублировать ли кнопки run-state в пульте).
```
