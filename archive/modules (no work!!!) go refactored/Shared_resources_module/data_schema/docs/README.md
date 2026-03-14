# Data Schema Module

Универсальная система работы с данными на основе **Pydantic v2**.

Этот модуль инкапсулирует всю логику для работы с дата-классами и схемами данных. Использует гибридный подход: dict в ProcessData, Pydantic модели в коде.

## Основные возможности

✅ **Схемы на основе Pydantic v2** - используйте все возможности Pydantic v2  
✅ **Валидация данных** - автоматическая валидация через Pydantic  
✅ **Конвертация форматов** - JSON, YAML, dict, Pydantic model  
✅ **Дефолтные значения** - автоматическое заполнение из схем  
✅ **Версионирование** - история изменений и откат к предыдущим версиям  
✅ **Реестр схем** - централизованное управление схемами  
✅ **Визуализация схем** - визуализация структуры схем в различных форматах (text, JSON, HTML, Mermaid)  
✅ **Генерация документации** - автоматическая генерация документации из схем (Markdown, RST, HTML)  
✅ **Расширяемость** - легко добавлять новые форматы через паттерн Strategy  
✅ **Производительность** - оптимизировано для работы с большими объемами данных  
✅ **Лаконичный API** - простой и понятный интерфейс  
✅ **53 unit теста** - все тесты проходят успешно ✅  

## Быстрый старт

### 1. Определите схему данных

```python
from pydantic import BaseModel, Field
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    BaseManagerModel,
    ComponentType
)

class LoggerManagerModel(BaseManagerModel):
    """Модель данных для LoggerManager."""
    
    log_level: str = Field(default="INFO", description="Уровень логирования")
    file_path: str = Field(default="logs/app.log", description="Путь к файлу")
    max_file_size: int = Field(default=10485760, description="Максимальный размер файла")
```

### 2. Зарегистрируйте схему

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaRegistry,
    register_schema
)

# Способ 1: Через декоратор
@register_schema("LoggerManager")
class LoggerManagerModel(BaseManagerModel):
    log_level: str = "INFO"

# Способ 2: Вручную
registry = SchemaRegistry.get_instance()
registry.register("LoggerManager", LoggerManagerModel)
```

### 3. Создайте экземпляр модели

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import ModelFactory

# Создание с данными
model = ModelFactory.create_manager(
    "LoggerManager",
    "main_logger",
    data={"log_level": "DEBUG"}
)

# Создание с дефолтными значениями
model = ModelFactory.create_manager("LoggerManager", "main_logger")
```

## Документация

- [USER_GUIDE.md](USER_GUIDE.md) - Полное руководство пользователя
- [STRUCTURE.md](STRUCTURE.md) - Описание структуры модуля
- [EVALUATION.md](EVALUATION.md) - Оценка модуля по сравнению с аналогами
- [TOOLS_GUIDE.md](TOOLS_GUIDE.md) - Руководство по инструментам (визуализация и генерация документации)
- [EXTENDING_GUIDE.md](EXTENDING_GUIDE.md) - Руководство по расширению модуля (добавление новых форматов)
- [SENIOR_REVIEW.md](SENIOR_REVIEW.md) - Оценка модуля от senior разработчика (8.85/10)
- [DNA_USAGE_EXAMPLES.md](DNA_USAGE_EXAMPLES.md) - Примеры работы с ДНК компонентов
- [examples/](examples/) - Примеры использования

## Архитектура

Модуль состоит из нескольких компонентов:

- **SchemaRegistry** - реестр и управление схемами (Pydantic моделями)
- **StorageManager** - менеджер хранения данных компонентов в ProcessData
- **ModelFactory** - фабрика для создания моделей с дефолтными значениями
- **ManagerDataAdapter** - адаптер для работы с данными менеджера
- **VersionManager** - версионирование конфигураций
- **DataConverter** - конвертация между форматами
- **DataValidator** - валидация данных по схемам
- **SchemaVisualizer** - визуализация схем в различных форматах
- **SchemaDocumentationGenerator** - автоматическая генерация документации
- **Utils** - вспомогательные функции для работы с данными

Все компоненты реализуют интерфейсы (ABC) для расширяемости и тестирования.

## Тесты

Модуль включает unit тесты в папке `tests/`. Для запуска:

```bash
pytest tests/
```

Подробнее см. [tests/README.md](../tests/README.md)

## Лицензия

Внутренний модуль проекта.
