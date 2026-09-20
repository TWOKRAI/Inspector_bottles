# Инвентарь точек `_log_error` / `log_error` — шаг 1 задачи Task 1.3

> Рабочий список для реализации Task 1.3 фазы Ф1 плана
> [`observability-closure`](./phase-1-invisible-failures.md). Составлен **только чтением кода**
> (AST + `grep`), без семантического поиска: qex/Ollama на момент сбора не запущены.

**Дата:** 2026-08-31 · **Ветка:** `feat/observability-closure` · **Коммит:** `97fe2123`

## Как считал

1. `grep -rn` по четырём деревьям (`multiprocess_framework`, `multiprocess_prototype`,
   `Services`, `Plugins`), исключены каталоги `tests/`/`test/` и файлы `test_*.py`.
2. Поверх грепа — обход AST каждого файла: берутся **узлы вызова** `Call`, у которых
   `func` — атрибут `_log_error` или `log_error`. Это отсекает определения методов и
   упоминания в докстрингах, которые греп считает наравне с вызовами.
3. Для каждой точки из AST снят **структурный контекст**: класс и функция, тип
   пойманного исключения, условие ветки `if`/`else`, наличие `return False` в функции,
   и соседние вызовы `report_error` / `_track_error` / `track_error` в той же функции
   с расстоянием в строках.
4. Классификация — ручная, по структуре (тип `except`, условие ветки, что теряется при
   отказе), **не по тексту сообщения**. Спорные вынесены в класс C с причиной.

## Числа

Три разных числа, и путать их нельзя:

| Что считаем | Число |
|---|---|
| Строк с `_log_error(` по грепу | 260 |
| — из них определения `def _log_error` | 8 |
| — из них упоминания в докстрингах | 2 |
| **Вызовов `_log_error(`** | **250** |
| Строк с `.log_error(` по грепу | 66 |
| — из них упоминание в докстринге (`process_module/plugins/base.py:200`) | 1 |
| **Вызовов `.log_error(`** (`ctx.`, `self._services.`, `self._logger.`, `log.`) | **65** |
| **ВСЕГО точек вызова** | **315** |

Число **252** из постановки задачи — это `250 + 2 докстринга`, то есть греп по
`_log_error(` за вычетом определений. Оно **не включает 65 вызовов `.log_error(`**, а
именно в них живёт почти весь слой плагинов (в `Plugins` из 33 точек `_log_error` только
одна) — и именно `.log_error` стоит в трёх из четырёх адресов, названных спекой Task 1.3
(`plugin_orchestrator` ×3, `capture/plugin.py:288`). Число **226** из текста плана
совпадает с количеством точек во фреймворке (`226` из 315) — совпадение, а не то же
измерение.

### По классам

| Класс | Точек | Доля |
|---|---|---|
| **A** — отказ подсистемы, обязан попасть в плоскость ошибок | 240 | 76% |
| **B** — ошибка обработки данных / ожидаемая ветка, остаётся логом | 51 | 16% |
| **C** — спорные, решение неочевидно | 14 | 4% |
| **W** — обёртки/транзит (перекладывают чужое сообщение, своего события нет) | 10 | 3% |
| **Всего** | **315** | |

`W` выделен отдельно намеренно: это `ObservableMixin.log_error`, `ProcessIO.log_error`,
`RecipeManager._log_error` и подобные — у них нет своего события, они пересылают чужое.
Скрипт, считающий 315 точек «событиями», отнёс бы их в A или B и завысил бы обе цифры.

### По каталогам

| Каталог | A | B | C | W | Всего |
|---|---|---|---|---|---|
| `multiprocess_framework` | 189 | 34 | 12 | 8 | 243 |
| `multiprocess_prototype` | 15 | 3 | 1 | 2 | 21 |
| `Services` | 14 | 3 | 1 | 0 | 18 |
| `Plugins` | 22 | 11 | 0 | 0 | 33 |

---

## Класс A — отказы подсистем (240 точек)

Колонка «разъём сейчас» отвечает на вопрос, видит ли отказ плоскость ошибок **уже**:
`только лог` — точка невидима для `errors.log`/health/breaker; `двойной` — рядом уже
стоит `report_error`/`_track_error`, то есть работа по этой точке не «подключить», а
«убрать вторую строку» (см. раздел «Двойные разъёмы»).

### A-P1 — первоочередные (81)

Отбор: точки из спеки Task 1.3, отказы подъёма (boot/initialize/create/start),
недоступность ресурса ОС (сокет, SHM, камера, порт), потеря данных и ослепление самой
плоскости наблюдаемости.

