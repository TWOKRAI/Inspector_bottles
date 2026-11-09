# Ревью стадии 0 — Task 1.4m (манифест `pre_stop` прототипа)

- **Режим:** `MODE: plan`, один файл `plans/2026-10-20_gui-graceful-close/tasks/1.4m.md` (не закоммичен). Раунд 1 из 2.
- **Дерево:** `main` = `a63f5cbc1` (после `09b60018a` менялись только atlas-файлы; `git diff --stat 09b60018a HEAD -- multiprocess_prototype multiprocess_framework Plugins Services` пуст). Чтение, `git grep`, `Read`. Тесты и стенд не запускались, в репозитории ничего не правилось.
- **Вердикт: CHANGES REQUESTED.** 3 блокера, 3 major, 6 minor. Механика DESIGN сходится с кодом; ломают задачу пропущенные файлы и живая приёмка, которую на macOS нельзя выполнить как написана.
- memory hits: `scripts/memory/search.py pre_stop park devices orchestrator_config` -> 2 файла (`feedback_status_snapshot_lags_program_done.md`, `project_switch_live_survivor.md`), к задаче не относятся.

## 1. Проверка якорей и посылок (п. 1-3, 7 задания)

| Посылка | Результат | Где |
|---|---|---|
| PM читает `pre_stop` из `get_config` | верно | `process_manager_process.py:706`; `spawner.py:95-96` `process_config.update(orchestrator_config)`; `ProcessConfiguration.get_process_config` отдаёт значение как есть, список не трогает (`process_config_handler.py:36-45`). Тот же путь у `backend_ctl` (`process_manager_process.py:376`). |
| `launch.py` — единственная точка сборки | верно для прототипа | единственный `assemble_launcher` в прототипе — `launch.py:747`, словарь `:750`. `orchestrator.py`, `generic_process_app.py` ключи не собирают (читают `manifest_path`). `orchestrator_hooks.py:35,42,109` только читают. Вторая сборка — `app_module/builder.py:380-409` (generic-дорога); прототип идёт через `AppSpec.launcher_factory` (`main.py:92-121,167-171`), `spec.orchestrator_config` не задаёт. |
| `base.yaml` объявляет `devices` и `device_io` | верно | `base.yaml:27` (`process_name: devices`, `protected: true`), `:38` (`device_io: {max_workers: 4, max_pending: 64}`). |
| Список заменяется, не склеивается (REDS 5) | верно | `schemas.py:226-241` -> `deep_merge` (`data_schema_module/core/helpers.py:83`, `list_strategy="replace"`, ветка `else: result[key] = deepcopy(value)`). `{shutdown: {pre_stop: []}}` непустой словарь, рекурсия доходит до ключа. Страж: `config/tests/test_deep_merge_characterization.py:41`. |
| `user_overrides.yaml` рядом с `system.yaml` | верно | `schemas.py:268-269`: `path.parent / "user_overrides.yaml"`; файл в `.gitignore:90`. |
| Слои | чисто | `schemas.py` — pydantic; `launch.py` берёт `sys_config.shutdown.pre_stop`, новых импортов не нужно. Прототип -> framework, обратных импортов нет. `sentrux check .` не запускал. |

## 2. `robot_park_all` и форма ответа (п. 2)

- Без роботов, и с роботами не `delta_v2` или без связи: `{"status": "ok", "timeout_s": 30.0, "elapsed_s": ~0, "robots": {...}}` сразу. `manager.py:692-697` (`not_v2`, `not_connected` -> `skipped`), `:737-741` (`skipped` с этими причинами — не сбой), `_PARK_ALL_OK_SKIPS` `:64`.
- Команда идёт на `device_io` (`plugin.py:265-275`, `executor`, `targets="all"`), то есть ответ отложенный: `router_manager.py:1354-1370` — `reply(r)` -> `reply_to_request(processed, r, success=_result_is_success(r))`.
- **Форма ответа до PM — конверт**, не плоский dict: `{"type": "response", "command": "command.response", "sender": "devices", "targets": ["ProcessManager"], "queue_type": "system", "request_id": ..., "success": bool, "result": {<ответ хаба>}}` (`router_manager.py:1316-1325`). `success = not (result.status == "error")` (`router_manager.py:108-127`). Шаг PM читает `response.get("success") is True` (`pre_stop.py:182`) — форма согласована с кодом. Отказ всей команды и `status: "error"` (кто-то из роботов не дошёл домой) дают `success False` -> WARNING «ошибка ответа».
- Срок: `timeout_s` по умолчанию 30,0 (`manager.py:51`), ожидание до `t0 + timeout_s + 1,5` = **31,5 с** (`:55,:683`). 33,5 с — только при `timeout_s: 32` (максимум, `:53`). Манифест `args: {}` даёт 31,5 с + остаток одной отправки. 35 с годится (запас ~3,5 с), но обоснование в DESIGN («33,5 + 1,5») неверно — см. m1.

## 3. Находки

### Блокеры (`spec`)

