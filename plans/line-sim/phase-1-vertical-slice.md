# Phase 1 — Вертикальный срез: топология процессов

Часть плана [`plan.md`](plan.md). Цель фазы: доказать сквозной путь recipe → процесс →
плагин → IPC → дисплей И то, что существующий код инспектора подключается к
симулятору робота без единой правки — оба риска сняты в минимальной форме, до того как
движок объектов (Ф3) написан целиком.

---

### Task 1.1 — Секция `sim:` в рецепте + минимальный source-плагин камеры **[VERTICAL SLICE]**

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `python multiprocess_prototype/run.py hikvision_letter_robot` с `sim.enabled:
true` в YAML поднимает новый процесс с source-плагином камеры-заглушки, и картинка
доходит до нового дисплея `line_sim` — без единой правки боевого пути.

**Контекст:** Это тонкий срез через ВСЕ затрагиваемые слои (recipe-формат, загрузчик,
process-plugin, IPC/SHM, display_module) в минимальной форме — кадр-заглушка (плоский
цвет + счётчик, как у `synthetic_frame_source`), без объектов/слоёв/фотометрии (это
Ф3–Ф4). Обратная связь «дошло до GUI» нужна здесь, а не в конце Ф3.

**Files:**
- `multiprocess_prototype/recipes/hikvision_letter_robot.yaml` — добавить top-level
  секцию `sim:` (см. формат ниже)
- НОВЫЙ `multiprocess_prototype/backend/recipes/sim_overlay.py` (путь ориентировочный,
  см. Step 1) — функция `apply_sim_overrides(blueprint: dict, sim_cfg: dict) -> dict`
- НОВЫЙ `Plugins/sources/line_sim_camera/plugin.py` — `LineSimCameraPlugin`
  (по образцу `Plugins/sources/synthetic_frame_source/plugin.py`)
- НОВЫЙ `Plugins/sources/line_sim_camera/__init__.py`
- Точка вызова `apply_sim_overrides` — файл определяется по Step 1 (кандидаты:
  `multiprocess_prototype/run.py`, `multiprocess_framework/modules/recipe/yaml_io.py`,
  `multiprocess_prototype/backend/*`)

**Steps:**
1. Разведка: найти место, где YAML рецепта превращается в blueprint-dict, который
   получает `SystemLauncher`/`ProcessManagerProcess`. `grep -rn "blueprint"
   multiprocess_prototype/run.py multiprocess_prototype/backend` и/или проследить
   `RecipeManagerProtocol.load()` (`multiprocess_framework/modules/recipe/
   interfaces.py`) до места, где результат передаётся в launcher. Зафиксировать
   найденную точку в комментарии рядом с вызовом `apply_sim_overrides`.
2. Спроектировать и задокументировать минимальный формат секции `sim:` (растёт в
   Ф2–Ф4, здесь — только то, что нужно для среза):
   ```yaml
   sim:
     enabled: true
     camera:
       process_name: line_cam        # имя нового процесса в blueprint.processes
       resolution_width: 1440
       resolution_height: 1080
       fps: 25
       chain_targets: [vision]       # как у camera_0 — картинка идёт в тот же тракт
     devices_override:               # host/port устройств на симулятор (заполняются Ф1.2)
       robot_main: {host: 127.0.0.1, port: 5021}
     display:
       id: line_sim
       name: "Виртуальная линия"
   ```
3. `apply_sim_overrides`: если `sim.enabled` falsy или секции `sim` нет — вернуть
   blueprint БЕЗ изменений (боевой путь). Если `enabled: true` — заменить
   `camera_0`-плагин (`Services.hikvision_camera...HikvisionCameraPlugin`) на
   `Plugins.sources.line_sim_camera.plugin.LineSimCameraPlugin` с конфигом из
   `sim.camera` (сохранить `chain_targets`); применить `devices_override` к
   соответствующим записям `devices:` (по `id`, точечно — merge, не replace);
   добавить дисплей из `sim.display` в список `displays:` и в
   `blueprint.displays` wiring (`node_id: <camera_process>.line_sim_camera.frame`).
4. `LineSimCameraPlugin` — по образцу `synthetic_frame_source`: `configure()` читает
   `resolution_width/height/fps` (fps здесь информационный — throttling делает
   `SourceProducer` по `metadata.source_target_fps`, как у `camera_0`); `produce()`
   возвращает кадр-заглушку (сплошной цвет + видимый штамп кадра, БЕЗ cv2/np.random —
   дёшево, как в образце) в форме `list[dict]` с полями `frame/camera_id/seq_id/
   frame_id/timestamp/width/height/channels/dtype` (тот же контракт, что у
   `synthetic_frame_source.produce()`).
