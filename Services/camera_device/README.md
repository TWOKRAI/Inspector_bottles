# Services/camera_device

Общее ядро камер: один порт прибора, сеанс с потоком-владельцем, общий набор команд плагина.
Вендорские сервисы (`code_reader`, `hikvision_camera`) и драйвер OpenCV — тонкие драйверы над ним.

**Stability: contract.** Контракт порта (`interface.py`) и честный фейк (`testing/fake_port.py`) — Task 1.5.
Сеанс, команды плагина и драйверы — следующие задачи плана; «как добавить вендора» — Task 5.4.

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

Тестовые средства (не входят в `__all__`): `testing/fake_port.py` — `make_port(**opts)`, `from_recording(path, **opts)`;
контрактный набор — `tests/port_contract.py` (`PortContractSuite`, `PortCase`).

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
- Один экземпляр плагина камеры на процесс (путь состояния `processes.<p>.state.<плагин>` и register по имени плагина).
- Фейк не проверяет границы min/max и принадлежность enum списку entries (потолок честности: `kind="range"` не вводится).
- Умолчания узлов фейка — гибрид: диапазон ExposureTime — запись MVS; закрытые узлы и PARENTS — запись `mvcr` и 6.2;
  значения (в т.ч. 10000.0) — решение лида, ни одной записи не соответствуют. В записи MVS `TriggerMode` при захвате
  остаётся RW, у фейка по умолчанию он RO.
- Ядро ветвится только по пяти `capabilities`: `read_back`, `live_write`, `node_describe`, `software_trigger`, `restart_regrab`.

## Stability

Stability: contract

## Решения и план

- [`DECISIONS.md`](DECISIONS.md) — ADR-CAM-001…004.
- [`STATUS.md`](STATUS.md) — что есть.
- План: [`plans/2026-10-18_camera-device-service/plan.md`](../../plans/2026-10-18_camera-device-service/plan.md).