**B1. [FILES, TESTS, ACCEPTANCE] Два golden-снимка станут красными, в FILES их нет.**
`backend/tests/test_build_characterization.py:84-98` кладёт в срез `launcher._orchestrator_config` целиком; `:137` — `assert actual == expected` («ловит ЛЮБОЙ дрейф»). Сейчас в `orchestrator_config` снимка 10 ключей (`backend_ctl, initial_state, manifest_path, observability_*, presentation_overlay, replace_debounce_s, state_throttle_rules, sys_config`), в `sys_config` — секции из `system.yaml` (`camera, discovery, display, observability, processing, storage, system, telemetry, backend_ctl`).
Вход: правка по DESIGN (`"pre_stop"` в `orchestrator_config` + секция `shutdown` в `system.yaml`; `sys_config_for_orchestrator` = `model_dump(exclude_unset=True)`, `shutdown` в нём задана). Наблюдаемое: `test_build_matches_snapshot[phone_sketch]` и `[hikvision_letter_robot]` красные (новые ключи `orchestrator_config.pre_stop` и `orchestrator_config.sys_config.shutdown`). Не запускал; вывод по чтению теста и снимка.
TRAPS велит «нужен другой файл -> stop and ask»: исполнитель встанет или перегенерирует снимки вне FILES.
Замена: в FILES добавить `multiprocess_prototype/backend/tests/snapshots/phone_sketch.build.json` и `hikvision_letter_robot.build.json` (перегенерировать `UPDATE_BUILD_SNAPSHOTS=1 python -m pytest multiprocess_prototype/backend/tests/test_build_characterization.py`; docstring теста `:30-33`). В ACCEPTANCE добавить A6: «golden перегенерированы, `git diff` по ним — ровно два новых ключа (`orchestrator_config.pre_stop`, `orchestrator_config.sys_config.shutdown`), других изменений нет; `test_build_matches_snapshot` зелёный». В `TESTS` добавить `multiprocess_prototype/backend/tests/test_build_characterization.py` и по файлу `test_hot_rebuild_parity_acceptance.py`, `test_hot_rebuild_parity_hazards.py`, `backend/state/tests/test_integration.py` (все зовут `build()`/`sys_config_for_orchestrator`; зелёными должны остаться).

**B2. [ACCEPTANCE L1, L4] Park робота на симе недостижим: нет v2-симулятора по TCP, а `robot_demo` — робот v1.**
- `multiprocess_prototype/recipes/robot_demo.yaml:29`: `protocol: delta_universal3`. `DeviceManager._park_all` (`manager.py:692-697`) такой робот пропускает: `skipped / not_v2`, ответ `status: ok` за миллисекунды, park не запускается.
- `python -m Services.robot_comm.server` — v1-симулятор (`server/__main__.py:42`: «карта universal3»; флага `--protocol` нет). TCP-сервер v2 не построен: `sim_core_v2.py:32` «Отложено: TCP-сервер ``--protocol v2`` ... (T2.4)», `server/README.md:18` — «T2.3 добавит ... `--protocol v2`»; `git grep -- '--protocol' -- Services/robot_comm` даёт только эти упоминания. Рецепт `letter_robot_sim.yaml:74` объявляет `delta_v2` на `127.0.0.1:5021` — против v1-сима связи не будет (`skipped / not_connected`, тоже за миллисекунды).
Вход: исполнитель L1 по тексту (рецепт `robot_demo`, сим на :5021). Наблюдаемое: шаг кончается за миллисекунды, «итог `park` (`ParkMachine`) ДО t(process.stop devices)» взять неоткуда; L4 («робот долго идёт домой, подмена задержкой на симе») невозможен. Строка «если симулятор не поднимается — сообщить и остановиться» не срабатывает: сим v1 поднимается. Риск — ложно-зелёный L1.
Замена: переписать как честную приёмку.
- L1a (достижимо): `robot_demo`, `system_shutdown(graceful)`; доказательство пути PM -> роутер -> `devices` -> авто-ответ -> PM — шаг завершился без WARNING `pre_stop: шаг 'devices.robot_park_all' — …` и события стопа взведены после шага (числа: `elapsed_s` драйвера, метки времени INFO-строк, см. B3). Что шаг ушёл реальной командой, а не пропущен: в журнале `devices` строка выполнения `robot_park_all` (проверить, какая строка есть) или `supervision_status` до/после.
- L1b (park до `process.stop`) и L4 (прерывание `force` посреди ожидания): «не проверено — нужен v2-сим по TCP (T2.4 отложена) или медленный ответчик»; не подменять другим процессом и не писать «прошло».
- Либо лид явно разрешает другой стенд (например, `Services/robot_comm/tests/e2e_rig_v2.py` в процессе) — тогда назвать его в задаче.

