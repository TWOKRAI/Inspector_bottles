# Руководство по инструментам data_schema

## Обзор

Модуль `data_schema` включает два мощных инструмента для работы со схемами:
- **SchemaVisualizer** - визуализация структуры схем
- **SchemaDocumentationGenerator** - автоматическая генерация документации

---

## SchemaVisualizer

### Описание

Класс для визуализации структуры Pydantic схем в различных форматах.

### Использование

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaVisualizer,
    SchemaManager
)

# Создание визуализатора
visualizer = SchemaVisualizer()

# Визуализация одной схемы
text = visualizer.visualize_schema("LoggerManager", format="text")
print(text)

# Визуализация всех схем
all_text = visualizer.visualize_all_schemas(format="text")

# Сохранение в файл
from pathlib import Path
visualizer.save_visualization(
    "LoggerManager",
    Path("schema_visualization.html"),
    format="html"
)
```

### Поддерживаемые форматы

1. **text** - текстовый формат (по умолчанию)
2. **json** - JSON формат
3. **html** - HTML таблица
4. **mermaid** - Mermaid диаграмма классов

### Примеры

#### Текстовая визуализация

```python
visualizer = SchemaVisualizer()
text = visualizer.visualize_schema("LoggerManager")
print(text)
```

Вывод:
```
Схема: LoggerManager
================================================================================

Описание: Модель данных для LoggerManager

Поля:
--------------------------------------------------------------------------------
  log_level: str = INFO
    └─ Уровень логирования
  file_path: str = logs/app.log
    └─ Путь к файлу логов
  max_file_size: int = 10485760
    └─ Максимальный размер файла
```

#### HTML визуализация

```python
html = visualizer.visualize_schema("LoggerManager", format="html")
# Сохранить в файл
Path("schema.html").write_text(html)
```

#### Mermaid диаграмма

```python
mermaid = visualizer.visualize_schema("LoggerManager", format="mermaid")
print(mermaid)
```

Вывод:
```
classDiagram
    class LoggerManager {
        +log_level: str = INFO
        +file_path: str = logs/app.log
        +max_file_size: int = 10485760
    }
```

### Параметры

- `include_defaults` - включить дефолтные значения (по умолчанию True)
- `include_types` - включить типы полей (по умолчанию True)
- `include_descriptions` - включить описания полей (по умолчанию True)

---

## SchemaDocumentationGenerator

### Описание

Класс для автоматической генерации документации из зарегистрированных Pydantic схем.

### Использование

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaDocumentationGenerator
)
from pathlib import Path

# Создание генератора
generator = SchemaDocumentationGenerator()

# Генерация документации для одной схемы
docs = generator.generate_documentation(
    "LoggerManager",
    format="markdown",
    include_examples=True
)

# Генерация документации для всех схем
all_docs = generator.generate_documentation(format="markdown")

# Сохранение в файл
Path("schemas_docs.md").write_text(all_docs)

# Генерация API Reference
api_ref = generator.generate_api_reference(
    output_path=Path("API_REFERENCE.md"),
    format="markdown"
)
```

### Поддерживаемые форматы

1. **markdown** - Markdown формат (по умолчанию)
2. **rst** - reStructuredText формат
3. **html** - HTML формат

### Примеры

#### Markdown документация

```python
generator = SchemaDocumentationGenerator()
docs = generator.generate_documentation("LoggerManager", format="markdown")
print(docs)
```

Вывод:
```markdown
# LoggerManager

**Тип:** Схема данных (Pydantic Model)

## Описание
Модель данных для LoggerManager

## Поля

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|---------------|--------------|----------|
| `log_level` | `str` | ✅ | `INFO` | Уровень логирования |
| `file_path` | `str` | ✅ | `logs/app.log` | Путь к файлу логов |

## Пример использования

```python
from your_module import LoggerManager

# Создание экземпляра с дефолтными значениями
instance = LoggerManager()

# Создание экземпляра с данными
instance = LoggerManager(
    log_level=INFO,
    file_path=logs/app.log
)
```
```

#### API Reference для всех схем

```python
generator = SchemaDocumentationGenerator()
api_ref = generator.generate_api_reference(
    output_path=Path("API_REFERENCE.md"),
    format="markdown"
)
```

Создает полный API Reference со всеми зарегистрированными схемами.

### Параметры

- `include_examples` - включить примеры использования (по умолчанию True)
- `include_defaults` - включить дефолтные значения (по умолчанию True)

---

## Интеграция

### Использование в CI/CD

```python
# Генерация документации при сборке
from pathlib import Path
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaDocumentationGenerator
)

generator = SchemaDocumentationGenerator()
docs = generator.generate_api_reference(
    output_path=Path("docs/API_REFERENCE.md"),
    format="markdown"
)
```

### Использование в разработке

```python
# Быстрая визуализация схемы для отладки
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaVisualizer
)

visualizer = SchemaVisualizer()
print(visualizer.visualize_schema("MySchema", format="text"))
```

---

## Примеры использования

### Полный пример

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaManager,
    SchemaVisualizer,
    SchemaDocumentationGenerator,
    register_schema
)
from pydantic import BaseModel, Field
from pathlib import Path

# Определяем схему
@register_schema("AppConfig")
class AppConfig(BaseModel):
    """Конфигурация приложения."""
    
    host: str = Field(default="localhost", description="Хост сервера")
    port: int = Field(default=8080, description="Порт сервера")
    debug: bool = Field(default=False, description="Режим отладки")

# Визуализация
visualizer = SchemaVisualizer()
print(visualizer.visualize_schema("AppConfig", format="text"))

# Генерация документации
generator = SchemaDocumentationGenerator()
docs = generator.generate_documentation("AppConfig", format="markdown")
Path("AppConfig_docs.md").write_text(docs)

# Генерация API Reference для всех схем
api_ref = generator.generate_api_reference(
    output_path=Path("API_REFERENCE.md"),
    format="markdown"
)
```

---

## Заключение

Инструменты `SchemaVisualizer` и `SchemaDocumentationGenerator` значительно упрощают работу со схемами данных, автоматизируя визуализацию и генерацию документации.

