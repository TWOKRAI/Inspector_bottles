# Индекс модулей multiprocess_framework (refactored)

**Назначение:** Быстрый справочник — что импортировать, откуда, как связывать модули.

**Обновление:** При добавлении/изменении модуля обновить этот файл.

---

## Сводная таблица

| Модуль | Импорты (основные) | Точки входа | Зависит от | Используется в |
|--------|--------------------|-------------|------------|----------------|
| **base_manager** | BaseManager, BaseAdapter, ObservableMixin | initialize(), shutdown(), attach_adapter() | — | Все менеджеры |
| **worker_module** | WorkerManager, ThreadConfig, ThreadPriority, WorkerStatus | create_worker(), start_worker(), stop_worker() | base_manager | Backend процессы |
| **router_module** | RouterManager, QueueChannel, Message, MessageType | send_async(), register_channel(), register_route() | message_module, dispatch_module | App, Backend |
| **message_module** | Message, MessageType, generate_message_id | Message.create() | — | router_module, App |
| **data_schema_module** | RegistersContainer, FieldMeta, RegistersScanner | — | — | App (RegistersManager) |
| **shared_resources_module** | QueueRegistry, EventManager | — | process_module (state) | router_module, процессы |
| **dispatch_module** | Dispatcher, DispatchStrategy | dispatch() | — | router_module |
| **config_module** | ConfigModule | get(), set() | base_manager | process_module |
| **logger_module** | LoggerManager | log_* | base_manager | Все модули |
| **command_module** | CommandManager | — | base_manager | — |
| **process_module** | ProcessModule | — | config, shared_resources | — |
| **queue_module** | QueueManager | *(создать)* | shared_resources? | App (main_app) |

---

## Детали по модулям

### base_manager
- **Путь:** `multiprocess_framework.refactored.modules.base_manager`
- **README:** `modules/base_manager/README.md`
- **Назначение:** Базовый класс для всех менеджеров, адаптеры, ObservableMixin

### worker_module
- **Путь:** `multiprocess_framework.refactored.modules.worker_module`
- **README:** `modules/worker_module/README.md`
- **Назначение:** Управление потоками (threading.Thread). Для QThread — App.ThreadManager

### router_module
- **Путь:** `multiprocess_framework.refactored.modules.router_module`
- **README:** `modules/router_module/README.md`
- **Назначение:** Единая точка маршрутизации сообщений между процессами/потоками

### message_module
- **Путь:** `multiprocess_framework.refactored.modules.message_module`
- **README:** `modules/message_module/README.md` (если есть)
- **Назначение:** Структура сообщений IPC (Message, MessageType)

### data_schema_module
- **Путь:** `multiprocess_framework.refactored.modules.data_schema_module`
- **README:** `modules/data_schema_module/docs/`
- **Назначение:** Схемы данных, регистры, FieldMeta, валидация

### shared_resources_module
- **Путь:** `multiprocess_framework.refactored.modules.shared_resources_module`
- **README:** (добавить)
- **Назначение:** Очереди, события, разделяемая память

---

## App → Framework зависимости

| Компонент App | Импортирует из framework |
|---------------|--------------------------|
| main_app | queue_manager (QueueManager) — **отсутствует** |
| coordinator | router_module (RouterManager, QueueChannel, Message, MessageType) |
| thread_manager | — (собственная реализация QThread) |
| RegistersManager | data_schema_module (FieldMeta, RegistersContainer) |

---

## Отсутствующие модули

| Модуль | Статус | Действие |
|--------|--------|----------|
| queue_manager | ❌ Не существует | Создать queue_module или адаптер в shared_resources |

---

## Как использовать этот индекс

1. **Добавляю новый модуль** → добавить строку в таблицу, создать README по шаблону
2. **Ищу зависимости** → смотреть колонки "Зависит от" и "Используется в"
3. **Пишу интеграцию** → смотреть "Импорты" и "Точки входа"
4. **Рефакторю** → проверять, не дублируется ли логика в framework
