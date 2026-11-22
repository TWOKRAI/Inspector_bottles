# camera_device — архитектурные решения

Решения плана [`camera-device-service`](../../plans/2026-10-18_camera-device-service/plan.md) (владелец и лидер, 2026-10-18),
записанные как ADR до первой строки кода ядра. Номера `Р<n>` — [`decisions.md`](../../plans/2026-10-18_camera-device-service/decisions.md)
плана; исходное сравнение вариантов — ревью `docs/reviews/2026-10-18_camera-services-unification-review.md` (Q1, Q3, Q5) и
`docs/reviews/2026-10-18_camera-plan-review.md`. Код ядра на момент записи не существует: ADR описывают принятое, не готовое.

## ADR-CAM-001 — Ядро камер и вендорские драйверы; реестр драйверов — словарь строк

**Дата:** 2026-10-28 (решение принято 2026-10-18)
**Статус:** Accepted
**Task context:** Task 0.1 плана `plans/2026-10-18_camera-device-service/tasks/0.1.md`; решение владельца 1 и 5; Р11

### Context
Камеры обслуживают два несвязанных пакета (`Services/code_reader`, `Services/hikvision_camera`) с разными API и форматами item;
MVS-камеру открывают четыре независимых места без владельца (F14), общих тестов нет. Живые пути `hikvision` держат четыре
рецепта, бэкенд `Plugins/sources/camera_service/backends/hikvision.py:17`, `Plugins/hub/device_hub/plugin.py:137-142` и вкладка GUI.
Силы: принцип №3 (живой путь — контракт), DLL одного вендора не должна грузиться в процесс другого, слоёв не прибавлять (принцип №4).

### Alternatives

**A. Один пакет `Services/camera/` с `drivers/{mvcr,mvs}`**
- Pros: один пакет.
- Cons: удаляет или переносит живые пути `Services.hikvision_camera.*` (4 рецепта, `camera_service`, хаб, вкладка); TCP-путь и разбор кодов
  (`code_reader/core/sink.py`, `result.py`) — домен считывателя, не камеры.

**B. Ядро `Services/camera_device/` + два вендорских сервиса над ним**
- Pros: слоёв столько же (всё в Services); старые пути живут; DLL вендора не грузится в чужой процесс.
- Cons: один новый пакет; вендорские плагины переопределяют создание порта.

**C. Как сейчас**
- Pros: ничего не трогать.
- Cons: четыре открывателя MVS без владельца, два API, два формата item, ноль общих тестов.

Реестр драйверов (внутри B):
- *R1. Статический импорт вендоров в ядре.* Cons: ядро грузит DLL всех вендоров, цикл ядро <-> драйвер.
- *R2. Plugin-discovery (entry points).* Cons: механизм ради четырёх строк; отвергнут владельцем (ponytail, решение 5).
- *R3. Словарь строк `DRIVERS = {"mvs": "Services.hikvision_camera.driver:make_port", …}`, разрешение `importlib` в `configure`.* Выбран.

### Decision
Chose B + R3. Ядро знает вендоров только по строкам реестра (`Services/camera_device/drivers/__init__.py`, Р11): неизвестный ключ ->
`ValueError` со списком известных; общий `CameraDevicePlugin` берёт `driver:` из рецепта, вендорские плагины переопределяют
`create_port()` ленивым импортом своего `make_port`. Направление импорта: вендор -> ядро -> `multiprocess_framework`; обратного статического
импорта нет. `cv2`/`numpy` — только `drivers/opencv_driver.py` и `testing/`.
*Уточнено ADR-CAM-006 (2026-11-22):* ленивый `import cv2` внутри ветки дебайера ядра (`plugin_base.py`, `_frame_array`) допускается;
`numpy` в `plugin_base.py` уже импортирован. Правило выше остаётся для всего прочего кода ядра: `cv2` на уровне модуля и вне ветки дебайера запрещён.

