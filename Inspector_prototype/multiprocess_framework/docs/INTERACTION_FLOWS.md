# Interaction Flows — Цепочки взаимодействия

**Назначение:** последовательности вызовов между модулями для ключевых сценариев. Mermaid + псевдокод. Документ отвечает на вопрос «*что происходит, когда…*».

> **Формат:** для каждого сценария — диаграмма + комментарии по шагам. Для полного описания модуля — см. [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) и `modules/<X>/README.md`.

---

## Сценарий 1 — Запуск системы

Пользователь запускает `python my_app.py` с `SystemLauncher`.

```mermaid
sequenceDiagram
    participant U as User main.py
    participant SL as SystemLauncher
    participant PS as ProcessSpawner
    participant SRM as SharedResourcesManager
    participant PMP as ProcessManagerProcess<br/>(в OS Process)
    participant PR as ProcessRegistry
    participant Child as Child Process<br/>(run_process_function)

    U->>SL: SystemLauncher(processes=[(name, dict), ...])
    U->>SL: .run()
    SL->>PS: launch_orchestrator()
    PS->>SRM: создать SharedResourcesManager
    PS->>PMP: Process(target=ProcessManagerProcess.run, args=(srm, configs))
    PS-->>U: signal handlers (SIGINT/SIGTERM) → stop_event
    PS->>PS: wait()  блокирует MainProcess
    PMP->>PMP: initialize() (super = ProcessModule.initialize)
    loop для каждого пользовательского процесса
        PMP->>SRM: register_process(name, config)
        Note over SRM: создаёт Queue/Event<br/>сохраняет в ProcessStateRegistry<br/>конфиг → ConfigStore
        PMP->>PR: create_and_register(name, class_path, config, priority)
        PR->>PR: build_bundle(queues, config, custom, routing_map)
        PR->>Child: Process(target=run_process_function, args=(class_path, name, stop_event, bundle))
        PR->>Child: process.start()
    end
    Child->>Child: _build_shared_resources_from_bundle()
    Child->>Child: srm.reinitialize_in_child()
    Child->>Child: _load_process_class(class_path)
    Child->>Child: ProcessClass(name, srm, config)
    Child->>Child: process.initialize()
    Child->>Child: process.run() ← основной цикл
```

**Ключевые моменты:**
1. **SystemLauncher** принимает только `dict` — Dict at Boundary.
2. **ProcessSpawner** — минималист (ADR-PM-002): только SRM, без `ConfigManager/LoggerManager/ErrorManager`. Стандартные подсистемы создаёт сам `ProcessManagerProcess` как `ProcessModule`.
3. **ProcessRegistry** строит **per-process `stop_event`** (ADR-PM-001) — остановка одного не задевает остальных.
4. **bundle** — pickle-safe `dict` с кодом контракта в `bundle_contract.py` (ADR-PM-003).
5. **`run_process_function`** — top-level (pickle-safe), не метод. Восстанавливает SRM в дочернем процессе через `reinitialize_in_child()`.

---

## Сценарий 2 — Отправка сообщения (COMMAND)

Процесс A отправляет команду процессу B.

```mermaid
sequenceDiagram
    participant WA as Worker (Process A)
    participant MA as MessageAdapter
    participant RA as RouterManager(A)
    participant Q as Queue (SRM)
    participant RB as RouterManager(B)
    participant CM as CommandManager(B)
    participant H as handler

    WA->>MA: msg = adapter.command(targets=["B"], command="x", args={...})
    Note over MA: Message(SchemaBase)<br/>sender=A, type=COMMAND
    WA->>RA: router.send(msg)
    RA->>RA: AsyncSender.put(msg, priority)
    Note over RA: фоновый thread читает queue
    RA->>RA: _send_middleware(msg)
    RA->>RA: _resolve_channel(msg) → channel_dispatcher
    RA->>Q: channel.send(msg.to_dict())
    Note over Q: Dict at Boundary<br/>plain dict в multiprocessing.Queue

    RB->>RB: AsyncReceiver.poll() (фоновый thread)
    RB->>Q: queue.get_nowait()
    RB->>RB: _recv_middleware(raw_dict)
    RB->>RB: msg = Message.from_dict(raw_dict)
    RB->>RB: message_dispatcher.dispatch(msg, key="type")
    RB->>CM: handle_command(msg)
    CM->>CM: dispatcher.dispatch(msg, key="command")
    CM->>H: handler(msg.data["args"])
    H-->>CM: result
    Note over CM: опционально — adapter.response(...)
```

**Ключевые моменты:**
1. **MessageAdapter** фиксирует `sender` один раз (избавляет от дублирования).
2. **AsyncSender** — отдельный thread с `PriorityQueue`. Отправка сразу возвращается, реальная запись — позже.
3. **Channel resolver:** `RouterManager.channel_dispatcher` (он же `CRM._dispatcher`) возвращает имя канала по сообщению. Handler возвращает имя, а не результат записи (ADR-154).
4. **Dict at Boundary:** в `Queue` всегда `dict`, не `Message`-объект. На стороне B — `Message.from_dict()`.
5. **Двухуровневая диспетчеризация на B:** `message_dispatcher` (по `type`) → `CommandManager.dispatcher` (по `command`).

