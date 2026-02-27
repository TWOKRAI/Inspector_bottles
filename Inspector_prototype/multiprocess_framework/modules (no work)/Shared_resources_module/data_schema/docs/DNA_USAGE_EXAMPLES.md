# Примеры использования полной ДНК компонентов

## Концепция ДНК компонента

**ДНК компонента** - это полная информация, необходимая для его воссоздания:
- ✅ Путь к классу и модулю
- ✅ Ссылки на ресурсы (queues, events, shared memory)
- ✅ Иерархия компонентов
- ✅ Параметры создания
- ✅ Метаданные о расположении

---

## Пример 1: Создание ДНК из класса

```python
from data_schema import DNAFactory, ComponentDNA, ResourceType
from multiprocess_framework.modules.Logger_module.manager import LoggerManager

# Создаем ДНК компонента
dna = DNAFactory.create_dna_from_class(
    component_class=LoggerManager,
    component_name="main_logger",
    creation_params={
        "log_level": "DEBUG",
        "file_path": "logs/app.log"
    },
    resources={
        "input_queue": {
            "type": ResourceType.QUEUE,
            "id": "queue:logger:input",
            "name": "logger_input_queue",
            "metadata": {"maxsize": 100}
        },
        "control_event": {
            "type": ResourceType.EVENT,
            "id": "event:logger:control",
            "name": "logger_control_event"
        },
        "data_memory": {
            "type": ResourceType.SHARED_MEMORY,
            "id": "memory:logger:data",
            "name": "logger_data_memory",
            "metadata": {"size": 1024 * 1024}  # 1MB
        }
    },
    parent_id="VisionProcess",
    parent_type="PROCESS"
)

# Получаем полную информацию
full_info = dna.get_full_info()
print(full_info)
# {
#     "component": {...},
#     "location": {
#         "module_path": "multiprocess_framework.modules.Logger_module.manager",
#         "class_name": "LoggerManager",
#         "file_path": "/path/to/manager.py",
#         "full_class_path": "multiprocess_framework.modules.Logger_module.manager.LoggerManager"
#     },
#     "resources": {
#         "input_queue": {...},
#         "control_event": {...},
#         "data_memory": {...}
#     },
#     "hierarchy": {
#         "parent_id": "VisionProcess",
#         "parent_type": "PROCESS",
#         "children_ids": [],
#         "level": 1
#     },
#     ...
# }
```

---

## Пример 2: Сохранение ДНК в ProcessData

```python
from data_schema import ProcessDataContainer, DNAFactory, ResourceType
from multiprocess_framework.modules.Logger_module.manager import LoggerManager

# Получаем ProcessData
process_data = shared_resources.get_process_data("VisionProcess")

# Создаем контейнер
container = ProcessDataContainer(process_data)

# Создаем ДНК
dna = DNAFactory.create_dna_from_class(
    LoggerManager,
    "main_logger",
    resources={
        "input_queue": {
            "type": ResourceType.QUEUE,
            "id": "queue:logger:input",
            "name": "logger_input_queue"
        }
    }
)

# Регистрируем в ProcessData
container.register_dna(dna)

# Теперь ДНК доступна в ProcessData.custom['component_dnas']
```

---

## Пример 3: Воссоздание компонента по ДНК

```python
from data_schema import ProcessDataContainer, DNAFactory

# Получаем ProcessData
process_data = shared_resources.get_process_data("VisionProcess")
container = ProcessDataContainer(process_data)

# Получаем ДНК компонента
dna = container.get_dna("main_logger", "MANAGER")

# Воссоздаем компонент по ДНК
recreated_component = DNAFactory.recreate_from_dna(dna)

# Компонент полностью воссоздан со всеми параметрами!
print(recreated_component.log_level)  # "DEBUG"
```

---

## Пример 4: Клонирование компонента

```python
from data_schema import ProcessDataContainer

container = ProcessDataContainer(process_data)

# Клонируем компонент с изменениями
new_dna = container.clone_component(
    source_name="main_logger",
    new_name="backup_logger",
    source_type="MANAGER",
    creation_params={"log_level": "INFO"}  # Изменяем параметр
)

# Новый компонент создан на основе старого
print(new_dna.name)  # "backup_logger"
print(new_dna.creation_params["log_level"])  # "INFO"
```

---

## Пример 5: Построение дерева компонентов

```python
from data_schema import ProcessDataContainer

container = ProcessDataContainer(process_data)

# Получаем дерево компонентов
tree = container.get_component_tree(
    root_component_name="VisionProcess",
    root_component_type="PROCESS"
)

print(tree)
# {
#     "component": {
#         "id": "VisionProcess",
#         "type": "VisionProcess",
#         "name": "VisionProcess",
#         "status": "running"
#     },
#     "location": {...},
#     "children": [
#         {
#             "component": {
#                 "id": "main_logger",
#                 "type": "LoggerManager",
#                 ...
#             },
#             "children": [...]
#         },
#         ...
#     ]
# }
```

---

## Пример 6: Карта хранилища компонентов

```python
from data_schema import ProcessDataContainer

container = ProcessDataContainer(process_data)

# Получаем карту хранилища
storage_map = container.get_storage_map()

for component_id, info in storage_map.items():
    print(f"\nКомпонент: {component_id}")
    print(f"  Класс: {info['class_location']['full_path']}")
    print(f"  Файл: {info['class_location']['file']}")
    print(f"  В ProcessData: {info['storage_locations']['process_data']}")
    print(f"  Ресурсы:")
    for name, res_info in info['resources'].items():
        print(f"    {name}: {res_info['storage']}")
```

