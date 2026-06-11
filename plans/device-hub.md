# План: device-hub — always-on процесс устройств, реестр, YAML-протоколы, универсальные вкладки

**Slug:** `device-hub` • **Ветка:** `feat/robot-vfd-services` (продолжение) • **Dual-save:** `plans/device-hub.md`
**Refs в коммитах:** `Refs: plans/device-hub.md`
**Ревью:** Fable, APPROVE WITH NOTES — Б1/Б2 и улучшения 1–8 внесены в текст ниже (помечены `[ревью]`)

## Статус выполнения

- [x] **Фаза 0** — YAML-протоколы + загрузчик (protocol_file.py, 3 протокола, 80 parity/loader-тестов) — `32cdf2f8`
- [x] **Фаза 1** — Services/device_hub: реестр, DeviceManager, драйверы, 90 тестов (см. git log: `feat(device_hub)`)
- [ ] **Фаза 2** — процесс devices: плагин, base.yaml, клиент, баг protected, restart_policy
- [ ] **Фаза 3** — тонкий robot_io, рецепт v4, devices_sync
- [ ] **Фаза 4** — GUI: вкладки Робот/ПЧ/Камеры + devices_common
- [ ] **Фаза 5** — миграция/чистка, ADR, sync доков
- [ ] **Сквозная верификация** — pytest, sim E2E, qt-mcp smoke, protected-инвариант

## Контекст

Фазы 0–5 плана `robot-vfd-services` дали рабочие сервисы (`Services/modbus` универсальный + `robot_comm`/`vfd_comm` + симулятор + parity-тесты с отлаженным `pc_full.py`). Но архитектура владения не устроила владельца:

- соединением владеет pipeline-плагин `robot_io` → **ручное управление без запущенного рецепта невозможно**;
- ПЧ-управление зашито во вкладку робота, хотя это отдельный сервис;
- карты регистров зашиты кодом — нельзя «зарегистрировать 10 ПЧ и 3 робота» без программиста;
- co-location трёх плагинов в одном процессе (ADR-RC-003) — ограничение, рождённое владением-в-плагине.

**Решения владельца (2026-06-11):**
1. Отдельный **always-on процесс `devices`** (protected, как `gui`) — владеет ВСЕМИ соединениями; GUI и плагины ходят к нему по IPC. Честный анализ: IPC-хоп 0.2–2 мс против Modbus-операции 2–50 мс — накладные расходы пренебрежимы; tight-loop'ы (feeder CVT) живут внутри хоста.
2. **Реестр устройств** — экземпляры (id, имя, вид, транспорт, протокол, параметры), CRUD из GUI, персистентность `devices.yaml`.
3. **Файлы-протоколы YAML** → RegisterMap (транспорт) + метаданные min/max/unit/hint (GUI). Решение: YAML, не SchemaBase-кодом.
4. **Универсальные вкладки**: «Робот» (без ПЧ), «ПЧ» (отдельная, выбор связи: TCP на адрес робота-моста / bridge / будущий RTU), «Камеры» (hikvision тоже в реестр). Каждая — выпадающий список устройств, работают всегда.
5. **Per-device конфиг в рецепте** — секция `devices:` (upsert в реестр при активации).
6. Плагины — тонкие: `device_id` в конфиге + IPC-команды в `devices`.

## Зафиксированные дизайн-решения

### Р1. Слои и размещение

```
multiprocess_framework  — НЕ трогаем (вся машинерия есть)
Services/modbus         — + core/protocol_file.py (загрузчик YAML-протоколов)
Services/robot_comm     — + protocols/delta_universal3.yaml; runtime.py → удалить (Фаза 5)
Services/vfd_comm       — + protocols/gd20_bridge.yaml, gd20_direct.yaml
Services/device_hub     — НОВЫЙ: DeviceEntry, RegistryStore, DeviceManager, драйверы, фабрика транспортов
Plugins/hub/device_hub  — НОВЫЙ тонкий плагин (commands → DeviceManager) + DeviceHubClient для плагинов
Plugins/io/robot_io     — тонкий job-форвардер; vfd_control/robot_draw — удаляются (логика в hub)
multiprocess_prototype  — base.yaml (+процесс devices), recipes (devices:-секция), GUI-вкладки
```

Загрузчик протоколов — в `Services/modbus` (там живёт `RegisterMap`); файлы протоколов — рядом с сервисом устройства (`Services/<svc>/protocols/`). `Services/device_hub` импортирует соседей по слою (как `sql` ← другие) — законно.

### Р2. DeviceEntry + devices.yaml

