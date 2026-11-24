# Диаграммы системы камер

Часть отчёта [README.md](README.md). Все шесть диаграмм прошли рендер Mermaid Chart: `valid: true` у каждой. Картинки глазами я не смотрел.

## 1. Слои и зависимости по фактическим импортам

Сплошная стрелка — импорт. Пунктир — ленивый импорт, колбэк, IPC или строка рецепта.

```mermaid
flowchart TB
    subgraph FW["multiprocess_framework"]
        FWP["process_module.plugins: ProcessModulePlugin, Port, register_plugin"]
        FWO["PluginOrchestrator._on_register_update"]
        FWR["registers_module: RegistersManager.set_field_value, subscribe"]
        FWW["worker_module: WorkerManager"]
        FWS["data_schema_module: FieldMeta, SchemaBase"]
    end
    subgraph CORE["Services/camera_device - 2962 строк"]
        CI["interface.py: DevicePort, DeviceSdk, PortError - только stdlib"]
        CS["session.py: DeviceSession"]
        CPR["profiles.py: ProfileRunner"]
        CPA["params.py: build_plan"]
        CB["plugin_base.py: CameraDevicePlugin, create_port знает fake"]
        CRB["registers_base.py: CameraDeviceRegisters"]
        CF["testing/fake_port.py"]
    end
    subgraph HIK["Services/hikvision_camera - 4515 строк"]
        HD["driver.py: MvsPort, MvsSdk, BINDINGS"]
        HP["plugin/plugin.py: HikvisionCameraPlugin"]
        HR["plugin/registers.py: HikvisionCameraRegisters"]
        HSDK["sdk/bindings.py: MvCamera на ctypes"]
        HOLD["core/*: HikvisionCamera, discovery, FrameConverter - старый путь"]
        HINIT["__init__.py: грузит core при импорте пакета"]
        HAPP["sdk_app - FROZEN"]
    end
    subgraph SDH["Services/device_hub"]
        DHD["drivers/hikvision_driver.py: HikvisionDriver"]
    end
    subgraph PL["Plugins"]
        PHUB["hub/device_hub/plugin.py"]
        PCS["sources/camera_service/backends/hikvision.py"]
    end
    subgraph PROTO["multiprocess_prototype"]
        TAB["вкладка hikvision: presenter, controller"]
        REC["рецепты: plugin_name hikvision, plugin_class CameraDevicePlugin"]
    end
    CR["Services/code_reader - 0 импортов ядра"]
    RULE["sentrux: 2 правила, ядро не импортирует hikvision_camera и code_reader - пройдено"]
    CS --> FWW
    CS --> CI
    CS --> CPR
    CPR --> CI
    CPA --> FWS
    CPA --> CI
    CB --> FWP
    CB --> CS
    CB --> CPA
    CB --> CRB
    CB -.->|лениво| CF
    CRB --> FWP
    HD --> CI
    HD --> HSDK
    HP --> CB
    HP --> HR
    HP -->|FrameConverter| HOLD
    HP -.->|лениво в create_port| HD
    HR --> CRB
    HINIT --> HOLD
    HOLD --> HSDK
    HAPP --> HOLD
    DHD -->|HikvisionCamera через пакет| HINIT
    PHUB -->|core.discovery| HOLD
    PCS -->|core.camera| HOLD
    FWO --> FWR
    FWR -.->|колбэк подписки| CB
    TAB -.->|IPC: команды и register_update, импорта нет| FWO
    REC -.->|строки рецепта| HP
    RULE -.- CB
    RULE -.- CR
```

Что видно: ядро зависит только от framework, вендор зависит от ядра, обратных импортов нет. Старый путь `core/*` — узел, к которому сходятся 5 потребителей, в том числе новый плагин.
Что скрыто: импорты тестов (`camera_device` импортируют ещё 2 теста рецептов); связь хаба с процессом камеры через IPC; `code_reader` и `phone_gateway` изнутри.
Источник импортов: `git grep` по `Services.camera_device` (14 строк вне ядра: 12 в `hikvision_camera`, 2 в тестах prototype) и по `hikvision_camera.core` (48 строк).

## 2. Жизненный цикл сеанса `DeviceSession`

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> opening: start
    closed --> opening: start, владельца нет
    busy --> opening: start, владелец вышел
    not_found --> opening: start, владелец вышел
    error --> opening: start, владелец вышел
    opening --> grabbing: open, run, start_grabbing прошли
    opening --> busy: PortError busy до open
    opening --> not_found: PortError not_found до open
    opening --> error: прочий отказ
    opening --> closed: срок start истёк, откат
    opening --> stopping: stop
    grabbing --> stopping: stop
    grabbing --> error: 3 ошибки get_frame подряд или отказ перезахвата
    stopping --> closed: владелец закрыл порт и SDK
    busy --> closed: stop
    not_found --> closed: stop
    error --> closed: stop
    note right of grabbing
        apply и перезахват идут внутри grabbing
        state не меняется, on_state не зовётся
    end note