**B3. [ACCEPTANCE L1, L2] Строк журнала PM, на которые опираются L1 и L2, в коде нет; L2 по тексту всегда зелёный.**
`process_manager_process.py`: успех шага молчит. Строки есть только такие: INFO `System shutdown requested via command` (`:1241`), INFO `pre_stop: шагов {N} — события стопа после них` (`:1243`, только `graceful` с шагами), WARNING `pre_stop: шаг '<label>' — <причина>` (`:837`, причины: `процесс не найден`, `ребёнок не готов`, `timeout`, `ошибка отправки`, `ошибка ответа`, `исключение <Класс>`; только сбой), INFO `pre_stop: шаг '<label>' прерван (force|event)` (`:817,:834`), ERROR `pre_stop[<i>]: …` (разбор, `:706-709`). Строк «шаг начат» и «ответ ребёнка получен (`success`)» нет — L1 просит «строки в порядке: шаг начат -> ответ получен -> события взведены -> `process.stop`».
Вход L2: `force`, `deadline_s=1.0`; критерий «нет строки шага `robot_park_all`». Наблюдаемое: этой строки нет и при успешном `graceful` — критерий верен всегда, `force` его не проверяет.
Вход: ключ `pre_stop` не дошёл до PM (опечатка в имени, `None`). `parse_pre_stop(None) == ([], [])` — ни ERROR, ни INFO; стоп идёт как до 1.4. Тихий отказ.
Замена: в L1 назвать маркеры, которые существуют: t0 — ответ драйвера / INFO `System shutdown requested via command`; «ключ дошёл» — **обязательная** INFO `pre_stop: шагов 1 — события стопа после них` (нет строки = L1 красный); «шаг завершён успешно» — отсутствие WARNING `pre_stop: шаг 'devices.robot_park_all' — …` плюс `system_stop.pre_stop_step` в `supervision_status` (`"devices.robot_park_all"` во время шага, затем `null`) и `phase` `pre_stop -> children`; порядок «события -> `process.stop devices`» — по строкам фазы детей (уточнить, какие строки есть). В L2 критерий: нет INFO `pre_stop: шагов`, в ответе `phase == "children"`, `system_stop.pre_stop_step` не принимал значения. Что успех шага молчит — записать как наблюдение для лида (добавлять лог — правка framework, вне 1.4m).

### Major

**M1. [REDS 3] Ячейка зелёная до правки и не привязана к манифесту.**
`parse_pre_stop(<список из 2>)` — список литерал; `parse_pre_stop` уже в `main` (`process_manager_process.py:53`, `pre_stop.py:85`). Вход: HEAD без единой правки 1.4m. Наблюдаемое: зелёная; и с любым неверным `system.yaml` зелёная. Заявка «5 красных до правки» неверна для REDS 3.
Заодно «список из 2» читается как «список из двух записей», а ожидается `1 шаг` — речь о п. 2 REDS.
Замена: «`parse_pre_stop(load_system_config().shutdown.pre_stop)` на настоящем `system.yaml` -> 1 шаг, `errors == []`, `label == "devices.robot_park_all"`, `timeout_s == 35.0`» (красная до правки: нет `.shutdown`). Слова «список из 2» заменить на «список из п. 2» (литерал можно повторить).

**M2. [REDS 4] Форма не названа; два утверждения не проверяются.**
Способ собрать лончер без запуска процессов есть: `SystemBuilder.build()` не спавнит (`assemble_launcher`, `launcher/builder.py:60-64`: «функция НЕ спавнит процессы»; `launch.py:747`). Прецеденты: `test_build_characterization.py:84-98` (`SystemBuilder.from_manifest(load_manifest(<app.yaml>), "phone_sketch").build()`, читает `launcher._orchestrator_config`), `backend/state/tests/test_integration.py:278`. Другой способ без приватного поля — подменить `multiprocess_framework.modules.process_manager_module.launcher.assemble_launcher` (в `build()` он импортируется локально, `launch.py:637`) и взять `orchestrator_config` из аргументов; хрупче.
Оговорки: `build()` пишет `os.environ` (`MPF_APP_NAME`, `INSPECTOR_LOG_DIR`, `launch.py:636,680-683`), импортирует плагины, при невалидном рецепте — `sys.exit(1)` (`:740`).
Для случая `[]` нужен `system.yaml` с `shutdown: {pre_stop: []}`: `SystemBuilder.from_topology_path(tmp/system.yaml, <topology>)` (`launch.py:601-618`) или конструктор `SystemBuilder(sys_config=..., blueprint=..., topology_path=...)` (`:490-510`).
Не покрыто: «копии словарей» (TRAPS) — ни одной ячейки; «ключ есть и равен `[]`» — нужен `"pre_stop" in cfg`, иначе `cfg.get("pre_stop") == []` не отличит.
Замена: в REDS 4 написать форму (прецедент выше), две проверки («ключ есть, равен списку из п. 2»; при пустом — `"pre_stop" in cfg and cfg["pre_stop"] == []`) и третью: элемент списка в `orchestrator_config` — не тот же объект, что в `sys_config.shutdown.pre_stop` (изменение копии не меняет `sys_config`). Слова «списку из 2» -> «списку из п. 2».

