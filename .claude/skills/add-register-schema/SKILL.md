Добавь новую схему регистров в пакет `multiprocess_prototype/registers/` согласно `SchemaBase`.

## Чек-лист добавления схемы регистров

### 1. Понять существующую структуру
Прочитай:
- `Inspector_prototype/multiprocess_prototype/registers/__init__.py` — как регистры экспортируются
- Один из существующих файлов схем в `registers/` — для паттерна

### 2. Создать файл схемы
**Путь:** `Inspector_prototype/multiprocess_prototype/registers/<schema_name>_schema.py`

```python
from multiprocess_framework.core.data_schema_module import SchemaBase
from pydantic import Field
from typing import Any

class <SchemaName>Schema(SchemaBase):
    """Описание назначения схемы."""

    field_name: type = Field(default=..., description="...")
    # ...

    class Config:
        # Pydantic v2 config если нужно
        pass
```

**Правила:**
- [ ] Наследуй от `SchemaBase` (не от `BaseModel` напрямую)
- [ ] Используй `Field(description=...)` для всех полей
- [ ] Только Pydantic v2 синтаксис (`model_validator`, не `validator`)
- [ ] На границу процессов — только `schema.model_dump()` (dict)

### 3. Зарегистрировать в `__init__.py`
```python
from .register_name_schema import <SchemaName>Schema
__all__ = [..., "<SchemaName>Schema"]
```

### 4. Использование в приложении
```python
# Внутри процесса
schema = <SchemaName>Schema(field_name=value)

# На границе (в сообщении)
msg = {"channel": "...", "payload": schema.model_dump(), "targets": [...]}

# Восстановление
schema = <SchemaName>Schema.model_validate(msg["payload"])
```

### 5. Тест
- [ ] Создать `registers/tests/test_<schema_name>_schema.py`
- [ ] Тест сериализации: `schema.model_dump()` → `model_validate()` round-trip
- [ ] Тест валидации невалидных данных

### 6. Документация
- [ ] Добавить строку в `registers/README.md` (если есть) с описанием схемы
