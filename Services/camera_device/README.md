# Services/camera_device

Общее ядро камер: один порт прибора, сеанс с потоком-владельцем, общий набор команд плагина.
Вендорские сервисы (`code_reader`, `hikvision_camera`) и драйвер OpenCV — тонкие драйверы над ним.

**Stability: contract.** Контракт порта (`interface.py`) и честный фейк (`testing/fake_port.py`) — Task 1.5; план записи (`params.py`) — 1.6;
сеанс (`session.py`) — 2.1; профили (`profiles.py`) — 2.2; плагин-заготовка на фейке (`plugin_base.py`, `registers_base.py`) — 1.8.
Общие команды плагина (Р7), публикация телеметрии, живая правка и драйверы — следующие задачи плана; «как добавить вендора» — Task 5.4.

## Purpose

- Один владелец прибора на процесс; все вызовы SDK — из одного потока (ADR-CAM-002).
- Параметр описан один раз — в поле register'а; драйвер держит только таблицу привязки (ADR-CAM-003).
- Один набор команд для всех драйверов, один формат item (ADR-CAM-004).
- Любой драйвер реализует один порт `DevicePort` и проходит один контрактный набор `PortContractSuite`.

## Public API

Экспорт `Services/camera_device/__init__.py` (весь — из [`interface.py`](interface.py)):

- `DevicePort` — порт одного прибора: `open`, `get_param`, `set_param`, `describe_param`, `execute`,
  `start_grabbing`, `get_frame`, `stop_grabbing`, `close` и `capabilities`.
  Состояния: `closed -> opened -> grabbing -> opened -> closed`.
- `DeviceSdk` — жизненный цикл SDK вендора: `acquire`, `release` (счётчик ссылок), `enum_devices`.
- `DeviceIdentity(kind, value, name="")` — как найти прибор (`serial|ip|url|index`).
- `Binding(kind, key, vtype, eps_abs=1e-6)` — привязка параметра к узлу; ядро по `kind` не ветвится.
- `ParamInfo(min, max, inc, entries, access)` — описание узла.
- `RawFrame(data, width, height, pixel_format, frame_num, extras)` — кадр, `data` — `bytearray`-копия.
- `PortError(kind, where, code=None)` — единственная ошибка порта; текст не содержит записываемого значения.

Сеанс и профили — вне `__all__` (импорт по модулю):

- `session.DeviceSession(port, sdk, ident=None, *, timeout_ms=500, watchdog_s=5.0, on_frame, on_stall=None, on_state=None, on_timing=None, run=(), rest=())` —
  сеанс одного прибора; `watchdog_s` должен быть больше `timeout_ms/1000`, иначе `ValueError`. `set_cycle(ident, run, rest) -> bool` (2.3a) заменяет идентичность и план для СЛЕДУЮЩЕГО цикла (`False` при `device_held`, цикл не меняется); `timeout_ms` и `watchdog_s` заморожены при создании сеанса — их правка вступает в силу только после перезапуска процесса. Все вызовы порта и `DeviceSdk` идут из потока-владельца
  (один на цикл `open -> close`, `daemon`); вызывающие потоки только ставят команды.
  - `start(timeout=5.0) -> bool` — `True`, если захват идёт; `stop(timeout=2.0)` — не отбрасывается, `timeout` — срок ожидания вызывающего.
  - Ящик владельца (2.4a): `submit(fn) -> bool`, `call(fn, timeout) -> (ok, результат)`, `apply(steps, policy)` — см. «Живая правка и ящик владельца» ниже.
  - Свойства: `state`, `errors` (ошибки кадров + отказы узлов профилей), `params` (прочитанное, скаляры), `params_status` (`{поле: {"verified", "rc"}}`),
    `param_errors` (`{поле: текст}`), `last_error`, `device` (`DeviceIdentity | None`), `device_held` (поток-владелец жив).
  - Колбэки: `on_frame(RawFrame)` — из владельца, обязателен; `on_state(old, new)` — из потока, сменившего состояние, порядок не гарантирован (истина — `state`);
    `on_stall(имя_вызова, секунды)` — один раз на вызов порта дольше `watchdog_s`; `on_timing(имя, секунды)` — замеры `open`, `stop_grabbing`, `get_frame`, `apply` (запись шага в прибор), `regrab` (перезахват порта).
    Исключение колбэка логируется и не роняет сеанс.
  - `run`/`rest` — последовательности `Step` из `build_plan`: `run` пишется между `open` и `start_grabbing` при каждом старте, `rest` — best-effort после `stop_grabbing`.