| файл:строка | контекст | триггер | разъём сейчас | почему A |
|---|---|---|---|---|
| `Plugins/control/robot_control/plugin.py:348` | `RobotControlPlugin._write_verdict` | `if: not self._verdict_gap_reported` | только лог | вердикт не записан — плоскость документов не настроена |
| `Plugins/hub/device_hub/plugin.py:401` | `DeviceHubPlugin._ensure_device_workers` | `else: ok` | двойной: разные ветки (проверено) — на ветке `ok is False` report_error НЕТ | create_worker вернул False — воркер устройства не поднялся |
| `Plugins/io/frame_saver/plugin.py:354` | `FrameSaverPlugin._on_write_error` | `if: self._error_streak == 1 or self._error_streak % _ERROR_LOG_EVERY =` | только лог | серия отказов записи кадров (streak) — подсистема сохранения не работает |
| `Plugins/io/robot_draw/plugin.py:296` | `RobotDrawPlugin._forwarder_loop` | `else: result.get("status") == "ok"` | двойной: разные ветки (проверено) — на ветке `status != ok` report_error НЕТ | хаб вернул статус != ok — отказ по коду, НЕ исключение |
| `Plugins/io/robot_io/plugin.py:259` | `RobotIoPlugin._forwarder_loop` | `else: result.get("status") == "ok"` | двойной: разные ветки (проверено) — на ветке `status != ok` report_error НЕТ | хаб вернул статус != ok — отказ по коду, НЕ исключение |
| `Plugins/io/telemetry_sink/plugin.py:121` | `TelemetrySinkPlugin.start` | `if: ctx.state_proxy is None` | только лог | ctx.state_proxy is None — плагин остаётся no-op, подсистема не поднялась |
| `Plugins/processing/segmentation/plugin.py:103` | `SegmentationPlugin._init_model` | `except ImportError` | только лог | зависимость mediapipe отсутствует, _init_model → False (passthrough) |
| `Plugins/processing/segmentation/plugin.py:111` | `SegmentationPlugin._init_model` | `if: model_path is None` | только лог | файл модели не найден, _init_model → False (passthrough) |
| `Plugins/sources/capture/plugin.py:288` | `CapturePlugin._start_capture` | `else: self._cap.isOpened()` | только лог | камера не открылась (else от isOpened) — точка приёмки Task 1.3 |
| `Services/auth/audit_writer.py:256` | `AuditWriter._write_batch` | `except Exception` | только лог | запись аудита в SQLite не удалась — журнал аудита теряется |
| `Services/hikvision_camera/plugin/plugin.py:137` | `HikvisionCameraPlugin.configure` | прямой вызов | только лог | колбэк on_error драйвера камеры — любой отказ SDK приезжает сюда |
| `Services/hikvision_camera/plugin/plugin.py:150` | `HikvisionCameraPlugin.start` | `if: self._auto_start` | только лог | auto_start захвата не удался — камера не поднялась |
| `Services/ml_inference/plugin/plugin.py:279` | `MLInferencePlugin._load_selected_model` | `except Exception` | только лог | модель не загружена — возможность пропала |
| `Services/modbus/plugin/plugin.py:134` | `ModbusPlugin._register_channel` | `except Exception` | только лог | канал не зарегистрирован — маршрут не поднялся |
| `Services/modbus/plugin/plugin.py:225` | `ModbusPlugin._on_error` | прямой вызов | только лог | колбэк on_error драйвера — любой отказ соединения приезжает сюда |
| `Services/phone_gateway/plugin/plugin.py:195` | `PhoneCameraPlugin._start_server` | `except OSError` | только лог | HTTP-сервер не поднялся на порту (OSError) — сокет не забиндился |
| `multiprocess_framework/modules/app_module/orchestrator.py:267` | `GenericProcessManagerApp._fan_out` | `except Exception` | только лог | правка наблюдаемости не роздана детям — конфиг не применился |
| `multiprocess_framework/modules/channel_routing_module/buffers/async_sender_buffer.py:170` | `AsyncSenderBuffer._worker` | `except Exception` | только лог | send_fn канала упал — плоскость доставки теряет запись |
| `multiprocess_framework/modules/channel_routing_module/buffers/async_sender_buffer.py:175` | `AsyncSenderBuffer._worker` | `except Exception` | только лог | воркер асинхронного отправителя упал |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:364` | `ChannelRoutingManager._rollback_to` | `if: previous is None` | только лог | откат невозможен — принятого конфига не было |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:379` | `ChannelRoutingManager._rollback_to` | `except Exception` | только лог | ОТКАТ НЕ УДАЛСЯ — реестр каналов в неизвестном состоянии |
| `multiprocess_framework/modules/frontend_module/application/process_attached_frontend.py:61` | `-.run_process_attached_frontend` | `if: not fm.initialize()` | только лог | fm.initialize() вернул False — GUI не поднялся |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:185` | `ProcessRegistry._create_process` | `except Exception` | только лог | процесс не создан |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:224` | `ProcessRegistry.start_all` | `except Exception` | только лог | процесс не стартовал |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:275` | `ProcessRegistry.stop_one` | `if: alive and self.logger` | только лог | процесс жив после kill — остановка НЕ подтверждена |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:371` | `ProcessRegistry.stop_many` | `if: alive and self.logger` | только лог | процесс жив после kill — остановка НЕ подтверждена |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:395` | `ProcessRegistry.stop_all` | `if: survivors and self.logger` | только лог | процессы выжили после полной эскалации |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:744` | `ProcessMonitor._run_iteration` | `except Exception` | только лог | цикл монитора упал — надзор ослеп |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:964` | `ProcessMonitor._handle_dead_process` | `if: new_status == "crashed"` | только лог | процесс упал, авто-рестарт отключён |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1071` | `ProcessMonitor._check_heartbeat_timeout` | `else: policy.enabled and policy.restart_on_unresponsive` | только лог | процесс не отвечает, авто-рестарт отключён |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1261` | `ProcessMonitor._try_auto_restart` | `if: count >= max_retries` | только лог | превышен лимит рестартов — процесс больше не поднимут |
| `multiprocess_framework/modules/process_manager_module/process/observability_broker.py:283` | `ObservabilitySubscriptionBroker._fan_out` | `except Exception` | только лог | подписка наблюдаемости не роздана — плоскость ослепла |
| `multiprocess_framework/modules/process_manager_module/process/observability_broker.py:344` | `ObservabilitySubscriptionBroker._own_tail` | `except Exception` | только лог | свой хвост не поставлен — плоскость ослепла |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:578` | `ProcessManagerProcess._cmd_process_create` | `except Exception` | только лог | автостарт процесса не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:946` | `ProcessManagerProcess._cmd_wire_setup` | `except Exception` | только лог | SHM-аллокация для wire не удалась |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2671` | `ProcessManagerProcess._log_redelivery` | `else: delivered` | только лог | досылка команды НЕ доставлена — команда потеряна |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3251` | `ProcessManagerProcess._handle_critical_error` | `else: error_manager` | только лог | критическая ошибка при ОТСУТСТВУЮЩЕМ error_manager — фолбэк там, где плоскость мертва |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3331` | `ProcessManagerProcess._boot_create_and_start` | прямой вызов | только лог | boot: создание процесса не удалось |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3419` | `ProcessManagerProcess.shutdown` | `if: isinstance(stop_results, dict)` | только лог | дети выжили после shutdown — смерть не подтверждена |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3547` | `ProcessManagerProcess.restart_process` | `if: not process` | только лог | процесс не пересоздан при рестарте |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3769` | `ProcessManagerProcess.apply_topology` | `if: not_ready` | двойной: разные ветки (проверено) — track_error только в `except` на 3827 | процессы умерли на старте (initialize-провал) |
| `multiprocess_framework/modules/process_module/core/process_module.py:285` | `ProcessModule.initialize` | `except Exception` | только лог | initialize процесса провален — процесс не поднялся |
| `multiprocess_framework/modules/process_module/core/process_module.py:286` | `ProcessModule.initialize` | `except Exception` | только лог | вторая строка того же инцидента (трасса) — дубль по построению |
| `multiprocess_framework/modules/process_module/core/process_module.py:514` | `ProcessModule._apply_boot_observability_layers` | `except Exception` | только лог | слои наблюдаемости не применены на старте |
| `multiprocess_framework/modules/process_module/core/process_module.py:786` | `ProcessModule._create_workers_from_config` | `except Exception` | только лог | воркер не создан из конфига |
| `multiprocess_framework/modules/process_module/generic/data_receiver.py:166` | `DataReceiver._note_lag_drops` | прямой вызов | только лог | исполнитель не успевает — коллекции выброшены (потеря данных) |
| `multiprocess_framework/modules/process_module/generic/data_receiver.py:193` | `DataReceiver.on_items_ready` | `except queue.Full` | только лог | очередь pipeline переполнена — перегрузка |
| `multiprocess_framework/modules/process_module/generic/generic_process.py:114` | `GenericProcess._init_data_pipeline` | `if: plugin.state != PluginState.RUNNING` | только лог | источник не поднят (state != RUNNING) — конвейер без входа |
| `multiprocess_framework/modules/process_module/generic/pipeline_executor.py:378` | `PipelineExecutor._on_plugin_fail` | `if: fails >= self._max_fails` | только лог | circuit breaker OPEN — плагин выключен из конвейера |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:157` | `PluginOrchestrator.boot` | `if: missing` | только лог | REQUIRES не удовлетворены — плагин пропущен (точка спеки) |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:180` | `PluginOrchestrator.boot` | `except Exception` | только лог | configure плагина упал — плагин не поднялся (точка спеки) |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:202` | `PluginOrchestrator.boot` | `except Exception` | только лог | start плагина упал — плагин не поднялся (точка спеки) |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:355` | `PluginOrchestrator._init_registers` | `except Exception` | только лог | RegistersManager не инициализирован |
| `multiprocess_framework/modules/process_module/generic/source_producer.py:138` | `SourceProducer.run_loop` | `except NotImplementedError` | двойной: разные ветки (проверено) — на ветке NotImplementedError report_error НЕТ | нет produce() → stop_event.set(), источник встал НАВСЕГДА; report_error на этой ветке НЕТ |
| `multiprocess_framework/modules/process_module/plugins/base.py:1563` | `ProcessModulePlugin._auto_register_commands` | `if: method is None` | только лог | объявленная команда не найдена у плагина — команда молча не подключена |
| `multiprocess_framework/modules/router_module/channels/queue_channel.py:208` | `QueueChannel._listen_loop` | `except Exception` | только лог | listen-цикл канала упал — канал ослеп |
| `multiprocess_framework/modules/router_module/channels/socket_channel.py:132` | `SocketChannel.start` | `except OSError` | только лог | bind/listen не удался → start() возвращает False (точка спеки) |
| `multiprocess_framework/modules/router_module/core/_receiver.py:156` | `AsyncReceiver._worker` | `except Exception` | только лог | воркер приёмника упал — приём встал |
| `multiprocess_framework/modules/router_module/core/_sender.py:182` | `AsyncSender._worker` | `except Exception` | только лог | воркер отправителя упал — отправка встала |
| `multiprocess_framework/modules/router_module/core/router_manager.py:474` | `RouterManager.initialize` | `except Exception` | только лог | initialize RouterManager провален |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:488` | `FrameShmMiddleware._note_loan_exhausted` | `if: n == 1 or n % _PICKLE_WARN_EVERY == 0` | только лог | free-list исчерпан — кадр дропнут (потеря данных) |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:636` | `FrameShmMiddleware.restore_frame` | `if: self._restore_fail_count == 1 or self._restore_fail_count % _RESTO` | только лог | кадр не восстановлен — дроп (потеря данных) |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:756` | `FrameShmMiddleware._allocate_shm` | `except Exception` | только лог | аллокация SHM не удалась |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:143` | `SharedResourcesManager.initialize` | `except Exception` | только лог | initialize SRM провален |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:220` | `SharedResourcesManager.register_process` | `except Exception` | только лог | процесс не зарегистрирован в SRM |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:315` | `SharedResourcesManager.reinitialize_in_child` | `except Exception` | только лог | реинициализация в ребёнке провалена — ребёнок без ресурсов |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:123` | `MemoryManager.initialize` | `except Exception` | только лог | initialize MemoryManager провален |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:167` | `MemoryManager.reinitialize_handles` | `if: shm is None` | только лог | SHM-сегмент не открывается — ресурс недоступен |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:199` | `MemoryManager.create_memory_dict` | `except Exception` | только лог | create_memory_dict провален — SHM не выделена |
| `multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:286` | `DeltaDispatcher._flusher_loop` | `except Exception` | только лог | flush-тик коалесцирования упал — дельты не уходят |
| `multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:396` | `DeltaDispatcher._send_state_changed` | `except Exception` | только лог | state.changed не доставлен подписчику |
| `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:1008` | `StateProxy._resync` | `except Exception` | только лог | ресинк не отправлен — прокси остаётся рассинхронизированным |
| `multiprocess_framework/modules/statistics_module/core/stats_manager.py:468` | `StatsManager._setup_channels` | `if: not self._channel_registry.names()` | только лог | у плоскости статистики не осталось приёмников — плоскость ослепла |
| `multiprocess_framework/modules/worker_module/core/worker_manager.py:58` | `WorkerManager.initialize` | `except Exception` | только лог | initialize WorkerManager провален (точка спеки) |
| `multiprocess_framework/modules/worker_module/core/worker_manager.py:131` | `WorkerManager.remove_worker` | `if: not stopped` | только лог | воркер не удалён — поток не остановился (точка спеки) |
| `multiprocess_framework/modules/worker_module/lifecycle/worker_lifecycle.py:162` | `WorkerLifecycle.stop_worker` | `if: thread.is_alive()` | только лог | воркер не остановился за таймаут join (точка спеки) |
| `multiprocess_framework/modules/worker_module/lifecycle/worker_lifecycle.py:228` | `WorkerLifecycle._worker_wrapper` | `except Exception` | только лог | тело воркера упало — воркер мёртв (точка спеки) |
| `multiprocess_prototype/frontend/app.py:572` | `-.run_gui` | `except Exception` | двойной: разные ветки (проверено) — _track_error только в блоке валидации топологии | подсистема авторизации не поднялась |
| `multiprocess_prototype/frontend/app.py:653` | `-.run_gui` | `except Exception` | двойной: разные ветки (проверено) — _track_error только в блоке валидации топологии | AppServices factory упала — сервисы GUI не поднялись |
| `multiprocess_prototype/frontend/headless_process.py:68` | `HeadlessGuiProcess._init_application_threads` | `if: not self.worker_manager` | только лог | нет worker_manager — data-очередь не поднята |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:494` | `RecipesPresenter._on_apply_result` | `if: isinstance(result, dict) and result.get("success")` | только лог | процессы не запустились после apply |

### A-P2 — остальные отказы подсистем (159)

| файл:строка | контекст | триггер | разъём сейчас | почему A |
|---|---|---|---|---|
| `Plugins/calibration/camera_robot/plugin.py:278` | `CameraRobotCalibrationPlugin._dispatch` | `except Exception` | двойной (тесная пара, 1 стр.) | действие калибровки упало целиком (except Exception в _dispatch) |
| `Plugins/hub/device_hub/plugin.py:300` | `DeviceHubPlugin._process_conn_queue` | `except Exception` | двойной (тесная пара, 1 стр.) | операция с устройством (connect/disconnect) упала |
| `Plugins/hub/device_hub/plugin.py:408` | `DeviceHubPlugin._ensure_device_workers` | `except Exception` | двойной (тесная пара, 1 стр.) | воркер устройства не создан (исключение) |
| `Plugins/io/database/plugin.py:183` | `DatabasePlugin._do_flush` | `except Exception` | двойной (тесная пара, 3 стр.) | вставка в БД не удалась — хранилище недоступно |
| `Plugins/io/drawing_io/plugin.py:178` | `DrawingIoPlugin._do_save` | `except Exception` | двойной (тесная пара, 1 стр.) | запись файла не удалась (ФС недоступна) |
| `Plugins/io/frame_saver/plugin.py:283` | `FrameSaverPlugin._write_sidecar` | `except (OSError, TypeError, ValueError)` | двойной (тесная пара, 1 стр.) | sidecar не записан — OSError на ФС |
| `Plugins/io/frame_saver/plugin.py:347` | `FrameSaverPlugin._cleanup_old_days` | `except OSError` | двойной (тесная пара, 1 стр.) | retention не смог удалить каталог — OSError |
| `Plugins/io/robot_draw/plugin.py:169` | `RobotDrawPlugin.process` | `except queue.Full` | двойной (тесная пара, 1 стр.) | очередь заданий полна — задание потеряно |
| `Plugins/io/robot_draw/plugin.py:280` | `RobotDrawPlugin._forwarder_loop` | `except Exception` | двойной (тесная пара, 2 стр.) | хаб робота недоступен (исключение) |
| `Plugins/io/robot_io/plugin.py:242` | `RobotIoPlugin._forwarder_loop` | `except Exception` | двойной (тесная пара, 3 стр.) | хаб робота недоступен (исключение) |
| `Plugins/processing/edge_detection/plugin.py:195` | `EdgeDetectionPlugin.process` | `except FileNotFoundError` | двойной (тесная пара, 1 стр.) | файл модели не найден — возможность пропала |
| `Plugins/processing/pixel_to_robot/plugin.py:107` | `PixelToRobotPlugin._load_calibration` | `except Exception` | двойной (тесная пара, 1 стр.) | калибровка не прочитана — конфиг не применился |
| `Plugins/sinks/modbus_sink/plugin.py:206` | `ModbusSinkPlugin._write_item` | `except (ModbusDriverError, ValueError, TypeError)` | двойной (тесная пара, 1 стр.) | запись в устройство не удалась |
| `Services/auth/manager.py:354` | `AuthManager.login` | `except Exception` | только лог | сессия не открыта — трекер сессий недоступен |
| `Services/auth/manager.py:367` | `AuthManager.logout` | `except Exception` | только лог | сессия не закрыта — трекер сессий недоступен |
| `Services/hikvision_camera/plugin/plugin.py:264` | `HikvisionCameraPlugin._apply_parameters_from_register` | `if: hasattr(self._camera, "_camera") and self._camera._camera is not N` | только лог | параметры из register не применены — конфиг не применился |
| `Services/modbus/channels/modbus_channel.py:117` | `ModbusChannel.send` | `except ModbusDriverError` | только лог | команда Modbus не прошла — устройство/канал недоступны |
| `Services/modbus/plugin/plugin.py:146` | `ModbusPlugin._unregister_channel` | `except Exception` | только лог | канал не снят с регистрации |
| `Services/modbus/plugin/plugin.py:164` | `ModbusPlugin.process` | `except (ModbusDriverError, ValueError, TypeError)` | только лог | запись в устройство не удалась |
| `Services/sql/core/sql_manager.py:75` | `SQLManager.initialize` | `except Exception` | двойной (тесная пара, 1 стр.) | SQLManager.initialize упал |
| `multiprocess_framework/modules/app_module/orchestrator.py:98` | `GenericProcessManagerApp.shutdown` | `except Exception` | только лог | watcher наблюдаемости не остановлен — ресурс не освобождён |
| `multiprocess_framework/modules/app_module/orchestrator.py:105` | `GenericProcessManagerApp.shutdown` | `except Exception` | только лог | L2-watcher не остановлен — ресурс не освобождён |
| `multiprocess_framework/modules/app_module/orchestrator.py:112` | `GenericProcessManagerApp.shutdown` | `except Exception` | только лог | state_store не остановлен |
| `multiprocess_framework/modules/app_module/orchestrator.py:211` | `GenericProcessManagerApp._start_recipe_observability_watcher` | `except Exception` | только лог | прежний L2-watcher не остановлен — риск двух watcher'ов |
| `multiprocess_framework/modules/app_module/orchestrator.py:353` | `GenericProcessManagerApp._active_recipe_from_manifest` | `except Exception` | только лог | манифест не прочитан — свой слой не собран |
| `multiprocess_framework/modules/channel_routing_module/core/channel_registry.py:70` | `ChannelRegistry.register` | `if: not isinstance(channel, IChannel)` | только лог | канал не реализует IChannel → не зарегистрирован |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:266` | `ChannelRoutingManager.initialize` | `except Exception` | только лог | initialize менеджера каналов провален |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:329` | `ChannelRoutingManager.reconfigure` | `except Exception` | только лог | reconfigure отвергнут — новый конфиг не применился |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:347` | `ChannelRoutingManager.reconfigure` | `except Exception` | только лог | reconfigure провален |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:501` | `ChannelRoutingManager.shutdown` | `except Exception` | только лог | shutdown менеджера каналов провален |
| `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:1178` | `ChannelRoutingManager._close_all_channels` | `except Exception` | только лог | канал не закрылся — ресурс не освобождён |
| `multiprocess_framework/modules/command_module/core/command_manager.py:133` | `CommandManager.initialize` | `except Exception` | двойной (тесная пара, 1 стр.) | initialize CommandManager провален |
| `multiprocess_framework/modules/command_module/core/command_manager.py:156` | `CommandManager.shutdown` | `except Exception` | двойной (тесная пара, 1 стр.) | shutdown CommandManager провален |
| `multiprocess_framework/modules/config_module/core/config_manager.py:68` | `ConfigManager.initialize` | `except Exception` | только лог | initialize ConfigManager провален |
| `multiprocess_framework/modules/config_module/core/config_manager.py:81` | `ConfigManager.shutdown` | `except Exception` | только лог | shutdown ConfigManager провален |
| `multiprocess_framework/modules/config_module/core/config_manager.py:164` | `ConfigManager.sync_config` | `except Exception` | только лог | sync_config провален — конфиг не применился |
| `multiprocess_framework/modules/config_module/core/config_manager.py:188` | `ConfigManager.load_config_from_storage` | `except Exception` | только лог | конфиг не загружен из хранилища |
| `multiprocess_framework/modules/console_module/core/console_manager.py:89` | `ConsoleManager.initialize` | `except Exception` | только лог | initialize ConsoleManager провален |
| `multiprocess_framework/modules/console_module/core/console_manager.py:109` | `ConsoleManager.shutdown` | `except Exception` | только лог | shutdown ConsoleManager провален |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:152` | `Dispatcher.initialize` | `except Exception` | двойной (тесная пара, 1 стр.) | initialize Dispatcher провален |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:183` | `Dispatcher.shutdown` | `except Exception` | двойной (тесная пара, 1 стр.) | shutdown Dispatcher провален |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:275` | `Dispatcher.register_handler` | `except Exception` | двойной (тесная пара, 1 стр.) | обработчик не зарегистрирован — маршрут не поднялся |
| `multiprocess_framework/modules/display_module/registry.py:336` | `DisplayRegistry.persist` | `except OSError` | только лог | реестр дисплеев не записан на диск (OSError) |
| `multiprocess_framework/modules/frontend_module/application/frontend_manager.py:113` | `FrontendManager.initialize` | `except Exception` | только лог | initialize FrontendManager провален |
| `multiprocess_framework/modules/frontend_module/application/frontend_manager.py:134` | `FrontendManager.shutdown` | `except Exception` | только лог | shutdown FrontendManager провален |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:106` | `ProcessRegistry._create_process` | `except Exception` | только лог | ConfigManager update провален — конфиг процесса не применился |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:269` | `ProcessRegistry.stop_one` | `except Exception` | только лог | kill процесса упал |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:359` | `ProcessRegistry.stop_many` | `except Exception` | только лог | kill процесса упал |
| `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:403` | `SystemLauncher._prepare_pid_registry` | `except Exception` | только лог | реап PID-реестра не удался |
| `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:446` | `SystemLauncher._cleanup_shm_at_startup` | `except Exception` | только лог | уборка объявленных SHM-сегментов не удалась |
| `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:473` | `SystemLauncher._cleanup_shm_at_startup` | `except Exception` | только лог | уборка осиротевших SHM по префиксу не удалась |
| `multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:582` | `SystemLauncher.stop` | `except Exception` | только лог | чистка PID-реестра при остановке не удалась |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1002` | `ProcessMonitor._broadcast_shm_reclaim` | `except Exception` | только лог | рассылка shm_reclaim упала — займы мёртвого читателя не сняты |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1392` | `ProcessMonitor._escalate_group_giveup` | прямой вызов | только лог | эскалация: группа сдана |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1509` | `ProcessMonitor._dispatch_due_restarts` | `except Exception` | только лог | отправка рестарта не удалась |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1513` | `ProcessMonitor._dispatch_due_restarts` | `else: sent` | только лог | рестарт НЕ отправлен |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1543` | `ProcessMonitor._check_recovery_timeouts` | прямой вызов | только лог | рестарт не подтвердился восстановлением к дедлайну |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:1678` | `ProcessMonitor._broadcast_status_change` | `except Exception` | только лог | рассылка смены статуса не удалась |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:355` | `ProcessManagerProcess._sweep_orphaned_log_dirs` | `except Exception` | только лог | sweep осиротевших каталогов логов упал |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:798` | `ProcessManagerProcess._observability_recipe_address` | `except Exception` | только лог | адрес рецепта не прочитан из конфига |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:825` | `ProcessManagerProcess._retarget_recipe_address` | `except Exception` | только лог | адрес рецепта не записан в конфиг |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:830` | `ProcessManagerProcess._retarget_recipe_address` | `except Exception` | только лог | ретаргет L2-watcher не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:981` | `ProcessManagerProcess._cmd_wire_setup` | `except Exception` | только лог | wire.configure не отправлен источнику |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:993` | `ProcessManagerProcess._cmd_wire_setup` | `except Exception` | только лог | wire.configure не отправлен приёмнику |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1033` | `ProcessManagerProcess._cmd_wire_teardown` | `except Exception` | только лог | wire.deconfigure не отправлен — ресурс не освобождён |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1177` | `ProcessManagerProcess._send_wire_configure` | `except Exception` | только лог | повторная выдача wire не удалась |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1416` | `ProcessManagerProcess._child_ready_event` | `except Exception` | только лог | ready_event ребёнка не прочитан |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1627` | `ProcessManagerProcess._run_child_action_after_ready` | `except Exception` | только лог | отложенное действие ready-gate упало |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1803` | `ProcessManagerProcess._rollback_to_snapshot` | `except Exception` | только лог | откат: stop_many не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1806` | `ProcessManagerProcess._rollback_to_snapshot` | `if: unstoppable` | только лог | откат: остановка НЕ подтверждена |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1820` | `ProcessManagerProcess._rollback_to_snapshot` | `except Exception` | только лог | откат: cleanup не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1828` | `ProcessManagerProcess._rollback_to_snapshot` | `except Exception` | только лог | откат: provision не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1836` | `ProcessManagerProcess._rollback_to_snapshot` | `else: self._topology_create(name, cfg)` | только лог | откат: create не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1838` | `ProcessManagerProcess._rollback_to_snapshot` | `except Exception` | только лог | откат: create упал с исключением |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1845` | `ProcessManagerProcess._rollback_to_snapshot` | `else: self._topology_start(name)` | только лог | откат: start не удался |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1847` | `ProcessManagerProcess._rollback_to_snapshot` | `except Exception` | только лог | откат: start упал с исключением |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1978` | `ProcessManagerProcess._broadcast_routing_refresh` | `except Exception` | только лог | рассылка routing refresh упала |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2321` | `ProcessManagerProcess._replay_telemetry_runtime_delta` | `except Exception` | только лог | доигрывание telemetry-дельты упало |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2379` | `ProcessManagerProcess._compose_own_recipe_layer` | `except Exception` | только лог | спутник рецепта не прочитан — свой слой не собран |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2474` | `ProcessManagerProcess._reset_observability_sessions` | `except Exception` | только лог | свой L3 наблюдаемости не сброшен |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2489` | `ProcessManagerProcess._reset_observability_sessions` | `except Exception` | только лог | рассылка сброса сессий не удалась |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2815` | `ProcessManagerProcess._forget_closed_session` | `except Exception` | только лог | снятие подписок закрытой сессии упало — подписки-сироты |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2873` | `ProcessManagerProcess._replay_observability_subscriptions` | `except Exception` | только лог | переигрывание подписок наблюдаемости упало |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2970` | `ProcessManagerProcess._cmd_process_relay` | `except Exception` | только лог | process.relay не доставлен |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3070` | `ProcessManagerProcess._cmd_telemetry_broadcast` | `except Exception` | только лог | адресный publish телеметрии упал |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3079` | `ProcessManagerProcess._cmd_telemetry_broadcast` | `except Exception` | только лог | fan-out publish телеметрии упал |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3134` | `ProcessManagerProcess._cmd_telemetry_broadcast` | `except Exception` | только лог | применение throttle телеметрии упало |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3237` | `ProcessManagerProcess._handle_process_command` | `except Exception` | только лог | ответ на process.command не отправлен |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3608` | `ProcessManagerProcess._send_worker_command` | `except Exception` | только лог | команда воркеру не отправлена |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3779` | `ProcessManagerProcess.apply_topology` | `if: cleanup_failures` | двойной: разные ветки (проверено) — track_error только в `except` на 3827 | cleanup не подтверждён — ghost-риск ресурсов |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3820` | `ProcessManagerProcess.apply_topology` | `except Exception` | двойной: одна ветка (проверено) — track_error@3827 в том же `except`, под `hasattr` | исключение в manager.apply — топология в неизвестном состоянии |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3996` | `ProcessManagerProcess._topology_stop_all` | `if: failed` | только лог | topology stop_all: остановка НЕ подтверждена |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:220` | `TopologyManager.apply` | `if: not result.get("success", True)` | двойной: разные ветки (проверено) — _track_error только во внешнем `except` | cleanup-команда неуспешна — старые ресурсы не освобождены |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:226` | `TopologyManager.apply` | `if: not result.get("success", True)` | двойной: разные ветки (проверено) — _track_error только во внешнем `except` | конструктивная команда топологии неуспешна — apply прерван |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:255` | `TopologyManager.apply` | `except Exception` | двойной (тесная пара, 1 стр.) | исключение apply топологии |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:422` | `TopologyManager._execute_command` | `except Exception` | двойной (тесная пара, 1 стр.) | исключение команды топологии |
| `multiprocess_framework/modules/process_module/commands/builtin_commands.py:2911` | `BuiltinCommands._cmd_observability_persist` | `except Exception` | только лог | L2-watcher не пере-вооружён после сохранения |
| `multiprocess_framework/modules/process_module/core/process_module.py:395` | `ProcessModule._uninstall_process_hooks` | `except Exception` | только лог | снятие процессных хуков не удалось |
| `multiprocess_framework/modules/process_module/core/process_module.py:465` | `ProcessModule._apply_boot_observability_layers` | `except Exception` | только лог | секция менеджеров не прочитана — пересборка слоёв пропущена |
| `multiprocess_framework/modules/process_module/core/process_module.py:481` | `ProcessModule._apply_boot_observability_layers` | `except Exception` | только лог | спутник рецепта не прочитан |
| `multiprocess_framework/modules/process_module/core/process_module.py:1056` | `ProcessModule._announce_ready` | `except Exception` | только лог | ready_event процесса не выставлен — ready-gate не увидит процесс |
| `multiprocess_framework/modules/process_module/generic/generic_process.py:307` | `GenericProcess._handle_shm_release` | `except Exception` | только лог | обработчик shm_release упал — сегменты не освобождены |
| `multiprocess_framework/modules/process_module/generic/generic_process.py:319` | `GenericProcess._handle_shm_reclaim` | `except Exception` | только лог | обработчик shm_reclaim упал — займы не сняты |
| `multiprocess_framework/modules/process_module/generic/pipeline_executor.py:337` | `PipelineExecutor._flush_releases` | `except Exception` | только лог | flush освобождений SHM не удался |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:83` | `PluginOrchestrator.load_and_configure_managers` | `except Exception` | только лог | configure_managers плагина упал |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:222` | `PluginOrchestrator.shutdown` | `except Exception` | только лог | shutdown плагина упал — ресурсы не освобождены |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:335` | `PluginOrchestrator._init_registers` | `except Exception` | только лог | схема регистра не зарегистрирована |
| `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:401` | `PluginOrchestrator._register_control_commands` | `except Exception` | только лог | control-команда set_enabled не зарегистрирована |
| `multiprocess_framework/modules/process_module/generic/source_producer.py:142` | `SourceProducer.run_loop` | `except Exception` | двойной: одна ветка (проверено) — report_error@148 в том же `except Exception` | produce() упал — итерация источника неуспешна |
| `multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py:145` | `ProcessLifecycle.shutdown` | `except Exception` | только лог | SRM не остановлен — SHM/ресурсы могли остаться |
| `multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py:247` | `ProcessLifecycle.shutdown` | `except Exception` | только лог | shutdown процесса провален |
| `multiprocess_framework/modules/process_module/plugins/base.py:330` | `PluginContext.write_document` | `except Exception` | только лог | документ не записан — плоскость документов недоступна |
| `multiprocess_framework/modules/process_module/state/process_state.py:55` | `ProcessState.register` | `except Exception` | только лог | состояние процесса не зарегистрировано в state-дереве |
| `multiprocess_framework/modules/process_module/state/process_state.py:88` | `ProcessState.update` | `except Exception` | только лог | состояние процесса не обновлено в state-дереве |
| `multiprocess_framework/modules/process_module/threads/system_threads.py:48` | `SystemThreads.stop` | `except Exception` | только лог | обработчик сообщений не остановлен |
| `multiprocess_framework/modules/recipe/manager.py:230` | `RecipeManager.duplicate` | `except OSError` | только лог | запись нового рецепта на диск не удалась (OSError) |
| `multiprocess_framework/modules/registers_module/core/manager.py:183` | `RegistersManager.set_field_value` | `except Exception` | только лог | send_callback регистра упал — значение не доставлено |
| `multiprocess_framework/modules/router_module/channels/queue_channel.py:138` | `QueueChannel.poll` | `except Exception` | только лог | poll канала упал |
| `multiprocess_framework/modules/router_module/channels/socket_channel.py:387` | `SocketChannel._drop_clients` | `except Exception` | только лог | колбэк закрытия сессии упал — сессия не убрана |
| `multiprocess_framework/modules/router_module/core/router_manager.py:398` | `RouterManager._report_send_error` | прямой вызов | двойной (тесная пара, 1 стр.) | отправка не удалась (эталонная пара с _track_error, точка спеки) |
| `multiprocess_framework/modules/router_module/core/router_manager.py:494` | `RouterManager.shutdown` | `except Exception` | только лог | shutdown RouterManager провален |
| `multiprocess_framework/modules/router_module/core/router_manager.py:1435` | `RouterManager.receive` | `except Exception` | только лог | receive упал |
| `multiprocess_framework/modules/router_module/core/router_manager.py:1520` | `RouterManager._poll_all_channels` | `except Exception` | только лог | poll канала упал — канал не читается |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:165` | `FrameShmMiddleware.__init__` | `if: cache_requested and not self._owner_incarnation` | только лог | cache_shm_handles без owner_incarnation — конфиг не применён |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:181` | `FrameShmMiddleware.__init__` | `if: zero_copy_requested and not self._cache_shm_handles` | только лог | zero_copy без кэша — конфиг не применён |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:390` | `FrameShmMiddleware.release_owned_memory` | `except Exception` | только лог | освобождение SHM не удалось |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:629` | `FrameShmMiddleware.restore_frame` | `except Exception` | только лог | SHM fallback не сработал |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:734` | `FrameShmMiddleware._allocate_shm` | `except Exception` | только лог | старый SHM не закрыт перед реаллокацией |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:155` | `SharedResourcesManager.shutdown` | `except Exception` | только лог | shutdown SRM провален |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:244` | `SharedResourcesManager.unregister_process` | `except Exception` | только лог | SHM процесса не освобождена при снятии регистрации |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:250` | `SharedResourcesManager.unregister_process` | `except Exception` | только лог | PSR-снятие регистрации не удалось |
| `multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py:256` | `SharedResourcesManager.unregister_process` | `except Exception` | только лог | конфиг процесса не удалён |
| `multiprocess_framework/modules/shared_resources_module/events/core/manager.py:72` | `EventManager.initialize` | `except Exception` | только лог | initialize EventManager провален |
| `multiprocess_framework/modules/shared_resources_module/events/core/manager.py:84` | `EventManager.shutdown` | `except Exception` | только лог | shutdown EventManager провален |
| `multiprocess_framework/modules/shared_resources_module/events/core/manager.py:100` | `EventManager.reinitialize` | `except Exception` | только лог | reinitialize EventManager провален |
| `multiprocess_framework/modules/shared_resources_module/events/core/manager.py:140` | `EventManager.emit_event` | `except Exception` | только лог | событие не отправлено через router |
| `multiprocess_framework/modules/shared_resources_module/events/core/manager.py:151` | `EventManager.emit_event` | `except Exception` | только лог | emit_event провален |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:134` | `MemoryManager.shutdown` | `except Exception` | только лог | shutdown MemoryManager провален |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:174` | `MemoryManager.reinitialize_handles` | `except Exception` | только лог | реинициализация хендлов провалена |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:348` | `MemoryManager.write_images` | `except Exception` | только лог | запись изображений в SHM не удалась |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:394` | `MemoryManager.read_images` | `except Exception` | только лог | чтение изображений из SHM не удалось |
| `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py:497` | `MemoryManager._safe_close_shm` | `except Exception` | только лог | close/unlink SHM не удался — сегмент утёк |
| `multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:330` | `DeltaDispatcher.stop_flusher` | `if: self._flusher is not None` | только лог | flusher не завершился за таймаут — поток завис |
| `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:1440` | `StateProxy._send` | `except Exception` | только лог | команда state не отправлена |
| `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:1525` | `StateProxy._send_sync` | `except Exception` | только лог | синхронный request() не прошёл |
| `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:1537` | `StateProxy._send_sync` | `except Exception` | только лог | синхронная отправка не прошла |
| `multiprocess_framework/modules/statistics_module/core/stats_manager.py:267` | `StatsManager.initialize` | `except Exception` | только лог | initialize StatsManager провален |
| `multiprocess_framework/modules/worker_module/core/worker_manager.py:68` | `WorkerManager.shutdown` | `except Exception` | только лог | shutdown WorkerManager провален (точка спеки) |
| `multiprocess_prototype/backend/state/adapters/display_state_adapter.py:119` | `DisplayStateAdapter.sync_domain_to_state` | `except Exception` | только лог | запись в state не удалась — state-подсистема недоступна |
| `multiprocess_prototype/backend/state/adapters/display_state_adapter.py:131` | `DisplayStateAdapter.sync_domain_to_state` | `except Exception` | только лог | запись в state не удалась — state-подсистема недоступна |
| `multiprocess_prototype/backend/state/adapters/service_state_adapter.py:113` | `ServiceStateAdapter.sync_domain_to_state` | `except Exception` | только лог | запись в state не удалась — state-подсистема недоступна |
| `multiprocess_prototype/frontend/app.py:297` | `-.run_gui` | `if: _report.errors` | двойной: одна ветка (проверено) — N строк лога в цикле + ОДИН _track_error после цикла | ошибки валидации топологии на старте — конфиг не применится |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:246` | `RecipesPresenter.on_create` | `except OSError` | только лог | запись рецепта на диск не удалась (OSError) |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:433` | `RecipesPresenter.on_set_active` | `if: self._apply_topology_fn is not None` | только лог | рецепт не прочитан — ресурс недоступен |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:458` | `RecipesPresenter.on_set_active` | `except Exception` | только лог | apply не отправлен — IPC не сработал |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:512` | `RecipesPresenter._on_apply_result` | прямой вызов | только лог | apply_topology провален |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:546` | `RecipesPresenter._rollback_activation` | `except Exception` | только лог | откат активации не удался — состояние рассогласовано |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:552` | `RecipesPresenter._rollback_activation` | `except Exception` | только лог | компенсирующая команда не удалась — состояние рассогласовано |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:603` | `RecipesPresenter.on_save` | `except Exception` | только лог | сохранение рецепта не удалось |

---

## Класс C — спорные (14 точек)

| файл:строка | контекст | триггер | в чём спор |
|---|---|---|---|
| `Services/sql/core/sql_manager.py:320` | `SQLManager.execute_command` | `except Exception` | execute_command: и кривой SQL вызывающего, и мёртвая БД — по коду не различимо |
| `multiprocess_framework/modules/config_module/core/config_manager.py:155` | `ConfigManager.sync_config` | `if: config is None` | 'config not found': и ошибка вызывающего, и отсутствие конфига подсистемы |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:264` | `ProcessRegistry.stop_one` | `if: process.is_alive()` | 'Force killing' — штатная ступень эскалации останова, не отказ; уровень ERROR спорен |
| `multiprocess_framework/modules/process_manager_module/core/process_registry.py:354` | `ProcessRegistry.stop_many` | `if: self.logger` | 'Force killing' — штатная ступень эскалации останова, не отказ; уровень ERROR спорен |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:1751` | `ProcessManagerProcess._collect_partial_new` | `except Exception` | fallback-парсинг blueprint: разбор данных, но внутри аварийной процедуры отката |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3221` | `ProcessManagerProcess._handle_process_command` | `except Exception` | исключение при исполнении команды: отказ подсистемы и кривой аргумент в одной ветке |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3514` | `ProcessManagerProcess.restart_process` | `if: not config` | 'No saved config' при рестарте: и отсутствие конфига, и ошибка вызывающего |
| `multiprocess_framework/modules/process_module/plugins/base.py:599` | `PluginContext._stats_call` | `except Exception` | метрика не записана: одна метрика или мёртвая плоскость статистики — не различимо |
| `multiprocess_framework/modules/recipe/manager.py:209` | `RecipeManager.duplicate` | `except (yaml.YAMLError, OSError)` | чтение рецепта: OSError (ресурс) и YAMLError (данные) в одном except — классы слиты |
| `multiprocess_framework/modules/recipe/manager.py:322` | `RecipeManager.read_recipe` | `except (yaml.YAMLError, OSError)` | чтение рецепта: OSError и YAMLError в одном except — классы слиты |
| `multiprocess_framework/modules/router_module/channels/socket_channel.py:341` | `SocketChannel._handle_line` | `except Exception` | on_inbound упал: структурно ошибка обработки (B), но входящее сообщение потеряно целиком; спека называет её точкой Task 1.3 |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:363` | `FrameShmMiddleware._note_pickle_fallback` | `if: self.frame_pickle_fallbacks == 1 or self.frame_pickle_fallbacks % ` | pickle-fallback: деградация производительности, отказа нет; уровень ERROR спорен |
| `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:558` | `FrameShmMiddleware.reclaim_reader` | `if: reclaimed` | реклейм займов мёртвого читателя — по смыслу успешное восстановление, ERROR спорен |
| `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:402` | `RecipesPresenter.on_set_active` | `except Exception` | непойманное исключение команды: отказ подсистемы и ошибка данных в одной ветке |

