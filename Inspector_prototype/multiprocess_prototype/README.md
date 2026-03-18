# multiprocess_prototype — Тестовый прототип Inspector

**Назначение:** Тестовое приложение для проверки и демонстрации работы **Multiprocess Framework**. Используется для отладки пайплайна обработки изображений, интеграции камер и GUI.

**Зависимости:** `multiprocess_framework/refactored/modules`  
**Python:** 3.8+

---

## Что это

Тестовый прототип системы инспекции бутылок на базе Multiprocess Framework. Запускает 5 процессов:

| Процесс | Назначение |
|---------|------------|
| **Camera** | Захват кадров (simulator / webcam / Hikvision) |
| **Processor** | Обработка: маска, контуры, детекция пятен |
| **Renderer** | Отрисовка: оригинал + маска + контуры |
| **Robot** | Симуляция робота (приём/отправка команд) |
| **GUI** | PyQt окно с чекбоксами Original, Mask, Contours |

**Связь:** SharedMemory (camera_frame, processor_mask, rendered_frame, mask_frame) + очереди сообщений.

---

## Структура проекта

```
multiprocess_prototype/
├── main.py                 # Точка входа
├── prefs.py                # Сохранение camera_type (GUI → .inspector_prefs.json)
├── run.sh                  # Запуск с PYTHONPATH и очисткой SharedMemory
│
├── backend/                # Бэкенды захвата кадров
│   ├── backends.py         # SimulatorBackend, WebcamBackend, HikvisionBackend
│   └── __init__.py
│
├── configs/                # Pydantic-конфиги процессов
│   ├── camera_config.py
│   ├── processor_config.py
│   ├── renderer_config.py
│   ├── robot_config.py
│   └── gui_config.py
│
├── processes/              # Реализации процессов
│   ├── unified_camera_process.py   # Единый процесс камеры (переключение без перезапуска)
│   ├── processor_process.py
│   ├── renderer_process.py
│   ├── robot_simulator_process.py
│   └── gui_process.py
│
├── gui/                    # GUI-компоненты
├── utils/                  # FrameGenerator, WebcamCapture, shm_utils
└── tests/                  # Unit- и интеграционные тесты
```

---

## Как используется

### 1. Запуск

**Рекомендуемый способ** — скрипт `run.sh`:

```bash
# Из корня репозитория (Inspector_bottles)
./Inspector_prototype/multiprocess_prototype/run.sh

# Или из Inspector_prototype
cd Inspector_prototype && ./multiprocess_prototype/run.sh
```

**Через Python:**

```bash
python Inspector_prototype/multiprocess_prototype/main.py
```

**С явным PYTHONPATH (CI, скрипты):**

```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
```

### 2. Регистрация процессов

В `main.py` процессы добавляются единообразно через `process()` из `data_schema_module`:

```python
launcher = SystemLauncher(stop_timeout=5.0)
camera_type = get_camera_type()

launcher.add_process(*process(CameraConfig(camera_type=camera_type)))
launcher.add_process(*process(ProcessorConfig()))
launcher.add_process(*process(RendererConfig()))
launcher.add_process(*process(RobotConfig()))
launcher.add_process(*process(GuiConfig(camera_type=camera_type)))

launcher.run()
```

### 3. Тип камеры

- **Источник:** `prefs.get_camera_type()` → env `INSPECTOR_CAMERA_TYPE` → default `"simulator"`
- **Сохранение:** GUI сохраняет выбор в `.inspector_prefs.json`
- **Режимы:** `simulator` | `webcam` | `hikvision`
- **Переключение:** команда `set_camera_type` — без перезапуска процесса

### 4. Тесты

```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" pytest Inspector_prototype/multiprocess_prototype/tests/ -v
```

- `test_configs_build.py` — конфиги и `process()`
- `test_camera_process.py` — изолированный запуск Camera
- `test_processor_mask_contours.py` — Processor
- `test_renderer_commands.py` — Renderer
- `test_full_integration.py` — полный пайплайн (требует DISPLAY)

---

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `INSPECTOR_CAMERA_TYPE` | Тип камеры: simulator, webcam, hikvision |
| `INSPECTOR_LOG_LEVEL` | Уровень логов: INFO, DEBUG, WARNING, ERROR |
| `INSPECTOR_LOG_DIR` | Каталог логов (по умолчанию `multiprocess_prototype/logs`) |
| `DISPLAY` | Требуется для GUI (headless CI — тесты с GUI пропускаются) |

---

## Связь с фреймворком

- **Фреймворк:** `Inspector_prototype/multiprocess_framework/refactored/modules/`
- **Прототип** использует: `process_manager_module`, `data_schema_module`, `process_module`, `message_module`, `worker_module`, `shared_resources_module` и др.
- **Контракт:** Dict at Boundary — `launcher.add_process(name, proc_dict)` принимает только `dict`.
