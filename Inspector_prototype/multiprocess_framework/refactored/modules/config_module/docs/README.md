# Документация ConfigModule

Добро пожаловать в документацию модуля управления конфигурациями!

## 📚 Содержание

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство пользователя с примерами
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

## 🚀 Быстрый старт

```python
from multiprocess_framework.refactored.modules.config_module import Config, ConfigManager

# Простое использование
config = Config()
config.set('database.host', 'localhost')
host = config.get('database.host')

# Использование ConfigManager
config_manager = ConfigManager()
config_manager.initialize()
app_config = config_manager.create_config(name='app', initial_data={'name': 'MyApp'})
```

## 📖 Основные концепции

### Config

Базовый класс для работы с конфигурацией. Поддерживает:
- Вложенные ключи через точку
- Загрузку/сохранение JSON/YAML файлов
- Валидацию через Pydantic схемы
- Работу с секциями
- Подписку на изменения

### ConfigManager

Менеджер для управления несколькими конфигурациями. Интегрирован с:
- BaseManager для единообразия
- SharedResourcesManager для межпроцессного хранения
- EventManager для синхронизации изменений

### ConfigSection

Представление части конфигурации как отдельного объекта.

## 🔗 Интеграция

Модуль интегрируется с:
- `data_schema_module` - для валидации и конвертации
- `shared_resources_module` - для хранения в ProcessData
- `base_manager` - для единообразия со всеми менеджерами

## 📝 Примеры использования

См. [USAGE_GUIDE.md](USAGE_GUIDE.md) для подробных примеров.

