# Модули App — справочник и связи с framework

**Назначение:** Понимать, какие модули есть в App, что они импортируют из framework, как связываются.

---

## Сводная таблица

| Модуль App | Путь | Импортирует из framework | Назначение |
|------------|------|--------------------------|------------|
| main_app | App.main_app | queue_manager (QueueManager) | Entry point |
| coordinator | App.Core.Application.coordinator | router_module (RouterManager, QueueChannel, Message, MessageType) | Фасад, инициализация слоёв |
| thread_manager | App.Core.Application.thread_manager | — | QThread (image_update, bot) |
| window_manager | App.Core.Application.window_manager | — | WindowRegistry, окна |
| RegistersManager | App.Core.Domain.Registers.manager | data_schema_module (FieldMeta) | Состояние регистров |
| DataManager | App.Core.Managers.data_manager | — | Координатор Camera/Region/Recipe |

---

## Точка входа

```
main_app.main()
    │
    ├── QueueManager (framework) — ОТСУТСТВУЕТ, fallback MockQueueManager
    ├── ApplicationCoordinator(queue_manager, stop_event)
    │
    └── coordinator.initialize()
            ├── Config (AppConfig)
            ├── Domain (RegistersManager, DataManager)
            ├── Infrastructure (RouterManager из framework)
            └── Application (ThreadManager, WindowManager)
```

---

## Зависимости App → Framework

```
App
 │
 ├── main_app
 │     └── queue_manager.QueueManager  ❌ не существует
 │
 ├── coordinator
 │     └── router_module (RouterManager, QueueChannel, Message, MessageType) ✅
 │
 ├── RegistersManager
 │     └── data_schema_module (FieldMeta, RegistersContainer) ✅
 │
 └── Threads (UpdateImage, BotThread)
       └── queue_manager (display_queue, bot_message, etc.) — через coordinator
```

---

## WorkerManager vs ThreadManager

| Аспект | WorkerManager (framework) | ThreadManager (App) |
|--------|---------------------------|---------------------|
| Тип потоков | threading.Thread | PyQt5.QtCore.QThread |
| Использование | Backend процессы | UI приложение |
| API | create_worker(), start_worker() | register(), create(), start() |
| Сигналы | — | pyqtSignal (thread_created, etc.) |
| Интеграция | — | Подключение frame_ready → MainWindow |

**Рекомендация:** Оба нужны. WorkerManager — для backend. ThreadManager — для App (QThread + Qt signals).

---

## Связанные документы

- `App/NEW_ARCHITECTURE.md` — архитектура App
- `UNIFICATION_PLAN.md` — план унификации
- `multiprocess_framework/docs/MODULES_INDEX.md` — индекс модулей framework
