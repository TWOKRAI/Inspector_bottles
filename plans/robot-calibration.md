# План: калибровка изображение→координаты робота (robot_comm + плагины)

> **СИНХРОНИЗИРОВАНО с plans/robot-vfd-services.md (2026-06-11).** Базовая
> инфраструктура УЖЕ СОЗДАНА тем планом и здесь НЕ делается заново:
> - `Services/robot_comm` существует (порт **universal3** `pc_full.py`, НЕ u2;
>   карта CFG=11/TLM=11/DCBUS_SCALE=10/REG_MODE/drawing) **поверх
>   `Services/modbus`** (`ModbusDevice.transaction` + `RegisterMap` +
>   `RegisterTransport`) — собственная pymodbus-обёртка НЕ нужна, долг P1.1
>   закрыт до возникновения (ADR-MB-001, ADR-RC-001);
> - кодеки = `Services.modbus.sdk.datatypes` + `RegisterMap` (никаких
>   `sdk/transport.py`/`sdk/codec.py` в структуре Фазы 0);
> - `vfd_*` НЕ в `RobotClientProtocol` — они в `Services/vfd_comm.VfdClient`
>   (мост через RegisterTransport); пункт P2.2 «отдельный план vfd-control.md»
>   закрыт планом robot-vfd-services;
> - симулятор готов: `FakeRobotTransport` (in-process) + TCP `sim_robot`
>   (`python -m Services.robot_comm.server`) — двухуровневый, см. ADR-RC-004;
> - **плагин `robot_io` уже создан** (владелец соединения + feeder +
>   `manual_mode` для P2.5) — Фаза 4 этого плана РАСШИРЯЕТ его
>   (reject → `image_to_robot` → `send_job`), а не создаёт;
> - P2.5 «калибровка активна»: уже есть `robot_io.set_manual_mode` (флаг на
>   ПК); защита на роботе — Lua-кандидат №5 «регистр ручного режима» в
>   robot-vfd-services.
>
> Актуальный объём этого плана: circle_detector (Фаза 1), calibration math +
> store (Фаза 2), UI калибровки (Фаза 3), расширение robot_io (Фаза 4).

## Context

Нужна калибровка камеры под координаты робота для конвейерной системы инспекции.
Оператор кладёт лист бумаги с **5 чёрными кругами** (4 угла + центр), система находит
их центры в пикселях. Затем оператор двигает конвейер, лист приезжает в рабочую зону
робота, оператор подводит инструмент к каждой из 5 точек и жмёт «Считать» — по Modbus
запрашиваются реальные X,Y,Z робота. Получаем 5 пар соответствий пиксель↔робот →
строим преобразование image→robot. Калибровка хранится **на конкретную камеру** и
учитывает смещение конвейера по энкодеру (лист едет от камеры к зоне робота).

Цель — сделать это как **сервис `Services/robot_comm`** (общение с роботом по Modbus) +
**плагины** (детекция кругов, калибровка, ввод/вывод робота, управление ПЧ), и встроить
в прототип-инспектор.

**Решения владельца (2026-06-10):**
- **Приоритет — тонкий вертикальный срез**: быстро рабочая цепочка, минимум тестов,
  цель — пощупать на железе. Полировка/sim/покрытие — позже.
- **UI калибровки — выделенная вкладка по MVP** (как `services/hikvision/`).
- **Z — 2D-плоскость**: homography строится по X,Y; Z читается с робота и хранится
  «на всякий случай», но в преобразование не входит.
- **Ключ калибровки — имя камеры в рецепте** (напр. `cam_main`).
- **Калибровочная цепочка — штатные ноды pipeline** (камера → circle_detector →
  calibration → robot_io), а не отдельный движок.
- **Рецепт может содержать НЕСКОЛЬКО цепочек** — по одной на камеру (2-3+ камер).
  Калибровка делается **на каждую камеру отдельно** (свой ключ camera_id, своя homography).
  При этом **робот, как правило, один** на весь рецепт — соединение к нему общее (см.
  раздел «Мульти-камера / мульти-цепочка» ниже).

