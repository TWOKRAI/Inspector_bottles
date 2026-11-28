# Plan: состояние работы системы — рецепт поднят, ЗАПУСТИТЬ по готовности, ОСТАНОВИТЬ

- **Slug:** system-run-state
- **Дата:** 2026-10-27
- **Статус:** APPROVED 2026-11-02 (лид, по вердикту cto Task 0.1: ACCEPT WITH CONDITIONS, условия внесены)
- **Plan review:** reviewer ×2 — CHANGES REQUESTED (18 + 5, внесены); teamlead express (эскалация) — Б1–Б4 внесены; cto Task 0.1 — ACCEPT WITH CONDITIONS, условия внесены; формального APPROVED третьего раунда reviewer нет (cto: не нужен, правки текстовые)
- **Ветка:** `feat/system-run-state` (предложение; заводит лид)

## Что где живёт

| Что | Где |
|---|---|
| Контракт: цели, задачи одной строкой, бюджет, вопросы | этот файл |
| Факты (file:line), машина состояний, готовность, START/STOP, квитирование, соседи, риски | [`design.md`](design.md) |
| Стандарты (PackML, NE 107, IEC 60204-1, ISA-18.2) — design.md §9 | [`standards.md`](standards.md) |
| Тело задачи | `tasks/<id>.md` |
| Изменения после approve | [`amendments.md`](amendments.md) |

## Контекст

Требование владельца 2026-10-27 (строка 14а `plans/queue/ORDER.md`): на старте рецепт прогружается, но не работает;
система поднимает все узлы, получает от каждого узла рецепта готовность и только тогда разрешает ЗАПУСТИТЬ; есть
ОСТАНОВИТЬ. Сегодня boot сразу переводит плагины в `RUNNING` и источники шлют кадры (`plugin_orchestrator.py:197`,
preroll ADR-PMM-034 ≤ 10 с). Есть только барьер готовности процессов (`_wait_processes_ready`) с liveness-фолбэком;
состояния работы системы и команд старт/стоп нет (`git grep`, design.md §2). Принцип 6: START/STOP — команды бэкенда
(PM), GUI/пульт/`backend_ctl` только вызывают.

## Цели (вехи)

1. **Ф0 — архитектура:** вердикт `cto` по design.md §3 и вопросам К1–К7; ответы владельца В1–В8 получены 2026-11-02.
2. **Ф1 — framework:** PM владеет `booting → not_ready/ready → running → stopping → ready`, `fault`; одно `mp.Event`
   работы гейтит источники и зовёт существующие хуки `pause/resume`; готовность — самоотчёт плагин → процесс → система
   по набору рецепта, молчание = не готов, причины по NE 107 в `system.run.*`; preflight C-55b — причины.
   Вертикальный срез 1.1: `backend_ctl system.run.start` → кадры идут, `stop` → кадры стоят. Авария держится до
   квитирования `system.run.ack` (1.7); процесс с флагом `run_auto_restart` перезапускается без аварии (1.8, прочтение В9 = (а), владелец 2026-11-02).
3. **Ф2 — прототип:** `run_gate: true`, готовность устройств/камеры/модели, стоп ленты, кнопки GUI ЗАПУСТИТЬ /
   ОСТАНОВИТЬ / Квитировать, живая приёмка.

## Out of scope

- Аппаратный аварийный останов (e-stop) — функция безопасности, не программная (standards.md §9.3).
- Held/Suspended (В8: «нет диска» — индикатор, не состояние), режимы PackML, OPC UA (design.md §7).
- Отдельный статус «рецепт загружен» (В1).
- Логика «домой» робота (T5.3e) и сама точка `pre_stop` (gui-graceful-close 1.4) — только переиспользование.
- Кнопки пульта (строки 15–17 ORDER) — пульт вызывает `system.run.*` (вкл. `system.run.ack`) в своём плане. (2026-11-21: кнопки ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать — виджет `RunControlWidget` главного окна, S5 `b778b9503`; Phase 6 пульта (`plans/pult-control-panel-phase6.md`) их не дублирует; В4 для пульта — на подтверждении владельца)
- Правка барьера `_wait_processes_ready` и его liveness-фолбэка.