---

## Класс B — обработка данных и ожидаемые ветки (51 точек)

Полный список не нужен — эти точки остаются логом. Числа по каталогам:

| Каталог | Точек B |
|---|---|
| `multiprocess_framework` | 34 |
| `multiprocess_prototype` | 3 |
| `Services` | 3 |
| `Plugins` | 11 |

Характерные примеры:

| файл:строка | контекст | триггер | почему B |
|---|---|---|---|
| `Plugins/processing/blur/plugin.py:50` | `BlurPlugin.configure` | `if: kernel_size <= 0` | kernel_size<=0 от пользователя, взят дефолт |
| `Plugins/_shared/fanin/inspector_manager.py:77` | `InspectorManager.on_item` | `if: region_name in self._buffer[key]` | дубликат region_name во входных данных |
| `multiprocess_framework/modules/display_module/registry.py:369` | `DisplayRegistry.load` | `if: not isinstance(displays_raw, list)` | неверная форма YAML |
| `multiprocess_framework/modules/router_module/channels/socket_channel.py:185` | `SocketChannel.send` | `except (TypeError, ValueError)` | JSON не сериализовался — кривой payload |
| `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:1304` | `StateProxy._deserialize_deltas` | `except Exception` | дельты не десериализовались — кривой payload |
| `multiprocess_framework/modules/process_module/generic/pipeline_executor.py:369` | `PipelineExecutor._on_plugin_fail` | прямой вызов | plugin.process() на одном элементе |
| `multiprocess_framework/modules/process_module/plugins/base.py:1460` | `ProcessModulePlugin._do_configure` | `if: self.state != PluginState.IDLE` | configure() в неверном состоянии — контрактная ветка |
| `multiprocess_framework/modules/chain_module/core/error_policy.py:51` | `-.apply_on_error_policy` | `if: step.on_error == "fail_region"` | объявленная политика on_error=fail_region на упавшей ноде |
| `multiprocess_framework/modules/process_module/generic/data_receiver.py:204` | `DataReceiver.on_items_ready` | `except queue.Full` | дроп на остановке (stop_event) — штатная ветка |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:228` | `ProcessManagerProcess._log_active_feature_flags` | `except Exception` | диагностическая печать feature-флагов |

---

## Двойные разъёмы — `log_error` и `report_error`/`_track_error` в одной функции

Найдено **46** точек в **32** функциях. Эталон из постановки задачи
(`router_manager.py:398-399`) — одна из них; остальные 45 были не названы.

Почему это важно именно так, а не «одна лишняя строка»:
`HealthState.report_error` (`process_module/health/state.py:231`) под своим дросселем
пишет **и** строку `[health] …` в журнал, **и** запись в плоскость ошибок
(`_safe_track`). Значит соседний `log_error` в той же ветке даёт **вторую** строку об
одном инциденте — ровно то, что критерий Task 1.3 называет «одна строка вместо трёх».

При этом парность у плагинов **не случайна**: она поставлена сознательно по ADR-PM-030 /
задаче C2 (докстринг `PluginContext.health`, `process_module/plugins/base.py:190-210`
прямо разводит `ctx.log_error` = диагностическая строка и `ctx.health.report_error` =
инцидент). Страж «один разъём на точку» из шага 2 Task 1.3 покраснеет на всех этих
адресах — под него нужен либо whitelist с причиной, либо снятие второй строки; решение
стоит принять **до** написания стража, иначе его придётся ослаблять задним числом.

| точка `log_error` | сосед | Δ строк | вердикт |
|---|---|---|---|
| `Plugins/calibration/camera_robot/plugin.py:278` | `self._ctx.health.report_error@277` | 1 | тесная пара |
| `Plugins/hub/device_hub/plugin.py:300` | `self._ctx.health.report_error@299` | 1 | тесная пара |
| `Plugins/hub/device_hub/plugin.py:401` | `self._ctx.health.report_error@383`, `self._ctx.health.report_error@407` | 6 | разные ветки (проверено) — на ветке `ok is False` report_error НЕТ |
| `Plugins/hub/device_hub/plugin.py:408` | `self._ctx.health.report_error@383`, `self._ctx.health.report_error@407` | 1 | тесная пара |
| `Plugins/io/database/plugin.py:183` | `self._ctx.health.report_error@180` | 3 | тесная пара |
| `Plugins/io/drawing_io/plugin.py:100` | `self._ctx.health.report_error@99` | 1 | тесная пара |
| `Plugins/io/drawing_io/plugin.py:160` | `self._ctx.health.report_error@177` | 17 | разные ветки (проверено) — на ветке валидации report_error НЕТ |
| `Plugins/io/drawing_io/plugin.py:178` | `self._ctx.health.report_error@177` | 1 | тесная пара |
| `Plugins/io/frame_saver/plugin.py:283` | `self._ctx.health.report_error@282` | 1 | тесная пара |
| `Plugins/io/frame_saver/plugin.py:347` | `self._ctx.health.report_error@346` | 1 | тесная пара |
| `Plugins/io/robot_draw/plugin.py:169` | `self._ctx.health.report_error@168` | 1 | тесная пара |
| `Plugins/io/robot_draw/plugin.py:185` | `self._ctx.health.report_error@184` | 1 | тесная пара |
| `Plugins/io/robot_draw/plugin.py:280` | `self._ctx.health.report_error@278` | 2 | тесная пара |
| `Plugins/io/robot_draw/plugin.py:296` | `self._ctx.health.report_error@278` | 18 | разные ветки (проверено) — на ветке `status != ok` report_error НЕТ |
| `Plugins/io/robot_io/plugin.py:242` | `self._ctx.health.report_error@239` | 3 | тесная пара |
| `Plugins/io/robot_io/plugin.py:259` | `self._ctx.health.report_error@239` | 20 | разные ветки (проверено) — на ветке `status != ok` report_error НЕТ |
| `Plugins/io/telemetry_sink/plugin.py:265` | `self._ctx.health.report_error@264` | 1 | тесная пара |
| `Plugins/processing/circle_detector/plugin.py:102` | `self._ctx.health.report_error@101` | 1 | тесная пара |
| `Plugins/processing/edge_detection/plugin.py:195` | `self._ctx.health.report_error@194`, `self._ctx.health.report_error@198` | 1 | тесная пара |
| `Plugins/processing/edge_detection/plugin.py:199` | `self._ctx.health.report_error@194`, `self._ctx.health.report_error@198` | 1 | тесная пара |
| `Plugins/processing/pixel_to_robot/plugin.py:107` | `self._ctx.health.report_error@106` | 1 | тесная пара |
| `Plugins/processing/segmentation/plugin.py:158` | `self._ctx.health.report_error@157` | 1 | тесная пара |
| `Plugins/sinks/modbus_sink/plugin.py:206` | `self._ctx.health.report_error@205` | 1 | тесная пара |
| `Services/sql/core/sql_manager.py:75` | `self._track_error@74` | 1 | тесная пара |
| `Services/sql/core/sql_manager.py:320` | `self._track_error@319` | 1 | тесная пара |
| `multiprocess_framework/modules/command_module/core/command_manager.py:133` | `self._track_error@134` | 1 | тесная пара |
| `multiprocess_framework/modules/command_module/core/command_manager.py:156` | `self._track_error@157` | 1 | тесная пара |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:152` | `self._track_error@153` | 1 | тесная пара |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:183` | `self._track_error@184` | 1 | тесная пара |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:275` | `self._track_error@276` | 1 | тесная пара |
| `multiprocess_framework/modules/dispatch_module/core/dispatcher.py:425` | `self._track_error@426` | 1 | тесная пара |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3769` | `self.error_manager.track_error@3827` | 58 | разные ветки (проверено) — track_error только в `except` на 3827 |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3779` | `self.error_manager.track_error@3827` | 48 | разные ветки (проверено) — track_error только в `except` на 3827 |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3788` | `self.error_manager.track_error@3827` | 39 | разные ветки (проверено) — track_error только в `except` на 3827 |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3820` | `self.error_manager.track_error@3827` | 7 | одна ветка (проверено) — track_error@3827 в том же `except`, под `hasattr` |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:220` | `self._track_error@256` | 36 | разные ветки (проверено) — _track_error только во внешнем `except` |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:226` | `self._track_error@256` | 30 | разные ветки (проверено) — _track_error только во внешнем `except` |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:255` | `self._track_error@256` | 1 | тесная пара |
| `multiprocess_framework/modules/process_manager_module/process/topology_manager.py:422` | `self._track_error@423` | 1 | тесная пара |
| `multiprocess_framework/modules/process_module/generic/source_producer.py:138` | `self._health.report_error@148` | 10 | разные ветки (проверено) — на ветке NotImplementedError report_error НЕТ |
| `multiprocess_framework/modules/process_module/generic/source_producer.py:142` | `self._health.report_error@148` | 6 | одна ветка (проверено) — report_error@148 в том же `except Exception` |
| `multiprocess_framework/modules/router_module/core/router_manager.py:398` | `self._track_error@399` | 1 | тесная пара |
| `multiprocess_prototype/frontend/app.py:297` | `process._track_error@298` | 1 | одна ветка (проверено) — N строк лога в цикле + ОДИН _track_error после цикла |
| `multiprocess_prototype/frontend/app.py:572` | `process._track_error@298` | 274 | разные ветки (проверено) — _track_error только в блоке валидации топологии |
| `multiprocess_prototype/frontend/app.py:606` | `process._track_error@298` | 308 | разные ветки (проверено) — _track_error только в блоке валидации топологии |
| `multiprocess_prototype/frontend/app.py:653` | `process._track_error@298` | 355 | разные ветки (проверено) — _track_error только в блоке валидации топологии |

---

## Отдельные наблюдения (не классификация, но для реализации важно)

1. **Все номера строк из спеки актуальны на `97fe2123`** — сверено, ни один не съехал:
   `plugin_orchestrator.py:157, 180, 202`; `worker_module` — ровно 5 точек
   (`core/worker_manager.py:58, 68, 131`, `lifecycle/worker_lifecycle.py:162, 228`);
   `socket_channel.py:132` и `:341`; `router_manager.py:398` (пара с `_track_error@399`);
   `Plugins/sources/capture/plugin.py:288`.
   Оговорка: у всех, кроме пяти точек `worker_module`, я открывал исходный код вокруг
   вызова; у `worker_module` подтверждены только номер строки и текст вызова грепом.
2. **Асимметрия «отказ по исключению виден, отказ по коду — нет».** У `robot_draw` и
   `robot_io` ветка `except Exception` зовёт `health.report_error`, а соседняя ветка
   «хаб вернул `status != ok`» — только `log_error`. Тот же отказ хаба попадает в
   плоскость ошибок или не попадает в зависимости от того, как драйвер его вернул.
   То же у `device_hub` (`create_worker` вернул `False` против брошенного исключения).
3. **`source_producer.py:138`** — единственная найденная точка, где `log_error`
   сопровождается `stop_event.set()`: источник встаёт навсегда, и на этой ветке
   `report_error` нет (он есть только на соседней, `except Exception`).
4. **`process_module.py:285` и `:286`** — один инцидент двумя вызовами (сообщение и
   отдельной строкой трасса). Дубль по построению, до всякого `report_error`.
5. **`process_manager_process.py:3251`** — `_log_error` в ветке `else`, когда
   `error_manager` отсутствует. Фолбэк стоит ровно там, где плоскость ошибок мертва;
   любая правка «переводим на `report_error`» здесь применяться не должна.
6. **`recipe/manager.py:209` и `:322`** ловят `(yaml.YAMLError, OSError)` одним
   `except`: класс A (файл недоступен) и класс B (файл кривой) физически слиты в одной
   ветке. Развести классы здесь нельзя без разделения `except`.
7. **Уровень ERROR местами взят по инерции:** `frame_shm_middleware.py:558` сообщает об
   **успешном** реклейме займов мёртвого читателя; `:363` — о деградации
   производительности (pickle-fallback); `process_registry.py:264, 354` — о штатной
   ступени эскалации останова (`Force killing`). Все четыре в классе C.

## Что в этом инвентаре ненадёжно

- **Классификация — суждение, а не измерение.** Структурные признаки (тип `except`,
  условие ветки, `return False`) собраны машинно и проверяемы; отнесение к A/B/C —
  моё решение по правилу «пропала ли у системы возможность, или это один плохой
  элемент из потока». Правило названо, но другой человек с тем же правилом получит
  другую границу на десятке-другом точек.
- **Из 315 точек я открывал исходный файл вокруг вызова у 31** (точки спеки кроме
  `worker_module`, все «далёкие» пары, часть спорных). Остальные **284**
  классифицированы по структурному срезу AST — это не текст сообщения, но и не чтение
  функции целиком: контекст выше по стеку (кто вызывает, что делает с `False`) в срез
  не попал. Ошибки классификации, если они есть, сидят именно в этих 284.
- **13 пар «в одной функции, но на разных ветках» проверены чтением; ни одна пара не
  осталась непроверенной**, но проверка была на глаз по 20-30 строкам, без прогона.
- **Приоритет P1/P2 — тоже суждение.** Он ничем не измерен; на живом стенде порядок
  может оказаться другим.
- Инвентарь снят на `97fe2123`. Любая правка кода сдвигает номера строк — перед
  реализацией стоит перегенерировать срез, а не доверять числам отсюда.
