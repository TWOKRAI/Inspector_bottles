# STATUS — hikvision_camera_module_2

## Текущий статус: ✅ Готов к использованию

Дата: 2026-05-08

---

## Качество реализации

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Архитектура | 9/10 | Три чистых слоя (SDK → core → plugin); нет циклических зависимостей |
| Type hints | 9/10 | Protocol вместо ABC; dataclasses типизированы; Pydantic v2 в plugin |
| Error handling | 8/10 | SdkError с кодами ошибок; graceful degradation при отсутствии DLL |
| State machine | 9/10 | CameraState enum с гарантиями переходов; все валидации на месте |
| Тесты | 8/10 | 60+ тестов без DLL; покрыты все core-модули и plugin |
| Документация | 8/10 | README с примерами, структура, API; нет ADR (простой модуль) |
| Реактивность | 8/10 | HikvisionCameraRegisters интегрирована с GUI через фреймворк |

---

## Что реализовано

- [x] SDK layer — минимальные ctypes bindings (~15 методов из SDK)
- [x] SDK structures — MV_CC_DEVICE_INFO, MV_FRAME_OUT и другие (ctypes)
- [x] SDK constants — PixelType IntEnum, MV_GIGE_DEVICE, MV_USB_DEVICE
- [x] SDK errors — SdkError, check_sdk_error, graceful degradation (SDK_AVAILABLE)
- [x] Core camera — HikvisionCamera state machine (CLOSED → OPEN → GRABBING)
- [x] Core discovery — enum_devices() для GigE и USB с DeviceInfo dataclass
- [x] Core parameters — CameraParameters dataclass с exposure, gain, fps
- [x] Core converter — FrameConverter для Bayer/Grayscale/RGBA/RGB → BGR конвертации
- [x] Plugin layer — HikvisionCameraPlugin(ProcessModulePlugin) как source
- [x] Plugin config — HikvisionCameraConfig(PluginConfig) с параметрами камеры
- [x] Plugin registers — HikvisionCameraRegisters(SchemaBase) для runtime-настроек
- [x] SDK App — PySide6 GUI (CameraTestWindow) для отладки и тестирования
- [x] Tests — 60+ pytest-тестов без физической камеры (мокирование SDK)
- [x] Interfaces — HikvisionCameraProtocol(Protocol) для structural subtyping
- [x] Dict at Boundary — DeviceInfo.to_dict(), CameraParameters.to_dict() для IPC

---

## Улучшения vs оригинальный код

| Что было | Что стало | Почему |
|---------|----------|--------|
| bool флаги для состояния | `CameraState` enum (CLOSED/OPEN/GRABBING) | Явность, безопасность переходов |
| Голые SDK error codes | `SdkError(code, message)` с wrapper | Типизация, лучший логирование |
| ctypes memcpy | numpy.copy() | Безопаснее, понятнее, быстрее |
| ABC (Abstract Base Class) | Protocol с @runtime_checkable | Структурная типизация, более pythonic |
| Сырые dict для параметров | `CameraParameters` dataclass | Типизация, методы to_dict()/from_dict() |
| PyQt5 в GUI | PySide6 в SDK App | Совместимость с фреймворком |
| Без graceful degradation | SDK_AVAILABLE флаг, работает без DLL | Разработка и тестирование на Win+Mac |

---

## Структура файлов

| Путь | Назначение |
|------|-----------|
| `__init__.py` | Публичный API (ленивая загрузка plugin) |
| `interfaces.py` | HikvisionCameraProtocol |
| `sdk/bindings.py` | MvCamera wrapper, SDK_AVAILABLE |
| `sdk/structures.py` | ctypes структуры |
| `sdk/constants.py` | PixelType, коды устройств |
| `sdk/errors.py` | SdkError, обработка ошибок |
| `core/camera.py` | HikvisionCamera state machine |
| `core/discovery.py` | enum_devices(), DeviceInfo |
| `core/parameters.py` | CameraParameters dataclass |
| `core/converter.py` | FrameConverter (Bayer→BGR) |
| `plugin/plugin.py` | HikvisionCameraPlugin |
| `plugin/config.py` | HikvisionCameraConfig |
| `plugin/registers.py` | HikvisionCameraRegisters |
| `sdk_app/` | PySide6 GUI (опционально) |
| `tests/` | 60+ pytest-тестов |

---

## Использование

