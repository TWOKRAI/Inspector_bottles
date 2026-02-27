# Коммуникация ProcessModule

## Архитектура коммуникации

Коммуникация между процессами, менеджерами и потоками происходит через **RouterManager**, который использует **Dispatch модуль** для интеллектуальной маршрутизации сообщений.

```
ProcessCommunication → RouterManager → Dispatcher → MessageChannel
```

### Компоненты

1. **ProcessCommunication** - высокоуровневый интерфейс для коммуникации процесса
2. **RouterManager** - менеджер маршрутизации с интегрированным Dispatcher
3. **Dispatcher** (из Dispatch модуля) - выбирает оптимальный канал для отправки
4. **MessageChannel** - отправляет сообщение через свой протокол (Queue, Logger, etc.)

## Как это работает

### 1. Отправка сообщения

```python
# ProcessCommunication.send() → RouterManager.send()
# RouterManager использует Dispatcher для выбора канала
# Dispatcher анализирует сообщение и выбирает оптимальный канал
# MessageChannel отправляет сообщение
```

### 2. Маршрутизация через Dispatch

RouterManager использует два диспетчера:
- **channel_dispatcher** - выбирает канал для отправки
- **message_dispatcher** - обрабатывает входящие сообщения

### 3. Типы каналов

- **QueueChannel** - межпроцессная коммуникация через очереди
- **LoggerChannel** - логирование через LoggerManager
- **SystemEventsChannel** - системные события

## Примеры использования

### Отправка сообщения процессу

```python
# ProcessCommunication автоматически использует RouterManager
# RouterManager использует Dispatch для выбора канала
result = process.communication.send_to_process(
    target="WorkerProcess",
    message={"type": "command", "command": "process_data"}
)
```

### Broadcast сообщения

```python
# RouterManager использует Dispatch для broadcast
count = process.communication.broadcast(
    message={"type": "event", "event": "system_started"},
    exclude_self=True
)
```

### Получение сообщений

```python
# RouterManager получает сообщения из всех каналов
# Dispatch обрабатывает входящие сообщения
messages = process.communication.receive(timeout=0.01)
```

## Интеграция с RouterManager

ProcessCommunication полностью интегрирован с RouterManager:

- Регистрация очередей в QueueRegistry
- Регистрация каналов в RouterManager
- Использование Dispatch для маршрутизации
- Обработка ошибок и статистика

## Важно

**Вся коммуникация идет через RouterManager**, который использует **Dispatch модуль** для интеллектуальной маршрутизации. Это обеспечивает:

- ✅ Гибкую маршрутизацию сообщений
- ✅ Оптимальный выбор канала
- ✅ Обработку различных типов сообщений
- ✅ Расширяемость через регистрацию новых обработчиков

