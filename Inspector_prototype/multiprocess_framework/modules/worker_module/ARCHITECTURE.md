# Worker Module — Архитектурное руководство

Этот документ описывает **внутренний дизайн** `worker_module`: как компоненты взаимодействуют, как управляется жизненный цикл и как модуль интегрируется с фреймворком.

---

## Обзор системы

### Главная диаграмма

```
┌─────────────────────────────────────────────────────────────┐
│ ProcessModule (OS Process)                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ WorkerManager (BaseManager + ObservableMixin)        │   │
│  ├──────────────────────────────────────────────────────┤   │
│  │                                                       │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐   │   │
│  │  │ WorkerRegistry  │  │ WorkerLifecycle         │   │   │
│  │  │ (potent-safe)   │  │ (create/start/stop)     │   │   │
│  │  │                 │  │                         │   │   │
│  │  │ - workers{}     │  │ - _worker_wrapper()     │   │   │
│  │  │ - Lock          │  │ - _auto_restart()       │   │   │
│  │  │ - get_by_type() │  │                         │   │   │
│  │  └─────────────────┘  └─────────────────────────┘   │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Потоки (Threads)                                    │   │
│  ├──────────────────────────────────────────────────────┤   │
│  │                                                       │   │
│  │  Системные:              Прикладные:                │   │
│  │  • message_processor     • worker_1                 │   │
│  │  • health_check (*)      • worker_2                 │   │
│  │                          • task_worker              │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ RouterManager (межпроцессное общение)               │   │
│  ├──────────────────────────────────────────────────────┤   │
│  │                                                       │   │
│  │  Каналы:                                            │   │
│  │  • local (queue.Queue) ← межпоточное                │   │
│  │  • process_1_worker_in (mp.Queue) ← межпроцесс      │   │
│  │  • process_2_worker_in (mp.Queue) ← межпроцесс      │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Компоненты

### 1. WorkerManager

**Роль:** Главный менеджер, реализует жизненный цикл всех потоков.

**Наследование:**
```
BaseManager
    ▲
    │
    ├── ObservableMixin
    │
WorkerManager ← реализует IWorkerManager
```

**Ответственность:**
- Создание и регистрация воркеров
- Запуск/остановка/перезагрузка потоков
- Мониторинг статуса и метрик
- Потокобезопасность через Lock

**Ключевые методы:**

```python
class WorkerManager:
    # Жизненный цикл
    def initialize(self) -> bool: ...
    def shutdown(self) -> bool: ...
    
    # CRUD
    def create_worker(name, target, config, auto_start=False) -> bool: ...
    def start_worker(name) -> bool: ...
    def stop_worker(name, timeout=5.0) -> bool: ...
    def restart_worker(name, timeout=5.0) -> bool: ...
    
    # Управление состоянием
    def pause_worker(name) -> bool: ...
    def resume_worker(name) -> bool: ...
    
    # Групповые операции
    def start_all_workers() -> None: ...
    def stop_all_workers() -> None: ...
    
    # Мониторинг
    def get_worker_status(name) -> Optional[Dict]: ...
    def get_all_workers_status() -> Dict[str, Dict]: ...
    def get_worker_metrics(name) -> Optional[Dict]: ...
    def is_worker_running(name) -> bool: ...
    
    # Фильтрация
    def list_workers(worker_type=None) -> List[str]: ...
    def list_system_workers() -> List[str]: ...
    def list_application_workers() -> List[str]: ...
    
    # Статистика
    def get_stats() -> Dict[str, Any]: ...
```

### 2. WorkerRegistry

**Роль:** Потокобезопасное хранилище информации о всех воркерах.

**Данные:**
```python
class WorkerRegistry:
    _lock: threading.Lock  # Потокобезопасность
    _workers: Dict[str, WorkerInfo]  # имя → полная инфа о воркере
