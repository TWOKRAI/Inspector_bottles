# Сервис камер: один сеанс прибора для ID3013, Hikvision и следующих камер (проект)

Статус: **проект, не принят** (Opus reviewer, 2026-10-17). Кода нет. Основание: ревью
`docs/reviews/2026-10-17_codereader-multicamera-opus-review.md` (часть B, находки A1–A3). Решения, которые переживают
задачу, оформить ADR (`/dev:adr`) после ответа владельца (раздел 8).

## 1. Что сейчас

Четыре пути к камере, общего контракта нет:

| Путь | Модель | Параметры прибора | Проблема |
|---|---|---|---|
| `Services/code_reader/core/sdk_reader.py:69` `SdkCodeReader` | свой поток захвата (push) | таблица `_TRIGGER_NODES` (`:43-47`), чтение исходного -> запись -> возврат | возврат из прочитанных исходных ненадёжен (ниже) |
| `Services/hikvision_camera/plugin/plugin.py` | захват в `produce()` под замком (pull, `:163-166`) | только из команд (`:243-266`); при открытии нет | нет ошибок узлов, нет снимка; приватный `self._camera._camera` (`:261`) |
| `Services/hikvision_camera/core/camera.py:96` `HikvisionCamera.open` | state machine | **скрыто** пишет `TriggerMode=Off` при каждом открытии (докстринг `:101`) | запись, которой нет в рецепте |
| `Plugins/sources/camera_service/backends/base.py:11` `CameraBackend` | pull | нет | контракт без параметров и состояния |
| `Services/device_hub/drivers/hikvision_driver.py:66-78` | control-only | `get/set_params` | второй владелец той же камеры; по коду `open(self._serial)` уходит в `open(camera_index: int)` и сравнение `camera_index >= nDeviceNum` (`camera.py:96`, `:127`) — подключение по серийнику, похоже, не работает (не воспроизводил) |

Факты стенда 2026-10-16 (ревью, A1–A3):
- штатный выход приложения сносит процессы читателей через 1,02 с после `system_stop_event` (`TerminateJobObject`);
  возврата режима нет;
- после одного отказа возврата следующий `start()` считает самотриггер «исходным», `Off` теряется (воспроизведено на фейке);
- SDK вернул `0x80020206` на все записи возврата, а следующее открытие прочитало исходные значения: результат записи
  нельзя брать из кода возврата SDK, только из чтения узла.

## 2. Модель состояния прибора

### 2.1 Варианты

| Вариант | Что даёт | Чем платим | Вердикт |
|---|---|---|---|
| (a) Полное желаемое состояние при КАЖДОМ старте («профиль работы»), включая `Off` | Сходится к нужному состоянию из любого исходного, в том числе после убийства процесса. Не зависит от выхода. | Узлы вне таблицы не трогаются никогда; рецепт, который управляет группой, обязан задать её целиком | **Берём** |
| (b) Возврат прочитанных исходных при остановке | «Вежливость» к IDMVS | Исходное неоднозначно (это может быть остаток прошлого запуска -> потеря `Off`); не работает при убийстве; результат SDK врёт (NETER) | **Отказ** от чтения исходных как истины |
| (c) Профиль «на покой» при остановке (явные значения, не прочитанные) | Камера после штатной остановки в известном тихом состоянии (подсветка не мигает) | Только best-effort: при убийстве не выполнится | **Берём как best-effort** |
| (d) Журнал исходных на диске | Переживает убийство | Тот же изъян, что (b): «исходное» неоднозначно; устаревший журнал, два компьютера, сбой посреди записи | **Отказ** (костыль вокруг отсутствия явного профиля) |
| (e) Владелец состояния прибора | — | — | Сеанс в процессе захвата (см. 2.3) |

### 2.2 Выбор: (a) + (c), проверка чтением

- **Профиль работы** (`run`) пишется при каждом `start()` между `open` и `start_grabbing`, ПОЛНОСТЬЮ для каждой управляемой группы.
- **Профиль покоя** (`rest`) пишется при остановке между `stop_grabbing` и `close`. Это best-effort: отказ попадает в
  `param_errors` и `errors`, `close` идёт всегда. Гарантии нет и не обещается.
- **Исходные значения не читаются как истина.** Чтение узла нужно только для проверки записи и для снимка (`params`).
- **Каждая запись проверяется чтением.** SDK бросил ошибку, а чтение показывает цель -> узел записан, WARNING в лог
  (`SDK вернул 0x…, значение на месте`). SDK не бросил, а чтение другое -> ошибка узла `не подтвердилось чтением`.
- **Группа управляется целиком или не управляется.** Задан хотя бы один ключ группы в профиле -> обязательны все ключи,
  которые нужны для этого значения родителя (2.4). Частичная группа -> отказ в `configure` (текст без значения из рецепта).