## Бюджет

| Задачи | Агенты | Оценка |
|---|---|---|
| 0.1 | cto (fable) | ~0,2M |
| 1.1, 1.2, 1.3 | tester (sonnet, слепой) + teamlead (opus) + reviewer (sonnet) | ~0,7–0,9M на задачу |
| 1.4, 1.5, 1.6 | teamlead/developer + reviewer (sonnet) | ~0,4–0,6M на задачу |
| 1.7, 1.8 | tester (sonnet, слепой) + teamlead (opus) + reviewer (sonnet) | ~0,4–0,6M на задачу |
| 1.9 | tester (sonnet, слепой) + developer (sonnet) + reviewer (sonnet) | ~0,3–0,5M |
| 2.1, 2.2, 2.3 | developer (sonnet) + reviewer (sonnet) | ~0,3–0,5M на задачу |
| 2.4 | tester + стенд heavy, опись — haiku | ~0,3M |
| 2.5 | tech-writer + reviewer(express) | ~0,15M |
| Стартовый контекст | ~32 участника × ~56k | ~1,8M (в строки выше не входит) |
| Ревью ветки перед merge | reviewer (opus) | ~0,4M |
| **Итого** | 15 задач | **~8,2–10,6M токенов** (строки 5,95–8,35M + 1,9M + 0,4M), Opus ~8 запусков: teamlead ×7 (1.1–1.4, 1.6–1.8) + ревью ветки ×1 (оценка) |

## Порядок выполнения

Вход Ф1: LSO 1.10, 1.11 и C-60 влиты (`ORDER.md`, строки 36–37). C-55b влита версией v3 без хука `preflight` (2026-11-12, `amendments.md` §4) — для 1.2 ждать нечего, у 1.6 источника причин нет (переписать на её стадии 0); `pre_stop.py` в `main` с 2026-11-09 (для 1.4 условие снято). Ждём влития полос Ф (C-64/C-79, `process_manager_process.py`) и Д (1.10, `frontend/app.py`) для кода Ф1 и 2.3. Код стартует
только после перечисленных merge, номера строк в design и tasks сверять по HEAD.

**Порядок на файле PM — строго последовательно, один писатель:** 1.1 → 1.2 → 1.9 → 1.3 → 1.3b → 1.4 → 1.7 → 1.5 → 1.6 → 1.8
(1.9 не трогает файлы PM).
Критический путь: gui-graceful-close (0.1 → 1.1 → 1.2, 1.3 → 1.4) → наша 1.4 → 1.7 → 1.8, 2.3, 2.4. Task 1.9 заведена по вердикту К6
(резка потока на потребителе); строка про `run_gated: false` у камеры — в 2.1.
Заметки о владельцах: Task 2.1 (`app.yaml`, драйвер `backend_ctl`) и 2.3 (главное окно, `frontend/app.py`) — через
координатора и полосу Д; 2.2 пишет в `Plugins/hub/device_hub` (Р2, один файл на шаги 1 и 4) и `word_layout` (С) — через
координатора.

### Ф0 — архитектура
- Task 0.1: вердикт `cto` по машине состояний, сигналу готовности, механизму `run_event`, К1–К7 [DONE 2026-11-02 — вердикт cto ACCEPT WITH CONDITIONS, условия внесены; ответы владельца В1–В8 получены 2026-11-02]

### Ф1 — framework
- Task 1.1: **[VERTICAL SLICE]** `run_event` PM → ребёнок → `SourceProducer`; `system.run.start/stop/status`; `ready ↔ running`; `run_gate` **[РЕАЛИЗОВАНА 2026-11-09; стадии 3–5 пройдены 2026-11-12 (инъекции 16/16, стенд 0/91/0/90, ревью APPROVED); слияние в main — см. отчёт docs/reports/2026-11-12_system-run-state_1.1.md]** **[DONE df6aa3f]** (после 0.1, merge LSO 1.10)
  - **Module contract:** public-api-change
