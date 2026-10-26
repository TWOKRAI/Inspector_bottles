# Аудит фундамента — опись 1б: Services

Дата: 2026-10-26. Полоса А, `inspector-bottles-1a`. Продолжение описи [шага 1](2026-10-26_foundation-audit-inventory.md) (framework); соседний файл — [backend_ctl и библиотеки](2026-10-26_foundation-audit-1b-backend-ctl-libs.md). Только факты, вердикт за CTO; вопросы — в [брифе CTO](2026-10-26_foundation-audit-cto-brief.md), раздел «Шаг 1б».

## Как снято

- HEAD `f63f68403`. После среза шага 1 (`71bfc55fe`) влито одно слияние с кодом — C-40 (`d39ca7ba0`, 20:32): `Services/ml_inference`, плагин `word_layout`, три рецепта. Строки `ml_inference` сверены после слияния: регистр `inference_every_n` убран, строка с CPU-fallback теперь `plugin/registers.py:67`.
- 3 агента Explore (2 на Haiku: опись по группам; 1 на Sonnet: хостинг, дубли, путь робота, изоляция сбоев). Лид сверял по коду выборочно, отметка «сверено».
- Тесты не запускались. Даты — последний коммит, тронувший строку (`git log -L`), или дата добавления файла.

## 1. Сводка по сервисам

`Services/` — 17 пакетов плюс `tests/`. В `Services/STATUS.md` описаны 14: нет control_panel, otel_export, phone_gateway.

| сервис | код / тесты, строк | кто хостит (процесс) | глубокие импорты framework¹ | заметное |
|---|---|---|---|---|
| robot_comm | 13 266 / 25 021 | библиотека в драйверах `device_hub` (процесс `devices`); свой сим-сервер TCP (`server/sim_robot.py:260, 316`) | 2 (`gui/line_source.py:34, 36`) | v1 и v2 клиента, протокола и симулятора живут рядом (раздел 3) |
| device_hub | 6 950 / 15 638 | плагин `DeviceHubPlugin` (`Plugins/hub/device_hub/plugin.py:113`) в процессе `devices`; supervisor + поток на устройство | 0 | все 4 драйвера — robot v1/v2, vfd, hikvision (нативный SDK), generic_modbus — в одном процессе (`manager.py:192–228`) |
| hikvision_camera | 4 465 / 2 754 | свой плагин (5 рецептов), `HikvisionDriver` в device_hub, `HikvisionBackend` в `camera_service` (9 рецептов); SDK-app — подпроцесс `subprocess.Popen` (`plugin/plugin.py:459`) | 1 | `service.py:42, 52` — «TODO Phase 4+»: инициализация и освобождение SDK не сделаны (2026-05-25 · d4eeb153e); 8 `except Exception: pass` |
| modbus | 2 864 / 1 912 | библиотека под robot_comm / vfd_comm / device_hub; `ModbusPlugin` в рецептах не найден | 1 (`channels/modbus_channel.py:21`) | `MODBUS_WIRE_LOG` env; README обещает «внутри транзакции нет тихого reconnect/retry» — ни кода, ни теста |
| vfd_comm | 492 / 409 | библиотека, создаётся только в `VfdDriver.connect` (`device_hub/drivers/vfd_driver.py:99`) | 0 | `Services/STATUS.md:27`: «robot_comm НЕ импортирует vfd_comm», но `robot_comm/server/sim_core_v2.py:247–256` импортирует 10 констант из `vfd_comm.core.registers` |
| line_sim | 2 807 / 11 377 | библиотека (`Plugins/sim/*`) | 0 (framework не импортирует вовсе) | — |
| code_reader | 5 123 / 9 303 | плагины TCP (`plugin/plugin.py:62`) и SDK (`plugin/sdk_plugin.py:65`); свой TCP-сервер (`core/sink.py:193, 203, 273`), поток SDK (`core/sdk_reader.py:241`) | 0 | два пути приёма — TCP и SDK, у каждого свои рецепты |
| ml_inference | 1 649 / 1 270 | плагин `MLInferencePlugin`; GUI импортирует `core.registry` напрямую (`multiprocess_prototype/frontend/forms/model_picker.py:20`) | 0 | молчаливый CPU-fallback при `device=cuda` (`backends/torch_backend.py:53`, `onnx_backend.py:36`) |
| ml_train | 2 204 / 1 652 | отдельный процесс через `QProcess` из GUI (`ml_train_section.py:167, 178`) | 0 | mixup упомянут в docstring `trainer.py:1`, в коде только комментарий |
| dataset_gen, layer_render | 2 492 + 2 689 / 4 295 + 8 029 | библиотеки; `dataset_gen/core/*` — реэкспорт-шимы на `layer_render` (LR-001) | 0 | 4 `ponytail:` в layer_render |
| sql | 3 391 / 1 521 | библиотека для `Plugins/io/database`, `Plugins/io/telemetry_sink` | 4 (`actions_module.schemas` / `.bus`) | `service.py:42, 52` — тот же «TODO Phase 4+» (подключение и закрытие не сделаны) |
| otel_export | 1 762 / 4 126 | библиотека для `Plugins/io/otel_export` | 4 (`channel_routing_module.observability.*`, `logger_module.core.trace_id_guard`) | `ObservabilityPort` объявлен (`interfaces.py:251`), прод-реализаций нет |
| auth | 3 449 / 3 303 | библиотека GUI (13 файлов прототипа) | 0 | `service.py:42, 52` — тот же «TODO Phase 4+»; `PermissionsRegistry` потокобезопасен по STATUS — теста нет |
| documents | 657 / 927 | библиотека; потребитель `Plugins/control/robot_control/plugin.py:54` | 0, но импорт приватного `multiprocess_framework.modules._fallback` (`wiring.py:23`) | `Services/STATUS.md:23` «потребители не подключены» против `documents/STATUS.md:3` «работает на ДВУХ клиентах» |
| phone_gateway | 1 238 / 534 | плагин `PhoneCameraPlugin`; свой `ThreadingHTTPServer` (`gateway.py:120, 124`) | 0 | STATUS: «always-on процесс в base.yaml» — в `multiprocess_prototype/backend/topology/base.yaml` его нет (4 формы поиска) |
| control_panel | 455 / 269 | плагин `ControlPanelPlugin` | 0 | в коде есть контрол `select`, в STATUS его нет |