**M3. [FILES, DESIGN] Цепочка «`orchestrator_config` -> настоящий PM» не проверена ни одной ячейкой REDS.**
Тесты 1.4 ставят `pm.config = {"pre_stop": ...}` (`test_pre_stop_author.py:61`) — фейк (project-rules §9: «fake-harness suite needs one test that wires the real objects»; урок 6 handoff 1.4). Кодом я проверил, что ключ доходит (см. п. 1 выше), но REDS 1-5 этого не охватывают, а в L1 нет обязательного маркера (B3). Замена: либо один тест на настоящем `ProcessConfiguration`/`ProcessConfigHandler.get_config("pre_stop")` со списком из `orchestrator_config` (ячейка в `test_launch_pre_stop.py`), либо — прямо в ACCEPTANCE — «INFO `pre_stop: шагов 1 …` в журнале PM обязательна» (B3). Выбрать одно и записать.

### Minor

**m1. [DESIGN, шапка] Арифметика срока.** «35 с = 33,5 с срока `robot_park_all` + 1,5 с запаса» — при `args: {}` срок хаба 31,5 с (`manager.py:51,55,683`), запас 3,5 с; 33,5 с — потолок при `timeout_s: 32`. Исправить текст на «31,5 с (30 по умолчанию + 1,5 с) + остаток одной отправки; запас ~3,5 с; 33,5 с — потолок хаба». Число 35 менять не нужно (Σ 35 ≤ 120, `timeout_s` ≤ 60).

**m2. [DESIGN, README] Негодный тип секции роняет старт бэкенда, а DESIGN обещает «PM стартует всегда».** `schemas.py:243-282` ловит только `yaml.YAMLError`; `SystemConfig.model_validate(raw)` бросает `ValidationError`. Вход (не запускал; следует из `list[dict[str, Any]]`): `user_overrides.yaml` с `shutdown:\n  pre_stop:` (голый ключ = `None`) или `pre_stop: "x"` -> загрузка падает, бэкенд не поднимается; PM для той же записи только пишет ERROR (`pre_stop.py:94-95`). Замена: в `config/README.md` записать единственную форму отключения — `pre_stop: []` — и что голый ключ/не список ломают загрузку; либо принять `list[Any] | None` и `None` -> `[]` (решение лида; согласуется с принципом 5).

**m3. [ACCEPTANCE L3] Нет порога.** «Число секунд шага … шаг не держит стоп до 35 с» — пороговой цифры нет. На `robot_demo` L3 и L1a — один и тот же сценарий (робот не `v2`, пропуск за миллисекунды, `manager.py:692-697`); L3 без порога не отличить от L1a. Замена: порог из замера L1a (например, шаг ≤ 1,0 с, `phase` `pre_stop -> children` не дольше) или честно «цифра фиксируется, порога нет».

**m4. [REDS 5, REDS 2] Форма слоя не названа.** `load_system_config(path)` берёт `user_overrides.yaml` из `path.parent` (`schemas.py:268`). Тестер, написавший `user_overrides.yaml` в настоящий каталог `backend/config/`, засорит репозиторий (файл в `.gitignore`, но локальный) и испортит REDS 2 на этой машине. Замена в REDS 5: «копия настоящего `system.yaml` во временный каталог + `user_overrides.yaml` рядом; `load_system_config(<временный system.yaml>)`». В REDS 2 — «`load_system_config()` без аргументов читает `user_overrides.yaml` рядом, если он есть; тест это терпит или читает копию без него».

**m5. [DESIGN, checklist (i)] Нет причины выбора имени и места секции.** Почему отдельная `shutdown`, а не поле в `system` (рядом `system.stop_timeout`, `system.yaml:8`). Добавить одну строку причины.

**m6. [Риски, не названы] Графическое закрытие.** В `main` уже есть путь GUI -> `system.shutdown` (`frontend/app.py:918,1215`, `frontend/process.py:354-379`, Task 1.1). После 1.4m каждый graceful-стоп проходит `pre_stop`; на роботе v2, не дошедшем домой, это до 35 с без показа фазы в GUI (2.1/2.2 не в `main`). Для v1/без робота — миллисекунды. Лиду: записать в риски и в отчёт владельцу; поведение GUI — задачи 2.1/2.2 (2.0).

## 4. Чек-лист одной задачи (a, d, f, i, ii, iii)

| Пункт | Ответ | Где |
|---|---|---|
| (a) приёмка несёт команду/литерал | частично | A1-A5 да; L1-L4 — нет (B2, B3, m3); A6 (снимки) отсутствует (B1) |
| (d) `Module contract`, `Handoff`, `Gate`, `Dependencies` | да | `n/a` для конфига прототипа допустим |
| (f) `OUT OF SCOPE` не пуст и не повтор `Goal` | да | |
| (i) решение с причиной | частично | m5; арифметика m1 |
| (ii) инвариант модуля не ломается | да | PM: один сбой шага не роняет соседа; `launch.py` — одна строка; но m2 (старт бэкенда при негодном типе) |
| (iii) тексты ошибок без значений | n/a | новых текстов нет; тексты PM — `pre_stop.py:63-77` без значений |