- **Узлы вне таблицы не трогаются.** Скрытые записи (как `TriggerMode=Off` в `HikvisionCamera.open`) переносятся в таблицу явно.

**Чем рискует выбор (остаточные риски):**
1. Убийство процесса оставляет камеру в профиле работы до следующего старта или выключения питания (подсветка мигает).
   Снижает: исправление выхода приложения во framework (Task 1.8, fix-forward) — дети получают время на `shutdown()`.
   Полностью не убирается. Это решение владельца (раздел 8, вопрос 3).
2. Другой инструмент (IDMVS) видит состояние, которое оставил наш последний запуск. По выбору (a) это норма: каждый
   владелец прибора пишет своё.
3. Если запись после `StopGrabbing` на этом приборе отвергается (гипотеза H1), профиль покоя не запишется. Тогда покой
   пишется после `close` -> `open` в том же потоке-владельце (решение по опыту Task 1.0).
4. Рецепт длиннее: группа задаётся целиком. Плата за отсутствие скрытого состояния.

### 2.3 Владелец состояния прибора (вариант (e)) и принцип №6

- Прибор эксклюзивен (один клиент), кадры идут через SHM процесса захвата. Поэтому handle и всё состояние прибора
  держит **сеанс в процессе захвата**. Не оркестратор (PM не знает о камерах; framework универсален), не `device_hub`
  (второй владелец той же камеры — конфликт, раздел 4).
- Желаемое состояние — поля register'а узла: их задаёт рецепт и меняет GUI (`register_update`). GUI формирует
  желаемое, бэкенд исполняет headless (принцип №6): GUI ничего не открывает и не пишет в прибор сам.
- Фактическое состояние — снимок сеанса в дереве `processes.<процесс>.state.<плагин>`; GUI и `backend_ctl` его читают.

### 2.4 Таблица параметров (декларативная)

Одна строка — один узел GenICam:

| Поле | Смысл | Пример |
|---|---|---|
| `key` | имя поля register'а | `trigger_source` |
| `node` | узел прибора | `TriggerSource` |
| `kind` | `int` / `float` / `enum` / `enum_str` / `bool` | `enum_str` |
| `group` | группа, управляемая целиком | `trigger` |
| `requires` | родитель и значения родителя, при которых узел открыт | `("trigger_mode", {"On"})` |
| `live` | можно писать при идущем захвате | `False` (у `ExposureTime`, `Gain` — `True`) |

Правила плана записи:
- порядок — родитель раньше потомка (порядок строк таблицы);
- потомок, чей родитель в целевом профиле его закрывает, НЕ пишется и ошибкой не считается (`не нужен: TriggerMode=Off`);
- обратного порядка и «возврата» нет: и работа, и покой — прямые планы из своих профилей.

Пример, группа `trigger` камер ID3013:
- работа `{On, SelfTrigger, 40}` -> `TriggerMode=On`, `TriggerSource=SelfTrigger`, `TriggerSelfTriggerPeriod=40`;
- покой `{On, Line0}` -> `TriggerMode=On`, `TriggerSource=Line0`; период не нужен (источник не `SelfTrigger`);
- работа `{Off}` -> только `TriggerMode=Off`; источник и период не нужны.

## 3. Контракт сеанса

### 3.1 Жизненный цикл — один поток-владелец

```
idle -> opening -> applying(run) -> grabbing -> stopping -> resting(rest) -> closed -> idle
            |            |               |
         not_found     error         error (3 ошибки get_frame подряд, как сейчас)
         busy
```
- **Все** вызовы SDK одного прибора идут из одного потока-владельца: поиск, `open`, запись и чтение узлов, `start_grabbing`,
  `get_frame`, `stop_grabbing`, `close`. Вопрос «привязан ли SDK к потоку» (H2) снимается устройством сеанса.
  Сейчас `SdkCodeReader` открывает и пишет в потоке вызывающего `start()`, а возвращает в потоке захвата (`sdk_reader.py:186-243`, `:377-402`).
- Команды (`start`, `stop`, `apply`) — сообщения в очередь владельца. Вызывающий ждёт ответ с дедлайном; `stop()` из колбэка
  кадра не ждёт сам себя (правило уже есть, `sdk_reader.py:158-160`).
- `close` — только владелец (правило `sdk_reader.py:4-9` распространяется на открытие и запись).
- Автопереподключения нет (ADR-CR-009 остаётся).

### 3.2 Порт вендора — 8 методов

