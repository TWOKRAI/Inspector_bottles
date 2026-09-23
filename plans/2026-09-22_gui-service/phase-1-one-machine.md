# Phase 1 — Пульт на одной машине, один бэкенд

Часть плана [`plan.md`](plan.md). Цель фазы: сегодняшний GUI работает **вне** дерева процессов,
подключаясь к инспектору через `SocketChannel`, с теми же вкладками и теми же дисплеями. Ничего
не переносится — добавляются транспорт и точка входа. Фаза доказывает гипотезу «driver уже показал
совместимость формы сообщений» или опровергает её на первом же шаге, а не в line-sim Ф6.

---

### Task 1.1 — Инвентарь разъёмов GUI ↔ дерево: числа, baseline

> **[DONE 2026-09-22]** — [`docs/audits/2026-09-22_gui-seams-inventory.md`](../../docs/audits/2026-09-22_gui-seams-inventory.md). 12 разъёмов: аналог есть у 4, частично у 4, нет у 4; блокеров Ф1 — 2 (кадры → 1.3, `_fence` → 1.2). Baseline только по тестам (edge case плана): `frontend_module` 574/0/0, `multiprocess_prototype/frontend` **2470/0/3**. **fps не снят** — нет синтетического рецепта с процессом `gui`; число для 1.4 остаётся открытым.

**Level:** Middle+ (Opus, read-only)
**Assignee:** investigator
**Goal:** отчёт с **числами**: какими разъёмами виджеты и `frontend_module` касаются дерева
процессов напрямую, у каких из них уже есть сокетный аналог в `backend_ctl`, и каковы baseline
(fps дисплея во встроенном GUI, число зелёных тестов pytest-qt), с которыми Task 1.4 будет сравниваться.

**Контекст:** план стоит на непроверенном допущении «GUI по сокету = GUI по очереди». Проверенные
факты на 2026-09-22 — только грепом: `CommandSender` — 29 файлов в `multiprocess_prototype/frontend`,
`StateProxy/StateStore` — 20 файлов там же + 2 в `frontend_module`. Что ещё держит GUI внутри дерева
(`FrameShmMiddleware` в `GuiProcess`, `DataReceiverBridge`, `AppServices` DI, `ConfigStore`/регистры,
`intent_taps`, `DisplayRegistry.reload`, telemetry read-model) — не посчитано.

**Files:**
- НОВЫЙ `docs/audits/2026-09-XX_gui-seams-inventory.md` — отчёт (дата — день выполнения)
- Код не меняется.

**Steps:**
1. Составить таблицу разъёмов: для каждого — файлы/число вхождений (grep, не память), направление
   (GUI→дерево / дерево→GUI), тип трафика (команда / стейт / кадр / лог / регистр / телеметрия),
   **есть ли аналог в `backend_ctl`** (`driver.py`: `send_command`, `state_*`, `set_register`,
   `log_tail`, `ui_tap`, `watch_like_gui`, `telemetry_*`) — да/нет/частично, с номером строки.
2. Найти все места, где `frontend_module`/`multiprocess_prototype/frontend` предполагают, что живут
   в `ProcessModule` (обращение к `self.router`, `ctx`, `process_name`, прямой `RouterManager`,
   `multiprocessing.Queue`, SHM-хендлы без `shm_actual_name`) — список `файл:строка`.
3. Снять baseline на стенде: `frontend/run.py` на рецепте с синтетическим источником
   (`dualcam_synth` или `g1_perf_probe` — что поднимается без железа), 60 с: fps дисплея из
   `introspect_router_stats`/счётчика DisplaysTab; `pytest -q` по `frontend_module/tests` и
   `multiprocess_prototype/frontend` — число passed/skipped/failed.
4. Вердикт одной строкой: «сокетный аналог есть у N из M разъёмов; блокеров для Ф1 — K», с перечнем
   блокеров (то, чего в протоколе сокета нет и что придётся добавить в Task 1.2/1.3).

**Acceptance criteria:**
- [x] Отчёт содержит таблицу ≥ 6 разъёмов, каждый — с числом файлов (из grep, команда приведена) и
      колонкой «аналог в `backend_ctl`: да/нет/частично + `driver.py:строка`».
- [x] Список in-tree допущений — `файл:строка`, каждая строка существует (проверяется скриптом
      `sed -n` по списку, 0 несуществующих).