## 5. FILES: полнота

Есть: `schemas.py`, `system.yaml`, `launch.py`, `config/README.md`, два новых теста. **Нет** (B1): `backend/tests/snapshots/phone_sketch.build.json`, `hikvision_letter_robot.build.json`. Остальное не требуется:
- `sys_config_for_orchestrator` (`launch.py:365`) менять не надо: `exclude_unset=True` само понесёт `shutdown` в PM; повторная валидация `SystemConfig.model_validate(...)` на стороне PM принимает новое поле (`test_hot_rebuild_parity_acceptance.py:144-202` — round-trip, должен остаться зелёным).
- Вкладка настроек: `yaml_io.py:23` — жёсткий список `_SECTIONS` без `shutdown`, секция не показывается; `save_settings` пишет `cfg.model_dump()` (`:56-60`) — `shutdown` сохраняется при записи, форма круглая. Тесты вкладки (`test_settings_tab.py`, `test_yaml_io.py`, `test_system_presenter.py`) выбранные ключи не перечисляют (по `git grep` `telemetry|backend_ctl|SECTIONS` в них нет). Не запускал.
- `hot_rebuild_framework_keys.txt` — ключи наблюдаемости, к `pre_stop` не относится.
- `docs/claude/OPEN_QUESTIONS.md:2212-2213` и `plan.md` — правит лид (не FILES исполнителя): записать решение владельца 2026-11-09 и принятое поведение «не дома к сроку».

## 6. Что оставил открытым / ненадёжно

1. Ничего не запускал (по заданию). B1 — вывод по чтению `test_build_characterization.py` и снимков, а не по красному прогону; перегенерация и прогон — за исполнителем. m2 (`ValidationError` при `pre_stop: null`) следует из типа `list[dict[str, Any]]`, не воспроизведён.
2. Не проверено, какая строка выполнения `robot_park_all` остаётся в журнале `devices` и какие строки PM показывают `process.stop devices` в фазе детей (`_ChildrenStop._announce_phase`) — маркеры B3 для L1 лид уточняет сам; я их не нашёл и не придумывал.
3. Не проверено прогоном, что `reply(r)` отложенного ответа `device_io` доходит до PM при реальном `devices` (чтение `router_manager.py:1354-1370, 1316-1325` и `pre_stop.py:182`; конец-в-конец нет). Это содержимое L1a.
4. Не проверено, существует ли в `main` другой способ поднять v2-сим по TCP (искал `--protocol`, `SimRobotServerV2`, `serve_v2` по `Services`, `tests`, `apps` — не нашёл; `tests/e2e_rig_v2.py` поднимает сим в процессе — не читал). Если лид знает стенд — B2 снимается частично.
5. Тесты вкладки настроек, `test_hot_rebuild_*` и `state/tests/test_integration.py` читал выборочно (`git grep`), на красные после правки не прогонял.
6. Ветки/worktree против FILES не сверял. qex не использовал (индекс не проверял); поиск — `git grep`/`Read`.
7. Влияние 35-секундного шага на закрытие GUI (m6) — только по наличию путей в коде, поведение не проверялось.

---

# Раунд 2 (последний)

- **Читано:** `tasks/1.4m.md` целиком (84 строки, не закоммичено) против кода `main` `a63f5cbc1`. Сверено по коду: `schemas.py` (`SystemConfig`, `load_system_config`), `data_schema_module/core/schema_base.py:37-80`, `frontend/widgets/tabs/settings/{yaml_io.py,system/presenter.py,system/section.py}`, `launch.py:490-560`, `test_boot_companion_base.py:60-80`, `process_manager_process.py:1199-1243,5359-5368`, `command_manager.py:129-134`, `Services/device_hub/manager.py:674-690`, `plan.md:52,113`. Запускал два безвредных скрипта (`yaml.safe_load`, проверка валидации `SystemConfig` без записи); тесты и стенд не запускались, ничего не правил.
- **Вердикт: CHANGES REQUESTED (итерация 2 из 2).** Блокеров нет. Из 12 пунктов раунда 1 закрыто полностью 9, частично 3 (B3, M2, m2); новых находок 6: 3 major, 3 minor. Все — правки текста задачи. Если лид применит их и проверит `git diff`, стадию 0 считаю закрытой без третьего раунда.

## 1. Пункты раунда 1: закрыты ли

