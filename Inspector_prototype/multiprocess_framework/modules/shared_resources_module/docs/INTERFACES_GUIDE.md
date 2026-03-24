# Руководство по интерфейсам Shared Resources Module

## 🎯 Зачем нужны интерфейсы?

**Интерфейсы (ABC - Abstract Base Classes)** - это контракты, которые определяют **ЧТО** должен делать компонент, но не **КАК** он это делает.

### Преимущества подхода с интерфейсами:

1. **📖 Понятность API** - Сразу видно какие методы доступны и что они делают
2. **🧪 Легкое тестирование** - Можно создать моки для изоляции тестов
3. **🔧 Расширяемость** - Можно создать альтернативные реализации
4. **✅ Типобезопасность** - IDE и type checkers понимают структуру
5. **📚 Документация** - Интерфейсы служат живой документацией

## 📋 Список интерфейсов

Все интерфейсы определены в `core/interfaces.py`:

- `ISharedResourcesManager` - Главный менеджер ресурсов
- `IQueueRegistry` - Реестр очередей
- `IEventManager` - Менеджер событий
- `IMemoryManager` - Менеджер разделенной памяти
- `IProcessStateRegistry` - Реестр состояний процессов

---

## 🔷 ISharedResourcesManager

**Главный интерфейс менеджера общих ресурсов.**

### Реализация
`SharedResourcesManager` (в `core/shared_resources_manager.py`)

### Основные методы

```python
def get_process_data(process_name: str) -> Optional[ProcessData]:
    """Получить ProcessData процесса."""
    
def get_all_process_data() -> Dict[str, ProcessData]:
    """Получить все ProcessData."""
    
def register_process_state(
    process_name: str,
    initial_state: Optional[Dict[str, Any]] = None
) -> bool:
    """Зарегистрировать состояние процесса."""
```

### Свойства

```python
@property
def process_state_registry(self) -> IProcessStateRegistry:
    """Реестр состояний процессов."""
    
@property
def event_manager(self) -> IEventManager:
    """Менеджер событий."""
```

### Пример использования

```python
from multiprocess_framework.modules.shared_resources_module import (
    SharedResourcesManager,
    ISharedResourcesManager
)

# Создание с типизацией через интерфейс
manager: ISharedResourcesManager = SharedResourcesManager()
manager.initialize()

# Использование методов интерфейса
process_data = manager.get_process_data("MyProcess")
all_data = manager.get_all_process_data()

# Доступ к подкомпонентам через интерфейсы
registry: IProcessStateRegistry = manager.process_state_registry
event_mgr: IEventManager = manager.event_manager
```

### Что можно понять из интерфейса:

✅ Менеджер работает с процессами через `ProcessData`  
✅ Можно регистрировать процессы  
✅ Есть доступ к реестру процессов и менеджеру событий  
✅ Все методы возвращают типизированные результаты  

---

## 🔷 IQueueRegistry

**Интерфейс реестра очередей для межпроцессного взаимодействия.**

### Реализация
`QueueRegistry` (в `queues/core/manager.py`)

### Основные методы

```python
def create_queues(
    queue_config: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Queue]:
    """Создать очереди на основе конфигурации."""
    
def register_process_queues(
    process_name: str,
    queues: Dict[str, Queue]
) -> bool:
    """Зарегистрировать очереди процесса."""
    
def get_queue(
    process_name: str,
    queue_type: str
) -> Optional[Queue]:
    """Получить очередь процесса."""
    
def send_to_queue(
    process_name: str,
    queue_type: str,
    message: Any
) -> bool:
    """Отправить данные в очередь."""
```

### Пример использования

```python
from multiprocess_framework.modules.shared_resources_module import (
    QueueRegistry,
    IQueueRegistry
)

# Создание с типизацией
registry: IQueueRegistry = QueueRegistry(
    process_state_registry=shared_resources.process_state_registry
)
registry.initialize()

# Использование методов интерфейса
queue_config = {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50}
}

# Создание очередей
queues = registry.create_queues(queue_config)

# Регистрация
registry.register_process_queues("MyProcess", queues)

# Получение очереди
queue = registry.get_queue("MyProcess", "system")

# Отправка сообщения
registry.send_to_queue("MyProcess", "system", {"type": "test"})
```

