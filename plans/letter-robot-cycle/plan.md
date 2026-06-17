# Планы: полный цикл укладки слова роботом

**Ветка:** `feat/pult-control-panel` (текущая; работы ведутся в ней)
**Slug:** `letter-robot-cycle`
**Статус:** В работе. Тракт распознавания DONE. Цикл укладки→возврата — в процессе.
**Дедлайн:** Выставка (день написания плана: 2026-06-16, ~2 часа до показа)
**Приоритет задач:** BLOCKER → HIGH → MED → LOW

---

## Контекст

Рецепт `hikvision_letter_robot.yaml` распознаёт букву+угол диска на конвейере
(Hikvision → круги → триггер линии → crop → ml_inference). Цель: замкнуть
**полный цикл укладки слова роботом**:

1. Слово приходит с телефона (`phone.signal_2`).
2. `word_layout` формирует раскладку — какая буква в какой слот, с каким доворотом.
3. Каждый диск, проехавший мимо линии, если нужен для слова — робот берёт с ленты
   (CVT pick по энкодеру) и кладёт в статичный слот слова (place + доворот rz).
4. Когда слово готово — ждём команды с пульта.
5. По `phone.signal_1` (пульт «вернуть») — робот забирает все буквы со стола и
   кладёт обратно на ленту (MODE=3 RETURN). Раскладка сбрасывается.

**Что уже работает (не трогать):**
- транспорт `send_job`/`do_return` (38/38 CVT-регистров совпадают с прошивкой)
- handshake job_flag/place_flag
- машина состояний в `word_layout` (assembler, дедуп дублей, return_trigger)
- диспетчер `robot_enqueue_job` / `robot_return_job` в device hub
- авто-коннект устройств из рецепта (`devices:` секция)
- DRAW-режим, телеметрия, VFD-мост

**Критические пробелы (выявлены аудитом):**
| № | Пробел | Критичность |
|---|--------|-------------|
| 1 | `pixel_to_robot`: нет гомографии-файла → `pick_xy` не выдаётся → раскладка стоит | **BLOCKER** |
| 2 | Симулятор: не настроен для приёма рецепта (host:port в yaml = боевой робот) | **HIGH** |
| 3 | Энкодер: не читается в момент триггера линии, читается позже в драйвере | **HIGH** |
| 4 | Стоп ленты: нет сигнала VFD после `done=True` | **HIGH** |
| 5 | TOOLCHANGE (MODE=4): не реализован в Python / симуляторе | **LOW** (на выставке не нужен) |

---

## Задачи

### Task 1.1 — Linear px→мм в `pixel_to_robot` (BLOCKER)

**Уровень:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Добавить режим линейной калибровки (4 угла ROI → 4 угла в мм робота)
как альтернативу гомографии, чтобы `pick_xy` выдавалось без файла `cam0.yaml`.

**Почему сейчас:** `config/calibration/cam0.yaml` не существует (визард не
запускался). `pixel_to_robot.plugin.py:110` проверяет `if self._h is None: return item`
→ `pick_xy` не добавляется → `word_layout` с `require_pick=True` пропускает
ВСЕ диски → раскладка не идёт совсем.

**Решение:** inline-математика по образцу `robot_scale/plugin.py:80-120`
(4-угловая билинейная интерполяция). Калибровочные точки задаются вручную в
инспекторе/пульте, без файла.

**Файлы:**
```
Plugins/processing/pixel_to_robot/registers.py   # +9 полей linear-режима
Plugins/processing/pixel_to_robot/plugin.py      # ветка use_linear в process()
Plugins/processing/pixel_to_robot/tests/test_pixel_to_robot.py   # новые тесты
multiprocess_prototype/recipes/hikvision_letter_robot.yaml        # config узла
```

**Шаги:**