- [~] Baseline записан числами (fps — не снят, см. отметку DONE): fps дисплея (среднее за 60 с, ≥ 2 знака), passed/skipped/failed
      двух тестовых наборов, SHA `main`, на котором снято.
- [x] Отчёт заканчивается разделом «что не проверено» (не пустым).

**Out of scope:** правки кода; рекомендации по переносу файлов (это rework).
**Edge cases:** стенд не поднимается без железа ни на одном рецепте — зафиксировать явно и снять
baseline только по тестам; это не провал задачи.
**Dependencies:** нет.
**Module contract:** none (отчёт).

---

### Task 1.2 — Сокетный транспорт для GUI

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** виджеты шлют команды и читают стейт через сокет **тем же интерфейсом**, что сейчас через
очередь: `RemoteCommandSender` и `RemoteStateProxy` — реализации существующих контрактов поверх
клиента `SocketChannel`; Пульт штампует `_fence` как встроенный GUI (закрыть G1).

**Контекст:** клиентская половина уже есть в `backend_ctl/transport.py` (`_TransportMixin`:
`connect`, `request` с ожиданием по `request_id`, `connection_lost`) и `backend_ctl/subscriptions.py`
(durable-подписки). Но `frontend_module` — слой framework и не может импортировать `backend_ctl`
(dev-пакет верхнего уровня). Решение плана: wire-клиент переезжает в
`router_module/channels/socket_client.py`, `backend_ctl.transport` — тонкий реэкспорт; тесты
`backend_ctl` (число из `pytest backend_ctl -q` ДО правки) — страж, что ничего не сломано.
Это ранняя часть rework Q8 (`backend_ctl → tooling/`): клиент канала — код фреймворка, остальной
`backend_ctl` едет позже как решено там.

**Мидлварь — уточнено по `backend_ctl/AGENTS.md` («Чего драйвером проверить нельзя»), 2026-09-22:**
receive-мидлварь **дочернего** процесса на сокетном пути отрабатывает штатно — обхода нет, чинить
нечего. Два настоящих разрыва: (1) `make_fence_stamp_middleware` висит только в дочерних
`ProcessModule` (`process_module.py:654`), встроенный `GuiProcess` — дочерний и штампует `_fence`;
Пульт — внешний и не штампует, фильтр пропускает его легаси-веткой (`token.py:124-126`) — после
рестарта бэкенда устаревшие команды Пульта не отсекутся как stale; (2) у хаба (ProcessManager)
receive-мидлвари нет **ни для кого** — не цель этого плана (см. G1b в `context.md`).
**Транспортные болезни `SocketChannel`:** второй клиент — **уже решено** (`8fae4034`, ADR-PMM-026,
`session_isolation` дефолт ON); HOL-блокировка read-цикла и `sendall` — **Task 1.3a этого плана**
(перенесены из remediation Ф3 решением владельца 2026-09-24). Эта задача их **не** дублирует и
**не ждёт**: 1.2 — клиентская половина, 1.3a — серверная, файлы не пересекаются.

**Files:**
- НОВЫЙ `multiprocess_framework/modules/router_module/channels/socket_client.py` — `SocketClient`
  (перенос `_TransportMixin` + минимальная поверхность: `connect/close/request/send/subscribe`,
  колбэк на push-сообщения, `connection_lost`, реконнект с восстановлением подписок). **Qt-free**
  (домен для rework 2б.2 — ядро)
- `backend_ctl/transport.py` — реэкспорт из фреймворка, поведение и публичные имена без изменений
- НОВЫЙ `multiprocess_framework/modules/frontend_module/bridge/remote_command_sender.py` —
  `RemoteCommandSender` (тот же Protocol, что `CommandSender`); штамп `_fence` из `capabilities`
  тем же кодом, что `make_fence_stamp_middleware` (импорт, не копия). **Qt-free**
- НОВЫЙ `multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py` —
  `RemoteStateProxy` (`set/get/subscribe` через `state.*` сообщения протокола). **Qt-free**
- `backend_ctl/AGENTS.md` — абзац «внешний GUI и fence» рядом с таблицей ограничений
- Тесты: `router_module/tests/test_socket_client.py`, `frontend_module/tests/test_remote_*.py`

