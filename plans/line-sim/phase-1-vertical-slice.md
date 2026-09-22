# Phase 1 — Вертикальный срез: симулятор как второе приложение, кадры по сети

> **⚠ УСТАРЕЛА В ДЕНЬ НАПИСАНИЯ (сверка 2026-09-22).** Ф1 на ветке `feat/line-sim` (ред. 3) **уже
> закрыта** задачами 1.0–1.6 в другой форме: `apps/line_sim/` на `run_app` (не `multiprocess_line_sim/`),
> дверь кадров — `Plugins/sim/mjpeg_sink` + бэкенд `stream` у `camera_service` (не `Services/frame_stream`
> + правка `capture`), сцена — `Plugins/sim/scene_source` в процессе `camera` (не `line_sim_scene` в
> `scene`), робот — `Plugins/sim/robot_host`. Стенд двух приложений снят 2026-09-21
> (`docs/reviews/2026-09-21_line-sim-f1-stand.md`). Из этой редакции в ред. 4 переходит только
> **замер влияния кодека** (Step 6 / критерий «таблица SHM/q90/q95/PNG») — как отдельная задача при
> Ф3.4, когда есть что мерить. Остальное — не исполнять. См. `QUEUE.md` решение №13.

Часть плана [`plan.md`](plan.md). **Переписана 2026-09-22** под автономную форму (решение владельца
2026-08-31) и сеть (решение 2026-09-22): симулятор — своё процессное дерево на том же фреймворке,
**без Qt**, стыкуется с инспектором только внешними протоколами — кадры потоком, робот/ПЧ по Modbus
TCP, управление через `SocketChannel` (для Пульта, план [`gui-service`](../2026-09-22_gui-service/plan.md)).
Прежняя редакция (секция `sim:` в боевом рецепте, `LineSimCameraPlugin` внутри прототипа) отменена
целиком — прототип **не знает** о симуляторе; в его рецепте меняются только адреса.

Цель фазы: доказать сквозной путь «дерево симулятора → поток кадров → `capture` инспектора →
дисплей» И то, что существующий код инспектора подключается к роботу-симулятору без единой правки —
оба риска сняты в минимальной форме, до движка объектов (Ф3).

---

### Task 1.1 — `Services/frame_stream`: поток кадров по сети + `capture` принимает URL

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** новый Services-модуль: MJPEG-сервер (публикует последний кадр N клиентам) и клиент
(«всегда последний кадр, старые выбрасывает», возраст кадра известен); боевой `capture`-плагин
учится принимать строку-URL как источник (~20 строк). Это ЕДИНСТВЕННАЯ дорога кадров для трёх пар:
симулятор → инспектор (здесь), инспектор → Пульт и симулятор → Пульт (gui-service Task 2.1).

**Контекст:** развилка кадров закрыта владельцем 2026-09-22 вариантом **(а)** — сеть. Образец
HTTP-сервера в процессе без новых зависимостей — `Services/phone_gateway/gateway.py` (stdlib
`ThreadingHTTPServer`, HTML из `web.py`). `Plugins/sources/capture/plugin.py:273` —
`cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)`: только целочисленный индекс. Клиент — свой,
на stdlib `http.client`, а не `cv2.VideoCapture(url)`: у OpenCV внутренний буфер даёт нарастающую
задержку на MJPEG-по-HTTP, а нам нужна семантика «последний кадр, старые в мусор» и возраст кадра.
Честная оговорка плана: JPEG меняет пиксели против lossless SHM — пороги `hsv_mask`/`circle_detector`
могут повести себя иначе; по умолчанию `quality=90`, режим PNG — опция; мерить в Step 6.