- `profiles.ProfileRunner(port, ident, state, log, on_timing=None, call=None)` — `apply_plan(steps)`, `apply_step(step)`, `run_rest(steps, restart_regrab)`:
  запись узла и проверка чтением. Отказ узла план не прерывает; потомки отказавшего родителя (`Step.parent`) не пишутся.
  Живую правку (`DeviceSession.apply`, 2.4a) исполняет владелец тем же `ProfileRunner`.
- `profiles.within_tolerance(binding, inc, target, read)` — допуск по `Binding.vtype`, не по типу значения:
  `float` — `|read − target| ≤ max(inc or 0, 1e-3·|target|, eps_abs)`; `int` — `|read − target| < max(inc or 1, 1)` (без относительного члена);
  прочее (enum по имени элемента, `bool`, `string`) — `==`.
- `params.build_plan(register_cls, values, bindings) -> list[Step]` — упорядоченный план из полей register'а (`FieldMeta.enabled_if`, `ui_group`) и таблицы
  `BINDINGS`; `Step(field, binding, value, skip=None, parent=None)` — `skip` с причиной вместо исключения, `parent` — первый ключ `enabled_if`, не являющийся флагом
  `*_managed`. Группа без флага `<группа>_managed` = `True` не пишется. Нет значения у нужного поля — `ValueError` с именем поля.
- `params.check_bindings(register_cls, bindings, vendor_fields)` — `ValueError`, если ключи `BINDINGS` не совпадают с полями register'а (кроме флагов `*_managed` и `vendor_fields`).

Состояния сеанса (`state`): `idle`, `opening`, `grabbing`, `stopping`, `closed`, `busy`, `not_found`, `error`. Переходы — compare-and-set под замком сеанса:

| Из | В | Что вызывает |
|---|---|---|
| `idle`, `closed` | `opening` | `start()`: стартует поток-владелец |
| `opening` | `grabbing` | `open`, профиль `run`, `start_grabbing` прошли |
| `opening` | `busy` / `not_found` / `error` | `PortError` с `kind` `busy`/`not_found` до успешного `open` (`enum_devices`, `open`); любой другой отказ (в т.ч. профиль `run`, `start_grabbing`) — `error` |
| `grabbing` | `error` | 3 ошибки `get_frame` подряд (`MAX_CONSECUTIVE_ERRORS`) |
| `opening`, `grabbing` | `stopping` | `stop()` |
| `stopping` | `closed` | владелец закрыл прибор (`stop_grabbing`, `rest`, `close`, `release`) |
| `busy`, `not_found`, `error` | `closed` | `stop()`; сам владелец отказное состояние не меняет |

`start()` возвращает `False` сразу из `stopping`, из потока владельца и из отказного состояния при живом владельце (автопереподключения нет).
Новый `start()` после выхода владельца — новый поток. Пауза перезапуска — `restart_policy.backoff_sec` процесса в рецепте, не поле плагина.

Плагин-заготовка (Task 1.8): `plugin_base.CameraDevicePlugin` (`plugin.py` — точка обнаружения), `registers_base.CameraDeviceRegisters`; команды `take_device`,
`release_device`, `get_status`; драйвер только `fake`. Запись `run`/`rest` плагином и общие команды Р7 — Task 2.3a.

Тестовые средства (не входят в `__all__`): `testing/fake_port.py` — `make_port(**opts)`, `from_recording(path, **opts)`;
контрактный набор — `tests/port_contract.py` (`PortContractSuite`, `PortCase`). Опции фейка (умолчания сохраняют поведение 1.5):
`neter_after_stop`, `applied_but_error` (`bool | frozenset[str]`), `busy_for_s`, `capabilities`; для сеанса — `open_delay_s` (пауза в `open`),
`frame_period_s` (период кадров; 0 — без пауз), `get_frame_hang_s` (разовое зависание `get_frame`; повторно взводит `arm_hang(seconds)`),
`get_frame_errors` (первые N вызовов `get_frame` — `PortError`), `get_frame_script` (шаги `err` (`PortError`), `none` (тайм-аут), `frame` (кадр); допустимые — `SCRIPT_STEPS`),
`read_offset` (`{Binding.key: смещение}` — чтение отличается от записи, узел не меняется).

## Usage

Фейк порта с узлами по умолчанию:

```python
from Services.camera_device import Binding, DeviceIdentity
from Services.camera_device.testing.fake_port import make_port

port = make_port()
port.open(DeviceIdentity("serial", "FAKE-0001"))
exposure = Binding("genicam", "ExposureTime", "float")
port.set_param(exposure, 1234.5)
assert port.get_param(exposure) == 1234.0  # шаг узла 1.0, коррекция вниз
port.start_grabbing()
frame = port.get_frame(100)  # RawFrame: 4x2, mono8, frame_num == 1
port.stop_grabbing()
port.close()
```

Фейк по записи реального прибора и режим сбоя (запись после `stop_grabbing` отказывает, как NETER):

```python
from Services.camera_device.testing.fake_port import from_recording

port = from_recording("Services/camera_device/testing/recordings/mvs_MV-CS020-10GC.json", neter_after_stop=True)
```

Контрактный набор вендорского порта подклассируется в тестовом каталоге вендора:

```python
import pytest
from Services.camera_device.tests.port_contract import PortCase, PortContractSuite

class TestMyVendorContract(PortContractSuite):
    @pytest.fixture
    def port_case(self):
        return PortCase(id="vendor", make=make_my_port, ident=my_ident, rw_binding=my_binding, frame_byte0=None)
```

Тесты против реального прибора: `CAMERA_HARDWARE=1`, `CAMERA_PORT_FACTORY=<пакет.модуль:функция>`,
`CAMERA_DEVICE_KIND`, `CAMERA_DEVICE_VALUE`; без `CAMERA_HARDWARE=1` они пропускаются (маркер `hardware`).

## Живая правка и ящик владельца

Порт и `DeviceSdk` зовёт только поток-владелец (Р1), поэтому правка из другого потока не пишет в прибор сама, а кладёт команду в
**ящик** цикла (один на цикл `open -> close`, создаётся в `start()` вместе с событием стопа, закрывается при выходе владельца).

- **Когда владелец читает ящик.** После КАЖДОГО возврата `get_frame` (кадр, `None` по таймауту, `PortError`). Задержка исполнения команды не
  больше `timeout_ms` (500 мс по умолчанию); если `get_frame` завис, команда ждёт до его возврата. Стоп запрошен -> команды не исполняются.
- `submit(fn) -> bool` — не блокирует, срока нет; `False` — не поставлено (не `grabbing` или ящик закрыт). Ответ `fn` не возвращается.
- `call(fn, timeout) -> (ok, результат)` — `submit` и ожидание. По сроку, пока владелец `fn` не взял, команда отменяется и не исполнится
  позже: `(False, "срок")`; если `fn` уже исполняется, ждём ещё не больше `watchdog_s`. Остановка: `(False, "сеанс остановлен")`; исключение
  `fn` — `(False, <тип исключения>)`, цикл продолжается. Из потока владельца (например, из `on_frame`) — `(False, ...)` сразу.
  Блокирующий `call` — для команд плагина с портом (2.3d: `list_devices`, `describe_params`, `trigger_software`); колбэк подписки (2.4b) зовёт только
  неблокирующий `apply`. В ящик `call` ставит обёртку `_port_call("call", fn)`: зависший `fn` виден сторожу (`on_stall("call", секунды)`).
