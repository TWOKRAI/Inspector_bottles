# process_manager_module — архитектурные решения (ADR)

## ADR-PMM-001 (was ADR-PM-001): Per-process stop events (2026-04-10)

- **Контекст:** Все дочерние процессы получали один `stop_event`; `stop_process("A")` останавливал всех.
- **Решение:** У каждого дочернего процесса свой `multiprocessing.Event`; `ProcessRegistry` хранит `Dict[str, Event]`. `stop_all()` выставляет все события; `stop_one(name)` — только одно.
- **Следствие:** Возможны `restart_process` и точечное управление.

## ADR-PMM-002 (was ADR-PM-002): Минимальный ProcessSpawner (2026-04-10)

- **Контекст:** Spawner создавал ConfigManager, LoggerManager, ErrorManager, не передаваемые в дочерние процессы.
- **Решение:** Spawner поднимает только `SharedResourcesManager` и `_ProcessLogger`; полный стек — в `ProcessManagerProcess`.
- **Следствие:** Меньше дублирования и проще bootstrap.

## ADR-PMM-003 (was ADR-PM-003): Bundle contract (2026-04-10)

- **Контекст:** Bundle-словарь собирался в реестре и разбирался в runner без явного контракта.
- **Решение:** `core/bundle_contract.py` — `build_bundle()`, `validate_bundle()`; runner проверяет bundle при входе.
- **Следствие:** Один формат и явные обязательные ключи (`queues`, `config`).

## ADR-PMM-004 (was ADR-PM-004): Heartbeat / liveness в ProcessMonitor (2026-04-10)

- **Контекст:** Монитор смотрел только на состояние из ProcessStateRegistry.
- **Решение:** Дополнительно `process.is_alive()`; при выходе без актуального state — `stopped` (exitcode 0) или `crashed` (иначе), обновление PSR и broadcast.
- **Следствие:** Видны внезапные падения без участия кода дочернего процесса.

## ADR-PMM-005 (was ADR-PM-005): Расслоение process_runner (2026-04-10, обновлено 2026-04-12)

- **Контекст:** Один крупный файл совмещал загрузку класса, memory, SRM, console, lifecycle.
- **Решение:** `runner/class_loader.py`, `bundle_builder.py`; публичный API — `run_process_function` без изменений смысла.
- **История:** `console_redirect.py` был создан как отдельный модуль (2026-04-10) для переадресации stdout/stderr в очередь, но позднее удалён при рефакторинге `console_module` (2026-04-12).
- **Следствие:** Меньшие файлы и ясные границы; console redirection теперь управляется через `console_module.ConsoleManager`.

## ADR-PMM-006 (was ADR-PM-006): stop_event оркестратора вне bundle (2026-04-10)

- **Контекст:** После удаления `stop_event` из `custom` в bundle spawner всё должен передавать тот же Event в `ProcessManagerProcess`.
- **Решение:** Spawner передаёт Event третьим аргументом в `run_process_function`; runner кладёт его в `process_data.custom` перед конструктором процесса.
- **Следствие:** Bundle остаётся pickle-safe и без лишних полей; сигнал завершения с main-процесса сохраняется.

## ADR-PMM-007 (AD-8): Router endpoint для ProcessManagerProcess (2026-04-22)

- **Контекст:** ProcessManagerProcess принимал runtime-команды (`process.create/start/stop/restart`) только через внутренний CommandManager. Другие процессы в системе не могли запросить spawn/stop через Router-сообщения, что ограничивало динамическое управление (например, добавление камер в runtime).
- **Решение:** При `initialize()` регистрируется `register_message_handler("process.command", _handle_process_command)`. Handler извлекает из `msg["data"]` вложенную команду (`cmd`), делегирует в `command_manager.handle_command()` и отправляет ответ `process.command.response` с `correlation_id` обратно через Router. Добавлена команда `process.create` для создания процессов из inline-конфига.
- **Отклонённые альтернативы:** (1) Прямой вызов методов `start_process/stop_process` без CommandManager — теряется единообразие и метрики. (2) Отдельный endpoint на каждую команду (`process.start`, `process.stop`) — избыточное количество handlers, сложнее расширять.
- **Следствие:** Любой процесс может динамически управлять другими через стандартный Router. ACL whitelist — отложен (можно добавить позже без изменения контракта).