---

## Сценарий 3 — Изменение поля регистра с FieldRouting

Frontend меняет поле регистра → backend получает уведомление автоматически.

```mermaid
sequenceDiagram
    participant UI as Виджет
    participant Br as FrontendRegistersBridge
    participant RM as RegistersManager
    participant RC as RegistersContainer
    participant Cb as send_callback
    participant Rt as RouterManager
    participant Bk as Backend Process

    UI->>Br: user input (fps=60)
    Br->>RM: set_field_value("CameraRegister", "fps", 60)
    RM->>RC: validate_field("CameraRegister", "fps", 60)
    RC-->>RM: ok
    RM->>RC: update("CameraRegister", "fps", 60)
    RM->>RM: notify field observers (UI subscribers)
    RM->>RM: resolve_dispatch_targets("CameraRegister", "fps")
    Note over RM: читает FieldRouting<br/>channel="camera_settings"<br/>process_targets=["camera"]
    RM->>Cb: send_register_message("CameraRegister", "fps", 60, sender)
    Cb->>Rt: msg = adapter.data(targets=["camera"], data_type="register_update", data={...})
    Cb->>Rt: msg.set_channel("camera_settings")
    Cb->>Rt: router.send(msg)
    Rt-->>Bk: ... (см. Сценарий 2)
    Bk->>Bk: handler принимает register_update
```

**Ключевые моменты:**
1. **Один источник истины:** `FieldRouting` декларирован в коде регистра один раз; `RegistersManager` использует его автоматически.
2. **Граница frontend / backend:** UI не знает про IPC — `RegistersManager` через `send_callback` делегирует в `RouterManager`.
3. **Two-step dispatch:** сначала observers внутри процесса (sync), потом fan-out по `process_targets`.

---

## Сценарий 4 — Graceful shutdown

Пользователь нажимает Ctrl+C.

```mermaid
sequenceDiagram
    participant OS as OS Signal
    participant PS as ProcessSpawner
    participant PMP as ProcessManagerProcess
    participant PM as ProcessMonitor
    participant PR as ProcessRegistry
    participant Child as Child Processes
    participant W as Workers

    OS->>PS: SIGINT / SIGTERM
    PS->>PS: _signal_handler() (НЕ sys.exit)
    PS->>PS: stop_event.set()  (главный)
    PS->>PMP: stop_event передан в bundle  (главный)
    PMP->>PMP: shutdown()
    PMP->>PM: stop()
    Note over PM: останавливает heartbeat-thread
    PMP->>PR: stop_all(timeout=5)
    loop для каждого процесса
        PR->>Child: stop_events[name].set()
        PR->>Child: process.join(timeout=5)
        alt Процесс жив
            PR->>Child: process.terminate()  (SIGTERM)
            PR->>Child: process.join(timeout=5)
            alt Всё ещё жив
                PR->>Child: process.kill()  (SIGKILL)
            end
        end
    end
    Child->>W: stop_event сигнализирует воркерам
    W->>W: while not stop_event.is_set(): break
    Child->>Child: process.shutdown()
    Note over Child: WorkerManager.stop_all()<br/>RouterManager.shutdown()<br/>LoggerManager.flush()
    PMP->>PMP: super().shutdown()  (ProcessModule cleanup)
    PS-->>OS: exit code 0
```

**Ключевые моменты:**
1. **Никакого `sys.exit()` в signal handler** (ADR-PM-006). Только `stop_event.set()`. Это позволяет корректно завершить с записью данных.
2. **Per-process events** — остановка по одному.
3. **Двойной таймаут + kill():** при зависшем процессе система гарантированно закрывается за 5–10 сек.
4. **Воркеры обязаны проверять `stop_event` в каждой итерации `while`** (паттерн `while not stop_event.is_set():`). Без этого — terminate.

---

## Сценарий 5 — Cross-process конфигурация

Процесс A читает изменение конфига, обновлённое в процессе B.

```mermaid
sequenceDiagram
    participant B as Process B
    participant CMb as ConfigManager(B)
    participant CS as ConfigStore (SRM)
    participant A as Process A
    participant CMa as ConfigManager(A)

    Note over B: пользователь изменил настройку
    B->>CMb: config.set("debug", true)
    B->>CMb: cm.sync_config("app")
    CMb->>CS: config.data → dict
    Note over CS: ConfigStore — pickle-safe dict в SRM
    A->>CMa: cm.load_config_from_storage("app")
    CMa->>CS: dict
    CMa->>CMa: Config.from_dict(...)
    CMa->>CMa: notify subscribers
    Note over CMa: callbacks: на изменение поля<br/>обновить runtime-параметры
```