**Steps:**
1. `pytest backend_ctl -q` — записать число passed (baseline). Перенести `_TransportMixin` в
   `socket_client.py` как класс `SocketClient`; `backend_ctl/transport.py` импортирует и реэкспортирует.
   Прогнать `pytest backend_ctl -q` — число не меньше baseline, 0 failed.
2. `RemoteCommandSender`: реализовать интерфейс `CommandSender` (какой именно Protocol — по отчёту 1.1),
   сообщения строить билдерами протокола (не руками). Ответы — по `request_id`. Fence: при
   подключении взять текущий эпох/токен из `capabilities` (если его там нет — это находка: добавить
   в `capabilities` на хосте, одно поле) и штамповать каждое исходящее сообщение той же функцией,
   что дочерние процессы.
3. `RemoteStateProxy`: `get` — запрос; `subscribe(pattern, cb)` — durable-подписка (восстанавливается
   после реконнекта); `set` — запрос с подтверждением. Троттлинг — как на хосте, клиент ничего не
   троттлит сам.
4. Автор пишет hazard-тесты: (а) реконнект в момент ожидания ответа — `request` получает понятную
   ошибку, не висит; (б) подписки восстановлены после реконнекта — событие после реконнекта доходит;
   (в) push-колбэк вызывается не в потоке чтения сокета, а через переданный диспетчер (для Qt —
   `QueuedConnection`), иначе виджеты трогаются из чужого потока; (г) после реконнекта штамп
   берётся заново — команда со старым эпохом не уходит.

**Acceptance criteria:**
- [ ] `pytest backend_ctl -q` — passed ≥ baseline из Step 1, 0 failed; `from backend_ctl.transport
      import <прежние имена>` работает.
- [ ] In-process тест: `SocketChannel(port=0)` + `RouterManager` + процесс-стаб с командой `ping`;
      `RemoteCommandSender.send("ping")` → ответ `{"status":"ok"}` за < 1 с.
- [ ] **Fence-паритет:** сообщение от `RemoteCommandSender` несёт `_fence` того же вида, что
      сообщение встроенного `GuiProcess` (сравнение структуры штампа); дочерний процесс-стаб с
      включённым fence-фильтром принимает команду Пульта с актуальным эпохом и **отвергает** команду
      с устаревшим (парный тест, счётчик отказов фильтра +1).
- [ ] `RemoteStateProxy.subscribe("a.*", cb)`; хост делает `set("a.b", 1)` → `cb` вызван с `("a.b", 1)`
      за < 1 с; после разрыва и восстановления соединения `set("a.c", 2)` → `cb` вызван снова (подписка
      пережила реконнект).
- [ ] Разрыв соединения во время `request(...)` → исключение/ошибка за ≤ таймаут, не зависание
      (тест в daemon-потоке с join-дедлайном, как требует канон).
- [ ] Ни один файл `multiprocess_framework/**` не импортирует `backend_ctl` (`grep -rn "backend_ctl"
      multiprocess_framework --include=*.py` → 0 вне тестов и докстрингов); новые файлы не импортируют
      `PySide6` (`grep` → 0); `sentrux check .` — все правила зелёные.

