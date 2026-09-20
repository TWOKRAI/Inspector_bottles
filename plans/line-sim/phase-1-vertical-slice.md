# Phase 1 — Вертикальный срез: симулятор как второе приложение

Часть плана [`plan.md`](plan.md). **Ред. 2 (2026-09-20)** — фаза переписана под форму
сборки, принятую владельцем 2026-08-31: симулятор — **автономный сервис со своим
процессным деревом** на том же фреймворке; прототип о нём не знает и стыкуется по
внешним протоколам (Modbus TCP для робота/ПЧ, видеопоток для кадров, `backend_ctl`
для управления). Ред. 1 (секция `sim:` в боевом рецепте, source-плагин внутри
прототипа) отменена целиком — история в git.

Цель фазы: доказать в **минимальной** форме два риска, до того как написан движок
объектов (Ф3): (1) второе приложение поднимается на `app_module.run_app` и обслуживает
существующий код инспектора **без единой правки** этого кода; (2) кадр из сима доходит
до штатного дисплея прототипа через боевой source-плагин.

## Разведка 2026-09-20 — факты кода, на которых стоит фаза (qex не использовался)

| факт | где | следствие |
|---|---|---|
| Второе приложение = `app.yaml` + `pipeline.yaml` + `run_app()`; процессы на фреймворковом `GenericProcess` | [`examples/minimal_app`](../../examples/minimal_app/), [`app_module/README.md`](../../multiprocess_framework/modules/app_module/README.md) | форма для `apps/line_sim/` готова, копировать нечего |
| `StateProxy` в процессе создаёт **прототипный** `GenericProcessApp`; фреймворковый `GenericProcess` его не заводит | [`generic_process_app.py:23`](../../multiprocess_prototype/generic_process_app.py#L23), [`plugin_orchestrator.py:59`](../../multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py#L59) | второе приложение без `ctx.state_proxy`. ~~Ф1 его не требует~~ — **ошибка разведки, вскрыта Task 1.1:** `system_overview` читает топологию из state-дерева, которое generic-оркестратор не сеет (`initial_state={}` не проходит гейт `_setup_state_store`). Серверная половина (посев топологии) — **Task 1.0**; клиентская (`ctx.state_proxy` у `GenericProcess`) остаётся Task 2.0 |
| `SocketChannel`/`SocketBridgeAdapter` — единственная дверь между деревьями: newline-JSON, «Кадры/SHM через сокет НЕ гоняем» | [`socket_channel.py`](../../multiprocess_framework/modules/router_module/channels/socket_channel.py) | «через RouterManager» = управление (`backend_ctl` на своём порту), не кадры |
| `camera_service` бэкенд `file` = `cv2.VideoCapture(str)` за сторожем `os.path.isfile` | [`file_source.py:35`](../../Plugins/sources/camera_service/backends/file_source.py#L35) | дверь кадров: новый тип `stream` с `url` (~30 строк), FFmpeg внутри cv2 читает MJPEG/RTSP |
| Боевая `camera_0` рецепта — `Services.hikvision_camera` (MVS SDK), не эмулируется | [`hikvision_letter_robot.yaml:114`](../../multiprocess_prototype/recipes/hikvision_letter_robot.yaml#L114) | для сим-прогона `camera_0` → `camera_service/stream` — правка **данных**, того же класса, что host/port робота |
| Робот/ПЧ: реестр `data/devices.yaml`, `vfd_belt` — bridge через `robot_main`; энкодер прототип читает **у робота** | [`robot_driver.py:307`](../../Services/device_hub/drivers/robot_driver.py#L307) | ноль правок кода инспектора; «один энкодер» = регистр сим-робота |
| `phone_gateway` уже принимает кадры по HTTP (`POST /frame`) | [`Services/phone_gateway/README.md`](../../Services/phone_gateway/README.md) | **отвергнуто**: дверь для фото без темпа, плюс сигнал-items пульта — работало бы случайно |
| `SimRobotServer(host, port, unit_id, core=, on_write=)` `.start()/.stop()`; без `pymodbus` — `ModbusNotAvailableError` в конструкторе | [`sim_robot.py:65`](../../Services/robot_comm/server/sim_robot.py#L65) | хост-плагин — тонкая обёртка; отсутствие extra — состояние `error` плагина, процесс живёт (образец: `otel_export` без `[otel]`) |

**Порты стенда (фиксируются здесь, чтобы два приложения не толкались):** прототип
`backend_ctl` **8765** (эксклюзивен, полоса closure); сим `backend_ctl` **8766**; Modbus
сим-робота **5021**; MJPEG **8090**.

**Дом сима — `apps/line_sim/`**, новый корень рядом с `multiprocess_prototype/` (сам
прототип — такой же корень). Движок — `Services/line_sim` (Ф3), плагины-хосты —
`Plugins/sim/` (образец пары: `Services/otel_export` + `Plugins/io/otel_export`). Граница
`apps/* → multiprocess_prototype/*` запрещается зеркально правилу для `examples/*`.

**Связка с closure:** Task **4.4** (`log_tail`/`ui.tap` переживают рестарт процесса) —
дедлайн **до Task 1.3**, первого сценария с рестартом; до него у отладчика есть
`observability_tail` + `history_query` (вердикт CTO 2026-09-08).

---

### Task 1.0 — Дефолтный `StateBootstrap` в `app_module`: generic-приложение сеет топологию и отвечает на `state.get_subtree`

**Статус: [DONE] 2026-09-20** — `eecba231` (teamlead, 190k токенов под потолком 350k).
`default_state_bootstrap` в `app_module/builder.py:115`, применение `builder.py:348`; ADR-APP-007
(сужает отклонение ADR-APP-006: store у generic-приложения есть всегда, посев непустой). Пустой
blueprint → `{"processes": {}}` — пришпилено `test_empty_blueprint_decision_is_pinned` с контрольной
половиной (`{}` store не поднимает). Два старых теста, пинивших контракт «без хуков —
`initial_state == {}`», переписаны по решению lead. Числа: `app_module + apps/line_sim +
examples/minimal_app` — **103 passed / 0 failed**; фреймворк `run_framework_tests.py` — **9871 passed /
40 skipped / 1 xfailed / 1 failed** (красный `config_module/test_watcher.py::test_foreign_file…` —
**воспроизводится на чистом main ×3, код модуля идентичен; посторонний, записан в OPEN_QUESTIONS**);
sentrux 37/37. Критерий 3 Task 1.1 (`test_backend_ctl_sees_robot_and_status`) — зелёный без правок
плагина и конфига.
**Break-injection (lead), предсказания до прогона:** J1 дефолт `{}` → умерли 8 (все живые + hazard) ✓;
J2 прикладная ветка в посеве → 3 ✓; J3 приоритет перевёрнут → 2 (тестерский «явный хук выигрывает»
+ hazard) ✓; J4 `status=running` в посеве → **предсказывал «выживут все», умер
`test_default_bootstrap_builds_topology_only`** — тестер пришпилил литерал `stopped`, расхождение в
пользу тестов; J5 непиклябельный объект → 6 (сборка падает на `_pickle_sanity`) ✓.
**Открыто (teamlead):** «прототип выигрывает у дефолта» держится дорогой `launcher_factory`
(`builder.py:241`), не `AppSpec.state_bootstrap`, — тестом не пришпилено; `list(proc["plugins"])` —
поверхностная копия, словари плагинов общие с blueprint'ом (риск оценён, не измерен).

**Level:** Senior (Opus)
**Assignee:** teamlead
**Источник:** [расследование 2026-09-20](../../docs/reviews/2026-09-20_line-sim-generic-app-observability-investigation.md) §4, §6 — зелёное воспроизведение топологическим хуком уже есть.
**Goal:** `system_overview()` у ЛЮБОГО generic-приложения (`examples/minimal_app`, `apps/line_sim`)
видит свои процессы; строки `No handler for key 'state.get_subtree'` исчезают; явный
`AppSpec.state_bootstrap` по-прежнему выигрывает у дефолта.

**DESIGN:** `default_state_bootstrap(blueprint) -> dict` рядом с `default_blueprint_loader`
([`builder.py:93-115`](../../multiprocess_framework/modules/app_module/builder.py#L93)),
применяется в `SystemBuilder._build_generic` вместо `initial_state = {}`
([`builder.py:283-289`](../../multiprocess_framework/modules/app_module/builder.py#L283)):
`spec.state_bootstrap or default_state_bootstrap`. Строит ТОЛЬКО топологию —
`{"processes": {<name>: {"config": {"plugins": [...], "chain_targets": [...], "priority": ...},
"state": {"status": "stopped", "pid": None, "fps": None, "error": None}}}}` — подмножество
[`bootstrap.py:203-215`](../../multiprocess_prototype/backend/state/bootstrap.py#L203) без
прикладных веток (`system`/`wires`/`services`/`displays`/`recipes`/`plugins` читают реестры
прототипа). Только pickle-safe примитивы (`_pickle_sanity`). НЕ менять: гейт
`_setup_state_store`, `assemble_proc_dicts`, factory-дорогу прототипа. ADR в
`app_module/DECISIONS.md`.

**Files:** `app_module/{builder.py, __init__.py, README.md, DECISIONS.md, tests/test_contract.py}`;
`multiprocess_prototype/backend/state/bootstrap.py` — только комментарий-указатель.

**Acceptance criteria** (измеримы тестером вслепую):
- [ ] `examples/minimal_app`: `drv.system_overview()["processes"]` содержит имя процесса из
      `pipeline.yaml` со `status == "running"`; в `anomalies` нет `kind == "empty_topology"`.
- [ ] `apps/line_sim`: `test_backend_ctl_sees_robot_and_status` зелёный БЕЗ правок
      `Plugins/sim/*` и `apps/line_sim/*`.
- [ ] `drv.send_command("ProcessManager", "state.get_subtree", {"path": "processes"})` →
      `success: true`; в stderr прогона нет `No handler for key 'state.get_subtree'`.
- [ ] Явный `AppSpec(state_bootstrap=my_hook)` выигрывает: посев равен результату `my_hook`.
- [ ] Blueprint без процессов — решение (пустой `{}` или `{"processes": {}}`) осознанное и
      пришпилено тестом.
- [ ] `python scripts/run_framework_tests.py` не ниже baseline; `sentrux check .` — все правила.

**Out of scope:** `ctx.state_proxy` у `GenericProcess` и ветка `processes.<p>.health` (Task 2.0).
**Dependencies:** нет. **Module contract:** impl-only.

---

### Task 1.1 — `apps/line_sim/`: второе приложение, процесс `robot` с хостом `SimRobotServer` **[VERTICAL SLICE]**

**Статус (2026-09-20):** код закоммичен `d0d391b2` (developer, 401k токенов — жёсткий потолок
не был включён, см. память `feedback_agent_hard_budget_is_off_by_default`); приёмка **5/6**,
критерий 3 ждёт Task 1.0. hazard-тесты автора 4/4, sentrux 37/37, `robot_comm` 127.
**Арбитражи lead по тестам тестера** (неверные модели — находки, записаны в самих тестах):
крит. 6 сканировал собственные докстринги → матчим import-формы; крит. 4 пинил
`history_query(metric=)`, а `record_metric` едет агрегатом окна (`kind=stats`,
`extra.metrics[].name`) — так и у прототипа (R12); крит. 5 читал `<log_dir>/<process>/errors.log`,
контракт — общий `<log_dir>/errors.log`, И инъекция «без pymodbus» не доезжала до ребёнка
(spawn копирует `sys.path` родителя, env не пересчитывается) — заглушка теперь и в `sys.path`.
Замечание в ревью: `record_metric` зовётся только из `cmd_status`/`shutdown` — без опроса
статуса числа не текут.
**Break-injection (lead, 2026-09-20), предсказания записаны до прогона:** I1 без пробного bind →
умер `test_port_busy…` ✓; I2 без guard повторного start → `test_double_start_is_noop` ✓; I3 shutdown
без `stop()` → `test_shutdown_closes_port` ✓, тестерский тест 1 выжил — **как и предсказано** (он
проверяет порт после убийства процесса, свойство закрыто hazard-тестом автора); I4a чтения тоже
считаются → `test_on_write_counts_only_writes` ✓; I4b итог вместо дельты → тот же ✓; I5 `enc_rate=0`
→ тестерский тест 2 ✓; I6 `_fail` пробрасывает исключение → hazard `test_port_busy…` ✓, **тестерский
тест 5 выжил дважды** (и после усиления `state=="error"`): оркестратор сдерживает исключение старта
плагина, объект и его команды живут — наблюдаемый исход одинаков, механизм «start не бросает»
пришпилен только hazard-тестом автора. Расхождение с предсказанием одно (I6/тест 5), объяснено.

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** `python apps/line_sim/run.py` поднимает своё процессное дерево через
`app_module.run_app`, в нём процесс `robot` держит `SimRobotServer` на `127.0.0.1:5021`;
существующий клиент `Services.robot_comm.core.client.RobotClient` подключается и читает
растущий энкодер; `backend_ctl` на порту 8766 видит процесс. Ни одной правки в
`multiprocess_prototype/`, `Services/robot_comm`, `Services/device_hub`.

**Контекст:** это бывшая Task 1.2 ред. 1, поставленная первой: ей не нужен ни один новый
механизм фреймворка, и она снимает главный архитектурный риск — «инспектор подключается к
симу, как к железу». Форма — `examples/minimal_app` один в один (манифест + плоская
топология + три строки bootstrap); хост-плагин — по образцу `Plugins/io/otel_export`
(сервис в `Services`, тонкий плагин в `Plugins`, деградация без extra в состояние `error`).

**Files:**
- НОВЫЙ `apps/__init__.py` (докстринг по образцу `examples/__init__.py`)
- НОВЫЙ `apps/line_sim/__init__.py`, `app.yaml`, `pipeline.yaml`, `run.py`, `README.md`
- НОВЫЙ `apps/line_sim/tests/__init__.py`, `tests/test_ci_smoke.py` — по образцу
  `examples/minimal_app/tests/test_ci_smoke.py` (`build_app` + `BackendHarness`, свой
  порт, свой `MULTIPROCESS_LOG_DIR` в `tmp_path`)
- НОВЫЙ `Plugins/sim/__init__.py`
- НОВЫЙ `Plugins/sim/robot_host/{__init__.py, plugin.py, README.md, STATUS.md, tests/}` —
  `SimRobotHostPlugin` (`@register_plugin("sim_robot_host", category=…)` — категорию
  выбрать из канонического списка `PluginCategory`, см. `plugins/manifest.py`)
- `.sentrux/rules.toml` — новая `[[boundaries]]` `apps/* → multiprocess_prototype/*`
- `multiprocess_framework/modules/app_module/tests/test_contract.py` — grep-контракт
  для `apps/` по образцу `test_examples_does_not_import_prototype`
- `plans/line-sim/plan.md` — статус задачи

**Steps:**
1. `apps/line_sim/pipeline.yaml`: один процесс `robot`,
   `process_class: multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess`,
   плагин `Plugins.sim.robot_host.plugin.SimRobotHostPlugin` с конфигом
   `host: 127.0.0.1`, `port: 5021`, `unit_id: 2` (= `ROBOT_UNIT_ID`), `auto_start: true`.
   `wires: []` (кадров в этом процессе нет — как в minimal_app).
2. `app.yaml`: `name: Line Sim`, `pipeline: pipeline.yaml`, `discovery` с
   `plugin_paths: []` / `auto_discover: false` — плагины сима лежат в `Plugins/sim`, их
   резолвит `plugin_class` по import-пути; авто-скан здесь не нужен.
3. `SimRobotHostPlugin`: `configure(ctx)` читает host/port/unit_id; `start(ctx)` создаёт
   `SimRobotServer(host, port, unit_id, on_write=self._on_write)` и зовёт `.start()`;
   `shutdown(ctx)` зовёт `.stop()` симметрично. `ModbusNotAvailableError` в `start` →
   `ctx.health.report_error(...)`, плагин в состоянии `error`, процесс **живёт**
   (образец: `OtelExportPlugin` без extra `[otel]`). Счётчик `writes_seen` из `on_write`
   (только записи, `values is not None`) — `ctx.record_metric("sim_robot.writes", …)` —
   первый измерительный крючок для Ф5. Команда `sim_robot.status` →
   `{running, host, port, unit_id, writes_seen}`.
4. `run.py` — три строки bootstrap по образцу `examples/minimal_app/run.py`; `sys.path`
   на корень репозитория (`parents[2]`).
5. `.sentrux/rules.toml` + контракт-тест границы. `sentrux check .` — все правила зелёные
   (число правил в отчёте задачи; сегодня 36).
6. `README.md` приложения: запуск, порты (таблица выше), как направить прототип на сим
   (`data/devices.yaml`: `robot_main` → `127.0.0.1:5021`; `vfd_belt` едет мостом сам).

**Acceptance criteria** (измеримы независимым тестером без знания реализации):
- [ ] `PYTHONPATH=. python apps/line_sim/run.py` с env `BACKEND_CTL=1
      BACKEND_CTL_PORT=8766 MULTIPROCESS_LOG_DIR=<tmp>` — в течение 10 с
      `socket.create_connection(("127.0.0.1", 5021), timeout=1)` успешно; процесс
      завершается по SIGINT/`system_command shutdown` без зомби (children = 0 через 5 с).
- [ ] `RobotClient(RobotConfig(host="127.0.0.1", port=5021)).connect()` → `True`;
      два `read_encoder()` с паузой ≥ 0.5 с — второе строго больше первого.
- [ ] `backend_ctl` (порт 8766): `system_overview` содержит процесс `robot` в состоянии
      running; `send_command("robot", "sim_robot.status")` → `running: True`,
      `port: 5021`.
- [ ] После `bot.send_job(...)` (любое валидное задание по образцу
      `Services/robot_comm/tests/test_sim_e2e.py`) `sim_robot.status.writes_seen` ≥ 1, а
      `history_query(kind="stats")` отдаёт ≥ 1 строку с `sim_robot.writes` в
      `extra.metrics[].name`. **Исправлено 2026-09-21:** исходная форма
      `history_query(metric=…)` отменена арбитражем lead (см. статус задачи выше) —
      `record_metric` едет безымянным агрегатом окна; тест уже приведён, текст отставал.
- [ ] Без `pymodbus` (инъекция `sys.modules["pymodbus"] = None` или окружение без extra):
      процесс `robot` поднимается, плагин в состоянии `error`, в плоскости ошибок
      (`errors.log` / `system_overview.anomalies`) есть запись с упоминанием extra
      `modbus`. Одна пара инъекций: с extra → нет записи; без extra → ровно одна.
- [ ] Ни одной ИМПОРТ-формы прототипа: `grep -rnE "^[[:space:]]*(from|import)[[:space:]]+multiprocess_prototype" apps/ Plugins/sim/` → 0 совпадений. **Не «0 вхождений слова»** (ревью 2026-09-21, FIX-2): голый `grep -rn "multiprocess_prototype"` даёт 10 строк — комментарии, докстринги и сам regexp контракт-теста; критерий в прежней форме был невыполним и «краснел» на верной реализации. Форма сверена с пином `apps/line_sim/tests/test_f1_task11_acceptance.py` и `app_module/tests/test_contract.py`;
      `sentrux check .` → все правила пройдены, включая новую границу `apps/*`.
- [ ] `pytest apps/line_sim Plugins/sim -q` — 0 failed; `pytest Services/robot_comm -q`
      — число passed не ниже baseline (127 при установленном pymodbus).

**Статус реализации (developer, 2026-09-20):** [BLOCKED, частично] — код готов
(`apps/line_sim/` + `Plugins/sim/robot_host/`), пункты 1-2 и 6 (частично) зелёные,
пункты 3-5 и грепп-часть 6 красные по причинам вне файлов задачи (framework-level
gap, не мой код — воспроизведено байт-в-байт на `examples/minimal_app`). Полный
разбор с input→output — [`docs/reviews/2026-09-20_task-1.1-developer.md`](../../docs/reviews/2026-09-20_task-1.1-developer.md).

**Out of scope:** живая скорость энкодера от команды ПЧ (Ф2.1), канал энкодера в
line-процесс (Ф2.2), окно-монитор `SimMonitorWindow` (Ф6), правка `data/devices.yaml`
в репозитории (это runtime-файл; инструкция — в README).
**Edge cases:** порт 5021 занят (ручной `python -m Services.robot_comm.server`) → ошибка
в плоскости ошибок с номером порта, процесс живёт; повторный `start` при живом сервере —
no-op.
**Dependencies:** Ф0 (закрыта).
**Module contract:** new-lite (`Plugins/sim/robot_host/plugin.py` — однофайловый
публичный плагин: докстринг-контракт + `README.md` + `STATUS.md` + `tests/`).

---

### Ревью Ф1 (Task 1.0 + 1.1) — 2026-09-21, вердикт FIXES REQUIRED, правки внесены

**Ход.** Первый ревьюер (фон, сессия 2026-09-20) вердикта не дал вовсе — агент не дожил до
конца сессии, текста не осталось. Перезапуск синхронный: оборвался на ECONNRESET после 154k
токенов, отчёт забран возобновлением агента из транскрипта (ещё 170k). Покрытие ревьюера —
5 углов из 8; углы 4, 7 и измерение поверхностной копии закрыл lead своей рукой.
**Вывод для протокола: фоновый ревьюер = потерянный вердикт.** Синхронный падает громко и
с сохранённым транскриптом, из которого отчёт достаётся.

**Восемь углов — все закрыты.** 1 (топология `minimal_app`), 2 (`state.get_subtree`),
3 (дорога прототипа), 5 (`line_sim` живьём: сокет 5021 за 1.23 с, энкодер 441 → 798,
`exit 0`, `SURVIVORS: []`), 6 (числовая плоскость: `writes_seen=4`, `history_query(metric=)`
пуст по контракту, запись едет `kind=stats`) — ревьюером. 4, 7, 8 — lead'ом, ниже.

**Матрица инъекций lead (предсказания записаны ДО прогона):**

| # | Что ломалось | Предсказание | Факт |
|---|---|---|---|
| K1 | пустой blueprint → `{}` (откат решения) | умрут ровно 2 | **✓ ровно 2** — `test_empty_blueprint_decision_is_pinned`, `test_no_build_time_hooks_minimal_config`; 104 passed |
| K2 | гейт `_setup_state_store` поднимает store всегда | умрёт контрольная половина | **✓, но 3** — плюс `TestSetupStateStoreGating::{test_no_state_no_throttle_is_noop, test_absent_keys_is_noop}`. Расхождение в пользу тестов: покрытие шире ожидаемого |
| K3 | дефолтный посев дописан поверх factory-результата | умрёт 0 | **✓ 0 из 100** — свойство «прототип выигрывает» держалось ранним `return` и не было пришпилено ничем (FIX-1) |
| K3′ | та же инъекция ПОСЛЕ нового пина | умрёт ровно новый тест | **✓ 1 из 101** — `test_factory_road_keeps_application_seed_untouched` |
| K7 | заглушка `pymodbus` в `sys.path` родителя, пара половин | плагин `error`, процесс жив, ровно 1 запись | **✓ точно** (числа ниже) |
| K8 | `_fail` пишет запись дважды | умрёт усиленный пин FIX-3 | **✓ 1** — счёт дал 2 при двух `#NN`, хотя «modbus» встречается трижды в каждом traceback |
| I6′ | `_fail` пробрасывает исключение, ПОСЛЕ усиления пина | умрёт и усиленный пин (вторая запись от оркестратора) | **✗ НЕ подтвердилось** — счёт остался 1, умер только hazard-тест автора. Объяснение lead'а от 2026-09-20 замером не подтверждено, см. OPEN_QUESTIONS |

**Угол 7, живой замер (K7, обе половины одной парой, `run.py` + `backend_ctl`):**

```
БЕЗ pymodbus: plugin state=error, running=False | proc robot=running, ok=True
              port5021 open=False | errors.log: 1 запись, упоминают modbus: 1 | exit 0
С  pymodbus: plugin state=running, running=True | port5021 open=True
              errors.log: 0 записей, упоминают modbus: 0 | exit 0
```

Заглушка доехала до ребёнка по-настоящему: сработала дорога `ModbusNotAvailableError`, маркер
самой заглушки в логе отсутствует. `gate_probe` в пине зовёт НАСТОЯЩИЙ `_setup_state_store()`,
не копию условия, — K2 это подтвердила.

**Угол 8, риск teamlead'а измерен и СНЯТ (понижен до NIT).** `list(proc["plugins"])` —
поверхностная копия, словари плагинов у blueprint и посева физически одни
(`ALIAS_TO_BLUEPRINT = True`, мутация видна в обе стороны). Но `SystemBlueprint.model_validate`
разрывает связь с `proc_dicts` (`ALIAS_STATE_TO_PROCDICT = False`), мутация из процесса в
дерево НЕ проходит, а `blueprint` после `build()` — локальная переменная. Остаточный риск
только у приложения, которое само держит ссылку на blueprint и правит его после сборки.

**Находки и что с ними сделано:**

- **FIX-1 [ЗАКРЫТА]** — свойство «прототип выигрывает у дефолта» не было пришпилено ничем
  (K3: 0 смертей из 100). Добавлен `test_factory_road_keeps_application_seed_untouched`
  (опасность 4 в `test_state_bootstrap_hazards.py`): пинует НАБЛЮДАЕМЫЙ эффект — тот же объект
  посева на выходе плюс литерал против правки на месте, — а не имя невызванной функции.
- **FIX-2 [ЗАКРЫТА]** — критерий приёмки Task 1.1 требовал «0 совпадений» голого грепа, по
  факту их 10 (комментарии, докстринги, сам regexp теста). Критерий переписан на import-форму.
- **FIX-3 [ЗАКРЫТА]** — пин деградации проверял «хотя бы одну» запись против критерия «ровно
  одна». Добавлен счёт ПО ЗАПИСЯМ (`#NN` + дата), а не по вхождениям слова: у одной записи
  «modbus» в traceback трижды, и счёт по вхождениям согласился бы с чем угодно.
- **NIT (не чинились):** нет `__all__`/`Stability:` в `plugin.py`; `cmd_status` читает
  `self._state` без лока (под GIL худший исход — транзиентное `configured` в ответе);
  алиасинг выше.

**Числа после правок:** `app_module + apps/line_sim + Plugins/sim + test_run_app_prototype +
minimal_app` — **111 passed / 0 failed**; `sentrux check .` (CLI) — **37 правил, все проходят**,
Quality 6972. Правки — только в двух файлах ТЕСТОВ (+91 строка), продакшн-код не тронут.

**Чего не делалось (и это не «сделано»):** полный `run_framework_tests.py` не гонялся ни
ревьюером, ни lead'ом — сверки с baseline 9871 нет. Все прогоны с `-p no:randomly`; изоляция
тестов на порту 5021 между собой не проверена. Замечание «без опроса `sim_robot.status` числа
не текут» негативным контролем не измерено. Углы 1, 2, 5, 6 lead своей рукой не повторял.

---

### Task 1.2 — Дверь кадров: тип `stream` в `camera_service` + MJPEG-сток в симе

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** сим отдаёт кадры по HTTP (MJPEG, `multipart/x-mixed-replace`) на `:8090`;
прототипный `camera_service` с `camera_type: stream`, `url: http://127.0.0.1:8090/`
читает их как обычную камеру. Кадр в Ф1 — заглушка (уже готовый `SimulatorBackend`/
`FrameGenerator` того же `camera_service`), объектов и слоёв нет (Ф3).

**Контекст:** дверь выбрана владельцем 2026-09-20 (вариант «а»). Единственная правка вне
сима — в `Plugins/sources/camera_service` (слой Plugins, **не** прототип): снять
запрет URL. `pyvirtualcam` и `phone_gateway` отвергнуты (см. таблицу разведки).

**Files:**
- `Plugins/sources/camera_service/backends/stream_source.py` — НОВЫЙ `StreamSourceBackend`
  (`cv2.VideoCapture(url)`, без `isfile`; EOF/обрыв → `None`, переоткрытие по
  `start()`), ИЛИ параметризация `FileSourceBackend` — выбор за исполнителем, но
  сторож `os.path.isfile` для URL применяться **не должен**
- `Plugins/sources/camera_service/backends/__init__.py` — `CAMERA_TYPES` + ветка фабрики
- `Plugins/sources/camera_service/config.py` — `CameraTypeStr` + поле `stream_url`
- `Plugins/sources/camera_service/plugin.py` — `_backend_kwargs()` для `stream`
- `Plugins/sources/camera_service/readme.txt`, `tests/` — новый тип задокументирован и
  покрыт
- НОВЫЙ `Plugins/sim/mjpeg_sink/{__init__.py, plugin.py, README.md, STATUS.md, tests/}` —
  `MjpegSinkPlugin`: вход `frame` (`image/bgr`), HTTP-сервер stdlib (`http.server`,
  поток-демон) отдаёт последний кадр как MJPEG; `jpeg_quality`, `fps_cap` в конфиге
- `apps/line_sim/pipeline.yaml` — процесс `camera`: `camera_service` (`camera_type:
  simulator`, `auto_start: true`) → `mjpeg_sink` (внутрипроцессный wire)
- НОВЫЙ `multiprocess_prototype/recipes/letter_robot_sim.yaml` — копия боевого рецепта
  с единственным отличием: блок `camera_0` = `camera_service` / `stream` / `url`.
  **Оговорка в шапке файла:** это не второй боевой рецепт, а сим-вариант; расхождение с
  боевым — ровно один блок (проверяется тестом-диффом)

**Steps:**
1. `StreamSourceBackend` + тест на fake-cap: строка-URL принимается, `isfile` не зовётся
   (spy на `os.path.isfile` **и** на наблюдаемый эффект — открытие `cv2.VideoCapture` с
   той же строкой).
2. `MjpegSinkPlugin`: сервер стартует в `start(ctx)`, порт из конфига, `GET /` →
   `Content-Type: multipart/x-mixed-replace; boundary=…`; кадр кодируется
   `cv2.imencode(".jpg")` при поступлении, клиент получает последний. Нет кадра → сервер
   отвечает, но границ не шлёт (клиент ждёт).
3. Сим-pipeline: `camera` → `mjpeg_sink`; `apps/line_sim/tests/test_ci_smoke.py` —
   `cv2.VideoCapture("http://127.0.0.1:<port>/")` читает ≥ 5 кадров за 5 с.
4. `letter_robot_sim.yaml` + тест-дифф с боевым рецептом (единственный отличающийся
   ключ — `processes[camera_0].plugins[0]`).

**Acceptance criteria:**
- [ ] `camera_service` c `camera_type: stream`, `stream_url: <url локального
      MJPEG-сервера-фикстуры>` → `produce()` отдаёт item с `frame` формы `(H, W, 3)`
      `uint8`; с `stream_url: "/nonexistent.avi"` — `report_error`, не исключение из
      `produce()`.
- [ ] `os.path.isfile` не вызывается для `camera_type: stream` (инъекция: вернуть
      сторож → красный).
- [ ] `curl -s -m 3 http://127.0.0.1:8090/ | head -c 200` содержит `--` boundary и
      `Content-Type: image/jpeg`; `cv2.VideoCapture(url).read()` → `ret=True` ≥ 5 раз
      за 5 с при поднятом `apps/line_sim`.
- [ ] Живой стенд: `python multiprocess_prototype/run.py letter_robot_sim --headless`
      при поднятом симе → в `state` прототипа `camera_0` рапортует кадры (fps > 0 в
      readback `camera_service`), `line_filter` на пустой заглушке не срабатывает
      (счётчик триггеров = 0 за 30 с).
- [ ] `pytest Plugins/sources/camera_service -q` — passed не ниже baseline (число в
      отчёте), 0 failed.

**Out of scope:** объекты/слои/фотометрия (Ф3–Ф4), ROI (Ф4), GUI-дисплей внутри сима.
**Edge cases:** обрыв потока (сим остановлен) → `camera_service` уходит в `report_error`
и восстанавливается после повторного `start_capture`; два клиента MJPEG одновременно
(прототип + `curl`) обслуживаются оба.
**Dependencies:** Task 1.1 (дерево сима, порты).
**Module contract:** new-lite (`Plugins/sim/mjpeg_sink/plugin.py`).

---

### Task 1.3 — Живой стенд двух приложений

**Level:** Senior (Opus) — стенд ведёт lead, ревью — `reviewer`
**Assignee:** lead (стадия 4 конвенции), затем `reviewer`
**Goal:** оба приложения подняты одновременно (прототип 8765 + сим 8766), `backend_ctl`
ведёт оба; числа сима видны его же плоскостью наблюдаемости; отказ сима виден прототипу
как отказ устройства — «наблюдаемость достаётся готовой» доказана числами, не
обещанием.

**Steps / что снять:**
1. Сим: `system_overview`, `introspect_observability`, `history_query(kind="stats")` с именем
   `sim_robot.writes` в `extra.metrics[].name` (не `metric=` — арбитраж критерия 4 Task 1.1), `observability_tail` — все четыре ответа непустые и согласованы
   (число записей в `history_query` ≥ `writes_seen` из `sim_robot.status` не бывает).
2. Прототип: `devices` рапортует `robot_main` online; `send_job` из пульта прототипа
   (или `robot_send_test_job` через `device_hub`) → `writes_seen` сима растёт.
3. Отказ: `system_command` стоп процесса `robot` в симе → в прототипе `health_errors`
   называет отказ робота в течение 10 с; рестарт `robot` → связь восстанавливается.
   **Этот сценарий — после closure Task 4.4** (см. связку выше); до неё — снять только
   пункты 1–2 и сказать об этом в отчёте.
4. Цена: fps `camera_0` в прототипе на заглушке `640x480` — число в отчёт (ориентир
   ≥ 20); задержка кадра не меряется (Ф5).

**Acceptance criteria:** отчёт стенда в `docs/reviews/<дата>_line-sim-f1-stand.md` с
input → observed output по каждому пункту; ревью `reviewer` синхронно —
APPROVE / CHANGES REQUESTED с воспроизведением.
**Dependencies:** Task 1.1, Task 1.2; п.3 — closure Task 4.4.
**Module contract:** impl-only (кода нет — стенд и документ).

---

### Task 1.4 (новая, ред. 3 плана) — Приёмка наблюдаемости второго приложения тем же зондом

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** симулятор проходит ту же потребительскую приёмку наблюдаемости, что прототип: тот
же чек-лист, тот же зонд, другой адрес. Каждая строка — зелёная, N/A с причиной либо
красная со ссылкой на заведённую задачу. После этого «наблюдаемость достаётся готовой» —
измеренный факт, а не обещание (пожелание владельца 2026-09-21, раздел «Наблюдаемость» в
[`plan.md`](plan.md)).

**Контекст (факты):** зонд `backend_ctl/probes/probe_observability_consumer_acceptance.py`
(1600+ строк) прибит к прототипу: `PORT = 8765` (строка 75), стенд поднимает сам, каталог
логов выставляет сам (строки 53–64). Команда-обёртка —
`.claude/commands/core/quality/observability-acceptance.md`. Что у generic-приложения уже
работает и какие разрывы известны — в разделе «Наблюдаемость» плана; неизвестные разрывы
(проводка гейта телеметрии, observability-watcher) выясняет именно этот прогон.

**Steps:**
1. Параметризовать зонд: команда запуска приложения, порт, каталог логов, имена
   процессов-мишеней. **Поведение без аргументов не меняется** (прототип, 8765).
2. Прогон по `apps/line_sim`: порт 8766, свой `MULTIPROCESS_LOG_DIR`.
3. Таблица вердиктов: строка чек-листа → прототип / сим / причина расхождения / куда чинить
   (конфиг сима · carve-out во фреймворк · N/A — например, у сима нет GUI, значит строки
   `ui_tap` неприменимы, и это написано словами).
4. Красная строка класса «заперто в прототипе» → задача carve-out в этот план по образцу
   Task 1.0 и 2.0. Обход в `apps/line_sim` или `Plugins/sim` ради зелёной строки запрещён.
5. Разведка попутно: откуда берётся имя сервиса у `otel_export` — нужно ли различать два
   приложения в одном коллекторе.

**Acceptance criteria:**
- [ ] Зонд без аргументов даёт по прототипу то же число строк и те же вердикты, что до
      задачи (baseline снят ДО правки и приведён в отчёте).
- [ ] Зонд с параметрами сима доходит до конца; ни один шаг не может повиснуть без дедлайна.
- [ ] Отчёт `docs/reviews/<дата>_line-sim-observability-acceptance.md`: нет строки без
      вердикта; N/A — только с причиной; каждая красная — со ссылкой на задачу.
- [ ] Уровень, опубликованный плагином сима через `publish_metric`, читается
      `introspect_telemetry` → `levels` на порту 8766. Если нет — это и есть разрыв
      «гейт телеметрии у generic-приложения», заводится задачей, а не чинится в плагине.
- [ ] В `apps/line_sim/` и `Plugins/sim/` нет правок, сделанных ради зелёной строки (ревью).

**Out of scope:** сами carve-out'ы, найденные прогоном, — отдельными задачами.
**Dependencies:** Task 1.1. Координация: зонд общий с полосой `observability-closure`.
**Module contract:** impl-only.

---

## Что переехало из ред. 1 и куда

| было (ред. 1) | стало |
|---|---|
| Task 1.1 секция `sim:` + `apply_sim_overrides` + `LineSimCameraPlugin` в прототипе | отменено: прототип о симе не знает. Кадры — Task 1.2 через боевой `camera_service` |
| Task 1.2 робот-процесс в топологии прототипа | **Task 1.1** — тот же `SimRobotServer`, но в дереве сима |
| дисплей `line_sim` в `display_module` прототипа | не нужен: кадр идёт в штатный `main` через `camera_0` |
| `StateProxy` для канала энкодера | **Task 2.0** (голова Ф2): carve-out из `GenericProcessApp` в `GenericProcess` |
| вкладка-пульт Ф6 внутри прототипа | Ф6 переписывается отдельно: v1-пульт = регистры плагинов сима через `backend_ctl`, Qt-окно — после `GuiBootstrap`/`minimal_gui` |