**Ключевые моменты:**
1. **Dict at Boundary** для конфига — `ConfigStore` хранит plain dict, не Pydantic.
2. **Sync — pull-модель:** другие процессы должны явно вызвать `load_config_from_storage()`. Можно автоматизировать через `EventManager` (broadcast «config.updated») + подписка в `A`.

---

## Сценарий 6 — Request / Response с correlation_id

Синхронный запрос между процессами.

```mermaid
sequenceDiagram
    participant A as Process A
    participant Aa as MessageAdapter(A)
    participant R as RouterManager
    participant B as Process B
    participant Ba as MessageAdapter(B)

    A->>Aa: req = adapter.request(targets=["B"], request_type="get_x", query={...}, timeout=5.0)
    Note over Aa: req.id = uuid4()<br/>(== correlation_id)
    A->>A: pending[req.id] = Future()
    A->>R: router.send(req)
    R->>B: ... доставка ...
    B->>B: handler принимает REQUEST
    B->>Ba: reply = adapter.response(targets=[A.sender], request_id=req.id, result=...)
    B->>R: router.send(reply)
    R->>A: ... доставка ...
    A->>A: handler принимает RESPONSE
    A->>A: pending[reply.request_id].set_result(reply.result)
```

**Ключевые моменты:**
1. **`request_id`** в RESPONSE равен `id` исходного REQUEST.
2. **Таймаут** реализуется на стороне A (`Future.get(timeout=...)`), не во фреймворке.
3. **Pattern не блокирует:** worker thread A продолжает работать, ждёт async future.

---

## Сценарий 7 — Error → Logger → ErrorManager

Ошибка в worker'е автоматически проходит через цепочку.

```mermaid
sequenceDiagram
    participant W as Worker
    participant PM as ProcessModule (ObservableMixin)
    participant EM as ErrorManager
    participant LM as LoggerManager
    participant FC as FileChannel<br/>(critical.log)
    participant SC as Scope-channel<br/>(business.log)

    W->>W: try: ... except Exception as e:
    W->>PM: self._track_error(e, context={"worker": "capture"})
    PM->>EM: track_error(e, context)
    EM->>EM: log_exception(e, context)
    Note over EM: уровень CRITICAL
    EM->>EM: log() override → severity routing
    EM->>FC: channel.send(LogRecord(level=CRITICAL, ...))
    Note over FC: FileChannel — critical.log
    EM->>LM: super().log(DEBUG/INFO scope-based)
    Note over LM: для DEBUG/INFO — обычный scope routing
```

**Ключевые моменты:**
1. **`_track_error`** — единый вход через `ObservableMixin`. Никакого `print(traceback)`.
2. **Severity routing:** WARNING/ERROR/CRITICAL → отдельные файлы по `_level_to_channel`. DEBUG/INFO — fallback на scope-based parent.
3. **Traceback** включается автоматически в `log_exception()`.

---

## Сценарий 8 — Console God Mode (interactive)

Пользователь в терминале набирает команду.

```mermaid
sequenceDiagram
    participant U as Пользователь
    participant Term as Terminal (UnixConsole)
    participant CMg as ConsoleManager
    participant CA as ConsoleAdapter
    participant Cmd as CommandManager
    participant H as Handler
    participant R as RouterManager

    U->>Term: stdin: "reg set CameraReg.fps 60"
    Term->>CMg: input_thread reads line
    CMg->>CA: callback(raw_line)
    CA->>CA: parse → {command="reg", args=["set", "CameraReg.fps", "60"]}
    CA->>Cmd: handle_command({command, args})
    Cmd->>H: RegisterCommandHandler.set_field("CameraReg", "fps", "60")
    H->>R: ... fan-out через FieldRouting (см. Сценарий 3)
    H-->>Cmd: result
    Cmd-->>CA: result
    CA->>CMg: write(result_text)
    CMg->>Term: stdout
```

**Ключевые моменты:**
1. **God Mode** — это конфигурация (`ConsoleProcessConfig`), не отдельный класс (ADR-CM-002).
2. **Парсинг raw → dict** — в `ConsoleAdapter`, не в `CommandManager`.
3. **Один процесс** для God Mode-консоли запускается через `launcher.add_process(*process(ConsoleProcessConfig()))`.

---

## Полные точки для отладки

| Что отлаживать | Где включить логирование |
|----------------|--------------------------|
| Отправка сообщений | `RouterManager` (BUSINESS scope), `AsyncSender` (DEBUG) |
| Получение сообщений | `AsyncReceiver`, `message_dispatcher` (DEBUG) |
| Регистры | `RegistersManager` (BUSINESS scope) |
| ConfigStore sync | `ConfigManager` (DEBUG) |
| Жизненный цикл процессов | `ProcessRegistry` (SYSTEM scope), `ProcessMonitor` (DEBUG) |
| Воркеры | `WorkerManager` (DEBUG) |
| Команды | `CommandManager` (BUSINESS scope) |
| SQL | `SQLManager` (PERFORMANCE для timing, BUSINESS для запросов) |