| Метод | ID3013, `MvCodeReaderApi` (`Services/code_reader/sdk/api.py`) | Hikvision MVS (`MvCamera`) |
|---|---|---|
| `enum_devices()` | `:142` | `MV_CC_EnumDevices` |
| `open(entry)` | `:162` | `MV_CC_CreateHandle` + `MV_CC_OpenDevice` |
| `get_node(h, node, kind)` | `get_int/float/enum/bool` `:106-125` | `MV_CC_Get{Int,Float,Enum,Bool}Value` |
| `set_node(h, node, kind, value)` | `set_*` `:127-140` | `MV_CC_Set{Int,Float,Enum,EnumByString,Bool}Value` |
| `start_grabbing(h)` | `:180` | `MV_CC_StartGrabbing` |
| `get_frame(h, timeout_ms)` | `:193` (None = нет кадра) | `MV_CC_GetOneFrameTimeout` |
| `stop_grabbing(h)` | `:183` | `MV_CC_StopGrabbing` |
| `close(h)` | `:186` | `MV_CC_CloseDevice` + `MV_CC_DestroyHandle` |

`MvCodeReaderApi` уже такой: адаптер — тонкая функция `get_node/set_node` по `kind`. Для MVS — новый тонкий адаптер над `MvCamera`.
Имена функций MVS взяты из `Services/hikvision_camera/core/parameters.py` и `core/camera.py`; на живой MVS-камере я их не проверял.

### 3.3 Ошибки узлов

`param_errors: {узел: текст}` — отдельно от `last_error` и счётчика ошибок сеанса (как в 2.2a). Тексты:
`0x80020106: MV_CODEREADER_SetEnumValue[TriggerSource]`; `TypeError` (для не-SDK исключений только имя типа: в тексте
может быть значение из рецепта); `не подтвердилось чтением`; `пропущен: родитель не записан`. Значение из рецепта в текст
не попадает. Отказ профиля покоя растит `errors` (как сейчас отказ возврата).

### 3.4 Снимок состояния (фиксированные ключи)

`state`, `device` (`ip`, `model`, `serial`), `device_held`, `profile` (`run` / `rest` / `None`), `frames`, `fps`, `errors`,
`dropped`, `last_error`, `param_errors`, `params` (прочитанные после записи значения управляемых узлов: `{узел: значение}`),
`pending`. Плюс поля вида камеры (у считывателя — `last_code`, `history` и т.п.).
Публикация: смена `state`, `device_held`, `last_error`, `param_errors` — сразу; счётчики — не чаще `state_publish_hz`
(по умолчанию 5 Гц). Сейчас публикуется каждый `produce()` с кадрами (`sdk_plugin.py:199-201`).

### 3.5 Команды

| Команда | Что делает | Есть сейчас |
|---|---|---|
| `take_device` | `start()` сеанса | да (`sdk_plugin.py:354`) |
| `release_device` | `stop()`: покой + `close` | да (`:368`) |
| `get_status` | снимок | да (`:386`) |
| `reset_stats` | точка отсчёта счётчиков | да (`:394`) |
| `apply_params` | записать поля сейчас (живая правка), ответ — `params` и `param_errors` | нет (Task 1.3c) |

Живая правка: `register_update` -> `RegistersManager.subscribe` (`multiprocess_framework/modules/registers_module/core/manager.py:151`)
-> `apply` в очередь владельца. Узел `live=True` пишется при идущем захвате. Группа с `live=False` (триггер):
владелец делает `stop_grabbing` -> запись группы -> `start_grabbing` в том же handle, без `close`/`open` (нет ожидания
~10 с отпускания прибора). Если опыт Task 1.0 покажет, что запись после `StopGrabbing` отвергается (H1), — `close` -> `open`
-> запись -> захват в том же потоке-владельце.

### 3.6 Как это видно в GUI и в `backend_ctl`

- GUI, инспектор Pipeline: поля register'а (желаемое): `trigger_*`, `rest_trigger_*`, позже `exposure_time`, `gain`;
  readonly: `device_state`, `param_errors`. Дерево: `processes.reader_1.state.code_reader_sdk` -> `params`, `profile`, `fps`.
- `backend_ctl`: `state_get processes.reader_1.state.code_reader_sdk`; `send_command` в `reader_1` с `take_device` / `release_device`;
  `set_register_verified` по полю `trigger_period_ms` и сверка с `params.TriggerSelfTriggerPeriod` в снимке.

## 4. Слои и границы

