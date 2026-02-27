# Интеграция RouterModule с Dispatch модулем

## Обзор

RouterManager использует **Dispatch модуль** для интеллектуальной маршрутизации сообщений.

## Архитектура

```
RouterManager
├── channel_dispatcher (Dispatcher) - выбор канала для отправки
└── message_dispatcher (Dispatcher) - обработка входящих сообщений
```

## Как это работает

### 1. Отправка сообщения

```python
# RouterManager.send() → channel_dispatcher → MessageChannel.send()
router.send(message)
```

**Процесс:**
1. Определяется ключ для диспетчера (`_get_dispatch_key()`)
2. Dispatcher находит обработчик по ключу
3. Обработчик возвращает имя канала
4. Сообщение отправляется через выбранный канал

### 2. Получение сообщения

```python
# RouterManager.receive() → message_dispatcher → обработка сообщения
messages = router.receive()
```

**Процесс:**
1. Сообщения получаются из всех каналов (`_poll_all_channels()`)
2. Определяется ключ для диспетчера
3. Dispatcher обрабатывает сообщение через message_dispatcher
4. Результат обработки добавляется в сообщение

## Обработчики по умолчанию

### channel_dispatcher

- **log_message** - для логических сообщений → `log_channel`
- **broadcast_message** - для широковещательных сообщений → `internal_queue`
- **default_queue** - по умолчанию → `internal_queue`

### Регистрация кастомных обработчиков

```python
def custom_channel_selector(message):
    if message.get('urgent'):
        return {'channel': 'priority_queue'}
    return {'channel': 'internal_queue'}

router.register_channel_handler('urgent_message', custom_channel_selector)
```

## Определение ключа диспетчера

Приоритет определения ключа:
1. Поле `command` для командных сообщений
2. Поле `type` для типизированных сообщений
3. Автоматическое определение по содержимому
4. По умолчанию: `default_queue`

## Примеры

### Отправка командного сообщения

```python
message = {
    'type': 'command',
    'command': 'process_data',
    'data': {'file': 'test.txt'}
}

# Dispatcher определит ключ 'process_data' и найдет обработчик
result = router.send(message)
```

### Отправка логического сообщения

```python
message = {
    'type': 'log',
    'level': 'info',
    'message': 'Processing started'
}

# Dispatcher определит ключ 'log_message' и выберет log_channel
result = router.send(message)
```

## Преимущества

- ✅ Интеллектуальная маршрутизация сообщений
- ✅ Оптимальный выбор канала
- ✅ Расширяемость через регистрацию обработчиков
- ✅ Гибкость стратегий диспетчеризации

