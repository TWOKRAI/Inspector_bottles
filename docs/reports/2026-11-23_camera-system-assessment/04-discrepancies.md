# Расхождения с design-документами и со страницей от 17 ноября

Часть отчёта [README.md](README.md). Сокращения путей: `plan/` = `plans/2026-10-18_camera-device-service/`; `cd/` = `Services/camera_device/`;
`hik/` = `Services/hikvision_camera/`. Вердикт «чьё»: **документ** — документ устарел или забежал вперёд; **код** — код не выполнил
обещание, срок которого уже наступил; **план** — обещание P1/P2, срок не наступил, код его ещё не делал.

## 1. Решения и обещания плана против кода `main`

### (а) Реестр драйверов

- **а1. Реестр строк `drivers/__init__.py`.**
  - Решено: «Реестр драйверов — словарь строк в `Services/camera_device/drivers/__init__.py` … реестр — P1 (5.1)» (`plan/decisions.md:20`, Р11).
  - ADR-CAM-001 говорит в настоящем времени: «Ядро знает вендоров только по строкам реестра» (`cd/DECISIONS.md:41-43`). README ядра — тоже: «драйверы подключаются строками реестра `drivers/__init__.py` (ADR-CAM-001)» (`cd/README.md:315`).
  - Код: каталога `cd/drivers/` нет (`git ls-files Services/camera_device`). `create_port(driver)` знает только `"fake"` (`cd/plugin_base.py:126-132`). Hikvision переопределяет `create_port()` ленивым импортом (`hik/plugin/plugin.py:39-43`); Р11 и R-b это разрешают (`plan/tasks/5.1.md:17`).
  - Чьё: **документ** (ADR-CAM-001 и README описывают P1 как готовое) и **план** (5.1 не начата).
- **а2. Поле `driver` у вендора.**
  - Обещано: «вендорский плагин переопределяет `driver` константой и register не даёт его менять (`readonly`)» (`plan/tasks/5.1.md:18`).
  - Код: у Hikvision поле `driver` правится, умолчание `"fake"`, плагин его не читает (`cd/registers_base.py:27-30`, `hik/plugin/plugin.py:39-43`). Рецепт с `driver: opencv` на узле `hikvision` молча ничего не меняет (вывод чтения кода, не запуск).
  - Чьё: **план** (часть 5.1).
- **а3. `cv2` и `numpy` в ядре.**
  - Решено: «`cv2`/`numpy` — только `drivers/opencv_driver.py` и `testing/`» (`cd/DECISIONS.md:44`, ADR-CAM-001; то же — `plan/decisions.md:37`).
  - Код: `numpy` на верхнем уровне `cd/plugin_base.py:58`, ленивый `cv2` в ветке дебайера `:577`, `pydantic` в `cd/commands.py:26`. README уже это описывает (`cd/README.md:310-314`); дебайер в ядро перенёс ADR-CAM-006 (`cd/DECISIONS.md:296`).
  - Чьё: **документ** (строку ADR-CAM-001 и `decisions.md:37` после ADR-CAM-006 не поправили; ссылку «заменено» я в ADR-CAM-001 не нашёл).

### (б) Задача 4.2b и старый путь `core/*`

- **б1. Что 4.2b обещала.** Удалить тесты удалённых команд; `service.py`: `get_status() -> "shell"`, `start() -> False`; ADR-HIK-001; README с командами Р7 и `sdk_app` FROZEN (`plan/tasks/4.2b.md:17-22`, приёмка `:33`).
  - Код: `hik/service.py:29` и `:55-59` — `"shell"`; старых команд в плагине нет (`cd/plugin_base.py:177-187`; `hik/tests/test_plugin_on_core_contract.py:54` держит `open_sdk_app` в списке удалённых); ADR-HIK-001 есть (`hik/DECISIONS.md:7`).
  - Чьё: расхождения нет, 4.2b выполнена.
- **б2. Что 4.2b говорила про `core/*`.** Удалять `core/*` 4.2b не обещала. Она оставляет `HikvisionCamera` (`core/camera.py`) FROZEN вне объёма (`plan/tasks/4.2b.md:40`); Р14 — «`HikvisionCamera` … остаётся у `sdk_app`» (`plan/decisions.md:25`).
  - ADR-HIK-001 называет одного пользователя: «`HikvisionCamera` (`core/camera.py`) FROZEN: им пользуется `sdk_app`» (`hik/DECISIONS.md:42-43`).
  - Код: `HikvisionCamera` создают ещё хаб (`Services/device_hub/drivers/hikvision_driver.py:73-77`) и `camera_service` (`Plugins/sources/camera_service/backends/hikvision.py:67`). Пакет грузит `core` при импорте (`hik/__init__.py:18-21`). Новый плагин берёт `core.converter.FrameConverter` (`hik/plugin/plugin.py:16`).
  - Чьё: **документ** (ADR-HIK-001 и Р14 неполны: у пути есть живые вызывающие, значит это не мёртвый код под FREEZE, а живой путь до 4.5 и 4.6d). Карточка `hikvision_camera` в arch-review («старый путь убирает задача 4.2b») неверна.