| № | Статус | Замечание |
|---|---|---|
| B1 (снимки, TESTS, A7/A8) | **закрыта** | FILES 8 путей, A7 — «ровно `pre_stop` и `sys_config.shutdown`», `test_build_characterization.py` в TESTS, радиус перечислен. A8 — см. R2-1. |
| B2 (L1b/L4 недостижимы) | **закрыта** | L1b/L4 — PENDING, статус `[DONE, L1b/L4 PENDING]`; `sim_core_v2.py:32` сверен лидом, мной — в раунде 1. Технические детали L1a — R2-5. |
| B3 (маркеры журнала) | **закрыта частично** | INFO `pre_stop: шагов N` — обязательный маркер «ключ дошёл» (`:1243`); L2 теперь различает режимы (INFO есть только у `graceful` с шагами). «Ответ получен» остаётся недоказанным — R2-2. |
| M1 (REDS 3) | **закрыта** | вход — `load_system_config().shutdown.pre_stop`; до правки красная (`.shutdown` нет, `extra` у pydantic `ignore` — `AttributeError`). |
| M2 (REDS 4) | **закрыта частично** | три проверки есть; форма «копии» через `from_manifest` пуста — R2-3. |
| M3 (цепочка до настоящего PM) | **закрыта** | выбран вариант (б): маркер INFO в L1a обязателен. |
| m1 (арифметика) | **закрыта** | 31,5 с + запас 3,5 с; верно по `manager.py:51,55,683`. |
| m2 (`None` в секции) | **закрыта частично** | `None` -> `[]` — R2-4 (остаток: не список, голый `shutdown:`). |
| m3 (L3 без порога) | **закрыта** | L3 стала негативным маркером; порога больше не требует. |
| m4 (REDS 5-6 только во временный каталог) | **закрыта** | REDS 5-6 и TRAPS говорят это прямо. |
| m5 (причина секции) | **закрыта** | ссылка на «решение владельца 1» сверена: `plan.md:52,113`, `design.md:90`. |
| m6 (риск закрытия GUI) | **закрыта** | в DESIGN записан с источником и смягчением. |

## 2. Ответы на три вопроса координатора

**Вопрос 1. L1a: достижим ли маркер «шаг не держал стоп до `timeout_s`» по elapsed, не слишком ли он слаб? — Слаб, и он лишний.**
Шаг, кончившийся по `timeout`, и так даёт WARNING `pre_stop: шаг 'devices.robot_park_all' — timeout` (`process_manager_process.py:837`): критерий «нет WARNING» уже его ловит, elapsed ничего не добавляет. Сам elapsed «от команды до `done`/`pm_gone`» складывается из фазы детей (graceful PM 5 с и больше); шаг на `robot_demo` занимает миллисекунды и в нём теряется. Главное: «INFO есть, WARNING нет, elapsed секунды» согласуется и с тем, что команда до `devices` не дошла (например, `submit` отклонён без строки, события взведены сразу) — доказательства «ответ получен» нет. Положительной строки успеха ни в PM, ни в `devices` нет (`log_success` выключен по умолчанию, `command_manager.py:134`; в `system.yaml` ключа нет). Снимки `pre_stop_step` при шаге в миллисекунды (опрос 50 мс) могут быть пустыми — 0 снимков не сбой, но и не доказательство.
Замена: добавить контрольный прогон L1c, не требующий кода. `user_overrides.yaml` с `shutdown: {pre_stop: [{process: devices, command: robot_park_all, args: {timeout_s: 0}, timeout_s: 3}]}`. Хаб отвечает отказом `{"status": "error", "message": "timeout_s: число от 1 до 32"}` (`manager.py:679-681`) -> `success False` (`router_manager.py:108-127`) -> WARNING `pre_stop: шаг 'devices.robot_park_all' — ошибка ответа` через миллисекунды после INFO `pre_stop: шагов 1` (число: разница меток времени < 1 с, не 3 с). Это доказывает, что настоящий конверт ответа дошёл до PM и разобран; при потере ответа причина была бы `timeout` через 3 с. Успешный прогон (`args: {}`) тем же кодом читает `success True`. Критерий elapsed из L1a убрать или пометить «справочно».

**Вопрос 2. Не краснит ли `ShutdownSection` с `field_validator` вкладку настроек или `save_settings`? — Тесты не краснеют, но запись через вкладку молча сбрасывает манифест (R2-1).**
- Валидатор: `SchemaBase` — обычный `BaseModel`, `_check_field_constraints` обходит только поля с `FieldMeta` и пропускает обычные (`schema_base.py:61-80`); поле без `FieldMeta` допустимо. `validate_assignment=True` на `mode="before"` не влияет.
- Вкладка: `yaml_io.py:23` `_SECTIONS = ["system", "camera", "processing", "display", "storage"]` — `shutdown` не показывается; тесты вкладки секций не перечисляют.
- `save_settings(cfg)` (`yaml_io.py:40-62`) пишет `cfg.model_dump()` — `shutdown` круглый.
- **Но** `presenter.py:80-110` (кнопка «Сохранить») собирает `dict_form` только из значений редакторов — то есть из этих пяти секций, — вызывает `SystemConfig.model_validate(dict_form)` и пишет результат в `system.yaml`. Все секции вне пяти берут умолчания схемы. Воспроизведено на `HEAD` скриптом (имитация: `dump` пяти секций -> `model_validate`): `backend_ctl.enabled` `True` -> `False`; `observability.documents` `{factory: 'Services.documents.wiring:make_document_sink', …}` -> `{factory: '', config: {}}`. `shutdown` сбросится так же: `pre_stop` -> `[]`, шаг молча отключён.