### Consequences
- Architectural changes: новый пакет `Services/camera_device/`; `code_reader` и `hikvision_camera` становятся тонкими драйверами (Фазы 3, 4 плана).
- Migration: нет в этой задаче; переводы — Task 3.2, 4.2a.
- Constraints: запрет «ядро -> вендор» держат две записи `[[boundaries]]` в `.sentrux/rules.toml`
  (`Services/camera_device/*` -> `Services/code_reader/*` и -> `Services/hikvision_camera/*`). Без них запрета нет: `rules.toml` — deny-список,
  Services -> Services запрещены только 4 парами (`layer_render`, `dataset_gen`); замер 2026-10-28: `sentrux check .` на базовой
  линии — exit 0, 41 правило; пробный файл `import Services.code_reader` + `import Services.hikvision_camera` в ядре — exit 0 (не пойман);
  после двух boundary — exit 1, две ошибки `boundary`, после удаления пробы — exit 0, 43 правила. Строки реестра (Р11) boundary не задевает
  (проба со словарём строк — exit 0).
- Known risks: CLI не поймал `from Services.hikvision_camera.sdk import structures` (импорт модуля из подпакета; один замер) — запрет
  держится на форме `import pkg` / `from pkg.mod import name`; граница не заменяет проверку просмотром импортов в задачах 1.5 и 5.1.
  Дубль таблицы `CAP_PROP` (~15 строк, `camera_service/backends/webcam_controls.py:24-182` -> драйвер OpenCV ядра) — долг `ponytail:` в коде,
  снятие — когда `camera_service` переедет на ядро (вне плана).

### Links
- Related: ADR-CAM-002…004; `.sentrux/rules.toml` (блок «Services/camera_device»); память `feedback_sentrux_freetier_3rule_limit.md`
- Related: `docs/design/camera-device-architecture.md`

## ADR-CAM-002 — Один сеанс прибора на процесс, поток-владелец, профили run/rest, проверка чтением

**Дата:** 2026-10-28 (решение принято 2026-10-18)
**Статус:** Accepted
**Task context:** Task 0.1; Р1, Р6, Р12; решение владельца 4 (убийство процесса оставляет камеру в профиле run — риск принят)

### Context
Нужно N камер (цель М3: 2 MVS по serial, 2 ID3013). Живые дефекты: открытие по индексу даёт одному прибору двух хозяев (повтор R5 на фейке:
`opened: ['192.168.1.10', '192.168.1.10']`), код возврата SDK не равен состоянию прибора (прецедент ForceIp, гипотеза H5), прибор отпускается
через ~10 с после убийства процесса (один замер, handoff §4.1), режим триггера ID3013 прибор сам не возвращает. Режим ADR-CR-010 (прочитать
исходное, записать, вернуть исходное) при отказе возврата читает оставшийся самотриггер как «исходное» и теряет `Off` навсегда.

### Alternatives

**A. Процесс на камеру, один сеанс на процесс, все вызовы SDK из потока-владельца**
- Pros: падение ctypes роняет один процесс, супервизор поднимает; глобальное состояние SDK своё на процесс; нет гонок вызовов SDK.
- Cons: процессов столько же, сколько камер; жёсткий путь состояния `processes.{p}.state.<плагин>` и register по имени плагина запрещают два экземпляра в одном процессе.

**B. Поток на камеру в одном процессе**
- Pros: один процесс.
- Cons: падение DLL роняет все камеры; `_lib` грузится без замка (`code_reader/sdk/api.py:87-88`), `_dll_dir_cookies` глобальный (`loader.py:29`); общий GIL.

**C. N сеансов в одном процессе**
- Pros: —
- Cons: те же, что у B, плюс столкновение путей состояния.

Профиль прибора (внутри A):
- *P1. Вернуть исходное (ADR-CR-010).* Cons: см. Context; на убитом процессе не работает всё равно.
- *P2. Профиль `run` пишется целиком при каждом старте; профиль `rest` — best-effort при остановке; исходные не читаются.* Выбран.
- *V1. Доверять коду возврата.* Cons: H5 (ложный отказ) и обратный случай (запись не дошла при `rc=0`) невидимы.
- *V2. Каждую запись проверять чтением.* Выбран.