```

Что видно: 8 состояний и все переходы из `session.py`. Переходы — compare-and-set под `self._lock` (`session.py:402-416`).
- Из отказа `start()` работает, только когда владелец уже вышел (`session.py:268-269`). Пока владелец жив, `start()` возвращает `False`; автопереподключения нет.
- `opening -> closed` — откат по сроку `start(timeout)`: владелец видит `cancelled` в `_commit` и не зовёт `start_grabbing` (`session.py:294-296`, `:512-518`).
- `stop()` из отказа ставит `closed` сразу, порт закрывает сам владелец (`session.py:314-315`). Пара `closed` + `device_held=True` поэтому возможна.

Что скрыто: флаг `device_held`; сторож (`on_stall` после `watchdog_s`, `session.py:804-817`); ящик владельца. Зависший `open` держит `opening`, пока не вернётся: перехода по таймауту нет.

## 3. Путь кадра от порта до потребителя

```mermaid
flowchart LR
    DLL[("MvCameraControl.dll")]
    subgraph OWN["поток-владелец сеанса"]
        GF["MvsPort.get_frame: MV_CC_GetImageBuffer, копия string_at, MV_CC_FreeImageBuffer"]
        RF["RawFrame: bytearray, pixel_format bayer_rg8"]
        GL["DeviceSession._grab_loop, затем _poll_box"]
        OF["CameraDevicePlugin._on_frame: слот на 1 кадр, seq_id плюс 1"]
    end
    subgraph SP["поток SourceProducer процесса"]
        PR["produce: _tick, забрать слот"]
        FA["ядро _frame_array: bayer - cv2.cvtColor в BGR, rgb8 - срез, mono8 - копия"]
        HB["hikvision _build_item: mono8 - GRAY2BGR, FrameConverter.resize до resolution"]
        IT["item: frame HxWx3 BGR, pixel_format bgr8, source_format bayer_rg8, seq_id, device_id, ts"]
        SHM["SourceProducer: кадр в слот SHM, dict по IPC"]
    end
    DROP["кадр отброшен: dropped плюс 1, log_error один раз на причину"]
    CONS["потребители рецепта: дисплей и ниже по цепочке"]
    DLL --> GF --> RF --> GL --> OF
    OF -->|новый кадр вытесняет старый| PR
    PR --> FA --> HB --> IT --> SHM --> CONS
    FA -.->|формат не поддержан или длина буфера| DROP
    HB -.->|cv2.error| DROP
```

Что видно: буфер SDK освобождается до возврата `get_frame` (`driver.py:391-407`). Между потоками кадр передаёт слот на 1 кадр (`plugin_base.py:402-406`).
Цвет приводит ядро (`plugin_base.py:558-583`), размер слота SHM — вендор (`plugin.py:50-65`). `source_format` хранит формат прибора, `pixel_format` всегда `bgr8` у Hikvision.
`bayer_rg8` на прибор — из `OPEN_QUESTIONS.md:2622` (бриф лида), в коде формат приходит из `enPixelType`.
Что скрыто: запись в SHM и IPC внутри `SourceProducer` framework — я их не читал. Состав потребителей по рецептам я не сверял.

## 4. Путь живой правки поля

```mermaid
sequenceDiagram
    autonumber
    participant G as GUI HikvisionSettingsPresenter
    participant O as PluginOrchestrator
    participant R as RegistersManager
    participant P as HikvisionCameraPlugin
    participant S as DeviceSession
    participant W as поток-владелец
    participant N as ProfileRunner
    participant M as MvsPort
    participant D as MvCamera и DLL
    G->>O: register_update exposure_time, set_parameters presenter.py:97
    O->>R: set_field_value, plugin_orchestrator.py:879
    R->>P: колбэк подписки _on_field_update, manager.py:252
    P->>P: _apply_policy restart, _changed_steps: build_plan дважды
    P->>S: apply steps, policy restart
    S->>S: _pending по полю, в _Box одна команда _drain
    Note over G,S: системный поток процесса вернулся, порт не тронут
    M-->>W: get_frame вернулся, кадр или None
    W->>S: _poll_box, _execute, _drain
    Note over W,M: в CAPABILITIES нет live_write и restart_regrab, driver.py:63
    W->>M: _regrab: stop_grabbing, close, open
    W->>N: apply_plan весь run цикла
    N->>M: _port_call set_param
    M->>D: MV_CC_SetFloatValue ExposureTime
    N->>M: _port_call get_param, within_tolerance
    W->>M: start_grabbing
    W->>P: on_timing regrab, затем _sync_events
    P->>P: state_proxy.merge params, params_status, param_errors