**Files (новый пакет — module-contract new-full):**
- `Services/frame_stream/__init__.py`, `interfaces.py` — Protocol'ы `FramePublisher` (`publish(frame_bgr,
  ts_monotonic)`, `client_count`), `FrameReader` (`read(timeout) -> (frame, age_s) | None`)
- `Services/frame_stream/server.py` — `FrameStreamServer(host, port, quality=90, codec="jpeg"|"png")`:
  `/stream.mjpg` (multipart/x-mixed-replace, заголовок части `X-Timestamp`, `X-Seq`), `/snapshot.jpg`,
  `/health`; несколько именованных потоков (`/stream/<name>.mjpg`) — для дисплеев Пульта
- `Services/frame_stream/client.py` — `FrameStreamClient(url)`: поток чтения, хранит только последний
  кадр, `read()` отдаёт его один раз (дедуп по `X-Seq`), `age_s` по `X-Timestamp` относительно
  собственного монотонного времени с поправкой echo (`/health` возвращает время сервера)
- `Services/frame_stream/README.md`, `STATUS.md`, `DECISIONS.md`
- `Services/frame_stream/tests/test_server.py`, `test_client.py`, `test_roundtrip.py`
- `Plugins/sources/capture/plugin.py` — `source: str` (URL) → `FrameStreamClient`; `device_id: int` —
  как прежде; конфиг-схема плагина принимает одно из двух
- `Plugins/sources/capture/tests/` — тест URL-ветки на in-process сервере

**Steps:**
1. `module-contract` (new-full): README + Protocol + Pre/Post + contract-тесты.
2. Сервер: один энкодер на именованный поток, кодирование только при `client_count > 0`;
   последний кадр побеждает (без очереди); медленный клиент не тормозит `publish()` (publish —
   неблокирующий, копия кадра под lock).
3. Клиент: daemon-поток читает multipart, парсит границы сам (stdlib); `read()` не блокирует дольше
   `timeout`; при обрыве — реконнект с паузой, `connected` флаг.
4. `capture`: если `source` — строка, открыть `FrameStreamClient`, `produce()` берёт `read()`;
   `timestamp` item'а — время получения (как у настоящей камеры), возраст — в `item["source_age_s"]`
   (новое необязательное поле, Dict at Boundary).
5. Автор пишет hazard-тесты: (а) `publish()` из потока продюсера при 50 клиентах, один из которых
   не читает — `publish()` возвращается за < 1 мс (p99 из 1000 вызовов); (б) обрыв соединения
   посреди части — клиент не отдаёт половинный кадр (JPEG не декодируется → кадр отброшен, счётчик).
6. Замер влияния кодека: прогнать `hsv_mask` + `circle_detector` (из рецепта) на 100 синтетических
   кадрах с дисками — через SHM-путь и через JPEG q90/q95/PNG; таблица «найдено кругов / отклонение
   центра px» в DECISIONS модуля. Число, не мнение.

**Acceptance criteria:**
- [ ] `from Services.frame_stream import FrameStreamServer, FrameStreamClient` — без `PySide6`/`torch`
      (только stdlib + numpy + opencv).
- [ ] Round-trip на localhost: сервер `publish()` 30 кадров/с 640×480 с счётчиком в углах; клиент за
      10 с получил ≥ 27 кадров/с, у 100 % кадров четыре угла совпадают (JPEG q90 углы-паттерн —
      сплошные блоки, устойчивые к сжатию), `age_s` p50 ≤ 70 мс.
- [ ] Клиент, вызывающий `read()` раз в секунду при 30 fps сервера, каждый раз получает **самый
      свежий** кадр (`X-Seq` последнего опубликованного ± 1), а не первый из очереди.
- [ ] Без клиентов `cv2.imencode` не вызывается (счётчик энкодера сервера == 0 за 5 с publish'а).
- [ ] `capture` с `source: "http://127.0.0.1:<port>/stream.mjpg"` отдаёт `produce()` с полями
      контракта источника (`frame/camera_id/seq_id/frame_id/timestamp/width/height/channels/dtype`) +
      `source_age_s`; с `device_id: 0` — ветка не тронута (существующие тесты `capture` зелёные).
- [ ] Таблица Step 6 присутствует в `DECISIONS.md` модуля с числами для SHM/q90/q95/PNG.
- [ ] `sentrux check .` зелёный (Plugins → Services импорт разрешён; обратного нет).

**Out of scope:** аутентификация потока (gui-service 2.2); RTSP/H.264; аппаратное кодирование.
**Edge cases:** кадр моно (1 канал) — кодируется как есть, `channels` честный; `quality` вне 1..100 —
ошибка валидации; сервер не поднялся (порт занят) — понятная ошибка, не тихий None.
**Dependencies:** нет (первая задача Ф1). Task 0.1 закрыта.
**Module contract:** new-full.

---

### Task 1.2 — Каркас приложения симулятора: своё дерево, `scene` отдаёт кадры потоком **[VERTICAL SLICE]**

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** второе приложение на фреймворке — `multiprocess_line_sim/` (composition root уровня
`multiprocess_prototype/`): свой `run.py`, свой манифест/рецепт `line_sim.yaml`, дерево
`SystemLauncher → ProcessManager` с процессами `scene` (плагин `LineSimScenePlugin` — v1 заглушка:
фон + движущийся прямоугольник, публикует в `FrameStreamServer`) и `gui` в headless-воплощении
(Qt в симуляторе нет и не будет), `BACKEND_CTL=1` на своём порту (8766). Инспектор на своём боевом
рецепте с `capture.source: http://<sim>:8090/stream.mjpg` показывает кадры симулятора в дисплее.

