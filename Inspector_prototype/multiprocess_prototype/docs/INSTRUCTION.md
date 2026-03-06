# Инструкция: multiprocess_prototype

Пошаговое руководство по созданию и расширению демо-приложения на базе `multiprocess_framework/refactored`.

## Обзор

Приложение использует **только** классы из `Inspector_prototype/multiprocess_framework/refactored`.  
Структура: 2 процесса (Process A, Process B), по 2 потока в каждом. Связь через RouterManager и очереди.

---

## Шаг 1: Структура проекта

```
multiprocess_prototype/
├── __init__.py
├── config.py          # AppConfig, get_default_queue_config
├── app.py             # MultiprocessPrototypeApp
├── main.py            # Точка входа
├── test_init.py       # Тест инициализации в главном процессе
├── processes/
│   ├── __init__.py
│   ├── process_a.py   # ProcessAModule
│   └── process_b.py   # ProcessBModule
└── docs/
    └── INSTRUCTION.md # Эта инструкция
```

---

## Шаг 2: Конфигурация (config.py)

- `AppConfig` — dataclass с параметрами: `process_a_enabled`, `process_b_enabled`, `process_a_workers_count`, `process_b_workers_count`, `queue_maxsize`.
- `get_default_queue_config(maxsize)` — возвращает `{"system": {"maxsize": N}, "data": {"maxsize": N}}`.

---

## Шаг 3: Порядок инициализации приложения

В `MultiprocessPrototypeApp.initialize()`:

1. **SharedResourcesManager** — общий контейнер состояний процессов.
2. **ConfigManager** — хранение конфигурации.
3. **QueueRegistry** — создание и регистрация очередей (передаётся `process_state_registry` из SharedResourcesManager).
4. **ProcessManagerCore** — управление процессами (shared_resources, config_manager, queue_registry, stop_event).
5. **Регистрация процессов** — `register_process_state` + `create_and_register_queues` + `create_process`.

### Важно: конфигурация процесса

`register_process_state` принимает `config` в формате:

```python
config = {
    "process": {
        "workers_count": 2,
        "queue_maxsize": 100,
    },
    # опционально: "managers": {...}, "modules": {...}
}
```

Это сохраняется в `ProcessData.custom['process_config']` и доступно в ProcessModule через `ProcessConfigHandler`.

---

## Шаг 4: Регистрация процесса

Для каждого процесса:

```python
# 1. Регистрация состояния процесса
self.shared_resources.register_process_state(
    "process_a",
    config={"process": process_a_config},
)

# 2. Создание очередей
self.queue_registry.create_and_register_queues("process_a", queue_config)

# 3. Создание процесса
self.process_manager.create_process(
    name="process_a",
    class_path="multiprocess_prototype.processes.process_a.ProcessAModule",
    config=process_a_config,
    priority="normal",
)
```

---

## Шаг 5: Модуль процесса (ProcessModule)

Наследуйте от `ProcessModule`:

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority,
)

class ProcessAModule(ProcessModule):
    def __init__(self, name, shared_resources=None, config=None):
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.workers_count = config.get("workers_count", 2) if config else 2

    def initialize(self) -> bool:
        if not super().initialize():
            return False
        self._create_workers()
        return True

    def _create_workers(self):
        for i in range(self.workers_count):
            worker_name = f"process_a_worker_{i}"

            def worker_func(stop_event, pause_event, worker_id=i):
                while not stop_event.is_set():
                    if pause_event.is_set():
                        time.sleep(0.1)
                        continue
                    # Работа воркера
                    time.sleep(0.01)

            thread_config = ThreadConfig(priority=ThreadPriority.NORMAL)
            self.worker_manager.create_worker(worker_name, worker_func, thread_config)
```

### API WorkerManager и ThreadConfig

- `create_worker(worker_name, target, config, auto_start=False)` — позиционные аргументы!
- `ThreadConfig(priority=..., restart_on_failure=False, max_restarts=3, dependencies=None)` — без `name` и `daemon`.

---

## Шаг 6: Запуск

```bash
cd Inspector_prototype
python -m multiprocess_prototype.main
```

или тест инициализации:

```bash
python multiprocess_prototype/test_init.py
```

---

## Шаг 7: Планируемые расширения (Фаза 2)

1. **Обмен сообщениями** — `self.send()` / `self.receive()` через RouterManager.
2. **Message.create()** — создание типизированных сообщений.
3. **Дополнительные процессы** — повторить шаг 4 для нового процесса.
4. **Дополнительные очереди** — расширить `queue_config` и зарегистрировать в `create_and_register_queues`.

---

## Зависимости

- `multiprocess_framework.refactored` — все модули (process_module, worker_module, shared_resources_module, config_module, router_module, process_manager_module и т.д.).
- `modules (no work!!!) go refactored` — **не** используется.

---

## Исправления, внесённые в framework

Для совместимости с ProcessData.custom (без ProcessData.config):

1. **ProcessConfigHandler** — поддержка `process_data.custom['process_config']` через `_CustomProcessConfig`.
2. **ProcessModule._init_configuration** — загрузка конфига из `custom` при отсутствии `config`.
3. **ProcessModule** — `self.config = self.config_handler.data` вместо `dict(self.config_handler)`.
4. **ProcessLifecycle** — `print()` в `except` для отладки при падении инициализации.

Подробное описание проблем и причин исправлений: [PROBLEMS_AND_FIXES.md](PROBLEMS_AND_FIXES.md).