- Task 1.2: самоотчёт готовности — хук `readiness()`, лист `processes.<n>.readiness`, наблюдатель `run_event` → `pause/resume` [DONE 506eea2] (после 1.1; C-60 влита; **посылка «merge C-55b» устарела 2026-11-12** — C-55b влита версией v3 без хука `preflight`/`PreflightFinding`, `plugins/base.py` не меняла: ждать нечего, см. `amendments.md` §4)
  - **Module contract:** public-api-change
- Task 1.9: `PluginRunner.call_process` в `PAUSED` — bypass; `PAUSED` перестаёт быть ярлыком (вердикт cto К6) [DONE 506eea2] (после 1.2; до 1.3)
  - **Module contract:** impl-only
- Task 1.3: агрегат PM — набор рецепта, молчание = не готов, причины, `booting/not_ready/fault`, непрерывная оценка [DONE 506eea2] (после 1.2, 1.9)
  - **Module contract:** impl-only
- Task 1.3b: шкала загрузки — контракт `system.progress.<id>`, помощник `ProgressTracker`, издатель `boot` в PM (требование владельца 2026-11-12, `amendments.md` §5) [DONE 506eea2] (после 1.3; стадия 0 р.1 пройдена, v2 — срез 1.0, `amendments.md` §7)
  - **Module contract:** public-api-change
- Task 1.4: STOP — `pre_stop` → снять событие → ждать `paused`; авария без `pre_stop` [DONE 506eea2] (после 1.3, gui-graceful-close 1.4)
  - **Module contract:** impl-only
- Task 1.5: `topology.apply` в `running` — отказ `running`; после применения — `booting`, не `running` [DONE 506eea2] (после 1.3)
  - **Module contract:** impl-only
- Task 1.6: preflight C-55b при `run_gate` — причины `not_ready` вместо отказа boot [DONE 506eea2] (после 1.3; **источник причин устарел 2026-11-12:** хука `preflight`/`PreflightFinding` в `main` нет — C-55b v3: `error` идёт в плоскость ошибок, health `degraded`, регистр `last_error`, старт не блокируется; 1.6 переписывается на стадии 0 — причины брать из `readiness()` (1.2), health и `last_error`)
  - **Module contract:** public-api-change
- Task 1.7: квитирование — `system.run.ack`, `fault` держится до него, START в `fault` отказан (В4) [DONE 506eea2] (после 1.4)
  - **Module contract:** public-api-change
- Task 1.8: опциональный автоперезапуск — флаг процесса `run_auto_restart` в рецепте, падение с флагом не авария (В6) [DONE 506eea2] (после 1.3, 1.7; прочтение В9 = (а) — владелец 2026-11-02)
  - **Module contract:** public-api-change

### Ф2 — прототип
- Task 2.1: прототип включает `run_gate: true`; стенды и e2e шлют `system.run.start` [DONE f328121: коммит A ecf2914, коммит B (run_gate: true) f328121; хвосты входов без --autostart — OPEN_QUESTIONS 2026-11-21] (после 1.3, 1.5)
  - **Module contract:** n/a
- Task 2.2: `readiness()`/`pause()` у устройств, камеры, модели, ленты [DONE 8ff4fd1] (после 1.2, T5.3e)
  - **Module contract:** impl-only
- Task 2.3: GUI — ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать, состояние, причины, индикаторы [DONE 4a73cdc] (после 1.3, 1.7)
  - **Module contract:** impl-only
- Task 2.6: окно начальной загрузки — отдельный процесс-заставка с самого запуска, проект v3 (`tasks/2.6.md`, `amendments.md` §13); в 1.0 шкала загрузки рецепта = `boot`; `recipe_load` при смене — 2.0 (требование владельца 2026-11-12, `amendments.md` §5, §7) [DONE 1b3e29b48] (после 1.3b, 2.3; v3 — стадия 0 впереди)
  - **Module contract:** impl-only
- Task 2.4: живая приёмка на стенде с числами + матрица инъекций лида [PENDING] (после 1.4–1.8, 2.1–2.3, 2.7–2.9, 2.8f)
  - **Module contract:** n/a
