# План реализации: Dict at Boundary

**Цель:** Все модули фреймворка принимают только dict. Конвертация из RegisterBase выполняется в app-слое. data_schema_module — источник истины, без зависимостей в модулях.

---

## Текущее состояние

- `SystemLauncher` импортирует `RegisterBase`, принимает `Union[ProcessBuilder, RegisterBase, dict]`
- `ProcessBuilder` требует `RegisterBase` в типах
- `main.py`: `launcher.add_process(Process1Config(), workers=[Worker1Config()])`
- `ErrorManager` уже принимает dict (и build()) — ок

---

## Важно: Breaking Change

Это breaking change. API `add_process(config, workers=[])` заменяется на `add_process(name, proc_dict)`. Все вызовы в app нужно обновить.

---

## Шаг 1: Хелпер в data_schema_module

**Файл:** `multiprocess_framework/refactored/modules/data_schema_module/utils/config_converters.py` (новый)

```python
"""Конвертеры config → dict для передачи в модули."""

from typing import Any, List, Tuple

def config_to_dict(config: Any) -> Tuple[str, dict]:
    """
    Конвертировать конфиг в (name, dict).
    config должен иметь build() -> (name, dict).
    """
    if hasattr(config, "build") and callable(config.build):
        return config.build()
    raise TypeError(f"config must have build() -> (name, dict), got {type(config)}")

def configs_to_dicts(*configs: Any) -> List[Tuple[str, dict]]:
    """Конвертировать несколько конфигов в список (name, dict)."""
    return [config_to_dict(c) for c in configs]

def build_process_with_workers(
    process_config: Any,
    *worker_configs: Any,
) -> Tuple[str, dict]:
    """
    Собрать (name, proc_dict) с воркерами.
    process_config.build() -> (name, d), worker_configs.build() -> (wn, wd).
    """
    name, proc_dict = config_to_dict(process_config)
    if worker_configs:
        workers_dict = {}
        for w in worker_configs:
            wn, wd = config_to_dict(w)
            workers_dict[wn] = wd
        proc_dict["workers"] = workers_dict
    return name, proc_dict
```

**Экспорт в `data_schema_module/__init__.py`:**
```python
from .utils.config_converters import config_to_dict, configs_to_dicts, build_process_with_workers
# добавить в __all__
```

---

## Шаг 2: SystemLauncher — только dict

**Файл:** `process_manager_module/launcher/system_launcher.py`

### 2.1 Удалить
- `from ...data_schema_module import RegisterBase`
- Класс `ProcessBuilder` (переносится в app или удаляется)
- Логику `hasattr(config, "build")`, `hasattr(config, "to_dict")`

### 2.2 Изменить `add_process`

**Было:**
```python
def add_process(
    self,
    config: Union[ProcessBuilder, RegisterBase, Dict[str, Any]],
    workers: Optional[List[RegisterBase]] = None,
) -> "SystemLauncher":
```

**Стало:**
```python
def add_process(
    self,
    name: str,
    proc_dict: Dict[str, Any],
) -> "SystemLauncher":
    """
    Добавить процесс. Только dict.
    name: имя процесса, proc_dict: {"class": "...", "queues": {...}, "workers": {...}}
    """
    self._processes.append((name, proc_dict))
    return self
```

### 2.3 Удалить `create_process`
Метод больше не нужен — сборка в app.

### 2.5 Обновить экспорты
- `process_manager_module/launcher/__init__.py` — удалить ProcessBuilder
- `process_manager_module/__init__.py` — удалить ProcessBuilder из импорта и __all__

### 2.4 Проверить `_build_processes_config`
Уже работает с `_processes: List[Tuple[str, Dict]]` — без изменений.

---

## Шаг 3: Обновить main.py

**Файл:** `multiprocess_prototype/main.py`

**Было:**
```python
launcher.add_process(Process1Config(), workers=[Worker1Config()])
launcher.add_process(
    Process2Config(),
    workers=[Worker2_1Config(), Worker2_2Config()],
)
```

