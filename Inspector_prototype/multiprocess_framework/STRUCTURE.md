# Структура multiprocess_framework

## Общая структура

```
multiprocess_framework/
├── __init__.py              # Главный файл пакета (экспортирует все компоненты)
├── modules/                  # Все модули фреймворка
│   ├── Base_manager_module/
│   ├── Command_module/
│   ├── Config_module/
│   ├── Console_module/
│   ├── Dispatch_module/
│   ├── GUI_module/
│   ├── Logger_module/
│   ├── Message_module/
│   ├── Process_manager_module/
│   ├── Process_module/
│   ├── Router_module/
│   ├── Shared_resources_module/
│   └── Worker_module/
├── tests/                    # Unit тесты фреймворка
│   └── test_*_module/
├── examples/                 # Примеры использования
│   └── *.py
└── README.md                 # Полное описание фреймворка
```

## Принципы организации

### 1. Модули в `modules/`
- Все модули фреймворка находятся в одной папке `modules/`
- Это упрощает навигацию и понимание структуры
- Каждый модуль - отдельный пакет со своей ответственностью

### 2. Тесты в `tests/`
- Unit тесты для каждого модуля
- Тесты изолированы и тестируют только функциональность фреймворка
- Структура тестов повторяет структуру модулей

### 3. Примеры в `examples/`
- Примеры использования фреймворка
- Демонстрация различных паттернов и подходов
- Помогают понять, как использовать фреймворк

## Импорты

### Извне фреймворка (для пользователей):
```python
from multiprocess_framework import SystemLauncher, ProcessModule
from multiprocess_framework import ProcessConfig, process, worker
```

### Внутри фреймворка (между модулями):
```python
# Из Process_module в Config_module
from ..Config_module import ConfigManager

# Из Process_module в Worker_module
from ..Worker_module.worker_manager import WorkerManager
```

### Внутри модуля:
```python
# Из process_module.py в core.py (внутри Process_module)
from .core import ProcessCore
```

## Преимущества структуры

1. **Четкая организация**: модули отделены от тестов и примеров
2. **Простота навигации**: легко найти нужный модуль
3. **Масштабируемость**: легко добавлять новые модули
4. **Стандартность**: соответствует лучшим практикам Python

## Добавление нового модуля

1. Создайте папку в `modules/NewModule/`
2. Добавьте `__init__.py` с экспортами
3. Обновите `multiprocess_framework/__init__.py` для экспорта
4. Добавьте тесты в `tests/test_new_module/`
5. Обновите документацию

