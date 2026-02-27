# Console Module

Лаконичный и мощный модуль для управления консольными окнами процессов.

## Особенности

✅ Простой и понятный API  
✅ Интеграция с ProcessManager  
✅ Поддержка группировки процессов  
✅ Создание отдельных каналов для специальных сообщений  
✅ Интеграция с RouterManager  
✅ Автоматическое перенаправление stdout/stderr  

## Быстрый старт

```python
from src.Modules.Console_module import ConsoleManager

# Создание менеджера
console_manager = ConsoleManager(logger=logger)

# Настройка и создание консоли для процесса
console_manager.configure_process_console("Worker1", enabled=True, group="workers")
console_manager.create_process_console("Worker1")
```

## Основной API

### 1. Настройка консоли для процесса

```python
console_manager.configure_process_console(
    process_name="ProcessName",
    enabled=True,           # Включить консоль (по умолчанию True)
    group="group_name",     # Группа (None = отдельная консоль)
    title="Custom Title"    # Заголовок (None = авто-генерация)
)
```

**Важно:** Если `group` не указан, каждый процесс получает отдельную консоль.

### 2. Создание отдельного канала

```python
# Создать отдельный канал для специальных сообщений
queue = console_manager.create_custom_channel(
    name="notifications",
    title="System Notifications"
)

# Отправка сообщения напрямую в queue
queue.put(('stdout', 'Новое уведомление!\n'), block=False)

# Или через роутер (после регистрации)
router.send({
    'channel': 'console.notifications',
    'text': 'Важное уведомление!',
    'level': 'WARNING'
})
```

### 3. Интеграция с Router

```python
# Регистрация всех каналов в роутере (один метод!)
channels = console_manager.register_in_router(
    router_manager=router,
    prefix="console"  # опционально, по умолчанию "console"
)

# Отправка через роутер
router.send({
    'channel': 'console.Worker1',  # В консоль процесса
    'text': 'Привет из роутера!',
    'level': 'INFO',
    'timestamp': True
})

router.send({
    'channel': 'console.group.workers',  # В группу
    'text': 'Сообщение для всех workers',
    'level': 'WARNING'
})

router.send({
    'channel': 'console.all',  # Во все консоли
    'text': 'Broadcast сообщение',
    'level': 'ERROR'
})
```

## Примеры использования

### Пример 1: Отдельные консоли для каждого процесса

```python
# Настройка
console_manager.configure_process_console("Worker1")
console_manager.configure_process_console("Worker2")

# Создание
console_manager.create_process_console("Worker1")
console_manager.create_process_console("Worker2")

# Результат: два отдельных окна консоли
```

### Пример 2: Групповая консоль

```python
# Настройка с одной группой
console_manager.configure_process_console("Worker1", group="workers")
console_manager.configure_process_console("Worker2", group="workers")
console_manager.configure_process_console("Worker3", group="workers")

# Создание (достаточно создать для одного, остальные подключатся)
console_manager.create_process_console("Worker1")

# Результат: одно окно консоли "Worker1 + Worker2 + Worker3"
```

### Пример 3: Кастомный канал для уведомлений

```python
# Создаем канал
notif_queue = console_manager.create_custom_channel(
    name="notifications",
    title="System Notifications"
)

# Регистрируем в роутере
console_manager.register_in_router(router_manager)

# Использование через роутер
router.send({
    'channel': 'console.notifications',
    'text': 'Новое событие произошло!',
    'level': 'INFO',
    'timestamp': True
})
```

### Пример 4: Интеграция с ProcessManager

```python
from src.Modules.Process_manager_module import ProcessManager

pm = ProcessManager()
pm.initialize_processes("processes.yaml")

# ConsoleManager уже создан и настроен!
# Консоли создаются автоматически на основе конфигурации

# Регистрируем каналы в роутере (если есть доступ к роутеру)
# pm.console_manager.register_in_router(router_manager)
```

## Доступные каналы после регистрации

После вызова `register_in_router()` создаются каналы:

1. **`console.{process_name}`** - канал для конкретного процесса
   - Пример: `console.Worker1`, `console.Alice`

2. **`console.group.{group_name}`** - канал для группы процессов
   - Пример: `console.group.workers`, `console.group.chat_group`

3. **`console.all`** - канал для всех консолей (broadcast)

4. **`console.{custom_name}`** - кастомные каналы
   - Пример: `console.notifications`, `console.debug`

## Формат сообщений для ConsoleChannel

```python
message = {
    'text': 'Текст сообщения',      # Обязательно
    'level': 'INFO',                # INFO|WARNING|ERROR|DEBUG (опционально)
    'timestamp': True,              # Добавить временную метку (опционально)
}
```

## Архитектура модуля

```
Console_module/
├── __init__.py              # Экспорт главных классов
├── console_manager.py       # Главный менеджер (ConsoleManager)
├── console_channel.py       # Канал для RouterManager
├── redirector.py            # Перенаправитель stdout/stderr
├── window_process.py        # Процесс окна консоли
└── README.md                # Документация
```

### Компоненты

- **ConsoleManager** - главный класс, простой API
- **ConsoleRedirector** - перенаправляет print/stdout в консоль
- **ConsoleWindowProcess** - отдельный процесс для каждого окна консоли
- **ConsoleChannel** - реализует MessageChannel для RouterManager

## Интеграция в существующую систему

Модуль полностью интегрирован в `ProcessManager`:

```python
pm = ProcessManager()
# ConsoleManager уже создан:
# - pm.console_manager.configure_process_console() - настройка из конфига
# - pm.console_manager.create_process_console() - создание при старте процесса
# - pm.console_manager.close_all() - закрытие при остановке
```

## Преимущества

1. **Лаконичность** - один класс для всего
2. **Мощность** - все функции в одном месте
3. **Простота** - понятный API без лишних абстракций
4. **Гибкость** - поддержка кастомных каналов
5. **Интеграция** - легко работает с Router и ProcessManager

