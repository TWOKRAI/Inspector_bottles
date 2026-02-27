# LoggerModule - Модуль системы логирования (Refactored)

## Обзор

`LoggerModule` предоставляет гибкую и производительную систему логирования с поддержкой:
- Множественных каналов записи (файл, консоль, HTTP)
- Батчинга для оптимизации производительности
- Контекстного логирования
- Фильтрации по областям и модулям
- Динамической конфигурации
- Совместимости с multiprocessing (без блокировок)

## Структура модуля

```
logger_module/
├── core/
│   ├── logger_manager.py      # Главный менеджер логирования
│   ├── log_config.py          # Конфигурация логирования
│   └── log_dispatcher.py      # Диспетчер маршрутизации логов
├── channels/
│   └── log_channel.py         # Каналы записи (File, Console, Http)
├── batcher/
│   └── batch_manager.py       # Менеджер батчинга
├── adapters/
│   └── logger_adapter.py     # Адаптер для упрощенного доступа
├── interfaces.py              # Интерфейсы
├── docs/                      # Документация
└── tests/                     # Тесты
```

## Основные изменения при рефакторинге

### Интеграция с новыми модулями

1. **BaseManager и ObservableMixin**
   - LoggerManager теперь наследуется от нового BaseManager
   - Использует ObservableMixin для логирования и метрик

2. **Новый Dispatcher**
   - LogDispatcher использует новый Dispatcher из dispatch_module
   - Улучшенная маршрутизация логов по каналам

3. **RouterManager**
   - Интеграция с RouterManager для межпроцессного логирования
   - Вместо старого Message_module используется RouterManager

4. **ConfigManager**
   - Поддержка интеграции с новым ConfigManager
   - Динамическое управление конфигурацией

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.logger_module import (
    LoggerManager, LogConfig, LogLevel, LogScope, ChannelConfig
)

# Создаем конфигурацию
config = LogConfig()
config.app_name = "my_app"

# Добавляем канал
config.channels['console'] = ChannelConfig(
    name='console',
    type='console',
    enabled=True
)

# Создаем менеджер
logger = LoggerManager(
    manager_name="LoggerManager",
    config=config
)

# Инициализация
logger.initialize()

# Логируем сообщения
logger.info("Приложение запущено")
logger.error("Произошла ошибка")
logger.debug("Отладочная информация")

# Завершаем работу
logger.shutdown()
```

### С интеграцией RouterManager

```python
from multiprocess_framework.refactored.modules.router_module import RouterManager
from multiprocess_framework.refactored.modules.logger_module import LoggerManager

# Создаем роутер
router_manager = RouterManager("Router")
router_manager.initialize()

# Создаем логгер с интеграцией роутера
logger = LoggerManager(
    manager_name="LoggerManager",
    config=config,
    router_manager=router_manager,
    enable_router_routing=True
)

logger.initialize()

# Логи автоматически маршрутизируются через RouterManager
logger.info("Message via router")
```

## Компоненты

### LoggerManager

Главный менеджер логирования, наследуется от `BaseManager` и `ObservableMixin`.

**Основные методы:**
- `log(scope, level, message, module, **extra)` - основной метод логирования
- `debug/info/warning/error/critical(message, module, **extra)` - удобные методы
- `flush()` - принудительный сброс буферизованных логов
- `get_stats()` - получение статистики

### LogDispatcher

Диспетчер маршрутизации логов по каналам.

**Особенности:**
- Использует новый Dispatcher из dispatch_module
- Регистрация обработчиков для каналов
- Маршрутизация записей логов

### Каналы логирования

- **FileChannel** - запись в файл с ротацией
- **ConsoleChannel** - запись в консоль
- **HttpChannel** - отправка по HTTP

### BatchManager

Менеджер батчинга для оптимизации производительности.

**Особенности:**
- Группировка логов в пачки
- Приоритетный сброс для ошибок
- Сброс по размеру и времени

## Версия

2.0.0

