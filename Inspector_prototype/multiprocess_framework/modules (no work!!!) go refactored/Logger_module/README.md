# Logger Module - Система логирования

Модуль предоставляет гибкую и производительную систему логирования с поддержкой:
- Множественных каналов записи (файл, консоль, HTTP)
- Батчинга для оптимизации производительности
- Контекстного логирования
- Фильтрации по областям и модулям
- Динамической конфигурации
- Совместимости с multiprocessing (без блокировок)

## Архитектура

Модуль состоит из следующих компонентов:

### Основные компоненты

- **LoggerManager** - главный менеджер системы логирования
- **LoggerAdapter** - адаптер для упрощенного доступа
- **BatchManager** - менеджер пачек для группировки логов
- **LogDispatcher** - диспетчер маршрутизации логов по каналам
- **Channels** - реализации каналов записи (FileChannel, ConsoleChannel, HttpChannel)

### Вспомогательные компоненты

- **Config** - конфигурация системы (LogConfig, ChannelConfig, ScopeConfig)
- **Decorators** - декораторы для автоматического логирования
- **Utils** - вспомогательные утилиты

## Быстрый старт

### Базовое использование

```python
from src.Modules.Logger_module import LoggerManager, LogConfig, LogLevel, LogScope

# Создаем конфигурацию
config = LogConfig()
config.app_name = "my_app"

# Добавляем канал
from src.Modules.Logger_module.config import ChannelConfig
config.channels['console'] = ChannelConfig(
    name='console',
    type='console',
    enabled=True
)

# Создаем менеджер
logger = LoggerManager(config=config)
logger.initialize()

# Логируем сообщения
logger.info("Приложение запущено")
logger.error("Произошла ошибка")
logger.debug("Отладочная информация")

# Завершаем работу
logger.shutdown()
```

### Использование адаптера

```python
from src.Modules.Logger_module import LoggerAdapter, LoggerManager, LogConfig

# Создаем менеджер
logger_manager = LoggerManager(config=LogConfig())
logger_manager.initialize()

# Создаем адаптер
adapter = LoggerAdapter(logger_manager)
adapter.setup()

# Используем упрощенный интерфейс
adapter.info("Информационное сообщение")
adapter.error("Ошибка")
adapter.debug("Отладка")
```

### Загрузка конфигурации из YAML

```python
from src.Modules.Logger_module import LogConfig, LoggerManager

# Загружаем конфигурацию
config = LogConfig.from_yaml("config/logging.yaml")

# Создаем менеджер
logger = LoggerManager(config=config)
logger.initialize()
```

## Конфигурация

### Структура конфигурации

```yaml
app_name: "my_app"
enable_batching: true
batch_size: 100
batch_interval: 1.0
default_level: INFO

channels:
  console:
    type: console
    enabled: true
    format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  
  file:
    type: file
    enabled: true
    file_path: "logs/app.log"
    max_size: 10485760  # 10MB
    backup_count: 5

scopes:
  system:
    enabled: true
    min_level: INFO
    channels: [console, file]
  
  business:
    enabled: true
    min_level: INFO
    channels: [file]
```

### Области логирования (Scopes)

- **SYSTEM** - Системные события (запуск, остановка)
- **BUSINESS** - Бизнес-логика (платежи, заказы)
- **PERFORMANCE** - Производительность (время выполнения)
- **AUDIT** - Аудит (действия пользователей)
- **SECURITY** - Безопасность (логины, доступы)
- **DEBUG** - Отладочная информация

### Уровни логирования (Levels)

- **DEBUG** - Отладочная информация
- **INFO** - Информационные сообщения
- **WARNING** - Предупреждения
- **ERROR** - Ошибки
- **CRITICAL** - Критические ошибки

## Каналы записи

### Консольный канал

```python
from src.Modules.Logger_module.config import ChannelConfig

console_channel = ChannelConfig(
    name='console',
    type='console',
    enabled=True,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
```

### Файловый канал

```python
file_channel = ChannelConfig(
    name='file',
    type='file',
    enabled=True,
    file_path='logs/app.log',
    max_size=10 * 1024 * 1024,  # 10MB
    backup_count=5
)
```