1. **registers.py** — добавить поля (после `roi_offset_y`):
   ```python
   use_linear: bool = False           # True = linear режим, False = гомография (дефолт)
   # Углы ROI в пикселях (тот же порядок: TL, TR, BR, BL)
   px_tl: list[float] = [0.0, 0.0]
   px_tr: list[float] = [240.0, 0.0]
   px_br: list[float] = [240.0, 360.0]
   px_bl: list[float] = [0.0, 360.0]
   # Соответствующие точки в мм робота
   mm_tl: list[float] = [0.0, 0.0]
   mm_tr: list[float] = [100.0, 0.0]
   mm_br: list[float] = [100.0, 150.0]
   mm_bl: list[float] = [0.0, 150.0]
   ```
   Добавить к readonly: `linear_active` (bool, показывает активный режим).

2. **plugin.py — `_load_calibration`** — обернуть в `if self._reg.use_linear`.
   Если `use_linear=True` — гомографию не грузить, пометить `_h = None`,
   `_reg.loaded = True` (linear-режим «загружен» всегда).

3. **plugin.py — `process`** — после `if self._h is None` добавить ветку:
   ```python
   if self._reg.use_linear:
       x_mm, y_mm = self._linear_interp(center)
   else:
       ...  # гомография (существующий код)
   ```

4. **plugin.py — `_linear_interp(center)`** — билинейная интерполяция:
   ```
   u = (px - px_tl[0]) / (px_tr[0] - px_tl[0])   # нормировка по X
   v = (py - px_tl[1]) / (px_bl[1] - px_tl[1])   # нормировка по Y
   x_mm = (1-u)(1-v)*mm_tl[0] + u(1-v)*mm_tr[0] + uv*mm_br[0] + (1-u)v*mm_bl[0]
   y_mm = (аналогично для Y)
   ```
   Ошибки (деление на 0 при одинаковых углах) — логировать, возвращать item.

5. **hikvision_letter_robot.yaml** — в config узла `pixel_to_robot` добавить:
   ```yaml
   use_linear: true
   px_tl: [0.0, 0.0]          # углы ROI (px, относительно crop 560,240,800,600)
   px_tr: [240.0, 0.0]
   px_br: [240.0, 360.0]
   px_bl: [0.0, 360.0]
   mm_tl: [???, ???]           # ЗАПОЛНИТЬ с владельцем (см. раздел «От владельца»)
   mm_tr: [???, ???]
   mm_br: [???, ???]
   mm_bl: [???, ???]
   ```

6. **тесты** — `test_pixel_to_robot.py`:
   - linear_interp угловые точки (→ должны совпасть с mm_tl..mm_bl)
   - linear_interp центр ROI (→ ожидаемое среднее)
   - use_linear=False + h=None → item без pick_xy (существующий путь)
   - use_linear=True → item с pick_xy даже без файла

**Acceptance criteria:**
- [ ] `pytest Plugins/processing/pixel_to_robot/` зелёный
- [ ] ruff 0 ошибок
- [ ] При `use_linear=True` в рецепте: инспектор видит `loaded=True`,
      `last_x_mm`/`last_y_mm` меняются при проезде дисков
- [ ] `word_layout` начинает эмитить `robot_job` (в логах появляется `robot_enqueue_job`)

**Можно проверить симулятором:** Да — диск в item с `sidecar.center_px=[120, 180]`
(центр ROI) → `pick_xy={x_mm, y_mm}` → word_layout → robot_io → hub (лог).

---

### Task 1.2 — Runnable симулятор для рецепта (HIGH)

**Уровень:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Переключить рецепт на локальный симулятор одним флагом; убедиться,
что полный тракт phone→слово→диск→robot_job отрабатывает без железа.

**Почему сейчас:** `hikvision_letter_robot.yaml` жёстко указывает `host: 192.168.1.7`.
Без переключения любой тест тракта требует живого робота.