**Контекст:** это «второе приложение», которым конструктор доказывается (`QUEUE` P-2). Правило
задачи — **штатным путём**: как `multiprocess_prototype` собирает дерево (`backend/launch.py::
SystemBuilder.from_manifest`, `app_module`), так и здесь; если чего-то не хватает — это находка
конструктора (записать), а не костыль в симуляторе. Слои: `multiprocess_line_sim` импортирует
`Services`/`Plugins`/framework и **не** импортирует `multiprocess_prototype` (иначе «прототип знает»
наизнанку); `.sentrux/rules.toml` получает границы для нового корня.

**Files:**
- НОВЫЙ `multiprocess_line_sim/run.py`, `__init__.py`, `main.py` — по образцу `multiprocess_prototype/run.py`
  (venv-guard 1-в-1) и `main.py`
- НОВЫЙ `multiprocess_line_sim/config/app.yaml`, `manifest`, `recipes/line_sim.yaml` — процессы:
  `scene` (плагин `line_sim_scene`, `metadata.source_target_fps`), `gui` (headless, D8), позже `robot` (1.3)
- НОВЫЙ `Plugins/sources/line_sim_scene/plugin.py`, `__init__.py` — `LineSimScenePlugin`: `configure`
  (размер/fps/порт потока), `produce()` — кадр-заглушка + `publish()` в `FrameStreamServer`,
  дисплей `scene` (кадр идёт и в дерево — для Пульта через мост, и в поток — для инспектора)
- `multiprocess_prototype/recipes/hikvision_letter_robot.yaml` — **не меняется**; адреса — оверлеем
  параметров, если механизм есть (ADR-RCP-006 `recipe_io`/launch — разведать), иначе копия рецепта
  `hikvision_letter_robot_sim.yaml`, отличающаяся **только** адресами (`capture.source`,
  `devices.*.transport.host/port`) — diff проверяется тестом
- `.sentrux/rules.toml` — границы `multiprocess_line_sim`: не импортируется никем; сам не импортирует
  `multiprocess_prototype`
- `multiprocess_line_sim/README.md` — «как поднять симулятор и подключить к нему инспектор»
- Тесты: `multiprocess_line_sim/tests/test_topology.py` (снапшот дерева), `Plugins/sources/
  line_sim_scene/tests/`