**Вопрос 3. Достаточно ли `from_manifest(...).build()` для REDS 4 на `pre_stop: []`? — Для настоящего `system.yaml` достаточно, для `[]` — нет; нужен путь подмены, и он есть.**
`from_manifest` берёт конфиг из `app.system` (`launch.py:539-541`). Для `[]` у тестера два годных пути, оба с прецедентом: (а) прямой конструктор `SystemBuilder(sys_config=SystemConfig.model_validate({"discovery": {"auto_discover": False}, "shutdown": {"pre_stop": []}}), blueprint=<минимальный dict>, topology_path=<tmp>).build()` — образец `backend/tests/test_boot_companion_base.py:73-77`, не нужен ни манифест, ни копия `system.yaml`; (б) `app.model_copy(update={"system": <tmp/system.yaml>})` (`AppManifest` — `BaseModel` без `frozen`, не запускал) и `from_manifest(app_copy, "phone_sketch").build()`. Предпочтителен (а) — быстрее и даёт тестеру в руки объект `sys_config` (нужен для проверки копий, R2-3).

## 3. Новые находки

### Major

**R2-1. [A8, DESIGN, README] Сохранение со вкладки «Настройки» отключает манифест; A8 проверяет не тот путь.**
Вход: оператор меняет любое поле в `system`/`camera`/… и жмёт «Сохранить» (`presenter.py:80-110`). Наблюдаемое: `system.yaml` перезаписан с `shutdown.pre_stop: []` (и — уже сегодня — с `backend_ctl.enabled: false`, пустым `observability.documents`; воспроизведено на `HEAD`, см. вопрос 2). Следующий graceful-стоп идёт без шага, никакой строки об этом нет. A8 («`save_settings` round-trip секции `shutdown`») зелёный и при этом ничего не говорит о реальном пути: `save_settings` круглый, `presenter.save` — нет.
Дефект старый (4 секции уже теряются); манифест становится ещё одной жертвой. Править presenter вне FILES, поэтому решение лида: (а) записать в DESIGN-риски, в `config/README.md` («сохранение со вкладки «Настройки» сбрасывает секции вне `system/camera/processing/display/storage`, включая `shutdown`») и в `OPEN_QUESTIONS.md` с предложением отдельной задачи «presenter мержит поверх `self._cfg.model_dump()`»; (б) A8 переписать: «`save_settings` round-trip `shutdown` зелёный; сброс через `presenter.save` — известный дефект, записан (не проверяется)»; либо (в) включить правку presenter в FILES. Рекомендую (а)+(б): правка вкладки — полоса GUI.

**R2-2. [L1a] «Ответ получен» не доказан; elapsed избыточен.** См. вопрос 1. Добавить L1c (контроль `args: {timeout_s: 0}` -> WARNING `ошибка ответа` быстро), критерий elapsed убрать или пометить справочным; записать, что 0 снимков `pre_stop_step` на `robot_demo` — ожидаемо (шаг в миллисекунды).

**R2-3. [REDS 4] Проверка «копии» пуста в форме `from_manifest`; DESIGN и REDS расходятся по глубине копии.**
Вход: тестер строит `launcher = SystemBuilder.from_manifest(app, "phone_sketch").build()` и сравнивает элемент `orchestrator_config["pre_stop"]` с «`sys_config`». Объект `sys_config` у него не в руках; `orchestrator_config["sys_config"]` — результат `model_dump(exclude_unset=True)` (`launch.py:365-400`), всегда свежие словари. Наблюдаемое: проверка «`is not`» зелёная и у реализации без копий. Второе: DESIGN — `[dict(s) for s in …]` (верхний уровень), REDS — «мутация элемента не меняет `sys_config`». `args` внутри элемента — вложенный словарь, общий у `dict(s)`; тестер, мутирующий `el["args"]["k"]`, получит красный на реализации по DESIGN.
Замена: (а) REDS 4 — прямой конструктор (вопрос 3, образец `test_boot_companion_base.py:73-77`), `cfg = load_system_config()` держит сам тест; (б) мутация — по `el["process"]` (верхний уровень) ИЛИ DESIGN меняется на `copy.deepcopy(sys_config.shutdown.pre_stop)`: «копии» тогда вся глубина, и REDS мутирует `el["args"]["k"] = 1`, проверяя `cfg.shutdown.pre_stop[0]["args"] == {}`. Рекомендую `deepcopy` — одна строка, честнее. `from_manifest` оставить необязательным дымом (golden A7 его уже покрывает).

### Minor

