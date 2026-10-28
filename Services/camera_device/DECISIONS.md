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
Chose A + P2 + V2. Идентичность прибора обязательна, `select: first` — только явно (Р3). Допуск чтения: float/int —
`|read − target| ≤ max(inc or 0, 1e-3·|target|, eps_abs)`, `eps_abs` — поле `Binding` (умолчание `1e-6`: у float-узлов MVS шага нет,
`Services/hikvision_camera/sdk/structures.py:196-204`); enum — по символьному имени; в `params` пишется прочитанное. При H5 (код ≠ 0, чтение = цель) —
`verified: True` плюс `rc`. Без capability `read_back` — статус `unverified` (не ошибка и не «подтверждено»). Пауза перезапуска ≥ 10 с — это
`restart_policy.backoff_sec: 10.0` процесса в рецепте (Task 3.3, 4.3), поля плагина нет (ревью B3). Живая правка исполняется потоком-владельцем из очереди (Р12).

### Consequences
- Architectural changes: `session.py` (поток, очередь, профили), `params.py` (план записи); порт вызывается только из потока-владельца.
- Migration: `code_reader_sdk` теряет ADR-CR-010 (возврат исходных) — ADR-CR-011 в Task 3.2.
- Constraints: два экземпляра плагина в одном процессе запрещены (инвариант идёт в README ядра); убитый процесс оставляет камеру в профиле run (риск принят).
- Known risks: **основание «поток-владелец» — устранение класса дефектов, не доказанный отказ.** Опыты не подтвердили H1 (запись после
  `stop_grabbing` отвергается): ID3013 21/21 `rc=OK` (`tasks/6.2.result.md`), MVS `rc=0x0` при паузе 0 и 1,0 с (`tasks/0.5.result.md`, по одному прогону);
  H2 (SDK привязан к потоку): ID3013 `split` 9/9, `same` 12/12 OK, MVS оба режима OK; H5 не спровоцирована (ID3013 NETER 0 из 30; у MVS `Width` при
  захвате честно отказан `0x80000106`, значение не менялось). Поток-владелец остаётся дешёвой страховкой; перезахват `stop -> план -> start_grabbing`
  в том же handle у `mvcr` не измерен (шлюз Task 6.4). Шторм `EnumDevices` из трёх процессов не проверен.

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
`python -m Services.hikvision_camera` при остановленном стенде; оба пути запуска из приложения удаляются (`plugin.py:400-422`,
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
