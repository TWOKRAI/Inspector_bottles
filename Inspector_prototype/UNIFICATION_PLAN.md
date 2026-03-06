# План унификации: multiprocess_framework + App

**Версия:** 1.0  
**Дата:** 2025-03-05  
**Цель:** multiprocess_framework — конструктор для backend и frontend. App — одно из приложений. Модули слабо связаны, каждый со своей документацией.

---

## 1. Концепция

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    multiprocess_framework (КОНСТРУКТОР)                     │
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ base_manager│  │  router_    │  │  worker_    │  │  shared_resources   │ │
│  │             │  │  module     │  │  module     │  │  (queue_module)     │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                │                     │           │
│         └────────────────┼────────────────┼─────────────────────┘           │
│                          │                │                                  │
│         Все менеджеры наследуются от BaseManager                             │
│         Все процессы общаются через RouterManager                            │
│         Потоки — WorkerManager или QThread-обёртки                          │
└──────────────────────────┼────────────────┼──────────────────────────────────┘
                           │                │
                           ▼                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    App (ФРОНТЕНД)                                            │
│  Coordinator → ThreadManager (QThread) / WindowManager / RegistersManager   │
│  Использует: router_module, queue_manager (shared_resources), data_schema   │
└─────────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Backend (Multiproccesing/)                                │
│  Processes_Manager → camera, processing, post_processing, etc.              │
│  Использует: QueueManager, RouterManager                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Текущие проблемы и пробелы

| Проблема | Описание |
|----------|----------|
| **queue_manager отсутствует** | `main_app` импортирует `multiprocess_framework.refactored.modules.queue_manager`, но модуля нет. Реализация в `Multiproccesing/Queue_Manager.py`. |
| **Два WorkerManager** | `worker_module` — `threading.Thread`, `App/thread_manager` — `QThread`. Нет интеграции. |
| **Два WindowManager** | `Core/Application/window_manager` (новый) vs `Core/Managers/window_manager` (legacy). |
| **Разрозненная документация** | 70+ .md в framework, но нет единого шаблона для модулей. |
| **Processes_Manager не запускается** | Backend не стартует из `main_app` в новой архитектуре. |

---

## 3. План действий (пошагово)

### Фаза 0: Документация (старт для всех)

**Цель:** Создать шаблон README для каждого модуля и единый индекс.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 0.1 | Создать `multiprocess_framework/refactored/docs/MODULE_README_TEMPLATE.md` | Шаблон |
| 0.2 | Создать `multiprocess_framework/refactored/docs/MODULES_INDEX.md` | Таблица: модуль → импорты, точки входа, зависимости |
| 0.3 | Добавить README в каждый модуль по шаблону | Понимание: кто что делает, как связывать |

**Шаблон README модуля:**

```markdown
# Модуль {name}

## Назначение
Кратко: что делает.

## Импорты
```python
from multiprocess_framework.refactored.modules.{name} import X, Y
```

## Точки входа
- `ClassName.method()` — описание

## Зависимости
- Зависит от: `base_manager`, `message_module`
- Используется в: `router_module`, `App`

## Пример
```python
# минимальный пример
```

## Связь с другими модулями
Схема/таблица.
```

---

### Фаза 1: queue_manager в framework

**Цель:** `queue_manager` должен быть в framework.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 1.1 | Создать `multiprocess_framework/refactored/modules/queue_module/` | Новый модуль |
| 1.2 | Перенести/адаптировать `Queue_Manager` из `Multiproccesing/` | `QueueManager` в framework |
| 1.3 | `QueueManager` наследует `BaseManager` (опционально) | Единообразие |
| 1.4 | `multiprocess_framework.refactored.modules.queue_manager` → `queue_module` | main_app импортирует из framework |
| 1.5 | README для queue_module | Документация |

**Или:** `shared_resources_module` уже содержит `QueueRegistry`. Добавить `QueueManager` как фасад/адаптер над `QueueRegistry` + legacy-совместимость.

---

### Фаза 2: Унификация WorkerManager и ThreadManager

**Цель:** Framework поддерживает и `threading.Thread`, и `QThread`.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 2.1 | Добавить в `worker_module` поддержку QThread | `QThreadWorkerAdapter` или `QThreadWorker` |
| 2.2 | Или: `ThreadManager` (App) наследует `BaseManager` (framework) | Единообразие |
| 2.3 | Или: `ThreadManager` — тонкая обёртка над `WorkerManager` для QThread | `WorkerManager` для backend, `ThreadManager` для UI |
| 2.4 | README worker_module: когда использовать WorkerManager, когда ThreadManager | Чёткое разделение |

**Рекомендация:**  
- **WorkerManager** — для backend (processes, daemon threads).  
- **ThreadManager** — для App (QThread, UI).  
- **Общий интерфейс:** `register()` / `create()` / `start()` / `stop()`.  
- **Адаптер:** `QThreadWorker` — обёртка над `QThread` с совместимостью с `WorkerManager` (если нужна единая точка входа).

---

### Фаза 3: Менеджеры — единый BaseManager

**Цель:** Все менеджеры наследуют `BaseManager`.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 3.1 | Проверить: RouterManager, WorkerManager, LoggerManager — наследуют BaseManager | Уже есть |
| 3.2 | App: `ThreadManager` — опционально наследовать BaseManager | Для единообразия |
| 3.3 | App: `WindowManager` — опционально наследовать BaseManager | Для единообразия |
| 3.4 | Документировать: какие менеджеры в framework, какие в App | MODULES_INDEX |