**Зависимость:** Фаза 0 (порт класса `Robot`) ждёт, пока владелец дотестирует
`robot/universal2/pc_robot.py` на железе — регистровая карта/настройки могут уточниться.

---

## Архитектурные опорные факты

- **Слои импортов:** `framework → Services → Plugins → prototype`. Плагин знает только
  `PluginContext`, но **может прямо импортировать `Services.*`** (как `modbus_sink`).
- **Multiprocess:** pipeline-узлы — отдельные ОС-процессы. `ServiceRegistry` — синглтон
  *в пределах процесса*. Соединение с роботом живёт **внутри одного процесса-воркера**;
  плагины этого процесса делят один `RobotClient` (его внутренний `Lock` сериализует доступ).
- **GUI ↔ робот только через команды плагину.** Кнопка «Считать» в UI → round-trip
  команда `read_robot_point` плагину `calibration` → плагин зовёт `robot_comm.read_position()`
  → dict {x,y,z} → presenter пишет в таблицу. Паттерн — `services/hikvision/presenter.py`
  (`CommandSender.request_command` + `RequestRunner.submit`).
- **pymodbus** — в optional-dep `[modbus]`. `robot_comm` должен импортироваться без него
  (флаг `ROBOT_AVAILABLE`), сетевые операции — graceful degradation.

---

## Мульти-камера / мульти-цепочка (топология одного рецепта)

Рецепт может содержать **N независимых цепочек** — по одной на камеру:
```
cam_1 → circle_detector → calibration(camera_id=cam_1) → robot_io
cam_2 → circle_detector → calibration(camera_id=cam_2) → robot_io
...
```
Калибровочные ноды — **обычные ноды pipeline**, по одной на цепочку. Каждая нода
`calibration` параметризуется своим `camera_id` (из `registers.camera_id`, дефолт — имя
источника в рецепте) и хранит/грузит **свою** `{camera_id}.json`. Так калибровки камер
не конфликтуют: один файл на камеру.

**Робот — один общий ресурс на рецепт** (одно физическое устройство, один Modbus-slave,
обычно один TCP-master). Это диктует топологию соединения:

- **Срез (1 камера, 1 цепочка):** все ноды цепочки в одном процессе → делят один
  `RobotClient` по **модели владельца** (см. ниже), его `Lock` сериализует доступ.
- **Мульти-цепочка (несколько процессов):** in-process экземпляр НЕ виден между процессами.
  Целевая модель — **один «робот-процесс/нода» владеет соединением**, остальные цепочки
  адресуют его через IPC (RouterManager-канал: запрос `read_position`/`send_job` → ответ).
  Это согласуется с проектным направлением «единый транспорт RouterManager + каналы» и
  «иерархическая адресация процесс→воркер→плагин».
- **Калибровка читает робота одинаково** для любой камеры: подвели инструмент к точке →
  `read_position()` того же единственного робота. Различается только пиксельная сторона
  (камера) и сохраняемый homography.

### Модель владения соединением (P0.1 — заменяет «module-level синглтон»)

`RobotClient` НЕ создаётся каждым плагином и НЕ прячется в module-level mutable singleton
(у `ServiceRegistry` хранятся классы, не экземпляры — синглтон-паттерн в проекте отсутствует).
Вместо этого — **явный владелец**:

- **Владелец — плагин `robot_io`** (Фаза 4; в срезе с 1 камерой допустимо, что владельцем
  временно выступает `calibration`). Владелец в `start()` создаёт `RobotClient(config)` из
  **своего** config (единственный источник config робота в процессе), вызывает `connect()`,
  и публикует живой экземпляр в **process-local реестр** `Services/robot_comm/runtime.py`:
  `runtime.set_client(client)`. В `shutdown()` — `client.disconnect()` + `runtime.clear()`.
- **Потребители** (`calibration`, `vfd_control`) в `configure()/start()` берут готовый
  экземпляр: `runtime.get_client()` — read-only, бросает `RobotNotConnectedError`, если
  владелец не стартовал. Потребители НИКОГДА не создают и не закрывают клиент.