**Текущее состояние симулятора:**
- `Services/robot_comm/server/sim_robot.py` — TCP Modbus-slave, слушает `127.0.0.1:5021`
- `Services/robot_comm/server/__main__.py` — `python -m Services.robot_comm.server`
- `RobotSimCore` — эмулирует MODE=0 CVT, MODE=1 DRAW, MODE=3 RETURN полностью
- MODE=2 MANUAL и MODE=4 TOOLCHANGE не реализованы (не нужны для выставки)

**Файлы:**
```
multiprocess_prototype/recipes/hikvision_letter_robot.yaml   # host/port override
```

**Шаги:**

1. В `hikvision_letter_robot.yaml`, секция `devices[0].transport`, добавить
   отдельный блок под комментарием `# СИМУЛЯТОР (для разработки без железа)`:
   ```yaml
   # --- Боевой робот ---
   transport:
     type: tcp
     host: 192.168.1.7
     port: 502
     unit_id: 2
   # --- Симулятор (раскомментировать для тестов без железа) ---
   # transport:
   #   type: tcp
   #   host: 127.0.0.1
   #   port: 5021
   #   unit_id: 2
   ```

2. Добавить в `README` / шапку плана команду запуска:
   ```bash
   # Терминал 1 — симулятор
   python -m Services.robot_comm.server

   # Терминал 2 — рецепт (после раскомментирования transport)
   python multiprocess_prototype/run.py hikvision_letter_robot
   ```

3. Проверить вручную: симулятор стартует, рецепт подключается (`devices:
   robot_main connected`), job отправляется, `REG_FREE=1` возвращается.

**Acceptance criteria:**
- [ ] Симулятор стартует без ошибок: `python -m Services.robot_comm.server`
- [ ] Рецепт с `host: 127.0.0.1 / port: 5021` запускается, `device_hub` логирует
      `robot_main: connected`
- [ ] После отправки слова (через пульт или телефон) в логе появляется
      `robot_enqueue_job` и симулятор проходит цикл job→free

**Можно проверить симулятором:** Это и есть симулятор-тест.

---

### Task 1.3 — Энкодер в момент триггера линии (HIGH)

**Уровень:** Senior (Sonnet)
**Assignee:** developer
**Goal:** Передать значение энкодера (REG_ENC) в item в момент пересечения
линии, чтобы `word_layout` → `robot_io` → `robot_driver` использовал точный
`e_capture` для CVT-трекинга.

**Почему сейчас:** `word_layout/registers.py` имеет поле `encoder_source="e_capture"`;
`plugin.py:199` делает `e_cap = item.get(self._reg.encoder_source)` — ждёт значения.
Но `center_crop` не пишет `e_capture` в item. Fallback в `robot_driver.py:259-264`:
читает энкодер позже (в tick() воркера devices), когда диск уже уехал на несколько см.

**Текущий fallback приемлем для выставки** (CVT компенсирует лаг трекингом прошивки),
но при точном позиционировании нужен e_capture момента кадра.

**Архитектурная проблема:** `center_crop` (процесс `recog`) не имеет доступа к
`RobotClient` (тот в процессе `devices`). Прямой Modbus из узла обработки — нарушает
слои (Plugins → Services).

**Решение (минимальное, не нарушает слои):**
Использовать **кэшированный энкодер из state**: прошивка `cvt_universal_full.lua`
через Mirror-таску постоянно публикует `REG_ENC` в состояние. `robot_driver` уже
обновляет state-поля (telemetry). `word_layout` или узел до него мог бы читать
`state["devices.robot_main.encoder"]` через StateProxy.

**Альтернативное решение (проще):** Ничего не менять. Оставить fallback драйвера
(`robot_driver.py:259-264`), который читает энкодер один раз при обработке job.
Это достаточно: Modbus 1 запрос ≈ 2-5 мс, CVT-трекинг компенсирует оставшийся лаг.

**Файлы (если делать кэш-путь):**
```
Plugins/processing/word_layout/registers.py   # поле encoder_state_key
Plugins/processing/word_layout/plugin.py      # чтение из ctx.state_proxy
```

