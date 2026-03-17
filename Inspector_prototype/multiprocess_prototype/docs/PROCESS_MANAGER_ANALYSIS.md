# multiprocess_prototype\docs\PROCESS_MANAGER_ANALYSIS.md
# Анализ process_manager_module и упрощение app.py

## Текущая архитектура process_manager_module

```
process_manager_module/
├── core/
│   ├── process_manager_core.py   # ProcessManagerCore — ядро (refactored)
│   ├── process_lifecycle.py     # Жизненный цикл процессов ОС
│   ├── process_priority.py      # Приоритеты
│   └── process_status.py       # Статусы
├── process/
│   └── process_manager_process.py  # ProcessManagerProcess (использует СТАРЫЕ модули)
├── bootstrap/
│   └── process_manager_bootstrap.py # Использует СТАРЫЕ модули
├── launcher/
│   └── system_launcher.py      # Обёртка над bootstrap
├── monitor/
│   └── process_monitor.py
└── runner/
    └── process_runner.py       # run_process_function (refactored)
```

## Что можно использовать из refactored

| Компонент | Использование | Зависимости |
|-----------|---------------|-------------|
| **ProcessManagerCore** | Да | shared_resources, queue_registry, config_manager — все refactored |
| **run_process_function** | Да | refactored |
| **ProcessManagerProcess** | Нет | ConfigManager, QueueRegistry, ConsoleManager из старых модулей |
| **ProcessManagerBootstrap** | Нет | SharedResourcesManager, ConfigManager, LoggerManager из старых модулей |
| **SystemLauncher** | Нет | Зависит от ProcessManagerBootstrap |

## Проблема: ProcessManagerCore.create_process не регистрирует процесс

`create_process` **не вызывает** `shared_resources.register_process_state()`. В результате:

1. `run_process_function` получает `process_data = shared_resources.get_process_data(process_name)` → `None`
2. Вызывается `register_process_state(process_name)` без config → создаётся ProcessData без нашего конфига
3. Конфиг `workers_count`, `queue_maxsize` теряется

Поэтому в app.py приходится вручную вызывать `register_process_state` **до** `create_process`.

## Что уже умеет ProcessManagerCore

1. **create_process(name, class_path, config, priority)** — создаёт процесс, если:
   - `process_data` уже зарегистрирован (через register_process_state)
   - В `config` есть `queues` — создаёт очереди через `create_and_register_queues`
2. **create_processes_from_config(config_data)** — цикл по `config_data`, для каждого вызывает `create_process`

## Варианты упрощения app.py

### Вариант 1: Расширить ProcessManagerCore.create_process

Добавить в начало `create_process`:

```python
if self.shared_resources:
    self.shared_resources.register_process_state(
        name,
        config={"process": config or {}}
    )
```

Тогда app.py может вызывать только `create_process` — регистрация будет внутри.

**Плюсы:** Один вызов вместо трёх на процесс.  
**Минусы:** Изменение framework; `register_process_state` при повторном вызове обновляет ProcessData (это ок).

---

### Вариант 2: Добавить метод create_process_full в ProcessManagerCore

```python
def create_process_full(
    self,
    name: str,
    class_path: str,
    config: Optional[Dict[str, Any]] = None,
    priority: str = "normal",
    queue_maxsize: int = 100
) -> Optional[Process]:
    """Регистрация + очереди + создание процесса в одном вызове."""
    config = config or {}
    if "queues" not in config:
        config["queues"] = {
            "system": {"maxsize": queue_maxsize},
            "data": {"maxsize": queue_maxsize},
        }
    if self.shared_resources:
        self.shared_resources.register_process_state(name, config={"process": config})
    return self.create_process(name, class_path, config, priority)
```

**Плюсы:** Явный API, не трогает `create_process`.  
**Минусы:** Дублирование логики (create_process уже вызывает create_and_register_queues).

---

### Вариант 3: Конфиг-драйвен через create_processes_from_config

Формат конфига:

```python
processes_config = {
    "process_a": {
        "name": "process_a",
        "class": "multiprocess_prototype.processes.process_a.ProcessAModule",
        "priority": "normal",
        "workers_count": 2,
        "queue_maxsize": 100,
        "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 100}},
    },
    "process_b": { ... },
}
```

Расширить `create_processes_from_config`:
- перед `create_process` вызывать `register_process_state`
- при отсутствии `queues` — генерировать из `queue_maxsize`

Тогда app.py:

```python
def _create_processes(self):
    processes_base = "multiprocess_prototype.processes"
    processes_config = {}
    if self.config.process_a_enabled:
        processes_config["process_a"] = {
            "name": "process_a",
            "class": f"{processes_base}.process_a.ProcessAModule",
            "priority": "normal",
            "workers_count": self.config.process_a_workers_count,
            "queue_maxsize": self.config.queue_maxsize,
        }
    # ... process_b аналогично
    self.process_manager.create_processes_from_config(processes_config)
    self.process_names = list(processes_config.keys())
```

Но `create_processes_from_config` сейчас не вызывает `register_process_state` — нужно доработать.

---

### Вариант 4: Хелпер в multiprocess_prototype (без изменений framework)

```python
# app.py
def _create_processes(self):
    processes_base = "multiprocess_prototype.processes"
    queue_config = get_default_queue_config(self.config.queue_maxsize)

    def add_process(name: str, workers_count: int):
        config = {"workers_count": workers_count, "queue_maxsize": self.config.queue_maxsize}
        self.shared_resources.register_process_state(name, config={"process": config})
        self.queue_registry.create_and_register_queues(name, queue_config)
        self.process_manager.create_process(
            name=name,
            class_path=f"{processes_base}.{name}.{name.title().replace('_', '')}Module",
            config=config,
            priority="normal",
        )
        self.process_names.append(name)

    if self.config.process_a_enabled:
        add_process("process_a", self.config.process_a_workers_count)
    if self.config.process_b_enabled:
        add_process("process_b", self.config.process_b_workers_count)
```

Минимальное упрощение — убрать дублирование, оставить логику в app.

---

## Рекомендация

**Вариант 1** — добавить `register_process_state` в начало `ProcessManagerCore.create_process` — даёт наибольшее упрощение при минимальных правках:

1. Один вызов вместо трёх на процесс
2. Логика «процесс = регистрация + очереди + создание» в одном месте
3. `create_processes_from_config` начнёт работать без доп. вызовов

Дополнительно: при отсутствии `config["queues"]` подставлять `{"system": {"maxsize": N}, "data": {"maxsize": N}}` из `config.get("queue_maxsize", 100)`.

Тогда app.py сократится до:

```python
def _create_processes(self):
    processes_base = "multiprocess_prototype.processes"
    if self.config.process_a_enabled:
        self.process_manager.create_process(
            "process_a",
            f"{processes_base}.process_a.ProcessAModule",
            {"workers_count": self.config.process_a_workers_count, "queue_maxsize": self.config.queue_maxsize},
            "normal",
        )
        self.process_names.append("process_a")
    if self.config.process_b_enabled:
        self.process_manager.create_process(
            "process_b",
            f"{processes_base}.process_b.ProcessBModule",
            {"workers_count": self.config.process_b_workers_count, "queue_maxsize": self.config.queue_maxsize},
            "normal",
        )
        self.process_names.append("process_b")
```

Без `register_process_state` и `create_and_register_queues` в app.

---

## SystemLauncher / ProcessManagerBootstrap

Использовать **нельзя** — они зависят от старых модулей (`Shared_resources_module`, `Config_module`, `Logger_module`, `Process_manager_module.platforms`). Для multiprocess_prototype нужен только refactored-стек.