### Decision
Chose A + P2 + V2. Идентичность прибора обязательна, `select: first` — только явно (Р3). Допуск чтения: float —
`|read − target| ≤ max(inc or 0, 1e-3·|target|, eps_abs)`, int — `|read − target| < max(inc or 1, 1)` (без относительного члена; амендмент 3, Р6), `eps_abs` — поле `Binding` (умолчание `1e-6`: у float-узлов MVS шага нет,
`Services/hikvision_camera/sdk/structures.py:196-204`); enum — по символьному имени; в `params[поле]` пишется прочитанное скаляром, статус — в `params_status[поле] = {verified, rc}`. При H5 (код ≠ 0, чтение = цель) —
`verified: True` плюс `rc`. Без capability `read_back` — статус `unverified` (не ошибка и не «подтверждено»): форма `params_status = {"verified": False, "rc": None}`, `params[поле]` — записанная цель (`profiles.py:116`). Пауза перезапуска ≥ 10 с — это
`restart_policy.backoff_sec: 10.0` процесса в рецепте (Task 3.3, 4.3), поля плагина нет (ревью B3). Живая правка исполняется потоком-владельцем из очереди (Р12).

**Уточнение 2.3d (решение 2026-11-16, амендмент 8; записано 2026-11-17): команды Р7 с портом.** Решение — причина:
- Порт зовёт тот, кто его держит; исключения из Р1 нет. Пока владелец жив (`device_held`), любая команда плагина с портом идёт через ящик:
  `session.call` — единственный путь к порту из потока команды (`list_devices` при захвате, `describe_params`, `trigger_software`).
  Причина: SDK не обязан быть потокобезопасным, а безопасность `MV_CC_EnumDevices` при открытом handle не измерена (прежний вариант
  «единственное исключение из Р1: `list_devices` из потока команды», амендмент 6, снят).
- Путь `list_devices` выбирается по `session.device_held`, а не по `state`. Причина: `stop()` на отказном состоянии ставит `closed` сразу, пока
  владелец ещё в `_cleanup` (проба стадии 0: `state=closed held=True`); выбор по `state` дал бы `acquire`/`enum_devices` из потока команды
  параллельно `port.close()`/`sdk.release()` владельца. Без владельца (`device_held` ложно или сеанса нет) — `acquire`, `enum_devices`, `release`
  потоком команды; `device_held` и не `grabbing` — отказ «сеанс не в захвате».
- Порт создаёт `_ensure_port()` отдельно от сеанса (без моста логов и воркеров). Причина: список приборов нужен ДО `take_device`, чтобы выбрать
  серийник, а capability (`software_trigger`, `node_describe`) известны только у порта.
- Срок `_CALL_TIMEOUT_S = 2.0` с (больше `timeout_ms`, меньше терпения вызывающего); `call` ставит в ящик обёртку `_port_call("call", fn)`.
  Причина: без неё `_current` не выставлялся и сторож не видел зависший `fn` из `call`.
Последствия: команда с `call` блокирует приём команд процесса до `_CALL_TIMEOUT_S` + `watchdog_s` (около 7 с в худшем случае; по чтению кода, в живом
процессе не измерено); при захвате на время перечисления владелец не читает кадры.

**Уточнение W2 (2026-11-15):** очереди владельца в Task 2.1 нет — `session.py` исполняет только `start`/`stop`; почтовый ящик владельца и политику `apply` строит Task 2.4. Решение выше не меняется.

### Consequences
- Architectural changes: `session.py` (поток-владелец, переходы, сторож), `profiles.py` (профили run/rest, проверка чтением, `within_tolerance`), `params.py` (план записи); порт вызывается только из потока-владельца.
  Уточнение W2 (2026-11-15): раскладка фактическая — `session.py` (≈ 450 строк против ≈ 200 по плану 2.1), `profiles.py` (`ProfileRunner`, `ProfileState`), `params.py` (`build_plan`, `Step`, `check_bindings`); очередь владельца — Task 2.4.
- Migration: `code_reader_sdk` теряет ADR-CR-010 (возврат исходных) — ADR-CR-011 в Task 3.2.
- Constraints: два экземпляра плагина в одном процессе запрещены (инвариант записан в README ядра, «Boundaries»; кодом не проверяется); убитый процесс оставляет камеру в профиле run (риск принят).
- Known risks: **основание «поток-владелец» — устранение класса дефектов, не доказанный отказ.** Опыты не подтвердили H1 (запись после
  `stop_grabbing` отвергается): ID3013 21/21 `rc=OK` (`tasks/6.2.result.md`), MVS `rc=0x0` при паузе 0 и 1,0 с (`tasks/0.5.result.md`, по одному прогону);
  H2 (SDK привязан к потоку): ID3013 `split` 9/9, `same` 12/12 OK, MVS оба режима OK; H5 не спровоцирована (ID3013 NETER 0 из 30; у MVS `Width` при
  захвате честно отказан `0x80000106`, значение не менялось). Поток-владелец остаётся дешёвой страховкой; перезахват `stop -> план -> start_grabbing`
  в том же handle у `mvcr` не измерен (шлюз Task 6.4). Шторм `EnumDevices` из трёх процессов не проверен.
  Task 2.3d: безопасность `MV_CC_EnumDevices` при открытом handle (0.5/6.2) касается теперь только межпроцессного случая (`hikvision_dual.yaml`:
  процесс B перечисляет, пока процесс A держит GigE-прибор) — открытый вопрос, не блокер. Остаточный риск: `list_devices` без владельца не
  конкурирует с `start()` только пока оба идут из системного потока (`cmd_take_device`); по чтению кода (ревью Opus) это недостижимо сегодня, не
  воспроизведено, замка нет.