**Шаги (кэш-путь):**

1. `WordLayoutRegisters` — добавить:
   ```python
   encoder_state_key: str = "devices.robot_main.encoder"  # ключ в state (0 = не читать)
   ```

2. `plugin.py:configure` — получить `ctx.state_proxy` (если API позволяет).

3. `plugin.py:process` — перед `assembler.offer()`:
   ```python
   e_cap = item.get(self._reg.encoder_source)   # из item (если pixel_to_robot передаст)
   if e_cap is None and self._reg.encoder_state_key:
       e_cap = ctx.state_proxy.get(self._reg.encoder_state_key)
   ```

4. При `e_cap is not None` — добавить в `pose["e_capture"]`.

**Acceptance criteria:**
- [ ] Если `encoder_state_key` указан и state содержит ключ — `pose.e_capture` заполнен
- [ ] Если state пуст — fallback к `robot_driver` (без ошибок)
- [ ] Тест: `test_plugin.py` — item без e_capture + state с ключом → pose с e_capture

**Можно проверить симулятором:** Да — симулятор пишет энкодер в REG_ENC;
если state-bridge работает, word_layout увидит значение.

**Приоритет для выставки:** Можно пропустить — fallback в `robot_driver` достаточен.

---

### Task 1.4 — Стоп ленты после `done=True` (HIGH)

**Уровень:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Когда `word_layout.done=True` (все буквы уложены) — автоматически
остановить ленту (VFD), чтобы следующие диски не уезжали мимо.

**Почему сейчас:** `word_layout` публикует `done=True` в state, но никто не
реагирует. Лента продолжает крутиться. Диски едут дальше (и падают с конца ленты).

**Где управляется VFD:** `device_hub/drivers/vfd_bridge_driver.py` (или
`robot_driver` через VFD-мост). Команды: `vfd_stop` / `vfd_set_freq`.

**Варианты:**

- **Вариант A (рекомендуется для выставки):** Добавить выходной порт `belt_stop`
  в `word_layout` — пустой сигнал при `done=True`. В рецепте связать с отдельным
  плагином-триггером команды `vfd_stop` в device hub. Слои соблюдены.

- **Вариант B (быстрее):** Добавить в `robot_io` проверку `item.get("belt_stop")`
  → `DeviceHubClient.request("vfd_stop", {device_id: "vfd_belt"})`.

**Файлы (Вариант A):**
```
Plugins/processing/word_layout/plugin.py    # emit belt_stop при done
Plugins/io/robot_io/plugin.py               # forward belt_stop → vfd_stop
multiprocess_prototype/recipes/hikvision_letter_robot.yaml  # wire belt_stop
```

**Шаги (Вариант B — быстрее):**

1. `word_layout/plugin.py` — при `assembler.done` стал True первый раз:
   ```python
   item["belt_stop"] = True
   ```

2. `robot_io/plugin.py:process` — после обработки robot_job:
   ```python
   if item.get("belt_stop"):
       self._deque.append({"_command": "vfd_stop", "device_id": self._reg.vfd_device_id})
   ```

3. `robot_io/registers.py` — добавить `vfd_device_id: str = "vfd_belt"`.

4. `robot_io/plugin.py:_forwarder_loop` — различать `_command`:
   `robot_enqueue_job` / `robot_return_job` / `vfd_stop` → соответствующий hub-запрос.

5. Рецепт: убедиться что `vfd_belt` есть в `devices:` (уже есть, строка 68).

**Acceptance criteria:**
- [ ] При `assembler.done=True` в item появляется `belt_stop=True`
- [ ] `robot_io` форвардит `vfd_stop` в hub
- [ ] `vfd_belt` останавливается (лог `vfd_stop OK`)
- [ ] После `reset()` (signal_1 → return → done) лента НЕ стартует автоматически
      (рестарт — вручную)