- Task 2.5: ADR и карты — PMM, process_module, MODULES_RESPONSIBILITY_MAP [DONE 555a72724] (в ADR после закрытия 2.4 и C-125 дописать две фразы)
  - **Module contract:** n/a

### Ф2 — правки до железа (решение владельца 2026-11-16, срок 2026-11-22; тексты — `tasks/`)
- Task 2.7: PM — чистый `run_state` (`check_function` не прячется), `RunConfig` + `run_view()`, автостарт один раз за boot, флаг `run.py --autostart`; файл `tasks/2.7.md` (срезы S3a, S3b1, S3b2, S3c, S3c′, S3doc) [DONE 85a0521; приёмка на стенде открыта] (после 1.11, 3.3)
  - **Module contract:** public-api-change
- Task 2.7d: запрет команд плагина в `running` — второй `RunFlag` `run_active`, ключ плагина `run_locked_commands`; файл `tasks/2.7d.md` [DONE 85a0521] (после 2.7 S3b1 → S3c)
  - **Module contract:** public-api-change
- Task 2.8a: копия клиента хранит листья (read-model, `_cache_put`, `telemetry_sink`, `backend_ctl`), проекция при привязке (П3); файл `tasks/2.8a.md` [DONE a267360]
  - **Module contract:** impl-only
- Task 2.8: проекция состояния на шаблон в сторе — replay и живая подписка узла (S1 + П2); файл `tasks/2.8.md`; правило отката CTO: четыре условия до конца 2026-11-19 [DEFERRED 2.0 — владелец 2026-11-26, decisions.md; в 1.0 запасной ход] (после 2.8a)
  - **Module contract:** public-api-change
- Task 2.8f: запасной ход вместо 2.8 для 1.0 — GUI собирает узел состояния из листовых дельт (маркер конца пачки, `GuiStateBindings`); файл `tasks/2.8f.md` [DONE b91a5879f] (после 2.8a)
- Task 2.2d: индикаторы «слабое распознавание» и «нет диска» отдельным подключаемым пакетом; файл `tasks/2.2d.md` [DONE 98daa4b41]
- Task 2.2e: предупреждения «кадры не принимаются» и «обработка стоит» (ADR-PM-065); файл `tasks/2.2e.md` [DONE ecdca7f18]
- Task 2.10: вне `running` кадр только на display превью, остальные — плашка; файл `tasks/2.10.md` [DONE 889491c80]
- Task 2.11: метка `paused_by` у кадра, прошедшего мимо обработки (ADR-PM-066); файл `tasks/2.11.md` [DONE 889491c80] (после 2.10)
- Task 2.12: вкладки устройств разворачивают конверт ответа; «Изменить» не теряет настройки (C-117); файл `tasks/2.12.md` [DONE 6aa7d0dad]
  - **Module contract:** impl-only
- Task 2.13: во время рисования ПЧ не принимает пуск и смену частоты, пределы из рецепта (C-125); файл `tasks/2.13.md` [PENDING]
  - **Module contract:** impl-only
- Task 2.14: заставка не уходит по таймауту, пока шкала загрузки растёт (C-130); файл `tasks/2.14.md` [PENDING]
  - **Module contract:** impl-only
- Task 2.9: политика готовности узла `readiness: {hold_s, severity}` (S2, коммит A); файл `tasks/2.9.md` [DONE 85a0521] (после 1.2)
  - **Module contract:** public-api-change
- Task 2.9b: боевой рецепт — «модель не загружена» блокирует СТАРТ (YAML, литерал сим-теста, golden); файл `tasks/2.9b.md` [DONE 7410b16] (после 2.9, 2.2b)
  - **Module contract:** impl-only
- Task 2.2a2: возраст факта соединения, `pause_action` драйвера, параллельный `pause_all` (S4a «Services», S4b «plugin»); файл `tasks/2.2a2.md` в ветке `feat/run-state-2-2` [DONE 8ff4fd1] (после 2.2a)
  - **Module contract:** impl-only

