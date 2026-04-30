# Документация SharedResourcesModule

## Структура документации

- **ARCHITECTURE.md** - Архитектура модуля и принципы проектирования
- **USAGE_EXAMPLES.md** - Подробные примеры использования всех компонентов
- **INTERFACES_GUIDE.md** - Руководство по работе с интерфейсами модуля
- **EVALUATION.md** - Оценка модуля (8.2/10) и рекомендации по улучшению

## Быстрая навигация

- Хочу понять архитектуру → `ARCHITECTURE.md`
- Хочу увидеть примеры → `USAGE_EXAMPLES.md`
- Хочу понять интерфейсы → `INTERFACES_GUIDE.md`
- Хочу оценить модуль → `EVALUATION.md`

## Основные концепции

### SharedResourcesManager (Архив)

Легковесный контейнер для межпроцессного взаимодействия:
- Содержит ProcessStateRegistry и EventManager
- БЕЗ Manager() и Lock() для кросс-платформенной совместимости
- Передается в каждый процесс

### EventManager

Менеджер событий для межпроцессного взаимодействия:
- Интегрируется с RouterManager
- Данные хранятся в data_schema через ProcessData

### QueueRegistry

Реестр очередей для межпроцессного взаимодействия:
- Интегрируется с ProcessStateRegistry
- Данные хранятся в data_schema через ProcessData

### MemoryManager

Менеджер разделенной памяти:
- Инкапсулирует логику работы с multiprocessing.shared_memory
- Данные хранятся в ProcessData.custom через data_schema

### data_schema_module

Отдельный модуль (см. ARCHITECTURE.md «Связь с data_schema_module»):
- Схемы (RegisterBase), валидация, ProcessDataContainer
- shared_resources_module — runtime (ProcessData, Queue, Event, ConfigStore)
- DataSchemaAdapter — мост к StorageManager