```

**WorkerInfo содержит:**
```python
WorkerInfo = TypedDict({
    'thread': threading.Thread,          # OS thread object
    'stop_event': threading.Event,       # Сигнал для остановки
    'pause_event': threading.Event,      # Сигнал для паузы
    'target': Callable,                  # Функция воркера
    'config': ThreadConfig,              # Параметры потока
    'status': WorkerStatus,              # текущий статус
    'worker_type': WorkerType,           # SYSTEM или APPLICATION
    'execution_mode': ExecutionMode,     # LOOP или TASK
    'restart_count': int,                # сколько раз перезапускался
    'last_error': Optional[str],         # последняя ошибка
    'start_time': Optional[float],       # timestamp начала
    'total_runtime': float,              # общее время работы
    'last_run_duration': float,          # последний цикл
    'successful_runs': int,              # успешных итераций
    'failed_runs': int,                  # неудачных итераций
    'has_been_started': bool,            # когда-либо запускался?
})
```

**Методы:**

```python
def register(...) -> bool: ...           # Добавить воркер
def unregister(name) -> bool: ...        # Удалить воркер
def get(name) -> Optional[WorkerInfo]: ... # Получить инфу
def has(name) -> bool: ...               # Существует ли?
def get_all_names() -> List[str]: ...    # Все имена
def get_by_type(type) -> List[str]: ...  # Фильтр по типу
def update_status(name, status): ...     # Обновить статус
def get_status(name) -> WorkerStatus: ... # Получить статус
def snapshot() -> Dict: ...              # Снимок всех данных
```

### 3. WorkerLifecycle

**Роль:** Управление жизненным циклом одного воркера (create/start/stop/restart).

**Граф состояний:**

```
        ┌─────────────┐
        │  CREATED    │ (зарегистрирован, не запущен)
        └────┬────────┘
             │ start_worker()
             ▼
        ┌─────────────┐
        │  RUNNING    │◄─────────┐
        └────┬────────┘          │
             │                   │ resume_worker()
             │ pause_worker()    │
             ▼                   │
        ┌─────────────┐          │
        │   PAUSED    ├──────────┘
        └────┬────────┘
             │ stop_worker()
             ▼
        ┌─────────────┐
   ┌───►│  STOPPING   │
   │    └────┬────────┘
   │         │
   │         ▼
   │    ┌─────────────┐
   │    │  STOPPED    │  (для LOOP режима)
   │    └─────────────┘
   │
   │    ┌─────────────┐
   └───►│ COMPLETED   │  (для TASK режима)
        └─────────────┘
        
        ┌─────────────┐
        │   ERROR     │  (если исключение)
        └─────────────┘
```

**Ключевой метод:**

```python
def _worker_wrapper(self, worker_name, target, stop_event, pause_event):
    """Обёртка для потока. Обрабатывает События, ошибки, метрики."""
    
    try:
        # Запуск целевой функции
        target(stop_event, pause_event)
        
        # Если режим TASK — статус COMPLETED, иначе STOPPED
        if execution_mode == ExecutionMode.TASK:
            registry.update_status(worker_name, WorkerStatus.COMPLETED)
        else:
            registry.update_status(worker_name, WorkerStatus.STOPPED)
            
    except Exception as e:
        # Обработка ошибки
        registry.update_status(worker_name, WorkerStatus.ERROR)
        registry.set_last_error(worker_name, str(e))
        
        # Автоперезапуск если включен
        if config.restart_on_failure and restart_count < max_restarts:
            restart_worker(worker_name)
```

### 4. ThreadConfig

**Роль:** Конфигурация параметров потока, поддерживает Dict at Boundary.

```python
class ThreadConfig:
    priority: ThreadPriority                 # Poll interval
    restart_on_failure: bool                 # Auto-restart?
    max_restarts: int                        # Max attempts
    dependencies: List[str]                  # Запустить после
    worker_type: WorkerType                  # SYSTEM / APPLICATION
    execution_mode: ExecutionMode            # LOOP / TASK
    
    def to_dict(self) -> dict: ...          # → dict
    @classmethod
    def from_dict(cls, data: dict) -> 'ThreadConfig': ...  # ← dict
```

**Пример сериализации:**

```python
config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    worker_type=WorkerType.APPLICATION,
    execution_mode=ExecutionMode.LOOP,
)

