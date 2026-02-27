# Тесты для Router_module

## Структура тестов

```
Test_Router_module/
├── __init__.py
├── test_router_manager.py    # Тесты RouterManager
├── test_router_adapter.py    # Тесты RouterAdapter
├── test_channel.py           # Тесты каналов (MessageChannel, QueueChannel)
└── test_serialization.py     # Тесты сериализации для multiprocessing
```

## Запуск тестов

### Все тесты модуля

```bash
pytest tests/Test_Router_module/ -v
```

### Конкретный файл тестов

```bash
pytest tests/Test_Router_module/test_router_manager.py -v
pytest tests/Test_Router_module/test_router_adapter.py -v
pytest tests/Test_Router_module/test_channel.py -v
pytest tests/Test_Router_module/test_serialization.py -v
```

### Конкретный тест

```bash
pytest tests/Test_Router_module/test_router_manager.py::TestRouterCreation::test_create_router_basic -v
```

## Покрытие тестами

### RouterManager

- ✅ Создание и инициализация
- ✅ Управление каналами (регистрация, удаление)
- ✅ Отправка сообщений
- ✅ Получение сообщений
- ✅ Обработчики каналов и сообщений
- ✅ Асинхронное прослушивание
- ✅ Остановка прослушивания (`stop_listening`)
- ✅ Очистка ресурсов (`cleanup`)
- ✅ Статистика и мониторинг
- ✅ Интеграционные тесты

### RouterAdapter

- ✅ Инициализация адаптера
- ✅ Настройка (setup)
- ✅ Отправка сообщений
- ✅ Получение сообщений
- ✅ Отправка процессу через queue_registry
- ✅ Broadcast сообщений
- ✅ Статистика

### Каналы

- ✅ Базовый интерфейс MessageChannel
- ✅ QueueChannel: отправка и получение
- ✅ QueueChannel: асинхронное прослушивание
- ✅ Обработка ошибок
- ✅ Информация о канале

### Сериализация

- ✅ Базовая сериализация RouterManager
- ✅ Сериализация с диспетчерами
- ✅ Ограничения сериализации (Thread, Queue)
- ✅ Документация ограничений

## Особенности тестирования

### Использование Mock объектов

В тестах используются Mock объекты для:
- Логгера (`mock_logger`)
- QueueRegistry (`mock_queue_registry`)
- Каналов (`MockChannel`)

### Тестовый канал

Класс `MockChannel` реализует интерфейс `MessageChannel` для тестирования:
- Отправка сообщений
- Получение сообщений
- Отслеживание отправленных сообщений

### Асинхронное тестирование

Тесты для асинхронного прослушивания используют:
- `time.sleep()` для ожидания обработки
- Проверку статуса потоков
- Корректную остановку потоков после тестов

## Запуск с покрытием

```bash
pytest tests/Test_Router_module/ --cov=src.Modules.Router_module --cov-report=html
```

Отчет будет в `htmlcov/index.html`.

## Примечания

1. **Очистка ресурсов**: Все тесты, запускающие потоки, корректно их останавливают
2. **Изоляция тестов**: Каждый тест создает новый экземпляр RouterManager
3. **Моки**: Используются для изоляции тестов от внешних зависимостей

## Troubleshooting

### Проблема: Тесты зависают

- Проверьте, что потоки корректно останавливаются
- Убедитесь, что используется `stop_listening()` или `cleanup()`

### Проблема: Ошибки сериализации

- Это ожидаемо для объектов с Thread и Queue
- Тесты документируют эти ограничения







