# Phase 2 — Общий мир: лента и один энкодер

Часть плана [`plan.md`](plan.md). **Ред. 2 (2026-09-21)** — фаза переписана под автономную
форму (ред. 1 публиковала энкодер из плагина в топологии прототипа и читала его
source-плагином прототипа — оба отменены 2026-08-31; история в git).

Реализует принцип 5 [`vision.md`](vision.md): устройства не зовут друг друга, они делят
мир. В этой фазе мир — это лента: ПЧ задаёт скорость, лента крутит **один** энкодер, робот
отдаёт его регистром (как на железе), сцена читает его из мира. Второго Modbus-клиента
line→robot не появляется (решение 2026-08-13 в силе): `REG_ENC` — единственный источник
истины, вторая копия счётчика — тот же класс дефекта, что «два задания на одну деталь».

**Процессы стенда после фазы:** `robot` (хост `SimRobotHostPlugin`, владеет лентой и
энкодером) и `camera` (источник сцены → `mjpeg_sink`). Общий мир — `StateProxy` внутри
дерева симулятора, путь `sim.belt.*`.

---

### Task 2.0 — `ctx.state_proxy` у фреймворкового `GenericProcess` (carve-out из прототипа)

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** плагин в любом generic-приложении (`apps/line_sim`, `examples/minimal_app`)
получает рабочий `ctx.state_proxy`: `set` в одном процессе виден через `get`/`subscribe` в
другом. Прототип продолжает работать без изменений поведения.

**Контекст (факты разведки Ф1, [`phase-1`](phase-1-vertical-slice.md) §Разведка):**
`StateProxy` в процессе сегодня создаёт **прототипный** `GenericProcessApp`
(`multiprocess_prototype/generic_process_app.py:23`); фреймворковый `GenericProcess` его не
заводит (`process_module/generic/plugin_orchestrator.py:59`). Серверная половина — store с
непустым посевом у generic-приложения — закрыта Task 1.0 (ADR-APP-007). Эта задача —
клиентская половина. По правилу «запертое в прототипе выделяется, не копируется»
механизм переезжает во фреймворк, а `GenericProcessApp` становится его потребителем.

**Детальная спека — за `manager` перед стартом задачи.** В этой редакции разведка кода
carve-out не проводилась: список файлов и шаги ниже намеренно не выписаны, чтобы не
выдавать догадку за факт. Обязательные вопросы разведки: (1) что именно
`GenericProcessApp` делает сверх создания прокси (подписки, ветка
`processes.<p>.health`?); (2) проходит ли `set` по пути вне посеянного дерева
(`sim.belt.*`) или путь надо сеять через `AppSpec.state_bootstrap`; (3) ADR в
`process_module/DECISIONS.md` или `app_module/DECISIONS.md`.

**Acceptance criteria** (измеримы тестером вслепую):
- [ ] В `examples/minimal_app` и `apps/line_sim` плагин видит `ctx.state_proxy is not None`.
- [ ] Двухпроцессное generic-приложение-фикстура: `set("sim.belt.encoder", {"value": 42})`
      в процессе A → `get("sim.belt.encoder")` в процессе B возвращает `{"value": 42}` в
      течение 2 с; `subscribe("sim.belt.*", cb)` в B получает событие.
- [ ] `backend_ctl` приложения: `state_get("sim.belt.encoder")` возвращает то же значение.
- [ ] Прототип: тесты `multiprocess_prototype` и `python scripts/run_framework_tests.py`
      — не ниже baseline (числа в отчёте); в `multiprocess_prototype/generic_process_app.py`
      не осталось собственного создания прокси — только использование фреймворкового.
- [ ] `sentrux check .` (CLI) — все правила зелёные.

**Out of scope:** любые пути состояния, специфичные для симулятора, — их заводит Task 2.2.
**Dependencies:** Task 1.0. **Module contract:** impl-only.

---

### Task 2.1 — Модель ленты `BeltDrive`: команда ПЧ → скорость → энкодер

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** живая команда ПЧ (та же, что инспектор шлёт на железо через мост
`vfd_belt → robot_main`) меняет **фактическую** скорость приращения энкодера. Лента —
отдельный класс; ядро робота ей пользуется, а не содержит её внутри.

**Контекст:** `RobotSimCore._handle_vfd` уже эмулирует зеркало ПЧ (mailbox `0x1200` /
зеркало `0x1210`, обновление только по пульсу `VFD_FLAG` — как в боевой Lua), но
`_enc_rate` — константа из `__init__`: «инспектор притормозил конвейер» в симе сегодня не
происходит. Ред. 1 предлагала дописать формулу прямо в `_handle_vfd` — отвергнуто:
конвейер — самостоятельное устройство каталога ([`vision.md`](vision.md) §Каталог), и
когда появится ПЧ без моста (`Services/vfd_comm/protocols/gd20_direct.yaml`), той же лентой
должен уметь управлять другой хост. Поэтому: класс ленты + внедрение через конструктор.