- Запись в `ALLOWLIST` G6 R1 для потоков сеанса (`session.py`) запрошена: решение владельца ожидается; investigator проверяет `KeyedExecutor` (2026-11-15).

### Links
- Related: ADR-CAM-001, ADR-CAM-003; `amendments.md` §4 (умолчания `mvcr`); `docs/handoffs/2026-10-17_camera-service-handoff.md` §4.1, §4.3
- Supersedes (частично): механизм ADR-CR-010 `Services/code_reader/DECISIONS.md` — формально заменит ADR-CR-011 (Task 3.2)

## ADR-CAM-003 — Универсальность: `Binding.kind`, `Capabilities`, `DeviceIdentity`

**Дата:** 2026-10-28 (решение принято 2026-10-18)
**Статус:** Accepted
**Task context:** Task 0.1; Р2, Р3, Р4, Р5; решение владельца 5

### Context
У веб-камеры (OpenCV) и RTSP узлов GenICam нет, а черновик порта принимал `get_node/set_node(node, kind: NodeKind)` — GenICam в сигнатуре. Нужно
доказать универсальность третьим драйвером (OpenCV, P1), не раздувая порт возможностями, по которым ядро не ветвится. Порядок GigE-перечисления
не обещан (F13), выбор по индексу ломается при трёх камерах.

### Alternatives

**A. GenICam-узлы в сигнатуре порта**
- Pros: прямое отображение на MVS и ID3013.
- Cons: драйверы без узлов (OpenCV, RTSP) вынуждены имитировать узлы; порт знает вендорскую модель.

**B. `Binding(kind, key, vtype)` в порту + `Capabilities` — `frozenset[str]` драйвера**
- Pros: порт не знает GenICam; что можно писать, что на ходу, что читается обратно — решает драйвер.
- Cons: `Binding.kind` описателен и мало что значит для ядра.

**C. Широкий набор capability (`codes`, `self_trigger`, `exception_cb`, `enumerate` и др.)**
- Pros: все различия вендоров видны явно.
- Cons: ядро по ним не ветвится (ревью P4) — флаги без читателя.

Идентичность прибора:
- *I1. Индекс перечисления.* Cons: порядок не обещан (F13).
- *I2. `DeviceIdentity(kind ∈ {"serial","ip","url","index"}, value, name="")`.* Выбран.

### Decision
Chose B + I2. `DevicePort.get_param/set_param/describe_param/execute` принимают `Binding(kind ∈ {"genicam","cv_prop","vendor","none"}, key, vtype)`;
`Capabilities` — `frozenset[str]` из `read_back`, `live_write`, `node_describe`, `software_trigger`, `restart_regrab`; `Binding.kind`
ядром не читается (описательный, решение владельца 5). `index` разрешён только с `name` (UVC) или с WARNING в логе. Параметр описан один раз —
в поле register'а (тип плюс `FieldMeta`), драйвер держит только `BINDINGS: dict[str, Binding]` (Р4); «не управлять группой» — флаг `trigger_managed` (Р5).

### Consequences
- Architectural changes: `interface.py` (Task 1.5) — Protocol без вендорских типов, только stdlib; контрактный тест `set(BINDINGS) == {вендорские поля register'а}`.
- Migration: нет; старые `get_node/set_node` остаются внутри вендорских драйверов.
- Constraints: ядро не ветвится по `Binding.kind`; новая capability добавляется только вместе с читателем в ядре.
- Known risks: `cv2.VideoCapture.get` не всегда отражает прибор — драйвер OpenCV без `read_back` даёт `unverified`; показ `None` в спинбоксе фабрики форм не проверен
  (`multiprocess_prototype/frontend/forms/factory/kinds.py:76-81`), поэтому Р5 — явный флаг.