¹ Импорт вида `multiprocess_framework.modules.<m>.<sub>`, кроме `interfaces` и корня пакета. Всего 12 строк в Services. Импортов `Plugins` и `multiprocess_prototype` в production-коде Services — 0 (в тестах 21 строка).

Одинаковый шаблон «TODO Phase 4+» в `service.py` у auth, sql и hikvision_camera (2026-05-25 · d4eeb153e): карточка `ServiceHost` хранит статус и конфиг, но `start` / `stop` ничего не открывают. У robot_comm и vfd_comm карточки сервисов тоже соединений не открывают (`robot_comm/service.py:1–7`).

## 2. Долг (выборка; полный перечень — в отчётах агентов, не в git)

| сервис | файл:строка | что | дата · коммит | очередь |
|---|---|---|---|---|
| robot_comm | kinematics.py:99, 103, 108 | длины звеньев, диапазоны J1/J2, скорости осей — заглушки (`ponytail:` «из памяти, не сверено») | 2026-09-27 · 6ee8d198a / 1cc29d68a | — |
| robot_comm | server/sim_core.py:214 | `ponytail:` copy-then-reassign не атомарно, запись тикера | 2026-09-24 · 34943ad8d | — |
| robot_comm | gui/sim_view.py:194, 261, 353 | `ponytail:` доступ к приватным `core._workspace()` / `core._active` | 2026-09-27 · d39a26c8e | — |
| robot_comm | programs/program.py:304 | `model_copy(update=…)` обходит валидацию точек СК | 2026-10-12 · f6b8e88ea | — |
| device_hub | manager.py:376; drivers/generic_modbus_driver.py:86; drivers/hikvision_driver.py:90 | `except Exception: pass` | 2026-06-11 · 4b01b6ea2 | — |
| hikvision_camera | core/discovery.py:49, 57, 84, 92; core/camera.py:191; plugin/plugin.py:486 | `except Exception: pass` | 2026-05-10 · 4db04d3a0 и 2026-07-21 | — |
| modbus | plugin/plugin.py:175, 177 | опрос регистров через `sleep` | 2026-06-01 · de7e11731 | — |
| code_reader | core/sink.py:229 | `except OSError: pass` в TCP-приёмнике | 2026-09-28 · 5d863c122 | (C-3 — тема TCP) |
| phone_gateway | netinfo.py:52, 88, 103; plugin/plugin.py:277 | проглоченные `Exception` / `ValueError` | 2026-06-15 · 68beb6982 | — |
| sql | core/sql_manager.py:277, 290 | legacy-конверт `args` (rolling-switch) | 2026-07-13 · 712d79903 | — |
| auth, sql | bootstrap.py:79, 97; core/engine_factory.py:41 | env-алиасы `MULTIPROCESS_*` / `INSPECTOR_*`, включая dev-пароль из env | 2026-08-12 · e1396c4fc | — |

