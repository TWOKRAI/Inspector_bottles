# RouterModule (Refactored)

Менеджер маршрутизации сообщений с интеллектуальным диспетчером.

## Архитектура

RouterModule наследуется от **BaseManager** и использует **ObservableMixin** для единообразия со всеми менеджерами системы.

### Компоненты

- **RouterManager** - основной менеджер маршрутизации (BaseManager + ObservableMixin)
- **MessageChannel** - базовый интерфейс для каналов
- **QueueChannel** - канал для работы с очередями
- **RouterAdapter** - адаптер для интеграции с процессами

### Интеграция с Dispatch

RouterManager использует **Dispatch модуль** для интеллектуальной маршрутизации:

```
RouterManager → Dispatcher → MessageChannel
```

- **channel_dispatcher** - выбирает канал для отправки
- **message_dispatcher** - обрабатывает входящие сообщения

## Использование

### Базовое использование

```python
from multiprocess_framework.refactored.modules.router_module import RouterManager, QueueChannel

# Создание роутера
router = RouterManager(
    manager_name="my_router",
    process=process,  # опционально
    queue_registry=queue_registry,  # опционально
    logger=logger  # опционально, используется через ObservableMixin
)

# Инициализация
router.initialize()

# Регистрация канала
channel = QueueChannel("internal_queue", queue)
router.register_channel(channel)

# Отправка сообщения
result = router.send({
    'type': 'command',
    'command': 'process',
    'data': {'file': 'test.txt'}
})

# Получение сообщений
messages = router.receive(timeout=0.1)

# Завершение
router.shutdown()
```

### Использование с ObservableMixin

```python
# Логирование через ObservableMixin
router.log_info("Router started")  # Автоматический прокси-метод

# Статистика через BaseManager
stats = router.get_stats()
```

## Преимущества новой архитектуры

- ✅ Единообразие со всеми менеджерами системы
- ✅ Автоматическое логирование через ObservableMixin
- ✅ Стандартный жизненный цикл (initialize/shutdown)
- ✅ Расширяемость через адаптеры
- ✅ Интеграция с Dispatch модулем для маршрутизации

## Документация

См. `docs/` для детальной документации:
- `docs/USAGE_GUIDE.md` - подробное руководство по использованию с примерами
- `docs/ARCHITECTURE.md` - архитектура модуля
- `docs/DISPATCH_INTEGRATION.md` - интеграция с Dispatch модулем

## Интерфейсы

Модуль предоставляет интерфейсы для расширяемости:
- `IRouterManager` - интерфейс для менеджера маршрутизации
- `IMessageChannel` - интерфейс для каналов сообщений

## Тесты

Тесты находятся в `tests/`:
- `test_router_manager.py` - тесты для RouterManager
- `test_channels.py` - тесты для каналов

Запуск тестов:
```bash
python -m pytest tests/ -v
```

