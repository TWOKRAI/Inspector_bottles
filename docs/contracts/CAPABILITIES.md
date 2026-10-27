# Контактная книжка бэкенда (capability manifest v1)

> ГЕНЕРИРУЕТСЯ: `python -m backend_ctl.dump_capabilities` — руками не править.
> Дрейф с runtime ловит CI (`backend_ctl/tests/test_capabilities.py`).

## Как пользоваться (агенту)

```python
from backend_ctl import BackendDriver          # или BackendHarness для headless-старта

with BackendDriver() as drv:                   # порт: env BACKEND_CTL_PORT → DEFAULT_PORT
    res = drv.send_command("<процесс>", "<команда>", {<аргументы>})
    caps = drv.capabilities()                  # этот же свод, но runtime
```

Команда адресуется процессу по имени (колонка «Процесс» ниже). Ответ приходит
request-response (dict). События (push без request_id) читаются курсором `drv.events_page(plane)` (B.1; Python-driver'а `drv.events()` больше нет — удалён в F.1).

## Топология (управляемые процессы)

| Процесс | Класс |
|---|---|
| `camera_0` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `devices` | `multiprocess_prototype.generic_process_app.GenericProcessApp` |
| `gui` | `multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess` |
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
| `ProcessManager_observability` | `QueueChannel` |
| `ProcessManager_state` | `QueueChannel` |
| `ProcessManager_system` | `QueueChannel` |
| `backend_ctl` | `SocketChannel` |

## Процесс `ProcessManager`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.subscribe_all` | Брокер (Task 5.11): подписать адрес на хвост ВСЕХ процессов одним вызовом; намерение переживает рестарт, switch и появление нового процесса. Записи идут напрямую подписчику — PM брокер, не транзит | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `observability.tail.unsubscribe_all` | Брокер: снять намерение подписчика и разослать снятие хвоста всем процессам | system |
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
| `service.list` | Хост сервисов (ADR-SVC-004): service.list | system |
| `service.restart` | Хост сервисов (ADR-SVC-004): service.restart | system |
| `service.start` | Хост сервисов (ADR-SVC-004): service.start | system |
| `service.status` | Хост сервисов (ADR-SVC-004): service.status | system |
| `service.stop` | Хост сервисов (ADR-SVC-004): service.stop | system |
| `state.delete` | Удалить узел/поддерево по пути | state_store |
| `state.get` | Прочитать значение из дерева | state_store |
| `state.get_subtree` | Прочитать поддерево | state_store |
| `state.merge` | Глубокий merge dict в поддерево | state_store |
| `state.set` | Установить значение в дереве | state_store |
| `state.subscribe` | Подписаться на изменения | state_store |
| `state.unsubscribe` | Отписаться от подписки | state_store |
| `state.unsubscribe_all` | Отписать все подписки процесса | state_store |
| `stats_snapshot` |  | diagnostics, stats |
| `supervision.status` | Supervision-снимок: epoch + per-process incarnation/restart_count/last_exit/status/pid/started_at/instance_restarts. Маркер замены инстанса = pid+instance_restarts (считает и ручные, и авто-рестарты supervision — они идут той же process.restart). incarnation растёт только при смене identity очередей; restart_count — краш-рестарты монитора | system |
| `system.shutdown` | Завершить систему | system |
| `system.stats` | Статистика системы | system |
| `telemetry.broadcast` | Телеметрия через PM: publish → всем детям (fan-out) ИЛИ адресно (data.target), throttle → центральный троттл оркестратора; cap-детекция на обоих путях | system |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `topology.apply` | Применить топологию процессов | system |
| `topology.diff` | Вычислить diff топологии (dry-run) | system |
| `topology.get` | Получить текущую топологию | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `wire.setup` | Настроить wire-канал (SHM + routes) | system |
| `wire.status` | Статусы wire-каналов | system |
| `wire.teardown` | Разобрать wire-канал | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
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
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `freeze_capture` |  |  |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
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
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `unfreeze_capture` |  |  |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `devices`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
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
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
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
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `register_update` | GUI/процесс обновляет значение регистра | registers |
| `reset_metrics` |  | stats |
| `robot_abort` | Стоп робота: {device_id, mode: 1|2|3}. |  |
| `robot_clear_queue` | Очистить очередь заданий. |  |
| `robot_do_set` | Робот v2: дискретный выход {device_id, ch: 1..16, on: bool} |  |
| `robot_draw_abort` | Прервать рисование: {device_id}. |  |
| `robot_draw_circle` | Нарисовать окружность: {device_id, cx, cy, r}. |  |
| `robot_draw_polyline` | Нарисовать полилинию: {device_id, points, ...}. |  |
| `robot_draw_progress` | Прогресс рисования: {device_id}. |  |
| `robot_draw_set_accel` | Установить ускорение рисования: {device_id, accel} (мм/с²). |  |
| `robot_draw_set_overlap` | Установить overlap: {device_id, mm}. |  |
| `robot_draw_set_pass_size` | Установить размер пачки рисования: {device_id, n} (точек на проход). |  |
| `robot_draw_set_pen` | Установить перо: {device_id, down?, up?} (мм, можно одно из двух). |  |
| `robot_draw_set_speed` | Установить скорость рисования (перо по бумаге): {device_id, pct}. |  |
| `robot_draw_set_travel` | Установить скорость переезда (перо вверх): {device_id, pct}. |  |
| `robot_draw_square` | Нарисовать квадрат по двум углам: {device_id, x1, y1, x2, y2, z?}. |  |
| `robot_enqueue_job` | Поставить CVT-задание: {device_id, x_mm, y_mm, e_capture?}. |  |
| `robot_exchange_log_get` | Журнал обмена драйвера: {device_id, since_seq?, limit?}. Работает и при разрыве связи (T5.6). |  |
| `robot_exchange_log_set` | Ручки журнала обмена: {device_id, enabled?, periodic?, clear?} (T5.6). |  |
| `robot_frame_list` | Робот v2: список систем координат {device_id} -> frames, rev |  |
| `robot_frame_teach` | Робот v2: обучить СК по трём точкам {device_id, name, origin, on_x, in_plane, base_rev} |  |
| `robot_get_robot_config` | Прочитать конфиг-блок робота. |  |
| `robot_get_telemetry` | Телеметрия робота. |  |
| `robot_jog` | Ручной ход: {device_id, dx, dy, spd?, absolute?} — смещение мм + Override %. |  |
| `robot_jog_abort` | Прервать ручной ход: {device_id}. |  |
| `robot_jog_hold` | Робот v2: удержание jog {device_id, dir: 1..8, spd: 1..100} |  |
| `robot_jog_release` | Робот v2: отпустить jog {device_id} |  |
| `robot_jog_step` | Робот v2: шаг jog {device_id, dx, dy, dz?, drz?, spd: 1..100} |  |
| `robot_param_apply` | Робот v2: применить параметры класса reinit {device_id} |  |
| `robot_param_get_all` | Робот v2: все параметры из файла {device_id} -> params{raw, value}, epoch, rev |  |
| `robot_param_set` | Робот v2: записать параметр {device_id, name, value, base_rev} |  |
| `robot_park` | Робот v2: основная остановка — конец текущей команды или цикла, домой, серво OFF {device_id, timeout_s?}; ответ сразу, итог — devices.state.<id>.park |  |
| `robot_point_capture` | Робот v2: запомнить текущую позу как точку {device_id, name, base_rev} |  |
| `robot_point_delete` | Робот v2: удалить точку {device_id, name, base_rev} |  |
| `robot_point_list` | Робот v2: список точек {device_id} -> points, rev |  |
| `robot_point_save` | Робот v2: сохранить точку {device_id, point{name, x, y, z, rz, hand, frame?}, base_rev} |  |
| `robot_program_abort` | Робот v2: прервать программу {device_id} |  |
| `robot_program_delete` | Робот v2: удалить программу {device_id, name, base_rev} |  |
| `robot_program_get` | Робот v2: прочитать программу {device_id, name} -> program, rev |  |
| `robot_program_list` | Робот v2: имена программ {device_id} -> programs |  |
| `robot_program_run` | Робот v2: запустить программу {device_id, name} |  |
| `robot_program_save` | Робот v2: сохранить программу {device_id, program{name, steps}, base_rev} |  |
| `robot_read_echo` | Эхо последнего задания. |  |
| `robot_return_job` | Возврат буквы на ленту: {device_id, x_mm, y_mm, z_mm} (координата слота). |  |
| `robot_send_test_job` | Тестовое CVT-задание: {device_id, x, y}. |  |
| `robot_servo` | Робот v2: серво {device_id, on: bool} |  |
| `robot_set_encoder_offset` | Подстройка компенсации конвейера: {device_id, lead_mm} (мм вдоль ленты, знаковое). |  |
| `robot_set_manual_mode` | Ручной режим: {device_id, on: bool}. |  |
| `robot_set_mode` | Режим робота: {device_id, mode: cvt|draw|manual}. |  |
| `robot_set_robot_config` | Конфиг робота: {device_id, ...fields}. |  |
| `robot_set_servo` | Серво: {device_id, on: bool}. |  |
| `robot_stop` | Робот v2: стоп {device_id, level: SOFT|HARD|HALT} |  |
| `robot_toolchange` | Смена инструмента: {device_id, target: 0|1|2, timeout?}. |  |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_config` |  |  |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `vfd_get_status` | Статус ПЧ: {device_id}. |  |
| `vfd_reset_fault` | Сброс аварии ПЧ: {device_id}. |  |
| `vfd_run` | Пуск ПЧ: {device_id, direction?, freq_hz?}. |  |
| `vfd_set_freq` | Установить частоту: {device_id, freq_hz}. |  |
| `vfd_stop` | Стоп ПЧ: {device_id}. |  |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
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

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `gui`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

## Процесс `preprocessor`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `register_update` | GUI/процесс обновляет значение регистра | registers |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_config` |  |  |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
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

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `process_flip`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `process_grayscale`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `process_negative`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `region_splitter`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`

## Процесс `stitcher`

### Команды

| Команда | Описание | Теги |
|---|---|---|
| `catalog.plugins` | Каталог плагинов для GUI: форма регистра (FieldInfo dict) + порты + команды, без plugin-кода | system |
| `config.reload` | Применить секции observability и/или telemetry (логи, sink'и, publisher-gate, троттл) на лету | system |
| `diag.thread_raise` | Диагностика: поднять поток, бросающий RuntimeError — проверка threading.excepthook | diagnostics, system |
| `diag.warn` | Диагностика: позвать warnings.warn — проверка warnings.showwarning | diagnostics, system |
| `flush_stats` |  | stats |
| `get_metric` |  | stats |
| `get_metrics` |  | stats |
| `health.report` | Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости | health, system |
| `health.status` | Текущий снапшот здоровья процесса (status/errors/last_error) | health, system |
| `introspect.capabilities` | Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers | system |
| `introspect.executors` | Именованные исполнители процесса (ExecutorManager): тип, источник, владение, рабочие потоки | system |
| `introspect.handlers` | Router message-handlers + команды CommandManager процесса | system |
| `introspect.memory` | Инвентарь памяти процесса: SHM/пул/очереди (статистика, чего нет даже у GUI) | system |
| `introspect.observability` | Readback logger/error/stats: пороги и каналы + потери (buffer.dropped_by_channel, errors_to_floor) | system |
| `introspect.plugins` | Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover) | system |
| `introspect.queues` | Глубины очередей процесса (backpressure) | system |
| `introspect.registers` | Регистры процесса (имена + поля) из RegistersManager | system |
| `introspect.router_stats` | Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение) | system |
| `introspect.status` | Имя процесса, статус, воркеры (имена + статусы), cv_threads (потоки OpenCV, None без cv2) | system |
| `introspect.telemetry` | Readback телеметрийного gate: эффективная publish-секция + per-метрика (enabled, interval) | system |
| `log.tail.subscribe` | Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push) | system |
| `log.tail.unsubscribe` | Снять подписку на tail логов процесса | system |
| `logger.sink.disable` | Алиас observability.sink.disable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.enable` | Алиас observability.sink.enable (имя до 5.10; охват тот же — три плоскости) | system |
| `logger.sink.tail` | Алиас observability.sink.tail (имя до 5.10) | system |
| `observability.persist` | Сохранить рантайм-правки наблюдаемости в спутник рецепта (слой L2) | system |
| `observability.sink.disable` | Выключить приёмник по имени на плоскости manager=logger|error|stats (unregister_channel) | system |
| `observability.sink.enable` | Включить приёмник по имени на плоскости manager=logger|error|stats (register_channel) | system |
| `observability.sink.tail` | Прочитать последние N записей приёмника, хранящего их у себя (type=memory) | system |
| `observability.tail.subscribe` | Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record) | system |
| `observability.tail.unsubscribe` | Снять подписку на live-хвост наблюдаемости процесса | system |
| `reset_metrics` |  | stats |
| `router.relay` | Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам) | system |
| `routing.probe` | Диагностика: отправить inner-билет соседу (peer→peer доставка после switch) | system |
| `routing.refresh` | Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1) | system |
| `set_enabled` | Включить/выключить ноду (bypass) | control |
| `stats_snapshot` |  | diagnostics, stats |
| `telemetry.reconfigure` | Рантайм-переконфигурация телеметрии: publisher-gate (publish) и/или троттл (throttle) | system |
| `wire.configure` | Настроить wire middleware (SHM sender/receiver) | system |
| `wire.deconfigure` | Удалить wire middleware | system |
| `worker.create` | Создать воркер в процессе | system |
| `worker.drain` | Дренаж воркера (пауза+дождаться кадра); remove=True → drain→detach→stop | system |
| `worker.pause_all` | Поставить все прикладные воркеры процесса на паузу | system |
| `worker.remove` | Удалить воркер из процесса | system |
| `worker.restart` | Перезапустить воркер | system |
| `worker.resume_all` | Возобновить все прикладные воркеры процесса | system |
| `worker.start` | Запустить остановленный воркер | system |
| `worker.stop` | Остановить воркер (без удаления) | system |
| `worker.update` | Перенастроить воркер (приоритет/интервал) | system |

### Router-handlers (события, не команды)

`shm_reclaim`, `shm_release`, `state.changed`
