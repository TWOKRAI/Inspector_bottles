# Руководство по расширению модуля data_schema

## Обзор

Модуль `data_schema` спроектирован с учетом расширяемости. Вы можете легко добавлять новые форматы визуализации и генерации документации через паттерн Strategy.

---

## Расширение визуализации схем

### Создание кастомного форматера визуализации

Для добавления нового формата визуализации создайте класс, реализующий интерфейс `IVisualizationFormatter`:

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema.core.interfaces import (
    IVisualizationFormatter
)
from typing import Dict, Any

class MyCustomFormatter(IVisualizationFormatter):
    """Кастомный форматер визуализации."""
    
    @property
    def format_name(self) -> str:
        """Имя формата."""
        return "custom"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """
        Форматировать информацию о схеме.
        
        Args:
            schema_name: Имя схемы
            schema_info: Словарь с информацией о схеме:
                - name: имя класса схемы
                - fields: список полей с информацией (name, type, required, default, description)
                - docstring: описание схемы
        
        Returns:
            Отформатированная строка (или bytes для бинарных форматов)
        """
        # Ваша логика форматирования
        return f"Custom format for {schema_name}"
```

### Регистрация форматера

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaVisualizer
)

visualizer = SchemaVisualizer()
visualizer.register_formatter(MyCustomFormatter())

# Использование
result = visualizer.visualize_schema("MySchema", format="custom")
```

### Пример: Excel форматер

Полный пример Excel форматера находится в `tools/examples/excel_formatter.py`:

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaVisualizer
)
from multiprocess_framework.modules.Shared_resources_module.data_schema.tools.examples.excel_formatter import (
    ExcelVisualizationFormatter
)

visualizer = SchemaVisualizer()
visualizer.register_formatter(ExcelVisualizationFormatter())

# Сохранение в Excel
visualizer.save_visualization(
    "MySchema",
    Path("schema.xlsx"),
    format="excel"
)
```

**Требования:** `pip install openpyxl`

---

## Расширение генерации документации

### Создание кастомного форматера документации

Для добавления нового формата документации создайте класс, реализующий интерфейс `IDocumentationFormatter`:

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema.core.interfaces import (
    IDocumentationFormatter
)
from typing import Dict, Any, List

class MyCustomDocFormatter(IDocumentationFormatter):
    """Кастомный форматер документации."""
    
    @property
    def format_name(self) -> str:
        """Имя формата."""
        return "custom_doc"
    
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True
    ) -> str:
        """
        Форматировать документацию для одной схемы.
        
        Args:
            schema_name: Имя схемы
            schema_info: Словарь с информацией о схеме
            include_examples: Включить примеры использования
        
        Returns:
            Отформатированная документация
        """
        # Ваша логика форматирования
        return f"Custom docs for {schema_name}"
    
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]]
    ) -> str:
        """
        Форматировать API Reference для всех схем.
        
        Args:
            schemas: Список имен схем
            schema_infos: Словарь {schema_name: schema_info}
        
        Returns:
            Отформатированный API Reference
        """
        # Ваша логика форматирования
        return f"Custom API ref for {len(schemas)} schemas"
```

### Регистрация форматера

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaDocumentationGenerator
)

generator = SchemaDocumentationGenerator()
generator.register_formatter(MyCustomDocFormatter())

# Использование
docs = generator.generate_documentation("MySchema", format="custom_doc")
```

---

## Примеры расширения

### 1. Excel экспорт

См. `tools/examples/excel_formatter.py` для полного примера.

### 2. Экспорт в базу данных

Концептуальный пример в `tools/examples/excel_formatter.py` (класс `DatabaseVisualizationFormatter`).

Для реальной реализации:

```python
class DatabaseVisualizationFormatter(IVisualizationFormatter):
    def __init__(self, db_connection):
        self.db = db_connection
    
    @property
    def format_name(self) -> str:
        return "database"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        # Сохранение в БД
        self.db.execute(
            "INSERT INTO schemas (name, info) VALUES (?, ?)",
            (schema_name, json.dumps(schema_info))
        )
        return f"Saved to DB: {schema_name}"
```

### 3. CSV экспорт

```python
import csv
from io import StringIO

class CSVVisualizationFormatter(IVisualizationFormatter):
    @property
    def format_name(self) -> str:
        return "csv"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        output = StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(["Поле", "Тип", "Обязательное", "По умолчанию", "Описание"])
        
        # Данные
        for field in schema_info.get("fields", []):
            writer.writerow([
                field["name"],
                field.get("type", "Any"),
                "Да" if field.get("required", True) else "Нет",
                field.get("default", "-"),
                field.get("description", "-")
            ])
        
        return output.getvalue()
```

---

## Структура schema_info

При создании форматеров важно понимать структуру `schema_info`:

```python
schema_info = {
    "name": "ClassName",  # Имя класса схемы
    "fields": [  # Список полей
        {
            "name": "field_name",  # Имя поля
            "type": "str",  # Тип поля (строка)
            "required": True,  # Обязательное ли поле
            "default": "default_value",  # Дефолтное значение (если есть)
            "description": "Описание поля"  # Описание (если есть)
        },
        # ...
    ],
    "docstring": "Описание схемы"  # Docstring класса
}
```

---

## Лучшие практики

1. **Используйте интерфейсы**: Всегда реализуйте интерфейсы `IVisualizationFormatter` или `IDocumentationFormatter`
2. **Обработка ошибок**: Добавляйте проверки и понятные сообщения об ошибках
3. **Документация**: Документируйте ваш форматер с примерами использования
4. **Тестирование**: Напишите тесты для вашего форматера
5. **Зависимости**: Указывайте требуемые зависимости в docstring

---

## Интеграция с существующим кодом

После регистрации форматера он автоматически становится доступным через стандартный API:

```python
# Ваш код
visualizer.register_formatter(MyCustomFormatter())

# Использование через стандартный API
result = visualizer.visualize_schema("MySchema", format="custom")
visualizer.save_visualization("MySchema", Path("output.custom"), format="custom")
```

---

## Заключение

Модуль `data_schema` предоставляет мощный и гибкий механизм расширения через паттерн Strategy. Вы можете легко добавлять новые форматы без изменения основного кода модуля.

Для вопросов и примеров см.:
- `tools/examples/excel_formatter.py` - примеры расширения
- `core/interfaces.py` - интерфейсы для расширения
- `tools/formatters.py` - стандартные форматеры для референса