Маркеров `ponytail:` в Services — 21: robot_comm 14, layer_render 4, line_sim 2 (в `tools/`), code_reader 1.

## 3. Дубли механизмов

| # | что | факты | очередь |
|---|---|---|---|
| B1 | **Драйвер робота v1 и v2.** v1 `device_hub/drivers/robot_driver.py:34`, `_OPS` (:857, 27 операций); v2 `drivers/robot_driver_v2/`, `OPS` (ops.py:216, 15 операций). Выбор в `manager.py:196–219` по `protocol == "delta_v2"`. Каркас `call()` повторён: v1 `robot_driver.py:580`, v2 `driver.py:607`. v1 от 2026-06-11, v2 от 2026-10-20 | **Сверено.** GUI `RobotPresenter` шлёт v1-имена — `robot_send_test_job`, `robot_set_mode`, `robot_set_servo`, `robot_jog`, `robot_draw_*` (`multiprocess_prototype/frontend/widgets/tabs/services/robot/presenter.py:51–162`). Плагин превращает их в `_kind_call(..., "send_test_job" / "set_mode" / "jog")` (`Plugins/hub/device_hub/plugin.py:946–960`). В `OPS` v2 этих операций нет, значит v2 ответит «Неизвестная операция» (`driver.py:609–610`). Рецептов с `delta_v2` один — `letter_robot_sim.yaml:74`, с `delta_universal3` — 7. **Живьём не воспроизведено** | ORDER Р6 (T5.1); `plans/robot-protocol-v2/plan.md:353` «v1 заморожен как запасной», `:109` «старая вкладка — для устройств v1»; GUI-пакет v2 — 2.0 (строка 32 очереди), в 1.0 — пульт (строки 15–17). То есть граница по плану, а не случайная поломка; не решено, как вкладка ведёт себя на устройстве v2 |
| B2 | клиенты робота v1 (`robot_comm/core/client.py:80`, 698 строк) и v2 (`client_v2.py:272`, 1 196 строк) | v1 — из `robot_driver.py:944`, v2 — из `driver.py:100`, `jobs.py:23`, `params.py:37` | ORDER Р4 |
| B3 | протокол v1 (`delta_universal3.yaml`, `core/registers.py`, `sim_core.py` 622 строки) и v2 (`delta_v2.yaml` → кодоген → `protocol_v2.py`, `OP_SPEC` :78; `sim_core_v2.py` 1 711 строк) | `OP_SPEC` (опкоды прошивки) и `OPS` драйвера (операции оператора) — таблицы разного уровня, связаны вызовами `client_v2.py:865–940`; общего описания нет | `plans/robot-protocol-v2` |
| B4 | **три пути камеры Hikvision**, все создают `HikvisionCamera()`: плагин сервиса (`hikvision_camera/plugin/plugin.py:51`), `HikvisionBackend` в `Plugins/sources/camera_service/backends/hikvision.py:31` (свои 3 попытки открытия), `HikvisionDriver` в device_hub (`drivers/hikvision_driver.py:17`, без захвата кадров) | 5 + 9 рецептов на первые два пути | ORDER (план camera-device-service, 4.2a); R-7 |
| B5 | **шесть реализаций переподключения:** база `drivers/base.py:190` (лимит 3); тротлы 2 с в robot v1 (`robot_driver.py:29`), robot v2 (`robot_driver_v2/texts.py:72`), modbus_sink (`Plugins/sinks/modbus_sink/plugin.py:35`); тротл 3 с в vfd (`vfd_driver.py:19`); `_OPEN_RETRIES = 3` в hikvision- и webcam-бэкендах | `CircuitBreaker` framework (`process_module/health/breaker.py:58`) использует `SourceProducer`, Services — нет (поиск по именам) | 0 строк очереди |
| B6 | 12 загрузчиков YAML через `yaml.safe_load` в Services, `config_module` framework из Services не импортируется. Данные робота — три слоя над одним store: `robot_comm/robot_data.py`, `robot_comm/store.py:185 RobotDataStore`, `device_hub/robot_data_ops.py:280` | — | — |