- `apply(steps, policy) -> None` — `steps` из `params.build_plan`, `policy` — `live` или `restart`. Не блокирует, из любого потока. Правки
  сливаются по полю (последнее значение побеждает), в ящике лежит одна команда; принимается в `opening` (владелец исполнит её сразу после входа
  в `grabbing`, до первого `get_frame`) и в `grabbing`, в `stopping`/`closed`/отказе — нет (значение
  register'а попадёт в прибор планом `run` следующего цикла). Исполняет владелец:
  - `live` при `live_write` — запись шага и чтение без остановки захвата;
  - `restart` (и `live` без `live_write`) — ОДИН перезахват на пакет: `stop_grabbing`, запись шагов пакета, `start_grabbing` при
    `restart_regrab`; без неё `stop_grabbing`, `close`, `open`, весь `run` цикла (с шагами пакета), `start_grabbing`;
  - шаги пакета заменяют шаги тех же полей в `run` цикла, поэтому следующий перезахват их не откатывает.
- Перезахват идёт ВНУТРИ `grabbing`: `state` не меняется, `on_state` не зовётся, `device_held` остаётся `True`. `stop()` в окне перезахвата
  -> `start_grabbing` не зовётся, цикл закрывается; отказ `open`/`start_grabbing` перезахвата -> `error`, `last_error` заполнен.
  На GigE `open` перезахвата — 1–3 с, всё это время кадры не идут и команды из ящика ждут.
- `restart` здесь — **перезахват порта**, а не перезапуск процесса. В framework `FieldMeta.apply == "restart"` означает перезапуск
  процесса-владельца (`field_meta.py:106-108`); как поле плагина попадает в `live`/`restart` сеанса — задача 2.4b.
- Программный триггер (`trigger_software`) через ящик — порядка 2 Гц (задержка до `timeout_ms` на команду); это после 1.0, в рецептах он не используется.
- Журнал и замеры: `apply field=<поле> policy=live|restart ms=<мс>` (логгер сеанса), `on_timing("apply", с)` на запись шага,
  `on_timing("regrab", с)` на перезахват. Фейк считает открытые дескрипторы (`open_handles`, `max_open_handles`): их >1 значит вызов порта мимо владельца.

## Команды

Форма ответа зависит от команды: три прежние живут на `status`, новые команды Р7 — на `success` (Р7, `decisions.md:16`; перевод
прежних на `success` — отдельное решение). Потребителю (вкладка 4.4) нужны обе формы. Модели аргументов — `commands.py`
(`TakeDeviceArgs`, `ReleaseDeviceArgs`, `ApplyParamsArgs`); фреймворк до Task 1.3 `data` не валидирует, обработчик разбирает его сам.
Текст ошибки валидации модели аргументов строится из `loc` и `msg`: введённое значение в ответ и в журнал не попадает. Текст отказа
register'а (проба и запись `apply_params`) для значения вне `min`/`max` поля может содержать это число (так печатает framework).

| Команда | Аргументы | Ответ |
|---|---|---|
| `take_device` | `timeout_s` (0 < с <= 30, по умолчанию 5.0) -> `session.start` | `{"status": "ok"\|"error", "device_state", "error"?}` |
| `release_device` | `timeout_s` (0 < с <= 30, по умолчанию 2.0) -> `session.stop` | `{"status": "ok"\|"error", "device_state", "error"?}` |
| `get_status` | нет | `{"status": "ok", "state", "device_state", "device_id", "frames", "last_error"}` |
| `reset_stats` | нет | `{"success": True}` |
| `read_params` | нет | `{"success": True, "params": {...}, "param_errors": {...}}` |
| `apply_params` | `{"params": {поле: значение}}` | `{"success": True, "applied": [...], "on_device": bool}` или `{"success": False, "error": ...}` |
| `list_devices` | нет | `{"success": True, "devices": [{"kind", "value", "name"}]}` или `{"success": False, "error": ...}` |
| `describe_params` | нет | `{"success": True, "params_meta": {поле: {"min", "max", "inc", "entries", "access"} \| None}}` или `{"success": False, "error": ...}` |
| `trigger_software` | нет | `{"success": True}` или `{"success": False, "error": ...}` |

Лишние ключи `data` у `take_device`/`release_device` игнорируются; ошибка валидации (`timeout_s=3600`) -> ответ той же формы
(`status: error`), `start`/`stop` не вызываются. `reset_stats`, `read_params`, `apply_params` порт не зовут и ящик владельца не используют. `list_devices`, `describe_params`,
`trigger_software` зовут порт тем потоком, который его держит (ниже); порт для них создаёт `_ensure_port()` без сеанса.

- **`read_params`** — СНИМОК `params` и `param_errors` последнего цикла сеанса, не живое чтение: порт не зовётся. После
  `release_device` вернёт прежние значения (сброс — при следующем `start()`). Сеанса нет -> оба пусты.
- **`reset_stats`** — сбрасывает `frames` (счётчик плагина, поле register'а `frames`, метрика `frames` сразу в 0), `dropped`,
  причину отброшенного кадра (`last_error` битого кадра) и окно `fps` (иначе следующее окно дало бы отрицательный `fps`).
  НЕ сбрасывает: `errors` (счётчик жизни сеанса) и `seq_id` (Р10: номер кадра продолжает счёт; битый кадр тоже получает номер).
  Замок `_stats_lock` охраняет счётчики от гонки `produce()` / сброс; метрики и журнал идут вне замка, поэтому после сброса дерево
  может до одного кадра (порядка 20 мс) или окна `_TICK_S` показывать прежнее число `frames` (`reg.frames`, `get_status` — уже 0).
- **`apply_params`** — единственный путь записи — `RegistersManager.set_field_value`; на прибор значение доходит колбэком
  подписки 2.4b (Р12) в потоке вызывающего. Команда `session.apply` не зовёт (удвоение) и не ждёт владельца. Порядок проверок (всё
  до первой записи, при отказе ничего не записано): модель -> `ctx.registers` -> поле из `bindings()` -> не `readonly` и хватает прав (`FieldMeta.access_level`: «недостаточно прав для поля: <имя>») -> пробная
  запись ВСЕГО пакета на копии register'а (всё или ничего). Поля пишутся по одному в порядке словаря (зависимые поля работают
  только в нём); каждое поле — отдельный `set_field_value`, отдельный `apply`.
  - `applied` = «принято register'ом»; результат на приборе приходит позже — смотреть `param_errors` через `read_params`.
  - `on_device` = сеанс в `opening`/`grabbing` на момент ответа И хотя бы у одного записанного поля `FieldMeta.apply` — `live` или
    `restart`; для `config`/`None` колбэк на прибор ничего не шлёт. Без захвата значение сохранено в register'е и войдёт в план
    следующего `take_device`. Запись на прибор асинхронна (порядка десятков мс после ответа). `on_device` не обещает записи: шаг, не
    меняющий план (то же значение, закрытый `enabled_if`, как `trigger_mode` при `trigger_managed=False`), прибор не трогает; итог — `read_params`.
  - Поля вне `bindings()` (`*_managed`, `timeout_ms`, `watchdog_s`, `device_serial`, `driver`, `camera_id`) отвергаются: подписки
    на прибор у них нет. Флаги групп (`trigger_managed`, `rest_managed`) действуют только со следующего `take_device`, поэтому
    порядок «флаг -> поле» через `register_update` работает лишь для полей, остальное — после `take_device`.
  - Отказ на фазе записи (остаточный случай: значение между пробой и записью изменил другой писатель) -> `{"success": False,
    "error": ..., "applied": [уже записанные]}`; ранее записанные поля остаются.
- **`list_devices`** — перечисление исполняет тот, кто держит SDK; путь выбирается по `session.device_held`, а не по `state`: `stop()` на
  отказном состоянии ставит `closed` сразу, пока владелец ещё закрывает порт (`state == "closed"` при `device_held == True`).
  1. Сеанса нет или `device_held` ложно (потока-владельца нет): `acquire`, затем в `try/finally` `enum_devices` и `release` потоком команды
     на порту из `_ensure_port()`, без handle. `release` идёт только после успешного `acquire`.
  2. `device_held` и `grabbing`: `session.call(enum_devices)` — перечисление исполняет владелец (`acquire` не нужен, владелец держит ссылку);
     на время перечисления он не читает кадры.
  3. `device_held` и любое иное состояние (`opening`, `stopping`, отказ при живом владельце): `call` отвечает
     `{"success": False, "error": "сеанс не в захвате"}`, порт не вызывается.
  Отказ `acquire`/`enum_devices`/`release` на пути без владельца (`PortError` и любое исключение) -> `{"success": False, "error": <тип исключения>}`; отказ `call` -> его текст
  (`"срок"`, `"сеанс остановлен"`, `"сеанс не в захвате"`). `list_devices` без `take_device` создаёт порт (`_ensure_port()`), но не сеанс,
  не мост логов и не воркеры; последующий `take_device` строит сеанс из того же порта.
- **`describe_params`** — один `session.call` по ВСЕМ привязкам `bindings()` (в том числе полям, пропущенным в плане run): `describe_param`
  зовёт владелец. Это снимок текущего состояния (границы и `access` у узлов зависят от соседних: у фейка `TriggerMode` при захвате `RO`);
  `entries` в ответе — список. Узел, давший `None` или `PortError`, -> `null`, остальные узлы отвечают. Порт без capability `node_describe` ->
  `{"success": True, "params_meta": {}}` без вызова порта; с capability, но без захвата -> `{"success": False, "error": "сеанс не в захвате"}`. Исключение хука `bindings()` -> `{"success": False, "error": <тип исключения>}`, значения полей в ответ и журнал не попадают.
- **`trigger_software`** — порядок: порт -> capability `software_trigger` (статична на жизнь порта, порт не вызывается) -> захват -> `session.call`
  `port.execute(self.software_trigger_binding())`. Без capability -> `{"success": False, "error": "нет capability software_trigger"}` (команда
  регистрируется всегда); без захвата -> `"сеанс не в захвате"`; отказ порта -> `{"success": False, "error": <текст>}`. Привязку командного узла
  задаёт хук базы `software_trigger_binding()` (умолчание `Binding("genicam", "TriggerSoftware", "command")`), вендор переопределяет. Частота
  — порядка 2 Гц (после 1.0).
- **Срок и блокировка приёма команд.** Команды с `session.call` ждут не дольше `_CALL_TIMEOUT_S` = 2.0 с (больше `timeout_ms`, 0,5 с по умолчанию).
  Если владелец уже взял `fn`, `call` ждёт ещё до `watchdog_s` (5.0 с по умолчанию): худший случай блокировки — `_CALL_TIMEOUT_S` + `watchdog_s`
  (около 7 с). Команды плагина идут системным потоком процесса, поэтому на это время задерживаются `register_update`, `state.changed` и остальной
  приём команд; дедлока нет (владелец системный поток не ждёт). Вывод сделан по чтению кода, в живом процессе не измерялся. Перезахват
  у GigE-прибора (1–3 с) может не уложиться в срок — ответ `"срок"`.
- **Открыто / не измерено.**
  - Безопасность `MV_CC_EnumDevices` при открытом handle на MVS не измерена (0.5/6.2, ADR-CAM-002: «Шторм `EnumDevices` из трёх процессов не
    проверен»). Теперь касается только межпроцессного случая (`hikvision_dual.yaml`: процесс B перечисляет, пока процесс A держит GigE-прибор);
    внутри одного процесса `list_devices` при захвате перечисляет владелец.
  - Гонка `start()` против `acquire` на пути без владельца: поток команды не конкурирует с `start()`, пока оба идут из системного потока. По чтению
    (ревью Opus) сегодня недостижима: `session.start()` зовёт только `cmd_take_device`, её вызывают хук `start(ctx)` при `auto_start` из
    `PluginOrchestrator.boot()` (до запуска `message_processor`, `process_module.py:291-312`) и команды в `message_processor`. Не воспроизведено,
    замка нет; новый вызов `cmd_take_device` вне `message_processor` откроет окно. Это не гарантия.
- **`set_config`** (generic `cmd_set_config` базы) пишет через `reg.apply_values` и подписчиков НЕ будит: на прибор не доходит.
  На прибор — только `apply_params` или `register_update`.

## Boundaries

- `interface.py` импортирует только stdlib; `cv2` и `numpy` — только `drivers/opencv_driver.py` и `testing/`.
- Ядро импортирует только `multiprocess_framework`, `pydantic` (модели `commands.py`) и stdlib.
- Ядро не импортирует вендоров: драйверы подключаются строками реестра `drivers/__init__.py` (ADR-CAM-001).
  Запрет держат две записи `[[boundaries]]` в `.sentrux/rules.toml`; проверка — `sentrux check .`.
- Вендорские пакеты импортируют ядро, не наоборот. Services не импортируют `Plugins` и `multiprocess_prototype`.
- Два экземпляра плагина камеры в одном процессе запрещены (ADR-CAM-002): путь состояния `processes.<p>.state.<плагин>` и register по имени плагина
  один; одна камера — один процесс, один сеанс. Запрет — соглашение: кодом он не проверяется.
- Порт и `DeviceSdk` вызывает тот, кто их держит: поток-владелец сеанса; вызывающие потоки зовут `start`/`stop` и читают свойства, а команды с
  портом — `session.call`. Пока владельца нет (`device_held` ложно), `list_devices` держит порт потоком команды (`acquire`/`enum_devices`/`release`
  без handle); порт без сеанса создаёт `_ensure_port()`.
- Фейк не проверяет границы min/max и принадлежность enum списку entries (потолок честности: `kind="range"` не вводится).
- Умолчания узлов фейка — гибрид: диапазон ExposureTime — запись MVS; закрытые узлы и PARENTS — запись `mvcr` и 6.2;
  значения (в т.ч. 10000.0) — решение лида, ни одной записи не соответствуют. В записи MVS `TriggerMode` при захвате
  остаётся RW, у фейка по умолчанию он RO.
- Ядро ветвится только по пяти `capabilities`: `read_back`, `live_write`, `node_describe`, `software_trigger`, `restart_regrab`.

## Stability

Stability: contract

## Решения и план

- [`DECISIONS.md`](DECISIONS.md) — ADR-CAM-001…004 (ADR-CAM-002 уточнён 2026-11-15).
- [`STATUS.md`](STATUS.md) — что есть.
- План: [`plans/2026-10-18_camera-device-service/plan.md`](../../plans/2026-10-18_camera-device-service/plan.md).