**Можно проверить симулятором:** Частично (device hub + vfd_bridge_driver можно
запустить; точная симуляция VFD-моста зависит от наличия robot_main-соединения).

---

### Task 1.5 — Smoke: полный цикл на железе (HIGH)

**Уровень:** Middle (Sonnet)
**Assignee:** developer / владелец
**Goal:** Запустить `hikvision_letter_robot.yaml` с боевым роботом, отправить
слово с телефона, убедиться что робот укладывает буквы в слоты, по signal_1 —
возвращает на ленту.

**Предусловия:**
- Task 1.1 выполнена (pick_xy приходит, use_linear=True + mm-точки от владельца)
- Рецепт настроен: `host: 192.168.1.7, port: 502`
- Камера Hikvision подключена, MVS SDK присутствует
- Робот включён (192.168.1.7:502), лента работает

**Шаги:**

1. Запустить: `python multiprocess_prototype/run.py hikvision_letter_robot`
2. Убедиться: `devices: robot_main connected`, `vfd_belt connected`
3. Отправить слово с телефона (или записать в `word_layout.target_word` через пульт)
4. Проверить в инспекторе: `word_layout.slots_total / slots_filled / next_letter`
5. Пустить диски по ленте → наблюдать pick+place в лог (`robot_enqueue_job`)
6. После `done=True`: отправить signal_1 с телефона → RETURN в лог, буквы на ленту
7. Сбросить: следующее слово, повторить

**Acceptance criteria:**
- [ ] Робот физически берёт диск с ленты (pick по CVT)
- [ ] Диск кладётся в ожидаемый слот (place_x/y из word_layout)
- [ ] Доворот rz соответствует `angle_deg` из ml_inference
- [ ] После signal_1 робот возвращает все буквы (MODE=3 RETURN)
- [ ] Лента останавливается при `done=True` (Task 1.4)

**Можно проверить симулятором:** Нет — smoke только на железе.

---

### Task 2.1 — TOOLCHANGE (MODE=4) в Python-слое (LOW)

**Уровень:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить поддержку MODE=4 (TOOLCHANGE) в `registers.py`, `client.py`,
`sim_core.py` по паттерну MODE=3 RETURN.

**Почему LOW:** На выставке робот работает только в MODE=0 CVT (укладка).
TOOLCHANGE нужен при переходе DRAW → CVT или обслуживании. Не критично сейчас.

**Файлы:**
```
Services/robot_comm/core/registers.py          # REG_TOOL_FLAG/TARGET/BUSY/CUR 0x1360..0x1363
Services/robot_comm/core/client.py             # do_toolchange(target: int) -> bool
Services/robot_comm/server/sim_core.py         # _handle_toolchange()
Services/robot_comm/core/protocols/delta_universal3.yaml  # toolchange секция
Services/robot_comm/tests/test_client.py       # тест do_toolchange
```

**Шаги:**

1. `registers.py` — добавить константы:
   ```python
   REG_TOOL_FLAG   = 0x1360   # ПК → 1: команда готова
   REG_TOOL_TARGET = 0x1361   # ПК: целевой инструмент (0/1/2)
   REG_TOOL_BUSY   = 0x1362   # Робот → 1: выполняет смену
   REG_TOOL_CUR    = 0x1363   # Робот: текущий инструмент (зеркало)
   ```
   В `build_register_map()` — добавить эти адреса.

2. `client.py` — метод `do_toolchange(target: int, timeout: float = 30.0) -> bool`
   по паттерну `do_return()` (line 298-315):
   ```python
   write tool_target, set tool_flag=1
   wait: tool_flag→0 (приём)
   wait: tool_busy 1→0 (исполнение)
   ```

3. `sim_core.py` — `_handle_toolchange()` в tick():
   ```python
   if tool_flag == 1:
       self.w(REG_TOOL_FLAG, 0)    # подтверждение
       self.w(REG_TOOL_BUSY, 1)
       # через toolchange_ticks
       self.w(REG_TOOL_CUR, tool_target)
       self.w(REG_TOOL_BUSY, 0)
   ```

