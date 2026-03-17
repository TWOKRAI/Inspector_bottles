# Интеграция Hikvision камеры

## Переключение типа камеры

В `CameraConfig` поле `camera_type`:
- `simulator` — FrameGenerator (имитация)
- `webcam` — WebcamCapture (USB-вебкамера)
- `hikvision` — Hikvision SDK (MvCamera)

Переключение через переменную окружения:
```bash
set INSPECTOR_CAMERA_TYPE=hikvision
python multiprocess_prototype/main.py
```

Или в коде:
```python
camera_config = CameraConfig(camera_type="hikvision")
launcher.add_process(*process(camera_config))
```

## Модуль Services/hikvision_camera

Используется `Services.hikvision_camera.hikvision_camera.camera_process`:
- `MvCameraControl_class.py` — обёртка Hikvision SDK
- `CameraParams_header.py`, `CameraParams_const.py`
- `PixelType_header.py`, `MvErrorDefine_const.py`

Адаптер для фреймворка: `multiprocess_prototype/processes/hikvision_camera_process.py`  
Импортирует SDK из `Services.hikvision_camera.hikvision_camera.camera_process`.  
Портирован с `camera_proc_2.py` (старая архитектура queue_manager) на новую (ProcessModule, command_manager, memory_manager). Методы SDK используются напрямую, без дублирования.

## Команды HikvisionCameraProcess

| Команда | Описание |
|---------|----------|
| `enum_devices` | Перечисление GigE/USB устройств |
| `open` | Открыть камеру (data: camera_index) |
| `close` | Закрыть камеру |
| `start_grabbing` | Начать захват |
| `stop_grabbing` | Остановить захват |
| `start_capture` | Алиас: open + start_grabbing (совместимость с GUI) |
| `stop_capture` | Алиас: stop_grabbing |
| `get_parameters` | Получить frame_rate, exposure_time, gain |
| `set_parameters` | Установить параметры |

## Сообщения в GUI

| data_type | Описание |
|-----------|----------|
| `status` | Текстовый статус |
| `error` | Ошибка |
| `parameters_response` | Параметры камеры |
| `enum_devices_response` | Список устройств |
| `image_size` | Размер после первого кадра |

## Подготовка модуля hikvision_camera для внедрения

Модуль `Inspector_prototype/Services/hikvision_camera` готов к использованию:
- Требует Hikvision MvCameraControl.dll в PATH
- Используется в multiprocess_prototype как тест/шаблон
- Архитектура: ProcessModule → SharedMemory → frame_ready в Processor

Для других приложений: импортировать `camera_process` и использовать `MvCamera` напрямую или создать свой ProcessModule-адаптер по образцу `hikvision_camera_process.py`.