### Ф3 — после 1.0 (владелец 2026-11-15)
- Task 3.2: разбиение `process_manager_process.py` (6493 строки) на пакет `process/pm/` + чистка комментариев и docstring без ссылок на фазы и задачи; чистый перенос, поведение не меняется (закрывает C7; дизайн — `reports/pm-split.design.md`) [PENDING] (после тега 1.0, после слияния правок ревью Ф1 и веток, правящих PM-файл)
  - **Module contract:** impl-only
  - Номер 3.2: 3.1 в плане занят переносом gui-graceful-close в 2.0 (журнал 2026-11-09).
  - **Условия старта:** тег 1.0 поставлен; правки ревью Opus (M1–M5, m1–m5) слиты; ветки, правящие PM-файл, слиты или заморожены на время переноса; окно машины выдано координатором; шаблон docstring и ответы на шесть вопросов `pm-split.design.md` §12 согласованы владельцем.
  - **Правило до старта 3.2:** новую логику PM пишут отдельным файлом рядом (как `process/run_state.py`), а не в класс `ProcessManagerProcess`; комментарии в самом PM-файле не чистят — их чистит 3.2 одним проходом.

### Ф1+ — правки свежего ревью Opus (владелец 2026-11-15: «сделай как лучше и как полагается»)
- Task 1.10: флаг работы без межпроцессного замка вместо `mp.Event` (F3/С3 свежего ревью; текст — `tasks/1.10.md`; стадия 0 прошла, CHANGES REQUESTED применено; далее слепой tester → реализация → инъекции → стенд `kill -9` в окне машины → ревью) [DONE b5cd6d8: F3 доказан тестами и инъекциями, не стендом — decisions.md 2026-11-26] (до слияния в main)
  - **Module contract:** public API (`RunFlag`)
- Сделано в ветке `fix/run-state-phase1-review`: F1 (С2 форма листа на входе), F2 (С1 итог `settled` гарантирован), F4 (С4 снятие пометки рестарта), N3 (С7), регресс N2 — отчёты `docs/reviews/2026-11-15_fix-{A3,B3}.md`.

- Task 1.11: остатки итоговой проверки teamlead (`reports/phase1.review-teamlead-final.md`): Q1 (поток `run-fault-stop` не стартовал — итог ставится только для STOP, `ack` в `fault_stopping` навсегда) — ВЛИТ (`b74783413`); Q2 (`_run_ready` обновляет только такт: START сразу после `settled` + один сбойный такт → `fault`), Q3 (START и `ack` при исключении оценки бросают вместо отказа), A6 (`_run_stale_s()` внутри `_evaluation_failed` теряет такт) [DONE d859338: Q1 b74783413, Q2/Q3/A6 d859338; A1–A5 — в 3.7] (после слияния; Q1 влит; задача — `tasks/1.11.md`)
  - **Module contract:** impl-only
- Советы A1–A5 итоговой проверки (мёртвый фильтр в `run_state.evaluate:94`, причина «оценка не удалась» строится в двух местах с разным `source`, докстринг `readiness_reason_is_valid`, негодный лист не пишется в журнал PM, `_eval_fail_since` не объявлен на классе) — вместе с 3.7 [PENDING]

