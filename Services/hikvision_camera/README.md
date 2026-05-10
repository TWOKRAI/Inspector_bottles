# hikvision_camera_module_2

Рефакторинг модуля промышленной камеры Hikvision. Чистая архитектура на трёх слоях: SDK bindings → бизнес-логика → плагин для фреймворка.

---

## Назначение

Специализированный модуль для работы с камерами Hikvision (MVS SDK). Позволяет:
- Открывать/закрывать камеру и управлять захватом кадров
- Перечислять доступные устройства (GigE, USB)
- Настраивать параметры в реальном времени (экспозиция, усиление, fps)
- Захватывать и конвертировать кадры (Bayer → BGR)
- Использовать камеру как источник в `multiprocess_prototype_2` через плагин

---

## Архитектура в трёх слоях

```
┌─────────────────────────────────────────────────────────┐
│ plugin/                  (плагин для фреймворка)        │
│  - HikvisionCameraPlugin (ProcessModulePlugin)          │
│  - HikvisionCameraConfig (PluginConfig)                 │
│  - HikvisionCameraRegisters (SchemaBase)                │
└────────────────────────┬────────────────────────────────┘
                         │ использует
┌────────────────────────▼────────────────────────────────┐
│ core/                   (бизнес-логика)                 │
│  - HikvisionCamera      (state machine: CLOSED→OPEN→GRABBING) │
│  - enum_devices()       (обнаружение камер)             │
│  - CameraParameters     (настройки: exposure, gain, fps) │
│  - FrameConverter       (конвертер кадров)              │
└────────────────────────┬────────────────────────────────┘
                         │ использует
┌────────────────────────▼────────────────────────────────┐
│ sdk/                    (ctypes bindings)               │
│  - MvCamera             (минимальные 15 методов)        │
│  - MV_CC_DEVICE_INFO    (structures)                    │
│  - PixelType            (IntEnum констант)              │
│  - SDK_AVAILABLE        (graceful degradation)          │
└─────────────────────────────────────────────────────────┘
```

**Ключевая идея:** каждый слой не зависит от выше расположённых. SDK работает даже без DLL (graceful degradation). Core работает без фреймворка. Plugin опционально.

---

## Быстрый старт (Core API без фреймворка)

### Перечисление камер

```python
from hikvision_camera_module_2 import enum_devices

devices = enum_devices()
for dev in devices:
    print(f"{dev.index}: {dev.model_name} ({dev.device_type})")
```

### Работа с одной камерой

```python
from hikvision_camera_module_2 import HikvisionCamera, CameraState

# Создать камеру
camera = HikvisionCamera()

# Открыть (найти по индексу)
if not camera.open(camera_index=0):
    print("Ошибка: камера не найдена")
    exit(1)

assert camera.state == CameraState.OPEN

# Начать захват
if not camera.start_grabbing():
    print("Ошибка: не удалось начать захват")
    exit(1)

assert camera.state == CameraState.GRABBING

# Захватить кадр
frame, pixel_type = camera.capture_frame(timeout_ms=1000)

# Закончить
camera.stop_grabbing()
camera.close()
```

### Конвертация кадров

```python
from hikvision_camera_module_2 import FrameConverter

# Конвертировать в BGR (для OpenCV)
bgr_frame = FrameConverter.to_bgr(frame, pixel_type)

if bgr_frame is not None:
    import cv2
    cv2.imshow("Camera", bgr_frame)
```

### Настройка параметров

```python
from hikvision_camera_module_2 import CameraParameters

# Создать параметры
params = CameraParameters(
    exposure_time=20000.0,  # мкс
    gain=5.0,               # дБ
    frame_rate=25.0,        # fps
)

# Применить к камере
camera.set_parameters(params)

# Прочитать текущие параметры
current = camera.get_parameters()
print(f"Exposure: {current.exposure_time} мкс")
```

---

## Использование в multiprocess_prototype_2 (Plugin API)

### Добавить в topology.yaml

```yaml
processes:
  - process_name: camera_0
    plugins:
      - plugin_class: hikvision_camera_module_2.plugin.plugin.HikvisionCameraPlugin
        plugin_name: hikvision_camera
        category: source
        
        # Параметры камеры (из HikvisionCameraConfig)
        camera_id: 0
        camera_index: 0
        
        # Разрешение и fps
        resolution_width: 1920
        resolution_height: 1080
        fps: 25
        
        # Стартовые параметры
        exposure_time_us: 10000.0
        gain_db: 0.0
        
        # Авто-старт при запуске процесса
        auto_start: true
    
    # Направить кадры в процессор
    chain_targets: [processor]
```