```

Счёт уровней от `_on_register_update` до DLL (критерий 2):
1. `PluginOrchestrator._on_register_update` (`plugin_orchestrator.py:855`).
2. `RegistersManager.set_field_value` (`plugin_orchestrator.py:879`; колбэки — `manager.py:252`).
3. `CameraDevicePlugin._on_field_update` (`plugin_base.py:288`); внутри `_changed_steps` дважды строит `build_plan` (`:251-273`).
4. `DeviceSession.apply` -> ящик (`session.py:363-384`). Здесь очередь и переход в поток-владелец.
5. `_poll_box` -> `_execute` (`session.py:664-694`).
6. `_drain` (`session.py:708-732`).
7. `_regrab` (`session.py:741-776`).
8. `ProfileRunner.apply_plan` (`profiles.py:83`).
9. `ProfileRunner.apply_step` (`profiles.py:98`).
10. `DeviceSession._port_call` — запись для сторожа (`session.py:438-447`).
11. `MvsPort.set_param` (`driver.py:304`).
12. `MvCamera.MV_CC_SetFloatValue` -> ctypes DLL (`sdk/bindings.py:338`).

Каждый уровень несёт гарантию: один владелец, слияние правок, проверка чтением, сторож. Лишних по функции уровней я не нашёл.
Два кандидата на сокращение: двойной `build_plan` в `_changed_steps` и перезахват `close`/`open` у MVS вместо записи на ходу. Второй кандидат зависит от опыта H1 на приборе.
Что скрыто: путь команды `apply_params`. Он делает тот же `set_field_value` на каждое поле (`plugin_base.py:772-777`) и дальше идёт по этой же диаграмме.

## 5. Что на ядре и что мимо ядра

```mermaid
flowchart LR
    CORE{{"ядро camera_device: DevicePort, DeviceSession, CameraDevicePlugin"}}
    subgraph ON["на ядре"]
        HIKP["hikvision: HikvisionCameraPlugin и драйвер mvs - main, слияние 6cb212213"]
        FAKEP["camera_device с driver fake - рецепт camera_device_demo"]
    end
    subgraph OFF["мимо ядра"]
        CRS["code_reader_sdk: свой SdkCodeReader - 3.1 и 3.2 DEFERRED, вне 1.0"]
        CSB["camera_service backend hikvision: HikvisionCamera - 4.5 P2 PENDING"]
        DHB["device_hub HikvisionDriver: open по serial - 4.6a-d P1 PENDING"]
        DHE["device_hub plugin: core.discovery.enum_devices"]
        PHG["phone_gateway: свой seq_id - в плане нет"]
        SAPP["sdk_app: HikvisionCamera - FROZEN, ручной запуск"]
    end
    subgraph NONE["нет в коде"]
        REG["реестр драйверов - 5.1 P1"]
        OCV["драйвер opencv - 5.2 P1"]
        MIR["CameraMirrorDriver - 4.6b P1"]
    end
    OLD[("Services/hikvision_camera/core/* - старый путь")]
    HIKP --> CORE
    FAKEP --> CORE
    CSB --> OLD
    DHB --> OLD
    DHE --> OLD
    SAPP --> OLD
    HIKP -.->|FrameConverter.resize| OLD
    DHB -. та же камера .- HIKP
    CSB -. та же камера .- HIKP
```

Статусы из кода и `plan.md`:
- `hikvision` на ядре: `plugin.py:26` наследует `CameraDevicePlugin`. Пять рецептов указывают `plugin_name: hikvision`.
- `code_reader`: 0 строк `camera_device` (`git grep -n camera_device -- Services/code_reader`). План — `plan.md:101-102`, DEFERRED.
- `camera_service`: `backends/hikvision.py:17-20` импортирует `HikvisionCamera`, `:67` создаёт её. План — `plan.md:140`.
- `device_hub`: `HikvisionDriver.connect` создаёт `HikvisionCamera()` и зовёт `open` (`hikvision_driver.py:67-79`); kind `hikvision` — `kinds.py:170`. План — `plan.md:120-124`.
- `phone_gateway`: свой `seq_id` (`plugin/plugin.py:163`); импортов ядра 0. В плане нет: это другой источник, не камера SDK.

Что скрыто: включён ли kind `hikvision` в `devices.yaml` стенда и подключает ли хаб его сам. Файл данных вне git, я его не читал.

## 6. Риски

```mermaid
quadrantChart
    title Риски системы камер, суждение по коду
    x-axis Низкая вероятность --> Высокая вероятность
    y-axis Лёгкие последствия --> Тяжёлые последствия
    quadrant-1 Чинить первым
    quadrant-2 Следить
    quadrant-3 Терпимо
    quadrant-4 Раздражает
    Хаб открывает камеру: [0.45, 0.9]
    Пауза кадров при правке: [0.9, 0.55]
    Вкладка мимо GUI-менеджера: [0.8, 0.4]
    GainAuto не управляется: [0.5, 0.45]
    Второй вендор дороже: [0.6, 0.5]
    Старый путь core ломает плагин: [0.3, 0.6]
    Документы устарели: [0.95, 0.2]
```

Координаты — моё суждение, не замер. Вероятность «хаб открывает камеру» зависит от данных `devices.yaml`, которые я не читал.
Слабые места по этим рискам — в [02-weaknesses.md](02-weaknesses.md).
