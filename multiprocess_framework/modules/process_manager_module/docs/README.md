# Документация process_manager_module

**Эталонные примеры `proc_dict`:** [`examples/proc_dict_canonical_examples.py`](examples/proc_dict_canonical_examples.py). Контракт полей: [`CONFIG_CONTRACT.md`](CONFIG_CONTRACT.md).

## Основные концепции

`process_manager_module` управляет жизненным циклом OS-процессов системы.
Реализует трёхуровневую архитектуру:

```
SystemLauncher (фасад)
    └── ProcessSpawner (bootstrap)
            └── ProcessManagerProcess (оркестратор, OS-процесс)
                    └── ProcessRegistry → дочерние OS-процессы
```

## Компоненты

| Файл | Класс | Роль |
|------|-------|------|
| `launcher/system_launcher.py` | `SystemLauncher` | Фасад запуска, Dict at Boundary |
| `launcher/spawner.py` | `ProcessSpawner` | Bootstrap: инфраструктура + OS-процесс |
| `process/process_manager_process.py` | `ProcessManagerProcess` | Оркестратор (extends ProcessModule) |
| `runner/process_runner.py` | `run_process_function` | Top-level функция (pickle-safe) |
| `core/process_registry.py` | `ProcessRegistry` | Реестр + lifecycle дочерних процессов |
| `core/process_priority.py` | `ProcessPriority` | Управление приоритетами |
| `core/process_status.py` | `ProcessStatusMonitor` | Мониторинг статусов ОС-процессов (alive, pid, exitcode) |
| `monitor/process_monitor.py` | `ProcessMonitor` | Мониторинг состояний |
| `adapters/schema_adapter.py` | `ProcessSchemaAdapter` | SchemaBase → dict |
| `interfaces.py` | `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry` | Публичные контракты |

## Публичные контракты (interfaces.py)

```python
from process_manager_module.interfaces import ISystemLauncher

# ISystemLauncher
launcher.add_process(name, proc_dict)  # → self
launcher.run()                          # блокирующий запуск
launcher.start()                        # неблокирующий запуск
launcher.stop()                         # graceful shutdown
launcher.wait()                         # ожидание завершения
launcher.get_status()                   # → Dict
launcher.get_stats()                    # → Dict

# IProcessManagerProcess
pmp.create_process(name, class_path, config, priority)
pmp.start_process(process_name)
pmp.stop_process(process_name)
pmp.get_process_status(process_name)
pmp.get_all_processes_status()

# IProcessRegistry
registry.add_process(process)
registry.get_process_by_name(name)
registry.create_and_register(name, class_path, config, priority)
registry.start_all()
registry.stop_all(timeout)
```

## Bundle pattern

Для pickle-safe передачи данных в дочерний OS-процесс используется bundle dict:

```python
bundle = {
    "queues": {"worker_in": queue, ...},   # multiprocessing.Queue
    "config": {"processes_config": {...}},  # конфиг процесса
    "custom": {"stop_event": event, ...},   # дополнительные данные
    "routing_map": {"OtherProcess": {...}}, # очереди других процессов
}
```

`run_process_function` создаёт `SharedResourcesManager` из bundle внутри дочернего процесса.

## Graceful Shutdown

Каскад завершения:

```
SIGINT/SIGTERM
    → ProcessSpawner._signal_handler (без sys.exit!)
    → ProcessSpawner.stop()
        → stop_event.set()
        → process.join(graceful_timeout)
        → process.terminate() если не завершился
        → process.join(timeout)
        → process.kill() если всё ещё жив
    → SharedResourcesManager.shutdown()
    → ErrorManager.shutdown()
    → on_shutdown() callback

ProcessManagerProcess.shutdown():
    → ProcessMonitor.stop()
    → ProcessRegistry.stop_all(timeout)
        → stop_event.set()
        → join(timeout) для каждого процесса
        → terminate → join → kill
    → ConsoleManager.shutdown()
    → super().shutdown()
```

## Встроенные команды (CommandManager)

| Команда | Описание |
|---------|----------|
| `process.list` | Список всех процессов и статусов |
| `process.start` | Запустить именованный процесс |
| `process.stop` | Остановить именованный процесс |
| `process.status` | Статус именованного процесса |
| `system.shutdown` | Завершить систему |
| `system.stats` | Статистика системы |
