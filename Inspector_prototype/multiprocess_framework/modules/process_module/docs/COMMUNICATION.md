# Inter-Process Communication (IPC) в ProcessModule

## Обзор

ProcessModule использует **RouterManager** для безопасной и асинхронной коммуникации между процессами. Вся коммуникация проходит через очереди (multiprocessing.Queue) и интегрируется с системой маршрутизации.

## Методы коммуникации

### send_message(target, message) → bool
Отправить сообщение конкретному процессу или модулю.

```python
process.send_message(
    target="process_2",
    message={
        "command": "execute",
        "data": {"task": "compute", "value": 42},
    }
)
```

### broadcast_message(message, exclude_self=True) → bool
Отправить сообщение всем процессам.

```python
process.broadcast_message({
    "event": "status_changed",
    "status": "running",
})
```

### receive_message(timeout=None) → Dict | None
Получить одно сообщение из входящей очереди.

```python
msg = process.receive_message(timeout=1.0)
if msg:
    print(f"Получено: {msg}")
else:
    print("Timeout или очередь пуста")
```

## Архитектура

```
ProcessModule
    ├── send_message(target, msg)
    │       ↓
    ├── RouterManager (send)
    │       ↓
    ├── QueueRegistry (find queue by target)
    │       ↓
    └── multiprocessing.Queue (put message)

ProcessModule
    ├── receive_message(timeout)
    │       ↓
    ├── RouterManager (receive)
    │       ↓
    ├── Input Queue
    │       ↓
    └── Returns Dict or None
```

## Типы сообщений

Все сообщения передаются как обычные `dict` (Dict at Boundary):

```python
{
    "target_process": "process_2",      # Целевой процесс (опционально)
    "command": "execute",                # Команда для обработки
    "data": {...},                       # Данные (зависит от команды)
    "correlation_id": "uuid",            # ID для request-response (опционально)
}
```

## Примеры использования

### Пример 1: Producer-Consumer между двумя процессами

```python
class Producer(ProcessModule):
    def run(self):
        for i in range(10):
            self.send_message(
                target="consumer",
                message={"data": i}
            )
            time.sleep(1)

class Consumer(ProcessModule):
    def run(self):
        while not self.should_stop():
            msg = self.receive_message(timeout=2.0)
            if msg:
                self.log_info(f"Получено: {msg.get('data')}")
```

### Пример 2: Broadcast события

```python
# Process 1 - отправляет событие
class EventProducer(ProcessModule):
    def run(self):
        self.broadcast_message({
            "event": "system_ready",
            "timestamp": time.time(),
        })

# Process 2, 3, etc - получают событие
class EventConsumer(ProcessModule):
    def run(self):
        while not self.should_stop():
            msg = self.receive_message(timeout=1.0)
            if msg and msg.get("event") == "system_ready":
                self.log_info("Система готова!")
```

## Потокобезопасность

Все методы коммуникации **потокобезопасны**:
- RouterManager использует thread-safe очереди
- Все операции синхронизированы
- Можно вызывать из разных потоков безопасно

```python
# Безопасно из разных потоков
def worker_thread():
    process.send_message("other_process", {"data": "test"})

thread = threading.Thread(target=worker_thread)
thread.start()
```

## Обработка ошибок

```python
# Отправка может вернуть False если ошибка
success = process.send_message("target", {"data": "test"})
if not success:
    process.log_error("Не удалось отправить сообщение")

# Получение вернет None если timeout
msg = process.receive_message(timeout=1.0)
if msg is None:
    process.log_info("Timeout - нет сообщений")
```

## Производительность

- **send_message**: O(1) - прямая постановка в очередь
- **broadcast_message**: O(n) - где n = количество процессов
- **receive_message**: O(1) - получение из очереди (с timeout)
- **Throughput**: ~10,000 сообщений/сек (зависит от системы)

## Интеграция с worker_module

Воркеры внутри процесса также могут отправлять сообщения:

```python
def worker_func(stop_event, pause_event):
    while not stop_event.is_set():
        # Отправить сообщение из воркера
        process.send_message("other_process", {
            "worker": "worker_1",
            "data": {"result": 42},
        })

manager.create_worker("worker_1", worker_func, config, auto_start=True)
```

