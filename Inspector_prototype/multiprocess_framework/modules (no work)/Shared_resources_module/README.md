# Shared Resources Module

Модуль для управления общими ресурсами между процессами в многопроцессной архитектуре.

## 🚀 Быстрый старт

```python
from multiprocessing import Queue, Event
from src.Modules.Shared_resources_module import SharedResourcesManager, QueueManager

# 1. Создание библиотеки
shared_resources = SharedResourcesManager()

# 2. Регистрация процесса
shared_resources.register_process_state("process_1")

# 3. Создание очередей через QueueManager
queue_manager = QueueManager(process_state_registry=shared_resources.process_state_registry)
queue_manager.create_and_register_queues("process_1", {"data": {"maxsize": 100}})

# 4. Удобный доступ
shared_resources.process_1.queues.data.put("message")
message = shared_resources.process_1.queues.data.get()
```

## 📦 Основные компоненты

| Компонент | Назначение | Хранит данные? |
|-----------|------------|----------------|
| **SharedResourcesManager** | Библиотека для передачи между процессами | Только ссылки |
| **ProcessData** | Контейнер данных процесса | ✅ Да |
| **ProcessStateRegistry** | База данных ProcessData | ✅ Да |
| **QueueManager** | Методы для работы с очередями | ❌ Нет |
| **ImageMemoryManager** | Методы для работы с памятью | ❌ Нет |
| **ProcessConfiguration** | Методы для работы с конфигами | В ProcessData |

## 💡 Удобный интерфейс

```python
# Доступ к очередям
shared_resources.process_1.queues.data.put(item)
queue = shared_resources.process_1.queues.system

# Доступ к событиям
shared_resources.process_1.events.start.set()
event = shared_resources.process_1.events.stop

# Доступ к конфигурации
config_value = shared_resources.process_1.config.get_process_config("key")

# Доступ к памяти (через ImageMemoryManager)
memory_manager.write_images("process_1", "camera_feed", arrays, index)
```

## 📚 Документация

- **[Полная документация](../../docs/SHARED_RESOURCES_MODULE.md)** - Подробное руководство
- **[Анализ архитектуры](../../docs/SHARED_RESOURCES_ARCHITECTURE_ANALYSIS.md)** - Архитектурные решения
- **[Резюме рефакторинга](../../docs/SHARED_RESOURCES_REFACTORING_SUMMARY.md)** - История изменений

## 🧪 Тесты

```bash
# Все тесты модуля
pytest tests/Test_Shared_resources_module/ -v

# Конкретный компонент
pytest tests/Test_Shared_resources_module/test_image_memory_manager.py -v

# С покрытием
pytest tests/Test_Shared_resources_module/ --cov=src/Modules/Shared_resources_module
```

## 🎯 Ключевые особенности

- ✅ **Единый источник истины**: ProcessStateRegistry хранит все данные
- ✅ **Удобный интерфейс**: Доступ через атрибуты
- ✅ **Разделение ответственности**: Каждый класс отвечает за свою область
- ✅ **Сериализуемость**: Все объекты можно передавать между процессами
- ✅ **Без дублирования**: Данные хранятся в одном месте

## 📖 Примеры использования

### Работа с очередями

```python
queue_manager = QueueManager(process_state_registry=shared_resources.process_state_registry)
queue_config = {"data": {"maxsize": 100}, "system": {"maxsize": 50}}
queue_manager.create_and_register_queues("process_1", queue_config)

# Отправка сообщений
queue_manager.send_to_queue("process_1", "data", "message")
shared_resources.process_1.queues.data.put("message")
```

### Работа с памятью

```python
import numpy as np
memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)

# Создание памяти
memory_config = {"camera_feed": (100, (480, 640, 3), np.uint8)}
memory_manager.create_memory_dict("vision_process", memory_config, coll=5)

# Запись массивов
arrays = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) for _ in range(10)]
free_idx = memory_manager.find_free_index("vision_process", "camera_feed")
memory_manager.write_images("vision_process", "camera_feed", arrays, free_idx)

# Чтение массивов
read_arrays = memory_manager.read_images("vision_process", "camera_feed", free_idx)
```

## 🔗 Связанные модули

- `Process_module` - Использует SharedResourcesManager
- `Process_manager_module` - Создает и управляет SharedResourcesManager
- `Config_module` - Интегрируется с ProcessConfiguration

