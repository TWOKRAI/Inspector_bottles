# Архитектура RouterModule (Refactored)

## Обзор

RouterModule - менеджер маршрутизации сообщений с интеллектуальным диспетчером.

**Наследуется от:** BaseManager + ObservableMixin

## Архитектура

```
RouterManager (BaseManager + ObservableMixin)
├── channel_dispatcher (Dispatcher) - выбор канала для отправки
├── message_dispatcher (Dispatcher) - обработка входящих сообщений
└── _channels (Dict[str, MessageChannel]) - реестр каналов
```

## Компоненты

### RouterManager

Основной менеджер маршрутизации:
- Наследуется от BaseManager + ObservableMixin
- Использует Dispatch модуль для маршрутизации
- Управляет каналами и диспетчерами
- Поддерживает асинхронное прослушивание

### MessageChannel

Базовый интерфейс для всех каналов:
- `send()` - отправка сообщения
- `poll()` - получение сообщений
- `start_listening()` / `stop_listening()` - асинхронное прослушивание

### QueueChannel

Канал для работы с очередями:
- Поддерживает queue.Queue и multiprocessing.Queue
- Асинхронное прослушивание через поток

### RouterAdapter

Адаптер для интеграции с процессами:
- Упрощенный интерфейс для работы с роутером
- Интеграция с queue_registry
- Broadcast сообщений

## Жизненный цикл

```python
# 1. Создание
router = RouterManager("my_router", process=process)

# 2. Инициализация
router.initialize()  # Инициализирует обработчики по умолчанию

# 3. Использование
router.register_channel(channel)
router.send(message)
messages = router.receive()

# 4. Завершение
router.shutdown()  # Останавливает прослушивание, очищает ресурсы
```

## Интеграция с Dispatch

RouterManager использует два диспетчера:
- **channel_dispatcher** - выбирает канал для отправки
- **message_dispatcher** - обрабатывает входящие сообщения

См. `DISPATCH_INTEGRATION.md` для деталей.

## Преимущества новой архитектуры

- ✅ Единообразие со всеми менеджерами системы
- ✅ Автоматическое логирование через ObservableMixin
- ✅ Стандартный жизненный цикл (initialize/shutdown)
- ✅ Расширяемость через адаптеры
- ✅ Интеграция с Dispatch модулем