### Что можно понять из интерфейса:

✅ Работает с процессами и типами очередей  
✅ Создает очереди из конфигурации  
✅ Регистрирует очереди для процессов  
✅ Отправляет сообщения в очереди  
✅ Все операции типизированы  

---

## 🔷 IEventManager

**Интерфейс менеджера событий для системы уведомлений.**

### Реализация
`EventManager` (в `events/core/manager.py`)

### Основные методы

```python
def emit_event(
    event_type: Any,
    process_name: Optional[str] = None,
    **kwargs
) -> bool:
    """Отправить событие."""
    
def subscribe(
    event_type: Any,
    callback: Callable
) -> bool:
    """Подписаться на события."""
    
def wait_for_event(
    event_type: Optional[Any] = None,
    timeout: float = 1.0
) -> Optional[Dict[str, Any]]:
    """Ожидать событие с таймаутом."""
```

### Пример использования

```python
from multiprocess_framework.modules.shared_resources_module import (
    EventManager,
    EventType,
    IEventManager
)

# Создание с типизацией
event_manager: IEventManager = shared_resources.event_manager

# Подписка на события
def handle_event(event_data: Dict[str, Any]):
    print(f"Event: {event_data}")

event_manager.subscribe(EventType.PROCESS_STATE_CHANGED, handle_event)

# Отправка события
event_manager.emit_event(
    EventType.PROCESS_STATE_CHANGED,
    process_name="MyProcess",
    status="running"
)

# Ожидание события
event_data = event_manager.wait_for_event(
    EventType.PROCESS_REGISTERED,
    timeout=5.0
)
```

### Что можно понять из интерфейса:

✅ Система событий с типами событий  
✅ Подписка на события через callbacks  
✅ Отправка событий с дополнительными данными  
✅ Ожидание событий с таймаутом  
✅ Асинхронная архитектура событий  

---

## 🔷 IMemoryManager

**Интерфейс менеджера разделенной памяти для больших данных.**

### Реализация
`MemoryManager` (в `memory/core/manager.py`)

### Основные методы

```python
def create_memory_dict(
    process_name: str,
    memory_names: Dict[str, tuple],
    coll: int
) -> bool:
    """Создать память для процесса."""
    
def write_images(
    process_name: str,
    memory_name: str,
    images: List[np.ndarray],
    index: int
) -> Optional[str]:
    """Записать изображения в память."""
    
def read_images(
    process_name: str,
    memory_name: str,
    index: int,
    n: int = -1
) -> Optional[List[np.ndarray]]:
    """Прочитать изображения из памяти."""
```

### Пример использования

```python
from multiprocess_framework.modules.shared_resources_module import (
    MemoryManager,
    IMemoryManager
)
import numpy as np

# Создание с типизацией
memory_manager: IMemoryManager = MemoryManager(
    process_state_registry=shared_resources.process_state_registry
)
memory_manager.initialize()

# Создание памяти
memory_config = {
    "camera_feed": (100, (480, 640, 3), np.uint8)
}

memory_manager.create_memory_dict("MyProcess", memory_config, coll=5)

# Запись изображений
images = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) for _ in range(10)]
shm_name = memory_manager.write_images("MyProcess", "camera_feed", images, index=0)

# Чтение изображений
read_images = memory_manager.read_images("MyProcess", "camera_feed", index=0, n=5)
```

### Что можно понять из интерфейса:

✅ Работает с разделенной памятью между процессами  
✅ Создает память для процессов с конфигурацией  
✅ Записывает и читает изображения (numpy arrays)  
✅ Поддерживает несколько блоков памяти (coll)  
✅ Оптимизирован для больших данных  

---

## 🔷 IProcessStateRegistry

**Интерфейс реестра состояний процессов (из Process_module).**

### Реализация
`ProcessStateRegistry` (в `state/process_state_registry.py`)