5. Прописать в blueprint новый процесс (`process_class:
   multiprocess_prototype.generic_process_app.GenericProcessApp`, один плагин
   `line_sim_camera`, `metadata: {source_target_fps: <fps>}`) — либо статически в
   секции `sim:` (список processes-фрагментов), либо программно в
   `apply_sim_overrides` из `sim.camera`. Выбрать вариант с меньшим дублированием
   структуры blueprint; обосновать выбор в docstring функции.

**Acceptance criteria:**
- [ ] `python multiprocess_prototype/run.py hikvision_letter_robot` (рецепт БЕЗ
      изменения `sim.enabled`, т.е. значение по умолчанию `false`/секция закомментирована)
      поднимает ТОЛЬКО боевые процессы: `camera_0` использует
      `HikvisionCameraPlugin`, процесс `line_cam` НЕ создаётся, дисплей `line_sim` НЕ
      регистрируется в `DisplayRegistry().list()` — регрессии боевого пути нет.
- [ ] С `sim.enabled: true`: в blueprint, полученном launcher'ом, `camera_0`
      использует `LineSimCameraPlugin`; новый процесс из `sim.camera.process_name`
      присутствует и стартует (проверяется через `mcp__backend-ctl__system_overview`
      или `mcp__backend-ctl__introspect_plugins`, если бэкенд поднят под
      `BACKEND_CTL=1`, либо по логам старта процессов).
- [ ] Дисплей `line_sim` появляется в `DisplayRegistry().list()` (или в файле
      `displays.yaml` после `persist`) и в течение 5 секунд работы получает ≥1 кадр
      (проверяется через `mcp__backend-ctl__introspect_registers`/GUI DisplaysTab —
      счётчик кадров растёт).
- [ ] Кадр из `LineSimCameraPlugin.produce()` имеет форму `(sim.camera.
      resolution_height, sim.camera.resolution_width, 3)`, `dtype=uint8`.
- [ ] `apply_sim_overrides({}, {"enabled": False})` (или без ключа `sim`) возвращает
      blueprint БЕЗ добавленных полей (identity-проверка на существующем
      `hikvision_letter_robot.yaml`, распарсенном как dict).

**Out of scope:** реальные объекты/слои на ленте (Ф3), фотометрия (Ф4), ROI (Ф4),
робот-процесс (Task 1.2), правда/паспорт (Ф5).
**Edge cases:** секция `sim:` присутствует, но `enabled` отсутствует (дефолт — как
`false`, боевой путь); `sim.camera.process_name` совпадает с существующим именем
процесса (валидировать/сообщить об ошибке, не создавать дубль).
**Dependencies:** нет (первая задача после Ф0).
**Module contract:** new-lite (новый однофайловый публичный плагин
`LineSimCameraPlugin`; `sim_overlay.py` — вспомогательный модуль без собственного
публичного класса, туда же README-абзац не обязателен, но добавить docstring модуля).

---

### Task 1.2 — Робот-процесс: `SimRobotServer` в топологии прототипа

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** симулятор робота (`Services/robot_comm/server`) поднимается как ещё один
процесс blueprint'а (не ручной второй терминал), и СУЩЕСТВУЮЩИЙ код инспектора
(`devices` → `RobotDriver` → `RobotClient`) подключается к нему, читая
host/port из `sim.devices_override`, без единой правки `Services/device_hub`.

**Контекст:** `SimRobotServer.start()/stop()` (перенесён в Ф0) — уже чистый,
неблокирующий lifecycle (`start()` поднимает server-поток и ticker-поток и
возвращается сразу) — спроектирован специально для встраивания. Это ГЛАВНЫЙ риск
архитектуры («сможет ли боевой код инспектора говорить с симулятором, будучи
процессифицированным») — снимается здесь, до движка объектов.

**Files:**
- НОВЫЙ `Plugins/sim/robot_sim_process/plugin.py` — `RobotSimProcessPlugin`
- НОВЫЙ `Plugins/sim/robot_sim_process/__init__.py`
- `multiprocess_prototype/recipes/hikvision_letter_robot.yaml` — в секции `sim:`
  добавить блок `robot:` (host/port/тайминги: `job_ms`, `accept_ms`, `belt_mm_s` —
  прокидываются в `RobotSimCore` через `core_kwargs`, см. `server/__main__.py`)