### Links
- Related: ADR-CAM-001, ADR-CAM-002; ревью Q2, Q3 (`docs/reviews/2026-10-18_camera-services-unification-review.md`)

## ADR-CAM-004 — Политика переименования: без алиасов, FREEZE только без живого вызывающего

**Дата:** 2026-10-28 (решение принято 2026-10-18)
**Статус:** Accepted
**Task context:** Task 0.1; Р8, Р9, Р10, Р14; решение владельца 3

### Context
Команды `hikvision` (`open`, `start_capture`, `get_parameters`, `set_parameters`, …) отличаются от общего набора ядра (`take_device`, `release_device`,
`read_params`, `apply_params`, Р7). Их потребители — вкладка GUI (`presenter.py:80-115`), рецепты, хаб; граф зависимостей связь через имена команд IPC
не видит (нашёл только grep), поэтому пропущенный потребитель обнаруживается при запуске. Принцип №3 («FREEZE, не KILL») защищает пути без живого вызывающего.

### Alternatives

**A. Алиасы старых команд (старые имена живут как FROZEN)**
- Pros: потребители не ломаются.
- Cons: второй контракт без срока жизни; потребители остаются на старых именах; владелец решил иначе (решение 3).

**B. Переименовать без алиасов, перевести всех потребителей в одной точке коммита К4'**
- Pros: один контракт; нет долга.
- Cons: К4' = 20 файлов одним коммитом; пропущенный по IPC потребитель сломается на живом запуске, а тесты на моках зелёные.

**C. Удалить всё устаревшее, включая `sdk_app`, `HikvisionCamera`, `SdkCodeReader`, `CommandPanel`**
- Pros: меньше кода.
- Cons: нарушает принцип №3; для `sdk_app` — потеря инструмента диагностики к стенду MVS.

`sdk_app` отдельно: клиент IPC (переписать дубль вкладки GUI); удалить целиком; **FROZEN, ручной запуск** — выбран.

### Decision
Chose B. Переименование без алиасов (Р8): `open`+`start_capture` -> `take_device`; `close`/`stop_capture` -> `release_device`; `enum_devices` -> `list_devices`;
`get_parameters` -> `read_params`; `set_parameters`/`set_exposure`/`set_gain`/`set_frame_rate`/`set_resolution` -> `apply_params` (или `register_update`);
`open_sdk_app`/`close_sdk_app` удаляются. Хаб: новые `camera_list_devices`, `camera_owner`, `camera_read_params`; `hik_release` остаётся no-op
`{"status": "ok", "released": []}` (живой вызывающий `Plugins/sources/camera_service/plugin.py:262`); `hik_enum`, `hik_open`, `hik_close`, `hik_get_params`,
`hik_set_params` — отказ с текстом, какая команда заменяет. `sdk_app` — отдельный инструмент диагностики, FROZEN: ручной запуск
`python -m Services.hikvision_camera` при остановленном стенде; оба пути запуска из приложения удаляются (`Services/hikvision_camera/plugin/plugin.py:447` `cmd_open_sdk_app`, таблица команд `:97`,
`presenter.py:130-144`, `controller.py:90`) — запуск из приложения был вторым открывателем камеры (F14) и запуском процесса из GUI (принцип №6). Конверт item (Р10) сохраняет
межисточниковые ключи `frame`, `camera_id: int`, `seq_id`, `frame_id`, `timestamp` и добавляет `device_id`, `ts`, `pixel_format`, `width`, `height`, `device_frame_num`.

**FREEZE и переименование.** После миграции FROZEN остаются `HikvisionCamera` (`core/camera.py`, у `sdk_app`), `SdkCodeReader`
(`code_reader/core/sdk_reader.py`, его тесты остаются) и `CommandPanel` (`frontend/widgets/controls/command_panel.py:41-45` шлёт
`start_capture`/`stop_capture` в `camera_0`; живого создания нет). Старые команды не замораживаются: принцип «FREEZE, не KILL» защищает мёртвый код —
путь без живого вызывающего остаётся контрактом. API, которое владелец сам решил переименовать, — живое: старые имена удаляются, каждый потребитель
переводится в той же точке коммита К4'. Алиасов нет.