### Как standalone (без фреймворка)
```python
from hikvision_camera_module_2 import HikvisionCamera, enum_devices

devices = enum_devices()
cam = HikvisionCamera()
cam.open(0)
cam.start_grabbing()
frame, pixel_type = cam.capture_frame()
```

### Как плагин в multiprocess_prototype_2
```yaml
processes:
  - process_name: camera_0
    plugins:
      - plugin_class: hikvision_camera_module_2.plugin.plugin.HikvisionCameraPlugin
        camera_index: 0
        fps: 25
        auto_start: true
```

### Как SDK App (отладка)
```bash
python -m hikvision_camera_module_2
```

---

## Тестирование

**60+ тестов**, все проходят без физической камеры:

```bash
pytest hikvision_camera_module_2/tests/ -v
```

Модули:
- `test_errors.py` — error codes, SdkError
- `test_constants.py` — PixelType enum, device types
- `test_converter.py` — Bayer→BGR, grayscale, resize
- `test_discovery.py` — enum_devices(), DeviceInfo
- `test_camera.py` — state machine, transitions, capture_frame()
- `test_parameters.py` — CameraParameters, get/set
- `test_plugin.py` — HikvisionCameraPlugin lifecycle, commands

**Мокирование:** SDK вызовы мокируются в conftest.py; тесты работают на любой ОС (Win/Mac/Linux) и без DLL.

---

## Известные ограничения

1. **MvCameraControl.dll обязательна для live-режима** — SDK layer работает, но capture_frame() вернёт None если DLL не установлена
2. **SDK App только для отладки** — не входит в состав production plugin, используется для тестирования
3. **Поддержка форматов ограничена** — Bayer RG8/GR8/GB8/BG8, Grayscale, RGBA, RGB; другие форматы требуют расширения FrameConverter
4. **GigE vs USB** — оба типа поддерживаны enum_devices(), но SDK ограничивает одновременно открытые камеры (обычно < 4)

---

## Зависимости

| Модуль/Версия | Обязательный | Зачем |
|---------------|-------------|-------|
| Python 3.12+ | да | Type hints, dataclasses, enum.auto |
| numpy 2.x | да | Работа с кадрами как np.ndarray |
| ctypes | да | SDK bindings (встроенный в Python) |
| opencv-python 4.13+ | опционально | FrameConverter для Bayer→BGR конвертации |
| pyside6 6.10+ | опционально | SDK App GUI (`python -m hikvision_camera_module_2`) |
| multiprocess_framework | опционально | Если использовать как плагин в multiprocess_prototype_2 |
| MvCameraControl.dll | опционально | Для live capture (graceful degradation если нет) |

---

## Следующие улучшения (опционально)

- [ ] Поддержка ROI (Region of Interest) в CameraParameters
- [ ] Batch capture с внутренним буфером (для асинхронного захвата)
- [ ] Профили настроек (сохранение/загрузка конфигов из YAML)
- [ ] Телеметрия (frame_count, capture_time_ms, fps_actual)
- [ ] Кэширование enum_devices() результатов
- [ ] Поддержка дополнительных форматов кодирования (JPEG, H.264)

---

## Миграция с оригинального кода

Если переходите со старого модуля:

| Было | Стало |
|------|-------|
| `camera.is_open()` (bool) | `camera.state == CameraState.OPEN` |
| `device["model_name"]` (dict) | `device.model_name` (DeviceInfo dataclass) |
| `camera.capture_frame()` → (array, info) | `camera.capture_frame()` → (array, pixel_type) |
| `ConversionError` exception | `SdkError` с кодом ошибки |
| Параметры как dict | `CameraParameters` dataclass + get/set методы |

---

## История версий

| Дата | Версия | Событие |
|------|--------|---------|
| 2024 | 1.0 | Оригинальный модуль (code review, mvs_sdk wrapper) |
| 2025-Q4 | 2.0 | Рефакторинг: архитектура 3 слоя, protocol, dataclasses |
| 2026-04 | 2.1 | Полная интеграция с multiprocess_prototype_2; tests 60+ |
| 2026-05-08 | 2.2 | README.md, STATUS.md; готов к production |

---

## Контакты и поддержка

Модуль тесно интегрирован с:
- `multiprocess_framework` (plugin system, IPC)
- `multiprocess_prototype_2` (процессы, GUI, фреймворк)
- `Inspector_vision` проект (рабочий прототип)

Для questions см. main branch в `multiprocess_prototype_2/`.