- `multiprocess_prototype/backend/recipes/sim_overlay.py` (из 1.1) — добавить в
  blueprint процесс `robot` с плагином `robot_sim_process`, и мёрджить
  `sim.devices_override` в `devices:` (уже частично сделано в 1.1 — здесь реально
  используется: `robot_main.transport.host/port` меняются на `sim.robot.host/port`)

**Steps:**
1. `RobotSimProcessPlugin.configure(ctx)`: прочитать `host/port/unit_id` (дефолты
   `Services.robot_comm.server.sim_robot.DEFAULT_HOST/DEFAULT_PORT`,
   `Services.robot_comm.core.registers.ROBOT_UNIT_ID`) и тайминги (`job_ms`,
   `accept_ms`, `belt_mm_s` — дефолты как в `server/__main__.py`:
   `DEFAULT_JOB_MS=2500`, `DEFAULT_ACCEPT_MS=20`, `DEFAULT_BELT_MM_S=100.0`) из
   `ctx.config`. Собрать `core_kwargs` той же формулой, что `__main__.py`
   (`_ms_to_ticks`, `enc_rate = round(belt_mm_s * TICK_INTERVAL_S / FACTOR_MM)`) —
   переиспользовать эти функции напрямую (импорт), не копировать.
2. `start(ctx)`: создать `RobotSimCore(on_event=..., **core_kwargs)`, обернуть в
   `SimRobotServer(host, port, unit_id, core=core)`, вызвать `server.start()`.
   Сохранить `self._core`/`self._server` для `shutdown()` и для Ф2.2 (публикация
   энкодера). `on_event` — как минимум `ctx.log_info` (зеркало print() прошивки в лог
   процесса вместо консоли CLI).
3. `shutdown(ctx)`: `self._server.stop()`.
4. `commands`: минимум `get_status` (вернуть `core.encoder`, `is_connected`-подобное
   состояние — для ручной проверки живости из GUI/MCP), по образцу
   `ModbusPlugin.cmd_get_status`.
5. В `sim_overlay.apply_sim_overrides`: добавить процесс `robot` (один плагин
   `robot_sim_process`, конфиг из `sim.robot`) в `blueprint.processes`; смёрджить
   `sim.devices_override` в соответствующие записи `devices:` по `id` (host/port).
6. Ручная/скриптовая проверка живости: с поднятым sim-рецептом выполнить операцию
   инспектора, которая реально ходит по Modbus к роботу (например команда
   `send_test_job` через `device_hub.call("robot_main", "send_test_job", {...})`,
   или чтение `describe("robot_main")`) — убедиться, что `RobotDriver.connect()`
   успешен и `read_encoder()`/`read_telemetry()` не бросают.

**Acceptance criteria:**
- [ ] С `sim.enabled: true`, процесс `robot` стартует и слушает
      `sim.robot.host:sim.robot.port` (TCP-порт открыт — проверяется попыткой
      подключения `socket.create_connection`, timeout 2с, из независимого скрипта
      теста).
- [ ] `devices:` в загруженном (после `apply_sim_overrides`) blueprint содержит
      `robot_main.transport.host == sim.robot.host` и
      `robot_main.transport.port == sim.robot.port` (проверка на dict, без запуска
      системы).
- [ ] Инспекторский `DeviceManager.connect("robot_main")` (через
      `device_hub`, поднятый на blueprint с применённым sim-оверлеем) возвращает
      `True`; `DeviceManager.call("robot_main", "get_telemetry", {})` возвращает
      `{"status": "ok", ...}` с `encoder` — целым числом.
- [ ] Отправка `enqueue_job`/`send_test_job` через `DeviceManager.call` приводит к
      росту `RobotDriver.jobs_done` (или к появлению `[CVT] выполнено` в логе
      процесса `robot`) в течение `job_ms + accept_ms` + разумный запас (например
      `job_ms/1000 + 2` секунд).
- [ ] `pytest Services/robot_comm -q` по-прежнему 0 failed (эта задача не меняет
      `Services/robot_comm`, только оборачивает).

**Out of scope:** канал энкодера в line-процесс (Ф2.2), живая реакция скорости на
команды ПЧ (Ф2.1) — здесь `belt_mm_s` статичен на весь прогон, ровно как в текущем
CLI `server/__main__.py`.
**Edge cases:** порт уже занят (например ручной `python -m Services.robot_comm.server`
запущен параллельно) — `SimRobotServer.start()` должен упасть с понятной ошибкой, а не
тихо повиснуть; процесс `robot` должен прокинуть эту ошибку в лог, не маскировать.
**Dependencies:** Task 1.1 (структура `sim_overlay.py`, секция `sim:`).
**Module contract:** new-lite (новый однофайловый публичный плагин
`RobotSimProcessPlugin`).