**Стало:**
```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    build_process_with_workers,
)

# Вариант 1: через хелпер
launcher.add_process(*build_process_with_workers(Process1Config(), Worker1Config()))
launcher.add_process(*build_process_with_workers(
    Process2Config(),
    Worker2_1Config(),
    Worker2_2Config(),
))

# Вариант 2: явно
name1, d1 = Process1Config().build()
d1["workers"] = {wn: wd for wn, wd in [Worker1Config().build()]}
launcher.add_process(name1, d1)
```

Рекомендуется вариант 1 (хелпер).

---

## Шаг 4: ProcessBuilder — опционально

**Вариант A:** Удалить ProcessBuilder полностью. Использовать `build_process_with_workers` в app.

**Вариант B:** Перенести ProcessBuilder в `multiprocess_prototype/utils/` как утилиту app-слоя:
```python
# multiprocess_prototype/utils/process_builder.py
from multiprocess_framework.refactored.modules.data_schema_module import config_to_dict

class ProcessBuilder:
    """Сборщик (name, dict) в app-слое. Принимает объекты с build()."""
    def __init__(self, config):
        self._config = config
        self._workers = []

    def add_worker(self, config):
        self._workers.append(config)
        return self

    def build(self):
        return build_process_with_workers(self._config, *self._workers)
```
Тогда main.py: `launcher.add_process(*ProcessBuilder(Process1Config()).add_worker(Worker1Config()).build())`

**Рекомендация:** Вариант A — проще, меньше кода.

---

## Шаг 5: ErrorManager — упростить (опционально)

ErrorManager уже принимает dict. Для полной консистенции можно убрать поддержку `object с build()` — оставить только `dict | LogConfig | None`. Но это ломает `ErrorManager(config=ErrorManagerConfig())`.

**Рекомендация:** Оставить как есть. ErrorManager — пример dict-at-boundary, поддержка build() — удобство для app, которое вызывает `ErrorManagerConfig().build()` и передаёт dict.

---

## Шаг 6: Тесты

### 6.1 process_manager_module
- `test_system_launcher.py`: переписать под новый API
  - Удалить: MockConfigWithBuild, MockConfigWithToDict, test_add_process_with_build, test_add_process_with_to_dict, test_add_process_with_workers, test_add_process_with_process_builder, test_create_process_returns_builder
  - Изменить: test_add_process_with_dict → test_add_process_name_and_dict
  - Добавить: `add_process("p1", {"class": "mock.Process", "priority": "normal"})`
- `test_process_builder.py`: удалить файл (ProcessBuilder удалён) или перенести в app если выбран Вариант B

### 6.2 integration
- `test_launcher_integration.py`, `test_main_launcher.py` — обновить под новый API

### 6.3 data_schema_module
- Добавить `test_config_converters.py` для `config_to_dict`, `build_process_with_workers`

### 6.4 multiprocess_prototype
- Проверить, что `main.py` запускается и процессы стартуют

---

## Шаг 7: Документация

- `process_manager_module/README.md` — обновить API: `add_process(name, proc_dict)`
- `CONFIG_UNIFIED_APPROACH.md` — добавить раздел "Реализовано"
- `data_schema_module` — описать `config_to_dict`, `build_process_with_workers` в README

---

## Порядок выполнения

1. Создать `config_converters.py` в data_schema_module
2. Изменить SystemLauncher (удалить RegisterBase, ProcessBuilder, новый add_process)
3. Обновить main.py
4. Обновить тесты
5. Запустить все тесты
6. Обновить документацию

---

## Проверка

```bash
# Из Inspector_prototype
python -m pytest multiprocess_framework/refactored/modules/process_manager_module/tests/ -v
python -m pytest multiprocess_framework/refactored/modules/error_module/tests/ -v
python -m pytest multiprocess_framework/tests/integration/test_launcher_integration.py -v
python multiprocess_prototype/main.py  # ручная проверка запуска
```

---

## Откат

Если что-то пойдёт не так: git revert. Изменения локализованы в system_launcher, main.py, новый файл config_converters.

---

## Реализовано (обновление)

- config_converters.py, process(), HasBuild
- SystemLauncher: add_process(name, proc_dict)
- **DEFAULT_PROCESS_SCHEMA** (launcher/schema.py) — эталонная структура proc_dict
- **merge_with_defaults** — нормализация при add_process(), недостающие ключи заполняются из default
