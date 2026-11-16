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
  - Свойства: `state`, `errors` (ошибки кадров + отказы узлов профилей), `params` (прочитанное, скаляры), `params_status` (`{поле: {"verified", "rc"}}`),
    `param_errors` (`{поле: текст}`), `last_error`, `device` (`DeviceIdentity | None`), `device_held` (поток-владелец жив).
  - Колбэки: `on_frame(RawFrame)` — из владельца, обязателен; `on_state(old, new)` — из потока, сменившего состояние, порядок не гарантирован (истина — `state`);
    `on_stall(имя_вызова, секунды)` — один раз на вызов порта дольше `watchdog_s`; `on_timing(имя, секунды)` — замеры `open`, `stop_grabbing`, `get_frame`, `apply`.
    Исключение колбэка логируется и не роняет сеанс.
  - `run`/`rest` — последовательности `Step` из `build_plan`: `run` пишется между `open` и `start_grabbing` при каждом старте, `rest` — best-effort после `stop_grabbing`.
- `profiles.ProfileRunner(port, ident, state, log, on_timing=None, call=None)` — `apply_plan(steps)`, `apply_step(step)`, `run_rest(steps, restart_regrab)`:
  запись узла и проверка чтением. Отказ узла план не прерывает; потомки отказавшего родителя (`Step.parent`) не пишутся.
  Живую правку (Task 2.4) будет звать тот же `apply_step`.
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

## Boundaries

- `interface.py` импортирует только stdlib; `cv2` и `numpy` — только `drivers/opencv_driver.py` и `testing/`.
- Ядро импортирует только `multiprocess_framework` и stdlib.
- Ядро не импортирует вендоров: драйверы подключаются строками реестра `drivers/__init__.py` (ADR-CAM-001).
  Запрет держат две записи `[[boundaries]]` в `.sentrux/rules.toml`; проверка — `sentrux check .`.
- Вендорские пакеты импортируют ядро, не наоборот. Services не импортируют `Plugins` и `multiprocess_prototype`.
- Два экземпляра плагина камеры в одном процессе запрещены (ADR-CAM-002): путь состояния `processes.<p>.state.<плагин>` и register по имени плагина
  один; одна камера — один процесс, один сеанс. Запрет — соглашение: кодом он не проверяется.
- Порт и `DeviceSdk` вызываются только из потока-владельца сеанса; вызывающие потоки зовут `start`/`stop` и читают свойства.
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