---

## Пример 7: Работа с ресурсами

```python
from data_schema import ComponentDNA, ResourceType

# Создаем ДНК
dna = ComponentDNA(...)

# Добавляем ресурсы
dna.add_resource(
    name="input_queue",
    resource_type=ResourceType.QUEUE,
    resource_id="queue:logger:input",
    resource_name="logger_input_queue",
    metadata={"maxsize": 100}
)

dna.add_resource(
    name="control_event",
    resource_type=ResourceType.EVENT,
    resource_id="event:logger:control",
    resource_name="logger_control_event"
)

dna.add_resource(
    name="data_memory",
    resource_type=ResourceType.SHARED_MEMORY,
    resource_id="memory:logger:data",
    resource_name="logger_data_memory",
    metadata={"size": 1024 * 1024}
)

# Получаем ссылку на ресурс
queue_ref = dna.get_resource("input_queue")
if queue_ref:
    print(f"Очередь: {queue_ref.resource_id}")
    print(f"Тип: {queue_ref.resource_type.value}")
    print(f"Хранилище: SharedResources.queues['{queue_ref.resource_id}']")
```

---

## Пример 8: Иерархия компонентов

```python
from data_schema import ComponentDNA, ComponentHierarchy

# Создаем родительский компонент
parent_dna = ComponentDNA(...)
parent_dna.name = "VisionProcess"
parent_dna.component_class = "VisionProcess"

# Создаем дочерний компонент
child_dna = ComponentDNA(...)
child_dna.name = "main_logger"
child_dna.component_class = "LoggerManager"

# Устанавливаем иерархию
child_dna.set_parent(
    parent_id="VisionProcess",
    parent_type="PROCESS"
)

parent_dna.add_child(
    child_id="main_logger",
    child_type="MANAGER"
)

# Теперь видна иерархия
print(f"Родитель: {child_dna.hierarchy.parent_id}")
print(f"Дети: {parent_dna.hierarchy.children_ids}")
print(f"Уровень: {child_dna.hierarchy.level}")
```

---

## Пример 9: Полная информация о компоненте

```python
from data_schema import DNAFactory

dna = DNAFactory.create_dna_from_class(...)

# Получаем полную информацию
full_info = dna.get_full_info()

# Информация включает:
# - Компонент (тип, класс, имя, статус)
# - Расположение (модуль, класс, файлы)
# - Ресурсы (queues, events, memory)
# - Иерархия (родители, дети)
# - Параметры создания
# - Метаданные
# - Временные метки

# Информация о хранилище
storage_info = DNAFactory.get_storage_info(dna)
print(storage_info)
# {
#     "component_id": "LoggerManager:main_logger",
#     "storage_locations": {
#         "schema_registry": "SchemaRegistry['LoggerManager']",
#         "process_data": "ProcessData.custom['component_managers']['LoggerManager']['main_logger']",
#         "file_path": "/path/to/manager.py",
#         ...
#     },
#     "class_location": {
#         "module": "multiprocess_framework.modules.Logger_module.manager",
#         "class": "LoggerManager",
#         "full_path": "...",
#         "file": "/path/to/manager.py"
#     },
#     "resources": {
#         "input_queue": {
#             "type": "queue",
#             "id": "queue:logger:input",
#             "storage": "SharedResources.queues['queue:logger:input']"
#         },
#         ...
#     }
# }
```

---

## Пример 10: ProcessData как контейнер ДНК

```python
from data_schema import ProcessDataContainer, DNAFactory

# ProcessData хранит множество ДНК компонентов
process_data = shared_resources.get_process_data("VisionProcess")
container = ProcessDataContainer(process_data)

# Регистрируем несколько компонентов
logger_dna = DNAFactory.create_dna_from_class(LoggerManager, "main_logger")
db_dna = DNAFactory.create_dna_from_class(DatabaseManager, "main_db")
vision_dna = DNAFactory.create_dna_from_class(VisionProcessor, "processor")

container.register_dna(logger_dna)
container.register_dna(db_dna)
container.register_dna(vision_dna)

# Получаем все ДНК
all_dnas = container.list_dnas()
print(f"Всего компонентов: {len(all_dnas)}")

# Получаем только менеджеры
managers = container.list_dnas(component_type="MANAGER")
print(f"Менеджеров: {len(managers)}")

# Получаем дерево системы
system_tree = container.get_component_tree("VisionProcess", "PROCESS")

# Получаем карту хранилища
storage_map = container.get_storage_map()
# Показывает где хранится каждый компонент:
# - В SchemaRegistry
# - В ProcessData
# - В файлах
# - Ресурсы в SharedResources
```

---

## Преимущества полной ДНК

1. **Полное воссоздание** - можно воссоздать компонент в любой момент
2. **Клонирование** - легко создавать похожие компоненты
3. **Отслеживание** - видно где что хранится
4. **Иерархия** - понимание структуры системы
5. **Ресурсы** - все ссылки на queues, events, memory в одном месте
6. **Метаданные** - дополнительная информация о компоненте

---

## ProcessData как контейнер ДНК

ProcessData хранит в себе множество ComponentDNA, образуя полную картину системы:

```
ProcessData.custom = {
    'component_dnas': {
        'MANAGER': {
            'main_logger': ComponentDNA(...),
            'main_db': ComponentDNA(...),
            ...
        },
        'PROCESS': {
            'VisionProcess': ComponentDNA(...),
            ...
        },
        ...
    },
    'component_managers': {...},  # Старый формат (для совместимости)
    ...
}
```

Каждая ComponentDNA содержит всю информацию для воссоздания компонента!