### Команды плагина

```python
# Эти команды отправляются через GUI или API:

# Управление подключением
- open(camera_index=0)
- close()

# Управление захватом
- start_capture()
- stop_capture()

# Параметры
- get_parameters()
- set_parameters(exposure_time_us=..., gain_db=..., frame_rate=...)

# Информация
- enum_devices()
- get_status()
```

---

## SDK App — GUI для отладки

```bash
# Запустить GUI (PySide6)
python -m hikvision_camera_module_2
```

Окно `CameraTestWindow` показывает:
- Live-превью с камеры
- Параметры (exposure, gain, fps) с текущими значениями
- Слайдеры для настройки на лету
- Список обнаруженных устройств
- Статус и сообщения об ошибках

---

## Структура модуля

```
hikvision_camera_module_2/
├── __init__.py              # Публичный API (ленивая загрузка plugin)
├── __main__.py              # python -m → sdk_app
├── interfaces.py            # HikvisionCameraProtocol (Protocol)
│
├── sdk/                     # Слой bindings
│   ├── bindings.py          # MvCamera (~15 методов), SDK_AVAILABLE
│   ├── structures.py        # ctypes структуры (MV_CC_DEVICE_INFO, etc)
│   ├── constants.py         # PixelType IntEnum, коды устройств
│   └── errors.py            # SdkError, check_sdk_error
│
├── core/                    # Слой бизнес-логики
│   ├── camera.py            # HikvisionCamera (state machine)
│   ├── discovery.py         # enum_devices() → list[DeviceInfo]
│   ├── parameters.py        # CameraParameters dataclass
│   └── converter.py         # FrameConverter (Bayer→BGR, resize)
│
├── plugin/                  # Слой плагина
│   ├── plugin.py            # HikvisionCameraPlugin(ProcessModulePlugin)
│   ├── config.py            # HikvisionCameraConfig(PluginConfig)
│   └── registers.py         # HikvisionCameraRegisters (SchemaBase)
│
├── sdk_app/                 # GUI для отладки (опционально)
│   └── __init__.py          # CameraTestWindow (PySide6)
│
└── tests/                   # 60+ тестов
    ├── test_errors.py
    ├── test_constants.py
    ├── test_converter.py
    ├── test_discovery.py
    ├── test_camera.py
    ├── test_parameters.py
    └── conftest.py
```

---

## Ключевые классы и методы

### HikvisionCamera (state machine)

```python
class HikvisionCamera:
    # Свойства
    state: CameraState                      # текущее состояние

    # Методы управления
    open(camera_index: int = 0) -> bool     # открыть камеру
    close() -> None                         # закрыть камеру
    start_grabbing() -> bool                # начать захват
    stop_grabbing() -> None                 # остановить захват
    
    # Захват и параметры
    capture_frame(timeout_ms: int) -> (np.ndarray | None, int)
    get_parameters() -> CameraParameters
    set_parameters(params: CameraParameters) -> bool
    
    # Обратные вызовы (опционально)
    on_status: Callable[[str], None]        # для статусных сообщений
    on_error: Callable[[str], None]         # для ошибок
```

### enum_devices() — обнаружение

```python
# Возвращает список DeviceInfo
devices: list[DeviceInfo] = enum_devices()

# DeviceInfo — датакласс
@dataclass(frozen=True)
class DeviceInfo:
    index: int              # порядковый номер
    device_type: str        # "GigE" | "USB"
    user_name: str
    model_name: str
    serial: str
    display_name: str
    
    def to_dict(self) -> dict  # Dict at Boundary
```

### FrameConverter — конвертация кадров

```python
class FrameConverter:
    @staticmethod
    def to_bgr(frame: np.ndarray, pixel_type: int) -> np.ndarray | None:
        """Конвертировать в BGR.
        
        Поддерживает:
        - Bayer RG8/GR8/GB8/BG8 → BGR (через cv2.cvtColor)
        - Grayscale (Mono8) → BGR (копирование в 3 канала)
        - RGBA → BGR (отбросить alpha)
        - RGB → BGR (permute каналов)
        """
    
    @staticmethod
    def resize(frame: np.ndarray, width: int, height: int) -> np.ndarray:
        """Изменить размер кадра (INTER_LINEAR)."""
```