Dataclass + Dict-at-Boundary (НЕ SchemaBase — доменная сущность Services-слоя):

```python
# Services/device_hub/registry/entry.py
@dataclass
class DeviceEntry:
    id: str                 # slug: "robot_main", "vfd_belt_1"
    name: str               # "Робот Delta №1"
    kind: str               # "robot" | "vfd" | "hikvision"
    protocol: str = ""      # имя протокола без .yaml; "" для hikvision
    transport: dict = field(default_factory=dict)   # Р4
    params: dict = field(default_factory=dict)      # kind-специфика
    enabled: bool = True
    auto_connect: bool = False
    origin: str = "manual"  # "manual" | "recipe:<slug>"
    # to_dict()/from_dict() с валидацией id/kind/transport.type
```

`data/devices.yaml` (путь — параметр `registry_path` плагина в base.yaml):

```yaml
version: 1
devices:
  - id: robot_main
    name: "Робот Delta"
    kind: robot
    protocol: delta_universal3
    transport: {type: tcp, host: 192.168.1.7, port: 502, unit_id: 2}
    params: {word_order: little, feed_poll_s: 0.05, telemetry_interval_s: 0.5}
  - id: vfd_belt
    name: "ПЧ лента"
    kind: vfd
    protocol: gd20_bridge
    transport: {type: bridge, bridge: robot_main}
    params: {freq_max_hz: 50.0, default_freq_hz: 10.0, poll_interval_s: 0.5, stale_polls_limit: 6}
```

Персистентность — **простой atomic-YAML store** (`registry/store.py`, образец `multiprocess_prototype/adapters/stores/recipe_store.py`: tmp + `os.replace`). НЕ ConfigManager (ConfigStore — shared-memory, не диск).

### Р3. Формат YAML-протокола + загрузчик

Один файл = протокол одного устройства. Типы записей зеркалят DSL `register_map.py` (reg/dw/block) + GUI-метаданные. Высокоуровневых write-команд в файле НЕТ — командная семантика остаётся в клиентах (`RobotClient`/`VfdClient`).

```yaml
# Services/vfd_comm/protocols/gd20_bridge.yaml
name: gd20_bridge
kind: vfd
description: "INVT GD20 через RS-485-мост робота (mailbox, Lua)"
word_order: little
registers:
  cmd_run:   {type: reg, address: 0x1200, access: w, label: "Пуск"}
  cmd_dir:   {type: reg, address: 0x1201, access: w, label: "Направление"}
  cmd_freq:  {type: reg, address: 0x1202, access: w, scale: 100, unit: "Гц", min: 0, max: 50, default: 10, label: "Частота"}
  cmd_reset: {type: reg, address: 0x1203, access: w, label: "Сброс аварии"}
  flag:      {type: reg, address: 0x1204, access: rw, label: "VFD_FLAG (маркер)"}
  status:
    type: block
    address: 0x1210
    access: r
    fields:
      - {name: running, label: "Вращение"}
      - {name: out_freq_hz, scale: 100, unit: "Гц"}
      - {name: current_a, scale: 10, unit: "А"}
      - {name: dcbus_v, scale: 10, unit: "В"}
      - {name: fault}
      - {name: status_word}
      - {name: heartbeat, label: "Heartbeat моста"}
      - {name: comm_errors, label: "Ошибки RS-485"}
# type: dw → {type: dw, address: 0x1112, signed: true} (энкодер робота)
```

```python
# Services/modbus/core/protocol_file.py
@dataclass(frozen=True)
class RegisterMeta:   # GUI-метаданные регистра/поля
    name: str; kind: str          # "reg"|"dw"|"block"|"field"
    label: str = ""; unit: str = ""; hint: str = ""
    access: str = "r"; scale: float = 1.0; signed: bool = False
    min: float | None = None; max: float | None = None; default: float | None = None
    fields: tuple["RegisterMeta", ...] = ()
    def to_dict(self) -> dict: ...

@dataclass(frozen=True)
class DeviceProtocol:
    name: str; kind: str; description: str
    register_map: RegisterMap       # для транспорта
    meta: dict[str, RegisterMeta]   # для GUI

def load_protocol(path: Path) -> DeviceProtocol: ...
def find_protocols(kind: str | None = None) -> dict[str, Path]:
    """Скан Services/*/protocols/*.yaml."""
```

PyYAML парсит `0x1200` как int нативно. **Parity-инвариант:** YAML-карты эквивалентны существующим python-картам (тест сравнивает имена/адреса/scale/signed/word_order/write_ops). Python-карты остаются source of truth для `RobotClient` (его 46 тестов + parity с pc_full.py НЕ трогаются); `VfdClient` уже принимает `register_map=` — драйвер передаёт карту из протокола.