- **б3. README и STATUS вендора.**
  - README обновлён частично: команды Р7 есть (`hik/README.md:161-166`, `:405`), но схема и классы старые — «`HikvisionCameraPlugin (ProcessModulePlugin)`» (`hik/README.md:23`, `:217`, `:303`) и раздел «Быстрый старт (Core API без фреймворка)» (`:49`). В коде плагин наследует `CameraDevicePlugin` (`hik/plugin/plugin.py:26`). Про `driver.py` README молчит.
  - `hik/STATUS.md:1-5`: «hikvision_camera_module_2», «Готов к использованию», дата 2026-05-08. О ядре, драйвере `mvs` и К4' там ничего нет.
  - Чьё: **документ** (4.2b обещала README; задача закрыта, а схема и классы не переписаны).

### (в) Р9, Р10, Р12 и «хаб — зеркало владельца»

- **в1. Р9, `sdk_app`.** Решено: убрать команду `open_sdk_app` и `Popen` во вкладке; запуск только вручную (`plan/decisions.md:18`).
  - Код: команды нет; `subprocess.Popen` во вкладке `services/hikvision` нет (поиск по `Services`, `Plugins`, вкладке). Остаток — строка докстринга «Или из плагина: cmd_open_sdk_app» во FROZEN-файле `hik/sdk_app/main_window.py:9`.
  - Чьё: расхождения по коду нет; устаревший комментарий во FROZEN-файле — **документ**, правка запрещена FREEZE (`plan/tasks/4.2b.md:43`).
- **в2. Р10, конверт item.** Решено: ключи `frame`, `camera_id`, `seq_id`, `frame_id`, `timestamp` плюс `device_id`, `ts`, `pixel_format`, `width`, `height`, `device_frame_num`; `seq_id` без переполнения (`plan/decisions.md:19`).
  - Код: все ключи есть, плюс `source_format` (`cd/plugin_base.py:585-601`); `self._seq += 1` без модуля (`:405`). У `phone_gateway` свой `seq_id` (`Services/phone_gateway/plugin/plugin.py:163`) — вне плана.
  - Чьё: расхождения нет.
- **в3. Р12, живая правка.** Решено: `subscribe` -> очередь владельца; `live` только с `live_write`, иначе как `restart`; `restart` — перезахват при `restart_regrab`, иначе `close -> open -> план -> start` (`plan/decisions.md:21`). Умолчание по прибору выбирают опыты 0.5 и 6.2 (`docs/design/camera-device-service.md:202`; риск 1 — `plan/design.md:53`).
  - Код: путь совпадает (`cd/plugin_base.py:233-304`, `cd/session.py:363-384`, `:708-776`). У MVS нет ни `live_write`, ни `restart_regrab` (`hik/driver.py:63`), поэтому всегда `close`/`open`.
  - Чьё: с Р12 расхождения нет. Открыто решение «умолчание для MVS после 0.5»: в прочитанных мной документах его итога нет — **план**.
- **в4. Хаб — реестр и зеркало владельца (P1).** Решено: хаб камеру не открывает; `CameraMirrorDriver`, `camera_owner`, `camera_list_devices`, `camera_read_params`; `hik_*` отвечают отказом, `hik_release` — no-op (`plan/decisions.md:17`, Р8; П11 — `docs/design/camera-device-service.md:31`, `:223`; ADR-DH ×2 — `plan/decisions.md:56`). Хаб — после М2 (`plan/design.md:29-30`); К4' без хаба (`plan/amendments.md:22`).
  - Код: `git grep` по `CameraMirrorDriver|camera_owner|camera_list_devices` в `*.py` — 0 строк. `hik_open` и другие идут в драйвер (`Plugins/hub/device_hub/plugin.py:1283-1310`); `HikvisionDriver.connect` открывает камеру (`Services/device_hub/drivers/hikvision_driver.py:67-79`).
  - Дефект F1 «`connect()` -> `True` при отказе» (`plan/design.md:46`): сейчас `connect` возвращает `False` на исключении (`hikvision_driver.py:80-83`). Возвращает ли `HikvisionCamera.open` отказ без исключения — не проверял.
  - Чьё: **план** (P1, срок после М2). Риск принят текстом плана, но в коде он живой: см. [слабое место 1](02-weaknesses.md).

### (г) Вехи М1–М3 и приоритеты P1/P2

- **г1. М1** — старый `hikvision` даёт цветной кадр, параметры рецепта после `open`, дерево узлов записано (`plan/plan.md:34`). Статус: 0.5 PARTIAL, нет набора кадров дисков (`plan/plan.md:111`). Чьё: статус плана верен.
- **г2. М2** — MVS на ядре: все вызовы SDK из владельца, run полностью, проверка чтением, выбор по serial, поля через `backend_ctl` (`set_register_verified` + `await_condition`), `health` при `busy` (`plan/plan.md:35`). Статус: 6.3 PENDING (`plan/plan.md:112`).
  - Что есть: по брифу лида — стенд 2026-11-23 на ядре, 24,97 Гц, `param_errors {}`, перезахват `release_device -> take_device` (`OPEN_QUESTIONS.md:2622`). Код для всех условий М2 есть.
  - Чего нет: отчёта приёмки 6.3 в дереве. Пунктов «поля через `backend_ctl`» и «`health` при `busy`» в записи стенда нет.
  - Чьё: не подтверждено. Либо **документ** (статус 6.3 не обновлён), либо М2 закрыта не полностью — по дереву решить нельзя.