### Ф3 — советы свежего ревью, отложенные (источник — `reports/phase1.review-opus-fresh.md` §7)
- Task 3.3 (С5): внеочередной heartbeat при смене готовности (`push_if_paused_changed` → `push_if_changed`; подпись `(paused, ready, блокирующие причины)`, антидребезг 0,5 с). Снимает задержку доставки СМЕНЫ готовности 1,99–5,68 с (свежесть неизменного листа при заморозке — не цель, C1/3.4). Новый риск «fault на ходу» — решение владельца (`tasks/3.3.md` «Риск»). Новый механизм: слепой tester, матрица, стенд с замером. Лид 2026-11-16: делать до живой приёмки 2.4, отдельной веткой; слияние до/после тега 1.0 — владелец [DONE 762a112] (`tasks/3.3.md`)
- Task 3.4 (С6): срок молчания задаёт отправитель — поле `stale_after_s` в снимке, PM берёт `min(max(value, floor), ceiling)`; нет поля — как сейчас [PENDING] (после 1.0)
- Task 3.5 (С8): `paused` подтверждается снимком, посчитанным после снятия события (`t_clear`; `_paused_pending` принимает лист с `at >= t_clear`) [PENDING] (после 1.0)
- Task 3.6 (С9): номер воплощения выдаёт PM (`incarnation` в kwargs, эхо в heartbeat) вместо pid ОС; не нужен опрос реестра на каждом heartbeat; Windows-повтор pid [PENDING] (после 1.0; расширение контракта heartbeat — вердикт C11 уже дан: cto не нужен)
- Task 3.7 (С10): мелочи — дроссель `log_error` в `_process_alive`/`_supervisor_gave_up`; классовые изменяемые умолчания (`_run_unconfirmed`, `_run_down_since`) в `__init__`; текст отказа apply в `shutting_down` в документе 1.5; решение по сбою оценки на тике `running` (сейчас исключение идёт в цикл монитора; перевод в `fault` строже — решение владельца); из ревью 1.11 (`reports/1.11.review.md`): единое правило лога текста исключения (`_evaluation_failed` пишет `{type}: {exc}`, START/`ack` — только тип), `hazards.py:198` не охраняет запись `_run_ready` на `ack`, `start_allowed` True до 15 с при показанной причине `failure`, `_run_stop_timeout` без дедупликации WARNING, `get_config` без охраны на `run_restart_grace_s`/`restart_policy` [PENDING] (после 1.0)
  - **Module contract:** impl-only (3.3–3.7)

## Гейты

- S1′: владелец (В1–В8, закрыто 2026-11-02) → reviewer `MODE: plan` → `cto` (Task 0.1) → approve.
- Каждая Task Ф1: REDS до правки `src`, break-injection, reviewer (sonnet: IPC, потоки, жизненный цикл; Opus — только
  ревью ветки перед merge и вердикты по живым дефектам, `.claude/CLAUDE.md`).
- Ф1 целиком — к приёмке фазы PM (строка 6а ORDER) не привязана, но `cto` смотрит её при S7 этого плана.

## Связи (двусторонние — обратные ссылки ставит лид, этот план других файлов не правит)

- `plans/lifecycle-stop-ownership.md` (1.10, 1.11, C-60) — владелец файлов PM и `plugins/base.py`; берём исполнитель
  и честный стоп.
- `plans/2026-10-20_gui-graceful-close/` Task 1.4 — точка `pre_stop`; STOP и shutdown делят её.
- C-55b (`plans/word-layout/tasks/C-55b.md`, полоса С) — находки preflight → причины.
- `plans/robot-protocol-v2/` T5.3e — «домой» как шаг `pre_stop`.
- `plans/pult-control-panel.md` (строки 15–17) — кнопки пульта вызывают `system.run.*`. (план продолжен в `plans/pult-control-panel-phase6.md`; кнопки run-state пульт не дублирует)

## Решения и вопросы

Полный текст разделов вынесен в [`decisions.md`](decisions.md) (задача PS1, бюджет 32 КБ): решения владельца В1–В8, закрытые В9 и В10, вопросы CTO К1–К7 и журнал решений. Текст и нумерация там не менялись; ссылки на номера работают как прежде.

- **Решения владельца В1–В8** (закрыто 2026-11-02, `plans/queue/decisions.md` №26; не пересматривать). Например, В1 — оператор видит «поднимается» → «готов» → «работает»; В4 — кнопка «Квитировать», команда `system.run.ack` (Task 1.7).
- **Вопрос владельцу В9** (закрыт 2026-11-02). Ответ (а): падение процесса с флагом `run_auto_restart` — не авария. Блокировал Task 1.8.
- **Вопрос владельцу В10** — закрыт 2026-11-26: два разных текста («нет диска», «слабое распознавание»), сделано Task 2.2d.
- **Вопросы CTO К1–К7** (Task 0.1). Ответ cto отмечен у К4 («нет»); статус остальных ответов — в `decisions.md`.
- **Журнал решений (decisions log)**, 2026-10-27 — 2026-11-21. Последняя запись — сверка шапок по git: влито целиком 20 из 32 задач (с 0.1).
