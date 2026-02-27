# Тесты для модуля Shared_resources_module

## Структура тестов

### test_shared_resources_manager.py
Тесты для `SharedResourcesManager`:
- Инициализация
- Добавление и получение общих ресурсов
- Регистрация процессов
- Динамический доступ к процессам через атрибуты
- Сериализация

### test_process_data.py
Тесты для `ProcessData` и прокси-классов:
- Инициализация ProcessData
- QueuesProxy и EventsProxy
- Удобный доступ через атрибуты
- Сериализация

### test_process_state_registry.py
Тесты для `ProcessStateRegistry`:
- Регистрация процессов
- Добавление очередей и событий
- Обновление состояния
- Получение данных процессов

### test_queue_manager.py
Тесты для `QueueManager` (новый класс):
- Инициализация с ProcessStateRegistry
- Создание и регистрация очередей
- Отправка сообщений
- Рассылка сообщений
- Очистка очередей

### test_image_memory_manager.py
Тесты для `ImageMemoryManager` с интеграцией ProcessData:
- Инициализация с ProcessStateRegistry
- Создание памяти и сохранение в ProcessData.custom
- Запись и чтение numpy массивов (вместо изображений)
- Работа с разными типами данных (uint8, float32)
- Обработка ошибок (неверный тип, размер)
- Освобождение памяти
- Работа с несколькими процессами

### test_integration.py
Тесты полной интеграции всех компонентов:
- Полный рабочий процесс с всеми компонентами
- Несколько процессов с памятью
- Совместное использование очередей и памяти
- Сериализация с ссылками на память

## Запуск тестов

```bash
# Все тесты модуля
pytest tests/Test_Shared_resources_module/

# Конкретный файл
pytest tests/Test_Shared_resources_module/test_image_memory_manager.py

# Конкретный тест
pytest tests/Test_Shared_resources_module/test_image_memory_manager.py::TestImageMemoryManager::test_write_and_read_arrays

# С подробным выводом
pytest tests/Test_Shared_resources_module/ -v

# С покрытием кода
pytest tests/Test_Shared_resources_module/ --cov=src/Modules/Shared_resources_module
```

## Особенности тестирования

### ImageMemoryManager
- Использует numpy массивы вместо изображений для тестирования
- Проверяет интеграцию с ProcessData.custom
- Тестирует работу с разными типами данных (uint8, float32)
- Проверяет обработку ошибок

### QueueManager
- Тестирует работу через ProcessStateRegistry (единственный источник истины)
- Проверяет отсутствие дублирования данных
- Тестирует все методы работы с очередями

### Интеграционные тесты
- Проверяют совместную работу всех компонентов
- Тестируют полный рабочий процесс
- Проверяют изоляцию данных между процессами

## Покрытие

Тесты покрывают:
- ✅ Все основные классы модуля
- ✅ Все публичные методы
- ✅ Обработку ошибок
- ✅ Интеграцию компонентов
- ✅ Сериализацию
- ✅ Работу с numpy массивами

