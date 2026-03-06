# Модуль регистров App Inspector

**Использование библиотеки фреймворка** `data_schema_module`: конфигурация пакетов и тонкий фасад. Вся логика discovery и регистрации схем, тесты, документация и примеры — в **multiprocess_framework/refactored/modules/data_schema_module**.

## Структура

```
Registers/
├── __init__.py              # Экспорт моделей, схем, RegistersManager
├── manager.py                # Тонкий фасад: пути к пакетам + вызовы фреймворка
├── README.md
├── tests/
│   └── test_registers.py     # Один smoke-тест: RegistersManager как использование фреймворка
└── models/
    ├── __init__.py           # Реэкспорт из field_registers
    ├── field_registers/      # Регистры *Registers и схема полей
    │   ├── data_schema/
    │   ├── draw.py, camera.py, processing.py, ...
    │   └── __init__.py
    └── field_data/           # Дата-модели *Data и единая схема полей
        ├── data_schema/
        ├── camera.py, region.py, chain.py
        └── __init__.py
```

## Использование

### RegistersManager (пакеты по умолчанию для этого приложения)

```python
from App.Registers import RegistersManager

manager = RegistersManager()
manager.processing.crop_top = 100
manager.camera.source = "image"
meta = manager.get_field_metadata("draw", "dp")
desc = manager.get_field_description("draw", "dp")
```

### Другой процесс: свои пакеты

```python
from App.Registers.manager import RegistersManager

manager = RegistersManager(
    registers_package="OtherProcess.Registers.models.registers",
    data_package="OtherProcess.Registers.models.data",
    translation_manager=my_translation_manager,
)
```

### Конвертация и дата-модели

См. основной README фреймворка и примеры:

- **Фреймворк:** `multiprocess_framework/refactored/modules/data_schema_module/README.md`
- **Discovery и пакеты:** `data_schema_module/docs/DISCOVERY_AND_PACKAGES.md`
- **Пример discovery по суффиксу:** `data_schema_module/docs/examples/03_registers_and_data_packages.py`
- **Оценка в баллах (фреймворк + Registers):** `data_schema_module/docs/EVALUATION_FRAMEWORK_AND_REGISTERS.md`

## Тесты

- **Здесь:** один smoke-тест — что `RegistersManager()` создаётся и отдаёт метаданные (проверка использования фреймворка).  
  Запуск: `pytest App/Registers/tests/ -v` (из корня `Inspector_prototype`).
- **В фреймворке:** полные тесты discovery, `register_package_schemas`, преобразования имён — в `data_schema_module/tests/test_register_discovery.py`. Запуск из каталога `refactored/modules`: `pytest data_schema_module/tests/ -v`.