- Lifecycle закрыт однозначно: **создаёт/коннектит/закрывает только владелец**; config —
  один (владельца); потребители ссылаются. Ref-counting не нужен (один владелец на процесс).
- `runtime.py` — тонкий module-level holder (`_client` + `Lock` вокруг set/get/clear), НЕ
  бизнес-логика; держит ровно один экземпляр на процесс.

**Решение для среза:** 1 камера, 1 цепочка, владелец-плагин + `runtime` holder.
Мульти-цепочный шаринг робота через IPC-канал (робот-нода) — **Фаза 4+**, явный долг.
camera_id-ключ уже делает калибровку мульти-камерной «бесплатно».

---

## Эталоны (копировать структуру/паттерны отсюда)

| Что | Путь-эталон |
|-----|-------------|
| Источник для порта `RobotClient` (класс `Robot`, регистры, кодеки, Lock/_atomic) | `robot/universal2/pc_robot.py` |
| Структура сервиса (sdk/core/plugin/service.py/interfaces) + `@register_service` | `Services/modbus/` (`service.py`, `core/device.py`) |
| Processing-плагин + `registers.py` (SchemaBase+FieldMeta) для `circle_detector` | `Plugins/processing/blob_detector/plugin.py` (+`registers.py`) |
| Плагин с внешним соединением (lifecycle start/shutdown, доступ к `Services.*`) | `Plugins/sinks/modbus_sink/plugin.py` |
| MVP сервис-вкладка + round-trip команды для UI калибровки | `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/` (`presenter.py`/`section.py`/`widget.py`/`controller.py`) |

---

## Фаза 0 — Сервис `Services/robot_comm` (порт рабочего `Robot`)

**Цель:** живой `RobotClient` с публичным API, импортируемый без pymodbus.

**Транспорт — собственный pymodbus-клиент в `core/` (НЕ поверх `Services/modbus.ModbusDevice`).**
Обоснование: рабочий `Robot` использует атомарные мульти-записи под одним Lock (`_atomic`:
координаты+маркер одной серией, чтобы маркер не оторвался от данных) — `ModbusDevice`
даёт пооперационный Lock, не «серию под одним замком». Плюс семантика DW-энкодера и
`device_id=ROBOT_UNIT` — доменные для робота. Код уже отлажен владельцем на железе.

**Долг с hard deadline (P1.1):** реальный `_atomic` — это `with self._lock: for op in ops`.
Чтобы не плодить вторую pymodbus-обёртку с дублем reconnect/`_enable_nodelay`, в `ModbusDevice`
добавляется `def transaction(ops)` (серия записей под одним `self._lock`), и `RobotClient.transport`
**мигрирует поверх `ModbusDevice`** в Фазе 5 (не «когда-нибудь» — это пункт acceptance Фазы 5).
Зафиксировать в `DECISIONS.md` как принятый долг с дедлайном, а не как открытую альтернативу.

**Структура:**
```
Services/robot_comm/
  __init__.py            # реэкспорт: RobotClient, RobotConfig, Telemetry, VFDStatus,
                         #            RobotPosition, ROBOT_AVAILABLE
  __main__.py            # CLI-smoke: python -m Services.robot_comm --tcp 192.168.1.7:502 pos
  interfaces.py          # RobotClientProtocol (Protocol, runtime_checkable)
  README.md  STATUS.md  DECISIONS.md
  sdk/
    transport.py         # обёртка ModbusTcpClient + _enable_nodelay + reconnect; ROBOT_AVAILABLE
    codec.py             # _to_u16,_s16,_dw_to_regs,_regs_to_dw, XY_SCALE/FREQ_SCALE (чистые ф-ии)
    errors.py            # RobotCommError, RobotNotConnectedError
  core/
    config.py            # @dataclass RobotConfig(host,port,unit_id,word_order,timeout_sec)
                         #            + to_dict/from_dict (БЕЗ factor_mm/belt_vector — те в калибровке, SRP)
    registers.py         # КАРТА РЕГИСТРОВ робота — один источник истины
    client.py            # RobotClient — портированный Robot (Lock-safe, _atomic), БЕЗ REPL/print
    datatypes.py         # @dataclass Telemetry, VFDStatus, RobotPosition
  service.py             # @register_service("robot_comm") RobotCommService(IService)
  runtime.py             # process-local holder: set_client/get_client/clear (модель владельца)
  server/
    sim_robot.py         # фейковый Modbus-slave с картой робота (telemetry/encoder/echo)
    __main__.py          # python -m Services.robot_comm.server  → поднять sim для тестов/UI
  tests/
    test_codec.py        # без сети (всегда идёт)
    test_client.py       # против sim_robot (read_position/read_encoder/send_job)
```

