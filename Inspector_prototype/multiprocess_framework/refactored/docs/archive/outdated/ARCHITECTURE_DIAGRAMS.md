# Визуальные Диаграммы Архитектуры (Refactored)

## 🎯 "Тройца создания циклов" - Главная схема

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROCESSMANAGERCORE (СВЕРХЭГО)                        │
│                         BaseManager + ObservableMixin                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Компоненты управления                             │  │
│  ├───────────────────────────────────────────────────────────────────────┤  │
│  │  ProcessLifecycle  │  ProcessPriority  │  ProcessStatus              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Методы:                                                                    │
│    • create_process()      • start_process()      • stop_process()          │
│    • register_worker()    • register_queue()     • get_process_status()    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   Создает и управляет         │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│ProcessManager    │        │ VisionProcess   │        │  AIProcess      │
│Process (ЭГО)     │        │     (ЭГО)        │        │     (ЭГО)        │
│                  │        │                  │        │                  │
│ ┌──────────────┐ │        │ ┌──────────────┐ │        │ ┌──────────────┐ │
│ │WorkerManager │ │        │ │WorkerManager │ │        │ │WorkerManager │ │
│ │    (ИД)      │ │        │ │    (ИД)      │ │        │ │    (ИД)      │ │
│ │              │ │        │ │              │ │        │ │              │ │
│ │• monitor     │ │        │ │• camera      │ │        │ │• inference   │ │
│ │• commands    │ │        │ │• capture     │ │        │ │• processing  │ │
│ └──────────────┘ │        │ └──────────────┘ │        │ └──────────────┘ │
└──────────────────┘        └──────────────────┘        └──────────────────┘
```

---

## 🔄 Полный поток создания и запуска процесса

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ProcessManagerCore.create_process()                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
        ┌───────────▼───────────┐       ┌───────────▼───────────┐
        │ 1. Создание ProcessData│       │ 2. Регистрация очередей│
        │                        │       │                        │
        │ ProcessStateRegistry   │       │ QueueRegistry          │
        │   .register_process_  │       │   .create_and_         │
        │   state(name, state)   │       │   register_queues()    │
        └───────────┬───────────┘       └───────────┬───────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ 3. Создание процесса ОС        │
                    │                                │
                    │ Process(                        │
                    │   target=run_process_function,  │
                    │   args=(class_path, name, ...)  │
                    │ )                               │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ 4. Запуск процесса ОС         │
                    │                                │
                    │ Process.start()                │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ 5. run_process_function()     │
                    │    (в дочернем процессе)      │
                    │                                │
                    │ • Загружает класс процесса     │
                    │ • Получает ProcessData         │
                    │ • Создает ProcessModule        │
                    │ • Вызывает initialize()        │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ 6. ProcessModule.initialize()│
                    │                                │
                    │ • ProcessLifecycle.init()     │
                    │ • ProcessManagers.init()      │
                    │   └─ WorkerManager.init()     │
                    │   └─ LoggerManager.init()     │
                    │   └─ RouterManager.init()     │
                    │ • SystemThreads.init()        │
                    │   └─ WorkerManager.create_    │
                    │      worker("message_proc")    │
                    │ • ProcessState.register()      │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ 7. ProcessModule.run()        │
                    │                                │
                    │ • WorkerManager.start_all()    │
                    │ • Основной цикл процесса       │
                    └────────────────────────────────┘
```

---

## 📡 Взаимодействие через SharedResources

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ProcessManagerCore                                        │
│                    ┌──────────────────────┐                                 │
│                    │ ProcessManagerProcess│                                 │
│                    └──────────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Использует
                                    │
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                    SharedResourcesManager                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              ProcessStateRegistry                                      │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │  ProcessData (VisionProcess)                                    │  │  │
│  │  │  • config: {process: {...}, managers: {...}}                   │  │  │
│  │  │  • custom: {queues: {...}, events: [...]}                     │  │  │
│  │  │  • state: {status: "running", metadata: {...}}                │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │  ProcessData (AIProcess)                                        │  │  │
│  │  │  • config: {...}                                                │  │  │
│  │  │  • custom: {...}                                                │  │  │
│  │  │  • state: {...}                                                 │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              EventManager                                              │  │
│  │  • subscribe(PROCESS_STATE_CHANGED, handler)                         │  │
│  │  • emit(PROCESS_STATE_CHANGED, data)                                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
        ┌───────────▼───────────┐       ┌───────────▼───────────┐
        │  VisionProcess         │       │  AIProcess            │
        │  (ProcessModule)        │       │  (ProcessModule)       │
        │                        │       │                        │
        │ • Читает ProcessData   │       │ • Читает ProcessData   │
        │ • Обновляет state      │       │ • Обновляет state      │
        │ • Использует queues    │       │ • Использует queues    │
        └────────────────────────┘       └────────────────────────┘
```

---

## 🔄 Поток данных: Отправка сообщения

```
VisionProcess (отправитель)
    │
    ├── ProcessModule.send_message("AIProcess", message)
    │       │
    │       └── ProcessCommunication.send(message)
    │               │
    │               └── RouterManager.send(message)
    │                       │
    │                       ├── Определяет канал: "queue"
    │                       │
    │                       └── QueueRegistry.send_to_queue(
    │                               "AIProcess", "system", message
    │                           )
    │                               │
    │                               └── ProcessData.custom['queues']['system'].put(message)
    │                                       │
    │                                       └── Queue (multiprocessing.Queue)
    │                                               │
    │                                               │ Межпроцессная очередь
    │                                               │
