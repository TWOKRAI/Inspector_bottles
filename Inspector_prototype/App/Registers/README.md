# Модуль регистров App Inspector

Модуль для управления регистрами приложения с использованием Pydantic 2.

## Структура

```
Registers/
├── __init__.py          # Экспорт всех компонентов
├── manager.py           # RegistersManager - менеджер всех регистров
├── converters.py        # RegistersConverter - конвертация в форматы
└── models/              # Модели регистров
    ├── __init__.py
    ├── camera.py
    ├── processing.py
    ├── post_processing.py
    ├── visual.py
    ├── draw.py
    ├── robot.py
    ├── conveyor.py
    ├── neuroun.py
    ├── hikvision.py
    └── frame_process.py
```

## Использование

### Базовое использование

```python
from App.Registers import ProcessingRegisters, RegistersManager

# Использование отдельной модели
registers = ProcessingRegisters()
registers.crop_top = 100

# Использование менеджера (все регистры в одном месте)
manager = RegistersManager()
manager.processing.crop_top = 100
manager.camera.source = 'image'
```

### Конвертация

```python
from App.Registers import RegistersManager, RegistersConverter

manager = RegistersManager()

# Экспорт в JSON
json_str = RegistersConverter.to_json(manager)

# Экспорт в YAML
yaml_str = RegistersConverter.to_yaml(manager)

# Экспорт в словарь
data_dict = RegistersConverter.to_dict(manager)

# Импорт из JSON
manager_loaded = RegistersConverter.from_json(json_str)

# Плоский словарь для рецептов
flat_dict = RegistersConverter.to_flat_dict(manager)
```

### Валидация

```python
# Валидация всех регистров
is_valid = RegistersConverter.validate_contracts(manager)

# Или через менеджер
is_valid = manager.validate_all()
```

## Обратная совместимость

Все модели экспортируются из `App.Registers` для обратной совместимости:

```python
# Старый способ (всё ещё работает)
from App.Registers import ProcessingRegisters

# Новый способ
from App.Registers import RegistersManager
```
