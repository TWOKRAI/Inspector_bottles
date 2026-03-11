# Error Module (Refactored)

Специализированный менеджер ошибок — наследник LoggerManager. Отдельный файл `errors.log`, уровень ERROR по умолчанию.

## Dict at boundary

ErrorManager принимает config как:
- **dict** — уже преобразованный конфиг (минимальная зависимость)
- **LogConfig** — напрямую из logger_module
- **объект с build()** — `(name, dict)` по контракту RegisterBase
- **None** — дефолтный конфиг

**core/error_manager.py** не импортирует data_schema_module — только logger_module.

## ErrorManagerConfig (RegisterBase)

По образцу process_1_config: data_schema_module как точка истины.

```python
from multiprocess_framework.refactored.modules.error_module import (
    ErrorManager,
    ErrorManagerConfig,
)

# Вариант 1: RegisterBase-конфиг
config = ErrorManagerConfig(
    error_file_path="var/log/errors.log",
    include_stacktrace=True,
)
em = ErrorManager(config=config)

# Вариант 2: dict (без data_schema)
em = ErrorManager(config={
    "app_name": "errors",
    "default_level": "ERROR",
    "channels": {"errors_file": {"type": "file", "file_path": "logs/errors.log"}},
})

# Вариант 3: дефолты
em = ErrorManager(config=None)
```

## log_exception()

```python
try:
    risky_operation()
except Exception as e:
    em.log_exception(e, message="Operation failed", module="my_module")
```

## Запуск тестов

```bash
python -m pytest multiprocess_framework/refactored/modules/error_module/tests/ -v
```
