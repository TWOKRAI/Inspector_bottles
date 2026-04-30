# hikvision_camera_module

## Назначение

Модуль инкапсулирует работу с Hikvision SDK (MvCamera). Предоставляет простой фасад `HikvisionCameraFacade` и адаптер `HikvisionCameraProcessAdapter` для интеграции в multiprocess framework. Вся сложная логика (enum, open, grab, parameters) вынесена из прототипа.

## Импорты

```python
from hikvision_camera_module import (
    HikvisionCameraFacade,
    HikvisionCameraProcessAdapter,
    IHikvisionCameraFacade,
)
```

## Точки входа

| Класс/функция | Метод | Описание |
|---------------|-------|----------|
| HikvisionCameraFacade | `enum_devices()` | Перечислить GigE/USB устройства |
| HikvisionCameraFacade | `open(camera_index)` | Открыть камеру |
| HikvisionCameraFacade | `close()` | Закрыть камеру |
| HikvisionCameraFacade | `start_grabbing()` | Начать захват |
| HikvisionCameraFacade | `stop_grabbing()` | Остановить захват |
| HikvisionCameraFacade | `capture_frame(timeout_ms)` | Захватить кадр (сырой np.ndarray) |
| HikvisionCameraFacade | `get_parameters()` | Получить frame_rate, exposure, gain |
| HikvisionCameraFacade | `set_parameters(...)` | Установить параметры |
| HikvisionCameraFacade | `open_sdk_window()` | Открыть окно оригинального SDK |
| HikvisionCameraFacade | `close_sdk_window()` | Закрыть окно SDK |
| HikvisionCameraProcessAdapter | `initialize()` | ProcessModule: инициализация |
| HikvisionCameraProcessAdapter | `shutdown()` | ProcessModule: завершение |

## Зависимости

- **Зависит от:** `Services.hikvision_camera` (SDK), `multiprocess_framework` (для адаптера)
- **Используется в:** `multiprocess_prototype` (backends, `backend.modules.camera`)

## Пример

```python
from hikvision_camera_module import HikvisionCameraFacade

facade = HikvisionCameraFacade(
    on_status=lambda t: print("Status:", t),
    on_error=lambda t: print("Error:", t),
)
r = facade.enum_devices()
if r.get("status") == "ok":
    facade.open(0)
    facade.start_grabbing()
    frame = facade.capture_frame()
    if frame is not None:
        print("Frame shape:", frame.shape)
    facade.stop_grabbing()
    facade.close()
```

## Связь с другими модулями

```
hikvision_camera_module
    │
    ├── использует → Services.hikvision_camera (SDK)
    ├── использует → multiprocess_framework (ProcessModule)
    │
    └── используется в → multiprocess_prototype (backends, processes)
```

## Структура модуля

```
hikvision_camera_module/
├── __init__.py          # Публичный API
├── __main__.py          # python -m hikvision_camera_module → окно SDK
├── interfaces.py        # IHikvisionCameraFacade
├── sdk/                 # Локальная копия Hikvision SDK (из Services)
│   ├── MvCameraControl_class.py
│   ├── CameraParams_header.py, CameraParams_const.py
│   ├── PixelType_header.py, MvErrorDefine_const.py
│   └── clean_camera_process.py  # CleanCameraProcessManager (multiprocess)
├── sdk_app/             # Оригинальное приложение SDK (PyQt5)
│   └── clean_camera_test.py
├── core/
│   ├── facade.py        # HikvisionCameraFacade + open_sdk_window/close_sdk_window
│   ├── capture.py       # Enum, open, grab (сырые кадры)
│   └── parameters.py    # get/set parameters
├── adapters/
│   └── process_adapter.py  # HikvisionCameraProcessAdapter
├── tests/
├── README.md
└── STATUS.md
```

## Запуск оригинального SDK

```bash
# Из текущего каталога
PYTHONPATH="." python -m hikvision_camera_module
```

Или через фасад:
```python
facade = HikvisionCameraFacade()
facade.open_sdk_window()   # Открыть окно
# ...
facade.close_sdk_window()  # Закрыть
```

## Примечания

- SDK (sdk/) — локальная копия из Services.hikvision_camera
- Требует Hikvision MvCameraControl.dll в PATH
- `capture_frame()` возвращает сырой массив (2D Bayer/Gray, 3D RGB) без cv2
- cv2-конвертация (Bayer→BGR и т.д.) выполняется в прототипе или адаптере