### Р4. Фабрика транспортов

```python
# Services/device_hub/transports.py
# transport.type:
#   tcp    → собственный ModbusDevice(ModbusConfig(tcp, host, port, unit_id, tcp_nodelay))
#   rtu    → собственный ModbusDevice(rtu, serial, baudrate, parity) — закладка, тест на сборку
#   bridge → RegisterTransport чужого устройства: resolve(transport["bridge"]) → драйвер робота
def build_transport(entry: DeviceEntry, resolve_device) -> RegisterTransport: ...
```

`bridge` шарит соединение И Lock робота (`RobotClient` реализует `RegisterTransport`, transaction атомарна) — сегодняшний путь mailbox/Lua. bridge-устройство не имеет своего connect; `is_connected` делегируется носителю; disconnect носителя → зависимые в degraded.

### Р5. DeviceManager + драйверы

```python
# Services/device_hub/manager.py
class DeviceManager(BaseManager, ObservableMixin):   # правило владельца «всё через BaseManager»
    # CRUD: list/get/upsert/remove (+store.save, +publish_cb(path, dict) — инъекция)
    # lifecycle: connect(id)/disconnect(id); драйверы лениво
    # dispatch: call(id, op, args) -> dict — единая точка (валидация kind/op)
    # describe(id) -> {entry, protocol_meta, conn_state} — для GUI-форм
    # register_driver_factory(kind, factory) — расширяемый реестр драйверов

# Services/device_hub/drivers/base.py — BaseDeviceDriver(BaseManager, ObservableMixin):
#   kind; connect()/disconnect()/is_connected; tick(stop_event) -> dict|None (шаг поллинга → snapshot);
#   call(op, args) -> dict; stats (tx_ok/tx_err/reconnects/last_latency_ms)
#   [ревью У7] драйверы наследуют BaseManager+ObservableMixin (правило владельца), не голый Protocol
```

**[ревью Б2] Контракт исполнения команд — КРИТИЧНО.** Все команды процесса исполняются в ОДНОМ
приёмном потоке `message_processor` (`system_threads.py:67` → `_dispatch_command` → CommandManager
синхронно; никакого «отдельного CommandManager-потока» НЕТ). Поэтому:
- `device_connect`/`device_disconnect` — **асинхронные**: ответ сразу `{"status": "ok", "conn": "connecting"}`,
  сам connect — в supervisor/device-воркере, результат — push в `devices.state.<id>.conn`.
  Иначе connect к мёртвому IP (TCP-таймаут секунды) блокирует команды ВСЕХ устройств и каскадит
  таймауты GUI; `robot_enqueue_job` со снимком энкодера опоздает unbounded → промах по конвейеру.
- Быстрые register-операции (2–50 мс: send_job, vfd_run, чтения) — допустимы в командном потоке.
- Всё потенциально блокирующее >100 мс — только в воркере устройства.

**[ревью, паттерн] `kind: generic_modbus`** — включить в Фазу 1: универсальный драйвер для простых
register-устройств = poll списка регистров протокола + `device_read`/`device_write`. Почти ноль кода,
резко повышает ценность реестра («новое устройство без программиста»).

- `drivers/robot_driver.py` — `RobotClient` + **вся feeder-логика из `Plugins/io/robot_io/plugin.py:151-263`** (deque job, _deliver/_wait, throttled-reconnect, телеметрия, manual_mode) + **draw-очередь из robot_draw** (mode-gating CVT/DRAW). Конструктор `(entry, protocol, transport=None, sleep=time.sleep, clock=time.monotonic)` — инъекции как у RobotClient → тестируем без потоков (tick() зовётся тестом напрямую; потоки даёт плагин).
- `drivers/vfd_driver.py` — `VfdClient(transport из фабрики, VfdConfig(из entry.params), register_map=protocol.register_map)`; `tick()` = poll() + ensure_alive → snapshot (bridge_alive).
- `drivers/hikvision_driver.py` — control-only: enum/open/close/params поверх `Services/hikvision_camera` (lazy import SDK); `release()`. Кадры — НЕ здесь (capture-плагин → SHM, как сейчас).

### Р6. Процесс `devices` (base.yaml)

```yaml
# multiprocess_prototype/backend/topology/base.yaml — добавить рядом с gui:
  - process_name: devices
    protected: true
    process_class: multiprocess_prototype.generic_process_app.GenericProcessApp
    plugins:
      - plugin_class: Plugins.hub.device_hub.plugin.DeviceHubPlugin
        plugin_name: device_hub
        category: hub
        registry_path: data/devices.yaml
```