**Steps:**
1. Разведка (записать в README задачи): как `SystemBuilder.from_manifest` собирает дерево прототипа,
   что из `multiprocess_prototype/backend/config` — универсальное (кандидат в `app_module`) и что —
   прототипное. Симулятор берёт универсальное; если универсальное лежит в прототипе — это находка
   для конструктора/rework 4.6 (`QUEUE` §5 «прототип не оброс новым универсальным»), записать, в
   симулятор **не копировать** — импортировать через фреймворк или временно через явно помеченный
   шим с TODO-ссылкой на находку.
2. Каркас дерева: `scene` + `gui` (headless). Поднять, убедиться `backend_ctl capabilities` на 8766
   отвечает.
3. `LineSimScenePlugin`: `produce()` по образцу `synthetic_frame_source` (контракт полей источника);
   плюс `publish()` в сервер потока (сервер живёт в процессе `scene`, как `PhoneGateway` в своём
   плагине). Прямоугольник движется на фиксированной скорости (px/кадр) — заглушка до Ф2/Ф3.
4. Адреса для инспектора — Step «оверлей vs копия» (см. Files). Поднять инспектор со ссылкой на
   поток; дисплей `main` показывает прямоугольник.
5. Автор пишет hazard-тест: остановка инспектора (клиента потока) не роняет `scene` — `produce()`
   продолжает, `client_count` падает до 0, энкодер выключается.

**Acceptance criteria:**
- [ ] `python multiprocess_line_sim/run.py line_sim` (с `BACKEND_CTL=1 BACKEND_CTL_PORT=8766`)
      поднимает дерево; `backend_ctl capabilities` на 8766 перечисляет процессы `scene` и `gui`;
      Qt-модули **не импортированы** ни в одном процессе симулятора (проверка: `sys.modules` через
      `introspect_*`/лог старта, `grep PySide6` → 0 в `multiprocess_line_sim/` и `line_sim_scene/`).
- [ ] `curl http://127.0.0.1:8090/health` → `200`; `/snapshot.jpg` — валидный JPEG заданного размера.
- [ ] Инспектор `python multiprocess_prototype/run.py <рецепт с адресами симулятора>` поднимает
      **только боевые** процессы (список процессов — как у `hikvision_letter_robot`, diff — 0
      процессов), `camera_0`/`capture` читает поток; дисплей `main` получает ≥ 0.8 × fps сцены за 30 с.
- [ ] Рецепт инспектора с адресами симулятора отличается от боевого **только** строками адресов
      (тест: нормализованный diff двух YAML — ключи вне множества `{capture.source,
      devices.*.transport.host, devices.*.transport.port}` равны).
- [ ] `grep -rn "multiprocess_prototype" multiprocess_line_sim Plugins/sources/line_sim_scene
      --include=*.py` → 0; `sentrux check .` зелёный с новыми границами.
- [ ] Снапшот-тест дерева симулятора зелёный; `README.md` описывает запуск в двух терминалах и
      порты (8766 управление, 8090 поток).

**Out of scope:** объекты/слои (Ф3), фотометрия/ROI (Ф4), робот (1.3), правда (Ф5), Пульт (gui-service).
**Edge cases:** порт потока занят — `scene` падает громко с именем порта, супервизор перезапускает
по политике, не молчит; инспектор стартует раньше симулятора — `capture` ждёт поток с реконнектом,
кадры появляются, когда симулятор поднялся (без рестарта инспектора).
**Dependencies:** Task 1.1.
**Module contract:** new-lite (`LineSimScenePlugin`); `multiprocess_line_sim` — composition root, README обязателен.

---

### Task 1.3 — Робот-процесс в дереве симулятора: инспектор подключается без правок

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `SimRobotServer` (`Services/robot_comm/server`, перенесён в Ф0) поднимается процессом
`robot` в дереве симулятора (не ручной второй терминал); существующий код инспектора
(`devices` → `RobotDriver` → `RobotClient`) подключается к нему по host/port из рецепта-с-адресами
(1.2) без единой правки `Services/device_hub`.