### HTTP канал

```python
http_channel = ChannelConfig(
    name='http',
    type='http',
    enabled=True,
    url='https://logs.example.com/api/v1/logs',
    headers={
        'Authorization': 'Bearer token',
        'Content-Type': 'application/json'
    }
)
```

## Батчинг

Батчинг позволяет группировать логи для улучшения производительности:

```python
config = LogConfig()
config.enable_batching = True
config.batch_size = 100  # Размер пачки
config.batch_interval = 1.0  # Интервал сброса в секундах

logger = LoggerManager(config=config)
```

### Приоритетный сброс

Ошибки (ERROR, CRITICAL) сбрасываются немедленно, независимо от размера пачки.

## Контекстное логирование

```python
# Добавляем контекст
logger.push_context(user_id=123, request_id="abc-123")

# Логируем с контекстом
logger.info("Обработка запроса")

# Убираем контекст
logger.pop_context()
```

### Использование контекстного менеджера

```python
from src.Modules.Logger_module.decorators import log_context

with log_context(user_id=123, request_id="abc-123"):
    logger.info("Обработка запроса")
    # Контекст автоматически удалится при выходе
```

## Декораторы

### log_call - Логирование вызовов функций

```python
from src.Modules.Logger_module.decorators import log_call
from src.Modules.Logger_module.config import LogScope, LogLevel

@log_call(scope=LogScope.BUSINESS, log_args=True, log_time=True)
def process_order(order_id: int, amount: float):
    return True
```

### log_performance - Логирование медленных функций

```python
from src.Modules.Logger_module.decorators import log_performance

@log_performance(threshold=1.0)  # Логировать если выполнение > 1 секунды
def heavy_operation():
    # Тяжелая операция
    pass
```

## Отдельные файлы для модулей

Можно настроить отдельные файлы логирования для каждого модуля:

```python
# Включаем отдельный файл для модуля
logger.enable_module_logging("command_manager", "logs/command_manager.log")

# Логируем в модуль
logger.info("Сообщение", module="command_manager")

# Выключаем
logger.disable_module_logging("command_manager")
```

## Динамическая конфигурация

Модуль поддерживает динамическое изменение конфигурации через ConfigManager:

```python
from src.Modules.Config_module import ConfigManager
from src.Modules.Logger_module import LoggerManager, LogConfig

config_manager = ConfigManager()
logger = LoggerManager(config=LogConfig(), config_manager=config_manager)

# Изменяем конфигурацию в реальном времени
# Получаем Config через ConfigManager
config = ConfigManager.get_instance('logging')
config.set("logging.scopes.system.enabled", False)
config.set("logging.channels.console.enabled", False)
```

## Интеграция с multiprocessing

Модуль полностью совместим с multiprocessing:

- ✅ Нет блокировок threading.RLock() - все убрано для совместимости
- ✅ Используется contextvars для контекста (совместимо с multiprocessing)
- ✅ Все структуры данных сериализуемы
- ✅ Батчинг работает без блокировок (проверка времени при добавлении)

### Использование в процессах

```python
from multiprocessing import Process
from src.Modules.Logger_module import LoggerManager, LogConfig

def worker_process():
    # Каждый процесс создает свой экземпляр логгера
    logger = LoggerManager(config=LogConfig())
    logger.initialize()
    
    logger.info("Процесс запущен")
    
    # Работа процесса
    logger.shutdown()

if __name__ == '__main__':
    process = Process(target=worker_process)
    process.start()
    process.join()
```

## Статистика

Получение статистики использования:

```python
stats = logger.get_stats()

print(f"Обработано сообщений: {stats['messages_processed']}")
print(f"Пропущено сообщений: {stats['messages_skipped']}")
print(f"Каналов: {stats['channels_count']}")
print(f"Батчинг включен: {stats['batching_enabled']}")
```

## Примеры использования

### Базовый пример

