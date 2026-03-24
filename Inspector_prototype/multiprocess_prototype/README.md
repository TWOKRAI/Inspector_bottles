# multiprocess_prototype — Тестовый прототип Inspector

**Назначение:** Тестовое приложение для проверки и демонстрации работы **Multiprocess Framework**. Используется для отладки пайплайна обработки изображений, интеграции камер и GUI.

**Зависимости:** `multiprocess_framework/modules`  
**Python:** 3.8+

---

## Что это

Тестовый прототип системы инспекции бутылок на базе Multiprocess Framework. Запускает 6 процессов:

| Процесс | Назначение |
|---------|------------|
| **Camera** | Захват кадров (simulator / webcam / Hikvision) |
| **Processor** | Обработка: маска, контуры, детекция пятен |
| **Renderer** | Отрисовка: оригинал + маска + контуры |
| **Robot** | Симуляция робота (приём/отправка команд) |
| **Database** | Сохранение детекций в SQLite |
| **GUI** | PyQt (GuiProcess + frontend_module + FrontendLauncher) |

**Связь:** SharedMemory (camera_frame, processor_mask, rendered_frame, mask_frame) + очереди сообщений.

**Документация:** [docs/README.md](docs/README.md) (индекс). **Архитектура:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). **Фронт:** [docs/FRONTEND_MAP.md](docs/FRONTEND_MAP.md). **Рецепты:** [docs/RECIPES_SYSTEM.md](docs/RECIPES_SYSTEM.md).

---

## Структура проекта (кратко)

- `main.py` — вход; prefs камеры — `persistence/` (см. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- `camera_policy.py` — строковые типы и лимиты камеры (схемы, GUI, persistence)
- `backend/` — конфиги (в т.ч. `GuiConfig`), `processes/*`, `modules/` (camera с `backends.py`, processor_frame, renderer), `gui_process_mixin.py`, `database/`
- `frontend/` — `FrontendLauncher`, окна, виджеты, `FrontendConfig`
- `managers/` — `RecipeManager`, `AccessContext`, агрегат app-рецепта (YAML слоты)
- `registers/` — схемы, factory, command routing
- `persistence/` — корень данных (`INSPECTOR_DATA_DIR` или `~/.inspector_prototype`), `user_prefs.json`, миграция со старого `.inspector_prefs.json`
- `utils/`, `docs/`, `tests/`, `logs/` (рантайм; в git не коммитить `*.log`, см. `.gitignore`)

Полная таблица каталогов — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/modules" python -m multiprocess_prototype.main
```

### 2. Регистрация процессов

В `main.py` процессы добавляются единообразно через `process()` из `data_schema_module`:

```python
from multiprocess_framework.modules.process_manager_module import SystemLauncher
from multiprocess_framework.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import (
    CameraConfig,
    DatabaseConfig,
    GuiConfig,
    ProcessorConfig,
    RendererConfig,
    RobotConfig,
)
from multiprocess_prototype.persistence import get_camera_type

launcher = SystemLauncher(stop_timeout=5.0)
camera_type = get_camera_type()

launcher.add_process(*process(CameraConfig(camera_type=camera_type)))
launcher.add_process(*process(ProcessorConfig()))
launcher.add_process(*process(RendererConfig()))
launcher.add_process(*process(RobotConfig()))
launcher.add_process(*process(DatabaseConfig()))
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
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/modules" pytest Inspector_prototype/multiprocess_prototype/tests/ -v
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
| `INSPECTOR_DATA_DIR` | Каталог данных приложения (prefs, будущие кэши/экспорты). По умолчанию: `~/.inspector_prototype` |
| `INSPECTOR_LOG_LEVEL` | Уровень логов: INFO, DEBUG, WARNING, ERROR |
| `INSPECTOR_LOG_DIR` | Каталог логов (по умолчанию `multiprocess_prototype/logs`) |
| `INSPECTOR_UI_DIAGNOSTICS` | Если `1` / `true` / `yes` — включает опциональную телеметрию UI (`WidgetSignalBus` + шапка), см. `GuiConfig.ui_diagnostics` и `frontend/diagnostics.py` |
| `DISPLAY` | Для GUI на Unix; в CI можно `QT_QPA_PLATFORM=offscreen` (см. `tests/support/gui_env.py`) |

---

## Связь с фреймворком

- **Фреймворк:** `Inspector_prototype/multiprocess_framework/modules/`
- **Прототип** использует: `process_manager_module`, `data_schema_module`, `process_module`, `message_module`, `worker_module`, `shared_resources_module` и др.
- **Контракт:** Dict at Boundary — `launcher.add_process(name, proc_dict)` принимает только `dict`.
