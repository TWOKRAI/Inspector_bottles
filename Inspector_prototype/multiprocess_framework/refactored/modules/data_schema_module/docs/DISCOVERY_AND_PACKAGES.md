# Discovery и регистрация по пакетам (Registers / Data)

Универсальный механизм: один и тот же API для обнаружения и регистрации классов с любым суффиксом (*Registers, *Data и т.д.). Приложение только указывает пакет и суффикс; вся логика — в модуле.

## Было → Стало (идея рефакторинга)

| Было | Стало |
|------|--------|
| Отдельная функция discovery в приложении + захардкоженный список классов при пустом результате | `discover_registers_from_package(package_name, suffix="Registers")` — универсально; суффикс задаётся параметром |
| Отдельная функция регистрации дата-моделей с явным перечислением (CameraData, RegionData, …) | `register_package_schemas(package_name, suffix="Data")` — discovery по суффиксу + регистрация в SchemaManager |
| Толстый менеджер в приложении с дублированием логики | Тонкий фасад: два пакета (registers_package, data_package) + вызовы фреймворка |

Итог: тесты, документация и примеры по discovery/регистрации живут в **data_schema_module**; приложение (например App.Registers) — лишь **использование библиотеки** (импорт, константы пакетов, тонкий RegistersManager).

## API

- **`discover_registers_from_package(package_name, suffix="Registers")`**  
  Импортирует пакет, находит все классы `BaseModel` с именем, оканчивающимся на `suffix`, возвращает `{key: class}`. Ключ — snake_case от префикса имени (DrawRegisters → draw, CameraData → camera).

- **`register_package_schemas(package_name, schema_registry=None, suffix="Registers")`**  
  Вызывает discovery по `suffix` и регистрирует каждый класс в `SchemaManager`. Подходит и для регистров, и для дата-моделей.

- **`register_package_registers`** — алиас `register_package_schemas` для обратной совместимости.

## Пример использования (в приложении)

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    RegistersContainer,
    discover_registers_from_package,
    register_package_schemas,
)

# Контейнер регистров из пакета *Registers
register_map = discover_registers_from_package("MyApp.Registers.models.registers", suffix="Registers")
container = RegistersContainer(register_map)

# Регистрация дата-моделей в SchemaManager (для валидации рецептов и т.д.)
register_package_schemas("MyApp.Registers.models.data", suffix="Data")
```

См. также [examples/03_registers_and_data_packages.py](examples/03_registers_and_data_packages.py).