4. `robot_driver.py` — `_op_toolchange(args)` в `_OPS` dict.

5. Тест: `test_client.py` — `do_toolchange(1)` → `REG_TOOL_CUR==1` (через FakeTransport).

**Acceptance criteria:**
- [ ] `do_toolchange(1)` отрабатывает на симуляторе без ошибок
- [ ] `test_client.py::test_do_toolchange` зелёный
- [ ] `robot_driver.call("toolchange", {target: 1})` проходит через _OPS

**Можно проверить симулятором:** Да — полностью.

---

## Проверка на симуляторе

**Подготовка:**

```bash
# Терминал 1 — поднять симулятор
python -m Services.robot_comm.server
# Ожидаемый вывод: "sim_robot слушает 127.0.0.1:5021 (unit 2); карта universal3..."
```

**Рецепт для симулятора** — раскомментировать в `hikvision_letter_robot.yaml`:
```yaml
# transport:
#   type: tcp
#   host: 127.0.0.1
#   port: 5021
#   unit_id: 2
```

```bash
# Терминал 2 — запустить рецепт
python multiprocess_prototype/run.py hikvision_letter_robot
```

**Что проверять в симуляторе:**

| Проверка | Что смотреть |
|----------|-------------|
| robot_main connected | лог `device_hub: robot_main connected to 127.0.0.1:5021` |
| Task 1.1: pick_xy работает | инспектор `pixel_to_robot.loaded=True, last_x_mm≠0` |
| Task 1.1: job уходит | лог `robot_enqueue_job {x_mm, y_mm, place_x, place_y}` |
| CVT job принят | симулятор лог `[sim] job accepted, ticks=50` |
| Слово готово | `word_layout.done=True`, `slots_filled = slots_total` |
| Task 1.4: лента стоп | лог `vfd_stop → vfd_belt` |
| RETURN: signal_1 | лог `robot_return_job × N`, симулятор `return accepted` |
| Сброс | `word_layout.done=False`, assembler сброшен |

**Unit-тесты (без запуска рецепта):**
```bash
# Из корня проекта
pytest Plugins/processing/pixel_to_robot/         # Task 1.1
pytest Plugins/processing/word_layout/            # логика раскладки
pytest Plugins/io/robot_io/                       # форвардер
pytest Services/robot_comm/tests/                 # транспорт + симулятор
```

---

## Проверка на живом роботе

**Предусловия:**
- Камера Hikvision: MVS SDK (`MvCameraControl.dll`), камера на `camera_index: 0`
- Робот: `192.168.1.7:502, unit_id: 2`, включён, прошивка `cvt_universal_full.lua` загружена
- ПЧ лента: подключён через VFD-мост (`gd20_bridge` поверх `robot_main`)
- Телефон: сервис `phone_gateway` запущен и телефон подключён по WiFi

**Калибровка ROI (Task 1.1, linear-режим):**
1. Запустить рецепт, открыть вкладку `maskview` / `draw` — видеть ROI
2. Взять 4 угловые точки ROI (560,240) + (800,240) + (800,600) + (560,600) в пикселях
3. Измерить или зафиксировать вручную соответствующие мм-координаты робота (см. ниже)
4. Вписать в инспектор `pixel_to_robot`: `px_tl/tr/br/bl` и `mm_tl/tr/br/bl`

**Smoke-последовательность на железе:**

1. `python multiprocess_prototype/run.py hikvision_letter_robot`
2. Убедиться: `robot_main: connected`, `vfd_belt: connected`
3. Включить ленту: через VFD-команду или физически
4. Настроить `word_layout.target_word = "КОТ"` (3 буквы — минимум)
5. Пустить диски. Наблюдать:
   - `circle_detector` находит круги
   - `line_filter` срабатывает (триггер в логах)
   - `ml_inference` выдаёт предсказания
   - `pixel_to_robot` выдаёт `pick_xy`
   - `word_layout` выдаёт `robot_job` (первый незаполненный слот)
   - Робот движется (CVT pick → place)