---

### Фаза 4: Документация и индекс модулей

**Цель:** У каждого модуля — свой README. Единый индекс.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 4.1 | Создать `MODULE_README_TEMPLATE.md` | Шаблон |
| 4.2 | Создать `MODULES_INDEX.md` | Таблица: модуль, импорты, точки входа, зависимости |
| 4.3 | Пройти по всем модулям: base_manager, worker_module, router_module, message_module, data_schema_module, shared_resources_module, process_module, config_module, logger_module, dispatch_module, command_module | README в каждом |
| 4.4 | App: `App/docs/APP_MODULES.md` | Таблица: модуль App → импорты, зависимости от framework |

---

### Фаза 5: Выделение костяка App в framework

**Цель:** Универсальные классы в framework, специфика App — в App.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 5.1 | Определить: что в App универсально? | Coordinator-подобный, ThreadManager, WindowRegistry |
| 5.2 | `ApplicationCoordinator` — шаблон в framework? | `BaseCoordinator` или `BaseApplication` |
| 5.3 | `ThreadManager` — в framework как `QThreadManager` (если QThread) | Переиспользование |
| 5.4 | `WindowRegistry` — в framework? | Если не UI-специфичен |
| 5.5 | Перенести только то, что не зависит от PyQt/Inspector | Минимум дублирования |

---

### Фаза 6: Процессы и запуск backend

**Цель:** `main_app` запускает и App, и backend.

| Шаг | Действие | Результат |
|-----|----------|-----------|
| 6.1 | `Processes_Manager` — интегрировать в framework | `process_module` или `process_manager_module` |
| 6.2 | `main_app`: после создания QueueManager — запуск Processes_Manager | Backend стартует |
| 6.3 | `process_ready_queue` — используется в Loading | LoadingWindow ждёт готовности |

---

## 4. Порядок выполнения (для нейросетей)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ПРИОРИТЕТ 1: Документация (можно делать параллельно)                        │
│  - MODULE_README_TEMPLATE.md                                                 │
│  - MODULES_INDEX.md                                                          │
│  - README в каждом модуле framework                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ПРИОРИТЕТ 2: queue_manager в framework                                     │
│  - Создать queue_module или расширить shared_resources                      │
│  - main_app импортирует из framework                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ПРИОРИТЕТ 3: WorkerManager + ThreadManager                                 │
│  - Документировать разделение: WorkerManager (backend) vs ThreadManager (UI)│
│  - Опционально: QThreadWorker в worker_module                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ПРИОРИТЕТ 4: Процессы и backend                                            │
│  - Processes_Manager в main_app                                             │
│  - process_ready_queue                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ПРИОРИТЕТ 5: Выделение костяка App в framework                             │
│  - BaseCoordinator, QThreadManager (если универсально)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Структура документации модуля (шаблон)

Каждый модуль в `multiprocess_framework/refactored/modules/{name}/`:

```
{name}/
├── __init__.py          # Публичный API
├── README.md            # Обязательно
├── core/
├── ...
└── docs/                # Опционально, для сложных модулей
```

**README.md содержит:**

1. **Назначение** — 1–2 предложения  
2. **Импорты** — что экспортировать  
3. **Точки входа** — основные классы/методы  
4. **Зависимости** — от кого зависит, кем используется  
5. **Пример** — минимальный пример  
6. **Связь с другими модулями** — таблица или схема  

---

## 6. MODULES_INDEX (черновик)

| Модуль | Импорты | Точки входа | Зависимости |
|--------|---------|-------------|-------------|
| base_manager | BaseManager, BaseAdapter, ObservableMixin | initialize(), shutdown() | — |
| worker_module | WorkerManager, ThreadConfig, ThreadPriority | create_worker(), start_worker(), stop_worker() | base_manager |
| router_module | RouterManager, QueueChannel, Message | send_async(), register_channel(), register_route() | message_module, dispatch_module |
| message_module | Message, MessageType | Message.create() | — |
| data_schema_module | RegistersContainer, FieldMeta, etc. | — | — |
| shared_resources_module | QueueRegistry, EventManager | — | — |
| queue_module | QueueManager | (создать) | shared_resources? |
| process_module | ProcessModule | — | config, shared_resources |
| config_module | ConfigModule | — | base_manager |
| logger_module | LoggerManager | — | base_manager |
| dispatch_module | Dispatcher, DispatchStrategy | — | — |
| command_module | CommandManager | — | base_manager |

---

## 7. Связанные документы

- `App/NEW_ARCHITECTURE.md` — архитектура App  
- `multiprocess_framework/refactored/docs/MODULES_STATUS.md` — статус модулей  
- `multiprocess_framework/refactored/modules/base_manager/README.md` — пример  
- `multiprocess_framework/refactored/modules/router_module/README.md` — пример  

---

## 8. Checklist для разработчика/нейросети

1. [ ] Прочитал UNIFICATION_PLAN.md  
2. [ ] Прочитал README целевого модуля  
3. [ ] Проверил MODULES_INDEX для зависимостей  
4. [ ] При добавлении нового модуля — создал README по шаблону  
5. [ ] Обновил MODULES_INDEX  
6. [ ] Не дублировал логику — использовал framework  