Protected-процессы не трогаются `apply_topology`/`replace_blueprint` (`process_manager_process.py:590-600, 1061-1068`) — рецепты переключаются, devices живёт. **Известный баг «recipe-launch теряет protected:true» проверить и при необходимости закрыть в Фазе 2.**

Плагин: `configure()` — DeviceManager + store.load + публикация реестра в state; `start()` — upsert `recipe_devices` из конфига, auto_connect, supervisor-worker (LOOP: каждому connected-драйверу — воркер `dev_<id>`, крутит `driver.tick()` + публикует snapshot); `shutdown()` — disconnect всех + save.

### Р7. Командный контракт процесса `devices`

Ответы `{"status": "ok"|"error", "message"?, ...}` — формат текущих плагинов (GUI-контроллеры ретаргетятся без переписывания парсинга).

| Группа | Команды |
|---|---|
| Реестр | `device_list`, `device_describe`, `device_upsert`, `device_upsert_many`, `device_remove`, `device_protocols` (по kind) |
| Соединение | `device_connect`, `device_disconnect` |
| Универсальные регистры | `device_read {device_id, name}`, `device_write {device_id, values}` — через RegisterMap с валидацией access/min/max по meta |
| Робот | `robot_enqueue_job`, `robot_send_test_job`, `robot_abort`, `robot_set_mode`, `robot_set_servo`, `robot_set_robot_config`, `robot_get_robot_config`, `robot_get_telemetry`, `robot_read_echo`, `robot_set_manual_mode`, `robot_clear_queue` |
| Рисование | `robot_draw_polyline`, `robot_draw_circle`, `robot_draw_square`, `robot_draw_set_pen`, `robot_draw_set_speed`, `robot_draw_set_overlap`, `robot_draw_abort`, `robot_draw_progress` |
| ПЧ | `vfd_run`, `vfd_set_freq`, `vfd_stop`, `vfd_reset_fault`, `vfd_get_status` |
| Hikvision | `hik_enum`, `hik_open`, `hik_close`, `hik_get_params`, `hik_set_params`, `hik_release` (арбитраж с pipeline) |

**[ревью У8]** Все именованные команды — однострочные алиасы над `DeviceManager.call(id, op, args)`;
логика НЕ расползается по плагину; `introspect.handlers` — источник истины по доступным командам.
`device_connect`/`device_disconnect` — асинхронные (см. Р5/Б2).

### Р8. State-пути (push вместо pull)

```
devices.registry.<id>         = {id, name, kind, protocol, transport_type, origin, enabled}
devices.state.<id>.conn       = "disconnected"|"connecting"|"connected"|"error"
devices.state.<id>.status     = kind-специфика + quality + ts   [ревью, паттерн OPC UA]
devices.state.<id>.stats      = {tx_ok, tx_err, reconnects, last_latency_ms}   [ревью, паттерн]
devices.state.<id>.last_error = str
```

**[ревью] Quality codes:** каждый snapshot несёт `quality: "good"|"stale"|"bad"` + `ts` (supervisor
знает успех/возраст последнего tick() — это +10 строк). GUI сереет по stale вместо показа протухших
цифр — главное отличие профессионального device-сервера (Kepware/Ignition): оператор всегда знает,
верить ли цифре. Диагностические счётчики per device — инкременты в драйвере/фабрике транспорта.

GUI: `runtime.bindings.bind("devices.state.<id>.status...", ...)` (эталон `services/camera/section.py:102-136`); выпадающие списки — подписка на `devices.registry.*`.

### Р9. IPC из pipeline-плагина в devices (проверено по коду)

`RouterManager.request(msg, timeout)` — универсальный (router_module, `router_manager.py:353`), корреляция request_id, путь через PM-хаб. `build_command_message` — `message_module/builders/command_envelopes.py`. **Контракт потока (docstring request):** звать только из worker-потока, НЕ из приёмного цикла и НЕ из `process()` горячего пути.

```python
# Plugins/hub/device_hub/client.py
class DeviceHubClient:
    def __init__(self, ctx, target_process="devices", default_timeout=2.0): ...
    def request(self, command, args, timeout=None) -> dict:
        # build_command_message(target, command, args, sender=<process>)
        # ctx.router_manager.request(msg, timeout)
        # нормализация {"success": False, "error": "timeout"} → {"status": "error", ...}
```