# Сохранить в конфиге процесса (Dict at Boundary)
thread_dict = config.to_dict()
# {
#     "priority": "NORMAL",
#     "restart_on_failure": False,
#     "max_restarts": 3,
#     "dependencies": [],
#     "worker_type": "application",
#     "execution_mode": "loop",
# }

# Восстановить из конфига
config = ThreadConfig.from_dict(thread_dict)
```

### 5. Типы (types.py)

```python
class WorkerStatus(Enum):
    STOPPED = "stopped"           # LOOP воркер остановлен
    RUNNING = "running"           # Выполняется
    ERROR = "error"               # Ошибка при выполнении
    STOPPING = "stopping"         # Завершение в прогрессе
    COMPLETED = "completed"       # TASK воркер завершён (успешно)

class ThreadPriority(Enum):
    SYSTEM = 0                    # 0.001s
    REALTIME = 1                  # 0.01s
    NORMAL = 2                    # 0.1s (default)
    BATCH = 3                     # 1.0s
    BACKGROUND = 4                # 5.0s

class WorkerType(Enum):
    SYSTEM = "system"             # Фреймворк
    APPLICATION = "application"   # Пользователь

class ExecutionMode(Enum):
    LOOP = "loop"                 # Бесконечный цикл
    TASK = "task"                 # Один раз и завершить