> **sim_robot перенесён из Фазы 5 в Фазу 0 (P1.5):** без фейк-робота нельзя разрабатывать и
> тестировать UI (Фаза 3) и плагины без железа, и CI не прогонит round-trip. Паттерн готов —
> `Services/modbus/server/` (рабочий SimDevice). Это ~50-100 строк, окупается сразу.

**Порт из `robot/universal2/pc_robot.py`:**
- **Берём:** методы `read_encoder/is_free/job_accepted/read_echo/abort/send_job`, `vfd_*`,
  `get_config/set_config`+обёртки, `read_telemetry`, все `_to_u16/_s16/_dw_to_regs/_regs_to_dw`,
  регистровую карту, `_enable_nodelay/_reconnect/_atomic`, `Lock`.
- **Выбрасываем:** класс `Console`, `feeder`, `_dispatch`, `_HELP`, все `input()/print()`.
- **Чистим:** `print(...)` → опциональный callback `on_error`/`logging`.

**Публичный API (`RobotClientProtocol`):** `connect()/disconnect()/is_connected/get_status()`;
`read_position()->RobotPosition{x_mm,y_mm,z_mm,rz_deg}` (тонкая обёртка над `read_telemetry`,
блок 0x1130 — **главное для калибровки**); `read_encoder()->int`; `send_job/is_free/abort`;
`vfd_run/vfd_set_freq/vfd_stop/vfd_reset_fault/read_vfd_status`; `get_config/set_config`.

**Шаринг между плагинами:** модель владельца (см. «Модель владения соединением» выше) —
владелец создаёт/коннектит/публикует в `runtime`, потребители берут `runtime.get_client()`.

**SRP конфига (P2.1):** `RobotConfig` содержит только транспорт — `host/port/unit_id/
timeout_sec/word_order`. Калибровочные параметры `belt_vector`/`factor_mm` живут в
`CameraCalibration` (Фаза 2), а НЕ в `RobotConfig` — клиент не должен знать про конвейер.

**Graceful-disconnect (P2.4):** владелец регистрирует закрытие сокета на shutdown процесса
(`atexit`/lifecycle `shutdown`), чтобы при убийстве процесса TCP-сокет к роботу освобождался.

**Acceptance:** пакет импортируется без pymodbus (`ROBOT_AVAILABLE=False`);
`test_codec` + `test_client` (против `sim_robot`) зелёные; с железом
`python -m Services.robot_comm pos` возвращает X,Y,Z.

---

## Фаза 1 — Плагин `Plugins/processing/circle_detector`

**Цель:** найти и упорядочить 5 центров кругов.

```
Plugins/processing/circle_detector/
  plugin.py  registers.py  order_points.py  readme.txt
  tests/test_order_points.py
```

**`process(item)` — контурный метод (надёжнее для чёрных кругов на белом):**
1. grayscale → `cv2.threshold(..., THRESH_BINARY_INV)` (опц. `adaptiveThreshold`).
2. `cv2.findContours(RETR_EXTERNAL)`.
3. По контуру `cv2.minEnclosingCircle` → (cx,cy,r); фильтр по `min_radius..max_radius`
   и «кругловатости» `area/(π r²) ≥ circularity_min` (отсекает шум/буквы).