Масштаб «Гц → мм/с» реального стенда в коде не найден — остаётся конфигурируемым
параметром (владелец: «точность мира — примерная, достаточно»). Это калибровочная ручка,
а не константа.

**Files:**
- НОВЫЙ `Services/robot_comm/server/belt.py` — `BeltDrive`
  (`# ponytail:` лежит рядом с единственным потребителем; переезжает в `Services/line_sim`,
  когда лентой начнёт управлять второй хост)
- `Services/robot_comm/server/sim_core.py` — `RobotSimCore.__init__(…, belt: BeltDrive |
  None = None)`, `_handle_vfd`, `tick`
- `Services/robot_comm/server/__main__.py` — `--belt-mm-s` строит `BeltDrive`
- `Services/robot_comm/tests/test_belt_drive.py` — тесты автора (hazard)
- `Services/robot_comm/tests/test_sim_register_map_contract.py` — контракт карты регистров
- `Services/robot_comm/server/README.md`, `STATUS.md`

**Steps:**
1. Выяснить по `Services/vfd_comm` (карта `gd20_bridge.yaml`, scale регистра частоты), в
   каких единицах приходит `regs[_REG_VFD_CMD_FREQ]`; зафиксировать масштаб в docstring.
2. `BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)`:
   `command(run: bool, freq_hz: float, reverse: bool = False)`;
   `advance(dt_s: float) -> int` — приращение энкодера в отсчётах за `dt_s`;
   свойство `mm_s`. **Дробный остаток копится между вызовами** — средняя скорость точна
   при любом `dt_s`. Нынешняя формула `max(1, round(...))` так не умеет: она округляет на
   каждом тике и не даёт ленте ехать медленнее одного отсчёта за тик — на малой частоте
   это тихая ложь о скорости.
   `BeltDrive.from_enc_rate(enc_rate, tick_s)` — лента с постоянной скоростью,
   эквивалентной старому параметру.
3. `RobotSimCore`: `belt=None` → `BeltDrive.from_enc_rate(enc_rate, TICK_INTERVAL_S)`
   (поведение до первой команды ПЧ не меняется); `tick()` зовёт `belt.advance(dt)`;
   `_handle_vfd` при пульсе `VFD_FLAG` зовёт `belt.command(run, freq_hz, reverse)`.
   Скорость меняется **только в момент пульса** — это ограничение прошивки, воспроизведено
   намеренно; слово «плавно» нигде не писать.
4. Контракт-тест карты регистров (принцип 3 видения): адреса mailbox ПЧ, которыми
   пользуется `sim_core`, совпадают с адресами из `gd20_bridge.yaml`, откуда их читает
   драйвер. Сегодня это две копии (`sim_core.py:71-76` и yaml) — тест делает расхождение
   красным.
5. Hazard-тест автора: единственный писатель скорости — `tick()` на ticker-потоке;
   проверять синхронно, прямым вызовом `tick()`, без `time.sleep`.

**Acceptance criteria:**
- [ ] `BeltDrive(100.0, 50.0)`; `command(run=True, freq_hz=25.0)`; сумма `advance(0.01)`
      за 1000 вызовов равна **3461** ±1 отсчёт (половина частоты → 50 мм/с →
      500 мм за 10 с; 500 / 0.144473 = 3460.85). В тесте — литерал, а
      `FACTOR_MM == 0.144473` проверяется отдельным assert.
- [ ] `command(run=False, …)` → сумма `advance` равна 0.
- [ ] Малая скорость: `command(run=True, freq_hz=0.5)` (1 мм/с) → за 1000 вызовов
      `advance(0.01)` сумма равна **69** ±1 (10 мм / 0.144473 = 69.2), а **не** 1000
      (старый пол «не меньше отсчёта за тик»).
- [ ] `RobotSimCore(enc_rate=7)` без единой команды ПЧ: энкодер за N тиков растёт так же,
      как до задачи — существующие `test_sim_e2e.py` зелёные без правок.
- [ ] После записи команды ПЧ (run=1, freq, `vfd_flag=1`) и `tick()` скорость ленты
      соответствует команде; конструкторный `enc_rate` больше не действует.
- [ ] Сдвиг любого адреса mailbox в `sim_core.py` на 1 → контракт-тест карты красный.
- [ ] `pytest Services/robot_comm -q` — 0 failed, passed не ниже baseline 127.

**Out of scope:** разгон/торможение по рампе; публикация энкодера наружу (Task 2.2).
**Edge cases:** `freq_max_hz <= 0` → скорость 0 и предупреждение в лог, не исключение;
`freq_hz` вне `[0, freq_max_hz]` → clamp; `reverse=True` → отрицательное приращение
(энкодер квадратурный), знак покрыт тестом.
**Dependencies:** нет. **Module contract:** new-lite (`belt.py`).

