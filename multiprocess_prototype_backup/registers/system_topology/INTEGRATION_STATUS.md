# Статус интеграции topology_adapter → ProcessManagerProcess

## Task 3.2 — Wire Adapter

### Результат: РЕАЛИЗОВАНО ✓

Интеграция завершена через параметризацию `orchestrator_class_path` в `ProcessSpawner`.

### Реализованные изменения

| Файл | Что изменено |
|------|-------------|
| `multiprocess_framework/modules/process_manager_module/launcher/spawner.py` | Параметр `orchestrator_class_path: str = PROCESS_MANAGER_CLASS_PATH` в `__init__()`, использован в `launch_orchestrator()` |
| `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py` | Параметр `orchestrator_class_path: Optional[str] = None` в `__init__()`, пробрасывается в `_create_spawner()` |
| `multiprocess_prototype/backend/processes/process_manager/process.py` | Новый `ProcessManagerProcessApp(ProcessManagerProcess)`, переопределяет `_setup_topology_manager()` |
| `multiprocess_prototype/main.py` | `SystemLauncher(orchestrator_class_path=PROCESS_MANAGER_APP_CLASS_PATH, ...)` |

### Архитектурное решение

**Вариант A** (предпочтительный): фреймворк параметризован, прототип передаёт свой подкласс.

Обратная совместимость сохранена: `orchestrator_class_path` имеет default = `PROCESS_MANAGER_CLASS_PATH`,
существующие пользователи фреймворка не затронуты.

### Поток вызовов

```
main.py
  └─ SystemLauncher(orchestrator_class_path=PROCESS_MANAGER_APP_CLASS_PATH)
       └─ ProcessSpawner(orchestrator_class_path=...)
            └─ Process(target=run_process_function, args=(orchestrator_class_path, ...))
                 └─ ProcessManagerProcessApp.__init__()
                      └─ ProcessManagerProcessApp._setup_topology_manager()
                           ├─ super()._setup_topology_manager()  # создаёт self._topology_manager
                           └─ configure_topology_manager(self._topology_manager)  # подключает diff/commands
```

### Текущее состояние

- `system_diff_fn` — реализована, покрыта тестами (Task 3.3) ✓
- `system_commands_fn` — реализована, покрыта тестами (Task 3.3) ✓
- `configure_topology_manager` — реализована (Task 3.1) ✓
- `ProcessManagerProcessApp` — создан, подключает topology_adapter ✓
- Фреймворк параметризован — обратно совместим ✓
