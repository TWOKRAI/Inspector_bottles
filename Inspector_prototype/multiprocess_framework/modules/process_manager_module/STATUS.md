# process_manager_module — Статус рефакторинга

## Текущий этап: 8 / 8 — доработка 2026-04-10 (план #14)

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Runner расслоён; per-process stop events; bundle_contract |
| Тесты (покрытие) | 9 | +bundle_contract, stop_one, monitor heartbeat |
| Документация (README, interfaces) | 9 | DECISIONS.md модуля, CONFIG_CONTRACT (bundle), README |
| Связанность (меньше = лучше) | 6 | Spawner упрощён; контракт bundle в одном месте |
| Дублирование | 8 | build_bundle единая точка сборки dict |
| Работоспособность | 10 | stop одного процесса, restart, liveness в мониторе |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (убран sys.path.insert из process_runner.py)
- [x] Этап 1: SystemLauncher → ProcessSpawner → ProcessManagerProcess запускается (PID проверен)
- [x] Этап 2: ProcessManager создаёт и запускает Process1Module, Process2Module с воркерами
- [x] Этап 3: Коммуникация через Router (ProcessMonitor broadcasts state changes)
- [x] Этап 4: Архитектура стабилизирована (Dict at Boundary, bundle pattern)
- [x] Этап 5: CommandManager подключён (6 встроенных команд: process.list/start/stop/status, system.shutdown/stats)
- [x] Этап 6: Graceful shutdown работает (signal handler без sys.exit, настраиваемые timeout-ы)
- [x] Этап 7: Unit-тесты написаны и проходят (8 файлов)
- [x] Этап 8: README и interfaces.py готовы (ISystemLauncher, IProcessManagerProcess, IProcessRegistry)

## Обновление 2026-04-10 (план process_manager_module)

- **Per-process `stop_event`** в `ProcessRegistry`; `stop_one` / `remove_process`; `restart_process` + команда `process.restart`; конфиги для рестарта в `_process_configs`.
- **ProcessSpawner**: только SRM + `_ProcessLogger`; `stop_event` оркестратора не в bundle — подстановка в `run_process_function` → `process_data.custom`.
- **Runner**: `class_loader`, `bundle_builder`; `core/bundle_contract.py`.
- **ProcessMonitor**: `_check_heartbeats()` + `crashed_processes` в stats.

## Обновление 2026-04-03

- **`ProcessMonitor`**: цикл опроса вызывает `ProcessStateRegistry.get_all_process_data()` и собирает снимок из `ProcessData` (`status`, `metadata`, `custom`). Ранее вызывался несуществующий `get_all_processes()`, из‑за чего в логах оркестратора сыпался `AttributeError`.

## Обновление 2026-03-30 (ADR-102)

- **`process_runner._build_shared_resources_from_bundle`**: после `register_process_state` заполняется `ConfigStore` pickle-safe срезом `{"process", "managers"}` для текущего процесса и пустым срезом для имён из `routing_map`, чтобы `get_process_config` в child был согласован с контуром родителя.

## Что было сделано в рефакторинге (2026-03-13)

### interfaces.py
- Созданы `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry`
- Полные docstrings с примерами

### ProcessManagerProcess
- Извлечён `_create_components()` из `__init__`
- `ConsoleManager` создаётся только если `console_enabled: true` в конфиге
- `QueueRegistry` берётся из `shared_resources` если доступен
- Добавлен `_handle_critical_error()` с интеграцией error_module
- Зарегистрированы 6 встроенных команд через CommandManager
- Graceful `stop_process()`: stop_event → join → terminate → kill

### process_runner.py
- Извлечены вспомогательные функции: `_load_process_class`, `_build_shared_resources_from_bundle`, `_run_lifecycle`
- Создан `_ProcessLogger` — лёгкий логгер с fallback на print
- Удалены диагностические print-ы (queue_id/handle)
- Исправлен импорт `Console_module` → `console_module.ConsoleRedirector`
- Два цикла while объединены в один `_run_lifecycle()`
- Удалён alias `_run_process_function`
- Добавлены `_update_process_state()` и `_log_exception_via_error_manager()`

### spawner.py
- Убран `sys.exit(0)` из `_signal_handler` — wait() возвращается естественно
- Добавлен `ErrorManager` (создаётся в `launch_orchestrator`)
- Настраиваемый `stop_timeout`
- Поддержка `on_shutdown` callback
- Каскад stop: stop_event → join(graceful) → terminate → join → kill

### ProcessRegistry
- `stop_all(timeout)` — timeout настраиваемый (по умолчанию 5s)
- Логирование timeout-а для каждого процесса
- `_join_all` логирует процессы, которые не завершились

### SystemLauncher
- Добавлены `stop_timeout` и `on_shutdown` параметры
- `run()` обёрнут в try/except с error_module
- `_create_spawner()` передаёт настройки в ProcessSpawner

### __init__.py
- Экспортируются: ISystemLauncher, IProcessManagerProcess, IProcessRegistry
- Экспортируются: ProcessRegistry, ProcessPriority, ProcessStatus, ProcessMonitor, ProcessSchemaAdapter

## Конфигурация (2026-03-17)

- **ProcessSchemaAdapter** делегирует в `config_to_dict` (data_schema_module) при наличии `build()` — один источник правды
- **CONFIG_CONTRACT.md** — документирован контракт proc_dict (обязательные/опциональные поля, потребители)
- **docs/examples/proc_dict_canonical_examples.py** — эталонные dict и демо нормализации (2026-03-30)

## Известные проблемы

- Нет (все известные проблемы устранены)

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Убран sys.path.insert из process_runner.py, STATUS.md создан | 0 |
| 2026-03-11 | Этап 1: SystemLauncher → ProcessManagerProcess запускается, stop_event работает | 1 |
| 2026-03-11 | Этап 2: дочерние процессы создаются; flush=True в prints; graceful stop в spawner | 2 |
| 2026-03-13 | Этапы 3-8: interfaces.py, error_module, graceful shutdown, CommandManager, тесты, документация | 8 |
| 2026-03-30 | Добавлены docs/examples/proc_dict_canonical_examples.py; ссылка в CONFIG_CONTRACT.md и docs/README.md | 8 |