6. После 3 букв: `done=True`, лента стоп
7. С телефона: нажать кнопку `signal_1`
8. Робот: RETURN × 3 (все буквы на ленту)
9. Раскладка сброшена → следующее слово

---

## Что нужно от владельца

### Калибровочные данные (для Task 1.1 — КРИТИЧНО)

Нужно измерить 4 точки соответствия ROI↔робот. **ROI зафиксирован: (560,240)→(800,600)
в исходном кадре 1440×1080** (локальные координаты crop: 0,0→240,360).

Требуется (в системе координат РОБОТА, мм, как посылает `send_job`):

| Угол ROI | Пиксели ROI (локал.) | Мм робота (заполнить) |
|----------|---------------------|----------------------|
| TL (лев-верх) | [0, 0] | [?, ?] |
| TR (прав-верх) | [240, 0] | [?, ?] |
| BR (прав-низ) | [240, 360] | [?, ?] |
| BL (лев-низ) | [0, 360] | [?, ?] |

**Как получить:** В режиме MANUAL (MODE=2) подвести захват к углу поля укладки
на ленте → считать `REG_X / REG_Y` (0x1101, 0x1102) → перевести из 0.1мм в мм
(делить на 10). Повторить для 4 углов.

### Параметры раскладки (для `word_layout`)

Задаются через инспектор, но для рецепта удобнее сразу вписать:

| Поле | Что означает | Уточнить |
|------|-------------|---------|
| `first_x_mm`, `first_y_mm` | Слот №1 (первая буква слева) в мм робота | ? мм |
| `last_x_mm`, `last_y_mm` | Последний слот или `pitch_mm` (шаг в мм) | ? мм или шаг |
| `place_z_mm` | Глубина опускания при укладке (отрицательное) | ? мм |
| `angle_zero_deg` | Угол «нулевого» положения диска (ровно) | 0° или ? |
| `angle_sign` | Направление доворота (+1 или -1) | +1 или -1 |

### Подтверждение режима работы

- Лента: скорость ПЧ по умолчанию `default_freq_hz: 10.0` — подходит?
- CVT: диски на ленте появляются с интервалом ≥ 2 с? (робот не успеет взять быстрее)
- Слово: максимум 8-10 букв на один цикл (размер стола)?
- После RETURN: нужен ли авто-старт ленты или вручную?

---

## Открытые вопросы (follow-up после выставки)

1. **Автоматическая остановка CVT после done:** сейчас лента стопится по сигналу,
   но активные CVT-задания в очереди могут ещё выполняться. Нужен flush.
2. **Два слова / несколько строк:** `word_layout` поддерживает пробел как gap,
   но геометрия двух независимых строк — follow-up.
3. **Визард калибровки камера↔робот:** полноценная гомография через
   `camera_robot_calibration` — точнее linear-режима, но требует калибровочного сеанса.
4. **TOOLCHANGE (Task 2.1):** нужен при смене инструмента DRAW↔CVT. После выставки.
5. **Graceful-stop debt:** 5с-ханг при switch/shutdown рецепта — отдельный план
   `graceful-stop-debt`.
6. **Сброс e_capture точнее:** energy кэш через state-proxy (Task 1.3,
   если fallback будет давать промахи).

---

## Прогресс

- [x] Аудит тракта (cycle map + sim audit + gap analysis) — 2026-06-16
- [ ] Task 1.1 — linear px→мм в pixel_to_robot
- [ ] Task 1.2 — runnable симулятор для рецепта
- [ ] Task 1.3 — энкодер в момент триггера (опц.)
- [ ] Task 1.4 — стоп ленты после done
- [ ] Task 1.5 — smoke на живом роботе
- [ ] Task 2.1 — TOOLCHANGE (LOW, после выставки)