4. Если найдено ≠ 5 — не падать: вернуть всё что нашли + `circle_count` (UI покажет «N из 5»).
5. **`order_points.py`** (чистая ф-ия, юнит-тест): центр = ближайший к центроиду 5 точек
   (index 4); 4 угла по `atan2(y-cy, x-cx)` относительно центроида → 0=в-л,1=в-п,2=н-п,3=н-л.
   **Ограничение (P1.3):** корректно только когда лист ≈ параллелен камере (углы в разных
   квадрантах относительно центроида). При сильном повороте листа `atan2`-сортировка может
   спутать порядок. Триггер fallback: если два угла попали в один квадрант ИЛИ взаимные
   расстояния углов сильно неравны → флаг `order_uncertain=True`, и UI предлагает **ручную
   нумерацию** точек (оператор кликает по кругам в нужном порядке).
6. outputs `circles=[{index,pixel_x,pixel_y,radius}]` + `order_uncertain`; опц. рисует
   кружки+номера (`draw`).

**`registers.py` (`CircleDetectorRegisters`):** `method(contour|hough)`, `thresh`, `adaptive`,
`min_radius`, `max_radius`, `circularity_min`, Hough-ветка (`dp`,`min_dist`,`param1`,`param2`),
`draw`, `expected_count=5`.

**Acceptance:** на синт-картинке (5 чёрных кругов) → 5 центров в правильном порядке;
устойчив к лишним/недостающим. `test_order_points` с перемешанным входом.

---

## Фаза 2 — Плагин `Plugins/control/calibration` (math + персистентность)

**Цель:** хранить 5 точек, читать робота по запросу, строить homography, сохранять per-camera.

```
Plugins/control/calibration/
  plugin.py  registers.py  readme.txt
  calibration_math.py    # чистые ф-ии: compute_homography, image_to_robot, reproj_error
  store.py               # CalibrationStore: load/save json per camera_id
  tests/test_calibration_math.py
```

**Модель данных:**
```python
@dataclass
class CalibrationPoint:
    pixel_x: float; pixel_y: float                     # из circle_detector
    robot_x: float; robot_y: float; robot_z: float     # из read_position, редактируемо вручную

@dataclass
class CameraCalibration:
    camera_id: str                                     # имя камеры в рецепте
    points: list[CalibrationPoint]                     # 5: [0..3]=углы, [4]=центр
    homography: list[list[float]] | None               # 3x3, pixel(x,y)→robot(x,y) мм
    transform_kind: str = "homography"
    encoder_at_capture: int = 0                         # E_capture (пульсы) в момент кадра
    encoder_offset: int = 0                             # дельта камера→рабочая зона
    factor_mm: float = 0.144473                         # мм/пульс
    belt_vector: tuple[float,float] = (0.0, -1.0)       # UX,UY направление ленты
    units: str = "mm"
    reproj_error_px: float = 0.0                        # RMS reproj по всем точкам (центр подсвечен)
    timestamp: str = ""
```

**Математика (2D, Z информативно):**
- **Homography по всем 5 точкам с RANSAC (P1.2):** `cv2.findHomography(pixels_5, robot_5,
  cv2.RANSAC)`, а НЕ `getPerspectiveTransform` по 4 точкам. По 4 точкам нет степеней свободы
  для отбраковки выброса (одна ошибка оператора искривляет всё); 5 точек дают минимальную
  переопределённость → RANSAC отбросит грубую ошибку. Структура forward-compatible под 6-8
  точек (большая площадь) позже.
- **`reproj_error` — RMS по всем точкам** (не только по центральной): прогнать каждую
  `image_to_robot(pixel_i)`, сравнить с измеренной `robot_i`, корень из среднего квадрата.
  Центральная точка (index 4) дополнительно подсвечивается как «особый» индикатор в UI.
- **Учёт энкодера:** `robot_xy_final = H·pixel_xy + Δ·(UX,UY)`, где
  `Δ = (enc_now − encoder_at_capture)·factor_mm`. Та же логика, что `trav` в Lua-роботе.
- Z в преобразование не входит; хранится для информации.