```

---

## Жизненный цикл потока

### Сценарий 1: LOOP воркер (постоянный)

```python
def worker_loop(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        # Работа
        process_data()
        time.sleep(0.1)
```

**Этапы:**

1. **create_worker()** — регистрация в WorkerRegistry
2. **start_worker()** — запуск потока через Thread(target=_worker_wrapper)
3. **[RUNNING]** — бесконечный цикл
   - Может быть PAUSED (pause_event выставлен)
   - Может быть RESUMED
4. **stop_worker()** — выставить stop_event
5. **_worker_wrapper() выходит** → STOPPED

**Метрики:**
- `start_time` — когда запустился
- `total_runtime` — общее время
- `successful_runs` — число итераций цикла
- `failed_runs` — число ошибок

### Сценарий 2: TASK воркер (одноразовый)

```python
def init_task(stop_event, pause_event):
    print("Инициализация...")
    do_init()
    # Функция завершается сама
```

**Этапы:**

1. **create_worker()** — регистрация
2. **start_worker()** — запуск потока
3. **[RUNNING]** — функция выполняется один раз
4. **Функция завершается** → COMPLETED или ERROR
5. **_worker_wrapper() выходит** → COMPLETED

**Метрики:**
- `start_time` — когда запустился
- `last_run_duration` — общее время выполнения
- `successful_runs` — 1 если успешно, 0 если нет

### Сценарий 3: Автоперезапуск после ошибки

```python
config = ThreadConfig(
    restart_on_failure=True,
    max_restarts=3,
)
```

**Этапы:**

1. **Воркер бросает исключение**
2. **_worker_wrapper() ловит Exception**
   - `registry.update_status(..., ERROR)`
   - `registry.set_last_error(..., str(e))`
3. **Проверка:** if `restart_count < max_restarts`
4. **restart_worker()** — увеличить счётчик и перезапустить
5. **После 3 ошибок** → окончательно STOPPED с ERROR статусом

---

## Интеграция с ProcessModule

### Инициализация

```python
class ProcessModule(BaseManager):
    def initialize(self) -> bool:
        # ProcessManagers.initialize() создаёт WorkerManager
        self.worker_manager = WorkerManager("process_name", process=self)
        self.worker_manager.initialize()
        
        # Регистрируем как менеджер в ObservableMixin
        self.register_manager('worker', self.worker_manager, enabled=True)
        
        # Создаём и регистрируем локальный канал
        from queue import Queue as ThreadQueue
        local_queue = ThreadQueue(maxsize=256)
        local_channel = QueueChannel(f"{self.name}_local", local_queue)
        self.router_manager.register_channel(local_channel)
```

### Создание воркеров из конфига

```python
def _create_workers_from_config(self, workers_config):
    """ProcessModule читает конфиги и создаёт воркеров."""
    
    for worker_name, worker_config in workers_config.items():
        # Загрузить класс воркера
        target = self._load_target(worker_config['class'])
        
        # Создать ThreadConfig из "thread" секции
        thread_dict = worker_config.get("thread", {})
        thread_config = ThreadConfig.from_dict(thread_dict)
        
        # Создать и запустить воркер
        self.worker_manager.create_worker(
            worker_name,
            target,
            thread_config,
            auto_start=True
        )
```

### Локальный канал для общения

```
worker_1                    worker_2
   │                          │
   └──► router.send()         │
        │                      │
        ▼                      │
   [local_channel]             │
   (queue.Queue)               │
        │                      │
        └──────► router.receive()
```

**Использование:**

```python
# worker_1.py
def run(self, stop_event, pause_event):
    self.process.router_manager.send({
        "channel": f"{self.process.name}_local",
        "target_worker": "worker_2",
        "command": "process_data",
        "data": {"result": 42},
    })

# worker_2.py
def on_message(msg):
    if msg.get("target_worker") == "worker_2":
        print(f"Получено: {msg['data']}")

self.process.router_manager.register_message_handler(on_message)
```

---

## Адаптеры

### WorkerAdapter

Предоставляет удобный интерфейс для использования WorkerManager из кода процесса.

```python
class WorkerAdapter(BaseAdapter):
    def setup(self) -> bool: ...
    
    def create_worker(self, name, target, config=None, auto_start=False):
        return self.manager.create_worker(name, target, config or ThreadConfig(), auto_start)
    
    def start_worker(self, name): ...
    def stop_worker(self, name, timeout=5.0): ...
    def get_status(self, name): ...
    def list_workers(self): ...
    def list_application_workers(self): ...
```

**Использование:**

```python
adapter = process.worker_adapter
adapter.create_worker("worker", my_func, config, auto_start=True)
```

### WorkerSchemaAdapter

Извлекает настройки потоков из SchemaBase конфигов (интеграция с data_schema_module).

```python
class WorkerSchemaAdapter:
    THREAD_FIELDS = {"priority", "restart_on_failure", "max_restarts", ...}
    
    def adapt(self, schema_class, **options) -> dict:
        """Извлечь ThreadConfig dict из класса схемы."""
        
    def adapt_instance(self, schema_instance, **options) -> dict:
        """Извлечь ThreadConfig dict из экземпляра схемы."""
```

---

## Потокобезопасность

### Стратегия Lock-based

WorkerRegistry использует `threading.Lock` для всех операций:

```python
class WorkerRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._workers: Dict[str, WorkerInfo] = {}
    
    def register(self, ...):
        with self._lock:
            self._workers[name] = worker_info
    
    def get(self, name):
        with self._lock:
            return self._workers.get(name)
```

### Race conditions

**Защищены:**
- Добавление/удаление воркеров
- Обновление статуса
- Чтение списка воркеров

**Не защищены (но OK):**
- `stop_event` и `pause_event` — это `threading.Event` (потокобезопасны по природе)
- `target` функция — только читается, не изменяется

---

## Мониторинг и метрики

### Метрики воркера

```python
metrics = manager.get_worker_metrics("worker_1")
# {
#     'status': 'running',
#     'uptime': 123.45,
#     'poll_interval': 0.1,
#     'last_error': None,
#     'has_been_started': True,
#     'last_run_duration': 0.0050,
#     'total_runtime': 120.30,
# }
```

### Общая статистика

```python
stats = manager.get_stats()
# {
#     'total_workers': 3,
#     'running': 2,
#     'stopped': 0,
#     'error': 1,
#     'total_runs': 150,
#     'total_failed_runs': 2,
#     'uptime': 1234.5,
# }
```

### Логирование

WorkerManager логирует через ObservableMixin:

```
[WorkerManager] Creating worker: worker_1
[WorkerManager] Starting worker: worker_1
[WorkerManager] Worker worker_1 started successfully
[WorkerManager] Worker worker_1 failed: division by zero
[WorkerManager] Restarting worker: worker_1 (attempt 1/3)
[WorkerManager] Shutting down all workers...
```

---

## Граничные условия и обработка ошибок

### Создание воркера дважды

```python
manager.create_worker("worker_1", func1, config1)
manager.create_worker("worker_1", func2, config2)  # ERROR!
# → False (воркер уже существует)
```

### Остановка несуществующего воркера

```python
manager.stop_worker("nonexistent")  # ERROR!
# → False (воркер не найден)
```

### Timeout при остановке

```python
def long_running(stop_event, pause_event):
    while not stop_event.is_set():
        time.sleep(10)  # Долгая операция

manager.create_worker("slow", long_running, config, auto_start=True)
manager.stop_worker("slow", timeout=1.0)  # Timeout истёк
# → False (timeout), но попытка остановки продолжается
```

### Исключение в воркере

```python
def buggy_worker(stop_event, pause_event):
    raise ValueError("Ошибка!")

config = ThreadConfig(restart_on_failure=True, max_restarts=1)
manager.create_worker("buggy", buggy_worker, config, auto_start=True)

# Статус → ERROR, последняя ошибка сохранена
status = manager.get_worker_status("buggy")
assert status['status'] == WorkerStatus.ERROR
assert "ValueError" in status['last_error']
```

---

## Производительность и оптимизация

### Poll Intervals

Приоритет влияет на интервал опроса `stop_event`:

```python
while not stop_event.is_set():  # Проверка каждые poll_interval сек
    # Работа
    time.sleep(poll_interval)
```

**Рекомендации:**
- **SYSTEM (0.001s)** — только для критичных потоков, высокий CPU
- **REALTIME (0.01s)** — требует низкой задержки
- **NORMAL (0.1s)** — стандартно
- **BATCH (1.0s)** — фоновые пакетные задачи
- **BACKGROUND (5.0s)** — редко используемое

### Метрики в памяти

Все метрики хранятся в WorkerInfo (в памяти):
- Нет I/O для получения метрик
- Линейный поиск при фильтрации по типу (max N воркеров < 100)

### Локальный канал queue.Queue vs mp.Queue

```
Внутри процесса: queue.Queue — O(1), быстро
Между процессами: mp.Queue — pickle/unpickle, медленнее
```

---

## Тестирование

### Unit тесты

```bash
pytest worker_module/tests/ -v
```

### Интеграционные тесты

```bash
pytest inspector_prototype/tests/test_process_module.py -v -k worker
```

### Нагрузочное тестирование

```python
# Создать 100 воркеров и начать их все одновременно
for i in range(100):
    manager.create_worker(f"worker_{i}", my_func, config, auto_start=True)

# Проверить статистику
stats = manager.get_stats()
assert stats['running'] == 100
assert stats['total_workers'] == 100
```

---

## Ссылки на код

- `core/worker_manager.py` — главная реализация
- `registry/worker_registry.py` — реестр с Lock
- `lifecycle/worker_lifecycle.py` — жизненный цикл
- `core/thread_config.py` — конфигурация
- `types/types.py` — все типы и перечисления
- `interfaces.py` — публичные контракты
- `adapters/` — адаптеры для использования из кода

---

## Архитектурные решения (ADR)

| ADR | Решение | Причина |
|-----|---------|---------|
| ADR-007 | WorkerRegistry использует Lock, а не RwLock | Простота, воркеры редко удаляются |
| ADR-008 | Dict at Boundary для ThreadConfig | Стандарт фреймворка |
| ADR-009 | poll_interval вместо native OS priority | Кроссплатформенность |
| ADR-010 | COMPLETED вместо STOPPED для TASK режима | Различение успешной/ошибочной разовой задачи |
| ADR-011 | Локальный канал на queue.Queue | Низкая задержка для внутри-процессного общения |
| ADR-012 | WorkerAdapter наследует BaseAdapter | Единообразие с другими адаптерами |

---

## Будущие улучшения

1. **Метрики в Prometheus** — экспорт метрик через prometheus_client
2. **Distributed tracing** — correlation_id в logs
3. **Worker dependencies** — запуск worker_2 только если worker_1 запущен
4. **Graceful drains** — остановка воркеров со скоростью drain_rate
5. **CPU pinning** — привязка потока к конкретному CPU ядру (Linux только)