### Основные методы

```python
def register_process(
    process_name: str,
    initial_state: Optional[Dict[str, Any]] = None,
    config: Optional[Any] = None
) -> bool:
    """Зарегистрировать процесс."""
    
def get_process_data(process_name: str) -> Optional[ProcessData]:
    """Получить ProcessData процесса."""
    
def get_all_process_data() -> Dict[str, ProcessData]:
    """Получить все ProcessData."""
    
def update_state(
    process_name: str,
    status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    custom: Optional[Dict[str, Any]] = None
) -> bool:
    """Обновить состояние процесса."""
    
def add_queue(
    process_name: str,
    queue_type: str,
    queue: Queue
) -> bool:
    """Добавить очередь в процесс."""
    
def add_event(
    process_name: str,
    event_name: str,
    event: Event
) -> bool:
    """Добавить событие в процесс."""
```

### Пример использования

```python
from multiprocess_framework.modules.shared_resources_module import (
    IProcessStateRegistry
)

# Доступ через SharedResourcesManager
registry: IProcessStateRegistry = shared_resources.process_state_registry

# Регистрация процесса
registry.register_process("MyProcess", initial_state={"status": "ready"})

# Получение данных
process_data = registry.get_process_data("MyProcess")
all_data = registry.get_all_process_data()

# Обновление состояния
registry.update_state("MyProcess", status="running", metadata={"pid": 12345})

# Добавление очереди
from multiprocessing import Queue
queue = Queue()
registry.add_queue("MyProcess", "system", queue)
```

### Что можно понять из интерфейса:

✅ Централизованное управление состояниями процессов  
✅ Регистрация и обновление процессов  
✅ Хранение ProcessData для каждого процесса  
✅ Добавление очередей и событий к процессам  
✅ Единый источник истины для данных процессов  

---

## 🧪 Использование интерфейсов в тестах

### Создание моков

```python
from unittest.mock import Mock
from multiprocess_framework.modules.shared_resources_module import (
    IQueueRegistry,
    IEventManager
)

def test_with_mocks():
    # Создание мока через интерфейс
    mock_queue_registry = Mock(spec=IQueueRegistry)
    mock_queue_registry.get_queue.return_value = Mock()
    mock_queue_registry.send_to_queue.return_value = True
    
    # Использование мока
    queue = mock_queue_registry.get_queue("process", "system")
    assert queue is not None
    
    success = mock_queue_registry.send_to_queue("process", "system", {"data": "test"})
    assert success is True
```

### Проверка реализации

```python
from multiprocess_framework.modules.shared_resources_module import (
    QueueRegistry,
    IQueueRegistry
)

def test_implements_interface():
    registry = QueueRegistry(...)
    
    # Проверка что класс реализует интерфейс
    assert isinstance(registry, IQueueRegistry), \
        "QueueRegistry должен реализовывать IQueueRegistry"
```

---

## ✅ Правильность подхода

**ДА, подход с интерфейсами ПРАВИЛЬНЫЙ!**

### Почему это хорошо:

1. **📖 Самодокументируемость** - Интерфейсы показывают что делает модуль без чтения реализации
2. **🔍 Легко понять архитектуру** - Видно связи между компонентами
3. **🧪 Тестируемость** - Легко создавать моки и изолированные тесты
4. **🔧 Расширяемость** - Можно создать альтернативные реализации
5. **✅ Type safety** - IDE и type checkers помогают избежать ошибок
6. **📚 Документация** - Интерфейсы = живая документация API

### Пример понимания модуля через интерфейсы:

Прочитав интерфейсы, вы сразу понимаете:
- ✅ Модуль управляет процессами через `ISharedResourcesManager`
- ✅ Очереди создаются и управляются через `IQueueRegistry`
- ✅ События отправляются и обрабатываются через `IEventManager`
- ✅ Память создается и используется через `IMemoryManager`
- ✅ Все компоненты связаны через `IProcessStateRegistry`

**Это правильный подход к проектированию модулей!** 🎯