**`encoder_offset` (P2.3):** физическая константа установки (дистанция «камера→рабочая зона»
в пульсах). В срезе — **вводится оператором вручную** в UI (поле + кнопка «Зафиксировать»:
запомнить энкодер в зоне камеры, проехать, запомнить в зоне робота, дельта = offset).
Авто-калибровка offset — позже.

**Команды плагина (round-trip из UI):** `detect_circles`, `read_robot_point{index}`,
`set_point_manual{index,x,y,z}`, `set_pixel_manual{index,px,py}`, `capture_encoder`,
`compute_calibration`, `save_calibration{camera_id}`, `load_calibration{camera_id}`,
`image_to_robot{px,py,enc_now?}`, `get_state`.
`process(item)` кэширует последний `circles`/`frame` (чтобы `detect_circles` отдал по запросу),
pass-through. Доступ к роботу — `runtime.get_client()` (модель владельца).

**Адресация команд (P0.2).** `CommandSender.request_command(target_process, command, args)`
бьёт по **процессу**, имена команд уникальны в рамках процесса. Поэтому команды плагина
регистрируются с namespace **`{plugin_name}.{command}`** (напр. `calibration.read_robot_point`),
а при мульти-камере ноды получают уникальные `plugin_name` (`calibration_cam1`,
`calibration_cam2`). Проверить на старте, поддерживает ли авторегистрация команд namespace;
если нет — это правка во `_auto_register_commands` (отметить в acceptance Фазы 2). В срезе
(1 камера) конфликта нет, но модель данных и UI-адресация сразу делаются namespace-aware.

**Персистентность (`store.py`):** json per camera_id в `data/calibration/{camera_id}.json`,
каталог из env `INSPECTOR_CALIBRATION_DIR` (дефолт `data/calibration/`). `asdict(CameraCalibration)`.
Структура совместима с будущим переносом в yaml-секцию рецепта `calibration:`.
**Переименование камеры (P1.6):** ключ = имя источника в рецепте; при переименовании файл
`{old}.json` не найдётся → калибровка «потеряется». В срезе — tooltip в UI «после
переименования камеры нужна перекалибровка»; авто-миграция файла при rename — долг Фазы 5.

**Acceptance:** по 4 углам homography восстанавливает центр с малой ошибкой; save→load
идентичен; энкодер-сдвиг двигает результат вдоль belt_vector. `test_calibration_math`
(синтетические соответствия + проверка сдвига).

---

## Фаза 3 — UI-вкладка калибровки (MVP)

**Цель:** оператор калибрует через GUI; presenter дёргает плагин round-trip-командами.

```
multiprocess_prototype/frontend/widgets/tabs/services/robot/
  presenter.py    # RobotCalibrationPresenter (round-trip через CommandSender+RequestRunner)
  section.py      # сборка секции (как hikvision/section.py)
  widget.py       # таблица 5×[#,pixel_x,pixel_y,X,Y,Z,«Считать»] + кнопки + превью кадра
  controller.py   # сигналы виджета ↔ presenter
  tests/test_robot_calibration_presenter.py   # view как Protocol/мок, без Qt
```
Регистрация под-вкладки — рядом с hikvision в `services/tab.py`/`_sections.py`.

**Виджет:** **combo «Камера»** (список камер/цепочек активного рецепта — выбор какую
калибруем; адресует команды нужной ноде `calibration` этой цепочки); превью кадра
выбранной камеры с пронумерованными кругами; кнопка «Найти круги» (`detect_circles` →
заполнить pixel_x/pixel_y); таблица 5 строк, колонки `pixel_x,pixel_y` (редактируемо) и
`X,Y,Z` (редактируемо вручную) + кнопка «Считать» в строке (`read_robot_point{index}` →
заполнить X,Y,Z с общего робота); поля `E_capture`/`encoder_offset` + «Зафиксировать
энкодер» (`capture_encoder`); кнопки «Вычислить» (`compute_calibration`, reproj_error
зелёный/красный), «Сохранить», «Загрузить». Переключение камеры — независимые калибровки
(каждая в свой `{camera_id}.json`).