**Out of scope:** кадры (1.3), точка входа Пульта (1.4), аутентификация (2.2), судья на хабе (G1b),
HOL/`sendall`/границы кадров (Task 1.3a), второй клиент (сделан `8fae4034`).
**Edge cases:** два `RemoteCommandSender` на одном соединении (мультиплексирование по `request_id`);
сообщение хоста без `request_id` (push) — идёт в колбэк подписок, не теряется молча.
**Dependencies:** Task 1.1 (список разъёмов и Protocol'ов, которые реализуем). Task 1.3a (HOL) —
не к старту, а к старту 1.4 (см. «Транспортные болезни» выше); remediation 3.2 сделана.
**Module contract:** impl-only (`frontend_module`) + new-lite (`socket_client.py` с докстрингом-контрактом).

---

### Task 1.3 — Кадры между деревьями на одной машине: мост + SHM по имени

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** третье воплощение `gui`-слота — `BridgeGuiProcess`: принимает data-трафик как headless,
но публикует **дескрипторы** кадров (имя SHM-сегмента, индекс слота, форма, dtype, seq) подписчикам
сокета; на стороне Пульта `RemoteFrameSource` открывает сегмент по имени и копирует кадр. Байты
кадра сокет не пересекают (Dict at Boundary и README сокета соблюдены).

**Контекст:** D8 дал слот `gui` с двумя воплощениями (`HeadlessGuiProcess` дренирует,
`GuiProcess` рисует) и overlay, подменяющий класс. Мост — третье. Attach по имени из чужого
процесса — уже существующий fallback в `FrameShmMiddleware.on_receive` («прямое открытие
SharedMemory по `shm_actual_name`»), значит путь кода есть — его нужно вынести в переиспользуемый
клиент, не копировать. Ограничение честно: читатель вне loan-леджера; под `FW_SHM_LOAN_PROTOCOL=1`
слот может быть переиспользован под ним. В v1 Пульт отказывается от SHM при включённом флаге
(читает из `capabilities`) — и **измеряет** торн-кадры, а не обещает их отсутствие.

**Files:**
- НОВЫЙ `multiprocess_prototype/frontend/bridge_process.py` — `BridgeGuiProcess` (рядом с
  `headless_process.py`, тот же контракт процесса)
- НОВЫЙ `multiprocess_prototype/frontend/presentation_bridge.yaml` — overlay: `gui` → `BridgeGuiProcess`
- НОВЫЙ `multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py` —
  `RemoteFrameSource` (подписка на дескрипторы + attach по имени + copy-out + колбэк)
- `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py` — вынести
  attach-по-имени в функцию/класс, используемую и мидлварью, и `RemoteFrameSource` (не копия)
- Протокол подписки: `frames.subscribe/unsubscribe` (по образцу `ui_tap`) — в билдерах протокола и
  в `subscriptions.py` (durable)
- Тесты: `multiprocess_prototype/frontend/tests/test_bridge_process.py`,
  `frontend_module/tests/test_remote_frame_source.py`

**Steps:**
1. Разведать заголовок слота SHM-кольца (`shared_resources_module`): есть ли счётчик поколения /
   seq, по которому читатель может обнаружить перезапись во время копирования. Если есть — читатель
   проверяет его до и после копии; если нет — записать в DECISIONS модуля и мерить торн-кадры
   паттерном (Step 5).
2. `BridgeGuiProcess`: как headless принимает data-сообщения; для каждого кадра берёт из конверта
   `shm_actual_name/shm_index/shape/dtype/seq/display_id` и шлёт дескриптор (dict ≤ 300 байт) всем
   активным подписчикам `frames` через роутер (`channel=<сессия сокета>`, как уходят ответы).
   Без подписчиков — ведёт себя ровно как headless (не платит за сериализацию).
3. `RemoteFrameSource`: `subscribe(display_ids, on_frame)`; на дескриптор — attach по имени (кэш
   хендлов по имени), копия слота в свой буфер, колбэк с `np.ndarray` + `seq`. Дедупликация по `seq`.
   При `capabilities.flags.FW_SHM_LOAN_PROTOCOL == true` — отказ с понятной ошибкой (2.1 даст поток).
4. Автор пишет hazard-тест: продюсер пишет быстрее, чем читатель копирует (искусственная задержка в
   колбэке) — читатель пропускает кадры, но не падает и не блокирует продюсера (счётчик кадров
   продюсера растёт с прежней скоростью).
5. Измерение торн-кадров: продюсер стампует в каждый кадр один и тот же счётчик в четырёх углах;
   читатель считает кадры, где углы разошлись. 1000 кадров 640×480 на localhost — число в отчёт задачи
   и в DECISIONS.

**Acceptance criteria:**
- [ ] Бэкенд поднят с `INSPECTOR_PRESENTATION=frontend/presentation_bridge.yaml` на рецепте с
      синтетическим источником: `introspect_plugins`/`system_overview` показывают процесс `gui`
      классом `BridgeGuiProcess`; без подписчиков счётчик `received` роутера у `gui` растёт (дренаж
      работает как у headless).
- [ ] Внешний скрипт (вне дерева) через `RemoteFrameSource.subscribe(["main"], cb)` получает за 10 с
      ≥ 0.8 × fps продюсера (fps — из `introspect_router_stats`, не из конфига), кадры формы
      `(h, w, 3)` `uint8`.
- [ ] Кадры **побитово** равны продюсерским: продюсер стампует счётчик в углах; у ≥ 99.9 % принятых
      кадров четыре угла совпадают; число расхождений напечатано (0 — не требуется, требуется число).
- [ ] С `FW_SHM_LOAN_PROTOCOL=1` на бэкенде `RemoteFrameSource.subscribe` возвращает ошибку с текстом,
      называющим флаг, а не тихо отдаёт кадры.
- [ ] Отписка (`unsubscribe`) → мост перестаёт слать дескрипторы этой сессии за ≤ 1 с (счётчик
      отправленных дескрипторов замирает), продюсер не замечает.
- [ ] `frontend/run.py` (воплощение с Qt) и `--headless` работают как прежде — снапшот-тесты
      топологии зелёные, число из 1.1.

**Out of scope:** кадры по сети (2.1); выбор транспорта в Пульте (2.1); loan-протокол для внешнего
читателя (после v1 — либо мост держит собственное кольцо-копию, либо леджер учится внешним читателям).
**Edge cases:** сегмент с именем из дескриптора уже не существует (бэкенд перезапустил процесс) —
`RemoteFrameSource` логирует и ждёт следующий дескриптор, не падает; два дисплея с одним
`shm_actual_name` (один продюсер — два дисплея) — дескрипторы различаются `display_id`.
**Dependencies:** Task 1.2 (подписки по сокету).
**Module contract:** new-lite (`BridgeGuiProcess`, `RemoteFrameSource` — докстринги-контракты, Pre/Post).

---

### Task 1.3a — Серверный транспорт `SocketChannel`: без head-of-line, медленный клиент не держит запись

> **Перенесена из [`backend-ctl-review-remediation`](../backend-ctl-review-remediation.md) Ф3 (Task 3.1 + 3.3)
> решением владельца 2026-09-24.** Причина: к двери подключается долгоживущий второй легитимный
> клиент — Пульт. Для dev-драйвера HOL — неудобство, для Пульта — продуктовый дефект («дисплеи замирают,
> пока сосед ждёт `send_command(timeout=60)`»). Remediation 3.2 сделана (`8fae4034`), в remediation Ф3
> больше ничего не осталось.

**Level:** Senior+ (Opus) · **Assignee:** teamlead
**Layer:** framework. **Files:** `multiprocess_framework/modules/router_module/channels/socket_channel.py`,
`multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py` (+ тесты router_module).
Номера строк из remediation (`socket_channel.py:277-323` → `socket_bridge_adapter.py:86`) писались
до 2026-08 — перепроверить по дереву при старте.
**Goal:** один медленный запрос или один медленный читатель не останавливают ни соседние запросы того же
соединения, ни другие соединения.

**Steps:**
1. **«До» самим воспроизвести** (baseline remediation Task 0.1 п.3 и п.6 не снимался — план не
   стартовал): (а) `send_command(timeout=60)` + параллельный `state_get` на том же соединении → время
   ответа второго; (б) то же на втором соединении; (в) клиент, который перестал читать сокет →
   блокируется ли запись остальным клиентам. Числа — в отчёт задачи. Если (в) опровергнута —
   write-часть сжимается до max-line + байт-капа (как предписывала remediation 3.3).
2. HOL: read-цикл только читает и кладёт намерение в per-connection очередь; исполняет воркер-поток
   (паттерн applier из `WatchController`). Порядок ответов внутри соединения — по `request_id`, не по FIFO.
3. Запись: send-timeout на write-путь клиентских сокетов (осознанно, в докстринге — что происходит с
   клиентом по таймауту); max-line-length в обоих `_read_loop` (drop + лог вместо безграничного `buf`);
   байт-кап колец EventHub.

**Acceptance criteria:**
- [ ] Live-пара HOL: до (шаг 1а) второй запрос ждёт долгую команду; после — отвечает за обычное время
      (число «до/после» в отчёте, порог — p95 baseline `state_get` без нагрузки × 2).
- [ ] Live-пара «медленный читатель»: клиент перестал читать → остальные клиенты продолжают получать
      ответы и push'и; медленный отключён по таймауту с записью в лог, не висит.
- [ ] Unit: оверсайз-кадр дропнут с логом, соединение живо.
- [ ] Hazard-тесты автора: гонка «соединение закрыто, пока воркер исполняет намерение» (ответ не пишется
      в закрытый сокет, поток воркера завершается); завершение канала при непустой очереди — join с
      дедлайном, без зависания (тест с daemon-потоком и join-дедлайном).
- [ ] Полный suite router_module и `pytest backend_ctl -q` зелёные; существующие reconnect-live зелёные.
- [ ] Sentrux `session_start` до → `session_end` после, без новых циклов.

**Out of scope:** `session_isolation` (сделано), аутентификация (1b.4 / 2.2), клиентская половина (1.2).
**Edge cases:** push без `request_id` при переполненной очереди соединения; клиент отключился
посреди длинного ответа; два долгих запроса подряд на одном соединении (воркер один — второй ждёт
первого, но read-цикл и другие соединения живы; если нужно больше — решение по числам шага 1).
**Dependencies:** нет (параллельно 1.2/1.3 — файлы не пересекаются). Обязательна до старта 1.4.
**Module contract:** impl-only.

---

### Task 1.4 — Автономный Пульт: хост `apps/pult/` + пакет вкладок по имени, без дерева

> **Ред. 2 (2026-09-23), решения владельца «Пульт — отдельный сервис», «разбивать на сервисы и из них
> собирать».** Хост уходит из `multiprocess_prototype/frontend/pult/` в `apps/pult/` и **не импортирует
> прототип** (правило `apps/* ↛ multiprocess_prototype/*`, `.sentrux/rules.toml:128`, без исключения).
> Вкладки инспектора приходят как `GuiAppSpec`, загруженный по имени из конфига хоста. Обоснование —
> [`architecture.md`](architecture.md).

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** `python -m apps.pult --connect 127.0.0.1:8765` поднимает главное окно с тем же набором
вкладок, что `frontend/run.py`: `GuiBootstrap` (фреймворк) + `RemoteGuiRuntime` (фреймворк) +
`GuiAppSpec` инспектора, выбранный по `capabilities.app_id`. `SystemLauncher`/`ProcessManager` в этом
процессе нет, хост прототип не импортирует. Отказоустойчивость в обе стороны доказана числами.

**Предпосылка — frontend-constructor T4.1–T4.4 (обязательна, ред. 2):** T4.1 — дизайн-док
`GuiAppSpec`/стадий (ревью владельца); T4.2 — разборка `run_gui` (~749 строк) на стадии
`identity→theme→runtime→state→tabs→window→timers→show` с характеризацией boot-порядка; T4.3 —
`GuiBootstrap` **новым файлом** в `frontend_module/bootstrap/`; T4.4 — `GuiHostRuntime` вместо
`process._*`, встроенный GUI переходит на `InProcessRuntime`. Все четыре — новые файлы или правки на
месте, окно codemod им не нужно; статусы — в frontend-constructor. **Второго composition root нет**:
у Пульта только своя реализация рантайма.

**Контекст:** это и есть «GUI как сервис» — момент истины плана. Всё, что Task 1.1 назвал in-tree
допущением и что не покрыли 1.2/1.3, всплывёт здесь. Правило задачи: виджеты **не правятся** ради
Пульта; если виджет требует правки — это находка для отчёта и решение, чинить ли виджет (в пользу
обеих сборок) или дать ему адаптер.

**Files:**
- НОВЫЙ `apps/pult/__init__.py`, `__main__.py` (CLI: `--connect host:port` (повторяемый — задел для 3.1),
  `--token` — задел для 2.2, `--log-dir`), `config.yaml` (`gui_packs: {<app_id>: "<модуль>:APP_SPEC"}`),
  `README.md`, `STATUS.md`, `DECISIONS.md`, `tests/`
- НОВЫЙ `multiprocess_framework/modules/frontend_module/bootstrap/remote_runtime.py` — `RemoteGuiRuntime`:
  реализация `GuiHostRuntime` поверх `SocketClient` и `Remote*` из 1.2/1.3; реконнект-контроллер; статус
  соединения для статус-бара шелла. **Qt-free**
- НОВЫЙ `multiprocess_framework/modules/frontend_module/bootstrap/pack_loader.py` — загрузка `GuiAppSpec` по
  строке `модуль:атрибут`, проверка `protocol_version` из `capabilities`, внятная ошибка при несовпадении
- `multiprocess_prototype/frontend/app_spec.py` — `APP_SPEC` инспектора (появляется в T4.3); сборка
  `AppServices` из `runtime`, а не из `process`
- Поля `app_id` и `protocol_version` в `capabilities` на хосте (если их там нет — одно место в
  `backend_ctl_endpoint`)
- Тесты: `apps/pult/tests/` — pytest-qt: сборка окна на фейковом сокетном хосте (in-process
  `SocketChannel`), реконнект; `frontend_module/tests/test_pack_loader.py`
- Правки виджетов — только по находкам, каждая названа в PR-описании

**Steps:**
1. Разведать текущую сборку `AppServices` в `GuiProcess`/`frontend/run.py`: какие зависимости
   инжектируются (sender, state, frames, registry, config). Собрать ту же карту на `Remote*`.
2. `bootstrap.py`: подключение → `capabilities` → `DisplayRegistry.reload` из данных бэкенда →
   окно. Реконнект: экспоненциальная пауза с потолком, индикатор «отключён/подключён», подписки
   восстанавливаются клиентом (1.2).
3. Логи Пульта — `get_std_logger` в `--log-dir` (по умолчанию `INSPECTOR_LOG_DIR`), исключения
   потоков — в лог, не в stderr молча.
4. Автор пишет hazard-тесты: (а) бэкенд недоступен при старте — окно открывается в состоянии
   «отключён», подключается при появлении бэкенда; (б) закрытие окна во время активной подписки —
   процесс завершается за ≤ 3 с (нет висящих потоков клиента).
5. Live: стенд с синтетическим источником, `presentation_bridge.yaml`; Пульт рядом. Снять числа для
   критериев ниже через `backend_ctl` (не глазами).

**Acceptance criteria:**
- [ ] Набор вкладок Пульта == набор вкладок `frontend/run.py` на том же рецепте (список имён
      вкладок, сравнение множествами; допускается дополнительная вкладка «Подключение»).
- [ ] Дисплей `main` в Пульте показывает ≥ 0.8 × baseline fps из Task 1.1 в течение 60 с (счётчик
      кадров виджета / `RemoteFrameSource`), при этом fps продюсера по `introspect_router_stats` не
      упал относительно baseline более чем на 5 %.
- [ ] Команда из GUI Пульта (одна из штатных: пауза/возобновление плагина или запись регистра через
      вкладку настроек) исполняется на бэкенде — подтверждено `introspect_registers`/`get_status`
      через `backend_ctl`, не по виджету.
- [ ] `kill -9` Пульта: счётчики бэкенда (`received`/`sent_ok` продюсера, число процессов) через 10 с
      после убийства продолжают расти/не изменились — бэкенд не заметил.
- [ ] Остановка бэкенда при живом Пульте: Пульт показывает «отключён» за ≤ 5 с, не падает (процесс
      жив, окно отвечает); повторный запуск бэкенда → Пульт подключился сам за ≤ 15 с, дисплей ожил.
- [ ] `frontend/run.py` — регрессии нет: pytest-qt наборы из Task 1.1 дают passed ≥ baseline,
      0 failed.
- [ ] `README.md` Пульта описывает CLI и то, чего Пульт **не** умеет в v1 (сеть, токен, N бэкендов).
- [ ] **Граница хоста:** `sentrux check .` зелёный (правило `apps/* ↛ multiprocess_prototype/*` действует
      на `apps/pult` без исключения); `grep -rn "multiprocess_prototype" apps/pult --include=*.py` → 0 вне
      строк конфига.
- [ ] **Совместимость:** бэкенд с другим `protocol_version` → Пульт показывает обе версии и не рисует
      вкладки (тест на фейковом хосте); неизвестный `app_id` → «нет пакета для приложения <id>».

**Out of scope:** сеть/токен (Ф2), несколько бэкендов (Ф3), вкладка «Подключение» с формой (3.1 —
здесь только `--connect` из CLI).
**Edge cases:** бэкенд без `BACKEND_CTL=1` — Пульт называет причину («дверь закрыта: поднимите бэкенд
с BACKEND_CTL=1»), не «connection refused» голышом; бэкенд с включённым loan-протоколом — дисплеи
не работают, остальные вкладки работают, статус-бар называет причину.
**Dependencies:** Task 1.2, Task 1.3, Task 1.3a; frontend-constructor T4.1–T4.4 (обязательно до старта, ред. 2).
**Module contract:** new-full (`apps/pult` — README + тесты; контракт `GuiAppSpec` — в `frontend_module/bootstrap/interfaces.py`).
