# Примеры использования Shared Resources Module

## Содержание

1. [Базовое использование](#базовое-использование)
2. [Работа с очередями](#работа-с-очередями)
3. [Работа с памятью](#работа-с-памятью)
4. [Работа с событиями](#работа-с-событиями)
5. [Интеграция с data_schema](#интеграция-с-data_schema)
6. [Полный пример](#полный-пример)

## Базовое использование

### Создание и инициализация

```python
from multiprocess_framework.modules.shared_resources_module import (
    SharedResourcesManager
)

# Создание менеджера
shared_resources = SharedResourcesManager(
    manager_name="MySharedResources",
    router_manager=None,  # Можно установить позже
    logger=None  # Можно установить позже
)

# Инициализация
if not shared_resources.initialize():
    print("Ошибка инициализации")
    exit(1)

# Регистрация процесса
shared_resources.register_process_state(
    "MyProcess",
    initial_state={
        "status": "ready",
        "pid": None,
        "metadata": {}
    }
)

# Получение ProcessData
process_data = shared_resources.get_process_data("MyProcess")
print(f"Process: {process_data.name}")

# Завершение
shared_resources.shutdown()
```

### Динамический доступ к процессам

```python
# Доступ через атрибуты
vision_process = shared_resources.VisionProcess
ai_process = shared_resources.AIProcess

# Работа с очередями через ProcessData
vision_process.queues.data.put({"image_id": 123})

# Работа с событиями
vision_process.events.start.set()
```

## Работа с очередями

### Создание и регистрация очередей

```python
from multiprocess_framework.modules.shared_resources_module import QueueRegistry

queue_registry = QueueRegistry(
    process_state_registry=shared_resources.process_state_registry
)
queue_registry.initialize()

# Конфигурация очередей
queue_config = {
    "system": {"maxsize": 100},   # Системные сообщения
    "data": {"maxsize": 50},      # Данные
    "images": {"maxsize": 10},    # Изображения
    "results": {"maxsize": 20}    # Результаты
}

# Создание и регистрация
queues = queue_registry.create_and_register_queues(
    "VisionProcess",
    queue_config
)

print(f"Создано очередей: {len(queues)}")
```

### Отправка и получение сообщений

```python
# Отправка сообщения
message = {
    "type": "image_processed",
    "image_id": 123,
    "timestamp": time.time(),
    "results": {"defects": 0}
}

success = queue_registry.send_to_queue(
    "AIProcess",
    "results",
    message
)

# Получение сообщения
message = queue_registry.receive_from_queue(
    "AIProcess",
    "results",
    timeout=1.0  # Ждать до 1 секунды
)

if message:
    print(f"Получено сообщение: {message}")
```

### Рассылка сообщений

```python
# Рассылка всем процессам
broadcast_message = {
    "type": "system_command",
    "command": "pause"
}

sent_count = queue_registry.broadcast_message(
    broadcast_message,
    queue_type="system",
    exclude_process="MainProcess"  # Исключить отправителя
)

print(f"Сообщение отправлено {sent_count} процессам")
```

### Очистка очередей

```python
# Очистка конкретной очереди (сохранить последние 5 элементов)
queue = queue_registry.get_queue("VisionProcess", "data")
queue_registry.clear_queue(queue, keep_elements=5)

# Очистка всех очередей
queue_registry.clear_all_queues()
```

## Работа с памятью

### Создание памяти для изображений

```python
import numpy as np
from multiprocess_framework.modules.shared_resources_module import MemoryManager

memory_manager = MemoryManager(
    process_state_registry=shared_resources.process_state_registry
)
memory_manager.initialize()

# Конфигурация памяти
memory_config = {
    "camera_feed": (
        100,              # Максимум изображений в блоке
        (480, 640, 3),    # Размер изображения (height, width, channels)
        np.uint8          # Тип данных
    ),
    "processed_images": (
        50,
        (480, 640, 3),
        np.uint8
    ),
    "sensor_data": (
        500,
        (100, 100, 1),
        np.float32
    )
}

# Создание памяти (5 блоков для каждого типа)
memory_manager.create_memory_dict(
    "VisionProcess",
    memory_config,
    coll=5  # Количество блоков памяти
)
```

### Запись изображений

```python
# Создание тестовых изображений
images = [
    np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    for _ in range(10)
]

# Поиск свободного индекса
free_idx = memory_manager.find_free_index("VisionProcess", "camera_feed")

if free_idx is not None:
    # Запись изображений
    shm_name = memory_manager.write_images(
        "VisionProcess",
        "camera_feed",
        images,
        index=free_idx
    )
    
    if shm_name:
        print(f"Изображения записаны в блок: {shm_name}")
else:
    print("Нет свободных блоков памяти")
```

### Чтение изображений

```python
# Чтение всех изображений
all_images = memory_manager.read_images(
    "VisionProcess",
    "camera_feed",
    index=free_idx
)

# Чтение первых 5 изображений
first_5_images = memory_manager.read_images(
    "VisionProcess",
    "camera_feed",
    index=free_idx,
    n=5
)

print(f"Прочитано изображений: {len(all_images)}")
```

### Освобождение памяти

```python
# Освобождение конкретного блока
memory_manager.release_memory(
    "VisionProcess",
    "camera_feed",
    index=free_idx
)

# Закрытие конкретной памяти
memory_manager.close_memory("VisionProcess", "camera_feed")

# Закрытие всей памяти процесса
memory_manager.close_all("VisionProcess")
```

## Работа с событиями

### Подписка на события

```python
from multiprocess_framework.modules.shared_resources_module import (
    EventManager,
    EventType
)

event_manager = shared_resources.event_manager

# Обработчик события
def handle_process_state_change(event_data):
    process_name = event_data.get("process_name")
    old_status = event_data.get("old_status")
    new_status = event_data.get("new_status")
    
    print(f"Process {process_name}: {old_status} -> {new_status}")

# Подписка
event_manager.subscribe(
    EventType.PROCESS_STATE_CHANGED,
    handle_process_state_change
)
```

### Отправка событий

```python
# Отправка события
event_manager.emit_event(
    EventType.PROCESS_STATE_CHANGED,
    process_name="VisionProcess",
    old_status="ready",
    new_status="running",
    timestamp=time.time()
)

# Отправка события регистрации процесса
event_manager.emit_event(
    EventType.PROCESS_REGISTERED,
    process_name="AIProcess",
    config={"model": "yolo_v8"}
)
```

### Ожидание событий

```python
# Ожидание конкретного события
event_data = event_manager.wait_for_event(
    EventType.PROCESS_REGISTERED,
    timeout=5.0  # Ждать до 5 секунд
)

if event_data:
    print(f"Процесс зарегистрирован: {event_data['process_name']}")
else:
    print("Событие не получено (таймаут)")

# Ожидание любого события
any_event = event_manager.wait_for_event(timeout=1.0)
```

## Интеграция с data_schema

```python
# Получение DataManager через адаптер
data_manager = shared_resources.get_data_manager()

if data_manager:
    # Использование data_schema для работы с данными компонентов
    # ...
    pass
else:
    print("data_schema модуль не доступен")
```

## Полный пример

```python
"""
Полный пример использования Shared Resources Module.
"""

import time
import numpy as np
from multiprocess_framework.modules.shared_resources_module import (
    SharedResourcesManager,
    QueueRegistry,
    MemoryManager,
    EventManager,
    EventType
)


def main():
    # 1. Создание менеджера общих ресурсов
    shared_resources = SharedResourcesManager()
    if not shared_resources.initialize():
        print("Ошибка инициализации SharedResourcesManager")
        return
    
    # 2. Регистрация процессов
    processes = ["VisionProcess", "AIProcess", "DBProcess"]
    for process_name in processes:
        shared_resources.register_process_state(
            process_name,
            initial_state={"status": "ready"}
        )
    
    # 3. Настройка очередей
    queue_registry = QueueRegistry(
        process_state_registry=shared_resources.process_state_registry
    )
    queue_registry.initialize()
    
    queue_config = {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50}
    }
    
    for process_name in processes:
        queue_registry.create_and_register_queues(process_name, queue_config)
    
    # 4. Настройка памяти
    memory_manager = MemoryManager(
        process_state_registry=shared_resources.process_state_registry
    )
    memory_manager.initialize()
    
    memory_config = {
        "camera_feed": (100, (480, 640, 3), np.uint8)
    }
    memory_manager.create_memory_dict("VisionProcess", memory_config, coll=5)
    
    # 5. Настройка событий
    def on_state_change(event_data):
        print(f"Event: {event_data['event_type']} - {event_data.get('process_name')}")
    
    shared_resources.event_manager.subscribe(
        EventType.PROCESS_STATE_CHANGED,
        on_state_change
    )
    
    # 6. Использование
    # Отправка сообщения
    queue_registry.send_to_queue(
        "AIProcess",
        "data",
        {"image_id": 123, "timestamp": time.time()}
    )
    
    # Запись изображений
    images = [
        np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        for _ in range(10)
    ]
    free_idx = memory_manager.find_free_index("VisionProcess", "camera_feed")
    if free_idx is not None:
        memory_manager.write_images("VisionProcess", "camera_feed", images, free_idx)
    
    # Отправка события
    shared_resources.event_manager.emit_event(
        EventType.PROCESS_STATE_CHANGED,
        process_name="VisionProcess",
        status="processing"
    )
    
    # 7. Завершение
    memory_manager.shutdown()
    queue_registry.shutdown()
    shared_resources.shutdown()
    print("Все менеджеры завершены")


if __name__ == "__main__":
    main()
```