**Доставка кадра в GUI (P1.4).** Детектор живёт в процессе-воркере, GUI — в другом процессе;
полноразмерный поток кадров идёт через SHM-дисплей. Для калибровки нужен **дискретный
snapshot по запросу**, не поток. Решение: команда `detect_circles` возвращает в dict
**JPEG-bytes** кадра с нарисованными пронумерованными кругами (`cv2.imencode('.jpg', ...)`,
~30-50 КБ) + список пиксельных центров. Через RouterManager идёт компактный payload, не
сырой BGR (640×480×3 ≈ 900 КБ). Ограничение размера/формата сжатия — в контракте ответа.
Presenter декодит JPEG и показывает в превью.

**Acceptance:** `detect_circles` возвращает JPEG+центры; «Найти круги» рисует превью и
заполняет пиксели; «Считать» по строке заполняет X,Y,Z с (sim/железного) робота;
«Вычислить»+«Сохранить» работают; калибровка сохраняется per camera_id.
`test_robot_calibration_presenter` (мок view; ответ робота — через `sim_robot`).

---

## Фаза 4 — Плагин `robot_io` (владелец соединения) + мульти-цепочный шаринг робота

`robot_io` — **владелец `RobotClient`** (создаёт/коннектит в `start()`, публикует в
`runtime`, закрывает в `shutdown()` — см. «Модель владения соединением»).
- `Plugins/io/robot_io/` — `send_job` по reject; каждые N кадров `read_telemetry()` →
  `ctx.state_proxy.merge("robot/telemetry", {...})`; команды `send_job/abort/set_config/get_telemetry`.

**Связь с существующим `Plugins/control/robot_control` (P0.3).** `robot_control` уже
**принимает решение** отбраковки (`inspection_result.action = reject|pass`). `robot_io` —
**исполнитель**: читает `item["inspection_result"]["action"]` из upstream `robot_control`
и при `reject` зовёт `send_job(x, y, e_capture)`. Это разделение «решение vs исполнение»
зафиксировать; координаты для job берутся из калибровки (`image_to_robot`).

**Конфликт «калибровка vs send_job» (P2.5).** Во время калибровки робот в ручном режиме
(оператор подводит руку), `robot_io` НЕ должен слать задания. `RobotClient._lock` спасает
от гонки записи, но семантически нужен флаг **«калибровка активна»** (в `state`/через команду)
→ `robot_io` приостанавливает `send_job`, пока флаг взведён. Отметить как явный долг фазы.

**`vfd_control` вынесен из этого плана (P2.2).** Управление лентой через ПЧ INVT GD20 не
участвует в калибровке и перегружает фазу — выносится **отдельным планом** (`vfd-control.md`),
API в `RobotClient` (`vfd_*`) уже готов из Фазы 0, подключить позже.

**Долг этой фазы — один робот на несколько цепочек/процессов:** когда в рецепте >1 камеры
и цепочки разнесены по процессам, ввести **«робот-ноду/процесс»**, владеющую единственным
`RobotClient`; остальные цепочки (их `calibration`) адресуют её через RouterManager-канал
(запрос→ответ), а не создают своё TCP-соединение. Калибровочный `read_robot_point`
маршрутизируется в эту ноду. В срезе (1 камера) — пропускается.

---

## Фаза 5 — Интеграция в прототип + полировка

- Рецепт-пример: одна цепочка камера → `circle_detector` → `calibration` → `robot_io`;
  затем рецепт с **2+ камерами** (по цепочке на камеру, общий робот через робот-ноду).
- Сервис `robot_comm` в каталоге сервисов; вкладка калибровки в навигации.
- **Миграция транспорта (P1.1, hard deadline):** добавить `ModbusDevice.transaction(ops)`,
  перевести `RobotClient.transport` поверх `ModbusDevice` — убрать дубль pymodbus-обёртки.