- **г3. М3** — 2 MVS по serial (6.3) и 2 ID3013 5 мин (6.4) (`plan/plan.md:36`). Половина ID3013 вынесена из 1.0 амендментом 5 (`plan/amendments.md:144`, `plan/plan.md:117`). Рецепт `hikvision_dual.yaml` есть; на стенде была одна камера (`OPEN_QUESTIONS.md:2622` называет один серийный номер).
  - Чьё: М3 не сделана. Определение М3 в `plan.md:36` не учитывает амендмент 5 — **документ**.
- **г4. P1** — хаб не открывает камеру (4.6b), три драйвера и фейк проходят один контрактный тест (5.3), `backend_ctl` видит форму команд и диапазоны (1.3, 1.4) (`plan/plan.md:37`). Код: ни одного из трёх (в4, а1; `command_contracts` в ядре есть только в комментарии `cd/commands.py:15`). Чьё: **план**, статусы PENDING верны.
- **г5. P2** — 3.4, 4.5, 5.4 (`plan/plan.md:138-141`). Код: нет. Чьё: **план**.
- **г6. Шапка плана.** `plan/plan.md:5` — «следующая — W3»; `:95-112` — 2.3a–2.4, 4.1, 4.2a–4.4 `[PENDING]`. По коду и слияниям `6cb212213`, `dc7883ce6` они в `main`. Чьё: **документ**.

## 2. Прочие документы против кода

- `docs/design/camera-device-architecture.md` §2.1: «хаб камеру не открывает, а зеркалит». В коде хаб открывает камеру (см. в4).
- Там же §2.1: `HikvisionCamera` — FROZEN только для `sdk_app`. В коде её грузят ещё хаб, `camera_service` и `__init__.py` пакета (см. б2).
- Там же §2.2: ветка `apply live и capability live_write`. У MVS этой capability нет, поэтому живёт только ветка `close`/`open`.
- Там же §2.4: `code_reader` — «тонкий переводчик». Задача отложена, на ядре его нет.
- `cd/README.md:6-8` и `:71-72`: «драйвер только `fake`», «команды Р7 — следующие задачи». Устарело: 9 команд в коде, вендор MVS есть.
- `cd/README.md:303`: «в hikvision-рецептах ключа `run_locked_commands` нет». Ключ есть в 6 рецептах.
- `cd/STATUS.md` (дата 2026-11-20): «2.3a, 2.3b, 2.4 — нет». Всё это в коде.
- `cd/registers_base.py:29`: «сейчас известен только fake»; `cd/plugin_base.py:174`: `Port dtype="image/gray"` у базы, хотя база отдаёт цветной кадр как BGR.

## 3. Страница `docs/diagrams/camera-device/camera-service_artifact_2026-11-17.html`

- Строки 116 и 386: «на настоящей MVS не запускалось». Устарело: стенд 2026-11-23 прошёл по брифу лида (`OPEN_QUESTIONS.md:2622`).
- Строка 198: «Девять команд» — в ветке. Сейчас в `main` (`cd/plugin_base.py:177-187`).
- Строки 233-237 и 308: без захвата список камер делает «поток команды, под замком». В коде `_enumerate_here` идёт без замка (`cd/plugin_base.py:853-861`). Замок `MvsSdk._lock` охраняет только счётчик ссылок (`hik/driver.py:178-191`). README сам пишет «замка нет» (`cd/README.md:251-254`).
- Строка 240: «несколько камер в одном процессе возможны». README запрещает два экземпляра плагина камеры в одном процессе (`cd/README.md:318-319`, ADR-CAM-002).
- Строка 319: «371 прошёл». Позже было 462 (ядро) и 314 (вендор), по отчёту W4.
- Строки 325 и 351: «15 в main», «до железа 8 задач». Устарело после слияний `6cb212213` и `dc7883ce6`; пересчёт задач я не делал.
- Строка 380: «RGB или BGR — решить до 4.2a». Решено: BGR (`cd/plugin_base.py:574-575`, ADR-CAM-006 — `cd/DECISIONS.md:296`).
- Строка 299: «для MVS живая правка — закрыть, открыть, записать весь план». Совпадает с кодом и остаётся верным.

## 4. Карточки `docs/reports/2026-11-22_fable-architecture-review/arch-review-01-architecture-schemes.html`

Строки кода сходятся: 2962 у `camera_device`, 4515 у `hikvision_camera`. Текст карточки `hikvision_camera` «Старый путь Hikvision убирает задача 4.2b» с кодом и с задачей не сходится (см. б2).
