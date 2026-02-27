# Иерархия Классов Process Manager Module

## 📊 Текущая Структура (До Рефакторинга)

```
┌─────────────────────────────────────────────────────────────┐
│                    SystemLauncher                           │
│  - Высокоуровневый интерфейс для запуска системы            │
│  - Обработка сигналов                                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ использует
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              ProcessManagerBootstrap                        │
│  - Создает ManagerProcess как процесс ОС                    │
│  - Передает конфигурацию через SharedResourcesManager       │
└──────────────────────┬──────────────────────────────────────┘
                       │ создает
                       ↓
┌─────────────────────────────────────────────────────────────┐
│          ProcessManagerProcess (ProcessModule)              │
│  - ProcessManager как процесс системы                       │
│  - Обрабатывает команды через роутер                        │
│  - Воркеры: priority_command_processor,                    │
│             normal_command_processor, batch_processor       │
└───────────────┬───────────────────────────┬─────────────────┘
                │ использует                │ создает
                ↓                           ↓
┌───────────────────────────────┐  ┌───────────────────────────────┐
│      ProcessManagerCore       │  │      ProcessMonitor           │
│  - Логика управления процессами│  │      (ProcessModule)          │
│  - Создание процессов ОС      │  │  - Мониторинг состояний       │
│  - Управление жизненным циклом│  │  - Broadcast изменений        │
└───────────────┬───────────────┘  └───────────────────────────────┘
                │ использует
                ↓
        ┌───────┴───────┬───────────────┬─────────────────┐
        │               │               │                 │
        ↓               ↓               ↓                 ↓
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ProcessLifecycle│ │ProcessPriority│ │ProcessStatus  │ │_run_process_  │
│                │ │               │ │               │ │  function     │
│- start_all()   │ │- set_priority()│ │- get_status() │ │               │
│- stop_all()    │ │- apply_...()  │ │- get_all_...()│ │- Запуск       │
│- join_all()    │ │- register_...()│ │- get_stats()  │ │  процесса     │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

## 🔄 Предлагаемая Структура (После Рефакторинга)

```
┌─────────────────────────────────────────────────────────────┐
│                    SystemLauncher                           │
│  - Высокоуровневый интерфейс для запуска системы            │
│  - Обработка сигналов                                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ использует
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              ProcessManagerBootstrap                        │
│  - Создает ManagerProcess как процесс ОС                    │
│  - Передает конфигурацию через SharedResourcesManager       │
└──────────────────────┬──────────────────────────────────────┘
                       │ создает
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              ManagerProcess (ProcessModule)                 │
│  - ProcessManager как процесс системы                       │
│  - Обрабатывает команды через роутер                        │
│                                                              │
│  Воркеры:                                                   │
│  ├── priority_command_processor  (REALTIME, 0.01s)        │
│  ├── normal_command_processor    (NORMAL, 0.1s)           │
│  ├── batch_processor             (BATCH, 1.0s)            │
│  └── state_monitor               (NORMAL, 0.5s) [НОВЫЙ]   │
│                                                              │
│  Методы:                                                    │
│  ├── _handle_priority_command()                            │
│  ├── _handle_normal_command()                              │
│  ├── _handle_batch_operation()                             │
│  └── _state_monitoring_loop()    [ИЗ ProcessMonitor]      │
└───────────────┬─────────────────────────────────────────────┘
                │ использует
                ↓
┌─────────────────────────────────────────────────────────────┐
│              ProcessManagerCore                             │
│  - Логика управления процессами                             │
│  - Создание процессов ОС                                    │
│  - Управление жизненным циклом                              │
└───────────────┬─────────────────────────────────────────────┘
                │ использует
                ↓
        ┌───────┴───────┬───────────────┬─────────────────┐
        │               │               │                 │
        ↓               ↓               ↓                 ↓
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ProcessLifecycle│ │ProcessPriority│ │ProcessStatus  │ │_run_process_  │
│                │ │               │ │               │ │  function     │
│- start_all()   │ │- set_priority()│ │- get_status() │ │               │
│- stop_all()    │ │- apply_...()  │ │- get_all_...()│ │- Запуск       │
│- join_all()    │ │- register_...()│ │- get_stats()  │ │  процесса     │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

## 🔍 Детализация Классов

### ManagerProcess (было ProcessManagerProcess)

```python
class ManagerProcess(ProcessModule):
    """
    ProcessManager как процесс системы.
    
    Наследуется от ProcessModule для единообразия архитектуры.
    Использует ProcessManagerCore для выполнения операций управления процессами.
    Обрабатывает команды через роутер с помощью специализированных воркеров.
    """
    
    # Компоненты
    - core: ProcessManagerCore          # Логика управления процессами
    - platform: PlatformAdapter         # Адаптер платформы
    - config_manager: ConfigManager     # Менеджер конфигураций
    - queue_registry: QueueRegistry     # Реестр очередей
    - console_manager: ConsoleManager   # Менеджер консолей
    
    # Воркеры
    - priority_command_processor        # Приоритетные команды
    - normal_command_processor          # Обычные команды
    - batch_processor                   # Batch операции
    - state_monitor                     # Мониторинг состояний [НОВЫЙ]
    
    # Методы обработки команд
    - _handle_priority_command()        # start/stop/restart
    - _handle_normal_command()          # register_worker/queue
    - _handle_batch_operation()         # stats/status/health
    - _state_monitoring_loop()          # Мониторинг [ИЗ ProcessMonitor]
```

### ProcessManagerCore