### HikvisionCameraPlugin — для фреймворка

```python
class HikvisionCameraPlugin(ProcessModulePlugin):
    """Source-плагин.
    
    configure()    — создание HikvisionCamera из конфига
    start()        — start_grabbing() если auto_start
    produce()      → (frame: np.ndarray, metadata: dict)
    shutdown()     — graceful cleanup
    """
```

---

## State Machine (CameraState)

```
   ┌─────────┐
   │ CLOSED  │  (нет подключения, инициальное состояние)
   └────┬────┘
        │ open(index)
   ┌────▼────┐
   │ OPEN    │  (подключено, но не захватывает)
   └────┬────┘
        │ start_grabbing()
   ┌────▼────────┐
   │ GRABBING    │  (активный захват кадров)
   └────┬────────┘
        │ stop_grabbing()
   ┌────▼────┐
   │ OPEN    │  (вернулся в режим ожидания)
   └────┬────┘
        │ close()
   ┌────▼─────┐
   │ CLOSED   │
   └──────────┘
```

**Гарантия:** нельзя захватить кадр без `start_grabbing()`, нельзя `start_grabbing()` без `open()`. Все переходы защищены валидацией в `capture_frame()` и т.д.

---

## Обработка ошибок

Все ошибки SDK обёрнуты в `SdkError` с кодом ошибки:

```python
from hikvision_camera_module_2.sdk.errors import SdkError

try:
    camera.open(camera_index=0)
except SdkError as e:
    print(f"SDK error {e.code}: {e.message}")
```

---

## Dict at Boundary

| Слой | Формат |
|------|--------|
| Граница процессов (IPC) | `dict` (`DeviceInfo.to_dict()`, `CameraParameters.to_dict()`) |
| Внутри процесса (plugin) | `dataclass` (`DeviceInfo`, `CameraParameters`) и Pydantic (`HikvisionCameraConfig`, `HikvisionCameraRegisters`) |
| Core API | `dataclass` (не зависит от фреймворка) |
| SDK | `ctypes` и `numpy.ndarray` |

---

## Запуск тестов

```bash
# Все тесты (60+ шт, работают без DLL)
pytest hikvision_camera_module_2/tests/ -v

# Отдельные модули
pytest hikvision_camera_module_2/tests/test_camera.py -v
pytest hikvision_camera_module_2/tests/test_converter.py -v
```

**Примечание:** тесты работают без физической камеры и без MvCameraControl.dll благодаря мокированию SDK.

---

## Зависимости

### Обязательные
- `numpy` (работа с кадрами как np.ndarray)
- `ctypes` (встроенный, SDK bindings)

### Опциональные (для отдельных частей)
- `opencv-python` (cv2) — для конвертации Bayer и операций с кадрами (core)
- `pyside6` (PySide6) — для SDK App GUI (опционально, только для `__main__.py`)

### Фреймворк-зависимые (только plugin/)
- `multiprocess_framework` — если использовать плагин в `multiprocess_prototype_2`

### На границе (Dict at Boundary)
- Никаких пользовательских объектов между процессами — только `dict` и примитивы

---

## Интеграция с multiprocess_prototype_2

1. **Blueprint (YAML):** добавить процесс с `HikvisionCameraPlugin` в `topology.yaml`
2. **Команды:** отправлять через bridge (open, close, set_parameters и т.д.)
3. **Кадры:** захватываются плагином → SHM ring-buffer → другие процессы (processor и т.д.)
4. **Параметры:** регистры (`HikvisionCameraRegisters`) синхронизируются с GUI в реальном времени

---

## Дизайн-решения

- **State machine вместо флагов:** явные состояния (CLOSED, OPEN, GRABBING) в `CameraState` enum
- **SdkError вместо голых except:** все ошибки SDK обёрнуты с кодом ошибки
- **Protocol вместо ABC:** `HikvisionCameraProtocol` для структурной типизации (structural subtyping)
- **numpy.copy() вместо ctypes.memcpy():** более безопасно и читаемо
- **Dataclasses вместо dict:** типизированные `DeviceInfo`, `CameraParameters`
- **Graceful degradation:** модуль работает даже если DLL не установлена (`SDK_AVAILABLE = False`)

---

## Лицензия и авторство

Часть проекта `multiprocess_prototype_2` (Inspector_bottles).
