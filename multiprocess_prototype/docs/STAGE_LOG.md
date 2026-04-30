# multiprocess_prototype/docs/STAGE_LOG.md

## STAGE_LOG — обнаруженные проблемы фреймворка (v3)

Журнал проблем фреймворка, найденных при поэтапной сборке v3.

### Framework Gap #1: Signal handler не работает из не-main thread

- **Модуль:** `process_manager_module` (`launcher/spawner.py`, `_setup_signals`)
- **Симптом:** `ValueError: signal only works in main thread`
- **Контекст:** тестовый harness запускает `SystemLauncher.start()` в фоновом потоке; `ProcessSpawner.launch_orchestrator()` вызывает `_setup_signals()` из этого потока.
- **Fix:** в `ProcessSpawner._setup_signals()` добавлена проверка `threading.current_thread() is threading.main_thread()` — вне main thread регистрация сигналов пропускается.
- **Статус:** исправлено во фреймворке

### Framework Gap #2: Нет `launcher.wait_until_ready(timeout)`

- **Модуль:** `process_manager_module` (`system_launcher.py`)
- **Симптом:** интеграционные тесты используют `time.sleep(...)` вместо ожидания готовности дочерних процессов.
- **Fix:** добавлен `SystemLauncher.wait_until_ready(timeout)` — ожидает `multiprocessing.Event`, который `ProcessManagerProcess` выставляет после завершения `initialize()`. Harness обновлён.
- **Статус:** закрыт (ADR-116)

### Framework Gap #3: `send_callback` + `multiprocessing.Queue` — pickle

- **Модуль:** `registers_module` (`core/manager.py`, snapshot для IPC)
- **Симптом:** `RuntimeError: Condition objects should only be shared between processes through inheritance` при `queue.put(register_update)` из тестового/main-процесса.
- **Причина:** `model_dump()` без `mode="json"` может оставлять типы, которые плохо сериализуются в pickle для MP-очереди.
- **Fix:** `snapshot = reg.model_dump(mode="json")` перед вызовом `send_callback`.
- **Статус:** исправлено во фреймворке

### Observation #1: `ProcessModule.send()` vs `send_message()`

- **Модуль:** `process_module`
- **Наблюдение:** `send(msg)` принимает объект сообщения и может сериализовать через `.to_dict()`, но `send_message(target, dict)` однозначно кладёт dict в очередь целевого процесса; в v2 везде используется `send_message()`.
- **Рекомендация:** в прототипах v3 использовать `send_message(target, msg.to_dict())` для DATA-сообщений.

---

| Stage | Модуль | Симптом | Решение / issue |
|-------|--------|---------|-----------------|
| v3 review | spawner | сигналы из thread | проверка main thread в `_setup_signals` |
| v3 review | system_launcher | sleep в тестах | Gap #2 — `wait_until_ready` (ADR-116, закрыт) |