**Контекст:** `SimRobotServer.start()/stop()` — чистый неблокирующий lifecycle, спроектирован для
встраивания. Это ГЛАВНЫЙ архитектурный риск («сможет ли боевой код инспектора говорить с
процессифицированным симулятором») — снимается здесь, до движка объектов. Modbus уже TCP: для
запуска на другой машине меняется только host в адресах — ничего нового в этой задаче.

**Files:**
- НОВЫЙ `Plugins/sim/robot_sim_process/plugin.py`, `__init__.py` — `RobotSimProcessPlugin`
- `multiprocess_line_sim/recipes/line_sim.yaml` — процесс `robot` (плагин `robot_sim_process`,
  конфиг: `host/port/unit_id/job_ms/accept_ms/belt_mm_s`)
- Рецепт инспектора с адресами (1.2) — `devices.robot_main.transport.host/port` → симулятор

**Steps:**
1. `configure(ctx)`: `host/port/unit_id` (дефолты `Services.robot_comm.server.sim_robot.DEFAULT_HOST/
   DEFAULT_PORT`, `Services.robot_comm.core.registers.ROBOT_UNIT_ID`), тайминги как в
   `server/__main__.py` (`DEFAULT_JOB_MS=2500`, `DEFAULT_ACCEPT_MS=20`, `DEFAULT_BELT_MM_S=100.0`);
   `core_kwargs` — теми же функциями (`_ms_to_ticks`, `enc_rate = round(belt_mm_s * TICK_INTERVAL_S /
   FACTOR_MM)`) импортом, не копией.
2. `start(ctx)`: `RobotSimCore(on_event=ctx.log_info, **core_kwargs)` → `SimRobotServer(host, port,
   unit_id, core=core).start()`; хранить `_core`/`_server` для `shutdown()` и Ф2.2 (публикация энкодера).
3. `shutdown(ctx)`: `server.stop()`.
4. `commands`: `get_status` — `encoder`, число клиентов, `dups_seen` из `SimJournal` (задел Ф5.1).
5. Проверка живости из инспектора: `device_hub.call("robot_main", "get_telemetry", {})` и
   `send_test_job`.

**Acceptance criteria:**
- [ ] Процесс `robot` стартует и слушает `host:port` (TCP открыт — `socket.create_connection`,
      timeout 2 с, из независимого скрипта).
- [ ] Инспекторский `DeviceManager.connect("robot_main")` по рецепту-с-адресами → `True`;
      `call("robot_main", "get_telemetry", {})` → `{"status": "ok", ...}` с целым `encoder`.
- [ ] `enqueue_job`/`send_test_job` через `DeviceManager.call` → рост `jobs_done` / `[CVT] выполнено`
      в логе процесса `robot` за `job_ms/1000 + 2` с.
- [ ] `git diff --stat main -- Services/device_hub` == пусто (без правок инспекторской стороны).
- [ ] `pytest Services/robot_comm -q` — 0 failed, passed ≥ 127 (число Ф0).
- [ ] `backend_ctl send_command robot get_status` на 8766 возвращает `encoder` и `dups_seen`.

**Out of scope:** канал энкодера в `scene` (Ф2.2), живая скорость по команде ПЧ (Ф2.1) —
`belt_mm_s` статичен, как в CLI.
**Edge cases:** порт занят (параллельно запущен ручной `python -m Services.robot_comm.server`) —
`start()` падает с понятной ошибкой, процесс прокидывает её в лог, не маскирует.
**Dependencies:** Task 1.2. Связка с `observability-closure` Task 4.4 (до неё `log_tail`/`ui.tap`
не переживают рестарт процесса) — остаётся в силе для live-приёмки.
**Module contract:** new-lite (`RobotSimProcessPlugin`).