---

### Task 2.2 — Энкодер в общем мире: робот публикует, сцена едет

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** процесс `robot` публикует энкодер в мир симулятора; процесс `camera` рисует
**один** тестовый спрайт, положение которого считается из этого значения. Видимое
доказательство: остановил ленту командой ПЧ — спрайт в MJPEG-потоке замер.

**Files:**
- `Plugins/sim/robot_host/plugin.py` — throttled-паблишер энкодера
- НОВЫЙ `Plugins/sim/scene_source/{__init__.py, plugin.py, README.md, STATUS.md, tests/}` —
  `SceneSourcePlugin`: source-плагин **внутри симулятора** (образец формы —
  `Plugins/sources/synthetic_frame_source`). В этой задаче — фон + один спрайт-заглушка;
  движок слоёв подключается в Ф3.4
- `apps/line_sim/pipeline.yaml` — процесс `camera`: `scene_source` → `mjpeg_sink`
  (заменяет заглушку `camera_service/simulator` из Task 1.2); параметр `seed` стенда
- `apps/line_sim/README.md` — путь мира `sim.belt.encoder`

**Steps:**
1. Паблишер в `SimRobotHostPlugin`: каждые `publish_ms` (дефолт 50) —
   `ctx.state_proxy.set("sim.belt.encoder", {"value": core.encoder, "mm_s": belt.mm_s,
   "t": time.monotonic()})`. Без `state_proxy` (Task 2.0 не влита) — плагин живёт,
   `status` сообщает `world: unavailable`.
   Это **состояние мира** — его потребляет сцена. **Наблюдение** идёт отдельной дорогой:
   на том же такте `publish_metric("encoder", …)`, `publish_metric("belt_mm_s", …)`,
   `publish_metric("writes_seen", …)` — уровни с именем (раздел «Наблюдаемость» плана).
   Заодно закрывается замечание ревью Ф1: сегодня `record_metric` зовётся только из
   `cmd_status`/`shutdown`, и без опроса статуса числа не текут.
2. `SceneSourcePlugin.produce()`: читает `ctx.state_proxy.get("sim.belt.encoder",
   default=…)` на каждом кадре (без колбэков — меньше связности), хранит последнее
   значение. Мир пуст (процесс `robot` ещё не поднялся) → кадр с объектом в исходной
   позиции, без исключения.
3. Позиция спрайта: `x_px = (encoder − spawn_encoder) × FACTOR_MM × px_per_mm`;
   `FACTOR_MM` — импортом из `Services.robot_comm.core.registers`, не копией числа.
4. Hazard-тест автора: гонка старта процессов; дыра в публикации (значение старше
   `stale_ms`) — сцена замирает и пишет предупреждение, а не экстраполирует.

**Acceptance criteria** (сим поднят, `backend_ctl` на 8766):
- [ ] `state_get("sim.belt.encoder")` — два снятия с интервалом 1 с, второе `value`
      строго больше первого.
- [ ] Команда «стоп» ПЧ боевым клиентом (`Services/vfd_comm`, протокол `gd20_bridge`, на
      `127.0.0.1:5021`; если его API этого не позволяет — сырой записью mailbox-регистров
      pymodbus-клиентом, с пометкой в отчёте) → два снятия подряд равны. Команда «пуск» с
      `freq_hz > 0` → рост возобновился.
- [ ] Кадры из `http://127.0.0.1:8091/`: центр масс спрайта смещается монотонно, пока
      энкодер растёт, и неподвижен (±1 px), пока лента стоит.
- [ ] Поднят только процесс `camera` (без `robot`) → поток отдаёт кадры, исключений в
      `errors.log` нет.
- [ ] `introspect_telemetry` (порт 8766) → в `levels` процесса `robot` есть `belt_mm_s` и
      `encoder` писателя `sim_robot_host`; после команды «стоп» ПЧ `belt_mm_s == 0`.
      Опрашивать `sim_robot.status` для этого не требуется. (Если уровни не читаются у
      generic-приложения — разрыв ловит Task 1.4; здесь критерий остаётся красным, а не
      переписывается.)
- [ ] В `Plugins/sim/scene_source` нет импортов `Plugins.sim.robot_host` и
      `multiprocess_prototype` (принцип 5: модели не знают друг друга).

**Out of scope:** несколько объектов, спавн/деспавн, реальные спрайты (Ф3).
**Edge cases:** переполнение энкодера (32-бит signed, `RegDW(signed=True)`) — в README
числом: сколько часов прогона на типичной скорости до переполнения; v1 на более длинные
прогоны не рассчитан, и это сказано явно.
**Dependencies:** Task 1.2 (`mjpeg_sink`), Task 2.0, Task 2.1.
**Module contract:** new-lite (`Plugins/sim/scene_source/plugin.py`).