## 4. Путь команды GUI → робот (v2, `jog_step`)

14 звеньев. Пересылают или почти пересылают 7 из них: 1, 3, 6, 9, 11, 12 и `write_register`.

| # | звено | роль |
|---|---|---|
| 1 | `RobotPresenter` (`presenter.py:24, 48`) → `request_command("devices", …)` | пересылка |
| 2 | таблица команд плагина `device_hub` (`plugin.py:~125–215`, 99 команд) | диспетчеризация |
| 3 | `cmd_robot_jog_step` (`plugin.py:1074`) → `_kind_call` | пересылка, около 63 однострочных обёрток |
| 4 | `_kind_call` (`plugin.py:696`) | проверка `kind` |
| 5 | `_safe_call` (`plugin.py:657`) | граница ошибок |
| 6 | `DeviceManager.call` (`manager.py:461`) | почти пересылка |
| 7 | `RobotDriverV2.call` (`driver.py:607`) | диспетчер |
| 8 | `_op_jog_step` (`ops.py:144`) | логика |
| 9 | `RobotClientV2.jog_step` (`client_v2.py:873`) | пересылка |
| 10 | `cmd` (`client_v2.py:488`) | транзакция mailbox |
| 11 | `_wr` (`client_v2.py:413`) | тонкая обёртка |
| 12 | `ExchangeLogTransport.transaction` (`exchange_log.py:442`) | при выключенном журнале — чистая пересылка |
| 13 | `ModbusDevice.transaction` (`modbus/core/device.py:~125`) | логика |
| 14 | `ModbusSdkClient._call` (`modbus/sdk/client.py:225`) → pymodbus → сокет | `write_register` перед ним — однострочная пересылка |

## 5. Изоляция сбоев устройств (по коду, не проверено запуском)

- Исключение в `tick` драйвера ловит `tick_loop` плагина (`Plugins/hub/device_hub/plugin.py:~565`): цикл продолжается, отчёт идёт в `health.report_error` и `last_error`. Если упадёт сам поток, обёртка воркера framework (`worker_lifecycle.py:223`) поставит статус ERROR. Перезапуска не будет: `restart_on_failure` по умолчанию `False`, плагин его не задаёт (`plugin.py:~592`).
- В `_supervisor_loop` (`plugin.py:405–419`) нет своего `try`. Исключение из `_publish_state` внутри `except` уйдёт в обёртку воркера: ERROR без рестарта.
- `ModbusSdkClient._call` ловит только `TypeError` (`modbus/sdk/client.py:~250`), `ModbusDevice` — только `ModbusDriverError`. Сырой `OSError` из pymodbus не преобразуется. Об этом прямо сказано в docstring `robot_driver_v2/driver.py:569`: «сырой `OSError` … оставляет `is_connected == True`».
- `ModbusPlugin._poll_loop` без `try` (`modbus/plugin/plugin.py:~170–178`), автореконнекта нет.
- `VfdDriver` берёт транспорт у носителя-робота (`device_hub/transports.py:134`). Связь с носителем проверяется только в `manager.connect` (`manager.py:~412`).
- Нативный SDK Hikvision исполняется в процессе `devices` вместе с драйверами робота и ПЧ. Отдельным процессом идут только SDK-app (`Popen`) и `ml_train` (`QProcess`).

Строки с «~» агент читал кусками, перед цитированием их нужно сверить.

## Что я оставил открытым / ненадёжным

- B1 (v1-команды на драйвере v2) выведен из таблиц и сверен по коду, но живьём не воспроизведён. Нужен стенд `letter_robot_sim`. Не проверено, нет ли в GUI ветки, которая для v2 шлёт другие имена: агент видел только v1-имена в `presenter.py`.
- Раздел 5 не заполнен для code_reader (сбои TCP-сервера), phone_gateway, auth (`audit_writer`), generic_modbus, modbus_sink.
- «Сервисы не используют `CircuitBreaker` и `config_module`» проверено только поиском по именам.
- Обещания README и STATUS выбраны по ключевым словам, по 3–6 на сервис, — это не полный перечень.
- `ModbusPlugin` в рецептах не найден, но подключение через реестр плагинов не проверено. Нельзя утверждать, что он мёртв.
