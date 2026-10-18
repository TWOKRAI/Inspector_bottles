# camera-device-service — решения плана, ADR, слои

Часть плана [`plan.md`](plan.md). Решения входят в DESIGN задач; задача на них ссылается
номером `Р<n>`, а не пересказывает.

## Решения плана

| # | Решение | Почему |
|---|---|---|
| Р1 | **Процесс на камеру, один сеанс прибора на процесс, все вызовы SDK — из потока-владельца.** Идентичность прибора обязательна; `select: first` — только явно. Пауза перезапуска у супервизора ≥ времени отпускания прибора (~10 с, handoff §4.1) — `restart_policy.backoff_sec` процесса в рецепте (10,0 с; Task 3.3, 4.3; поля плагина нет — ревью B3) | F5, F7, Q5; снимает H2 устройством сеанса |
| Р2 | **Порт без GenICam в сигнатуре.** `DevicePort.get_param/set_param/describe_param/execute` принимают `Binding(kind, key, vtype)`, `kind ∈ {"genicam","cv_prop","vendor","none"}`. Что писать можно, что на ходу, что читается обратно — решает `Capabilities` драйвера (`frozenset[str]`: `read_back`, `live_write`, `node_describe`, `software_trigger`, `restart_regrab`; ревью P4 срезало `codes`, `self_trigger`, `exception_cb`, `enumerate` — ядро по ним не ветвится). `Binding.kind` оставлен описательным (решение владельца 5), ядро по нему не ветвится, не ядро | решение владельца 5: у веб-камеры и RTSP узлов GenICam нет |
| Р3 | **Идентичность:** `DeviceIdentity(kind ∈ {"serial","ip","url","index"}, value: str, name: str = "")`; `index` разрешён только с `name` (UVC) или с WARNING в логе | F13: порядок перечисления не обещан |
| Р4 | **Параметр описан один раз** — поле register'а (тип + `FieldMeta` с `apply`, `enabled_if`, `ui_group`); драйвер держит только таблицу `BINDINGS: dict[str, Binding]`. Контрактный тест: `set(BINDINGS) == {вендорские поля register'а}`, тип `Binding.vtype` совместим с аннотацией | A1 |
| Р5 | **«Не управлять группой» — явный флаг** (`trigger_managed: bool = False`) + `enabled_if={"trigger_managed": [True]}` у полей группы; не `None` в числе | фабрика снимает `Optional` до спинбокса (`kinds.py:76-81`), показ `None` не проверен |
| Р6 | **Профиль run — при каждом старте, rest — best-effort при остановке; исходные не читаются; каждая запись проверяется чтением**: float/int — `|read − target| ≤ max(inc or 0, 1e-3·|target|, eps_abs)`, `eps_abs` — поле `Binding`, умолчание `1e-6` (ревью B2: у float-узлов MVS шага нет, `structures.py:196-204`); при H5 (код ≠ 0, чтение = цель) — `verified: True` + `rc`, enum — по символьному имени; в `params` пишется прочитанное. Без capability `read_back` — статус `unverified` (не ошибка, не «подтверждено») | проект §2.2, A7; `cv2.VideoCapture.get` не всегда отражает прибор |
| Р7 | **Общий набор команд** (все драйверы): `take_device`, `release_device`, `get_status`, `reset_stats`, `list_devices`, `read_params`, `describe_params`, `apply_params`, `trigger_software` (только с capability `software_trigger`, иначе ответ `{"success": False, "error": "нет capability software_trigger"}`) | Q6 |
| Р8 | **Переименование `hikvision` (без алиасов):** `open`+`start_capture` -> `take_device`; `close`/`stop_capture` -> `release_device`; `enum_devices` -> `list_devices`; `get_parameters` -> `read_params`; `set_parameters`/`set_exposure`/`set_gain`/`set_frame_rate`/`set_resolution` -> `apply_params` (или `register_update`); `open_sdk_app`/`close_sdk_app` удаляются. **`device_hub` (решение лидера 2026-10-18, правка раунда 2):** новые `camera_list_devices`, `camera_owner`, `camera_read_params`; `hik_release` остаётся no-op `{"status": "ok", "released": []}` — у него живой вызывающий `Plugins/sources/camera_service/plugin.py:262` (принцип №3), «удалить» для него отменено; `hik_enum`, `hik_open`, `hik_close`, `hik_get_params`, `hik_set_params` — отказ с текстом, какая команда заменяет. Хаб — реестр + зеркало владельца, один `CameraMirrorDriver` (отчёт `docs/reviews/2026-10-18_device-hub-camera-integration.md`) | решение владельца 3; хаб камерой не владеет (проект §4) |
| Р9 | **`sdk_app` — отдельный инструмент диагностики, FROZEN**: ручной запуск `python -m Services.hikvision_camera` при остановленном стенде (как IDMVS). Удаляются оба пути запуска из приложения: команда плагина `open_sdk_app` (`plugin.py:400-422`) и `Popen` во вкладке (`presenter.py:130-144`, `controller.py:90`) | клиент IPC = переписать дубль вкладки GUI; удалить целиком — потерять инструмент диагностики к стенду MVS через ~2 дня; запуск из приложения = второй открыватель камеры (F14) и запуск процесса из GUI (принцип №6) |
| Р10 | **Конверт item:** межисточниковые ключи `frame`, `camera_id: int`, `seq_id`, `frame_id`, `timestamp` (monotonic) сохраняются — их несут `capture` (`Plugins/sources/capture/plugin.py:257-260`) и `camera_service` (`:180-183`) и читают fan-in (`join_inspector_manager.py:132`), `center_crop` (`plugin.py:33`), `line_filter` (`plugin.py:228`), `frame_saver`, `database`, `stitcher`. Добавляются `device_id: str`, `ts` (wall `time.time()`), `pixel_format`, `width`, `height`, `device_frame_num`. `seq_id`/`frame_id` в плагинах ядра растут без переполнения | F15, F20; переименование `camera_id` — правка всех источников и fan-in, вне объёма |
| Р11 | **Реестр драйверов — словарь строк** в `Services/camera_device/drivers/__init__.py`: `DRIVERS = {"fake": "Services.camera_device.testing.fake_port:make_port", "opencv": "Services.camera_device.drivers.opencv_driver:make_port", "mvcr": "Services.code_reader.driver:make_port", "mvs": "Services.hikvision_camera.driver:make_port"}`; разрешение `importlib` в `configure`; неизвестный ключ -> `ValueError` со списком известных. Поле `driver:` — у общего `CameraDevicePlugin`; вендорские плагины переопределяют `create_port()` ленивым импортом своего `make_port` (ревью R-b), реестр — P1 (5.1). Без plugin-discovery | решение владельца 5, ponytail; DLL чужого вендора в процесс не грузится |
| Р12 | **Живая правка:** `RegistersManager.subscribe` -> сообщение в очередь владельца. `apply="live"` — запись при идущем захвате (только с capability `live_write`, иначе как `restart`); `"restart"` — перезахват: `stop_grabbing -> план -> start_grabbing` при `restart_regrab`, иначе `close -> open -> план -> start`; `"config"` — со следующего `take_device`. Колбэк `subscribe` исполняется в системном потоке процесса (`_message_processing_loop`, `process_module/threads/system_threads.py:81` -> `router_manager.py:1467` -> `_dispatch_command`; прочитано, не запускалось) и только кладёт в очередь | A8, проект §3.5 |
| Р13 | **Проверка прибора — по `state…params`, не `set_register_verified`** (тот читает только register, `backend_ctl/registers.py:139-174`): шаблон «`set_register_verified` + `await_condition` на `processes.<p>.state.<plugin>.params.<поле>`» | совет 3 |
## FREEZE и переименование

**Р14. FREEZE после миграции:** `HikvisionCamera` (`core/camera.py`, остаётся у `sdk_app`), `SdkCodeReader`
(`code_reader/core/sdk_reader.py`, его тесты остаются), `CommandPanel` (`frontend/widgets/controls/command_panel.py:41-45`
шлёт `start_capture`/`stop_capture` в `camera_0`; `git grep -n "CommandPanel" -- multiprocess_prototype ':!*/tests/*'` ->
только сам файл и `plans/phase4_gui.md`, живого создания нет). Причина — принцип №3.

**Почему старые команды не замораживаются (для решения владельца 3).** Принцип «FREEZE, не KILL» защищает мёртвый код: путь без живого
вызывающего остаётся контрактом (Р14). API, которое владелец сам решил переименовать, — живое: старые имена удаляются, а
каждый потребитель переводится в той же точке коммита К4 ([`plan.md`](plan.md), «Точки коммита»). Алиасов нет.

## Слои и направление импорта

- `.sentrux/rules.toml` — deny-список: `Services/* -> multiprocess_prototype/*` и `Services/* -> Plugins/*` запрещены (`:133-142`), `Services/* -> backend_ctl/*` запрещён (`:74-77`), `multiprocess_framework/* -> Services/*` запрещён (`:95-98`), `Services/* -> frontend_module/application/*` (`:202-205`), и четыре пары Services -> Services (`:157-177`: `layer_render` -> `line_sim`/`dataset_gen`/`ml_train`, `dataset_gen` -> `line_sim`). `code_reader`/`hikvision_camera` -> `camera_device` не запрещены.
- Ядро импортирует только `multiprocess_framework` и stdlib; `cv2`/`numpy` — только `drivers/opencv_driver.py` и `testing/`. Вендор в ядре — только строки реестра (Р11), статического импорта нет.
- **Следствие для OpenCV:** таблица `CAP_PROP` уже есть в `Plugins/sources/camera_service/backends/webcam_controls.py:24-182` (`ParamSpec`), но Services не может импортировать Plugins. Драйвер ядра берёт свою таблицу привязки; дубль ~15 строк — долг `ponytail:` в коде, снятие — когда `camera_service` переедет на ядро (вне плана).
- Task 0.1 запускает `sentrux check .` (ревью его НЕ запускало) и решает по выводу, нужен ли явный boundary `Services/camera_device/* -> Services/code_reader/*|Services/hikvision_camera/*` (запрет обратного статического импорта ядра на вендора). Каждая задача, которая добавляет импорт между пакетами, повторяет `sentrux check .` в приёмке.

## ADR — что и где

Где: root `CLAUDE.md`, «Правила проекта» п.3 и п.7 — локальные ADR в `DECISIONS.md` модуля, индекс в
`multiprocess_framework/DECISIONS.md`. Каталога `docs/claude/DECISIONS/` нет (`ls docs/claude/DECISIONS` -> «No such file or directory»); не заводим.

| ADR | Суть | Файл | Задача |
|---|---|---|---|
| ADR-CAM-001 | ядро + вендорские драйверы, реестр строк (Р11) | `Services/camera_device/DECISIONS.md` (новый) | 0.1 |
| ADR-CAM-002 | один сеанс прибора на процесс, поток-владелец, run/rest, проверка чтением (Р1, Р6) | там же | 0.1 |
| ADR-CAM-003 | универсальность: `Binding.kind`, `Capabilities`, `DeviceIdentity` (Р2, Р3) | там же | 0.1 |
| ADR-CAM-004 | политика переименования: без алиасов, FREEZE только без живого вызывающего (Р8, Р9, Р14) | там же | 0.1 |
| ADR-DS-<след.> | `FieldMeta.apply`, `FieldMeta.enabled_if` | `multiprocess_framework/modules/data_schema_module/DECISIONS.md` | 1.1 |
| ADR-<код process_module>-<след.> | контракты и описания команд плагина; `introspect.registers` с `meta` | `multiprocess_framework/modules/process_module/DECISIONS.md` | 1.3, 1.4 |
| ADR-CR-011 | `code_reader_sdk` на ядре; механизм ADR-CR-010 (возврат исходных) заменён профилем rest | `Services/code_reader/DECISIONS.md` (сейчас ADR-CR-001…010) | 3.2 |
| ADR-HIK-001 | `hikvision` на ядре, новые команды, `sdk_app` FROZEN | `Services/hikvision_camera/DECISIONS.md` (новый: файла нет) | 4.3 |
| ADR-DH-<след.> ×2 | хаб камерой не владеет: реестр + зеркало (`CameraMirrorDriver`); инвариант `connect() == is_connected` | `Services/device_hub/DECISIONS.md` | 4.6a |

После каждой правки `DECISIONS.md`: `python -m scripts.sync`, затем `python scripts/validate.py` (root `CLAUDE.md` п.8).