AIProcess (получатель)
    │
    ├── SystemThreads._message_processing_loop()
    │       │
    │       └── RouterManager.receive(timeout=0.0)
    │               │
    │               └── QueueRegistry.get_queue("AIProcess", "system").get()
    │                       │
    │                       └── ProcessData.custom['queues']['system'].get()
    │                               │
    │                               └── Обработка сообщения
```

---

## 🔄 Поток данных: Обновление состояния

```
VisionProcess
    │
    ├── ProcessModule.update_process_state(status="running")
    │       │
    │       └── ProcessState.update(status="running")
    │               │
    │               └── SharedResourcesManager.update_process_state(
    │                       "VisionProcess", status="running"
    │                   )
    │                       │
    │                       └── ProcessStateRegistry.update_process_state(
    │                               "VisionProcess", status="running"
    │                           )
    │                               │
    │                               ├── Обновляет ProcessData.state.status
    │                               │
    │                               └── EventManager.emit(
    │                                       PROCESS_STATE_CHANGED,
    │                                       {process_name: "VisionProcess", ...}
    │                                   )
    │                                       │
    │                                       └── ProcessManagerProcess.state_monitor
    │                                               │
    │                                               └── Получает событие через
    │                                                   EventManager.subscribe()
    │                                                       │
    │                                                       └── Отслеживает изменения
    │                                                           и отправляет broadcast
```

---

## 🔄 Поток данных: Работа с конфигурацией

```
VisionProcess
    │
    ├── ProcessModule.get_config("camera.fps")
    │       │
    │       └── ProcessConfigHandler.get("camera.fps")
    │               │
    │               ├── Проверяет локальный ConfigManager
    │               │       │
    │               │       └── Если есть → возвращает значение
    │               │
    │               └── Если нет → ProcessData.config
    │                       │
    │                       └── SharedResourcesManager.get_process_data("VisionProcess")
    │                               │
    │                               └── ProcessStateRegistry.get_process_data("VisionProcess")
    │                                       │
    │                                       └── ProcessData.config.process.camera.fps
    │                                               │
    │                                               └── Иерархическая конфигурация:
    │                                                       • Глобальная конфигурация
    │                                                       • Конфигурация процесса
    │                                                       • Локальные переопределения
```

---

## 🧵 Поток данных: Создание воркера

```
VisionProcess
    │
    ├── ProcessModule._init_application_threads()
    │       │
    │       └── WorkerManager.create_worker("camera", camera_func, config)
    │               │
    │               └── WorkerLifecycle.create_worker()
    │                       │
    │                       ├── Проверяет зависимости
    │                       ├── Создает threading.Thread
    │                       ├── Регистрирует в WorkerRegistry
    │                       └── Запускает поток (если auto_start=True)
    │                               │
    │                               └── threading.Thread.start()
    │                                       │
    │                                       └── camera_func(stop_event, pause_event)
    │                                               │
    │                                               └── Основной цикл воркера
```

---

## 📊 Структура ProcessData (data_schema)

```
ProcessData
├── name: str                    # Имя процесса
│
├── config: ProcessConfig        # Конфигурация процесса
│   ├── process: Dict           # Конфигурация процесса
│   │   ├── name: str
│   │   ├── class: str
│   │   ├── priority: str
│   │   └── queues: Dict
│   │
│   ├── managers: Dict         # Конфигурация менеджеров
│   │   ├── logger: Dict
│   │   ├── command: Dict
│   │   └── router: Dict
│   │
│   └── modules: Dict           # Конфигурация модулей
│
├── custom: Dict                # Кастомные данные
│   ├── queues: Dict           # Очереди процесса
│   │   ├── system: Queue
│   │   ├── data: Queue
│   │   └── broadcast: Queue
│   │
│   ├── events: List           # События процесса
│   │
│   ├── console_queues: List   # Очереди консоли
│   │
│   └── component_managers: Dict # Данные менеджеров компонентов
│       └── {component_name}: Dict
│
└── state: ProcessState         # Состояние процесса
    ├── status: str            # initializing, ready, running, stopped, error
    ├── metadata: Dict         # Метаданные процесса
    └── events: List           # События состояния
```

---

## 🎯 Ответственность компонентов (визуально)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ProcessManagerCore (Сверхэго)                            │
│                    ┌─────────────────────────────────────┐                  │
│                    │  Ответственность:                  │                  │
│                    │  • Создание процессов ОС            │                  │
│                    │  • Управление жизненным циклом процессов     │                  │
│                    │  • Мониторинг состояния   процессов     │                  │
│                    │  • Управление приоритетами           │                  │
│                    └─────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    ProcessModule (Эго)                                      │
│                    ┌─────────────────────────────────────┐                  │
│                    │  Ответственность:                  │                  │
│                    │  • Жизненный цикл процесса          │                  │
│                    │  • Координация менеджеров  процесса         │                  │
│                    │  • Межпроцессная коммуникация        │                  │
│                    │  • Управление состоянием             │                  │
│                    │  • Системные потоки (на основе WorkerManager)            │                  │
│                    └─────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    WorkerManager (Ид)                                       │
│                    ┌─────────────────────────────────────┐                  │
│                    │  Ответственность:                  │                  │
│                    │  • Создание потоков-воркеров        │                  │
│                    │  • Управление жизненным циклом      │                  │
│                    │  • Приоритеты выполнения            │                  │
│                    │  • Метрики производительности        │                  │
│                    │  • Автоматический перезапуск         │                  │
│                    └─────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

*Визуальные диаграммы архитектуры v2.0*  
*Inspector Bottle V2 - Refactored Architecture*