```python
class ProcessManagerCore:
    """
    Утилитарный класс с логикой управления процессами.
    
    Не является процессом - содержит только бизнес-логику.
    Используется ManagerProcess для выполнения операций.
    """
    
    # Компоненты
    - shared_resources: SharedResourcesManager
    - queue_registry: QueueRegistry
    - config_manager: ConfigManager
    - console_manager: ConsoleManager
    - logger: LoggerManager
    - platform: PlatformAdapter
    - stop_event: Event
    
    # Утилиты
    - lifecycle: ProcessLifecycle       # Управление жизненным циклом
    - priority: ProcessPriority         # Управление приоритетами
    - status: ProcessStatus             # Мониторинг статусов
    
    # Методы
    - create_process()                  # Создание процесса ОС
    - create_processes_from_config()    # Создание из конфига
    - start_process()                   # Запуск процесса
    - stop_process()                    # Остановка процесса
    - register_worker()                 # Регистрация воркера
    - register_queue()                  # Регистрация очереди
    - get_process_status()              # Получение статуса
```

### ProcessLifecycle

```python
class ProcessLifecycle:
    """
    Управление жизненным циклом процессов ОС.
    """
    
    - os_processes: List[Process]       # Список процессов
    
    - add_process()                     # Добавить процесс
    - start_all()                       # Запустить все
    - stop_all()                        # Остановить все
    - join_all()                        # Ожидать завершения
    - wait_for_all()                    # Ожидание бесконечно
    - get_process_by_name()             # Найти по имени
```

### ProcessPriority

```python
class ProcessPriority:
    """
    Управление приоритетами процессов ОС.
    """
    
    - process_priorities: Dict[str, str]  # Маппинг имен → приоритетов
    - platform: PlatformAdapter           # Адаптер платформы
    - PRIORITY_MAP: Dict                  # Маппинг приоритетов
    
    - set_priority()                      # Установить приоритет
    - register_priority()                 # Зарегистрировать
    - get_priority()                      # Получить приоритет
    - apply_priority()                    # Применить приоритет
    - is_valid_priority()                 # Проверить валидность
```

### ProcessStatus

```python
class ProcessStatus:
    """
    Мониторинг статуса процессов.
    """
    
    - os_processes: List[Process]        # Список процессов
    
    - get_process_status()               # Статус одного процесса
    - get_all_status()                   # Статусы всех процессов
    - get_alive_count()                  # Количество живых
    - get_dead_count()                   # Количество завершенных
    - get_total_count()                  # Всего процессов
    - get_stats()                        # Полная статистика
```

## 🔗 Зависимости Между Модулями

### Импорты (Односторонние)

```
ManagerProcess
  ├── ProcessManagerCore (core/)
  ├── ProcessModule (Process_module/)
  ├── SharedResourcesManager (Shared_resources_module/)
  ├── ConfigManager (Config_module/)
  ├── ConsoleManager (Console_module/)
  └── LoggerManager (Logger_module/)

ProcessManagerCore
  ├── ProcessLifecycle (core/)
  ├── ProcessPriority (core/)
  ├── ProcessStatus (core/)
  ├── _run_process_function (runner/)
  ├── SharedResourcesManager (Shared_resources_module/)
  ├── QueueRegistry (Shared_resources_module/)
  ├── ProcessConfiguration (Shared_resources_module/)
  ├── ConfigManager (Config_module/)
  └── ConsoleManager (Console_module/)

ProcessLifecycle, ProcessPriority, ProcessStatus
  └── (не имеют зависимостей от других классов модуля)
```

## 📝 Конфигурация

### ProcessConfig vs ProcessConfiguration

```
┌─────────────────────────────────────────────────────────────┐
│                   ProcessConfig                             │
│  (config/process_config.py)                                 │
│                                                              │
│  Назначение: Валидация конфигураций в ConfigManager         │
│  Использование: ConfigManager.load_process_config()         │
│                                                              │
│  Методы:                                                    │
│  - validate_config()                                        │
│  - add_process_config()                                     │
│  - get_process_config()                                     │
│  - get_enabled_configs()                                    │
└─────────────────────────────────────────────────────────────┘
                              ↓ используется для создания
┌─────────────────────────────────────────────────────────────┐
│              ProcessConfiguration                           │
│  (Shared_resources_module/process_config.py)                │
│                                                              │
│  Назначение: Хранение данных в ProcessData                  │
│  Использование: ProcessData.config                          │
│                                                              │
│  Методы:                                                    │
│  - get_process_config()                                     │
│  - get_manager_config()                                     │
│  - get_module_config()                                      │
│  - to_dict()                                                │
│  - from_dict()                                              │
└─────────────────────────────────────────────────────────────┘
```

**Разница:**
- `ProcessConfig` - валидация и работа с ConfigManager (входные данные)
- `ProcessConfiguration` - хранение в ProcessData (выходные данные)

## ✅ Итоговая Архитектура

1. **SystemLauncher** - точка входа
2. **ProcessManagerBootstrap** - создает ManagerProcess
3. **ManagerProcess** - процесс-менеджер с воркерами
4. **ProcessManagerCore** - бизнес-логика управления
5. **ProcessLifecycle/Priority/Status** - утилиты
6. **process_runner** - запуск процессов

**Преимущества:**
- ✅ Четкое разделение ответственности
- ✅ Нет циклических зависимостей
- ✅ Мониторинг как часть ManagerProcess (не отдельный ProcessModule)
- ✅ Простая и понятная структура

