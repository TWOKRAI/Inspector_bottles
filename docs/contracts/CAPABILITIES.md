# Контактная книжка бэкенда (capability manifest v0)

> ГЕНЕРИРУЕТСЯ: `python -m backend_ctl.dump_capabilities` — руками не править.
> Дрейф с runtime ловит CI (`backend_ctl/tests/test_capabilities.py`).

## Как пользоваться (агенту)

```python
from backend_ctl import BackendDriver          # или BackendHarness для headless-старта

with BackendDriver(port=8765) as drv:          # бэкенд поднят с BACKEND_CTL=1
    res = drv.send_command("<процесс>", "<команда>", {<аргументы>})
    caps = drv.capabilities()                  # этот же свод, но runtime
```

Команда адресуется процессу по имени (колонка «Процесс» ниже). Ответ приходит
request-response (dict). События (push без request_id) читаются `drv.events()`.

## Топология (управляемые процессы)

| Процесс | Класс |
|---|---|
| `camera_0` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `devices` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `preprocessor` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `process_flip` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `process_grayscale` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `process_negative` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `region_splitter` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `stitcher` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |

## Каналы router'а ProcessManager

| Канал | Тип |
|---|---|
| `ProcessManager_data` | `QueueChannel` |
| `ProcessManager_local` | `QueueChannel` |
| `ProcessManager_system` | `QueueChannel` |
| `backend_ctl` | `SocketChannel` |
| `system_events` | `QueueChannel` |

## Процесс `ProcessManager`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `process.command` | Router endpoint: вложенная команда PM | system |
| `process.create` | Создать процесс из inline-конфига | system |
| `process.list` | Список всех процессов и статусов | system |
| `process.pause` | Поставить процесс на паузу | system |
| `process.relay` | Relay: доставить команду в целевой процесс через свежий PSR PM | system |
| `process.restart` | Перезапустить именованный процесс | system |
| `process.resume` | Возобновить процесс | system |
| `process.start` | Запустить именованный процесс | system |
| `process.status` | Статус именованного процесса | system |
| `process.stop` | Остановить именованный процесс | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `state.get` | Прочитать значение из дерева | state_store |
| `state.get_subtree` | Прочитать поддерево | state_store |
| `state.merge` | Глубокий merge dict в поддерево | state_store |
| `state.set` | Установить значение в дереве | state_store |
| `state.subscribe` | Подписаться на изменения | state_store |
| `state.unsubscribe` | Отписаться от подписки | state_store |
| `state.unsubscribe_all` | Отписать все подписки процесса | state_store |
| `stats_snapshot` |  | diagnostics, stats |
| `system.shutdown` | Завершить систему | system |
| `system.stats` | Статистика системы | system |
| `topology.apply` | Применить топологию процессов | system |
| `topology.diff` | Вычислить diff топологии (dry-run) | system |
| `topology.get` | Получить текущую топологию | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `wire.setup` | Настроить wire-канал (SHM + routes) | system |
| `wire.status` | Статусы wire-каналов | system |
| `wire.teardown` | Разобрать wire-канал | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`heartbeat`

## Процесс `camera_0`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `freeze_capture` |  |  |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `pause_capture` |  |  |
| `reset_metrics` |  | stats |
| `resume_capture` |  |  |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `start_capture` |  |  |
| `stats_snapshot` |  | diagnostics, stats |
| `stop_capture` |  |  |
| `unfreeze_capture` |  |  |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`

## Процесс `devices`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `device_connect` |  |  |
| `device_describe` |  |  |
| `device_disconnect` |  |  |
| `device_list` |  |  |
| `device_protocols` |  |  |
| `device_read` |  |  |
| `device_remove` |  |  |
| `device_sync_set` |  |  |
| `device_upsert` |  |  |
| `device_upsert_many` |  |  |
| `device_write` |  |  |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `hik_close` |  |  |
| `hik_enum` |  |  |
| `hik_get_params` |  |  |
| `hik_open` |  |  |
| `hik_release` |  |  |
| `hik_set_params` |  |  |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `register_update` | GUI/процесс обновляет значение регистра | registers |
| `reset_metrics` |  | stats |
| `robot_abort` |  |  |
| `robot_clear_queue` |  |  |
| `robot_draw_abort` |  |  |
| `robot_draw_circle` |  |  |
| `robot_draw_polyline` |  |  |
| `robot_draw_progress` |  |  |
| `robot_draw_set_accel` |  |  |
| `robot_draw_set_overlap` |  |  |
| `robot_draw_set_pass_size` |  |  |
| `robot_draw_set_pen` |  |  |
| `robot_draw_set_speed` |  |  |
| `robot_draw_set_travel` |  |  |
| `robot_draw_square` |  |  |
| `robot_enqueue_job` |  |  |
| `robot_get_robot_config` |  |  |
| `robot_get_telemetry` |  |  |
| `robot_jog` |  |  |
| `robot_jog_abort` |  |  |
| `robot_read_echo` |  |  |
| `robot_return_job` |  |  |
| `robot_send_test_job` |  |  |
| `robot_set_encoder_offset` |  |  |
| `robot_set_manual_mode` |  |  |
| `robot_set_mode` |  |  |
| `robot_set_robot_config` |  |  |
| `robot_set_servo` |  |  |
| `robot_toolchange` |  |  |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_config` |  |  |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `vfd_get_status` |  |  |
| `vfd_reset_fault` |  |  |
| `vfd_run` |  |  |
| `vfd_set_freq` |  |  |
| `vfd_stop` |  |  |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Регистры (поля — цели `register_update`)

- **device_hub**: `commands_err`, `commands_ok`, `devices_connected`, `devices_total`, `last_error`, `registry_path`, `supervisor_interval_s`

### Router-handlers (события, не команды)

`state.changed`

## Процесс `preprocessor`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `register_update` | GUI/процесс обновляет значение регистра | registers |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_config` |  |  |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Регистры (поля — цели `register_update`)

- **resize**: `scale_factor`, `target_height`, `target_width`

### Router-handlers (события, не команды)

`state.changed`

## Процесс `process_flip`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`

## Процесс `process_grayscale`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`

## Процесс `process_negative`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`

## Процесс `region_splitter`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`

## Процесс `stitcher`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `config.reload` | Перечитать/применить секцию observability (уровень логов, sink'и) на лету | system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Выключить sink логгера по имени (unregister_channel) | system |
| `logger.sink.enable` | Включить sink логгера по имени (register_channel) | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`state.changed`