```python
from src.Modules.Logger_module import LoggerManager, LogConfig, LogLevel, LogScope
from src.Modules.Logger_module.config import ChannelConfig, ScopeConfig

# Создаем конфигурацию
config = LogConfig()
config.app_name = "my_app"

# Настраиваем каналы
config.channels['console'] = ChannelConfig(
    name='console',
    type='console',
    enabled=True
)

config.channels['file'] = ChannelConfig(
    name='file',
    type='file',
    enabled=True,
    file_path='logs/app.log'
)

# Настраиваем области
config.scopes[LogScope.SYSTEM] = ScopeConfig(
    scope=LogScope.SYSTEM,
    enabled=True,
    min_level=LogLevel.INFO,
    channels=['console', 'file']
)

# Создаем и инициализируем логгер
logger = LoggerManager(config=config)
logger.initialize()

# Используем
logger.info("Приложение запущено")
logger.error("Произошла ошибка")

# Завершаем
logger.shutdown()
```

### Пример с декораторами

```python
from src.Modules.Logger_module.decorators import log_call, log_performance
from src.Modules.Logger_module.config import LogScope, LogLevel

@log_call(scope=LogScope.BUSINESS, log_args=True, log_time=True)
def process_payment(user_id: int, amount: float):
    # Логирование вызова и результата происходит автоматически
    return True

@log_performance(threshold=0.5)
def slow_operation():
    import time
    time.sleep(1)
    return "result"
```

### Пример с контекстом

```python
from src.Modules.Logger_module.decorators import log_context

def handle_request(request_id: str, user_id: int):
    with log_context(request_id=request_id, user_id=user_id):
        logger.info("Начало обработки запроса")
        
        # Вся обработка
        process_request()
        
        logger.info("Запрос обработан")
```

## API Reference

### LoggerManager

Основной класс для управления логированием.

**Методы:**

- `log(scope, level, message, module, **extra)` - Основной метод логирования
- `info(message, module, **extra)` - Информационное сообщение
- `error(message, module, **extra)` - Ошибка
- `warning(message, module, **extra)` - Предупреждение
- `debug(message, module, **extra)` - Отладка
- `critical(message, module, **extra)` - Критическая ошибка
- `flush()` - Принудительный сброс буферов
- `get_stats()` - Получение статистики
- `push_context(**context_vars)` - Добавление контекста
- `pop_context()` - Удаление контекста
- `enable_module_logging(module_name, file_path)` - Включение отдельного файла для модуля
- `disable_module_logging(module_name)` - Выключение отдельного файла для модуля

### LoggerAdapter

Адаптер для упрощенного доступа к логгеру.

**Методы:**

- `info(message, context, **kwargs)` - Информационное сообщение
- `error(message, context, **kwargs)` - Ошибка
- `warning(message, context, **kwargs)` - Предупреждение
- `debug(message, context, **kwargs)` - Отладка
- `critical(message, context, **kwargs)` - Критическая ошибка
- `system(level, message, context, **kwargs)` - Системное логирование
- `business(level, message, context, **kwargs)` - Бизнес-логирование
- `performance(level, message, context, **kwargs)` - Логирование производительности
- `audit(level, message, context, **kwargs)` - Аудит
- `security(level, message, context, **kwargs)` - Безопасность

## Тестирование

Все компоненты модуля покрыты тестами:

- `test_logger_manager.py` - Тесты LoggerManager
- `test_logger_adapter.py` - Тесты LoggerAdapter
- `test_batcher.py` - Тесты BatchManager
- `test_config.py` - Тесты конфигурации
- `test_channels.py` - Тесты каналов
- `test_dispatcher.py` - Тесты диспетчера
- `test_decorators.py` - Тесты декораторов

Запуск тестов:

```bash
python -m pytest tests/Test_Logger_module/
```

## Совместимость с multiprocessing

Модуль полностью совместим с multiprocessing:

1. **Нет блокировок** - все `threading.RLock()` убраны
2. **Батчинг без таймеров** - используется проверка времени при добавлении сообщений
3. **Контекст через contextvars** - совместимо с multiprocessing
4. **Сериализуемые структуры** - все данные можно передавать между процессами

## Производительность

- Батчинг снижает нагрузку на I/O операции
- Кэширование решений о логировании ускоряет обработку
- Приоритетный сброс для ошибок обеспечивает быструю реакцию на критические события

## Лицензия

Внутренний модуль проекта.