- Авто-миграция файла калибровки при переименовании камеры (P1.6).
- Догнать долги среза: полный набор тестов `robot_comm`, DECISIONS.md (вкл. принятый долг
  транспорта), STATUS.md, README по эталонам. (`sim_robot` уже сделан в Фазе 0.)

---

## Верификация (E2E)

1. **Без железа:** `python -c "import Services.robot_comm"` (graceful без pymodbus);
   `python -m Services.robot_comm.server` (поднять sim_robot) + `pytest Services/robot_comm`
   (codec + client против sim); `pytest Plugins/processing/circle_detector
   Plugins/control/calibration` (math + order_points).
2. **С железом (тонкий срез):** запустить прототип (`/run-proto`), открыть вкладку
   калибровки → положить лист → «Найти круги» (5 точек) → подвести робота к точке 1 →
   «Считать» (X,Y,Z заполнились) → повторить ×5 → «Вычислить» (reproj_error мал) →
   «Сохранить» → проверить `data/calibration/cam_main.json`.
3. **Smoke Qt:** после правки вкладки — `qt_snapshot` (обязательно для GUI, см. memory).
4. `python scripts/validate.py` + `python scripts/run_framework_tests.py` из корня.

---

## Риски / открытые вопросы

| Риск | Митигация |
|------|-----------|
| `Robot` ещё тестируется на железе | Фаза 0 стартует после стабилизации `robot/universal2`; карту регистров вынести в `core/registers.py` (один источник). |
| pymodbus optional-dep | `ROBOT_AVAILABLE`, кодек/math-тесты идут всегда; сетевые — skip/железо. |
| Порядок 5 точек (P1.3) | `order_points` + юнит-тест; работает при листе ≈ параллельном камере; `order_uncertain` → ручная нумерация в UI. |
| Homography по 4 точкам хрупкая (P1.2) | Строить по всем 5 точкам с `cv2.RANSAC`; `reproj_error` — RMS по всем точкам; центральная подсвечивается. |
| Перспектива/дисторсия объектива | Homography снимает перспективу плоскости; сильная радиальная дисторсия — позже undistort (camera matrix). |
| Шаринг `RobotClient` между плагинами (P0.1) | Модель владельца: `robot_io` создаёт/коннектит/закрывает, публикует в `runtime`; потребители — `runtime.get_client()`. `_lock` сериализует; плагины `thread_safe=False`. |
| Адресация команд к плагину (P0.2) | namespace `{plugin_name}.{command}`; мульти-камера → уникальные `plugin_name`. Команда бьёт по процессу, имена уникальны в процессе. |
| Связь с `robot_control` (P0.3) | `robot_control` решает reject, `robot_io` исполняет `send_job` по `item.inspection_result`. |
| Калибровка vs `send_job` (P2.5) | Флаг «калибровка активна» приостанавливает `send_job` в `robot_io` (ручной режим робота). |
| Один робот ↔ много камер-цепочек (разные процессы) | Срез — 1 камера, владелец-плагин. Мульти — робот-нода владеет соединением, остальные через RouterManager-канал (Фаза 4+). Файл калибровки на камеру (`camera_id`) — конфликтов нет. |
| Кадр в GUI (P1.4) | `detect_circles` отдаёт JPEG-bytes (~30-50 КБ), не сырой BGR; presenter декодит. |
| Тесты без железа | `sim_robot` в Фазе 0 (Modbus-slave с картой робота); UI/плагины тестируются против него. |
| Дубль pymodbus-обёртки (P1.1) | Принятый долг с дедлайном: Фаза 5 мигрирует на `ModbusDevice.transaction(ops)`. |
| Переименование камеры (P1.6) | Tooltip «нужна перекалибровка»; авто-миграция файла — Фаза 5. |

---

## Конвенции коммитов

Ветка `feat/robot-calibration` (или текущая). Каждый коммит — Conventional Commits +
trailers `Why:` и `Layer:` (Фаза 0 → `services`, плагины → `plugins`, вкладка → `prototype`).
`Refs: plans/robot-calibration.md`. Внутренняя копия плана Claude Code —
`~/.claude/plans/glistening-coalescing-pizza.md` (правило dual-save).