Деградация: плагин не падает; лог once-per-transition; счётчики ошибок в register-полях.

### Р10. Feeder и путь job из vision

Очередь job per-robot-device — в `RobotDriver` (devices-процесс). Тонкий `robot_io`: `process()` НЕ блокируется — кладёт job в локальную forward-deque; worker `job_forwarder` шлёт `robot_enqueue_job` request'ом (timeout 1.0), при недоступности hub — drop + инкремент `jobs_dropped`. Снимок энкодера `e_capture` читает hub при приёме команды (+единицы мс IPC — измерить на sim, компенсация по timestamp — follow-up).

### Р11. Семантика `devices:` в рецепте

Секция **top-level** в рецепте (sibling `blueprint:`). **[ревью, уточнение]** `unwrap_recipe`
(`backend/launch.py:56-58`) возвращает ТОЛЬКО blueprint — top-level `devices:` он выбрасывает,
поэтому извлечение обязано идти от **raw-yaml ДО unwrap** (`extract_recipe_devices(raw)`).
Элементы = формат DeviceEntry.

- **Активация [ревью У3]:** upsert (id совпал → merge transport/params/protocol, `origin="recipe:<slug>"`; ручные name/enabled не затираются) + **connect для ВСЕХ устройств рецепта** (запись в `devices:` подразумевает auto_connect — иначе pipeline молча дропает job'ы до ручного «Подключить»).
- **Деактивация:** записи ОСТАЮТСЯ (ручное управление работает всегда); hub не дисконнектит. Удаление — только вручную.
- **Доставка:** (a) boot — `extract_recipe_devices(raw)` в `multiprocess_prototype/recipes/devices_sync.py`, инжект `recipe_devices:` в конфиг плагина device_hub merged-топологии; (b) hot-активация из GUI — **[ревью У2] `device_upsert_many` + connect ДО replace_blueprint** (devices always-on, ничто не мешает подготовить устройства заранее; иначе свежий robot_io стартует и форвардит в неподключённое устройство → молчаливые drop'ы). Через RequestRunner, не из Qt main.

---

## Фазы

### Фаза 0 — YAML-протоколы + загрузчик (фундамент, без изменения поведения)

**Файлы:** `Services/modbus/core/protocol_file.py` (новый) + экспорт в `__init__.py`; `Services/vfd_comm/protocols/gd20_bridge.yaml`, `gd20_direct.yaml`; `Services/robot_comm/protocols/delta_universal3.yaml`; тесты `test_protocol_file.py` + parity-тесты в обоих сервисах.

1. `RegisterMeta`/`DeviceProtocol` + `load_protocol` (yaml.safe_load; валидация: дубли адресов, scale>0, access∈{r,w,rw}; `ProtocolFileError` с путём и именем записи). Без импорта pymodbus.
2. `find_protocols(kind)` — скан `Services/*/protocols/*.yaml`.
3. Три YAML — точный перенос из `vfd_comm/core/registers.py` и `robot_comm/core/registers.py` (имена/scale/word_order 1:1) + label/unit/min/max/hint.
4. Parity-тесты: names/адреса/scale/signed/word_order совпадают с python-картами; `write_ops({"cmd_freq": 25.0, "flag": 1})` идентичны.

**Acceptance:** все существующие тесты Services зелёные + ~15 новых.
**Коммит:** `feat(modbus): YAML-протоколы устройств — загрузчик RegisterMap + RegisterMeta` / `Layer: services`.

### Фаза 1 — `Services/device_hub`: реестр, DeviceManager, драйверы

**Файлы (новые):** `Services/device_hub/{__init__,errors}.py`, `README.md`, `STATUS.md`, `DECISIONS.md`, `registry/{entry,store}.py`, `transports.py`, `manager.py`, `drivers/{base,robot_driver,vfd_driver,hikvision_driver}.py`, `tests/`.

1. `DeviceEntry` (Р2) + `RegistryStore` (atomic YAML, version, миграционный hook-заглушка).
2. `build_transport` (Р4); rtu — ветка + тест сборки без железа. **[ревью У5]** Валидация bridge-ссылок: детект циклов и неверного kind носителя (`bridge: vfd_belt` — ошибка).
3. `RobotDriver`: перенос feeder из `robot_io/plugin.py:151-263` + draw-логики из `robot_draw` → методы `tick()`/`call()`; инъекции sleep/clock/transport. Наследует BaseDeviceDriver (У7).
4. `VfdDriver`, `HikvisionDriver`, **`GenericModbusDriver` (kind: generic_modbus)** (Р5). **[ревью У4]** VfdDriver: poll приостанавливается, пока носитель-робот в режиме DRAW (Lua не обслуживает VFD_FLAG в DRAW → heartbeat замёрзнет → ложный `VfdBridgeStaleError` на каждом рисовании); вместо тревоги публикуется `quality: stale, reason: "carrier busy"`. Тест на sim.
5. `DeviceManager` (Р5): publish_cb-инъекция; таблица `{kind: {op: handler}}`; bridge-резолв (vfd ждёт connect робота; disconnect робота → vfd degraded). **[ревью У5]** `device_remove` носителя блокируется при живых зависимых bridge-устройствах (или каскадная деградация — выбрать и зафиксировать в ADR). Диагностические счётчики stats (Р8).
6. Тесты: CRUD/persist (tmp_path); RobotDriver против `FakeRobotTransport`+`RobotSimCore` (enqueue→deliver→done, manual_mode, недоступный робот); VfdDriver через sim-зеркало (+DRAW-gating); bridge-резолв + целостность ссылок; generic_modbus read/write.

**Acceptance:** `pytest Services/device_hub` ~30 зелёных; импорт без pymodbus не падает; нет импортов Plugins/prototype (sentrux check_rules).
**Коммит:** `feat(device_hub): сервис реестра устройств — DeviceManager, драйверы robot/vfd/hikvision` / `Layer: services`.

### Фаза 2 — Процесс `devices`: плагин + base.yaml + клиент

**Файлы:** `Plugins/hub/device_hub/{plugin,client,registers,config}.py` + тесты; правка `multiprocess_prototype/backend/topology/base.yaml`.

1. **[ревью У1, ПЕРВАЯ задача]** Баг «recipe-launch теряет protected:true» — он УЖЕ воспроизведён в проекте (memory: «Перезапустить» рестартил gui). Починить (fix-forward) + регрессионный тест на merged-топологию. Весь инвариант «PID devices неизменен при переключении рецептов» стоит на этом флаге.
2. `DeviceHubPlugin`: commands = таблица Р7 → однострочные алиасы `DeviceManager.call()`; register_class (счётчики, last_error); supervisor-worker + per-device воркеры `dev_<id>`; **async connect/disconnect (Б2)** — в воркере, push результата в state; state-публикация по Р8 (quality+ts+stats).
3. `DeviceHubClient` (Р9) + unit-тест (успех/timeout/нет router).
4. base.yaml: процесс devices (Р6); merge_topologies (фундамент побеждает при коллизии имён). **[ревью У6]** `registry_path` резолвить от корня проекта/env (`INSPECTOR_DATA_DIR`-стиль), НЕ от CWD дочернего процесса.
5. **[ревью Б1]** Крэш devices: `RestartPolicy.enabled = False` по умолчанию (`restart_policy.py:24`) и прототип его НИГДЕ не включает — «PM перезапустит» сегодня НЕПРАВДА. Задача: включить restart_policy для devices и проверить, что рестарт protected-процесса реально поддержан watchdog'ом; если нет — зафиксировать «крэш = ручной рестарт» + GUI-индикация «hub мёртв» (quality=bad по всем устройствам).
6. Интеграционный smoke (marker integration): sim_robot → device_upsert(tcp→sim) → device_connect (async: дождаться conn=connected в state) → robot_send_test_job → jobs_done=1 → vfd_run/vfd_get_status через bridge.

**Acceptance:** `run.py` с рецептом БЕЗ устройств поднимается, `devices.registry` в state; `request_command("devices", "device_list")` отвечает; replace_blueprint НЕ перезапускает devices.
**Коммиты:** `feat(plugins): device_hub — always-on плагин + DeviceHubClient` / `Layer: plugins`; `feat(prototype): процесс devices в base.yaml` / `Layer: prototype`.

### Фаза 3 — Тонкие плагины + рецепт + recipe-devices

**Файлы:** переписать `Plugins/io/robot_io/`; удалить `vfd_control`/`robot_draw` из рецепта (пакеты — Фаза 5); `recipes/robot_demo.yaml` v4; новый `multiprocess_prototype/recipes/devices_sync.py`; правки `backend/launch.py` (инжект recipe_devices) + презентер активации рецепта (точку найти по replace_blueprint).

1. `robot_io` v2: конфиг `{device_id}`; forward-deque + worker `job_forwarder` (Р10); команды плагина УДАЛИТЬ (GUI ходит в devices; Фаза 4 в той же ветке до merge). Порты/имя сохранить — wire `*.robot_io.robot_job` не меняется.
2. `robot_demo.yaml` v4: top-level `devices:` (robot_main tcp + vfd_belt bridge); процесс robot — один тонкий `robot_io {device_id: robot_main}`; обновить sim-инструкцию в шапке.
3. `devices_sync.py`: `extract_recipe_devices(raw)` — от raw-yaml ДО unwrap (Р11); инжект в device_hub-конфиг при boot; при hot-активации из GUI — `device_upsert_many` + connect **ДО** replace_blueprint (Р11/У2).
4. Тесты: forward-очередь (фейк-клиент: успех/timeout/drop); extraction+инжект; assemble v4-рецепта.

**Acceptance:** sim_robot + `run.py recipes/robot_demo.yaml`: job доезжает (jobs_done в state); **деактивация рецепта → ручное управление с вкладок продолжает работать**; `pytest Plugins` зелёный.
**Коммиты:** `refactor(plugins): robot_io тонкий — job-форвард в devices` / `Layer: plugins`; `feat(prototype): devices:-секция рецепта + upsert при активации` / `Layer: prototype`.

### Фаза 4 — GUI: вкладки «Робот», «ПЧ», «Камеры»

**Файлы:** новые `frontend/widgets/tabs/services/devices_common/{combo,editor_dialog,presenter}.py` + тесты; новая `services/vfd/{widget,presenter,controller,section}.py` + тесты; правки `services/robot/*` (минус группа ПЧ `widget.py:198-227`, плюс комбо, ретаргет на devices); правки `services/hikvision/*` (комбо+регистрация); `services/_sections.py` (секция «ПЧ»).

1. `devices_common`: `DeviceComboController` (наполнение из `devices.registry.*` через bindings, fallback `device_list`); `DeviceEditorDialog` (id/name/transport-форма по type: tcp host/port/unit | bridge: выбор робота | rtu заглушка; protocol из `device_protocols`; params) → `device_upsert`/`device_remove` через RequestRunner (эталон hikvision `section.py:54-67`).
2. Вкладка «ПЧ» (MVP-эталон hikvision): комбо + Подключить/Отключить + Run/Reverse/Stop/частота/Reset (лимиты из protocol meta через `device_describe`) + статус на bindings + last_error. UX-gating: VFD-кнопки disabled в DRAW-режиме робота-носителя (признак из describe); `comm_errors` — с дельтой.
3. Вкладка «Робот»: убрать группу ПЧ; все вызовы → `request_command("devices", "robot_*", {device_id: combo.current, ...})`; телеметрия — bindings (push), кнопку «Обновить» оставить; рисование → `robot_draw_*`.
4. «Камеры»: комбо hikvision-устройств + регистрация (hik_enum → выбор → upsert); арбитраж — capture-плагин hikvision в start() шлёт `hik_release` через DeviceHubClient (**[ревью]** retry 1–2 раза: на boot devices может подняться позже; деградация — warning).
5. Починить/обновить `test_services_tab.py` под новые секции.

**Acceptance:** qt-mcp smoke ОБЯЗАТЕЛЕН (memory-правило): при ПУСТОМ pipeline — Services→ПЧ: зарегистрировать bridge-устройство, подключить робота, Run/Stop против sim_robot; вкладка Робот: тест-job + живая телеметрия; CRUD переживает рестарт приложения; `pytest multiprocess_prototype/frontend` зелёный.
**Коммиты:** `feat(gui): общие компоненты устройств — комбо, редактор, регистрация`; `feat(gui): вкладка ПЧ + универсализация вкладки Робот` / `Layer: prototype`.

### Фаза 5 — Миграция, чистка, документация

1. Удалить `Services/robot_comm/runtime.py` + тесты + grep `runtime.get_client|set_client`; удалить пакеты `Plugins/control/vfd_control`, `Plugins/control/robot_draw` (grep внешних ссылок: только рецепт и GUI — уже ретаргетнуты).
2. Проверить остальные рецепты на упоминания старых плагинов.
3. ADR в `Services/device_hub/DECISIONS.md`: ADR-DH-001 «один мастер — процесс devices», ADR-DH-002 «bridge-транспорт шарит Lock носителя», ADR-DH-003 «YAML-протокол → RegisterMap+meta»; пометить ADR-RC-003 (co-location) как superseded; `python -m scripts.sync`; обновить `plans/robot-vfd-services.md` (ссылка) и `plans/robot-calibration.md` (robot_io теперь тонкий — калибровка шлёт job в devices).
4. Сводный прогон + `python scripts/validate.py`.

**Коммит:** `chore(services): удалить runtime-владение + docs/ADR device-hub` / `Layer: mixed`.

---

## Верификация (сквозная)

1. **Pytest без железа:** `pytest Services Plugins multiprocess_prototype` — существующие (106 modbus / 46+parity robot_comm / 15 vfd / GUI) зелёные + ~70 новых.
2. **Parity:** `test_parity_universal3.py` НЕ тронут и зелёный — байты на проводе не изменились (драйвер использует тот же RobotClient).
3. **Sim E2E:** `python -m Services.robot_comm.server` → `run.py recipes/robot_demo.yaml` → job с вкладки → jobs_done; стоп рецепта → ручное управление живо; рестарт приложения → устройства на месте.
4. **qt-mcp smoke** вкладок при пустом pipeline (QT_MCP_PROBE=1).
5. **Protected-инвариант:** активация/деактивация рецепта ×3 — PID devices не меняется, соединение с sim не рвётся.
6. **[ревью] Конкурентность:** draw 120 с активен + GUI `vfd_get_status` + телеметрия параллельно — ограниченная латентность ответов, нет дедлока (проверяет Б2 и контракт RLock ModbusDevice).
7. Из корня: `python scripts/validate.py`, `python scripts/run_framework_tests.py`.

## Риски

| Риск | Митигация |
|---|---|
| Два мастера в переходный период | Фазы 3–4 в одной ветке до merge; старый рецепт ломается громко |
| Роутинг плагин→devices не обкатан (request шёл только GUI→backend) | Ранний spike в Фазе 2 (unit + integration smoke) до основной массы кода |
| Блокирующий connect/операция душит командный поток (Б2: ВСЕ команды в одном message_processor-потоке) | async connect/disconnect; блокирующее >100 мс — только в device-воркере; тест конкурентности №6 |
| Латентность IPC для e_capture энкодера | Измерить на sim; командный поток не занят блокирующим (Б2); компенсация по timestamp — follow-up |
| Крэш процесса devices (Б1: RestartPolicy выключен по умолчанию — авто-рестарта СЕЙЧАС НЕТ) | Фаза 2 п.5: включить restart_policy для devices / зафиксировать ручной рестарт + GUI-индикация |
| Ложный stale ПЧ при DRAW робота (Lua не обслуживает mailbox) | У4: VfdDriver гейтит poll по режиму носителя, quality=stale |
| Hikvision SDK handle в always-on процессе | control-only, lazy import, hik_release (+retry), закрытие по таймауту бездействия |
| Опечатки в YAML-протоколах | Строгая валидация загрузчика + parity-тесты с python-картами |

## Паттерны профессиональных device-серверов (итог ревью)

**Взято в план (дёшево):**
- **Quality codes + timestamp** на каждом snapshot (Р8) — оператор всегда знает, верить ли цифре (главное отличие Kepware/Ignition-класса от игрушки).
- **Диагностические счётчики per device** (tx_ok/tx_err/reconnects/last_latency_ms) — разбор «почему лента дёргается» без отладчика.
- **Browse-интерфейс** уже бесплатен: `device_describe` + `device_protocols` + meta из YAML = OPC UA browse в миниатюре.
- **`kind: generic_modbus`** (Фаза 1) — регистрация простых устройств без программиста.

**Осознанно отложено (зафиксировать направлением в ADR):**
- Scan groups / per-tag poll rates — пока хватает per-device `poll_interval_s`; вернуться, когда появится устройство с дорогими и дешёвыми регистрами.
- Подписки на изменение тега (OPC UA monitored items) — StateStore glob-подписки закрывают 90%.
- Store-and-forward (буферизация команд при offline) — для текущего цеха избыточно.
- Enforce «один мастер» технически (Modbus-slave примет второго клиента) — ADR-DH-001 + grep в Фазе 5 достаточно.

## Советы (предложения сверх задания)

1. **`device_read`/`device_write` как универсальные команды** дают бесплатный «инженерный режим»: GUI-таблица всех регистров устройства из protocol meta (read-only сейчас, редактор — потом). Это и есть «подсказки какие параметры есть и их границы».
2. **PROTO_VERSION** (Lua-улучшение №3 из прошлого плана) теперь естественно ложится в протокол-файл: поле `expects: {register: proto_version, value: N}` — hub сверяет при connect. Делать после железа.
3. **Drift-отчёт протоколов:** parity-тест Фазы 0 оставить навсегда — пока python-карты живы, YAML не разъедется.
4. Lua-улучшения и «Железо» из плана robot-vfd-services остаются открытыми — после merge прогнать чек-лист железа уже через вкладки.
