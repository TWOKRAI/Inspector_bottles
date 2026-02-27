# Архитектура SharedResourcesModule (Refactored)

## Обзор

SharedResourcesModule - менеджер общих ресурсов для межпроцессного взаимодействия.

**Наследуется от:** BaseManager + ObservableMixin

## Архитектура

```
SharedResourcesManager (архив, BaseManager + ObservableMixin)
├── ProcessStateRegistry (из Process_module)
│   └── ProcessData (данные процессов через data_schema)
├── EventManager (BaseManager + ObservableMixin)
│   └── Интеграция с RouterManager
├── QueueRegistry (BaseManager + ObservableMixin)
│   └── Интеграция с ProcessStateRegistry
└── MemoryManager (BaseManager + ObservableMixin)
    └── Использует ProcessData.custom через data_schema
```

## Компоненты

### SharedResourcesManager (Архив)

Легковесный контейнер для межпроцессного взаимодействия:
- Содержит ProcessStateRegistry и EventManager
- БЕЗ Manager() и Lock() для кросс-платформенной совместимости
- Передается в каждый процесс
- Координирует работу всех компонентов

### ProcessStateRegistry

Реестр состояний процессов:
- Хранит ProcessData всех процессов
- Использует data_schema для работы с данными
- БЕЗ Manager() и Lock()

### EventManager

Менеджер событий:
- Интегрируется с RouterManager для распространения событий
- Данные хранятся в data_schema через ProcessData
- Поддержка подписок на события

### QueueRegistry

Реестр очередей:
- Управляет очередями процессов
- Интегрируется с ProcessStateRegistry
- Данные хранятся в data_schema через ProcessData

### MemoryManager

Менеджер разделенной памяти:
- Инкапсулирует логику работы с multiprocessing.shared_memory
- Данные хранятся в ProcessData.custom через data_schema
- Поддержка создания, записи и чтения блоков памяти

## Принципы

1. **БЕЗ Manager()**: БЕЗ multiprocessing.Manager() для кросс-платформенной совместимости
2. **Легковесность**: SharedResourcesManager - легковесный контейнер
3. **data_schema**: Единая точка работы с данными через data_schema
4. **Модульность**: Каждый компонент - отдельный модуль с четкой ответственностью

## Жизненный цикл

```python
# 1. Создание
shared_resources = SharedResourcesManager(router_manager=router_manager)

# 2. Инициализация
shared_resources.initialize()  # Инициализирует EventManager и ProcessStateRegistry

# 3. Использование
shared_resources.register_process_state("MyProcess")
process_data = shared_resources.get_process_data("MyProcess")

# 4. Завершение
shared_resources.shutdown()  # Завершает EventManager и очищает ресурсы
```

## Интеграция с data_schema

Все данные хранятся через data_schema:
- ProcessData использует data_schema для работы с данными
- ProcessConfiguration хранится в ProcessData через data_schema
- Кастомные данные хранятся в ProcessData.custom через data_schema

См. `DATA_SCHEMA.md` для деталей (после переноса data_schema).

## Преимущества новой архитектуры

- ✅ Единообразие со всеми менеджерами системы
- ✅ Автоматическое логирование через ObservableMixin
- ✅ Стандартный жизненный цикл (initialize/shutdown)
- ✅ Модульная структура
- ✅ Интеграция с ProcessStateRegistry и ProcessData
- ✅ Использование data_schema для работы с данными