| Слой | Что | Новое / FREEZE |
|---|---|---|
| `multiprocess_framework` | Ничего о камерах. Только исправления вперёд, найденные на стенде: (1) выход приложения сносит детей до `shutdown()` плагинов (`launcher/spawner.py:200`, `:224`; процессы второй инкарнации не записали `Stop signal received`); (2) после full-replace теряется каталог логов из `INSPECTOR_LOG_DIR` (вторая инкарнация писала в `logs/prototype_2/`, PM: `protected 'gui': конфиг … отличается … по managers.logger…`, `ProcessManager/system.log` #91); (3) живой путь `RegistersManager.subscribe` (первый пользователь в бэкенде — ловушка 2.2b) | Task 1.8 |
| `Services/device_session/` (новый пакет, имя обсуждаемо) | `interface.py` (Protocol порта и API сеанса), `params.py` (таблица, планы), `session.py` (поток-владелец, жизненный цикл, снимок), `testing/fake_port.py` | новое |
| `Services/code_reader/` | `sdk/api.py` — порт ID3013 без изменений; `core/sdk_reader.py` — тонкая обёртка: сеанс + разбор кадра с кодами; плагин и register — как сейчас + поля `rest_*` | переписывается внутри, публичное API (`start/stop/stats`, `param_errors`) сохраняется |
| `Services/hikvision_camera/` | `core/port.py` — тонкий адаптер MVS (новое); плагин переводится на сеанс позже (Task 1.9) | FREEZE: `plugin.py:243-266` `_apply_parameters_from_register`, `core/parameters.py:80-138`, `HikvisionCamera` (нужен `camera_service` и `sdk_app`) — оставить, не расширять, не удалять |
| `Plugins/sources/camera_service` | `CameraBackend` (`backends/base.py:11`) — не расширять; бэкенд `hikvision` позже может обернуть сеанс | FREEZE |
| `Services/device_hub` | `HikvisionDriver.connect()` для камер, которыми владеет процесс захвата, — FREEZE (вернуть отказ «камерой владеет процесс X»); запись реестра — только описание (ip, серийник). Статус камеры — из дерева процесса-владельца | ADR-DH, Task 1.10 |
| `multiprocess_prototype` | рецепты: развести «без записи режима» и «самотриггер с профилями работы и покоя» | Task 1.6 |

Слоёв не добавляется: сеанс — пакет Services, им пользуются два плагина Services. Порт — существующая обёртка SDK.
Зависимость `code_reader` -> `device_session` и `hikvision_camera` -> `device_session`; обратных нет.
Граница слоёв после правок — только `sentrux check .` из CLI.

## 5. Производительность (оценки, не замеры)

| Место | Оценка | Что сделать | Что мерить |
|---|---|---|---|
| `sdk/api.py:203` `string_at` + `core/sdk_frame.py:182` `.copy()` | 2 копии 1,25 МБ на кадр (оценка) | `bytearray` при копировании из SDK -> одна копия | время `get_frame` -> `on_frame` |
| `overlay_draw/plugin.py:113` `frame.copy()` перед `:117` `GRAY2BGR` | лишняя копия 1,25 МБ (оценка) | копировать только BGR-вход | `produce`/`process` p95 у `draw_*` |
| Публикация состояния (`sdk_plugin.py:199-201`) | до 20 `state.merge`/с на читатель с историей 20 записей (оценка) | `state_publish_hz` (3.4) | `introspect_router_stats` — число `state.merge` в секунду |
| Очередь 8 и `produce()` 20 Гц (`source_target_fps: 20`) при 25–57 к/с | 1–3 кадра за проход (оценка) | ничего | `dropped` за 5 мин = 0 |
| Две камеры × 25 к/с | ~0,5 ГБ/с трафика памяти на всю цепочку (оценка) | — | CPU на процесс, `fps` обеих камер ≥ 24 при периоде 40 мс, `pickle-fallback` SHM = 0 |

Стенд (после Task 1.7): 5 минут, обе камеры `SelfTrigger/40`; `backend_ctl`: `telemetry_snapshot`, `introspect_router_stats`,
`introspect_queues`, `state_get`; числа в таблицу «до/после».

## 6. Задачи (план `plans/camera-device-service.md` пишет `manager` по этому документу)

Порядок: 1.0 -> 1.1 -> 1.2 -> 1.3a -> 1.3b -> 1.4 -> 1.5 -> 1.6; 1.3c после 1.0 и 1.4; 1.7, 1.8, 1.10 независимы; 1.9 последней.
Каждая правка ≤ ~150 строк. Acceptance каждой задачи — готовый список для слепого тестера (литералы).
**[OPUS]** — задачу нельзя отдавать Sonnet без Opus-ревью дизайна (стадия 0) и Opus-ревью кода; причина указана.

### Task 1.0 — Опыты на камерах (H1, H5/H6, H3)
Level: — · Assignee: лидер; числа собирает `haiku` · Gate: стенд (окно координатора) · Dependencies: нет.
Goal: ответить, (1) в каком состоянии камеры сейчас, (2) принимает ли прибор запись после `StopGrabbing`, (3) дошла ли запись при NETER.
Шаги: ревью, часть A1, опыты 1–3; зонд `thread_split_probe.py` сначала поправить: читать узел после каждой записи, и после отказа тоже.
Acceptance: таблица «опыт -> вывод -> числа» в `plans/camera-device-service.md`; ручной возврат по `cam_orig.json` подтверждён чтением.
Out of scope: любые правки кода.

### Task 1.1 — Таблица узлов и планы записи (чистая логика)
Level: Middle · Assignee: `developer` (sonnet) · Gate: `light` · Handoff: reviewer(stage 0, sonnet) -> tester(RED) -> developer -> reviewer (sonnet).
Module contract: новое публичное `Services/device_session/params.py`: `NodeSpec`, `build_plan(table, profile) -> list[Step]`.
Files: `Services/device_session/params.py`, `Services/device_session/tests/test_params.py`.
DESIGN: `NodeSpec(key, node, kind, group, requires, live)`; `build_plan` — порядок строк таблицы; потомок, закрытый целевым
значением родителя, -> `Step(skip="не нужен: <родитель>=<значение>")`; неизвестный ключ и частичная группа -> `ValueError`
(текст: имя ключа, без значения).
REDS: `test_params.py::*`.
Acceptance:
- [ ] таблица `trigger` + профиль `{"trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40}` -> шаги
      `[("TriggerMode","enum_str","On"), ("TriggerSource","enum_str","SelfTrigger"), ("TriggerSelfTriggerPeriod","int",40)]`;
- [ ] `{"trigger_mode": "On", "trigger_source": "Line0"}` -> 2 записи + пропуск `TriggerSelfTriggerPeriod` с текстом `не нужен: TriggerSource=Line0`;
- [ ] `{"trigger_mode": "Off"}` -> 1 запись `("TriggerMode","enum_str","Off")`, два пропуска;
- [ ] `{"trigger_source": "Line0"}` (нет родителя группы) -> `ValueError`, в тексте `trigger_mode`, нет `Line0`;
- [ ] `{"trigger_periodms": 40}` -> `ValueError`, в тексте `trigger_periodms`, нет `40`.
Break-injection: убрать проверку `requires`; обратный порядок; значение в тексте ошибки; частичная группа молча.
Ловушки: `0` и `""` — значения, а не «не задано»: «не задано» = ключа нет.
Out of scope: потоки, SDK.

### Task 1.2 — Порт вендора: Protocol и фейк
Level: Middle · Assignee: `developer` (sonnet) · Gate: `light` · Handoff: reviewer(stage 0, **opus**: публичный контракт) -> tester -> developer -> reviewer (sonnet).
Module contract: `Services/device_session/interface.py`: `DevicePort` (Protocol, `runtime_checkable`, 8 методов из 3.2); README пакета (Purpose / Public API / Usage / Boundaries / Stability: contract).
Files: `Services/device_session/interface.py`, `Services/device_session/README.md`, `Services/device_session/testing/fake_port.py`, `tests/contract/test_device_session_port.py`.
DESIGN: фейк с состоянием: узел закрыт `0x80020106`, пока родитель не открыл; при идущем захвате закрыты узлы `live=False`;
режимы отказа: `neter_after_stop` (запись после `stop_grabbing` -> `SdkError(0x80020206)`, значение НЕ меняется — модель H1),
`applied_but_error` (значение меняется, но `SdkError(0x80020206)` — модель H5); журнал вызовов с `threading.get_ident()`.
Acceptance:
- [ ] `isinstance(MvCodeReaderApi-адаптер, DevicePort)` — `True`;
- [ ] фейк, `applied_but_error`: `set_node(h,"TriggerMode","enum_str","On")` бросает `0x80020206`, затем `get_node` -> `1`;
- [ ] фейк, `neter_after_stop`: после `stop_grabbing` запись бросает `0x80020206`, `get_node` -> прежнее;
- [ ] журнал вызова содержит id потока.
Break-injection: фейк меняет значение в `neter_after_stop`; нет id потока в журнале.
Out of scope: сеанс.

### Task 1.3a — Сеанс: поток-владелец и жизненный цикл (без параметров) [OPUS]
Level: Senior · Assignee: `developer` (sonnet) только после Opus stage 0; при 3-й итерации — `teamlead` · Gate: `light`/`medium`.
Почему [OPUS]: потоки и жизненный цикл handle. В этой сессии ошибки порядка (`close` не в `finally`, `on_error` до `close`)
Sonnet-разработчик пропустил, нашло только ревью.
Files: `Services/device_session/session.py` (≤150), `Services/device_session/tests/test_session_lifecycle_hazards.py` (автор).
DESIGN: 3.1. Очередь команд; `start(timeout)` ждёт событие «захват идёт / отказ»; `stop(timeout)` идемпотентен, из колбэка не ждёт;
3 ошибки `get_frame` подряд -> `error` + `close`; снимок 3.4 без `params`.
Acceptance:
- [ ] порядок вызовов фейка: `["enum_devices","open","start_grabbing","get_frame",…,"stop_grabbing","close"]`;
- [ ] **все** вызовы порта — с одним id потока, и он не равен id потока теста;
- [ ] `stop(0.2)` при `get_frame` с таймаутом 500 мс возвращается за ≤ 0,8 с; `device_held` до выхода владельца `True`;
- [ ] `start()` во время остановки -> `False`, второго `open` нет;
- [ ] `stop()` из `on_frame` не виснет (поток теста с дедлайном 2 с);
- [ ] `close` ровно 1 на 1 `open` во всех тестах.
Break-injection: `open` в потоке вызывающего (тест id потока краснеет); `close` в `stop()`; ожидание потока под замком.
Ловушки: ADR-CR-008 (закрывает только поток захвата); `get_frame` не будится `close` на Windows.
Out of scope: параметры.

### Task 1.3b — Сеанс: профили работы и покоя, проверка чтением [OPUS]
Level: Senior · Assignee: `developer` (sonnet) после Opus stage 0 · Gate: `light`/`medium` · Dependencies: 1.1, 1.2, 1.3a.
Почему [OPUS]: порядок записи относительно захвата и `close`, поведение при отказах — тот же класс, что живой дефект B1.
Files: `Services/device_session/session.py` (+≤100), `tests/test_session_profiles_hazards.py`.
DESIGN: 2.2 и 2.4. План работы — между `open` и `start_grabbing`; план покоя — между `stop_grabbing` и `close`; после
каждого `set_node` — `get_node`; исходные значения не читаются.
Acceptance:
- [ ] работа `{On, SelfTrigger, 40}`: `set` и `get` трёх узлов идут после `open` и до `start_grabbing`, порядок — литерал;
- [ ] перед первым `set` нет ни одного `get` (исходные не читаются);
- [ ] фейк `applied_but_error` на `TriggerMode`: `param_errors == {}`, `errors == 0`, в логе WARNING `значение на месте`;
- [ ] фейк отдаёт при чтении не цель: `param_errors["TriggerSelfTriggerPeriod"] == "не подтвердилось чтением"`;
- [ ] покой `{On, Line0}` после `stop_grabbing`; фейк `neter_after_stop`: `param_errors` содержит `0x80020206`, `errors == 2`, `close` ровно 1;
- [ ] после неудачного покоя второй `start()` снова пишет полный профиль работы; работа `{Off}` пишет `TriggerMode=Off` (потеря `Off` невозможна).
Break-injection: покой до `stop_grabbing`; нет чтения после записи; чтение исходных; покой после `close`; отказ одного узла прерывает план.
Ловушки: при `Off` потомки закрыты — не писать их (1.1).
Out of scope: живая правка.

### Task 1.3c — Живая правка параметров (вклад 2.2b) [OPUS]
Level: Senior · Assignee: `developer` (sonnet) после Opus stage 0, или `teamlead` · Dependencies: 1.0 (H1), 1.4.
Почему [OPUS]: три потока (команды, владелец, источник), перезахват на живом handle, первый живой пользователь `RegistersManager.subscribe`.
Files: `session.py` (+≤80), `Services/code_reader/plugin/sdk_plugin.py` (подписка), тесты.
DESIGN: 3.5. `apply(fields)` — сообщение владельцу; `live=True` — запись без остановки захвата; группа `live=False` —
`stop_grabbing` -> план -> `start_grabbing` в том же handle (или `close`/`open`, если опыт 1.0 подтвердил H1).
Acceptance:
- [ ] `apply({"exposure_time": 1200.0})` при захвате: `set_node(ExposureTime, 1200.0)`, вызова `stop_grabbing` нет;
- [ ] `apply({"trigger_period_ms": 60})`: `["stop_grabbing","set_node(TriggerSelfTriggerPeriod,60)","get_node(…)","start_grabbing"]`, `open` и `close` нет;
- [ ] два `apply` из двух потоков: один открытый handle в каждый момент, итог `params` — последнее значение;
- [ ] `produce()` во время перезахвата < 50 мс;
- [ ] один тест связывает настоящие `RegistersManager` и `PluginOrchestrator._on_register_update` с плагином на фейке.
Break-injection: запись группы без остановки; запись из потока команд; подписка снята.
Ловушки: колбэк `subscribe` идёт в потоке команд; `subscribe` не зовётся на живом пути -> дефект framework, эскалация (принцип №2).
Out of scope: `UserSetSave`.

### Task 1.4 — `code_reader` на сеансе [OPUS: ревью кода]
Level: Middle+ · Assignee: `developer` (sonnet); Opus-ревью кода обязательно (смена жизненного цикла) · Dependencies: 1.3b.
Files: `Services/code_reader/core/sdk_reader.py` (тонкая обёртка), `Services/code_reader/plugin/sdk_plugin.py`, тесты 2.2a.
DESIGN: `SdkCodeReader` держит сеанс и разбирает кадр (`frame_from_raw`); `_TRIGGER_NODES` -> таблица `trigger` из 1.1;
`_apply_trigger`/`_restore_trigger` удаляются как механизм (заменены планами 1.3b); публичное `start/stop/stats`, ключи
`stats()` и снимка сохраняются, `param_errors` — тот же формат.
Acceptance:
- [ ] зелёные без правки: `test_sdk_plugin.py`, `test_sdk_plugin_hazards.py`, `test_sdk_overlay*.py`;
- [ ] `test_sdk_trigger.py`: строки про возврат исходных заменены на покой (список правок в отчёте, литералы `On`, `Line0`);
- [ ] ключи `stats()`: `frames, ok, no_code, bad_code, errors, state, last_error, device, device_held, param_errors`.
Break-injection: открытие вне владельца; потеря ключа `param_errors`.
Out of scope: Hikvision.

### Task 1.5 — Плагин: поля покоя, частота публикации, `params`
Level: Middle · Assignee: `developer` (sonnet) · Reviewer: sonnet · Dependencies: 1.4.
Files: `plugin/sdk_registers.py` (`rest_trigger_mode`, `rest_trigger_source`, `rest_trigger_period_ms`, `state_publish_hz: float = 5.0`),
`plugin/sdk_plugin.py`, `multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt`.
Acceptance:
- [ ] фейк даёт 50 кадров/с 2 с: число `proxy.merge` ≤ 12; смена `device_state` публикуется в тот же вызов;
- [ ] снимок содержит `params == {"TriggerMode": 1, "TriggerSource": 9, "TriggerSelfTriggerPeriod": 40}` для профиля работы (литералы фейка);
- [ ] частичная группа покоя в рецепте -> `configure` бросает `ValueError` с именем поля.
Break-injection: публикация на каждый кадр; `params` не в снимке.

### Task 1.6 — Рецепты: развести
Level: Junior · Assignee: `developer` (sonnet) или `junior` (haiku) по точному диффу · Dependencies: 1.5; решение владельца (раздел 8).
Files: `qr_reader_sdk_dual_demo.yaml` (без полей режима), новый `qr_reader_sdk_dual_selftrigger.yaml` (работа `On/SelfTrigger/40`, покой `On/Line0`), тесты рецептов.
Acceptance: литералы полей у `reader_1`, `reader_2`; ключи ⊆ полей register'а; `SystemBlueprint.check` проходит (как загрузчик).

### Task 1.7 — Копии кадра
Level: Middle · Assignee: `developer` (sonnet), reviewer sonnet · Files: `Services/code_reader/sdk/api.py`, `core/sdk_frame.py`, `Plugins/render/overlay_draw/plugin.py`.
Acceptance: `decode_image` отдаёт записываемый массив без второй копии (`np.shares_memory` с буфером кадра — `True`);
выход `overlay_draw` побайтно равен эталону до правки для серого и BGR входа.
Break-injection: вернуть `.copy()` — тест `shares_memory` краснеет.

### Task 1.8 — framework: выход приложения и каталог логов [OPUS, не Sonnet]
Level: Senior · Assignee: `investigator` (opus) -> `teamlead` (opus) · Почему: жизненный цикл процессов и IPC всего приложения.
Goal: на общем стопе каждый ребёнок (и поднятый full-replace) пишет `Stop signal received (system-wide)` и выполняет
`shutdown()` плагинов до `kill_tree`; `INSPECTOR_LOG_DIR` переживает full-replace.
Acceptance: стенд без камер, плагин-заглушка с `shutdown()` 0,8 с в процессе, поднятом full-replace: строка `shutdown`
плагина есть в логе в каталоге `INSPECTOR_LOG_DIR`; между `system_stop_event` и `TerminateJobObject` ≥ 1 с запаса.

### Task 1.9 — Hikvision MVS на сеансе
Level: Senior · Assignee: `developer` (sonnet) + Opus-ревью · Dependencies: 1.4; MVS-камера на стенде (раздел 8, вопрос 4).
Files: `Services/hikvision_camera/core/port.py` (новое), плагин — за флагом `use_session`; старый путь FREEZE.
Acceptance: фейк MVS-порта проходит `tests/contract/test_device_session_port.py`; `TriggerMode=Off` пишется только из таблицы.

### Task 1.10 — `device_hub`: камерой владеет процесс захвата
Level: Middle · Assignee: `developer` (sonnet) · Files: `Services/device_hub/drivers/hikvision_driver.py`, ADR-DH.
Acceptance: `connect()` для камеры с владельцем -> `False` и текст `камерой владеет процесс`; `HikvisionCamera.open` не вызывается (журнал фейка).

### Задачи по исполнителю

| Задача | Sonnet пишет код | Ревью дизайна | Ревью кода | Почему так |
|---|---|---|---|---|
| 1.1, 1.5, 1.6, 1.7, 1.10 | да | sonnet | sonnet | чистая логика, поля, YAML, копии — без потоков |
| 1.2 | да | **opus** | sonnet | публичный контракт порта |
| 1.3a, 1.3b, 1.3c | да, после Opus stage 0 | **opus** | **opus** | потоки, порядок относительно захвата и `close`, отказы прибора |
| 1.4 | да | sonnet | **opus** | меняется жизненный цикл живого читателя |
| 1.8 | нет | **opus** | **opus** | жизненный цикл процессов всего приложения |
| 1.9 | да | sonnet | **opus** | второй вендор, потоки SDK |
| 1.0 | — | — | — | только железо; вывод — Opus |

## 7. Что из 2.2a и 2.2b войдёт, что перепишется

| Часть | Судьба |
|---|---|
| Поля `trigger_mode`, `trigger_source`, `trigger_period_ms`, readonly `param_errors` (2.2a) | входят как есть |
| Формат `param_errors` (`узел: текст; …`), ключ снимка | как есть |
| `_parse_trigger`, `_TRIGGER_NODES` | переписываются в таблицу 1.1 |
| `_apply_trigger` (чтение исходного -> запись) | переписывается в план работы (без чтения исходного, с проверкой чтением) |
| `_restore_trigger`, `_Session.restore` | заменяются планом покоя (1.3b) |
| M1–M4: `close` в `finally`, `on_error` после `close`, текст со значением | правила входят в сеанс; текст M3 не нужен (исходные не читаются) |
| Замеры `stop_grabbing мс=`, `возврат … мс=` | входят в сеанс как `stop_grabbing мс=`, `покой <узел> мс=` |
| Hazard-тесты 2.2a (остановка во время старта, остановка из `on_frame`, второй старт при остановке) | переносятся на сеанс (1.3a) |
| Рецепт `qr_reader_sdk_dual_demo` с полями режима | разводится на два (1.6) |
| 2.2b: живая правка, `exposure_time`/`gain`, `params` в дереве | входит в 1.3c и 1.5; перезахват без `close`/`open` (если опыт 1.0 позволит) вместо `release`+`take` |

Совет по незакоммиченной 2.2a: код годен (64 теста зелёные). Коммитить без полей режима в рецепте по умолчанию
(или с решением владельца по вопросу 1) и с поправкой документов по ревью (A1).

## 8. Вопросы владельцу

1. **Рецепт по умолчанию.** Предложение лидера — развести на два рецепта. Я согласен: `qr_reader_sdk_dual_demo` — без
   записи режима (камера снимает так, как настроена в IDMVS); `qr_reader_sdk_dual_selftrigger` — работа `On/SelfTrigger/40`,
   покой `On/Line0`. По умолчанию в `app.yaml` — первый, пока не закрыта Task 1.8 (иначе каждое закрытие окна оставляет
   подсветку мигать). Согласны?
2. **Покой для ID3013:** когда приложение остановлено, камера ждёт аппаратный триггер (`On/Line0`, подсветка не мигает). Так?
3. **Остаточный риск:** при убийстве процесса (сбой, `taskkill`) камера остаётся в профиле работы до следующего старта
   или выключения питания. Принимаете?
4. **MVS-камера Hikvision на стенде** для Task 1.9 есть? Без неё 1.9 — только на фейке.
5. **Камеры в реестре `device_hub`:** показывать как описание (ip, серийник, кто владеет) или не показывать вовсе?
6. **`UserSetSave`** (сохранить настройки в камеру навсегда) из приложения не делать никогда? Предлагаю: никогда.

## 9. Что я оставил открытым / ненадёжным

- H1, H5, H6 не проверены (камер нет). От H1 зависит перезахват без `close`/`open` (1.3c) и запись покоя (1.3b).
- Имена функций MVS для порта взяты из кода `hikvision_camera`, на живой MVS-камере не проверены.
- Дефект `HikvisionDriver.connect` (серийник в `open(camera_index: int)`) найден чтением кода, не воспроизведён.
- Потеря `INSPECTOR_LOG_DIR` после full-replace — вывод из одного прогона (каталог `logs/prototype_2/` и строка PM #91); код не разбирал.
- Числа производительности — оценки по коду.
- Имя пакета `Services/device_session/` и выбор «отдельный пакет, а не `hikvision_camera/core`» — суждение; решает ADR.
- qex, graphify и `sentrux check .` в этом проходе не запускал: хватило прямого чтения файлов; индекс qex не проверял.
- Литералы enum в Acceptance 1.5 (`9` для `SelfTrigger`) — со стенда 2026-10-16; фейк должен их повторить, иначе тестер возьмёт числа фейка.