**R2-4. [DESIGN, README] Остаток m2.** `None` в `pre_stop` покрыт (REDS 6). Не покрыто и остаётся `ValidationError` при загрузке: `pre_stop: "x"`, `pre_stop: [1]` (`list[dict[str, Any]]` отвергает не-dict; PM для той же записи только пишет ERROR `запись — ожидается объект`, `pre_stop.py:99-101`) и голый `shutdown:` (секция `None`, `deep_merge` заменяет словарь значением `None`; так же ведут себя все прочие секции — старое поведение). Замена: тип `list[Any]` (схему шага проверяет PM — «одна истина») и строка в README: «`pre_stop:` без значения = пусто; не список — ошибка загрузки; отключение — `pre_stop: []`». Голый `shutdown:` — по решению лида (оставить как у остальных секций или добавить `field_validator("shutdown", mode="before")` на `SystemConfig`).

**R2-5. [L1a, L2, L3] Технические дыры живой проверки.**
(а) v1-симулятор на :5021 ничего не меняет: робот `delta_universal3` и так `skipped / not_v2` (`manager.py:692-693`), «разница в elapsed» с симулятором и без — шум; убрать критерий или назвать справочным. Чтобы направить `robot_main` на 127.0.0.1:5021 бегун не должен править `robot_demo.yaml` (вне FILES; шапка рецепта велит её править) — временная копия рецепта или `device_upsert` через `backend_ctl`.
(б) «без устройств»: реестр `devices` хранится в `data/devices.yaml` (`base.yaml`, `registry_path`) и между прогонами не очищается; перед прогоном снять `device_list` и записать состав.
(в) L3: загрузчик берёт `user_overrides.yaml` из `path.parent` (`schemas.py:268`), то есть файл лежит в настоящем каталоге `backend/config/` (в `.gitignore`); формулировка «временная копия» двусмысленна. Написать: «создать `backend/config/user_overrides.yaml`, сохранив прежний, по окончании вернуть».
(г) L2 без маркера «ключ дошёл» вакуумен при потерянном ключе (INFO нет и у `force`, и при `None`) — порядок прогонов: L1a (INFO есть) строго раньше L2 на той же сборке; записать.

**R2-6. [REDS 6] База не названа.** `shutdown: {pre_stop: }` даёт `None` (проверено: `yaml.safe_load` -> `{'shutdown': {'pre_stop': None}}`). Чтобы `[]` доказывал «`None` заменил базу», в REDS 6 база — копия настоящего `system.yaml` с шагом (как в REDS 5); иначе ячейка зелёная и у реализации, где `None` игнорируется, а умолчание — `[]`.

## 4. Итоговый список правок (для лида)

| Находка | Что исправить |
|---|---|
| R2-1 | риск в DESIGN, строка в `config/README.md`, запись в `OPEN_QUESTIONS.md` (задача «presenter мержит»); A8 переписать — `presenter.save` не проверяется, дефект известен |
| R2-2 | L1c: контроль `args: {timeout_s: 0}` -> WARNING `ошибка ответа` < 1 с; elapsed — справочно; 0 снимков `pre_stop_step` — не сбой |
| R2-3 | REDS 4 — прямой конструктор + `cfg` у теста; глубина копии: `copy.deepcopy` в DESIGN или мутация верхнего уровня в REDS |
| R2-4 | тип `list[Any]` + фраза README; голый `shutdown:` — решение лида |
| R2-5 | (а) симулятор v1 не меняет результат, не править `robot_demo.yaml`; (б) `device_list` перед прогоном; (в) формулировка L3; (г) порядок L1a -> L2 |
| R2-6 | база REDS 6 — копия настоящего `system.yaml` |

## 5. Что оставил открытым / ненадёжно (раунд 2)

1. Ничего не запускал из тестов и стенда. Воспроизведено только: (i) `yaml.safe_load('shutdown: {pre_stop: }')` даёт `None`; (ii) имитация валидации пяти секций из `presenter.py` — `backend_ctl.enabled` и `observability.documents` на `HEAD` теряются. Что кнопка «Сохранить» действительно доходит до `presenter.save` в живом GUI (а не только в юнит-тесте), не проверял; вывод по чтению `section.py:156`, `presenter.py:80-110`.
2. Что `AppManifest.model_copy(update={"system": …})` работает (путь (б) в вопросе 3), проверял только по отсутствию `model_config`/`frozen` в `manifest.py`; не запускал.
3. Положительная строка успеха шага в журнале PM или `devices` отсутствует (по умолчанию `log_success` выключен); доказательство «ответ получен» держится на контроле L1c и на отсутствии WARNING. Строки «шаг начат / ответ получен» — кандидат в отдельную задачу framework (OUT OF SCOPE в 1.4m записано верно).
4. Не проверено, как `observability.commands.log_success: true` включается на `devices` на лету (`config.reload` L3-слой или `user_overrides.yaml`) — вариант положительного маркера со стороны ребёнка предложен, но не исследован.
5. Не проверено прогоном, что хаб отвечает на `args: {timeout_s: 0}` именно текстом `timeout_s: число от 1 до 32` с `success False` через `device_io` (чтение `manager.py:674-681`, `router_manager.py:108-127,1354-1370`); это содержимое L1c.
6. Ветки/worktree против FILES не сверял; qex и `sentrux check .` не использовал; тесты вкладки настроек читал выборочно.
