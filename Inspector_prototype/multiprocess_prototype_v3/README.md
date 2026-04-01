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

- `main.py` — вход; 
- `backend/` — конфиги (в т.ч. `GuiConfig`), `processes/*`, `modules/` `database/`
- `frontend/` — `FrontendLauncher`, окна, виджеты, `FrontendConfig`
- `managers/` — `RecipeManager`, `AccessContext
- `registers/` — схемы регистров
- `utils/`, `docs/`, `tests/`, `logs/` (рантайм; в git не коммитить `*.log`, см. `.gitignore`)
---

## Как используется


## Связь с фреймворком

- **Фреймворк:** `Inspector_prototype/multiprocess_framework/modules/`
- **Прототип** использует: `process_manager_module`, `data_schema_module`, `process_module`, `message_module`, `worker_module`, `shared_resources_module` и др.
- **Контракт:** Dict at Boundary — `launcher.add_process(name, proc_dict)` принимает только `dict`.