### Consequences
- Architectural changes: плагин `hikvision` на общем наборе команд; вкладка GUI и хаб переведены в К4' / 4.6a–d; `sdk_app` вне приложения.
- Migration: потребители команд — Task 4.2a, 4.3, 4.4 (К4'), 4.6d; откат — `git revert` одного коммита, флага миграции нет.
- Constraints: новых алиасов старых имён не добавлять; запуск `sdk_app` из приложения или GUI не восстанавливать.
- Known risks: потребитель по имени команды IPC, не найденный grep (граф его не видит), сломается при запуске; между К4' и хабом (P1) хаб и
  плагин живут в разных коммитах — защита: `cmd_hik_enum` хаба импортирует `enum_devices` напрямую, команду плагина не вызывает (ревью P2).

### Links
- Related: ADR-CAM-001 (общий набор команд — Р7), ADR-HIK-001 (Task 4.3, будет записан своей задачей)
- Related: `plans/2026-10-18_camera-device-service/design.md` («Точки коммита»)

## ADR-CAM-005 — Readiness камеры: одна причина по состоянию сеанса; `out_of_spec` только у `stopping`

**Дата:** 2026-11-20 (запись); решение — таблица П.8 задачи 2.2 плана system-run-state, реализация Task 2.2c
**Статус:** Accepted; пункт про `stopping` при `auto_start` открыт (см. Consequences)
**Task context:** Task 2.2c плана `plans/2026-10-27_system-run-state/` (таблица П.8 в `tasks/2.2.md:36`; отчёты `reports/2.2c.*.md`)

### Context
Контракт хука `readiness` и политика готовности узла — ADR-PM-061 (`multiprocess_framework/modules/process_module/DECISIONS.md`):
плагин отчитывается фактом, степень и удержание задаёт рецепт узла ключом `readiness`. До 2.2c камера всегда отдавала `[]` (запись
`docs/claude/OPEN_QUESTIONS.md` 2026-11-20), `ready` на boot наступал бы до открытия порта (`tasks/2.2.md:36`). Хук зовёт поток снимка готовности (~2 Гц), поэтому он
обязан быть быстрым, без замков и IO (`plugin_base.py:361-368`).

### Alternatives

**A. Читать три поля сеанса: `state`, `device_held`, `last_error` (исходная формулировка П.8)**
- Pros: полная картина сеанса (так была записана П.8 до реализации).
- Cons: `params*` берут замок профиля, `last_error` несёт серийные номера и пути (`plugin_base.py:363-367`); лишнее чтение — лишняя гонка
  (`device_held` не меняет ответ: пара `closed` + `device_held=True` — это `closed`, `plugin_base.py:366-368`).

**B. Читать один голый атрибут `session.state`, текст причины — литерал**
- Pros: хук без замков и IO; текст без значений; ответ — пустой список либо один элемент.
- Cons: причина не говорит, ПОЧЕМУ камера в `error` (текст `last_error` в `reason` не входит); отступление от «трёх чтений» П.8 одобрено
  ревью 2.2c (`tasks/2.2.md:36`).

**C. Для `stopping` — блокирующая степень (`check_function`) при `auto_start`**
- Pros: узел не «зелёный», пока камера останавливается.
- Cons: причина отказа от C в источниках не записана; источник: Task 2.2c — таблица П.8 задаёт `stopping` -> `out_of_spec`.

### Decision
Chose B. Таблица (литералы текста, `plugin_base.py:360-387`, тесты — `tests/test_readiness.py`): `grabbing` -> `[]`; `opening` ->
`check_function`; `stopping` -> `out_of_spec`; `busy`, `not_found`, `error`, неизвестное состояние -> `failure`; `idle`/`closed` ->
`check_function` «камера не запущена» при `auto_start`, иначе `[]`; `session is None` — как `idle`. Блокируют START `failure` и `check_function`
(`health/schema.py:128`). Обоснования, записанные в источниках: `opening` блокирует, «иначе на boot система станет `ready` до открытия порта»
(решение Ф и К 2026-11-16, `tasks/2.2.md:36`); `closed` + `auto_start` блокирует и после `release_device` оператора «намеренно: START
заблокирован» (там же). Причина выбора `out_of_spec` для `stopping` не записана, источник: Task 2.2c.

### Consequences
- Architectural changes: метод `CameraDevicePlugin.readiness` (`plugin_base.py:360`); политику узла (`readiness: {hold_s, severity}`) читает
  `PluginOrchestrator._plugin_reasons`, плагин её не знает (ADR-PM-061). Единственная строка `"out_of_spec"` в ядре — `plugin_base.py:376`.
- Migration: не нужна; ключа `readiness` в рецепте камеры нет, поведение определяет код плагина.
- Constraints: хук не берёт замков (`_lock`, `_session_lock`, `session._lock`, `_profile.lock`), не создаёт сеанс, не читает `params*` и
  `last_error`; текст причины — литерал без значений (тесты `test_readiness_does_not_*`, `test_no_state_leaks_last_error`). Вторая причина
  `out_of_spec` сломает ключ `severity: {out_of_spec: ...}` (он действует на все причины своей степени, ADR-PM-061); пин-теста у камеры нет.
- Known risks: **открыто, не решено** — `stopping` при `auto_start` даёт `out_of_spec`, узел остаётся «зелёным» (ревью Opus 2.2c, запись
  `docs/claude/OPEN_QUESTIONS.md` 2026-11-20). Варианты: (а) в коде `stopping` -> `check_function` при `auto_start`; (б) без кода — ключ
  `readiness: {severity: {out_of_spec: check_function}}` в рецепте узла камеры. Решение ждёт CTO / владельца. Не покрыты кодом пункты (а)–(г)
  П.8 (перезахват внутри `grabbing`, `release_device` в `running`, бесконечный `opening` без таймаута, нет `pause`; `reports/2.2c.review.md`);
  нет теста через настоящий `PluginOrchestrator.readiness_snapshot` и теста на `stopping` на настоящем сеансе (только заглушка).

### Links
- Related: ADR-PM-061 (контракт хука и политика готовности), ADR-PM-062 (`run_locked_commands`; ключ камеры — Task 4c), ADR-CAM-002 (сеанс и состояния)
- Related: `plans/2026-10-27_system-run-state/tasks/2.2.md`, `plans/2026-10-27_system-run-state/reports/2.2c.review.md`

## ADR-CAM-006 — Цвет и дебайер в ядре камеры: потребителям уходит BGR, формат прибора — в `source_format`

**Дата:** 2026-11-22 (решение владельца 2026-11-20; реализация Task 4.2a, запись — Task 4.2c)
**Статус:** Accepted; для `mono8` (серый или BGR) — отклонение от записи 11-20, ждёт владельца
**Task context:** Task 4.2a плана `plans/2026-10-18_camera-device-service/tasks/4.2a.md` (блок «РЕШЕНИЯ 2026-11-20»); Task 4.2c; коммит `6de54a088`

### Context
Драйвер MVS (Task 4.1) отдаёт кадр честно, в формате прибора (`rgb8`, `bayer_*8`, `mono8`). Потребители кадра в рецептах — симулятор
`scene_source`, `mjpeg_sink`, `overlay_draw`, `frame_saver` — ждут `image/bgr (H, W, 3)`, 8 бит. Старый плагин `hikvision` конвертировал сам,
а шаг `color_convert` после камеры дублировал это в рецептах. Переводя `hikvision` на ядро (Task 4.2a), нужно решить, кто и где приводит цвет.
До 4.2a ядро дебайер не делало: `bayer_*` считался одним каналом и уходил потребителю сырой мозаикой.

### Alternatives

**A. Цвет в ядре (`CameraDevicePlugin._frame_array`)**
- Pros: одно место для всех вендоров; item у любого цветного источника одинаков; плагин вендора не повторяет таблицу дебайера.
- Cons: ядро получает зависимость от `cv2` (правило ADR-CAM-001); таблица форматов растёт вместе с ядром.

**B. Цвет в вендорском плагине (`hikvision`), ядро отдаёт кадр как есть**
- Pros: правило ADR-CAM-001 про `cv2` не трогаем; ядро не знает о цветовых форматах.
- Cons: каждый следующий вендор с цветным прибором повторяет конвертацию; форма кадра в ядре зависит от `pixel_format`, потребитель должен ветвиться.

**C. Оставить шаг `color_convert` в рецептах после камеры**
- Pros: ничего не менять в плагинах.
- Cons: потребитель, подключённый напрямую к камере, получает мозаику; рецепт обязан знать формат прибора; `outputs` плагина — атрибут класса,
  по `pixel_format` не выбирается, поэтому честно заявить «выход — BGR» нельзя.

### Decision
Chose A (решение владельца 2026-11-20; формат кадра выбирал лид полосы К по требованиям симулятора). Правила в `_frame_array` (`plugin_base.py:559`):

| `pixel_format` прибора | Кадр в ядре |
|---|---|
| `bgr8` | как есть, копия, `(H, W, 3)` |
| `rgb8` | `np.ascontiguousarray(frame[..., ::-1])` -> BGR; срез с отрицательным шагом не непрерывен, копия обязательна |
| `bayer_rg8` / `bayer_bg8` / `bayer_gr8` / `bayer_gb8` | `cv2.cvtColor` -> BGR |
| `mono8` | остаётся `(H, W)`, без конвертации |
| `bayer_*10`, `bayer_*12`, `mono16`, прочие | кадр отбрасывается: `dropped += 1`, `last_error` непустой, счётчик `errors` не растёт |

Имена констант OpenCV инвертированы относительно GenICam (`_DEBAYER_CODE`, `plugin_base.py:81`): `bayer_rg8 -> COLOR_BayerBG2BGR`,
`bayer_bg8 -> COLOR_BayerRG2BGR`, `bayer_gr8 -> COLOR_BayerGB2BGR`, `bayer_gb8 -> COLOR_BayerGR2BGR`. Проверено на синтетической мозаике,
`cv2` 4.13.0; железом не проверено. `import cv2` ленивый, внутри ветки дебайера; `cv2.error` превращается в `ValueError` (`produce()` ловит только его).
Item: `pixel_format="bgr8"` для цветных источников, новый ключ `source_format` — формат прибора (`rgb8`, `bayer_rg8`, …); у `mono8` `pixel_format`
остаётся `mono8`. Вендорский плагин `hikvision` дополнительно приводит кадр к `(resolution_height, resolution_width, 3)` (слот SHM), см. `tasks/4.2a.md`.
Достоинство: потребитель читает один формат; цена: ядро знает цвет и тянет `cv2` (уточнение ADR-CAM-001).

### Consequences
- Architectural changes: `_CHANNELS` и `_DEBAYER_CODE` в `plugin_base.py`; новый ключ item `source_format`; ленивый `import cv2` в ядре.
  Шаг `color_convert` после камеры в рецептах `hikvision` лишний, его снятие — Task 4.3.
- Migration: потребитель `bayer_*` кадров получал `(H, W)`, теперь `(H, W, 3)` BGR; `pixel_format` цветного источника теперь `bgr8`, а не формат
  прибора — формат прибора читать из `source_format`. Тесты ядра на `mono8` не меняются.
- Constraints: `cv2` в ядре — только внутри ветки дебайера (ADR-CAM-001, уточнение); `bayer` 10/12 бит и `mono16` ядро не принимает.
  Новый формат прибора = строка в `_CHANNELS` (и в `_DEBAYER_CODE` для Байера) плюс тест на литералах.
- Known risks:
  - Порядок каналов `rgb8` и дебайер реального `BayerRG8` проверены только синтетикой и фейком; железом не проверено. Остальные три
    паттерна, кроме `bayer_rg8`, подтверждены литералами тестов, не симметрией. Проверка на визите: цвет белой стены и лампы.
  - `mono8`: запись 11-20 говорила «`image/gray (H, W)`»; ядро держит `(H, W)`, но вендорский плагин отдаёт BGR (`GRAY2BGR`), потому что `outputs` —
    атрибут класса. Вернуть серый = убрать `GRAY2BGR` и ввести поле `output_color` в регистры. Решение ждёт владельца (`docs/claude/OPEN_QUESTIONS.md`, запись 2026-11-22).
  - Дебайер на каждом кадре стоит процессорного времени; замера на размере кадра 2592x1944 нет.

### Links
- Supersedes: нет; уточняет ADR-CAM-001 (правило про `cv2`/`numpy`)
- Related: `plans/2026-10-18_camera-device-service/tasks/4.2a.md`; `Services/camera_device/plugin_base.py` (`_frame_array`, `_build_item`)
