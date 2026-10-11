# Ответы для ручной оценки точности

## chain / chain / ход 1 / rep1 / A (275 слов)

После `python multiprocess_prototype/run.py` (без аргументов, с текущим `app.yaml`) получается такое дерево процессов:

**Служебные**
- **Главный процесс.** `run.py` при необходимости перезапускается через проектный `.venv`, затем `main()` → `run_app` → `SystemBuilder.build()` → `SystemLauncher`.
- **`ProcessManagerProcess`** — оркестратор, он поднимает дочерние процессы (`SystemLauncher → ProcessManagerProcess → ProcessModule`, по `CLAUDE.md`). Что это отдельный процесс ОС, я взял из документации и в коде не проверял.

**Дочерние процессы.** Это фундамент `backend/topology/base.yaml` плюс активный рецепт `recipes/webcam_sketch.yaml`:

| Процесс | Что делает |
|---|---|
| `gui` | `HeadlessGuiProcess`, то есть заглушка без окна (подробнее ниже) |
| `devices` | `device_hub`, реестр устройств. Есть и в фундаменте, и в рецепте; при склейке побеждает фундамент, дубль из рецепта отбрасывается с предупреждением (`launch.py:161-167`) |
| `camera_0` | `capture`, захват кадров с вебкамеры |
| `seg` | `segmentation` и `image_adjust` |
| `lines` | `crop`, `edge_detection`, `blob_filter`, `strokes_to_points`, `text_main`, `text_name` |
| `points` | `robot_scale`, `drawing_io`, `points_render`, `robot_draw` |
| `pult` | `control_panel` |

**Почему нет окна.** В `app.yaml` нет ключа `presentation`, поэтому при запуске через `run.py` настоящего Qt-GUI не будет. Процесс `gui` останется headless-заглушкой, а в лог уйдёт `[launch] presentation: overlay не задан`. Чтобы появилось окно, презентацию нужно подключить: через env `INSPECTOR_PRESENTATION` (его выставляет фронтовый вход `frontend/run.py`) или ключом `presentation:` в манифесте. Тогда overlay `frontend/presentation.yaml` подменит процесс `gui` на настоящий. Флаг `--headless` или `INSPECTOR_HEADLESS=1` отключает презентацию, даже если она задана.

Если передать имя рецепта (`run.py <recipe>`), оно запишется в `app.yaml: pipeline`, и вместо `seg`, `lines`, `points`, `pult` будут процессы того рецепта. `gui` и `devices` из фундамента остаются всегда.

Что не проверено: я читал только конфиги и `launch.py`, живой стенд не запускал. Наличие `ProcessManagerProcess` как отдельного процесса ОС взято из `CLAUDE.md`. Если нужен точный список PID, лучше поднять систему и посмотреть через `backend_ctl`.

## chain / chain / ход 1 / rep1 / B (139 слов)

Состав процессов задаёт не `run.py`, а топология, которую собирают из трёх слоёв в `app.yaml`. Живой запуск я не делал: ответ собран по конфигам.

**Всегда есть:**
1. Главный процесс: `run.py` → `main()` → `SystemLauncher`.
2. `ProcessManagerProcess` запускает дочерние процессы и следит за ними.

**Фундамент (`backend/topology/base.yaml`):**
3. `devices`.

**Презентация (`frontend/presentation.yaml`), если нет `--headless`:**
4. `gui` с классом `GuiProcess` (PySide6).

**Активный рецепт `recipes/webcam_sketch.yaml`:**
5. `camera_0`
6. `seg`
7. `lines`
8. `points`
9. `pult`

Рецепт тоже объявляет `gui` и `devices`. При совпадении имён побеждает фундамент: такие дубли пропускает `backend/launch.py:162`. В режиме `--headless` слой презентации не подключается. Тогда `gui`, видимо, берётся из рецепта как `HeadlessGuiProcess`, но это я не проверял.

Итого 9 процессов в обычном режиме. Если указать другой рецепт (`run.py <recipe>`) или сменить `pipeline:` в `app.yaml`, пункты 5–9 изменятся.

## chain / chain / ход 1 / rep2 / A (211 слов)

Состав процессов не зашит в коде. Его собирает `SystemBuilder` (`multiprocess_prototype/backend/launch.py`) из манифеста `multiprocess_prototype/app.yaml`. Это три части: фундамент `base`, затем рецепт `pipeline`, затем overlay презентации. Сейчас в манифесте стоит рецепт `recipes/webcam_sketch.yaml`.

**Служебный уровень**
- **Главный процесс** — `run.py` → `main()` → `SystemLauncher`.
- **Оркестратор** — `ProcessManagerProcessApp` (`multiprocess_prototype.orchestrator`). Он запускает дочерние процессы и меняет топологию при смене рецепта.

**Дочерние процессы (фундамент и рецепт `webcam_sketch`)**

| Процесс | Класс | Откуда |
|---|---|---|
| `devices` | `GenericProcessApp` | `base.yaml`. Рецепт тоже объявляет его, но копия из рецепта отбрасывается, остаётся версия фундамента |
| `gui` | `HeadlessGuiProcess`. Без `--headless` overlay заменяет его на Qt-шный `GuiProcess` | рецепт |
| `camera_0` | `GenericProcessApp` | рецепт: вебкамера |
| `seg` | `GenericProcessApp` | рецепт |
| `lines` | `GenericProcessApp` | рецепт: line-art (TEED) |
| `points` | `GenericProcessApp` | рецепт: карта точек робота |
| `pult` | `GenericProcessApp` | рецепт |

Всего 7 дочерних процессов плюс оркестратор и главный процесс. Все рабочие процессы одного класса `GenericProcessApp`, а различаются они набором плагинов и связями (`wires`) в рецепте.

Что учесть:
- При другом рецепте во вкладке Recipes или в строке `pipeline:` состав будет другим.
- Опциональный фрагмент `observability_sink.yaml` (история телеметрии в SQLite) в `app.yaml` закомментирован, поэтому этого процесса сейчас нет.
- Комментарий в `app.yaml:41` называет активным рецептом `color_inspect`, а строка 44 указывает `webcam_sketch`. Комментарий устарел.
- Я собрал состав по конфигам и коду и живьём систему не запускал. Точное число процессов выводит стартовый баннер (`processes: N`).

## chain / chain / ход 1 / rep2 / B (132 слов)

С текущим `app.yaml` (рецепт `recipes/webcam_sketch.yaml`) запускаются 8 процессов. Список я собрал по конфигам, систему живьём не запускал.

**Хозяин**
- `ProcessManagerProcessApp` — оркестратор. Лончер добавляет его отдельно через `orchestrator_class_path`, в YAML его нет.

**Фундамент** (`backend/topology/base.yaml`)
- `devices` — `DeviceHubPlugin`, защищён (`protected`). Тот же процесс объявлен и в рецепте. Как сборка сливает дубль, я не проверял.

**Рецепт `webcam_sketch`**
- `gui` — по умолчанию `HeadlessGuiProcess`. Без `--headless` / `INSPECTOR_HEADLESS` overlay `frontend/presentation.yaml` заменяет его классом на Qt.
- `camera_0` — захват с вебкамеры, авто-рестарт до 3 раз за 60 с.
- `seg` — сегментация и `image_adjust`.
- `lines` — crop, TEED, blob_filter, strokes_to_points, два text_vector.
- `points` — robot_scale, drawing_io, points_render, robot_draw.
- `pult` — пульт `ControlPanelPlugin`.

Если в `app.yaml` раскомментировать `observability_sink.yaml`, добавится сток истории телеметрии в SQLite. Другой рецепт (из `app.yaml` или первым аргументом `run.py`) меняет состав процессов рецепта.

## chain / chain / ход 2 / rep1 / A (344 слов)

Процессы общаются тремя путями. Все они проходят через `RouterManager`, а тот работает поверх очередей, событий и shared memory из `SharedResourcesManager` (SRM). Между процессами ходит только `dict` (правило «Dict at Boundary»), а крупные кадры передаются через SHM.

**1. Поток данных конвейера (кадры и точки)**
- Выход процесса уходит сообщением `{"target": <процесс>, "type": "data", "channel": "data", "data": item}` (`pipeline_executor.py:520-527`). Адресат берётся из `item["target"]`, а если его нет — из `chain_targets` процесса.
- Сам кадр в очередь не кладётся. Перед отправкой `FrameShmMiddleware` переносит массив в SHM, а в сообщении остаётся только ссылка на него (схема Claim Check). Получатель восстанавливает кадр из SHM и потом отправляет владельцу `shm_release` через системную очередь, чтобы слот освободился (`pipeline_executor.py:448`).
- В рецепте `webcam_sketch` межпроцессные связи такие:
  - `camera_0.capture → seg.segmentation`
  - `seg.image_adjust → lines.crop`
  - `lines.text_name → points.robot_scale`
  - `pult.control_panel.out_1 → points.robot_draw.trigger` (кнопка «Рисовать»)

**2. Кадры для дисплеев.** Узлы из раздела `displays:` пишут кадры в именованные SHM-каналы `display_module`: `orig`, `lineart`, `points`. Сегменты создаёт SRM при старте по blueprint, а читает их `gui`.

**3. Управление и состояние**
- **Команды и регистры.** Через `send_message(target, msg)` по имени процесса, у каждого процесса есть системная очередь. GUI отправляет `register_update` в процессы, указанные в `register_dispatch` / `connection_map`, а бэкенд подписывает обработчики на каналы Router (`FieldRouting.channel`, обычно `control_*`). Имя процесса и канал Router — разные оси адресации, их легко спутать (`ROUTING_GLOSSARY.md`).
- **Общее состояние.** Сервер `StateStoreManager` живёт в `ProcessManagerProcess`. В каждом процессе есть клиент `StateProxy` с локальным кэшем и подпиской на glob-шаблоны: он вызывает IPC-команды `state.set/merge/get/subscribe/…` и получает дельты.
- **Логи, ошибки, метрики** идут отдельной плоскостью наблюдаемости, транспорт конвейера они не используют.

Что не проверено:
- Я не проверял, как `wires:` превращаются в `chain_targets`. В рецепте видны оба поля, а отправка в коде идёт по `chain_targets`. Похоже, что `wires` указывают на конкретный порт плагина, а `chain_targets` задают процесс-адресат, но преобразование в `blueprint.py` я не открывал.
- Кто именно читает SHM дисплеев — headless-заглушка `gui` или только настоящий Qt-GUI, — тоже не проверял.

Если нужна полная карта (кто что отправляет и кто на что подписан), её построит `/analysis:channel-map`.

## chain / chain / ход 2 / rep1 / B (154 слов)

Процессы обмениваются только `dict` через очереди `multiprocessing`. Кадры идут отдельно, через разделяемую память. Это я прочитал в коде, на живом стенде не проверял.

**Цепочка отправки:**
1. Код процесса собирает `Message`, а `MessageAdapter` превращает его в `dict` (правило «Dict at Boundary»).
2. `RouterManager` кладёт сообщение в `AsyncSender`. Это фоновый поток с `PriorityQueue`: приоритеты `urgent`/`high`/`normal`/`low`, буфер на 512 сообщений (`router_module/core/_sender.py`).
3. Поток кладёт `dict` в очередь процесса-получателя (`shared_resources_module/queues/core/manager.py:285`).

**Очереди:** у каждого процесса свои, именованные по типу. В тестах и коде встречаются типы `system` и `data`. Судя по счётчику `system_evict_blocked`, сообщения `system` при переполнении не вытесняются. Очереди `data` при переполнении вытесняют старые сообщения.

**Кадры:** процесс пишет изображение в SHM-слот. По IPC уходит только `{owner, slot, seq_id}`, получатель читает кадр из слота сам.

**Адресация:** нужно различать два понятия:
- **имя процесса** — `targets`, `send_message`, `chain_targets` в YAML;
- **канал Router** — `msg["channel"]`, `FieldRouting.channel`.

Подробности — в `ROUTING_GLOSSARY.md`.

## chain / chain / ход 2 / rep2 / A (399 слов)

Процессы не делят общие объекты. Между ними ходят только `dict` (правило Dict at Boundary) по `multiprocessing`-очередям, а кадры лежат в разделяемой памяти. Каналов три.

**1. Почтовые ящики процесса (очереди)**
Каждому процессу `shared_resources_module` создаёт набор именованных очередей (`state/process_data.py:32`):

| Очередь | Что везёт | Политика |
|---|---|---|
| `system` | управление: heartbeat, `process.stop` и т. п. | без потерь |
| `data` | данные pipeline, в том числе извещения о кадрах | ограничена по размеру |
| `state` | `state.changed` (реактивное дерево состояния) | drop_oldest |
| `observability` | логи и телеметрия | best_effort, drop_oldest |
| `commands` / `results` | команды и ответы | — |

Для остановки, паузы и возобновления есть ещё события `stop` / `pause` / `resume`.

Управление, логи и состояние разнесены по разным очередям намеренно. Раньше всё шло через одну `system`, и поток логов вытеснял управляющие сообщения: замер дал 97 066 отказов доставки за ~25 минут.

**2. Router: кто кому шлёт**
Внутри процесса `RouterManager` получает сообщение (`Message` → `dict`) и выбирает канал (`QueueChannel` поверх очереди):
1. если задан `msg["channel"]`, канал берётся сразу по имени;
2. иначе срабатывает dispatcher: точное совпадение, шаблон или broadcast (fan-out).

Здесь легко спутать два понятия (`docs/ROUTING_GLOSSARY.md`). **Имя процесса** — это получатель, `send_message(target, msg)` и `targets`. **Канал Router** — это конкретная очередь, `FieldRouting(channel=...)`. Они не обязаны совпадать.

**3. Кадры: SHM-кольцо и короткое извещение**
Изображения через очередь не копируются. Процесс-источник (например, `camera_0`) пишет кадр в кольцо слотов в shared memory (`RingBufferWriter`, K слотов). Получателю в `data` уходит только маленькое сообщение `frame_ready` с `seq_id` и `slot_index`. Получатель читает кадр из SHM (`ShmFrameReader`). Если получатель отстал, самый старый кадр выбрасывается (drop-oldest). Глубина кольца задаёт допустимое число кадров «в полёте» (`blueprint.py:585`).

**Как это выглядит в рецепте `webcam_sketch`**
Связи объявлены в `wires` (формат `процесс.узел.порт`), сборщик сам превращает их в доставку между процессами:

```
camera_0.capture.frame         → seg.segmentation.frame      (кадр)
seg.image_adjust.frame         → lines.crop.frame            (кадр)
lines.text_name.draw_points    → points.robot_scale.draw_points
pult.control_panel.out_1       → points.robot_draw.trigger   (кнопка «Рисовать»)
```

Кроме того, `pult` шлёт результат напрямую в `points` через `chain_targets`. Секция `displays` отдаёт кадры из `seg` и `lines` в `gui` для показа.

**GUI ↔ бэкенд**
`gui` общается с остальными как обычный процесс. Изменения настроек уходят сообщениями `register_update`, адресат берётся из `register_dispatch` / `connection_map`. Назад GUI получает `state.changed` и кадры для дисплеев. Сам GUI ничего не запускает: топологию применяет оркестратор.

Эту схему я собрал по коду и документации фреймворка, живой поток сообщений не снимал. Точную карту «кто что шлёт и на что подписан» строит `/channel-map`, а живой трафик можно посмотреть через `backend_ctl`.

## chain / chain / ход 2 / rep2 / B (153 слов)

Процессы обмениваются сообщениями-словарями через очереди и передают кадры через разделяемую память. Эту схему я собрал по `CLAUDE.md`, рецепту и структуре `shared_resources_module`, трассу живого прогона не снимал.

**Транспорт** (`multiprocess_framework/modules/shared_resources_module`)
- `queues/` — очереди `multiprocessing`, по ним идут управляющие и данные-сообщения.
- `memory/` — разделяемая память с seqlock, по ней идут кадры (`shm_frame_reader.py`).
- `events/` — межпроцессные события.

**Сообщения**
- Между процессами передаются только `dict` (правило Dict at Boundary). Pydantic используется лишь внутри процесса.
- `Message` / `MessageAdapter` упаковывает сообщение, `RouterManager` выбирает получателя.
- Адрес бывает двух видов: имя процесса (`targets`, `send_message`) и канал Router (`FieldRouting.channel`). Их не путать.

**Связи в `webcam_sketch`**
- `chain_targets`: `camera_0 → seg → lines → points`; `seg`, `lines` и `points` шлют кадры ещё и в `gui`.
- `wires` соединяют порты плагинов, например `pult.control_panel.out_1 → points.robot_draw.trigger`.
- Кнопки пульта отправляют команды напрямую процессу `devices` (например `robot_set_mode`) или меняют параметры плагинов в `lines` и `points`.
- `displays` задают буфер дисплея на 3 блока (`ring_buffer_blocks`) для `orig`, `lineart` и `points`.

## chain / chain / ход 3 / rep1 / A (378 слов)

Если упал обычный дочерний процесс, `ProcessManagerProcess` замечает это и перезапускает только его (`ProcessMonitor`). Остальные процессы продолжают работать, но конвейер ниже упавшего узла простаивает, пока тот не поднимется.

**1. Обнаружение.** Есть два независимых сигнала:
- **процесс завершился:** `process.is_alive()` ложно. При `exitcode == 0` статус становится `stopped`, при любом другом — `crashed` (ADR в `process_manager_module/DECISIONS.md:24`);
- **процесс завис:** перестали приходить heartbeat, срабатывает `_check_heartbeat_timeout`, событие `unresponsive`.

**2. Автоперезапуск.** Включён по умолчанию для всех процессов, кроме защищённых (ADR о default-on автоперезапуске):
- Если у процесса нет своей `restart_policy`, менеджер строит глобальную `RestartPolicy(enabled=True)`.
- Параметры по умолчанию (`core/restart_policy.py`): `max_retries=3` за `window_sec=60`, пауза `backoff_sec=2.0`, режим `fixed`. Экспоненциальный backoff с jitter включается опционально (ADR-PMM-019).
- Если процесс падает чаще лимита, срабатывает событие `gave_up` со счётчиком, и менеджер прекращает попытки (защита от crash-loop).
- Защищённые процессы (`protected: true`) монитор не перезапускает. В `webcam_sketch` так помечены `gui` и `devices`, их падение не лечится.
- Остальные процессы рецепта (`camera_0`, `seg`, `lines`, `points`, `pult`) перезапускаются. У `camera_0` своя политика с теми же значениями: `{enabled: true, max_retries: 3, window_sec: 60}`.
- Выключить автоперезапуск целиком: `FW_AUTORESTART=0`.

**3. Влияние на соседей.** Стратегия по умолчанию `one_for_one`: перезапускается только упавший процесс. Каскад `rest_for_one` / `one_for_all` включается, если задать процессам общую `supervision_group`. В `webcam_sketch` групп нет, поэтому каскада не будет. Например, при падении `seg` процессы `lines` и `points` живы, но новых кадров не получают, пока `seg` не перезапустится.

**4. Видимость.** Каждый переход публикуется в StateStore по пути `processes.<name>.supervisor.{event,reason,attempt,at}` и дублируется в лог. Последовательность событий: `crashed` / `unresponsive` → `restarting k/N` → `recovered` или `gave_up`. Событие `recovered` фиксируется по первому heartbeat нового экземпляра, а не по смене статуса.

**Что теряется при перезапуске.**
- **In-memory состояние процесса** (модели, калибровка). ADR прямо называет это нерешённым нюансом.
- **Порядок старта по `depends_on`.** Он соблюдается только при загрузке, при перезапуске нет.
- **Сохраняются** runtime-правки телеметрии, адресованные конкретному процессу: менеджер повторно применяет их к новому экземпляру (замер в ADR: pid 36592 → 39268, правка жива).

Что не проверено: что происходит с сообщениями, которые приходят в очередь процесса, пока он лежит (копятся или отбрасываются), и как ведут себя кадры в SHM-слотах, которые держал умерший процесс. Код я не открывал, живьём не запускал. Проверить можно на стенде: `backend_ctl` и SIGKILL, например, `seg`. Готовый живой тест для такого сценария уже есть: `backend_ctl/tests/test_autorestart_all_live.py`.

## chain / chain / ход 3 / rep1 / B (155 слов)

Упавший процесс поднимает `ProcessMonitor` внутри `ProcessManagerProcess`, остальные процессы продолжают работать. Ответ собран по коду и тестам, падение на живом стенде я не воспроизводил.

**Обнаружение:** монитор опрашивает процессы каждые 0,5 с (`monitor_poll_interval`). Процесс без heartbeat 15 с считается зависшим (`heartbeat_timeout`).

**Рестарт (`core/restart_policy.py`):**
- авто-рестарт по умолчанию включён (`FW_AUTORESTART`), выключается через `FW_AUTORESTART=0` или `restart_policy.enabled`;
- поводы для рестарта: падение, зависание и `health failed`;
- пауза 2 с перед попыткой, режим `exponential` поднимает её до 60 с;
- не больше 3 попыток за окно 60 с.

**Give-up:** после 3 неудач процесс получает статус `failed`. В `processes.<name>.health.status` пишется `failed`, событие видно в `supervisor.event`. Новых попыток монитор больше не планирует.

**Очереди:** рестарт переиспользует те же очереди, сообщения в них сохраняются. SHM-регион переживает рестарт (`process_manager_process.py:1096`).

**Исключения:** `gui` и сам PM монитор не перезапускает (комментарий в `process_manager_process.py:169`).

Ручной перезапуск — командой `process.restart`. Статус процессов показывает supervision-снимок: `restart_count`, `last_exit`, `pid`.

## chain / chain / ход 3 / rep2 / A (458 слов)

Соседей падение одного процесса не роняет. Упавший процесс замечает и перезапускает **ProcessMonitor** внутри оркестратора (`process_manager_module/monitor/process_monitor.py`).

**1. Как падение замечают.** Монитор проверяет процессы каждые 0.5 с (`monitor_poll_interval`). Возможны три случая:
- **`crashed`** — процесс завершился с `exitcode != 0` (`process_monitor.py:924`). Выход с кодом 0 считается штатной остановкой (`stopped`), рестарта не будет.
- **`unresponsive`** — процесс жив, но не присылает heartbeat дольше `heartbeat_timeout` (по умолчанию 15 с).
- **`health failed`** — процесс жив, но плагин сам объявил фатальный отказ. Рестарт в этом случае работает только при включённом `FW_HEALTH_RESTART` (по умолчанию выключен).

О падении всегда сообщается громко: supervisor-событие `crashed` попадает в лог, а алерт публикуется в `system.alerts.<процесс>`.

**2. Решение о рестарте (`RestartPolicy`).**
- Авто-рестарт включён для всех процессов по умолчанию через флаг `FW_AUTORESTART`. Выключить его можно `FW_AUTORESTART=0` или полем `restart_policy` в рецепте. В `webcam_sketch` своя политика явно задана только у `camera_0`: `enabled: true, max_retries: 3, window_sec: 60`.
- **Protected-процессы `gui` и сам ProcessManager не перезапускаются никогда.** Их жизненным циклом владеет launcher.
- Рестарт выполняется не сразу, а после паузы `backoff_sec` (2 с, режим fixed или exponential). Публикуется событие `restarting k/N`. Сам перезапуск идёт IPC-командой в PM, чтобы не столкнуться с применением топологии.
- Новый экземпляр процесса получает **те же очереди**. Соседи продолжают писать в них, перепроводка не нужна (`reader_gone.py:19`).
- Восстановление засчитывается по первому heartbeat от нового экземпляра. Если heartbeat не пришёл к дедлайну, watchdog повторяет попытку.

**3. Отказ от рестартов (give-up).** Если в окне 60 с набралось 3 рестарта, монитор ставит процессу статус `failed`. Публикуется `health.status=failed` с причиной и терминальное событие `gave_up`, после чего попытки прекращаются.

**4. Что с соседями.**
- Стратегия по умолчанию — `one_for_one`: перезапускается только упавший процесс. Можно выбрать `rest_for_one` (упавший и всё, что от него зависит через `depends_on`) или `one_for_all` (вся `supervision_group`). Для этих двух у процессов должна быть задана `supervision_group`.
- Пока получатель не работает, писатель продолжает работу. Кадры в SHM-кольце перезаписываются по правилу drop-oldest, очередь `data` ограничена по размеру. Это следует из настроек QoS, отдельно сценарий я не проверял.
- Пример: если упал `seg`, то `camera_0` продолжает снимать, а `lines` и `points` ничего не получают, пока `seg` не вернётся.

**Пробелы в текущей настройке:**
- При `one_for_one` после give-up пайплайн остаётся полумёртвым: один процесс в `failed`, остальные живы, но без входных данных. Эскалация на группу (`_escalate_group_giveup`) срабатывает только при заданной `supervision_group`.
- У политики есть известная ловушка (описана в самом `restart_policy.py:46`): при `exponential` и `backoff_max_sec`, близком к `window_sec / max_retries`, give-up может не наступить никогда. Получится бесконечный медленный цикл падений и рестартов. С дефолтами (60/60/3) этого не происходит.

Всё это я прочитал в коде и падение живьём не воспроизводил. Проверить можно так: запустить стенд с `BACKEND_CTL=1`, убить, например, `seg` по PID и посмотреть через `backend_ctl` события `crashed` → `restarting 1/3` → восстановление. Если нужно, сделаю этот прогон.

## chain / chain / ход 3 / rep2 / B (178 слов)

Если дочерний процесс падает, `ProcessMonitor` в оркестраторе помечает его `crashed`, а остальные процессы продолжают работать. Ниже — разбор `monitor/process_monitor.py:905-967` и `1236-1347`. Живое падение я не воспроизводил.

**Порядок действий**
1. Монитор видит мёртвый процесс. Ненулевой `exitcode` даёт статус `crashed`, код 0 — `stopped`.
2. Публикуется событие `crashed` с `exitcode`.
3. При `FW_SHM_LOAN_PROTOCOL` всем процессам рассылается `shm_reclaim`. Так освобождаются слоты разделяемой памяти, занятые упавшим процессом.
4. Дальше всё решает `RestartPolicy`.

**RestartPolicy** (`core/restart_policy.py`)
- По умолчанию `enabled=False`. Тогда пишется ошибка в лог, процесс остаётся `crashed`, система не останавливается.
- При `enabled=True` рестарт ставится через `backoff_sec` (2 с), режим `fixed` или `exponential`.
- Попытки ограничены: `max_retries` (3) за `window_sec`. Сверх лимита процесс получает `FAILED`, публикуется событие `gave_up`.
- Если процесс проработал без сбоев дольше `window_sec`, счётчик попыток обнуляется.
- Для процессов с `protected` (`gui`, `devices`) авто-рестарт пропускается.
- Стратегия группы может перезапустить соседей. При `one_for_one` соседей не трогают.

**В `webcam_sketch`** политика включена только у `camera_0`: `{enabled: true, max_retries: 3, window_sec: 60}`. Если упадёт `seg`, `lines` или `points`, без `FW_AUTORESTART` они останутся `crashed`. Тракт после упавшего узла тогда перестанет получать данные.

## chain / chain / ход 4 / rep1 / A (406 слов)

У конфига процесса нет отдельного файла: он собирается из YAML при старте. Внутрь процесса он попадает один раз, как обычный `dict`, в аргументах `multiprocessing.Process` при spawn.

**Откуда собирается**

| Источник | Что даёт |
|---|---|
| `app.yaml` (манифест) | какие файлы читать: `system`, `base`, `pipeline` |
| `backend/config/system.yaml` | системные настройки и дефолты плагинов |
| `backend/topology/base.yaml` | фундамент: always-on процессы (`devices`) |
| `recipes/webcam_sketch.yaml` → `blueprint.processes[]` | **основной источник**: на каждый процесс `process_class`, `plugins[]` с их `config:`, `chain_targets`, `restart_policy`, `protected` и т.д. |
| presentation-overlay (если задан) | патч поверх процесса `gui` |

**Как доезжает до процесса**

1. **Склейка.** `SystemBuilder.from_manifest` (`backend/launch.py`) читает рецепт и разворачивает `blueprint:` в топологию (`unwrap_recipe`). Затем он склеивает её с фундаментом (`merge_topologies`, при дубле имени побеждает фундамент) и накладывает overlay.
2. **Валидация и плоские словари.** Топология проходит `SystemBlueprint.model_validate` (Pydantic, `process_manager_module/topology/blueprint.py`). На каждый процесс строится плоский `proc_dict`, плагины кладутся в `proc_dict["config"]["plugins"]` (`generic_process_config.py:299`).
3. **Передача в `ProcessManagerProcess`.** `SystemLauncher.add_process(name, proc_dict)` (`system_launcher.py:323`) передаёт словари менеджеру.
4. **Spawn** (`process_registry.py:147-265`, `_create_process`):
   - копия конфига дополняется ключами `name` и `class` и регистрируется в `ConfigManager` менеджера под секцией `processes`;
   - для процесса создаются его очереди;
   - собирается **bundle** (`build_bundle`): конфиг, очереди этого процесса, `routing_map` (очереди всех процессов, чтобы слать соседям), описания SHM-сегментов всех процессов (`_all_process_memory`), `routing_meta` и `ready_event`;
   - запускается `Process(target=run_process_function, args=(class_path, name, stop_event, bundle, system_stop_event))`. На Windows это spawn, поэтому всё в bundle должно пиклиться. Сырые `Event` из `custom` намеренно вырезаются и передаются отдельными аргументами.
5. **Внутри процесса.** `ProcessModule` достаёт конфиг через `get_config("config")`. Если там есть `plugins`, создаётся `PluginOrchestrator`, и плагины проходят цикл `load → configure → start` (`process_module.py:785-805`). Каждый плагин получает свой блок `config:` из рецепта. Воркеры поднимаются из `config["workers"]`. Это граница «dict снаружи — Pydantic внутри».

**Изменения конфига на лету**

- **Без перезапуска** через IPC-команды процессу меняются только отдельные срезы: `config.reload` и `telemetry.reconfigure` (наблюдаемость и телеметрия), `worker.update`, `wire.configure` (`builtin_commands.py`). Плюс `update_config(key, value)` внутри процесса.
- **Смена топологии или рецепта** (hot-apply, переключение во вкладке Recipes) приводит к респавну процесса со свежим bundle. Тот же путь проходит перезапуск после краша, поэтому упавший процесс снова получает исходный конфиг из рецепта.

**Что не проверено:** каким путём GUI меняет параметры конкретного плагина на лету (ползунки и т. п.): через `register_update` по каналу Router, через подписку на StateStore или через респавн. Команду вида `plugin.set_param` в `builtin_commands.py` я не нашёл. Если нужно, следующий шаг — `/analysis:channel-map` или чтение `PluginRunner` / `ProcessIO`.

## chain / chain / ход 4 / rep1 / B (153 слов)

Конфиг процесса хранится в YAML-файлах на диске. Внутрь процесса он попадает словарём в `bundle`, который передаётся аргументом при spawn. Ответ собран по коду, на живом стенде я его не проверял.

**Источники (склеивает `backend/launch.py`):**
1. `backend/config/system.yaml` — системные настройки и defaults плагинов.
2. `backend/topology/base.yaml` — фундамент.
3. `frontend/presentation.yaml` — `gui`.
4. Рецепт из `pipeline:` в `app.yaml`: его запись `processes:` даёт `process_name`, `chain_targets`, `plugins`.

**Доставка:**
1. `SystemLauncher` кладёт `processes_config` в bundle и передаёт его `ProcessManagerProcess` (`launcher/spawner.py:116`).
2. Для каждого дочернего процесса PM вызывает `ProcessRegistry`. Тот записывает конфиг в `ConfigManager` и собирает `build_bundle(queues, config, custom, routing_map)` (`core/process_registry.py:235`).
3. Bundle уходит аргументом `Process(...)`, на Windows это spawn-pickle.

**Внутри процесса:**
- значения читаются через `get_config(key)`, ключи поддерживают точечную нотацию (`process_config_handler.py:163`);
- порядок поиска: `ProcessConfiguration` → `ConfigManager` → локальный конфиг;
- типизированная схема — `GenericProcessConfig` (Pydantic). Где именно dict проходит через неё, я не проверял.

## chain / chain / ход 4 / rep2 / A (503 слов)

Конфиг процесса хранится в YAML-файлах. В процесс он попадает при старте одним `dict`, а не через общий объект: оркестратор передаёт его аргументом при spawn.

## Где хранится

| Слой | Файл | Что там |
|---|---|---|
| Манифест | `multiprocess_prototype/app.yaml` | какие фрагменты фундамента и какой рецепт собирать |
| L1, система | `system.yaml` (путь задаёт манифест) | общие настройки, в том числе observability |
| Фундамент | `backend/topology/base.yaml` | always-on процессы (`devices`) |
| **Рецепт** | `recipes/webcam_sketch.yaml` → `blueprint.processes[]` | **основной конфиг процесса** |
| Спутник рецепта | файл рядом с рецептом (`observability_companion`) | сохранённые настройки наблюдаемости |

Запись процесса в рецепте выглядит так (`webcam_sketch.yaml:89`):

```yaml
- process_name: camera_0
  process_class: multiprocess_prototype.generic_process_app.GenericProcessApp
  plugins:
    - plugin_name: capture
      plugin_class: Plugins.sources.capture.plugin.CapturePlugin
      config: {camera_id: 0, resolution_width: 640, fps: 30, ...}   # параметры плагина
  chain_targets: [seg]
  restart_policy: {enabled: true, max_retries: 3, window_sec: 60}
  metadata: {source_target_fps: 25}
```

## Как попадает внутрь процесса

1. **Сборка (главный процесс).** `SystemBuilder` склеивает фундамент, рецепт и overlay GUI через `merge_topologies`. Затем `BlueprintAssembler.assemble()` (`backend/assembly/assembler.py:90`) делает следующее:
   - валидирует топологию как Pydantic-модель `SystemBlueprint` (`check()`, при ошибке `sys.exit(1)`);
   - строит `GenericProcessConfig` на каждый процесс (`build_configs()`) и выводит из топологии бюджет кадров «в полёте»;
   - накладывает слои observability (L1 из `system.yaml`, затем L2 из рецепта), подставляет `telemetry` и `log_dir`;
   - дополняет результат дефолтами (`merge_with_defaults`) и отдаёт `{process_name: proc_dict}`, то есть уже обычные `dict`.
2. **Передача оркестратору.** `SystemLauncher.add_process(...)` собирает все `proc_dict` в `processes_config`. Spawner кладёт их в bundle процесса ProcessManager (`launcher/spawner.py:97`).
3. **Spawn ребёнка (в PM).** `ProcessRegistry` собирает на каждого ребёнка bundle (`core/bundle_contract.py:19`):
   ```
   {queues, config, custom, routing_map, routing_meta}
   ```
   и запускает `Process(target=run_process_function, args=(class_path, name, stop_event, bundle, ...))`. Bundle едет аргументом процесса (pickle при spawn). Поэтому очереди, события и метаданные SHM соседей приходят вместе с конфигом без отдельной проводки.
4. **Внутри ребёнка.** `run_process_function` поднимает из bundle локальный `SharedResourcesManager` и создаёт экземпляр класса по `class_path`. Конфиг читает `ProcessConfigHandler` (`process_module/configs/process_config_handler.py`):
   - `self.get_config("a.b")` ищет по точечному пути: сначала в данных из bundle, потом в локальном ConfigManager;
   - менеджеры (логгер, роутер и др.) получают свои секции через `get_manager_config(name)`;
   - плагины получают свой `config:` через `PluginContext`. В Pydantic значения превращаются уже внутри процесса (правило «dict на границе, Pydantic внутри»).

## Изменение на лету

Параметры работающего процесса меняются сообщением `register_update` с полями `{register, field, value}`. Его шлёт GUI или другой процесс. В процессе его обрабатывает `PluginOrchestrator._on_register_update` (`generic/plugin_orchestrator.py:422`): значение валидируется и записывается в регистр плагина через `RegistersManager.set_field_value`, отправителю возвращается `success`/`error`.

Такое изменение живёт только в памяти процесса. Чтобы оно пережило перезапуск, GUI должен сохранить рецепт в файл. Смена топологии (состав процессов, связи) идёт через рецепт и оркестратор (`apply_topology`), а не через `register_update`.

Чего я не проверил:
- **После авто-рестарта** процесс, по всей видимости, стартует с конфигом из bundle, с которым его запускали, а не с последними значениями `register_update`. Если так, правки из GUI без сохранения рецепта при рестарте теряются. Ответ на это лежит в `restart_process`, этот путь я не читал.
- Как именно `GenericProcessApp` раскладывает `plugins[].config` по плагинам, я тоже не открывал, поэтому шаг про `PluginContext` описан по контракту, а не по коду.

Если нужно, проверю оба места.

## chain / chain / ход 4 / rep2 / B (175 слов)

Конфиг процесса лежит в YAML рецепта и через `pickle` передаётся аргументом `multiprocessing.Process`. Ниже — разбор `process_registry.py` и `process_runner.py`. Живой прогон я не делал.

**Где хранится**
- Описание процесса — в `blueprint.processes[]` рецепта, например `recipes/webcam_sketch.yaml`.
- Фундамент — в `backend/topology/base.yaml`.
- Системные настройки и defaults плагинов — в `backend/config/system.yaml`.

**Как попадает внутрь**
1. `SystemBuilder` склеивает `base` с рецептом. Схема записи процесса — `ProcessConfig` (`topology/blueprint.py:73`).
2. До процесса доходят только ключи, которые явно выбирает `ProcessConfig._from_recipe`. Ключ в `metadata` теряется молча, нужен `extras` (проверено 2026-08-12, по комментарию в рецепте). Сам `_from_recipe` я не открывал.
3. Оркестратор собирает словарь `build_bundle(queues, config, custom, routing_map, routing_meta)` (`process_registry.py:235`).
4. `Process(target=run_process_function, args=(class_path, name, stop_event, bundle, ...))`. Словарь сериализуется через `pickle`.
5. Дочерний процесс восстанавливает `SharedResourcesManager` из bundle. `process_config` он берёт из `config.process` или `custom["process_config"]` (`process_runner.py:338-343`).
6. Вызывается `process_class(name=..., shared_resources=..., config=process_config)`, затем `initialize()`. Внутри процесса словарь разбирается в Pydantic.

**На ходу:** контролы пульта с `source: param` меняют поля плагинов в работающем процессе.

## chain / chain / ход 5 / rep1 / A (406 слов)

GUI узнаёт об изменениях push-уведомлениями: бэкенд сам присылает изменения, GUI ничего не опрашивает. Основной канал — дельты StateStore, плюс два отдельных канала для логов и ответов на команды. Всё подключается в `multiprocess_prototype/frontend/process.py:61-160`.

**1. Дельты StateStore (основной путь)**

Цепочка от бэкенда до виджета:

1. **Публикация.** Процессы бэкенда пишут в общее дерево состояния, сервер которого живёт в `ProcessManagerProcess`:
   - `ProcessMonitor` → `processes.X.state.*`, `processes.X.workers.Y.*`, события `processes.X.supervisor.*`;
   - сводное здоровье → `system.health.*`;
   - `DeviceHubPlugin` → `devices.registry.*`, `devices.state.*`;
   - плагин калибровки → `calibration.state.<camera_id>.progress`.
2. **Рассылка.** `DeltaDispatcher` отправляет сообщение `state.changed` только тем, кто подписан на подходящий glob-шаблон.
3. **Подписка GUI.** При старте GUI создаёт `GuiStateProxy` и подписывается на четыре шаблона: `processes.**`, `system.**`, `devices.**`, `calibration.**` (`process.py:128-145`). При подписке приходит начальный снимок (`_replay_initial_state`), поэтому, например, список устройств заполняется сразу.
4. **Приём.** Обработчик `state.changed` зарегистрирован в роутере GUI (`process.py:89`) и срабатывает в IO-потоке.
5. **Переход в Qt-поток.** Через `delta_sink` дельты попадают в `bridge.dispatch`. Это тот же мост, по которому идут кадры: `_deliver.emit` с AutoConnection переносит вызов в главный поток Qt.
6. **Виджеты.** `GuiStateBindings` обновляют виджеты.

Главная ловушка: данные, на которые GUI не подписан, до него не доходят, даже если бэкенд их публикует. Поэтому новый раздел дерева требует новой строки `subscribe(...)`. Комментарии в коде описывают живые случаи: пустой список устройств и «зависшая» калибровка.

**2. Отдельные каналы, не через дельты**
- **`observability.record`.** Бэкенд пушит записи логов, ошибок и статистики прямо в `gui` через системную очередь. Это живой хвост для вкладок «Логи», «Ошибки», «Статистика» (`process.py:94`).
- **`process.command.response`.** Ответы менеджера процессов на системные команды GUI. GUI отправляет команды без ожидания ответа, а этот обработчик нужен, чтобы отказ бэкенда не пропадал бесследно (`process.py:100`).

**3. Кадры** идут своим путём: SHM-каналы дисплеев и поток `data_receiver`. Это данные, а не состояние, но в Qt-поток они переходят через тот же мост.

**Известное ограничение.** Подписки оформляются с `sync=False`, без подтверждения: на этом шаге инициализации поток-приёмник ещё не запущен. Поэтому сервер подписку, скорее всего, получает, но GUI-прокси не знает, подтверждена ли она, и проверка покрытия шаблонов (`_find_covering_pattern`) для GUI ничего не находит. Комментарий в коде называет это осознанной ценой, отложенной на потом.

Что не проверено:
- `GuiStateBindings` и сам мост я не открывал, их поведение взято из комментариев в `process.py`.
- Всё это работает только в настоящем Qt-GUI (`frontend/process.py`). Подписывается ли на что-то `HeadlessGuiProcess`, который запускается без presentation, я не смотрел.

## chain / chain / ход 5 / rep1 / B (162 слов)

GUI узнаёт о смене состояния по push-подписке на общее дерево состояния, которое живёт в `ProcessManager`. Ответ собран по коду и README, на живом стенде я его не проверял.

**Сервер (PM):** `StateStoreManager` хранит дерево `TreeStore`. Бэкенд пишет в него через `state.set` и `state.merge`. Пример из прошлого ответа: монитор пишет `processes.<name>.health.status`.

**Подписка:** GUI отправляет `state.subscribe` с glob-шаблоном, например `processes.*.health.*`.

**Доставка:**
1. Дельты копятся по подписчику и уходят одним сообщением `state.changed` примерно раз в 120 мс через очередь `state`.
2. В GUI-процессе их принимает `GuiStateProxy.on_state_changed()` в IO-потоке. Прокси обновляет кэш и вызывает `delta_sink`.
3. `delta_sink` передаёт дельты в Qt main thread через `DataReceiverBridge`, как и кадры.

**Пропуски:** у каждой дельты есть номер `revision`. Если номер перескочил, прокси сам запрашивает свежий снимок через `state.get_subtree`.

**Исключение — телеметрия:** `telemetry_poller.py` опрашивает `introspect.telemetry` по `QTimer`, только пока вкладка видна.

Для GUI в отдельном процессе есть `RemoteStateProxy`, подключение через `SocketChannel`. Эту ветку я не разбирал.

## chain / chain / ход 5 / rep2 / A (454 слов)

GUI ничего не опрашивает: бэкенд сам присылает ему изменения. Основной путь — общее дерево состояния (`state_store_module`), куда пишут все процессы. GUI подписан на нужные ветки и получает только изменения (дельты).

## Схема

```
процесс X / ProcessMonitor
   │  StateProxy.set("processes.seg.health.status", "failed")
   ▼
StateStoreManager (в ProcessManager): TreeStore + SubscriptionManager
   │  совпадение с glob-подпиской GUI → дельта копится per-subscriber
   │  flusher ~120 мс → один конверт state.changed {deltas, revision}
   ▼  очередь gui_state (drop_oldest)
GuiProcess, IO-поток (message_processor)
   │  router → GuiStateProxy.on_state_changed → delta_sink
   ▼  DataReceiverBridge.dispatch (Qt queued connection)
Qt main thread → GuiStateBindings → setter виджета
```

## По шагам

1. **Кто пишет.** Дерево хранит `StateStoreManager` в процессе ProcessManager. Рабочие процессы пишут в него через свой `StateProxy` (`set`/`merge`). ProcessMonitor тоже пишет: статусы, `health.*`, supervisor-события, `system.alerts.*`.
2. **На что подписан GUI.** При старте `GuiProcess` подписывается на ветки `processes.**`, `system.**`, `devices.**`, `calibration.**` (`frontend/process.py:128–145`). Сами callback'и там пустые: подписка нужна, чтобы сервер вообще включил GUI в число адресатов. Без подписки дельты в GUI не приходят. В коде есть комментарий об уже случавшемся баге: `devices.*` не доходили до GUI именно из-за отсутствия подписки.
3. **Доставка.** Дельты уходят не по одной. Они копятся и раз в ~120 мс отправляются одним конвертом `state.changed` через очередь класса `state` (ADR-SS-020). Эта очередь отделена от управляющей `system` и при переполнении теряет самые старые сообщения.
4. **Переход из IO-потока в Qt.** Конверт принимает IO-поток процесса. Каждая дельта превращается в сообщение `state_delta` (`value`/`deleted`/`old_value`/`source`) и через `DataReceiverBridge` передаётся в main thread Qt. Тем же мостом идут кадры, так что виджеты из чужого потока никто не трогает.
5. **Виджеты.** `GuiStateBindings` (`frontend/state/bindings.py`) хранит пары «glob-путь → setter виджета». Виджеты хранятся через weakref и отписываются сами при `destroyed`. Вкладки (Processes, Pipeline, Services, Displays) подписываются через свои presenter'ы.

## Если GUI что-то пропустил

В каждом конверте есть монотонный `revision` дерева. Если клиент видит пропуск (например, очередь `state` выбросила старые сообщения), он запрашивает полный снимок нужных веток через `state.get_subtree(paths=[...])` (watch-from-revision + resync, ADR-SS-014/015). Новые виджеты сначала получают текущее значение из снимка read-model и только потом живые дельты.

## Другие каналы в GUI, помимо дерева

- **Кадры для дисплеев.** Это не state: кадры приходят через SHM-кольцо с извещением, а в виджет попадают через тот же bridge.
- **Логи и телеметрия.** Сообщения `observability.record` приходят напрямую в `gui` очередью `system` (комментарий в `process.py:91`).
- **Ответы на команды GUI.** На `register_update` с `request_id` отправитель получает автоматический reply с `success`/`error`.

Я описал механизм по коду и README `state_store_module` и задержку живьём не мерил. Реальное время от записи в бэкенде до обновления виджета можно снять на стенде через `backend_ctl`: процесс выставляет значение, а мы засекаем, когда придёт `state.changed`. В эту цифру войдут ~120 мс flusher'а и переход в Qt.

## chain / chain / ход 5 / rep2 / B (151 слов)

GUI подписан на дерево состояния в оркестраторе (`ProcessManager`) и получает от него дельты сообщением `state.changed`. Ниже — разбор `frontend/process.py:77-145` и `frontend/bridge_impl.py:81-119`. Живой трассы я не снимал.

**Путь дельты**
1. Бэкенд пишет в дерево `state_store_module`. Например, монитор публикует `processes.<имя>.health.status`.
2. `DeltaDispatcher` в оркестраторе рассылает дельты только подписчикам.
3. GUI подписан через `GuiStateProxy` на четыре шаблона: `processes.**`, `system.**`, `devices.**`, `calibration.**`. Подписки идут с `sync=False` и остаются неподтверждёнными (`_confirmed_patterns`).
4. Обработчик `state.changed` принимает дельту и передаёт её в мост.
5. `bridge_impl.dispatch` переводит её из рабочего потока в главный поток Qt через сигнал.
6. В главном потоке вызываются слушатели и испускается `state_updated`. Виджеты обновляются.

**Отдельные каналы**
- `observability.record` — живые логи, ошибки и статистика. Это не дельта состояния.
- `process.command.response` — ответы оркестратора на команды GUI.
- Кадры приходят как `frame`, сигнал `frame_received`.

Дельта по пути вне четырёх шаблонов до GUI не дойдёт.

## chain / chain / ход 6 / rep1 / A (426 слов)

Я бы начал с вопроса, где именно зависло: в GUI, в конвейере или в `ProcessManagerProcess`. Для этого нужен `backend_ctl` (`BACKEND_CTL=1`): он ходит теми же сообщениями роутера, что и GUI, но в обход Qt. Если `backend_ctl` получает ответы и видит свежие heartbeat, бэкенд жив, и проблема в GUI. Дальше три места по порядку.

**1. SHM-слоты кадров и возврат `shm_release`**
- **Почему подозреваю.** Кадры передаются через кольцо SHM-слотов. Отправитель получает слот обратно только после `shm_release` от получателя (`pipeline_executor.py:448`). Если получатель упал, завис или его `shm_release` ушёл не в ту очередь, кольцо заполняется, и источник встаёт. В коде прямо сказано, что без `queue_type="system"` это сообщение терялось (ревью-фикс 16).
- **Симптом.** Процессы живы, heartbeat идут, но кадры на дисплеях замерли, а счётчик `stale_drops` растёт.
- **Как проверить.** Метрики `transport_ms` и `stale_drops` по узлам конвейера, а также frame-trace (`FW_FRAME_TRACE`): на каком узле кадры перестают приходить.

**2. Блокирующий `RouterManager.request` в потоке, который сам должен принять ответ**
- **Почему подозреваю.** Это живой класс дефекта, а не гипотеза. GUI уже ловил его на подписках с `sync=True`: главный поток ждал ответа, который некому было принять. Сейчас это гасит пятисекундный грейс `_NO_PUMP_GRACE_SEC` (`router_manager.py:974`). Тот же рисунок возможен в любом процессе, если обработчик сообщения делает синхронный `request`.
- **Симптом.** Процесс не отвечает на команды, а менеджер процессов шлёт события `unresponsive`, затем `restarting` и `gave_up`.
- **Как проверить.** Посмотреть события `processes.*.supervisor.event` в StateStore и предупреждения роутера «приёмный цикл ещё не запускался» в логах. Затем снять стеки зависшего процесса (`py-spy dump --pid`) и найти, на чём стоят потоки.

**3. `ProcessManagerProcess` как узкое место**
- **Почему подозреваю.** В одном процессе собраны сервер StateStore, `DeltaDispatcher`, `ProcessMonitor` и авторестарт. Если он перегружен (поток дельт телеметрии, повторные применения правок при респавне) или заблокирован, то разом пропадает всё: GUI перестаёт получать дельты, мёртвые процессы не перезапускаются. Конвейер при этом может продолжать работать.
- **Отягчающее.** Подписки GUI оформляются без подтверждения (`sync=False`). Если подписка не дошла, GUI молча ничего не получает, и снаружи это неотличимо от зависания.
- **Как проверить.** Отвечает ли менеджер процессов на `state.get` через `backend_ctl` и за сколько. Есть ли GUI в списке подписчиков (`subscribers_snapshot()` / `StateInspector.subscriptions()`).

Если все три места чистые, бэкенд жив, и зависание в Qt: заблокирован главный поток GUI, тогда `py-spy dump` по процессу `gui`.

Оговорка: эти три места я выбрал по коду и ADR, которые прочитал в этой сессии, и ни одно не воспроизвёл на стенде. Ни один сценарий зависания здесь не проверен. Не смотрел я и то, ограничены ли очереди роутера по размеру. Если ограничены, переполненная очередь тоже может блокировать отправителя, и это стоит проверить параллельно с пунктом 1.

## chain / chain / ход 6 / rep1 / B (150 слов)

Я бы начал с трёх мест, где ожидание не ограничено сроком или где один поток обслуживает всех. Это гипотезы по прочитанному коду, на стенде я их не воспроизводил.

**1. Выход писателя в `ReaderGoneQueue` (`queues/core/reader_gone.py`).**
По докстрингу, писатель на выходе ждёт без таймера: пока очередь не опустеет или не появится метка. Если читателя убили и PM метку не взвёл, процесс висит на стопе.
Проверка: висит ли только остановка и какие процессы живы после `system_stop_event`.

**2. Переполненная очередь `system` получателя.**
Сообщения `system` при переполнении не вытесняются (`system_evict_blocked`). Отправитель с полным буфером `AsyncSender` (512) перестаёт доставлять.
Проверка: счётчики `put`/`lost` по каждой очереди `{process}_{queue_type}`.

**3. Приёмный поток PM.**
В PM работают `StateStoreManager`, `ProcessMonitor` и рассылка `state.changed`. Если этот поток стоит, у GUI замирает состояние, а монитор не видит смертей.
Проверка: обновляются ли `revision` и supervision-снимок.

Начинать с `backend_ctl`: ответил ли PM, затем стеки потоков нужного PID.

## chain / chain / ход 6 / rep2 / A (443 слов)

Первыми я бы проверил три места. Все три выбраны потому, что там зависание выглядит как «всё живое, но ничего не происходит», а супервизор его не ловит.

## 1. Рабочий поток процесса застрял, а heartbeat продолжает идти

**Почему первым.** Heartbeat шлёт отдельный системный поток (`process_heartbeat.py:159`, `WorkerType.SYSTEM`). Если плагин завис в `process()` (ждёт камеру, держит блокировку, долго считает на GPU), монитор продолжает получать heartbeat. Тогда не срабатывает ни `unresponsive`, ни рестарт. Процесс «жив», а соседи ниже по цепочке сидят без данных. Пример для `webcam_sketch`: `lines` (TEED) встал, значит `points` молчит.

**Как проверить.** Сравнить по процессам, что heartbeat свежий, а счётчики прогресса стоят: fps и обработанные кадры в `processes.<имя>.*` через `backend_ctl`. Найти первый процесс в цепочке, у которого прогресс равен нулю. Затем `py-spy dump --pid <PID>` на нём, чтобы увидеть, где стоит поток.

## 2. Поток обработки сообщений в ProcessManager

**Почему.** Это узкое горло всей системы: через PM идут дерево состояния, команды супервизора и рестарты. Рестарты специально сериализованы с `apply_topology` на этом потоке (`process_monitor.py:1306`). Если он застрял (долгий switch рецепта, синхронный запрос, исключение в обработчике), картина такая:
- GUI перестаёт получать `state.changed`, и окно выглядит замёрзшим, хотя Qt отзывчив;
- упавшие процессы не перезапускаются;
- после паузы возможна волна ложных `unresponsive`: монитор их ловит, но рестарт не исполняется.

**Как проверить.** Растёт ли `revision` в приходящих в GUI конвертах? Отвечает ли PM на простой запрос через `backend_ctl`? Если не отвечает — `py-spy dump` по PID оркестратора.

## 3. Main thread Qt в GUI

**Почему.** `gui` — protected-процесс, монитор его **никогда не перезапускает** (`process_monitor.py:1243`). Если слот виджета или presenter делает долгую работу в main thread, окно замирает, а бэкенд при этом работает нормально. Очередь `state` теряет старое, так что бэкенд не тормозит. Но по ощущениям оператора «зависла система».

**Как проверить.** Бэкенд жив, если `backend_ctl` видит прогресс процессов. Тогда `py-spy dump` по PID GUI и смотреть стек main thread.

## Отдельный случай — зависание на остановке

Если система висит именно на закрытии, первым смотреть `ReaderGoneQueue` (`reader_gone.py`). Писатель на выходе ждёт, пока сольётся буфер очереди, **без таймаута**, пока не появится метка «читатель ушёл». Метку ставит PM после подтверждённой смерти ребёнка. Если этот путь не отработал (например, ребёнка убили мимо `stop_one`/`stop_many`), писатель будет ждать вечно.

## Что я сознательно не поставил в тройку

Ожидание готовности системы перед первым кадром (preroll) я сначала подозревал, но проверил: там есть срок 10 с, после него WARNING и старт (`process_manager_module/DECISIONS.md:1615`). Вечно оно не висит.

Это рейтинг по чтению кода, а не по живым инцидентам. Если зависание у вас уже воспроизводится, удобнее всего начать с одного прохода `py-spy dump` по всем PID из pid-реестра. Он сразу покажет, какой из трёх случаев ваш, и могу сделать этот прогон.

## chain / chain / ход 6 / rep2 / B (149 слов)

Я бы начал с трёх мест, где цепочка блокируется по коду. Это гипотезы по прочитанному коду, ни одно зависание я не воспроизводил.

**1. Главный поток GUI**
- `RouterManager.request` с `sync=True` ждёт ответа на главном потоке. Без приёмного цикла это 0,5 с на каждый вызов (`process.py:103-116`).
- Медленный слушатель в `bridge_impl._on_deliver` останавливает весь Qt.
- Проверка: стек главного потока через `py-spy dump --pid <gui>`.

**2. Очереди медленного узла `lines`**
- TEED на этой машине выдаёт ~3,3 к/с, источник даёт 21 к/с.
- При `chain_max_lag_items: 0` действует режим «копим и блокируем». Пробка тогда идёт назад к `camera_0`.
- Проверка: глубина очередей и fps по процессам через `backend_ctl`.

**3. Слоты разделяемой памяти после смерти читателя**
- `shm_reclaim` рассылается только при `FW_SHM_LOAN_PROTOCOL` (`process_monitor.py:985`).
- Без флага мёртвый читатель держит слоты, пока список свободных не опустеет. Тогда писатель встаёт.
- Проверка: статусы `crashed` в `processes.**` и счётчики свободных слотов пула.

## chain / chain / ход 7 / rep1 / A (356 слов)

## Самый рискованный: `process_manager_module`, процесс `ProcessManagerProcess`

**Почему.** Он стоит во всех цепочках, которые мы разобрали, и при этом сам ничем не застрахован.

1. **Единая точка отказа без страховки.** В одном процессе собраны:
   - запуск всех дочерних процессов и сборка их bundle с конфигом, очередями, `routing_map` и SHM;
   - сервер StateStore и `DeltaDispatcher` — единственный путь, по которому GUI узнаёт о состоянии;
   - `ProcessMonitor` — обнаружение падений, автоперезапуск, give-up.

   Сам он помечен как защищённый процесс, и монитор его не перезапускает. Если он упадёт или зависнет, система теряет не одну функцию, а сразу обнаружение падений, восстановление и видимость состояния для GUI. Снаружи это выглядит как «всё застыло». У всех остальных процессов страховка есть.

2. **Размер и плотность решений.** В `process/process_manager_process.py` больше 3600 строк: я видел строку 3606, полный объём не считал. В `DECISIONS.md` модуля больше 1200 строк ADR, и многие из них описывают тонкие границы: какой ключ в каком пути учитывается, что переживает респавн, что инертно при горячей смене топологии. Например, `depends_on` действует только при загрузке. Каждая такая граница — место для регрессии при следующей правке.

3. **Самые сложные виды конкурентности.** Spawn на Windows со строгими правилами пиклинга, когда `Event` нельзя класть в bundle. Гонки «преемник с тем же именем, пока мёртвый ещё в реестре». Доставка правок телеметрии в процесс, который пересоздаётся. Это ровно те классы дефектов, которые плохо ловятся юнит-тестами: race-условия, повторный вход в код, порядок событий.

**Второй кандидат — `router_module` вместе с `FrameShmMiddleware`.** Через него идёт весь транспорт, а возврат SHM-слотов зависит от того, что `shm_release` дошёл по нужной очереди. Но его сбой обычно локален: стоит один участок конвейера. Сбой менеджера процессов глобален.

**Что не проверено.** Вывод сделан по коду и ADR, прочитанным в этой сессии, без измерений. Я не смотрел покрытие тестами и связность модулей, не считал полный объём файлов. Проверить вывод можно так:
- `/sentrux-gaps` — где нет тестов;
- `/sentrux-dsm` и `god_nodes` в graphify — насколько модуль центральный по графу зависимостей;
- живой тест с убийством `ProcessManagerProcess` через `backend_ctl` — что на самом деле видит GUI и что происходит с детьми. Внутри процессов есть сторож смерти родителя (ADR-PMM-032), но его поведение я не проверял.

Если замеры укажут на другой модуль, верить замерам, а не этой оценке.

## chain / chain / ход 7 / rep1 / B (145 слов)

Самый рискованный, на мой взгляд, `process_manager_module`, точнее `ProcessManagerProcess`. Это вывод по прочитанным фрагментам: метрики sentrux я не снимал.

**Почему:**
1. **Он один на систему.** Через него идут запуск процессов, доставка конфигов, создание очередей и `routing_map`.
2. **В одном процессе собраны четыре роли.** Это `ProcessMonitor`, сервер `StateStoreManager`, рассылка `state.changed` и команды `process.restart`.
3. **Его никто не перезапускает.** Монитор работает внутри PM и сам себя не поднимает (`process_manager_process.py:169`).
4. **Его отказ не виден снаружи.** GUI получает состояние только от PM. Если PM повиснет, на экране останется последнее состояние без признака сбоя.
5. **Файл большой.** В `process_manager_process.py` есть строки дальше 3600-й.

**Чего я не знаю:**
- что делают дочерние процессы, если PM умер;
- есть ли у PM внешний watchdog в `SystemLauncher` или в `spawner.py`.

Второй кандидат — `shared_resources_module/queues`. У писателя там ожидание без таймера, а очереди `system` не вытесняют сообщения при переполнении.

## chain / chain / ход 7 / rep2 / A (319 слов)

Самый рискованный модуль — **`process_manager_module`**, а внутри него `ProcessMonitor`. Вывод сделан по прочитанному за эту сессию, а не по метрикам.

## Почему

**1. Он единственный, кто держит систему, и подменить его некому.**
В процессе ProcessManager живут сразу четыре роли: запуск детей, супервизор с рестартами, применение топологии при смене рецепта и, судя по коду, сервер дерева состояния. Дети не переживают смерть PM, у них есть сторож родителя (ADR-PMM-032). Падение любого другого процесса система переживает, а падение или зависание PM — нет. Все три места из прошлого ответа, кроме GUI, сходятся именно сюда.

**2. Сложная логика восстановления.**
`process_monitor.py` больше 1500 строк. В нём несколько взаимодействующих состояний: `_pending_restarts`, `_pending_recovery`, `_recovery_deadline`, `_given_up`, `_induced_restarts`, история рестартов в окне, каскад по стратегиям и watchdog повторных попыток. Комментарии в коде помнят прошлые баги на стыках этих состояний: ложный `recovered`, пинг-понг каскада, шторм рестартов. Такой код ломается на редких порядках событий, а их тестами покрыть труднее всего.

**3. Есть известные открытые дыры.**
- `exponential` backoff может сделать так, что give-up никогда не наступит: получится бесконечный медленный цикл падений и рестартов. Это признано в самом `restart_policy.py:46`, полное решение отложено (NEW-6b).
- При `one_for_one` после give-up пайплайн тихо остаётся полумёртвым, если не задана `supervision_group`.
- Процесс с зависшим рабочим потоком, но живым heartbeat супервизор не видит: монитор проверяет «жив ли», а не «работает ли».

## Второе место — `shared_resources_module`

Через него идут все очереди и SHM. Его отказы обычно не громкие, а тихие: зависание на выходе без таймаута (`ReaderGoneQueue`), потеря сообщений по QoS, порча кадра, если отпустить очередь посреди записи. Он проще PM по логике, но ошибка здесь задевает всех сразу.

## Насколько это надёжно

Это оценка по чтению кода. Метрики и история дефектов её не подтверждают: sentrux (связность, god-nodes), частоту правок по `git log` и `test_gaps` я не запускал. Если подтвердить, первым шагом был бы `/sentrux-health` и подсчёт правок `process_manager_module` против остальных модулей за последние месяцы. Если цифры не совпадут с этим выводом, верить надо цифрам.

## chain / chain / ход 7 / rep2 / B (125 слов)

Самым рискованным я считаю `process_manager_module`, то есть оркестратор. Вывод сделан по чтению 6 файлов, без метрик sentrux и без живого прогона.

**Почему он**
- Через один процесс проходят 4 функции: запуск детей, передача конфигов, надзор и рестарты, раздача дельт состояния.
- GUI подписан именно на него (`server_target="ProcessManager"`). Если оркестратор завис, GUI перестаёт получать `state.changed` и ответы на команды.
- Рестарты выполняются IPC-командой на его же потоке `message_processor`. Если он занят, рестарт не произойдёт.
- Политика рестарта по умолчанию выключена (`enabled=False`). Процессы с `protected` не перезапускаются совсем.
- Только монитор шлёт `shm_reclaim`, и только при `FW_SHM_LOAN_PROTOCOL`.

**Второй кандидат** — `shared_resources_module`. В нём очереди и пул разделяемой памяти, а освобождение слотов после смерти читателя стоит за флагом.

Чтобы проверить оценку цифрами, нужны `sentrux` DSM и `test_gaps` по обоим модулям.

## chain / chain / ход 8 / rep1 / A (371 слов)

Первым я бы добавил живой тест для Windows: «`ProcessManagerProcess` убит при живом лаунчере → в течение нескольких секунд не остаётся ни одного дочернего процесса».

## Почему именно этот

Он закрывает самый рискованный модуль из прошлого ответа, и я нашёл в нём незакрытую дыру именно на нашей платформе:

- Сторож смерти родителя в процессах-детях **на Windows намеренно отключён**: `process_runner.py:114-115`, с комментарием «на Windows ребёнок переживает PM (дерево держит Job Object launcher'а, не PM)».
- Значит, на Windows после смерти менеджера процессов дети остаются живыми, пока лаунчер сам не закроет Job Object. Лаунчер замечает смерть менеджера через `spawner.wait()` → `join()` (`spawner.py:251`). Что он делает после этого, я не проверил.
- Все живые тесты на это поведение помечены `skipif(sys.platform == "win32")`: `test_parent_death_acceptance.py`, `test_parent_death_hazards.py`, `test_no_orphans_acceptance.py`, а в `backend_ctl` — `test_harness_no_orphans_acceptance.py`. Для Windows я нашёл только `test_windows_job_terminate_skips_fallback` в `test_process_tree_guard.py`. Судя по имени, это юнит-проверка ветки кода, а не живое убийство процесса.

Итог: продукт работает на Windows, а гарантия «смерть менеджера процессов не оставляет сирот» живьём проверена только на POSIX. Сироты на этой машине — это камера, занятая старым `camera_0`, и неосвобождённые SHM-сегменты. Следующий запуск получит странный отказ, который будет выглядеть как зависание.

## Каким должен быть тест

- **Подготовка.** Настоящий `SystemLauncher` и два ребёнка: обычный и «зависший», который игнорирует `stop_event`, по образцу `HungChild` из существующих тестов. Тест сначала проверяет, что оба ребёнка живы.
- **Действие.** Убить менеджер процессов по PID (`psutil.Process(pm_pid).kill()`). Не глобальный `taskkill`: это запрещено памятью проекта.
- **Проверки.**
  - Все PID из снимка поддерева исчезли за 5 с. Ожидаемый набор выживших — пустой список `[]`, литералом.
  - Вызов, ожидающий лаунчер, вернул управление.
  - Само ожидание идёт в daemon-потоке с дедлайном на `join`, чтобы при регрессии тест не повесил прогон.
- **Парная проверка достижимости.** Контрольный тест без убийства: при живом менеджере процессов оба ребёнка живут дольше этих 5 с. Иначе пустой список выживших может означать, что дети не стартовали вовсе.
- **Инъекция поломки.** Отключить `TerminateJobObject` / `kill_tree` в лаунчере → тест должен покраснеть на «зависшем» ребёнке.

**Предсказание до запуска.** Честно не знаю, зелёный он будет или красный. Если лаунчер после `wait()` не вызывает разрушение Job Object, «зависший» ребёнок выживет, и это будет находка. Это не утверждение, а причина писать тест первым.

По правилам проекта тест пишет `tester` вслепую, по критериям приёмки выше, в worktree. Запустить его?

## chain / chain / ход 8 / rep1 / B (196 слов)

Первым я бы добавил такой тест: на Windows убить `ProcessManagerProcess`, оставить главный процесс живым и проверить, что все дочерние процессы исчезли за 2,0 с. Он закрывает вопрос «что делают дети, если PM умер».

**Почему я думаю, что на Windows эта защита может не работать:**
1. Сторож смерти родителя `_watch_parent` ждёт, когда изменится `os.getppid()` (`runner/process_runner.py:101`). В докстринге прямо сказано, что так ведёт себя POSIX.
2. На Windows дочерний процесс не переходит к новому родителю. Поэтому `getppid()`, по моему пониманию, не меняется, и сторож не срабатывает.
3. Job Object с `KILL_ON_JOB_CLOSE` (`launcher/process_tree_guard.py`) убивает дерево только при закрытии handle. Если главный процесс жив, handle остаётся открытым.

Если это так, после смерти PM дети работают без супервизора, без раздачи состояния и без перезапуска.

**Тест:** главный процесс плюс 2 дочерних. PM убивается через `TerminateProcess` по PID. Потом нужно убедиться, что все PID детей мертвы через 2,0 с. Ожидаемое значение берётся литералом из `test_parent_death_hazards.py`.

Есть ли там Windows-вариант `test_parent_sigkill_during_child_initialize`, я не проверял. Может быть, `SystemLauncher` сам замечает смерть PM, этот путь я тоже не читал. Поэтому то, что защита на Windows не работает, пока гипотеза: её должен подтвердить или опровергнуть этот тест.

## chain / chain / ход 8 / rep2 / B (135 слов)

Первым я бы добавил тест на реальных процессах: убить дочерний процесс и проверить, что он перезапустился и что подписчик увидел это в дельтах.

**Почему этот**
- `test_process_monitor.py` построен на заглушках: 22 упоминания `Mock` и 1 упоминание `multiprocessing`.
- Цепочку «падение → рестарт → дельта» проверяют по частям, целиком на настоящих объектах — нет.
- Я искал только в `process_manager_module/tests`. В других каталогах такой тест может быть.

**Сценарий**
1. Настоящий оркестратор и один процесс-заглушка с `restart_policy: {enabled: true, max_retries: 3, window_sec: 60}`.
2. Подписчик на `processes.**`.
3. `kill()` дочернего процесса.
4. Ожидаем дельты по порядку: `crashed`, затем `running`. Новый PID должен отличаться от старого. Дедлайн — `backoff_sec + heartbeat_timeout + 5` с.
5. Ожидание идёт в потоке-демоне с `join(timeout)`, чтобы зависание дало красный тест, а не повисший прогон.

**Внесение поломки:** если убрать `_dispatch_due_restarts`, тест должен стать красным на шаге 4.

## single / q1 / ход 1 / rep1 / A (403 слов)

## Что делает `RouterManager`

Это единственная точка входа и выхода сообщений процесса. По умолчанию у каждого процесса один `RouterManager`, и с внешним миром процесс общается только через него (`router_module/README.md:3`). Наследуется от `ChannelRoutingManager`, поэтому получает потокобезопасный реестр каналов и подключение логов и ошибок через `ObservableMixin`.

**Исходящие сообщения:** `send(msg)` или `send_async(msg, priority)` проходят через `AsyncSender` (PriorityQueue плюс фоновый поток), затем через `MiddlewarePipeline` и `_resolve_channels`. После этого вызывается `IMessageChannel.send()`, обычно `QueueChannel` → `queue.put()`.

`_resolve_channels` выбирает канал в таком порядке (`router_manager.py:1998`):
1. Если `msg["channel"]` задан явно, канал берётся из реестра напрямую. Значение `"queue"` считается легаси и игнорируется.
2. Иначе `channel_dispatcher` ищет маршрут по `command` или `type`. Маршруты задаются через `register_route("set_fps", "control")`.
3. Если маршрута нет и флаг Ф7 G.2 включён, используются каналы по типу груза `{process}_{kind}`.
4. Если ничего не нашлось, возвращается пустой список. Дальше либо ошибка, либо fallback по `targets` в `_do_send`.

**Входящие сообщения:** `AsyncReceiver` в фоновом потоке опрашивает все каналы (`poll_all`), прогоняет сообщения через recv-middleware и передаёт в `message_dispatcher`. Тот вызывает callback'и, зарегистрированные через `add_message_callback` или `register_message_handler`.

## Имя процесса и канал Router

| | **Имя процесса** | **Канал Router** |
|---|---|---|
| Что это | Логический получатель: «кому» | Физическая очередь: «через какую трубу» |
| Где задаётся | `send_message(target, msg)`, `Message.targets`, `register_dispatch`, `connection_map` | `FieldRouting(channel=...)`, `msg["channel"]`, `register_channel(QueueChannel(name, q))` |
| Примеры | `renderer`, `processor` | `control_draw`, `system_events`, `{proc}_data`, `{proc}_local` |
| Чем является | Идентичность процесса в системе | Ключ в реестре очередей из `shared_resources_module`, на него backend подписывает обработчики |

Эти два значения **не обязаны совпадать**. Пример из `ROUTING_GLOSSARY.md:27`: поля регистра `draw` маршрутизируются в канал `control_draw`, а `register_update` из GUI уходит в процесс `renderer`, потому что так указано в `register_dispatch` или `connection_map`. Одному процессу может принадлежать несколько каналов (data, local, control_*), а один канал вроде `system_events` бывает общим.

Связь между ними такая: `send_message(target, msg)` в `process_communication.py:290` — это просто алиас `send_to_process`. Имя процесса превращается в канал внутри роутера: через fallback по `targets` или через каналы вида `{process}_{kind}`.

Есть и третья ось, её тоже часто путают с первыми двумя: **имя источника наблюдаемости** (`module`, например `multiprocess_framework.modules.router_module`). Оно отвечает не на вопрос «кому доставить», а на вопрос «чья это запись лога и куда её писать». С транспортом оно никак не пересекается.

**Что не проверено:** fallback по `targets` в `_do_send` и ветку с флагом G.2 я знаю только по docstring, сам код не читал. Если понадобится точное поведение при промахе диспетчера, следующим смотреть `_do_send` в `router_manager.py`.

## single / q1 / ход 1 / rep1 / B (150 слов)

`RouterManager` — транспорт сообщений внутри одного процесса. Он держит реестр каналов и отправляет или принимает через них сообщения.

**Что делает `RouterManager`** (`multiprocess_framework/modules/router_module/README.md:132`):
- `register_channel` / `get_channel` ведут реестр каналов. Каждый канал привязан к очереди из `shared_resources_module`.
- `send` отправляет синхронно, `send_async` — через PriorityQueue в `AsyncSender`.
- `register_route(key, channel_name)` привязывает тип команды к каналу. Если `channel_name=None`, канал берётся из `msg["channel"]`. Для рассылки в несколько каналов есть `register_broadcast_route`.
- `receive` и `add_message_callback` принимают сообщения синхронно и асинхронно.

**Имя процесса и канал Router** (`multiprocess_framework/docs/ROUTING_GLOSSARY.md:19`):

| | Имя процесса | Канал Router |
|---|---|---|
| Вопрос | Какому процессу доставить | В какую очередь положить и какой обработчик вызвать |
| Где задаётся | `send_message(target, msg)`, `Message.targets`, `register_dispatch` | `FieldRouting(channel=...)`, `msg["channel"]` |
| Пример | `renderer` | `control_draw` |

Эти имена не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`, а `register_update` из GUI уходит в процесс `renderer`.

Есть третья ось — имя источника логов (`module`). Она не связана с транспортом.

## single / q1 / ход 1 / rep2 / A (390 слов)

## RouterManager

`RouterManager` (`multiprocess_framework/modules/router_module/core/router_manager.py`) — единственная точка, через которую процесс обменивается сообщениями с другими процессами. По умолчанию у каждого процесса один такой объект. Наследуется от `ChannelRoutingManager` и берёт оттуда потокобезопасный реестр каналов и диспетчер.

**Исходящие сообщения:**
1. `send(msg)` отправляет синхронно. `send_async(msg, priority)` кладёт сообщение в `PriorityQueue` класса `AsyncSender`, а фоновый поток отправляет его позже.
2. Сообщение проходит через `MiddlewarePipeline` (функции `fn(msg) -> dict | None`, где `None` отбрасывает сообщение).
3. `_resolve_channels(msg)` выбирает канал:
   - если задан `msg["channel"]`, канал берётся из реестра напрямую по имени;
   - иначе `channel_dispatcher` ищет его по маршрутам: сначала точное совпадение, потом шаблон, потом broadcast. Маршруты задаются через `register_route("set_fps", "control")`.
4. Найденный `IMessageChannel` выполняет `.send(msg)`. Обычно это `QueueChannel`, который делает `queue.put()` в очередь из `shared_resources_module`. Можно подключить и свои каналы, например сокет или БД.

**Входящие сообщения:** фоновый поток `AsyncReceiver` опрашивает все каналы (`poll_all()`), пропускает сообщения через middleware приёма и передаёт в `message_dispatcher`, который вызывает callback'и, зарегистрированные через `add_message_callback` / `register_message_handler`.

Подробнее — `multiprocess_framework/modules/router_module/README.md`.

## Канал Router и имя процесса

Это две разные оси адресации, и совпадать они не обязаны (`multiprocess_framework/docs/ROUTING_GLOSSARY.md`):

| | **Имя процесса** | **Канал Router** |
|---|---|---|
| На какой вопрос отвечает | *Какому процессу* доставить сообщение | *В какую очередь* положить сообщение и *какой обработчик* на неё подписан |
| Где задаётся | `send_message(target, msg)`, `Message.targets`, `register_dispatch` / `connection_map` | `FieldRouting(channel=...)` в схеме регистра, `msg["channel"]`, имя `QueueChannel` |
| Примеры | `renderer`, `processor` | `control_draw`, `control_*` |
| Уровень | `ProcessModule.send_message` → `ProcessCommunication.send_to_process` | `RouterManager._resolve_channels` → реестр каналов |

Пример из глоссария: поля регистра `draw` по схеме уходят в канал `control_draw`, а `register_update` из GUI при этом доставляется процессу `renderer`, потому что так указано в `register_dispatch` или `connection_map`. Если в `register_dispatch` перечислено несколько процессов, сообщение отправляется им по очереди. Ошибки при этом проглатываются, и уже отправленное не откатывается, поэтому обработчики-получатели должны быть идемпотентны.

Есть и третья ось, которую тоже путают с первыми двумя: **имя источника наблюдаемости** (поле `module` в записи лога, например `multiprocess_framework.modules.router_module`). Оно определяет, куда и с каким порогом пишется запись, и к доставке сообщений отношения не имеет.

Коротко: имя процесса говорит, кому отправить сообщение, а канал — по какой очереди и в какой обработчик оно попадёт.

## Что осталось неясным
- Подробную реализацию `_resolve_channels` и связь между `send_to_process(target)` и выбором канала я не читал; ответ основан на README модуля и глоссарии. Если нужно, могу пройти по коду и описать точный путь от имени процесса до очереди.

## single / q1 / ход 1 / rep2 / B (134 слов)

`RouterManager` — единственная точка входа и выхода сообщений процесса. В каждом процессе по умолчанию один экземпляр (`multiprocess_framework/modules/router_module/README.md:3`).

**Что делает:**
- Исходящие: `send()` / `send_async()` → middleware → `_resolve_channels(msg)` → `IMessageChannel.send()`. Канал выбирается так: если задан `msg["channel"]`, это прямой поиск, иначе работает `channel_dispatcher` (exact / pattern / broadcast).
- Входящие: фоновый `AsyncReceiver` опрашивает каналы через `poll_all()`, прогоняет recv-middleware и отдаёт сообщение в `message_dispatcher`. Оттуда оно уходит в callbacks из `add_message_callback`.
- Наследует `ChannelRoutingManager`: реестр каналов и логирование через `ObservableMixin`.

**Процесс и канал — разные оси** (`multiprocess_framework/docs/ROUTING_GLOSSARY.md:19`):

| | Имя процесса | Канал Router |
|---|---|---|
| Вопрос | кому доставить | в какую очередь положить |
| Где задаётся | `send_message(target, …)`, `Message.targets`, `register_dispatch`, `connection_map` | `FieldRouting(channel=…)`, `msg["channel"]` |
| Пример | `renderer` | `control_draw` |

Эти значения не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`, а `register_update` из GUI может уйти в процесс `renderer`.

## single / q1 / ход 1 / rep3 / A (385 слов)

## Что делает `RouterManager`

Через него процесс общается со всеми остальными. По умолчанию в каждом процессе один `RouterManager`. Он наследует `ChannelRoutingManager` (`multiprocess_framework/modules/router_module/README.md:3`).

**Исходящие сообщения**

1. `send(msg)` отправляет синхронно, `send_async(msg, priority)` кладёт сообщение в `PriorityQueue` фонового `AsyncSender`.
2. Сообщение проходит `MiddlewarePipeline`: функции `fn(msg) -> dict | None` могут изменить сообщение или отбросить его.
3. `_resolve_channels(msg)` выбирает канал:
   - если задан `msg["channel"]`, канал берётся прямым поиском по имени, O(1);
   - если нет, его выбирает `channel_dispatcher` по точному совпадению, по шаблону или через broadcast.
4. Сообщение уходит в `IMessageChannel.send()`. Обычно это `QueueChannel`, который делает `queue.put()` в очередь из `shared_resources_module`. Можно подключить и свои каналы, например сокет или БД.

**Входящие сообщения**

- `AsyncReceiver` в фоновом потоке опрашивает все каналы (`poll_all`).
- Сообщения проходят recv-middleware.
- `message_dispatcher` раздаёт их обработчикам, зарегистрированным через `add_message_callback` или `register_message_handler`.

Ещё он подключает логирование к каждому каналу (`_attach_logger`) и поддерживает обработчики, которые возвращают строку: эта строка считается именем канала.

## Канал Router и имя процесса

По `multiprocess_framework/docs/ROUTING_GLOSSARY.md` это две разные оси адресации:

| | Имя процесса | Канал Router |
|---|---|---|
| На какой вопрос отвечает | Какому процессу доставить сообщение | В какую очередь положить сообщение и кто на неё подписан |
| Где задаётся | `send_message(target, msg)`, `Message.targets`, `register_dispatch`, `connection_map` | `FieldRouting(channel=...)` в схемах регистров, `msg["channel"]`, `QueueChannel("control", q)` |
| Пример | `renderer`, `processor` | `control_draw`, `control_*` |
| Уровень | Логический получатель | Физическая привязка к очереди в реестре каналов |

**Совпадать они не обязаны.** Пример из глоссария: поля регистра `draw` направляются в канал `control_draw`, а `register_update` из GUI уходит в процесс `renderer`, если так указано в `register_dispatch` или `connection_map`. Отсюда типичная ошибка: передать имя процесса туда, где ждут канал, или наоборот.

**Третья ось — источник наблюдаемости.** Поле `module` в лог-записи имеет вид точечного пути, например `multiprocess_framework.modules.router_module`. Оно решает, с каким порогом и в какие приёмники пишется запись, и с транспортом не связано. Учтите ещё два момента:
- `RouterManager` унаследовал `set_sink_enabled`, но операторская команда до него не доходит: его отсекает whitelist. Так пульт не может одной командой отключить IPC-канал.
- Наш `scope` (`SYSTEM` / `BUSINESS` / …) — это группа логирования. Это не `InstrumentationScope` из OTel: роль идентификатора источника у нас играет `module` (ADR-LOG-005).

**Что я не проверил.** Ответ составлен по README модуля и глоссарию, код я не открывал. Как именно `send_message(target, ...)` превращает имя процесса в конкретную очередь, нужно смотреть в `ProcessModule` / `RouterAdapter`. Если интересно, разберу этот путь по коду.

## single / q1 / ход 1 / rep3 / B (175 слов)

`RouterManager` — единственная точка, через которую процесс шлёт и принимает IPC-сообщения. По умолчанию у каждого процесса один такой объект (`multiprocess_framework/modules/router_module/README.md:3`).

**Исходящие сообщения:**
- `send(msg)` или `send_async(msg, priority)`; async-вариант кладёт сообщение в `PriorityQueue` фонового `AsyncSender`.
- Сообщение проходит send-middleware.
- `_resolve_channels(msg)` выбирает канал. Если задан `msg["channel"]`, канал находится прямым поиском за O(1). Иначе канал выбирает `channel_dispatcher` по точному имени, шаблону или broadcast.
- `IMessageChannel.send()` выполняет доставку, например `QueueChannel` → `queue.put()`.

**Входящие сообщения:** фоновый `AsyncReceiver` опрашивает каналы (`poll_all`). Затем идёт recv-middleware, затем `message_dispatcher` вызывает зарегистрированные callbacks.

**Канал и процесс — разные оси адресации** (`multiprocess_framework/docs/ROUTING_GLOSSARY.md:19`):

| | Имя процесса | Канал Router |
|---|---|---|
| Пример | `renderer`, `processor` | `control_draw` |
| Где задают | `send_message(target, msg)`, `Message.targets`, `register_dispatch`, `connection_map` | `FieldRouting(channel=...)`, `msg["channel"]` |
| Вопрос | Какому процессу доставить | В какую очередь положить и какой обработчик сработает |

Эти имена не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`. При этом `register_update` из GUI может уйти в процесс `renderer`.

Есть третья ось — имя источника наблюдаемости (поле `module` записи лога). К транспорту она не относится.

## single / q2 / ход 1 / rep1 / A (211 слов)

К ярусу **core** относятся **17 модулей**. Источник — `multiprocess_framework/docs/MODULE_TIERS.md:51`: «core — 17, optional — 10, frozen — 0». Всего модулей 27.

| # | Модуль | Почему core |
|---|---|---|
| 1 | `base_manager` | базовый класс всех менеджеров, `ObservableMixin`, `BaseAdapter` |
| 2 | `message_module` | `Message` и `MessageAdapter` — единица IPC |
| 3 | `channel_routing_module` | общая база Logger, Error, Router и Stats |
| 4 | `logger_module` | логирование, создаётся в каждом процессе при запуске |
| 5 | `error_module` | обработка ошибок, наследник Logger |
| 6 | `statistics_module` | счётчики и окна агрегации |
| 7 | `dispatch_module` | ядро диспетчеризации (`EXACT_MATCH`) |
| 8 | `command_module` | тонкий фасад над dispatch |
| 9 | `router_module` | транспорт сообщений между процессами (`AsyncSender`, `AsyncReceiver`) |
| 10 | `config_module` | конфиг на границе процесса |
| 11 | `data_schema_module` | `SchemaBase`, `FieldMeta`, `FieldRouting` — ядро схем |
| 12 | `shared_resources_module` | `ConfigStore`, `MemoryManager`, `QueueRegistry` |
| 13 | `process_module` | `ProcessModule` и плагинный рантайм |
| 14 | `process_manager_module` | `SystemLauncher`, `ProcessRegistry`, супервизия |
| 15 | `worker_module` | LOOP- и TASK-воркеры |
| 16 | `console_module` | `ConsoleManager` создаётся в каждом процессе |
| 17 | `chain_module` | pipeline-движок `ProcessModule` построен на `ChainRunnable` |

Что стоит учесть:
- **`chain_module`** раньше был помечен как frozen. Его перевели в core после merge `22393392`. В документе прямо сказано, что нужно переподтверждение владельца (`MODULE_TIERS.md:65`).
- У `console_module` и `dispatch_module` ярус core, но часть их функций заморожена: интерактивный God-Mode консоли и режимы dispatch сложнее `EXACT_MATCH`.

Я прочитал только сам документ. По словам корневого `CLAUDE.md`, его сверяет контракт-тест, но тест я не запускал. Поэтому с текущим кодом документ не сверен.

## single / q2 / ход 1 / rep1 / B (129 слов)

В `multiprocess_framework/docs/MODULE_TIERS.md` к ярусу core отнесено 17 модулей. В таблице 17 строк, итог на строке 51 говорит то же: «core — 17, optional — 10, frozen — 0».

1. `base_manager`
2. `message_module`
3. `channel_routing_module`
4. `logger_module`
5. `error_module`
6. `statistics_module`
7. `dispatch_module`: фичи сверх `EXACT_MATCH` заморожены, сам модуль в core.
8. `command_module`
9. `router_module`
10. `config_module`
11. `data_schema_module`
12. `shared_resources_module`
13. `process_module`
14. `process_manager_module`
15. `worker_module`
16. `console_module`: заморожен только режим God-Mode, модуль в core.
17. `chain_module`

`chain_module` попал в core при пересмотре старого вердикта, где он был frozen. Документ помечает его так: «Требует переподтверждения владельца» (§2, строка 65). Если владелец не подтвердит, в core останется 16 модулей.

Список взят из документа, по коду я его не сверял. Документ сверяется контракт-тестом, но этот тест я не запускал.

## single / q2 / ход 1 / rep2 / A (248 слов)

**К ярусу core относятся 17 модулей из 27.** Так записано в ярусной карте `multiprocess_framework/docs/MODULE_TIERS.md:51`: core — 17, optional — 10, frozen — 0.

Core — это модули, без которых не загружается ни одно приложение на фреймворке:

| # | Модуль | Роль |
|---|--------|------|
| 1 | `base_manager` | базовый класс менеджеров, `ObservableMixin`, `BaseAdapter` |
| 2 | `message_module` | `Message`/`MessageAdapter`, единица обмена между процессами |
| 3 | `channel_routing_module` | общая база Logger/Error/Router/Stats |
| 4 | `logger_module` | логирование процесса |
| 5 | `error_module` | обработка ошибок, наследник Logger |
| 6 | `statistics_module` | счётчики и окна агрегации |
| 7 | `dispatch_module` | ядро диспетчеризации (`EXACT_MATCH`) |
| 8 | `command_module` | тонкий фасад над dispatch |
| 9 | `router_module` | `AsyncSender`/`AsyncReceiver`, передача сообщений между процессами |
| 10 | `config_module` | конфиг на границе процессов |
| 11 | `data_schema_module` | `SchemaBase`/`FieldMeta`/`FieldRouting` |
| 12 | `shared_resources_module` | PSR, ConfigStore, MemoryManager, QueueRegistry |
| 13 | `process_module` | `ProcessModule`, среда выполнения плагинов |
| 14 | `process_manager_module` | `SystemLauncher`, оркестратор |
| 15 | `worker_module` | воркеры LOOP/TASK |
| 16 | `console_module` | `ConsoleManager` создаётся в каждом процессе |
| 17 | `chain_module` | на нём стоит pipeline-движок `ProcessModule` |

Ещё три оговорки:
- **`chain_module`.** В первоначальной карте он был замороженным модулем (frozen). По коду его перенесли в core, но в документе стоит пометка «требует переподтверждения владельца» (§2, строка 65). Пока вы это не подтвердите, этот вердикт открыт.
- **Замороженные функции внутри core-модулей.** В `console_module` и `dispatch_module` модули считаются core, но часть их функций заморожена: God-Mode консоли и диспетчеризация сложнее `EXACT_MATCH` (§3).
- **Сверка карты с кодом.** Карту в последний раз сверяли с кодом 2026-07-26. Сейчас на диске 27 каталогов модулей, и их имена совпадают с таблицей. Контракт-тест `modules/tests/test_module_tiers.py`, который следит за этим соответствием, я в этой сессии не запускал.

## single / q2 / ход 1 / rep2 / B (155 слов)

К ярусу `core` относится **17 модулей**. Источник — `multiprocess_framework/docs/MODULE_TIERS.md:51`: «core — 17, optional — 10, frozen — 0».

| # | Модуль | Роль |
|---|--------|------|
| 1 | `base_manager` | база всех менеджеров, `ObservableMixin` |
| 2 | `message_module` | `Message`/`MessageAdapter`, IPC |
| 3 | `channel_routing_module` | общая база Logger/Error/Router/Stats |
| 4 | `logger_module` | логирование процесса |
| 5 | `error_module` | обработка ошибок |
| 6 | `statistics_module` | счётчики и окна агрегации |
| 7 | `dispatch_module` | диспетчеризация `EXACT_MATCH` |
| 8 | `command_module` | фасад над dispatch |
| 9 | `router_module` | `AsyncSender`/`AsyncReceiver` |
| 10 | `config_module` | конфиг на границе |
| 11 | `data_schema_module` | `SchemaBase`, `FieldRouting` |
| 12 | `shared_resources_module` | PSR, `ConfigStore`, очереди |
| 13 | `process_module` | `ProcessModule`, плагинный рантайм |
| 14 | `process_manager_module` | `SystemLauncher`, супервизия |
| 15 | `worker_module` | LOOP/TASK-воркеры |
| 16 | `console_module` | `ConsoleManager` в каждом процессе |
| 17 | `chain_module` | движок pipeline `ProcessModule` |

У двух модулей есть оговорки:
- `chain_module` раньше был в ярусе `frozen`. Перевод в `core` в документе помечен «требует переподтверждения владельца» (строка 65).
- У `console_module` и `dispatch_module` заморожены отдельные фичи, а не модули целиком. Это God-Mode и режимы сверх `EXACT_MATCH`.

Цифры взяты из документа. Сам контракт-тест я не запускал.

## single / q2 / ход 1 / rep3 / A (216 слов)

Согласно ярусной карте `multiprocess_framework/docs/MODULE_TIERS.md:51`, к ярусу **core** относятся **17 модулей** из 27:

1. `base_manager` — базовый класс всех менеджеров, `ObservableMixin`, `BaseAdapter`.
2. `message_module` — `Message`/`MessageAdapter`, единица IPC.
3. `channel_routing_module` — общая база для Logger, Error, Router и Stats.
4. `logger_module` — логирование, создаётся в каждом процессе при запуске.
5. `error_module` — обработка ошибок, наследник Logger.
6. `statistics_module` — счётчики и окна агрегации.
7. `dispatch_module` — ядро диспетчеризации (`EXACT_MATCH`).
8. `command_module` — тонкий фасад над dispatch.
9. `router_module` — транспорт между процессами (`AsyncSender`/`AsyncReceiver`).
10. `config_module` — конфиг на границе процессов.
11. `data_schema_module` — `SchemaBase`, `FieldMeta`, `FieldRouting`, `DataConverter`.
12. `shared_resources_module` — PSR, ConfigStore, MemoryManager, QueueRegistry.
13. `process_module` — база дочернего процесса (`ProcessModule`).
14. `process_manager_module` — `SystemLauncher`, реестр процессов, супервизия.
15. `worker_module` — воркеры LOOP/TASK и жизненный цикл потоков.
16. `console_module` — `ConsoleManager` создаётся в каждом процессе.
17. `chain_module` — на нём стоит pipeline-движок `ProcessModule`.

Остальные 10 модулей — **optional**. Ярус **frozen** на уровне целых модулей пуст: заморожены только отдельные функции внутри живых модулей (раздел §3 документа).

Две оговорки:
- `chain_module` по решению G0 был frozen. В core его перевели при сверке с кодом, и в документе (§2) отмечено, что это **требует переподтверждения владельца**.
- По моим данным, документ последний раз обновлялся 2026-07-26. Я не сверял его с каталогами на диске и не запускал контракт-тест `modules/tests/test_module_tiers.py`. Этот тест падает, если строки таблицы расходятся с каталогами.

## single / q2 / ход 1 / rep3 / B (105 слов)

К ярусу `core` относятся **17 модулей** из 27. Так записано в `multiprocess_framework/docs/MODULE_TIERS.md:51`.

1. `base_manager`
2. `message_module`
3. `channel_routing_module`
4. `logger_module`
5. `error_module`
6. `statistics_module`
7. `dispatch_module`
8. `command_module`
9. `router_module`
10. `config_module`
11. `data_schema_module`
12. `shared_resources_module`
13. `process_module`
14. `process_manager_module`
15. `worker_module`
16. `console_module`
17. `chain_module`

Остальные 10 модулей относятся к ярусу `optional`. Ярус `frozen` пуст.

Ярус `chain_module` ещё не подтверждён вами. По карте G0 он был `frozen`. Теперь он `core`, потому что на `ChainRunnable` стоит pipeline-движок `ProcessModule`. Документ помечает это «⚠️ Требует переподтверждения владельца» (`MODULE_TIERS.md:65`).

Данные взяты из документа. Код я не открывал и `test_module_tiers.py` не запускал.

## single / q3 / ход 1 / rep1 / A (591 слов)

Доставка идёт в четыре шага: подписка → сопоставление в момент записи → общий буфер → один поток-отправитель, который раз в тик шлёт одно IPC-сообщение `state.changed`.

## 1. Подписка: `state.subscribe`

`StateStoreManager.handle_state_subscribe` (`multiprocess_framework/modules/state_store_module/manager/state_store_manager.py:393`) принимает `{pattern, subscriber, exclude_sources?}` и вызывает `SubscriptionManager.subscribe` (`core/subscription_manager.py:232`). Этот метод:
- создаёт неизменяемую `Subscription` с `sub_id` (uuid4);
- сохраняет её в `_subscriptions` и в индекс `_by_subscriber`, чтобы быстро снимать все подписки процесса через `unsubscribe_all`;
- заранее разбирает шаблон на сегменты через `_split_pattern`. Результат кэшируется в `lru_cache(256)`, потому что сопоставление вызывается тысячи раз.

Сразу после этого новый подписчик получает **текущий снимок** (`_replay_initial_state`, `:430`):
- `static_prefix(pattern)` выделяет часть шаблона до первого `*`/`**`, и копируется только поддерево этого префикса (`_iter_replay_pairs`, `:477`);
- если в шаблоне нет wildcard, значение берётся одним `get`, без копирования поддерева;
- найденные значения превращаются в дельты с `source="__replay__"` и revision снимка и отправляются через `dispatcher.enqueue_replay`. Прямой отправки нет: так у снимка тот же единственный отправитель, что и у обычных изменений.

## 2. Сопоставление шаблона с путём

`_match_pattern` (`subscription_manager.py:66`) — рекурсивное сравнение по сегментам пути, разделённым точками:
- `*` совпадает ровно с одним сегментом;
- `**` совпадает с нулём и более сегментов (проверяются две ветки: пропустить `**` или поглотить один сегмент);
- остальные сегменты сравниваются буквально, с учётом регистра.

`match(delta)` (`:310`) под `RLock` только копирует список подписок, а сопоставляет уже без блокировки. Подписки, у которых `delta.source` входит в `exclude_sources`, пропускаются: так процесс не получает обратно собственные записи.

⚠️ Индекса или дерева по шаблонам нет: каждая дельта проверяется против **всех** подписок по очереди.

## 3. Рассылка: `DeltaDispatcher`

Путь от записи: `handle_state_set` → middleware `run_before_set` → `store.set` → `run_after_set` → `dispatcher.dispatch_single(delta)` (`state_store_manager.py:213`). Пакетные операции вызывают `dispatch(deltas)`.

`dispatch` (`manager/delta_dispatcher.py:99`):
1. **Сопоставляет в момент записи, а не при отправке.** Иначе подписчик, появившийся между записью и тиком, получил бы чужие накопленные дельты.
2. **Группирует по подписчику и убирает повторы** (`_match_and_group`, `:127`). Если процесс подписан и на `cameras.0.*`, и на `cameras.**`, каждую дельту он получит один раз. Исходный порядок сохраняется.
3. **Кладёт дельты в буфер** `subscriber → list[Delta]` (`_buffer_deltas`, `:173`). Схлопывания «оставить последнее значение» нет: в буфере остаются все дельты в исходном порядке.

## 4. Отправка: поток `StateCoalesceFlusher`

- Это единственный поток, который отправляет сообщения. Период тика — `_DEFAULT_FLUSH_INTERVAL_SEC = 0.12` с. Если в буфере подписчика накопилось `_DEFAULT_BUFFER_CAP = 200` дельт, поток будят досрочно через `_wake`. Сам записывающий поток при этом ничего не отправляет, иначе нарушился бы порядок сообщений.
- `_flush_once` (`:245`) под блокировкой забирает весь буфер целиком и отправляет вне блокировки: каждому подписчику одно сообщение.
- `_send_state_changed` (`:339`) формирует сообщение `{"type": "event", "command": "state.changed", "targets": [subscriber], "queue_type": "state", "data": {deltas, revision, first_revision}}` и вызывает `router.send_async`.
  - `revision` и `first_revision` — максимальная и минимальная revision в сообщении. По ним `StateProxy` проверяет, что revision идут без пропусков, на всём диапазоне сообщения. Это нужно, потому что `merge` увеличивает revision на каждый изменённый лист.
  - Очередь `{proc}_state` при переполнении выбрасывает самые старые сообщения (drop_oldest). Тогда клиент видит пропуск revision и запрашивает состояние заново (resync), а не теряет управление.
- `stop_flusher` при остановке отправляет остаток буфера, но только если поток действительно завершился. Иначе остаток теряется — так сохраняется правило «один отправитель».

## Почему так устроено
В docstring модуля записано: без буферизации GUI не справлялся с потоком сообщений (замер 2026-07-23: 1702 потери за ~45 с). Задержка доставки до 120 мс принята осознанно: по аудиту на `state.changed` никто не реагирует действиями, подписчики только наблюдают.

## Что осталось непроверенным
- Ответ собран из исходного кода. Тесты и живой стенд я не запускал. qex недоступен (Ollama не запущена), поиск шёл через Grep и Read.
- Не смотрел, как `StateProxy` на стороне клиента обрабатывает пропуск revision и resync, и как `ThrottleMiddleware` влияет на запись до рассылки.

## single / q3 / ход 1 / rep1 / B (178 слов)

Доставка идёт в 4 шага: матчинг при мутации → дедуп по подписчику → буфер → один конверт `state.changed` на тик.

1. **Мутация.** `set`/`merge`/`delete` вызывают `DeltaDispatcher.dispatch*` (`state_store_manager.py:213`, `:271`, `:310`).
2. **Матчинг.** `SubscriptionManager.match()` снимает копию подписок под `RLock` и матчит её без лока (`subscription_manager.py:310`).
   - Путь и паттерн режутся по `.`. Разбор паттерна кэшируется через `lru_cache(256)`.
   - `*` — ровно один сегмент, `**` — от нуля сегментов, остальное — точное совпадение (`:66`).
   - Если `delta.source` входит в `exclude_sources` подписки, подписка пропускается.
3. **Дедуп.** `_match_and_group` группирует дельты по процессу и сохраняет их порядок (`delta_dispatcher.py:127`). При подписках `cameras.0.*` и `cameras.**` процесс получит дельту 1 раз.
4. **Буфер и flush.** Дельты копятся по подписчикам. Дедуп keep-last запрещён. Поток `StateCoalesceFlusher` отправляет буфер каждые 120 мс. При 200 дельтах у подписчика он срабатывает досрочно. Все отправки идут только из этого потока, поэтому порядок конвертов сохраняется.
5. **Конверт.** Сообщение `state.changed` уходит в очередь `{subscriber}_state` с drop_oldest. В нём `deltas`, `revision` (max) и `first_revision` (min) (`:339`).

Новому подписчику `enqueue_replay` кладёт снимок поддерева `static_prefix(pattern)` в тот же буфер (`state_store_manager.py:472`, `:507`).

## single / q3 / ход 1 / rep2 / A (633 слов)

Изменения доставляются в два этапа. При мутации дельта сразу сопоставляется с glob-шаблонами и попадает в буфер подписчика. Отдельный поток-flusher потом отправляет каждому подписчику один IPC-конверт `state.changed`.

## 1. Подписка: `state.subscribe`

`StateStoreManager` (`state_store_manager.py:400-428`) принимает `pattern`, `subscriber` и `exclude_sources`, затем вызывает `SubscriptionManager.subscribe()`:

- создаёт неизменяемый `Subscription` с ключом `sub_id = uuid4`;
- ведёт два индекса под `RLock`: `sub_id → Subscription` и `subscriber → {sub_id}` (второй нужен для быстрого `unsubscribe_all`);
- сразу разбирает шаблон через `_split_pattern` (`lru_cache(256)`), чтобы не делать этого при каждом сопоставлении.

После этого новому подписчику отправляется **снимок текущих значений** (`_replay_initial_state`, `:430`). Без него подписчик не увидел бы значения, опубликованные до его подписки, например разовый `status` процесса при старте:
- поиск идёт не по всему дереву, а только в поддереве **статического префикса** шаблона (`_static_prefix`: `processes.*.fps` → `processes`);
- в снимок попадают только листья (dict-узлы отбрасываются), с `source="__replay__"` и `old_value=MISSING`;
- снимок кладётся в буфер через `enqueue_replay`, а не отправляется напрямую. Причина ниже, в разделе про порядок.

## 2. Как шаблон сопоставляется с путём

`_match_pattern` (`subscription_manager.py:66`) рекурсивно сравнивает сегменты пути, разделённые точками:

| Сегмент шаблона | Что совпадает |
|---|---|
| `*` | ровно один любой сегмент |
| `**` | 0..N сегментов: две ветки, пропустить `**` или поглотить один сегмент |
| литерал | точное совпадение с учётом регистра |

`match(delta)` копирует список подписок под локом, а сопоставляет уже без лока. Подписки, у которых `delta.source` входит в `exclude_sources`, пропускаются: так процесс не получает собственные изменения.

## 3. Путь мутации

Пример для `state.set` (`state_store_manager.py:181`). `merge` и `delete` идут так же, через `dispatch` и `dispatch_single`:

```
middleware.before → TreeStore.set() → Delta(revision) → middleware.after
  → DeltaDispatcher.dispatch_single(delta)
```

`DeltaDispatcher.dispatch` (`delta_dispatcher.py:99`):
1. **`_match_and_group`**: для каждой дельты вызывает `subs.match(delta)` и раскладывает результат по подписчикам, **убирая повторы**. Если процесс подписан и на `cameras.0.*`, и на `cameras.**`, дельта дойдёт до него один раз (дубли отсекаются по индексу дельты).
2. **`_buffer_deltas`**: добавляет дельты в `_buffer[subscriber]`, сохраняя порядок. Ни одна дельта не теряется и не заменяется более свежей (схлопывание keep-last здесь запрещено).

Сопоставление выполняется **в момент мутации, а не при flush**. Иначе подписчик, появившийся между мутацией и тиком, получил бы дельты, которые были до него.

## 4. Отправка: daemon-поток `StateCoalesceFlusher`

- Тик — каждые **0.12 с** (`_DEFAULT_FLUSH_INTERVAL_SEC`). Если буфер подписчика достиг **200** дельт (`_DEFAULT_BUFFER_CAP`), flush начинается раньше через `_wake.set()`.
- `_flush_once` (`:245`) под локом подменяет весь буфер пустым, а отправляет уже вне лока: каждому подписчику **один конверт** со всеми накопленными дельтами.
- **Отправляет только flusher.** Даже при переполнении буфера поток, который делает мутацию, сам ничего не шлёт, а только будит flusher. Так конверты для каждого подписчика идут строго по порядку. Если бы отправляли несколько потоков, пакет `[1..cap]` мог бы прийти после `[cap+1]`, и получатель молча выбросил бы его как устаревший.
- `stop_flusher` при shutdown дожидается завершения потока (join) и делает финальный flush, чтобы ничего не осталось в буфере.

## 5. Конверт `state.changed` (`_send_state_changed`, `:339`)

```python
{"type": "event", "targets": [subscriber], "queue_type": QUEUE_STATE,
 "command": "state.changed",
 "data": {"deltas": [...], "revision": max_rev, "first_revision": min_rev}}
```

- Отправляется через `router.send_async` в очередь `{subscriber}_state`. Это отдельный класс очереди с политикой `drop_oldest`, поэтому всплеск `state.set` не забивает системную очередь команд подписчика, из которой ничего не выбрасывается.
- `first_revision` и `revision` задают диапазон ревизий пакета. По нему `StateProxy` проверяет, что ревизии идут без пропусков: `merge` на N листьев даёт N ревизий в одном конверте. Если пропуск есть (например, переполненная очередь выбросила пакет), клиент заново запрашивает состояние (resync).

**Цена такой схемы:** дельта приходит с задержкой до ~120 мс. Это сознательное решение: аудит 2026-07-23 показал, что подписчики `state.changed` только наблюдают за состоянием, а реакция на смерть процесса идёт через heartbeat.

## Что осталось открытым или непроверенным
- Ответ составлен по исходникам, без живого прогона и без запуска тестов.
- Сторону получателя (`StateProxy`: проверка непрерывности ревизий и resync) и `_iter_replay_pairs` / `glob_walker.py` я прочитал только по комментариям в коде, не по их реализации.
- qex недоступен (Ollama не запущена), поэтому искал через Glob, Grep и Read.

## single / q3 / ход 1 / rep2 / B (176 слов)

Доставка идёт в два шага: подписки матчатся сразу при мутации, а отправка откладывается до тика отдельного потока.

1. **Мутация.** `StateStoreManager` передаёт дельты в `DeltaDispatcher.dispatch()` (`state_store_manager.py:213`, `:271`, `:310`).
2. **Матчинг.** `SubscriptionManager.match()` копирует подписки под `RLock` и проверяет каждую уже без блокировки (`subscription_manager.py:310`).
   - Подписка пропускается, если `delta.source` входит в её `exclude_sources`.
   - Путь и паттерн режутся по `.`; разбор паттерна кэшируется через `lru_cache(256)`.
   - `_match_pattern` проверяет совпадение рекурсивно: `*` — ровно один сегмент, `**` — 0..N сегментов, остальное сравнивается буквально.
3. **Дедупликация.** `_match_and_group` группирует дельты по подписчику (`delta_dispatcher.py:127`). Если подписки `cameras.0.*` и `cameras.**` совпали обе, дельта всё равно попадёт к подписчику один раз. Порядок дельт сохраняется.
4. **Буфер.** Дельты дописываются в буфер подписчика. Схлопывания до последнего значения (keep-last) нет. Если в буфере 200 дельт, flusher будится досрочно.
5. **Отправка.** Поток `StateCoalesceFlusher` срабатывает раз в 120 мс. На каждого подписчика уходит один конверт `state.changed` в очередь `{subscriber}_state` с полями `deltas`, `first_revision` и `revision` (`delta_dispatcher.py:339`).

Начальный снимок для нового подписчика идёт через `enqueue_replay` тем же потоком. Так сохраняется порядок конвертов.

## single / q3 / ход 1 / rep3 / A (604 слов)

`StateStoreManager` сам glob-шаблоны не сопоставляет. Он меняет дерево и передаёт получившиеся дельты в `DeltaDispatcher`. Тот сразу находит подходящие подписки через `SubscriptionManager`, складывает дельты в буфер отдельно для каждого подписчика и раз в тик отправляет каждому одно сообщение `state.changed`.

## 1. Подписка: `state.subscribe`
`handle_state_subscribe` (`state_store_manager.py:393`):
- регистрирует `Subscription(sub_id, pattern, subscriber, exclude_sources)` в `SubscriptionManager.subscribe` (`subscription_manager.py:232`). Разобранный шаблон кэшируется в `_split_pattern` (`lru_cache`);
- сразу отправляет новому подписчику текущие значения по шаблону (`_replay_initial_state`, `:430`). Без этого он не увидит значения, опубликованные до подписки.
  - Обход дерева начинается не с корня, а с неизменной части шаблона до первого wildcard: для `processes.*.fps` это `processes` (`static_prefix`, `_iter_replay_pairs`, `:477`).
  - Отправляются только листья, с `source="__replay__"` и текущей revision дерева.
  - Снимок идёт через `enqueue_replay`, то есть через тот же буфер, что и обычные изменения, а не отдельной отправкой.

## 2. Изменение дерева: set / merge / delete
`handle_state_set` / `handle_state_merge` / `handle_state_delete` (`:181`, `:220`, `:281`):
1. Сначала middleware проверяет запрос (`run_before_*`) и может его отклонить. Для delete этот шаг не вызывается.
2. `TreeStore` меняет дерево и возвращает `Delta`. `merge` возвращает по дельте на каждый изменённый лист, и каждая получает свою revision.
3. Вызывается `run_after_*`, затем `self._dispatcher.dispatch(...)`.

## 3. Сопоставление и группировка: в момент изменения
`DeltaDispatcher._match_and_group` (`delta_dispatcher.py:127`):
- для каждой дельты вызывается `SubscriptionManager.match(delta)` (`subscription_manager.py:310`):
  - список подписок копируется под `RLock`, а сопоставление идёт уже без блокировки;
  - подписка пропускается, если `delta.source` входит в её `exclude_sources`. Так процесс не получает обратно собственные изменения;
  - `_match_pattern` рекурсивно сравнивает сегменты пути, разделённые точкой:
    - `*` совпадает ровно с одним сегментом;
    - `**` совпадает с любым числом сегментов, включая ноль;
    - остальные сегменты должны совпасть буквально, с учётом регистра.
- Повторы убираются по подписчику. Если процесс подписан, например, на `cameras.0.*` и на `cameras.**`, каждую дельту он получит один раз. Порядок дельт сохраняется.

Сопоставление намеренно делается при изменении, а не при отправке. Иначе подписчик, появившийся между изменением и тиком, получил бы дельты, которые к нему не относятся.

## 4. Буфер и отправка
- `_buffer_deltas` (`:173`) дописывает дельты в `self._buffer[subscriber]`. Ничего не выбрасывается, даже если по одному пути пришло несколько изменений подряд: иначе у получателя появятся пропуски в revision.
- Отправляет только один поток — `StateCoalesceFlusher` (`_flusher_loop`, `:265`). Он срабатывает раз в 120 мс или раньше, если его разбудили через `_wake`. Будят его в двух случаях:
  - в буфере какого-то подписчика накопилось 200 дельт;
  - пришёл начальный снимок для нового подписчика.
- `_flush_once` под блокировкой подменяет буфер на пустой и уже без блокировки отправляет каждому подписчику по одному сообщению.
- Отправитель один намеренно. Если бы отправляли несколько потоков, сообщения одному подписчику могли бы прийти не по порядку, и получатель отбросил бы пакет как устаревший без сообщения об ошибке.

## 5. Сообщение
`_send_state_changed` (`:339`) отправляет через `router.send_async`:
```python
{"type": "event", "targets": [subscriber], "queue_type": "state",
 "command": "state.changed",
 "data": {"deltas": [...], "revision": max_rev, "first_revision": min_rev}}
```
- Адрес — имя процесса в `targets`, а не канал Router.
- Сообщение попадает в очередь `{subscriber}_state`. При переполнении эта очередь выбрасывает самые старые сообщения, поэтому поток изменений состояния не забивает очередь команд процесса.
- Пара `first_revision`/`revision` нужна получателю (`StateProxy`), чтобы проверить, что revision идут без пропусков на всём диапазоне пакета. Если пропуск есть, он запрашивает свежий снимок через `state.get_subtree` с `paths`. Это я знаю из комментариев в коде; сам `state_proxy.py` не открывал.

## Итог
```
state.set/merge/delete → TreeStore → Delta(revision)
  → DeltaDispatcher.dispatch → SubscriptionManager.match (glob + exclude_sources)
  → убрать повторы по подписчику → буфер подписчика
  → поток-отправитель (120 мс или раньше) → state.changed → {subscriber}_state
```

**Что осталось непроверенным:**
- Сторону получателя (`proxy/state_proxy.py`) я не читал: проверку пропусков revision и запрос свежего снимка знаю только по комментариям в коде отправителя.
- Сопоставление перебирает все подписки на каждую дельту, отдельного индекса по шаблонам нет. Цифр производительности я не снимал; комментарий в коде говорит о десятках шаблонов.

## single / q3 / ход 1 / rep3 / B (162 слов)

Доставка работает в два этапа: матчинг в момент мутации, отправка одним конвертом на тике фонового потока.

1. **Мутация.** `set`/`update`/`delete` порождают `Delta` и вызывают `dispatch` (`state_store_manager.py:213`, `:271`, `:310`).
2. **Матчинг.** `SubscriptionManager.match` берёт снимок подписок под `RLock`. Затем сверяет путь дельты с каждым паттерном (`subscription_manager.py:310`). Подписка пропускается, если `delta.source` входит в её `exclude_sources`.
3. **Правила glob.** `*` означает ровно 1 сегмент, `**` — 0 и более. Остальные сегменты сравниваются точно, с учётом регистра. Матчер рекурсивный, разбор паттерна кэширует `lru_cache(256)`.
4. **Дедупликация.** `_match_and_group` даёт каждую дельту подписчику 1 раз, даже если совпали `cameras.0.*` и `cameras.**`. Исходный порядок сохраняется.
5. **Буфер.** Дельты копятся по подписчикам. Схлопывание до последнего значения запрещено, поэтому все дельты сохраняются.
6. **Отправка.** Поток `StateCoalesceFlusher` — единственный отправитель. Раз в тик (≤120 мс) он забирает буфер и шлёт каждому подписчику 1 сообщение `state.changed`.
7. **Начальный снимок.** При подписке `_replay_initial_state` ставит в тот же буфер текущие значения листьев с `source="__replay__"`. Берётся только поддерево статического префикса паттерна.

## single / q4 / ход 1 / rep1 / A (350 слов)

Почему так решили и где это правило проверяется:

## Почему только `dict`

Решение записано в ADR-008 (`multiprocess_framework/DECISIONS.md:262`) и в правиле R-3 (`multiprocess_framework/docs/DESIGN_RULES.md:49`). Причина такая: под Windows дочерние процессы запускаются через `spawn`. Всё, что идёт через `Queue` / `Pipe` / `SharedResourcesManager`, сериализуется через pickle. Pydantic-модели (`BaseModel`, `SchemaBase`) проходят через pickle не всегда. Обычный `dict` сериализуется гарантированно. Внутри процесса Pydantic разрешён. На границе модель превращают в словарь через `to_dict()` / `model_dump()`, а на приёмной стороне собирают обратно через `from_dict()` / `model_validate()`. Тем же правилом R-3 запрещено передавать между процессами лямбды, замыкания и незарегистрированные классы.

## Где проверяется

Единой автоматической проверки нет. Правило держится на нескольких местах, и у каждого своя зона:

| Где | Что делает | Насколько строго |
|---|---|---|
| `shared_resources_module/config_store/config_store.py:34` | `ConfigStore.store()` бросает `TypeError`, если конфиг не `dict` | Жёстко, во время работы |
| `router_module/core/router_manager.py:1929` | `_to_dict()` сам превращает `Message` в `dict` перед отправкой | Не проверяет, а приводит к `dict` |
| `router_module/adapters/schema_adapter.py:111` | регистр-схему перед отправкой превращает в `dict` через `model_dump()` | Не проверяет, а приводит к `dict` |
| `normalize_config()` в `ChannelRoutingManager` (ADR про `channel_routing_module`) | приводит конфиг менеджера к `dict` на входе | Приводит к `dict` (R-19) |
| Тесты: `pickle.dumps(...)` встречается 74 раза в 37 тестовых файлах (например, `message_module/tests/test_message.py`, `shared_resources_module/tests/test_shared_resources_manager.py`) | проверка, что объект переживает pickle | Только для тех типов, на которые тест написан |
| Сводная таблица `DESIGN_RULES.md:290` | для R-3 и R-11 указан способ проверки «`pickle.dumps(payload)` в тесте» | Проверка вручную, через ревью |

## Где правило не закрыто

- `scripts/validate.py` и `sentrux check` R-3 не проверяют. По `DESIGN_RULES.md:309` они следят за структурой модулей и границами слоёв, а не за содержимым сообщений.
- `_to_dict()` превращает в словарь только верхний уровень сообщения. Pydantic-объект, вложенный внутрь payload, судя по коду, пройдёт дальше без проверки, и ошибка вылезет только при pickle в очереди. Это вывод по чтению кода, я его не воспроизводил.

Если нужна настоящая проверка во время работы, её можно поставить в точке отправки роутера: например, проверять на глубину, что в payload нет `BaseModel`, и включать проверку флагом в отладке. Могу подготовить план под это.

## single / q4 / ход 1 / rep1 / B (176 слов)

ADR-008 объясняет правило так: Pydantic-модель не всегда проходит через `multiprocessing.Queue`, а `dict` гарантированно сериализуется через pickle (`multiprocess_framework/DECISIONS.md:262`).

Есть и практические причины, которые ADR не называет. Получателю не нужно импортировать чужие классы схем. Плагины и сервисы не связаны общими моделями. Pydantic по-прежнему используется внутри процесса, на границе данные переводятся через `to_dict`/`from_dict` и `model_dump()`.

Единой проверки во время работы на всех границах нет. Я нашёл только три точечные проверки:

1. `app_module/builder.py:507`, функция `_pickle_sanity`. Она вызывает `pickle.dumps` для результата build-time хуков до spawn и при ошибке бросает `TypeError` с именем хука.
2. `process_manager_module/core/bundle_contract.py:16`. Проверяет только форму bundle: это `dict` с ключами `queues` и `config`. Сериализуемость не проверяется.
3. Тесты. В 37 тестовых файлах 87 вызовов `pickle.dumps/loads`, больше всего в `message_module`, `shared_resources_module` и `router_module`.

При `send_message` и `router.send` проверки нет. Pydantic-объект в payload упадёт только при pickle внутри `Queue`. Линтерного правила или правила sentrux для этого тоже нет. Поиск шёл через `Grep`, потому что qex недоступен: Ollama не запущена.

## single / q4 / ход 1 / rep2 / A (385 слов)

## Почему только `dict`

На Windows дочерние процессы запускаются через `spawn`. Всё, что уходит в `Queue`, `Pipe` или `SharedResourcesManager`, сериализуется через `pickle`. Pydantic-объекты (`BaseModel`, `SchemaBase`, `Message`) так передаются не всегда: мешают замыкания, lambda и незарегистрированные классы. Обычный `dict` из примитивов — единственная форма, которая гарантированно проходит через pickle.

Поэтому граница устроена так:
- **внутри процесса** работают Pydantic-модели с валидацией;
- **на отправке** вызывается `model_dump()` или `to_dict()`;
- **на приёме** объект собирается обратно через `Message.from_dict()` или `model_validate()`.

Где это записано:
- `multiprocess_framework/docs/DESIGN_RULES.md:49` — правило **R-3 «Dict at Boundary»**.
- `multiprocess_framework/modules/message_module/DECISIONS.md:65` — **ADR-MSG-005**: сам объект `Message` намеренно не обязан быть pickle-safe, границу пересекает только `msg.to_dict()`.
- `DESIGN_RULES.md:264` — **R-19**: то же правило для конфигов. Конфиг принимается как `dict | SchemaBase`, внутри менеджера его приводит к рабочей форме `normalize_config()`.

## Где проверяется

Отдельного автоматического сторожа я не нашёл. Правило держится на трёх вещах:

1. **Преобразование в коде отправки.** `RouterManager` принимает `Message | dict` и сам переводит сообщение в `dict` (`router_module/core/router_manager.py:1929`, `_to_dict`). Каналы (`base_channel.py:67`, `interfaces.py:202`) по сигнатуре принимают только `Dict[str, Any]`. Если отправлять через Router, преобразование происходит само.
2. **Точечные тесты на `pickle.dumps`.** В сводной таблице `DESIGN_RULES.md:290` способ проверки R-3 указан как `pickle.dumps(payload)` в тесте. Нашёл такие тесты:
   - `message_module/tests/test_message.py:529` — `test_message_dict_is_pickle_safe`;
   - `process_module/tests/test_types.py:37` и `:92` — `test_pickle_safe`;
   - `app_module/tests/test_state_bootstrap_hazards.py:155` — `test_seed_is_pickle_safe_and_has_no_app_branches`.
3. **Конвенция и ревью.** Остальное держится на дисциплине.

## Что осталось непроверенным

- Я искал `R-3`, `pickle_safe` и `dict_at_boundary` в `scripts/`, тестах модулей фреймворка, `.sentrux/*.toml`, `.github/` и `Makefile`. Ни правила sentrux, ни проверки в `validate.py`, ни шага CI для R-3 там нет. Других имён и мест я не проверял, так что сторож под иным названием формально мог остаться незамеченным.
- **Тесты проверяют конкретные типы, а не границу целиком.** Если кто-то положит Pydantic-объект прямо в `mp.Queue` в обход Router, тест не упадёт. Ошибка проявится только при запуске на Windows в виде `PicklingError` или тихой порчи данных.
- Обход Router напрямую через `Queue` или `SharedResourcesManager` я не искал.

Если нужна настоящая проверка, проще всего добавить `pickle.dumps` в debug-режиме на входе `RouterManager.send` или каналов. Ещё один вариант — контракт-тест, который прогоняет `pickle.dumps` через все зарегистрированные схемы сообщений (`message_module/contracts/registry.py`). Могу оформить задачу, если нужно.

## single / q4 / ход 1 / rep2 / B (176 слов)

Причина в Windows: дочерние процессы стартуют через `spawn`, поэтому всё, что пересекает границу процесса, сериализуется через pickle. По `DESIGN_RULES.md:58`, Pydantic-объекты под `spawn` сериализуются не всегда, а простой `dict` — единственный гарантированно pickle-safe формат. Это правило R-3 в `multiprocess_framework/docs/DESIGN_RULES.md:49`.

**Что R-3 запрещает передавать через `Queue`, `Pipe` и `SharedResourcesManager`:**
- `BaseModel` и `SchemaBase` напрямую;
- lambda и closures;
- незарегистрированные классы.

**Где правило проверяется:**
1. Автоматически сводится к dict только верхний уровень сообщения. `RouterManager._to_dict` (`router_manager.py:1929`) вызывает `message.to_dict()` или `dict(message)`. Через него проходят `send` (стр. 530), фоновая отправка (стр. 526) и `request` (стр. 1064, 1149).
2. Вложенный payload не проверяется: Pydantic-объект внутри `dict` пройдёт этот путь.
3. В сводной таблице (`DESIGN_RULES.md:290`) проверка R-3 — это `pickle.dumps(payload)` в тесте. Такие тесты есть точечно, например `shared_resources_module/tests/test_config_store.py:76`.

Сквозного сторожа R-3 я не нашёл: ни контракт-теста, ни правила sentrux. `scripts/validate.py` я не открывал, поэтому этот вывод не окончательный. qex недоступен, потому что Ollama не запущена; поиск шёл через `Grep`.

## single / q4 / ход 1 / rep3 / A (377 слов)

## Почему только dict

Это **ADR-008 «Dict at Boundary»** (`multiprocess_framework/DECISIONS.md:262`, от 2026-03-11): на границе процессов передаётся `dict`, внутри процесса можно работать с Pydantic.

Причина — механика `multiprocessing`. Всё, что уходит в `Queue`, `Pipe` или `Process(args=...)`, сериализуется через pickle. Начиная с Атлас 0.8b процессы на всех ОС запускаются методом `spawn` (`DESIGN_RULES.md` R-11), поэтому дочерний процесс получает объекты только в сериализованном виде. Простой `dict` из примитивов pickle сериализует всегда. С Pydantic-моделями, lambda, closure, методами экземпляров и динамически созданными классами pickle может не справиться. В R-3 это сформулировано так: «Plain `dict` — единственный гарантированно pickle-safe формат».

Есть и архитектурный плюс: получатель не обязан импортировать класс отправителя. Он сам восстанавливает модель через `Message.from_dict()` / `model_validate()`. Это помогает соблюдать слои импортов. Для конфигов то же правило сформулировано как R-19: на входе `dict | None | SchemaBase`, внутри `normalize_config()`.

## Где проверяется

Отдельного статического гейта, который проверял бы это правило, **нет**. В `scripts/` (`validate.py` и остальное) проверок на pickle или ADR-008 нет, в `.sentrux/rules.toml` тоже. Правило держится на трёх вещах.

1. **Транспорт сам переводит сообщение в dict.** `RouterManager._to_dict` (`multiprocess_framework/modules/router_module/core/router_manager.py:1929`) вызывается на всех путях отправки (строки 526, 530, 1064, 1149). Если пришёл `Message`, вызывается `.to_dict()`, иначе `dict(message)`. Так что `Message` целиком в очередь не попадёт. Но значения **внутри** словаря никто не проверяет: Pydantic-объект в `data` пройдёт до `Queue.put` и упадёт уже там.
2. **Тесты.** `pickle.dumps(...)` встречается 87 раз в 40+ тестовых файлах. Главный тест — `test_message_dict_is_pickle_safe` (`message_module/tests/test_message.py:529`), есть и тесты в `shared_resources_module`, `router_module`, `process_module`. Они проверяют конкретные payload'ы, а не каждую отправку.
3. **Ревью.** В сводной таблице `DESIGN_RULES.md` для R-3 и R-11 указан способ проверки «`pickle.dumps(payload)` в тесте», то есть нарушение ловит человек.

## Что осталось открытым

- Если новый код положит не-pickle-safe объект во вложенное поле сообщения, это всплывёт только в рантайме на `Queue.put`. Ни линтер, ни `validate.py` этого не поймают. Закрыть дыру можно проверкой `pickle.dumps` в `_to_dict` под отладочным флагом либо AST-правилом. Если нужно, оформлю это задачей.
- Я искал через Grep: qex не работает, потому что не запущен Ollama. Возможно, проверка есть где-то в `Services/` или `Plugins/` под другим названием, их я смотрел не полностью.

## single / q4 / ход 1 / rep3 / B (176 слов)

Между процессами передают только `dict`, потому что так решено ради надёжной сериализации через `pickle`. Единой автоматической проверки этого правила нет.

**Почему так решено**
- ADR-008 (`multiprocess_framework/DECISIONS.md:262`): Pydantic-модели не всегда проходят через `multiprocessing.Queue`, а `dict` гарантированно сериализуется через `pickle`.
- R-3 (`multiprocess_framework/docs/DESIGN_RULES.md:49`) уточняет причину: под Windows процессы запускаются через `spawn`. Через границу процесса нельзя передавать `BaseModel`/`SchemaBase`, lambda, замыкания и незарегистрированные классы.
- Внутри процесса Pydantic разрешён. Объект переводят в `dict` через `to_dict()`/`model_dump()` перед отправкой и восстанавливают через `from_dict()`/`model_validate()` после приёма.

**Где проверяется**
- В `DESIGN_RULES.md:290` для R-3 указан способ проверки: вызвать `pickle.dumps(payload)` в тесте. Этот вызов есть в 36 тестовых файлах фреймворка, но каждый проверяет свой конкретный payload.
- В `scripts/validate.py` и `.sentrux/rules.toml` проверки этого правила нет.
- В `router_module` есть проверки `isinstance(..., dict)`, например `router_manager.py:832` и `socket_channel.py:446`. Это защита на стороне приёма, а не запрет при отправке. Путь `send` целиком я не прочитал.

**Что осталось непроверенным:** отклоняет ли `RouterManager.send` значение, которое не является `dict`.

## single / q5 / ход 1 / rep1 / A (502 слов)

## Где создаётся `ProcessManagerProcess`

Явного вызова `ProcessManagerProcess(...)` в коде нет. Класс передаётся строкой (путём к классу), а экземпляр создаётся уже внутри отдельного процесса ОС:

1. **`SystemLauncher.run()` / `.start()`** (`multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:481` и `:510`) вызывает `_create_spawner()` → `ProcessSpawner(...)` (`:357`).
2. **`ProcessSpawner.launch_orchestrator()`** (`launcher/spawner.py:86`) поднимает `multiprocessing.Process(target=run_process_function, args=(orchestrator_class_path, ORCHESTRATOR_PROCESS_NAME, stop_event, bundle, system_stop_event))` и вызывает `.start()` (`:122–140`). Экземпляр класса создаёт `run_process_function` внутри нового процесса.
3. Путь к классу по умолчанию — константа `PROCESS_MANAGER_CLASS_PATH` (`spawner.py:57`). Прототип подменяет его на свой подкласс: `multiprocess_prototype/backend/launch.py:38` → `"multiprocess_prototype.orchestrator.ProcessManagerProcessApp"`, передаётся через `orchestrator_class_path=` (`:735`).

## Порядок запуска

**В главном процессе (`SystemLauncher.run`):**
1. `_prepare_pid_registry()` записывает путь PID-файла в env (`MULTIPROCESS_PID_FILE` / `INSPECTOR_PID_FILE`) и завершает процессы, оставшиеся от прошлого запуска.
2. `_get_processes_config()` собирает конфиг из `add_process()` или из переданного config.
3. `_cleanup_shm_at_startup()` удаляет SHM-сегменты, объявленные в конфиге. Если включён флаг `FW_SHM_PREFIX_CLEANUP`, дополнительно удаляются осиротевшие сегменты по префиксу.
4. `launch_orchestrator()` выполняет по порядку:
   - `setup_multiprocessing()`;
   - `SharedResourcesManager.initialize()`;
   - `ProcessTreeGuard.install()` — на Windows создаётся job, его наследуют дети;
   - спавн процесса оркестратора и `guard.adopt(pid)`.
5. Затем цикл ожидания: `join(0.5)`, плюс проверка `system_stop_event` и Ctrl+C. На выходе вызывается `stop()`.

**В процессе оркестратора (`ProcessManagerProcess.initialize()`, `process/process_manager_process.py:248`):**
1. Регистрация самого PM в shared resources (очереди `HUB_QUEUES`), затем `ProcessModule.initialize()`.
2. Настройка console manager, topology manager, state store и встроенных команд.
3. `_create_processes_from_config()` (`:3344`) — запуск детей в две фазы:
   - **Фаза 1:** для каждого процесса с ключом `class` конфиг сохраняется в `_process_configs`, процесс регистрируется в `shared_resources.register_process`. Так очереди всех детей существуют до старта первого из них.
   - **Фаза 2:** `_plan_boot_waves()` (`:3418`) делит процессы на волны.
     - Если флаг `FW_DEPENDS_ON_BOOT_ORDER` выключен, ни у кого нет `depends_on` или в графе есть цикл, то волна одна, в порядке ключей конфига.
     - Иначе волны строятся топологической сортировкой по `depends_on`. Рёбра на себя и на несуществующие процессы отбрасываются с WARNING.
     - Перед каждой волной, кроме первой, PM ждёт сигнала готовности её реально стартовавших апстримов: `_wait_processes_ready`, таймаут `boot_ready_timeout_s`, по умолчанию 5 с. Если апстрим не готов, волна всё равно стартует, только с WARNING.
   - Каждый процесс запускает `_boot_create_and_start()` (`:3393`): `create_and_register` → `process.start()` → `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются, чтобы в системе не осталось записи о процессе, который так и не появился.
4. Старт `_process_monitor`, регистрация команды `process.command`, канал backend_ctl.
5. `_wait_boot_ready()` — общий барьер: ждёт сигнала готовности от всех запущенных детей. По таймауту всё равно продолжает, с WARNING.
6. `system_ready_event` подключается через `attach_ready_event`, но **взводится только в конце `run()`**, после регистрации BuiltinCommands. Это исправление B-1-1: раньше сигнал готовности приходил до того, как PM мог отвечать на `introspect.*`.
7. В главном процессе `SystemLauncher.wait_until_ready()` (`:520`) ждёт этот сигнал или падения PM.

## Что осталось непроверенным
- Включён ли `FW_DEPENDS_ON_BOOT_ORDER` по умолчанию и задан ли `depends_on` у процессов прототипа, я не смотрел. От этого зависит, одна волна при запуске или несколько.
- Внутренности `run_process_function` и `ProcessRegistry.create_and_register` не читал. Утверждение «экземпляр создаётся внутри дочернего процесса» сделано по сигнатуре вызова.
- qex недоступен (Ollama не запущена), поэтому поиск шёл через Grep. Вызовы через рефлексию в других местах могли не попасть в выборку.

## single / q5 / ход 1 / rep1 / B (205 слов)

`ProcessManagerProcess` создаётся в отдельном OS-процессе. Его запускает `ProcessSpawner.launch_orchestrator()` (`multiprocess_framework/modules/process_manager_module/launcher/spawner.py:86`).

**Порядок запуска**

1. `SystemLauncher.run()` передаёт `ProcessSpawner` путь к классу оркестратора. По умолчанию это `ProcessManagerProcess`, прототип может подменить его подклассом `GenericProcessManagerApp`.
2. `launch_orchestrator()` создаёт `SharedResourcesManager`, ставит `ProcessTreeGuard` и запускает `Process(target=run_process_function)` (`spawner.py:122`).
3. В дочернем процессе `run_process_function` создаёт экземпляр класса и вызывает `initialize()` (`process_manager_process.py:248`). Эту строку я знаю из README, сам код не открывал.
4. `initialize()` выполняет по порядку:
   - регистрирует себя в SRM;
   - поднимает консоль, топологию, StateStore и встроенные команды;
   - вызывает `_create_processes_from_config()` (`:3344`);
   - запускает `process_monitor.start()`.
5. `_create_processes_from_config()` работает в два этапа:
   - регистрирует конфиги всех процессов в SRM;
   - разбивает их на волны по `depends_on` топосортом Kahn (`:3418`). Если флаг `FW_DEPENDS_ON_BOOT_ORDER` выключен, зависимостей нет или есть цикл, волна одна, в порядке dict.
6. Перед каждой волной, кроме первой, оркестратор ждёт готовности её апстримов, до 5,0 с (`boot_ready_timeout_s`). По таймауту он пишет WARNING и всё равно стартует волну.
7. Каждый процесс проходит `create_and_register` → `start()` → `apply_priority` (`:3393`). При сбое создания его конфиг и ресурсы откатываются.

**Что осталось непроверенным**
- README (`README.md:414`) называет первый этап `create_and_register_queues`. В коде на этом этапе вызывается только `register_process`, так что README, вероятно, устарел.
- Код самого `run_process_function` я не открывал.

## single / q5 / ход 1 / rep2 / A (461 слов)

`ProcessManagerProcess` создаётся не через `ProcessManagerProcess(...)`, а по import-path внутри отдельного OS-процесса. Объект появляется уже в дочернем процессе-оркестраторе, когда отрабатывает `run_process_function`.

## Где создаётся

1. **`SystemLauncher.run()` / `.start()`** (`multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:481` и `:510`):
   - `_prepare_pid_registry()` записывает путь PID-файла в env и убивает процессы, оставшиеся от прошлого запуска;
   - `_get_processes_config()` берёт конфиг из `add_process()` или `config` и дополняет его значениями по умолчанию;
   - `_cleanup_shm_at_startup()` убирает зависшие SHM-сегменты;
   - `_create_spawner()` создаёт `ProcessSpawner`, затем вызывается `launch_orchestrator()`.
2. **`ProcessSpawner.launch_orchestrator()`** (`launcher/spawner.py:86`):
   - поднимает `SharedResourcesManager` и `ProcessTreeGuard` (на Windows — Job Object), причём до спавна;
   - собирает bundle: `{"processes_config": ...}` плюс `orchestrator_config`, `shutdown_timeout` и `system_ready_event`;
   - **`Process(target=run_process_function, args=(orchestrator_class_path, ORCHESTRATOR_PROCESS_NAME, stop_event, bundle, system_stop_event))`** (`spawner.py:122`), затем `.start()`;
   - `orchestrator_class_path` по умолчанию равен `PROCESS_MANAGER_CLASS_PATH` (`spawner.py:37`), то есть `ProcessManagerProcess`. Приложение может подставить свой класс.
3. **`run_process_function`** (`runner/process_runner.py:246`) в новом процессе импортирует класс, создаёт экземпляр и вызывает `initialize()` (`:362`), затем `run()` (`:139`).

## Порядок запуска дочерних процессов

**`ProcessManagerProcess.initialize()`** (`process/process_manager_process.py:248`):

1. Регистрирует себя в `shared_resources` и вызывает `super().initialize()` (`ProcessModule`).
2. Настраивает console, topology и state store, регистрирует встроенные команды (`process.*`, `topology.*`, `wire.*`…).
3. Чистит осиротевшие каталоги логов.
4. **`_create_processes_from_config()`** (`:3344`) работает в две фазы:
   - **Фаза A:** для *всех* процессов сохраняет конфиг и вызывает `shared_resources.register_process(name, cfg)`. Очереди всех детей появляются до первого старта, поэтому routing map полна.
   - **Фаза B:** создание и старт идут волнами (`_plan_boot_waves`, `:3418`):
     - если флаг `FW_DEPENDS_ON_BOOT_ORDER` выключен, ни у кого нет `depends_on` или в графе цикл, то волна одна и процессы стартуют **в порядке ключей `processes_config`**;
     - иначе применяется топосорт Kahn (`_compute_boot_waves`). Перед каждой волной, кроме первой, оркестратор ждёт ready от уже запущенных апстримов (`_wait_processes_ready`, таймаут `boot_ready_timeout_s`, по умолчанию 5 с). Если апстрим не готов, выводится WARNING, но волна всё равно стартует.
   - Для каждого процесса `_boot_create_and_start()` (`:3393`) вызывает `create_and_register`, затем `process.start()`, `_mark_instance_started` и `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются, чтобы в реестре не осталось записи без живого процесса.
5. `_process_monitor.start()` запускает супервизию.
6. Регистрируется endpoint `process.command` и при `BACKEND_CTL` — канал `backend_ctl`.
7. **`_wait_boot_ready()`** — barrier: оркестратор ждёт, пока все дети сами сообщат о готовности.
8. Подключается `system_ready_event`. Сам сигнал готовности взводится **в конце `ProcessModule.run()`**, после регистрации встроенных команд (ADR-116). `SystemLauncher.wait_until_ready()` ждёт именно его.

После этого `SystemLauncher.run()` в цикле делает `join(0.5)` и следит за `system_stop_event`, а также за Ctrl+C. По любому из них вызывается `stop()`.

## Что не проверил

- Ollama не запущена, поэтому qex недоступен. Искал через Grep и читал только ключевые участки.
- Не нашёл, где именно прототип создаёт лаунчер (вероятно, через `launcher/builder.py` из `multiprocess_prototype/run.py`): поиск выдал только тесты.
- Не открывал `ProcessRegistry.create_and_register`. Скорее всего, дети тоже запускаются через `run_process_function`, но это не проверено.
- `topology.apply` (выбор рецепта в GUI) запускает процессы другим путём: `apply_topology` → `_topology_start` → `start_process`. Его я не разбирал.

## single / q5 / ход 1 / rep2 / B (168 слов)

ProcessManagerProcess создаётся в `ProcessSpawner.launch_orchestrator()` (`multiprocess_framework/modules/process_manager_module/launcher/spawner.py:122`). Он запускается как `multiprocessing.Process` с функцией `run_process_function`. Путь к классу передаётся строкой. По умолчанию это `PROCESS_MANAGER_CLASS_PATH` (`spawner.py:38`), но его можно заменить через `orchestrator_class_path`.

**Порядок запуска:**

1. `SystemLauncher.run()` / `start()` (`system_launcher.py:481`, `:510`): сброс PID-реестра → очистка SHM → `_create_spawner()` → `launch_orchestrator()`.
2. `launch_orchestrator()`: создаёт `SharedResourcesManager` и ставит `ProcessTreeGuard`. Затем `Process(...).start()` и `guard.adopt(pid)`.
3. `ProcessManagerProcess.initialize()` (`process_manager_process.py:248`) по шагам: console → topology → state_store → команды → `_create_processes_from_config()`.
4. `_create_processes_from_config()` (`:3344`) работает в две фазы:
   - сначала регистрирует очереди всех детей в SRM;
   - затем создаёт и стартует детей волнами `_plan_boot_waves`. Это топологическая сортировка по `depends_on`, она работает при флаге `FW_DEPENDS_ON_BOOT_ORDER`. Без флага все дети стартуют одной волной в порядке конфига.
   - Перед каждой волной оркестратор ждёт сигнала ready от её зависимостей. По таймауту следующая волна всё равно стартует, в лог уходит WARNING.
5. Запускается `_process_monitor`, затем `_wait_boot_ready()` ждёт сигнала ready от всех детей.
6. Готовность системы объявляется в конце `run()` через `attach_ready_event`, уже после регистрации команд.

## single / q5 / ход 1 / rep3 / A (512 слов)

## Где создаётся `ProcessManagerProcess`

Напрямую `ProcessManagerProcess(...)` нигде не вызывается. Оркестратор поднимается в отдельном OS-процессе по пути к классу:

- **`multiprocess_framework/modules/process_manager_module/launcher/spawner.py:122`**: `ProcessSpawner.launch_orchestrator()` создаёт `multiprocessing.Process(target=run_process_function, args=(orchestrator_class_path, ORCHESTRATOR_PROCESS_NAME, stop_event, bundle, system_stop_event))`. Экземпляр класса создаётся уже внутри дочернего процесса, в `run_process_function`.
- Путь по умолчанию задан в `PROCESS_MANAGER_CLASS_PATH` (`spawner.py:37`). Приложение может подставить свой подкласс. Пример — `GenericProcessManagerApp(ProcessManagerProcess)` в `app_module/orchestrator.py:38`.
- Вызывает его `SystemLauncher.run()` (`launcher/system_launcher.py:481`).

## Порядок запуска

**1. `SystemLauncher.run()`** (`system_launcher.py:481`)
1. `_prepare_pid_registry()`
2. `_get_processes_config()`
3. `_cleanup_shm_at_startup()` — убирает осиротевшие SHM-сегменты по префиксам.
4. `_create_spawner()`, затем `launch_orchestrator()`.

**2. `ProcessSpawner.launch_orchestrator()`** (`spawner.py:86`)
1. `setup_multiprocessing()` (spawn).
2. Создаёт `SharedResourcesManager` и вызывает его `initialize()`.
3. `ProcessTreeGuard.install()` вызывается **до** спавна, чтобы дети на Windows унаследовали Job Object.
4. Собирает bundle: `processes_config` + `orchestrator_config` + `system_ready_event`. `system_stop_event` передаётся отдельным аргументом, а не в bundle: сырой `mp.Event` ломается при сериализации на Windows-spawn.
5. `Process.start()`, затем `guard.adopt(pid)`, затем обработчики SIGINT/SIGTERM.

**3. `ProcessManagerProcess.initialize()`** (`process_manager_process.py:248`)
1. Регистрирует себя в shared resources, затем `super().initialize()` (`ProcessModule`).
2. Поднимает console manager, topology manager и state store, регистрирует встроенные команды.
3. Подметает осиротевшие каталоги логов.
4. **`_create_processes_from_config()`** (`:3344`) — запуск детей, см. п. 4.
5. `_process_monitor.start()`.
6. Регистрирует endpoint `process.command` и канал `backend_ctl`.
7. **`_wait_boot_ready()`** (`:4133`) — барьер: ждёт self-reported ready от всех детей.
8. Подключает `system_ready_event` через `attach_ready_event`. Сам сигнал взводится последней строкой `run()`, после регистрации `introspect.*`, поэтому ранний `.set()` убран.

**4. Запуск детей в `_create_processes_from_config()`** идёт в две фазы:
- **Фаза A.** Для каждого процесса с ключом `class` конфиг копируется в `_process_configs`, процесс регистрируется в shared resources (`register_process`). Так очереди и ресурсы появляются у всех раньше, чем стартует первый ребёнок.
- **Фаза B.** Процессы стартуют волнами (`_plan_boot_waves`, `:3418`):
  - Одна плоская волна в порядке ключей `processes_config` получается в любом из случаев: флаг `FW_DEPENDS_ON_BOOT_ORDER` выключен, ни у кого нет `depends_on` или в графе цикл (тогда ERROR в лог).
  - Иначе волны строятся топосортом Кана (`_compute_boot_waves`). Внутри волны сохраняется исходный порядок. Рёбра на себя и на несуществующие процессы отбрасываются с WARNING.
  - Перед каждой волной, кроме первой, PM ждёт ready её апстримов (`_wait_processes_ready`, метка `boot-deps`). Если апстрим не готов, волна всё равно стартует, но в лог пишется WARNING.
  - Для каждого процесса вызывается `_boot_create_and_start()` (`:3393`):
    1. `create_and_register`
    2. регистрация приоритета
    3. `process.start()`
    4. `_mark_instance_started`
    5. `apply_priority`
  - Если создать процесс не удалось, его конфиг и ресурсы откатываются, чтобы не остался «призрак».

**Таймаут.** `boot_ready_timeout_s` (`:3413`), по умолчанию 5.0 с; при `0` ожидание выключено. По таймауту система стартует всё равно, не готовые процессы перечисляются в WARNING.

**5. Готовность системы.** `SystemLauncher.wait_until_ready()` ждёт `system_ready_event` и при этом следит, жив ли PM (`system_launcher.py:524`).

## Что осталось открытым

- qex был недоступен (Ollama не запущен), поэтому искал через `Grep` и читал код.
- `ProcessRegistry.create_and_register` и `run_process_function` я не открывал. Как именно там создаётся `Process` для ребёнка и передаются очереди, описываю по названиям и комментариям, а не по коду.
- Значение флага `FW_DEPENDS_ON_BOOT_ORDER` по умолчанию и заданы ли `depends_on` в регистрах прототипа, я не проверял. От этого зависит, работает ли на деле запуск волнами или всё стартует одной плоской волной.

## single / q5 / ход 1 / rep3 / B (187 слов)

Экземпляр `ProcessManagerProcess` создаётся в отдельном процессе-оркестраторе, внутри `run_process_function`. Родитель передаёт ему только путь к классу.

**Где создаётся**
- `ProcessSpawner.launch_orchestrator()` — `multiprocess_framework/modules/process_manager_module/launcher/spawner.py:86`.
- Сначала он поднимает `SharedResourcesManager` и `ProcessTreeGuard` (Windows job).
- Затем вызывает `Process(target=run_process_function, args=(self._orchestrator_class_path, ORCHESTRATOR_PROCESS_NAME, stop_event, bundle, system_stop_event))` (`spawner.py:122`).
- В дочернем процессе `run_process_function` собирает экземпляр по этому пути и вызывает `initialize()`, затем `run()`.

**Порядок запуска детей** — `_create_processes_from_config`, `process_manager_process.py:3344`:
1. Отбрасываются конфиги без `class`.
2. Для всех процессов вызывается `register_process` (очереди, PSR). Так очереди есть до первого старта.
3. `_plan_boot_waves` делит процессы на волны по топосорту `depends_on`. Это работает при включённом `FW_DEPENDS_ON_BOOT_ORDER`. Иначе, а также при цикле — одна плоская волна в порядке конфига.
4. Перед каждой волной, кроме первой, `_wait_processes_ready` ждёт готовности её апстримов. Если апстрим не готов к таймауту, пишется warning, но волна всё равно стартует.
5. Внутри волны вызывается `_boot_create_and_start` (`:3393`): `create_and_register` → `start()` → `apply_priority`. Если create не удался, конфиг и ресурсы откатываются.

После этого стартует `process_monitor`.

**Не проверял:** какой файл содержит `run_process_function`. В README (`README.md:406`) в `args` указан класс, а в коде передаётся путь к классу, так что README немного устарел.

## single / q6 / ход 1 / rep1 / A (210 слов)

Вот сообщение. Я сверил его с `scripts/run_framework_tests.py`, `multiprocess_framework/modules/pytest.ini` и `pyproject.toml`.

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py            # все
python scripts/run_framework_tests.py base_manager/tests -q   # один модуль, аргументы уходят в pytest как есть
```

Голый `pytest` из корня для этого не подходит. Из корня pytest берёт конфиг из `pyproject.toml`, а у фреймворка конфиг свой, в `multiprocess_framework/modules/pytest.ini`. Отсюда две проблемы:

1. **Запускаются не те тесты.** В `testpaths` корневого конфига из фреймворка есть только `state_store_module`, остальное там про прототип. Около 35 каталогов с тестами модулей (`router_module`, `worker_module`, `shared_resources_module` и т. д.) просто не запустятся. Прогон при этом будет зелёным, и легко поверить, что фреймворк проверен.
2. **Не те настройки.** Не применяются `asyncio_mode = auto` и маркер `legacy_gen1`. Async-тесты без явного `@pytest.mark.asyncio` будут пропущены или упадут, а про маркер pytest будет ругаться.

Скрипт делает одно: запускает pytest с cwd = `multiprocess_framework/modules`, чтобы подхватился нужный `pytest.ini`. Вместо скрипта можно перейти в эту папку и запустить `python -m pytest` вручную, получится то же самое.

---

Если нужно короче, для чата: «Тесты фреймворка гоняй через `python scripts/run_framework_tests.py`. Голый pytest из корня читает `pyproject.toml`: из фреймворка там есть только `state_store_module`, нет `asyncio_mode = auto`. Получишь зелёный прогон, который почти ничего не проверил».

## single / q6 / ход 1 / rep1 / B (147 слов)

Вот сообщение, можно пересылать:

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py
```

Голый `pytest` из корня для этого не подходит. Причина в том, что тестов два набора и у каждого свой конфиг:

1. Из корня pytest читает `[tool.pytest.ini_options]` в `pyproject.toml`. Там из фреймворка указан только `state_store_module/tests`. Тесты остальных модулей (около 35 каталогов) просто не соберутся. При этом прогон будет зелёным, и создастся ложное ощущение, что всё проверено.
2. Полный список каталогов и настройки фреймворка лежат в `multiprocess_framework/modules/pytest.ini`. Там же стоит `asyncio_mode = auto`, а в `pyproject.toml` этой настройки нет. Без неё async-тесты без явного `@pytest.mark.asyncio` не будут работать как задумано.

Скрипт запускает pytest с рабочей папкой `multiprocess_framework/modules`, поэтому подхватывается правильный `pytest.ini`. Аргументы передаются в pytest как есть:

```
python scripts/run_framework_tests.py base_manager/tests -q
```

Если хочешь запускать pytest вручную, сначала перейди в `multiprocess_framework/modules`.

---

## single / q6 / ход 1 / rep2 / A (230 слов)

Готовое сообщение, можно отправлять:

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py
```

Голый `pytest` из корня репозитория для этого не подходит. Без путей он берёт конфиг из корневого `pyproject.toml`, а не из `multiprocess_framework/modules/pytest.ini`. Отсюда две проблемы:

1. **Собирается не тот набор тестов.** В корневом `testpaths` из фреймворка есть только `state_store_module/tests` и `modules/tests`. Тесты остальных модулей (router, process, shared_resources, worker и других, всего около 30 каталогов) не собираются вообще. Прогон выглядит зелёным, но большую часть фреймворка он не проверяет.
2. **Другие настройки.** `asyncio_mode = auto` и маркер `legacy_gen1` заданы только в `modules/pytest.ini`. Без них async-тесты фреймворка работают неправильно.

Скрипт делает простую вещь: запускает `python -m pytest` текущим интерпретатором из каталога `multiprocess_framework/modules`. Поэтому подхватывается нужный `pytest.ini`. Аргументы передаются в pytest без изменений:

```
python scripts/run_framework_tests.py base_manager/tests -q
python scripts/run_framework_tests.py --maxfail=1
```

Можно и вручную: `cd multiprocess_framework/modules && python -m pytest` — результат тот же.

---

Это я проверил по `scripts/run_framework_tests.py`, `modules/pytest.ini` и секции `[tool.pytest.ini_options]` в корневом `pyproject.toml`. Сами тесты не запускал, так что точное число несобранных тестов не называю.

Одна оговорка, которую я в сообщение не включил. Если запустить pytest из корня с явным путём, например `pytest multiprocess_framework/modules/router_module/tests`, он, скорее всего, найдёт ближайший `pytest.ini` и сработает правильно. Проблема именно в запуске без путей. Если нужно, допишу это коллеге.

## single / q6 / ход 1 / rep2 / B (126 слов)

Текст для коллеги, можно вставлять как есть:

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py
```

Голый `pytest` из корня для этого не подходит.

**Почему.** pytest берёт настройки из того `pytest.ini`, который лежит в каталоге запуска.
- Из корня читается `[tool.pytest.ini_options]` в `pyproject.toml`. Из фреймворка там указан один `state_store_module/tests`, остальное — тесты прототипа.
- Настройки фреймворка лежат в `multiprocess_framework/modules/pytest.ini`: 35 каталогов тестов, `asyncio_mode = auto`, `qt_api = pyside6`, маркер `legacy_gen1`.
- Поэтому из корня большая часть тестов фреймворка не запустится. Прогон при этом может быть зелёным, и ошибки никто не увидит.

Скрипт сам переходит в `multiprocess_framework/modules` и передаёт pytest любые аргументы:

```
python scripts/run_framework_tests.py base_manager/tests -q
python scripts/run_framework_tests.py --maxfail=1
```

Можно и вручную: `cd multiprocess_framework/modules && python -m pytest`.

---

## single / q6 / ход 1 / rep3 / A (236 слов)

Вот сообщение. Перед тем как писать, я сверил его с `scripts/run_framework_tests.py`, `multiprocess_framework/modules/pytest.ini` и `pyproject.toml`.

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py            # весь фреймворк
python scripts/run_framework_tests.py base_manager/tests -q   # один модуль, аргументы уходят в pytest как есть
```

Голый `pytest` из корня репозитория не подходит. **У фреймворка свой конфиг pytest:** `multiprocess_framework/modules/pytest.ini`. Если запустить pytest из корня без аргументов, он возьмёт `[tool.pytest.ini_options]` из корневого `pyproject.toml`, и это будет другой прогон:

- **Другой набор тестов.** В `testpaths` корневого конфига из фреймворка только два каталога: `state_store_module/tests` и `modules/tests`. В `modules/pytest.ini` их около 35, по одному на модуль. Остальные тесты фреймворка просто не соберутся, и зелёный результат покажет покрытие, которого нет.
- **Другие настройки.** `asyncio_mode = auto` задан только в `modules/pytest.ini`. Async-тесты без явного `@pytest.mark.asyncio` при запуске из корня не выполнятся как надо. Маркер `legacy_gen1` тоже зарегистрирован только там.

Скрипт ничего хитрого не делает: он запускает `python -m pytest` с `cwd=multiprocess_framework/modules`, и pytest берёт правильный `pytest.ini`. Можно и вручную: `cd multiprocess_framework/modules && python -m pytest`.

---

Чего я не проверял: тесты не запускал, поэтому в сообщении нет числа тестов в каждом варианте прогона. Как именно поведут себя async-тесты из корня (пропуск или предупреждение), зависит от версии pytest-asyncio. Если нужны конкретные цифры для убедительности, могу сделать оба прогона с `--collect-only -q` и добавить их в сообщение.

## single / q6 / ход 1 / rep3 / B (161 слов)

Вот готовое сообщение:

---

Привет! Тесты фреймворка запускай так:

```
python scripts/run_framework_tests.py
```

Голый `pytest` из корня для этого не подходит. Скрипт ничего не добавляет к pytest, он только запускает его из каталога `multiprocess_framework/modules`. Там лежит свой `pytest.ini`, и от этого зависят две вещи:

1. **Набор тестов.** Из корня pytest читает `[tool.pytest.ini_options]` в `pyproject.toml`. Там из фреймворка указаны только `state_store_module/tests` и `modules/tests`. Остальные 33 каталога из `modules/pytest.ini` не соберутся. Прогон будет зелёным, но эти модули он не проверит.
2. **Настройки.** `asyncio_mode = auto` задан только в `modules/pytest.ini`. В корневом конфиге его нет. Async-тесты без явного `@pytest.mark.asyncio` из корня могут не выполниться.

Аргументы скрипт передаёт в pytest без изменений:

```
python scripts/run_framework_tests.py base_manager/tests -q
```

Можно и вручную: `cd multiprocess_framework/modules && python -m pytest`.

---

Пункт 2 я вывел из конфигов и сам не запускал. Если нужна точная цифра, прогоню async-тесты из корня и посмотрю, сколько из них пропущено.

## single / q7 / ход 1 / rep1 / A (560 слов)

## ChainRunnable или DagRunnable

**Коротко:** по умолчанию берите `ChainRunnable`. `DagRunnable` нужен только тогда, когда у операции несколько входов или выходов и данные расходятся по веткам и сливаются через именованные порты. Параллельности `DagRunnable` не даёт.

### Общее у обоих

- Оба реализуют `IRunnableChain.execute(payload, metadata) -> ChainResult` (`core/chain.py:14`).
- Шаги задаются одинаково (`RunnableStep`), контекст тоже общий (`ChainContext` из `camera_id`/`region_id`/`seq_id`).
- Ошибки обрабатываются одной функцией `apply_on_error_policy`. Если политика требует остановки, исполнение прерывается.
- Шаг в другом процессе (cross-process) вызывается через `execute_remote`. Из его ответа в результат попадают только `detections`.

### Различия

| | `ChainRunnable` | `DagRunnable` |
|---|---|---|
| Форма графа | Линия: выход шага N идёт на вход шага N+1 | DAG: ветвление 1→N и слияние N→1 |
| Конструктор | `steps` | `steps` + `topology` (порядок node_id) + `node_inputs` (связи `source`/`output_port`/`input_port`) |
| Как передаются данные | Через одну переменную `current_frame` | Через словарь `port_data[node_id][port]`. Исходный кадр берётся из виртуального источника `"frame"`, порт `"out"` |
| Контракт операции | `execute(frame, ctx) -> frame` | `execute_dag(inputs, ctx) -> dict`, если операция его реализует. Иначе вызывается обычный `execute`, а результат оборачивается в `{"out": ...}` (`dag.py:135`) |
| Что подаётся на вход | Что угодно: `ndarray` или `list[dict]` | Тип объявлен как `np.ndarray`. Если у последней ноды нет порта `"out"`, итоговый кадр ищется среди её выходов как `ndarray` (`dag.py:126`) |
| Шаг упал, политика «продолжить» | Шаг пропускается, следующий получает прежний кадр | Выходы ноды становятся `{}`, и ноды ниже по графу получают на этих портах **`None`** (`dag.py:115`, `dag.py:92`) |
| Шаг в другом процессе | Кадр не меняется | Вход `"in"` передаётся дальше как `"out"` без изменений (`dag.py:107`) |
| Итоговый кадр | Выход последнего шага | Выход **последней ноды в `topology`**. Если у графа несколько конечных нод, результат остальных не попадёт в `result.frame` |
| Где используется | `process_module/generic/pipeline_executor.py:116` и `:362` | В `multiprocess_prototype`, `Plugins`, `Services` и `process_module` вызовов нет, только тесты (`tests/test_dag_runnable.py`) |

### Когда что брать

1. **`ChainRunnable`.** Подходит для любого линейного pipeline, где у каждого шага один вход и один выход. На нём сейчас работает рабочий исполнитель (`pipeline_executor`). Кроме кадров, он прогоняет `list[dict]` из processing-pipeline.
2. **`DagRunnable`.** Нужен, когда у операции действительно несколько портов: например, «кадр + маска → наложение» или сравнение результатов двух веток. Без `execute_dag` операции получают только один вход, так что слияние смысла не имеет. Ноды исполняются **последовательно** в порядке `topology`, ветки идут по очереди.
3. **Если нужно параллельно исполнять независимые ветки,** для этого есть третий исполнитель, `ParallelChainRunnable`: пул потоков и связки из `detect_parallel_bundles` (README модуля, строка 89).

Выбирать исполнитель по форме графа помогают функции `is_nonlinear_graph` и `topological_sort` из `chain_module/graph/`.

### Подводные камни DagRunnable

Учтите их, если будете его использовать:
- Если упала нода, которая сливает ветки, ноды ниже по графу молча получат `None`. Им нужно уметь это обрабатывать.
- Шаг в другом процессе возвращает только детекции и не меняет данные в графе.
- Когда у графа несколько конечных нод, итоговый кадр зависит от того, какая из них стоит в `topology` последней.

Сейчас `DagRunnable` нигде не вызывается. По принципу владельца «FREEZE, не KILL» он остаётся контрактом и не удаляется.

### Что я не проверял

- Код `ParallelChainRunnable` (`core/parallel.py`) и `graph/topology.py` я не читал. Описание `ParallelChainRunnable` взято из README модуля, а точное условие, по которому `is_nonlinear_graph` считает граф нелинейным, не проверено.
- Тесты не запускал. Выводы о `None` на портах после ошибки и о выборе итогового кадра сделаны по чтению кода, без запуска.
- Отсутствие вызовов `DagRunnable` в рабочем коде проверено поиском по `multiprocess_prototype`, `Plugins`, `Services` и `process_module`. Остальные модули фреймворка (кроме тестов) проверены только поиском по прямым вызовам конструкторов.

## single / q7 / ход 1 / rep1 / B (228 слов)

`ChainRunnable` нужен для линейной цепочки, `DagRunnable` — для графа с ветвлениями и слияниями. В боевом коде сейчас работает только `ChainRunnable`.

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Как идут данные | Выход шага N подаётся на вход шага N+1 | Через `port_data`: `{node_id: {port: value}}` |
| Вход | Любой payload: `np.ndarray` или `list[dict]` | `np.ndarray` (так в сигнатуре) |
| Конструктор | `steps` | `steps`, `topology`, `node_inputs` |
| Контракт операции | `execute(frame, ctx)` | `execute_dag(inputs, ctx) → dict`, либо старый `execute`, обёрнутый в `{"out": …}` |
| Ошибка с политикой «continue» | Кадр проходит дальше без изменений | Выходы ноды равны `{}`, у зависимых нод на этих портах `None` |
| Результат | Последний payload | Порт `out` последней ноды в `topology`, иначе первый `ndarray` |
| Кто использует | `process_module/generic/pipeline_executor.py:116` | В production-коде вызовов нет |

**Когда брать `ChainRunnable`:**
- шаги идут строго друг за другом;
- payload — не кадр, например items в processing-pipeline.

**Когда брать `DagRunnable`:**
- нужно ветвление 1→N, например маска и исходный кадр уходят в разные ноды;
- нужно слияние N→1 через именованные порты.

Две ловушки `DagRunnable`:
- `topology` сортирует вызывающий код, сам класс порядок не проверяет.
- Cross-process нода не передаёт свой выход дальше: в `port_data` идёт её вход (`dag.py:107`), а детекции копятся в `result`.

Для независимых веток на пуле потоков есть третий вариант: `ParallelChainRunnable` (`core/parallel.py`).

**Что не проверено:** тесты и `DECISIONS.md` я не читал. Есть ли ADR о судьбе `DagRunnable` (заморожен он или запланирован), не знаю.

## single / q7 / ход 1 / rep2 / A (496 слов)

Сравнил по коду (`core/chain.py`, `core/dag.py`, `graph/topology.py`) и по тому, где оба класса создаются. Тесты не запускал, всё ниже получено чтением кода.

## Коротко

**`ChainRunnable`** подходит для линейной цепочки: шаг N получает выход шага N−1. **`DagRunnable`** нужен для графа с ветвлениями (1→N) или слияниями (N→1) через именованные порты. Какой из них нужен, по задумке определяет `is_nonlinear_graph(nodes)` (`graph/topology.py:62`): `True` значит `DagRunnable`.

## Различия

| | `ChainRunnable` | `DagRunnable` |
|---|---|---|
| Передача данных | одна переменная `current_frame` | словарь `port_data[node_id][port]` |
| Конструктор | `steps` | `steps` + `topology` (порядок нод) + `node_inputs` (связи) |
| Требование к шагу | `step.operation` | ещё `step.node.node_id` |
| Тип входа | любой (`np.ndarray` или `list[dict]`), исполнитель его не разбирает | в сигнатуре `np.ndarray`, запасной выбор итогового кадра ищет `ndarray` (`dag.py:126`) |
| Интерфейс операции | `execute(frame, ctx)` | `execute_dag(inputs, ctx) -> dict`, если операция его реализует, иначе обёртка над `execute` в `{"out": ...}` |
| Ошибка шага, политика «продолжить» | шаг пропускается, следующему уходит прежний `current_frame` | у ноды пустые выходы, ноды ниже по графу получают `None` на этих портах |
| Cross-process шаг | детекции собираются, кадр не меняется | то же; дальше идёт только порт `"in"`, остальные входы теряются (`dag.py:107`) |
| Итог `result.frame` | выход последнего шага | выход **последней ноды в `topology`**, а не заданного стока |
| Параллельность | нет | **тоже нет**: ноды выполняются по очереди в топологическом порядке |

## Когда что использовать

- **`ChainRunnable`** — почти всегда. Сейчас в боевом коде создаётся только он: `process_module/generic/pipeline_executor.py:116` и `:362`. Подходит и для CV-кадров, и для items в processing-pipeline.
- **`DagRunnable`** — когда операции правда нужно несколько входов (например, маска + кадр → merge) или один результат расходится на разные ветки. Если операция работает с несколькими портами, у неё должен быть `execute_dag`. Иначе в обёртку попадёт только `"in"`, `"frame"` или первый попавшийся вход.
- **Ради скорости `DagRunnable` не нужен.** Независимые ветки он не распараллеливает. Для параллельности есть `ParallelChainRunnable` (бандлы + пул).

## Подводные камни `DagRunnable`

1. **У графа несколько стоков, а в `result.frame` попадает только один.** Это выход ноды, которая стоит последней в `topology`. Выходы остальных стоков в итог не попадают, сохраняются только побочные результаты (детекции через `_collect_side_results`).
2. **Порядок нод проверяет вызывающий код.** `DagRunnable` берёт `topology` как есть, циклы и порядок не проверяет. Сортировку делают функции из `graph/topology.py`.
3. **Ноды без входов получают исходный кадр в порт `"in"`** (`dag.py:94`). Значит, каждая нода без связей считается источником.
4. **Нода без `execute_dag` после упавшего соседа выше по графу** получит `None` и вызовет `execute(None, ctx)`. Как операция с этим справится, зависит от неё самой.

## Что осталось непроверенным

- Тесты не запускал. Пункты 1 и 4 из подводных камней я вывел из кода, воспроизведением не подтверждал.
- `DagRunnable(` и `is_nonlinear_graph(` вызываются только в тестах модуля (искал Grep по всему репозиторию, папки `tests` исключил). В боевом коде выбора между двумя исполнителями сейчас нет: `pipeline_executor` всегда собирает `ChainRunnable`. Может, DAG собирается где-то динамически, не через прямой вызов конструктора, но я этого не видел. qex недоступен (Ollama не запущена), поэтому семантический поиск не делал.
- Заморожен ли `DagRunnable` официально, по `STATUS.md` и `docs/MODULE_TIERS.md` я не проверял.

## single / q7 / ход 1 / rep2 / B (166 слов)

Выбор простой: линейная цепочка шагов — `ChainRunnable`, граф с ветвлениями и слияниями — `DagRunnable`.

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Поток данных | выход шага N идёт на вход шага N+1 | через `port_data`: `{node_id: {port: value}}` |
| Вход | любой `payload`: кадр или `list[dict]` | `np.ndarray`, виртуальный источник `"frame"."out"` |
| Топология | порядок списка `steps` | `topology` + `node_inputs` (`source`, `input_port`, `output_port`) |
| Контракт операции | `execute(frame, ctx)` | `execute_dag(inputs, ctx)`; без него — обёртка над `execute` |
| Результат | выход последнего шага | порт `"out"` последней ноды или первый `ndarray` |
| Ошибка ноды | шаг пропускается, кадр не меняется | у ноды пустые выходы, у потребителей на входе `None` |

**Когда что:**
- `ChainRunnable` — обычный pipeline и processing-items. В продакшене создаётся только он: `process_module/generic/pipeline_executor.py:116` и `:362`.
- `DagRunnable` — один кадр нужно разделить на N веток и потом слить. Пример: две маски объединяются в одну. Вне тестов его никто не создаёт.

**Ограничения `DagRunnable`:**
- Cross-process нода пробрасывает `in` на `out` без изменений. Через `port_data` идут только её детекции.
- Принимает только кадр, `list[dict]` он не обработает.

## single / q7 / ход 1 / rep3 / A (484 слов)

## ChainRunnable или DagRunnable

Правило выбора такое: если граф линейный, берите `ChainRunnable`. Если в графе есть ветвление (1→N) или слияние (N→1), нужен `DagRunnable`. Формально это решает `is_nonlinear_graph(nodes)` (`graph/topology.py:62`). Он возвращает `True`, если у какой-то ноды больше одного активного входа или больше одного потребителя.

### Чем они отличаются

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Форма графа | Цепочка A→B→C | Граф с ветвлениями и merge |
| Конструктор | `steps` | `steps` + `topology` (порядок node_id) + `node_inputs` (связи `source/output_port → input_port`) |
| Как передаются данные | Выход шага сразу идёт на вход следующего (`current_frame`) | Через `port_data: {node_id: {port: value}}`. Виртуальный источник `"frame"` отдаёт исходный кадр через порт `"out"` |
| Контракт операции | `execute(frame, ctx) → frame` | `execute_dag(inputs, ctx) → {port: value}`. Если этого метода нет, вызывается старый `execute` с обёрткой `{"out": ...}` (`_execute_dag_default`, `dag.py:135`) |
| Тип payload | Любой (duck-typed): кадр `np.ndarray` или `list[dict]` items | Ориентирован на `np.ndarray`: итоговый кадр берётся из порта `"out"` последней ноды или из первого `ndarray` среди её выходов |
| Ошибка шага | `apply_on_error_policy`: `break` или пропуск шага | То же, но выход упавшей ноды становится `{}`, и её потребители получают на вход `None` |
| Cross-process шаг | Детекции попадают в результат, кадр не меняется | То же; нода пробрасывает дальше свой `in` как `out` |
| Стоимость | Минимальная | Сборка `inputs` для каждой ноды плюс словарь портов |

Общее у обоих: протокол `IRunnableChain.execute(payload, metadata) → ChainResult`, одна и та же `ChainContext`, сбор детекций через `_collect_side_results`. Оба исполняют шаги **последовательно в одном потоке**. Параллельность `DagRunnable` не даёт, она есть только у `ParallelChainRunnable`.

### Когда что брать

- **`ChainRunnable`** подходит для обычного конвейера preprocess → detect → postprocess, где каждый шаг преобразует результат предыдущего. Сюда же относится processing-pipeline на `list[dict]`, потому что `DagRunnable` фактически заточен под кадры.
- **`DagRunnable`** нужен, когда одному шагу требуется несколько входов. Например, маска из одной ветки и исходный кадр из другой, или два детектора на одном кадре со слиянием результатов. Нужны и именованные порты: операция реализует `execute_dag`.
- **`ParallelChainRunnable`** пригодится, если независимые ветки нужно реально выполнять одновременно на пуле (бандлы из `detect_parallel_bundles`).

### Где они используются сейчас

- В продакшене создаётся только `ChainRunnable`, в `process_module/generic/pipeline_executor.py:116` и `:362`.
- `DagRunnable` и `is_nonlinear_graph` нигде не вызываются в продакшене, только в тестах (`test_dag_runnable.py`, `test_topology.py`) и в реэкспортах `__init__`. Автоматический выбор «нелинейный граф → `DagRunnable`» сейчас не подключён. По принципу FREEZE, не KILL, это рабочий, но спящий путь.

### Что осталось открытым и что ненадёжно

- Всё выше получено чтением кода. Тесты я не запускал, поэтому поведение веток с ошибками (что в merge-ноду приходит `None`) описано по исходникам, без проверки запуском.
- qex был недоступен (Ollama выключена), поэтому вызовы я искал через Grep по `*.py` в репозитории. Если где-то `DagRunnable` создаётся через динамический импорт или фабрику по строке, Grep этого не найдёт.
- В `DagRunnable` есть неявная особенность: результатом считается выход последней ноды в `topology`, а не какого-то явно заданного sink. Если у графа несколько листьев, в `result.frame` попадёт только один из них. Если планируете подключать `DagRunnable`, это стоит оформить решением.

## single / q7 / ход 1 / rep3 / B (163 слов)

Если граф линейный, берите `ChainRunnable`. `DagRunnable` нужен только при ветвлении 1→N или слиянии N→1. Какой из них нужен, говорит `is_nonlinear_graph(nodes)` (`graph/topology.py:62`).

| | `ChainRunnable` | `DagRunnable` |
|---|---|---|
| Поток данных | выход шага сразу идёт на вход следующего | словари портов `port_data[node_id][port]` |
| Конструктор | `steps` | `steps`, `topology`, `node_inputs` |
| Вход | любой: кадр или `list[dict]` | `np.ndarray` |
| Контракт операции | `execute(frame, ctx)` | `execute_dag(inputs, ctx) → dict`, иначе запасной вызов `execute` |
| Итоговый кадр | выход последнего шага | порт `out` последней ноды или первый `ndarray` |
| Ошибка шага | шаг пропускается | у ноды пустые порты, потребители получают `None` |

Подводные камни `DagRunnable`:
- Cross-process нода не меняет данные: на выход она отдаёт свой вход `in` (`core/dag.py:107`).
- Если нода не нашлась в `steps`, она молча пропускается (`core/dag.py:79`).

Факт: в рабочем коде `DagRunnable` не вызывается нигде. `pipeline_executor.py:116,362` создаёт только `ChainRunnable`. `is_nonlinear_graph` вызывают только тесты. Значит, DAG — замороженный контракт, его покрывает лишь `test_dag_runnable.py`.

**Что осталось непроверенным:** worktrees я не искал. Тесты не запускал.

## single / q8 / ход 1 / rep1 / A (789 слов)

# Риски pickle в `shared_resources_module`

Ниже то, что видно при чтении кода. Я ничего не запускал и не воспроизводил, поэтому по правилам проекта это предположения, а не подтверждённые дефекты. Пути указаны от `multiprocess_framework/modules/shared_resources_module/`.

## Серьёзность выше средней

**1. В дочернем процессе ошибки логирования могут молча пропадать**
- `core/shared_resources_manager.py:437-447`: `__getattr__` возвращает `_noop` для любого отсутствующего атрибута, имя которого начинается на `_log_`, `_record_` или `_track_`.
- `__getstate__` (`:471-476`) убирает эти атрибуты при pickle.
- Пока логгер в дочернем процессе не подключён заново, вызовы `_log_error`, `_record_*` и `_track_*` ничего не делают.
- Пример: в `reinitialize_in_child()` (`:314-316`) сообщение из `except` уйдёт в `_noop`. Ошибку увидит только тот, кто проверит возвращённый `False`.
- Не проверено, восстанавливает ли `ObservableMixin` эти методы до вызова `reinitialize_in_child`.

**2. Дочерний процесс получает копию состояния, а не общий объект**
- Затронуты `state/process_data.py:245-270` и `state/process_state_registry.py:39-47`.
- `ProcessData` (status, metadata, custom) и весь `ProcessStateRegistry.states` копируются при spawn.
- Если родитель что-то меняет после старта процесса, ребёнок этого не видит. Синхронизируются только сами объекты `Queue`/`Event`.
- `memory/core/manager.py:19` обещает, что данные в `ProcessData.custom` «видны всем процессам». Это верно только для имён SHM, записанных до spawn.
- Сюда же относится смена топологии («routing-epoch»): `clear_queues` (`process_data.py:180-193`) снимает в ребёнке устаревшие ссылки на очереди. Значит, проблема рассинхрона уже возникала.

**3. `ProcessData.custom` сериализуется целиком, что бы в нём ни лежало**
- В `process_data.py:250` `__getstate__` кладёт `custom` как есть.
- `to_dict()` (`:224-229`) фильтрует `stop_event`, `error_manager`, `pause_event` и всё, что не является примитивом. Значит, там действительно бывают сложные объекты.
- Если в `custom` попадёт что-то несериализуемое (менеджер, замыкание, handle), spawn упадёт с `PicklingError`. Падение будет внутри `Process.start()`, далеко от места, где объект положили.
- Если объект сериализуется, ребёнок получит его оторванную копию. Это нарушает правило Dict at Boundary.

**4. EventManager не работает, пока явно не вызван `reinitialize()`**
- `events/core/manager.py:298-303`: после unpickle поля `_event_queue` и `_new_event_event` равны `None`, `_router_manager` тоже `None`.
- `reinitialize_in_child()` вызывается вручную из `ProcessModule.initialize()` (`shared_resources_manager.py:300`).
- Если событие отправить раньше или из потока, запущенного до `initialize()`, будет `AttributeError` на `None` либо событие потеряется.

## Средняя серьёзность

**5. Исключения из pickle заданы чёрными списками, и списки продублированы**
- `_PICKLE_EXCLUDE` в `shared_resources_manager.py:37-55` и `_EXCLUDE` в `events/core/manager.py:272-292` почти совпадают, но поддерживаются вручную.
- Если в `ObservableMixin` появится новый атрибут-замыкание и попадёт только в один список, spawn сломается на Windows. Linux с fork этого не заметит, ошибка проявится только на одной платформе.
- Защита от такого расхождения — контрактный тест: проверять, что в `__dict__` после создания объекта нет несериализуемых значений.

**6. Очередь `mp.Queue` можно передать только при spawn**
- Затронуты `queues/core/reader_gone.py:53-59` и `state/process_data.py`.
- Стандартный `__getstate__` у `mp.Queue` вызывает `assert_spawning`. Поэтому очередь, созданную после старта процесса, нельзя переслать сообщением: будет `RuntimeError`.
- Всё, что меняет состав очередей во время работы (переключение рецепта), зависит от hub-relay и пересоздания процессов.
- `assert_spawning` в модуле не найден, так что это вывод из устройства stdlib, а не из кода проекта.

**7. Если SHM не сработал, кадр уходит через pickle в pipe**
- Затронуты `memory/format/buffer.py:221` и `:297`, а также `DECISIONS.md:534-552`.
- При ошибке записи в SHM кадр сериализуется pickle и идёт через pipe. Это сильно дороже, а внешне выглядит как нормальная работа.
- Такое уже случалось на стенде 2026-09-29: все 15 кадров из 15 ушли этим путём. Сейчас есть счётчик `frame_pickle_fallbacks`. Риск — в том, что за ним никто не следит, а не в отсутствии метрики.

## Безопасность (низкая для текущего развёртывания)

**8. Чтение pickle из IPC позволяет выполнить произвольный код**
- `mp.Queue` и `Pipe` распаковывают pickle без проверки. Если кто-то посторонний может писать в эти каналы, он может выполнить код.
- Сейчас каналы локальные и работают от одного пользователя ОС, поэтому реального вектора атаки нет.
- Риск станет реальным, если появится мост наружу через pickle: сеть, файл или упомянутая в аудитах интеграция с ПЛК по OPC UA.
- `buffers/registry.py:58` пишет на диск JSON, а не pickle. Это хорошо.

## Что я не проверял и в чём не уверен
- Ни один пункт не воспроизведён. Это статическое чтение, вердикт носит рекомендательный характер.
- qex недоступен (Ollama не запущена), поиск шёл через `Grep` только внутри модуля. Где вызывающий код за пределами модуля (`process_module`, `router_module`) пользуется pickle, я не смотрел.
- В пункте 1 не проверено, как `ObservableMixin` заново подключает логгер в дочернем процессе. Это главный кандидат на проверку на живом стенде: сломать `reinitialize_in_child` и посмотреть, появится ли запись в логе.
- `ProcessStateRegistry` сериализует `self._logger` и `self.event_manager` вместе с собой (`process_state_registry.py:41`). Я не проверил, не получает ли ребёнок из-за этого дубликат `EventManager`, отличный от того, что лежит в SRM.

Могу оформить пункты 1, 3 и 5 как задачи с тестами на воспроизведение (`/dev:plan`) или запустить `/dev:security-review` по модулю.

## single / q8 / ход 1 / rep1 / B (281 слов)

Внешнего вектора RCE через `pickle.loads` в модуле я не нашёл. В рабочем коде модуля нет ни одного вызова `pickle.load(s)`. `buffers/registry.py:58` читает файл через `json`. Главные риски касаются надёжности, а не безопасности. Находки получены чтением кода, без воспроизведения, поэтому это рекомендации, а не вердикт.

1. **Правило «Dict at Boundary» здесь не проверяется.** `send_to_queue` (`queues/core/manager.py:269–309`) и `ProcessHandle` (`handles/process_handle.py:54`) кладут в очередь любой объект. `multiprocessing.Queue` сериализует его в фоновом feeder-потоке. Поэтому `put` вернёт `True`, а непиклуемый груз потеряется позже. Похожий случай разбирает тест `tests/test_observability_queue_split.py:168` (`cannot pickle '_thread.lock'`).
2. **`__getstate__` у SRM построен на чёрном списке.** Метод копирует весь `__dict__` и убирает только ключи из `_PICKLE_EXCLUDE` (`core/shared_resources_manager.py:471–476`). Если добавить в SRM поле с lock или замыканием, сломается spawn сразу всех дочерних процессов.
3. **`__setstate__` применяет состояние вслепую.** Он делает `__dict__.update(state)` без проверки версии. Затронуты `core/shared_resources_manager.py:478` и `state/process_data.py:257`.
4. **Состояние теряется молча.** `EventManager.__getstate__` убирает очередь и подписчиков (`events/core/manager.py:270–298`). Без вызова `reinitialize_in_child()` события в дочернем процессе никуда не уходят.
5. **Кадры уходят в pickle-fallback.** Если запись в SHM не удалась, кадр идёт через pipe целиком (`memory/format/buffer.py:221, 297`). До исправления так ушли 15 кадров из 15 (`DECISIONS.md:534`). Такие случаи считает счётчик `frame_pickle_fallbacks`.
6. **Метка ReaderGone держится только на `__getstate__`.** Она должна пережить spawn (`queues/core/reader_gone.py:53`). Тесты на это есть (`tests/test_reader_gone_hazards.py:188`).

**Что осталось открытым и ненадёжным:**
- Поиск охватил только `shared_resources_module`. Модули `router_module` и `Services/` я не проверял.
- Пункт 1 опирается на поведение CPython, а не на прогон теста.

## single / q8 / ход 1 / rep2 / A (637 слов)

Коротко о проделанном: я прошёлся грепом по `shared_resources_module` (без `tests/`) и прочитал места, где объекты сериализуются и восстанавливаются (`__getstate__`/`__setstate__`). Ничего не запускал, поэтому всё ниже — выводы из чтения кода, а не воспроизведения.

## Риски pickle в `shared_resources_module`

**0. Где здесь pickle.** Явных вызовов `pickle.loads`/`dumps` в рабочем коде модуля нет. Pickle работает неявно в двух местах:
- при запуске дочернего процесса через spawn туда целиком передаётся `SharedResourcesManager` (ADR-021);
- каждое `put`/`get` в `mp.Queue` тоже сериализуется через pickle.

Восстановление из pickle исполняет код. Сейчас данные приходят только от своих процессов на этой же машине, так что угроза выполнения чужого кода низкая. Она станет реальной, если байты из сети (PLC, OPC UA, Modbus) когда-нибудь попадут в очередь без преобразования в `dict`. Правило «Dict at Boundary» здесь — единственная защита.

### Находки

| # | Риск | Файл | Уверенность |
|---|------|------|------------|
| 1 | **Список исключений вместо списка разрешённых полей.** `SharedResourcesManager.__getstate__` копирует весь `__dict__` и убирает только поля из `_PICKLE_EXCLUDE`. Если кто-то добавит новое поле с lambda, lock или closure, запуск каждого дочернего процесса упадёт с `PicklingError`. Это противоречит принципу 5 («сбой одного не валит соседей»). | `core/shared_resources_manager.py:37-55`, `:471-476`; та же схема в `events/core/manager.py:270` | прочитано |
| 2 | **Сбой `reinitialize_in_child` может пройти без следа.** После восстановления в дочернем процессе `__getattr__` отдаёт заглушку `_noop` на любые имена `_log_*`, `_record_*`, `_track_*`. Если `_log_error` попадает в эту заглушку, ошибка в `reinitialize_in_child` будет поймана, не залогируется, а метод просто вернёт `False`. | `core/shared_resources_manager.py:302-315`, `:438-447` | **гипотеза**: не проверял, есть ли `_log_error` в самом классе `ObservableMixin` (если есть, до `__getattr__` дело не дойдёт) |
| 3 | **Опечатки маскируются.** Из-за проверки по префиксу вызов вроде `self._log_eror(...)` или `self._record_foo(...)` тихо вернёт `None`, а не `AttributeError`. | `core/shared_resources_manager.py:446` | прочитано |
| 4 | **Состояние внутри процесса теряется и молча восстанавливается.** После unpickle у `EventManager` пусты очередь событий, подписчики и `_router_manager`, у `MemoryManager` пусты `handles`. Всё это возвращается только явным вызовом `reinitialize_in_child()`. Если его забыть, ошибки не будет: события просто перестанут доставляться локальным подписчикам, а SHM не откроется. | `events/core/manager.py:298-303`, `memory/core/manager.py:77`, `:127` | прочитано |
| 5 | **`ProcessData.metadata` и `custom` не проверяются.** В них можно положить что угодно, и оно уедет через spawn. `__setstate__` делает `__dict__.update(state)` без проверки. Объект, который не сериализуется, сломает запуск всех процессов; тяжёлый объект замедлит каждый spawn. | `state/process_data.py:245-262` | прочитано |
| 6 | **Дочерний процесс видит снимок реестра на момент запуска.** Каждый дочерний процесс получает свою копию `ProcessStateRegistry`, а `RLock` пересоздаётся. Общими между процессами остаются только `Queue`/`Event`. Если, например, `custom["memory_names"]` добавлены в родителе после spawn, `reinitialize_handles` их не увидит. | `state/process_state_registry.py:39-47` | **гипотеза** о практическом сценарии |
| 7 | **Зависимость от внутреннего устройства CPython.** `ReaderGoneQueue` упаковывает своё состояние вместе с результатом `super().__getstate__()` от `mp.Queue`, а это непубличная деталь CPython. При обновлении Python сериализация может сломаться. | `queues/core/reader_gone.py:53-59` | прочитано |
| 8 | **Кадры тихо уходят в pickle по pipe.** Если запись кадра в SHM не удалась, кадр передаётся через pickle по pipe. Это видно только по счётчику `frame_pickle_fallbacks`. Такое уже случалось: 15 из 15 mono-кадров ушли этим путём. Риск здесь в пропускной способности и задержке, не в безопасности. | `memory/format/buffer.py:221`, `:297`; `DECISIONS.md:534` | прочитано (инцидент описан в ADR) |
| 9 | **`ConfigStore` безопасен только по договорённости.** Он «pickle-safe без `__getstate__`», пока внутри лежат простые `dict`. Принудительной проверки содержимого нет. | `config_store/config_store.py:22` | **не проверял**, как пишутся значения |

### Что не проверено или ненадёжно
- Пункт 2 — самый важный для эксплуатации, но он не подтверждён. Нужен тест: восстановить SRM в дочернем процессе, сломать `reinitialize_handles` и посмотреть, есть ли запись в логе.
- Код вне модуля не смотрел: место отката кадров в pickle в роутере, вызов `reinitialize_in_child` в `ProcessModule.initialize()`.
- qex не использовал: Ollama не запущена, поэтому искал только грепом.

Если нужно, могу дальше запустить `/dev:security-review` или `reviewer` с задачей воспроизвести пункты 2 и 6.

## single / q8 / ход 1 / rep2 / B (291 слов)

Явного `pickle.loads` в модуле нет. Pickle работает неявно, через spawn и `mp.Queue`. Главные риски — тихая потеря данных и хрупкие ручные списки полей. Ниже находки. Ни одна не проверена запуском.

1. **Тихий noop вместо логов.** `core/shared_resources_manager.py:437-447`: `__getattr__` возвращает `_noop` для любого имени `_log_*`, `_record_*`, `_track_*`. В дочернем процессе логи, метрики и ошибки пропадут без следа. Опечатка в имени метода тоже молча вернёт `_noop`.
2. **Ручной список исключений.** `core/shared_resources_manager.py:37-53`, `_PICKLE_EXCLUDE`: здесь вручную повторены атрибуты `ObservableMixin`. Новое замыкание в mixin, не попавшее в список, сломает spawn с `PicklingError`.
3. **Белый список полей.** `state/process_data.py:245-255`: новое поле `ProcessData`, не внесённое в `__getstate__`, молча пропадёт в дочернем процессе.
4. **Одна запись валит всех.** `ProcessData.custom` — произвольный dict, а SRM pickle-ится целиком. Значение, которое нельзя pickle, сорвёт запуск всех детей. Это нарушает принцип 5. Гипотеза.
5. **Копия выглядит как общая.** `state/process_state_registry.py:39-47`: `RLock` пересоздаётся, и каждый ребёнок получает свою копию реестра. Записи ребёнка родитель не видит.
6. **Обязательный ручной вызов.** Без `reinitialize_in_child()` у `EventManager` останется `_event_queue = None`, а у `MemoryManager` — handles `{}`. Источник: `docs/ARCHITECTURE.md:67`.
7. **Опора на внутренности CPython.** `queues/core/reader_gone.py:53-59` упаковывает приватный `mp.Queue.__getstate__` в кортеж. Обновление Python может это сломать.
8. **Кадр через pipe.** `memory/format/buffer.py:297`: при сбое записи в SHM кадр уходит pickle-fallback через pipe. Это стоит копирования кадра. Форма кадра уже раз зависела от пути доставки (`DECISIONS.md:534`).
9. **Исполнение кода при unpickle.** Каналы только локальные, между своими процессами. Риск низкий, пока очереди не открыты наружу.

**Что осталось открытым / ненадёжным**
- Тесты не запускал, поведение не воспроизводил.
- Пункт 4 — гипотеза.
- Использование `authkey` не проверял.
- Индекс qex недоступен: Ollama выключена. Искал через `Grep`, каталог `tests/` исключил.

## single / q8 / ход 1 / rep3 / A (599 слов)

# Риски pickle в `shared_resources_module`

Проверял только чтением кода и grep. Bash в этой сессии нет, поэтому ни одну находку я не воспроизвёл. По правилам проекта это пока советы, а не вердикт. qex не работал, потому что Ollama выключен.

В рабочем коде модуля нет явных вызовов `pickle.loads`/`dumps`. Объекты сериализуются неявно в двух местах: при `multiprocessing.Queue.put/get` и когда при spawn в дочерний процесс передаётся `SharedResourcesManager`.

## Находки, от самой серьёзной

**1. Если сообщение не сериализуется, оно пропадает, а отправка считается успешной.**
- Где: `queues/core/manager.py:305-309`, `handles/process_handle.py:53-57`.
- Почему: `mp.Queue.put()` не сериализует объект сразу. Это делает фоновый поток очереди позже. Поэтому `PicklingError` не попадает в `except`: `send_to_queue` возвращает `True`, счётчик `errors` не растёт, а traceback уходит в stderr мимо `logger_module`.
- Перехватчика нет: поиск `_on_queue_feeder_error` по `modules/` ничего не нашёл. Переопределить его естественно в `queues/core/reader_gone.py:44` (`ReaderGoneQueue`).
- Последствие той же причины: если изменить объект после `put()`, получатель может увидеть уже изменённое состояние.

**2. Нет проверки, что между процессами идёт только `dict` (правило Dict at Boundary).**
- Где: `send_to_queue(..., message)` и `ProcessHandle.send(message: Any)`.
- Тип сообщения не проверяется, поэтому в очередь можно положить Pydantic-модель, экземпляр класса или numpy-массив. Тогда получатель зависит от того, по какому пути импортируется класс. После переименования или переноса модуля при spawn упадёт уже приём, а не отправка.

**3. Ошибка распаковки на приёме не отличается от пустой очереди.**
- `handles/process_handle.py:67-70`: `except Exception: return None` глотает и `Empty`, и ошибки распаковки, ничего не записывая в лог. Байты из очереди к этому моменту уже вычитаны, так что сообщение потеряно.
- `queues/core/manager.py:383-386` пишет ошибку в лог и увеличивает `errors`, но тоже возвращает `None`. Вызывающий код потерю не видит.

**4. `ProcessData.custom` сериализуется целиком, а `to_dict` его фильтрует.**
- `state/process_data.py:224-229` явно исключает `stop_event`, `error_manager`, `pause_event` и всё, что не является примитивом.
- `__getstate__` в `state/process_data.py:245-255` отдаёт `custom` без фильтра.
- Если в `custom` лежит `error_manager`, spawn либо упадёт, либо дочерний процесс получит копию менеджера, не связанную с оригиналом.

**5. Состояние для передачи собирается вычитанием из `__dict__` по чёрному списку.**
- Где: `core/shared_resources_manager.py:37` (`_PICKLE_EXCLUDE`) и `:471-479`, а также `events/core/manager.py:270-303` (свой отдельный `_EXCLUDE`).
- Новое поле, которое не сериализуется (lock, поток, callback), сломает spawn. Новое поле, которое сериализуется (кэш, dict), молча станет независимой копией в дочернем процессе.
- `__setstate__` у SRM просто делает `__dict__.update`. В отличие от `EventManager` он не восстанавливает исключённые поля. Если дочерний процесс обратится к такому полю, он получит `AttributeError` уже во время работы, а не при старте.
- Два списка исключений почти совпадают, и со временем они разойдутся.

**6. Безопасность: сейчас риск низкий, но при одном условии.**
- Распаковка pickle может выполнить произвольный код. Сейчас канал — это OS pipes внутри дерева процессов одного пользователя. `managers`, `Listener` и `authkey` в модуле не найдены.
- Риск станет критическим, если любую из этих очередей подключат к внешнему источнику, например к мосту OPC-UA/PLC, который обсуждается в `docs/audits/2026-10-08_*`.

## Что осталось открытым или ненадёжным
- Пункты 1 и 3 я вывел из того, как работает `multiprocessing.Queue` в CPython, на стенде не проверял. Проверить их можно так: отправить `send_to_queue(..., lambda: 0)`, ожидать `True` и `errors == 0`.
- Не проверял `ConfigStore` (`config_store/config_store.py:22`): если он хранится как обычные данные, то после spawn дочерний процесс видит снимок, а не общее состояние.
- Не проверял, идут ли кадры через SharedMemory или через pickle. От этого зависит, есть ли у pickle цена по производительности.

Могу запустить `/dev:security-review` или `reviewer`, чтобы воспроизвести пункты 1, 3 и 4 и превратить их из советов в вердикт.

## single / q8 / ход 1 / rep3 / B (313 слов)

Явного `pickle.loads` на внешних данных в модуле нет. Pickle неявный: передача SRM при spawn и `multiprocessing.Queue`. Удалённого RCE в коде модуля я не нашёл. Риски лежат в надёжности, а не во внешней атаке. Все находки получены чтением кода, я их не воспроизводил. Поэтому это советы, а не вердикт.

**Находки**

1. `core/shared_resources_manager.py:446-447` — после unpickle `__getattr__` возвращает `_noop` для любого `_log_*`, `_record_*`, `_track_*`. Логи и метрики могут пропадать без следа. Опечатка вроде `_log_eror` тоже молча ничего не делает. Под угрозой `_log_error` в `reinitialize_in_child` (строка 315): сбой восстановления может остаться невидимым.
2. `core/shared_resources_manager.py:37-55, 471-476` — `__getstate__` исключает поля по чёрному списку `_PICKLE_EXCLUDE`. Новое поле без pickle в `ObservableMixin` сломает spawn. Любое новое поле молча уедет в дочерний процесс.
3. `state/process_data.py:245-255` — `custom` и `metadata` уходят в pickle как есть. Через `adapters/data_schema_adapter.py` там хранятся `ComponentDNA` и manager-модели. Это нарушает Dict at Boundary, а ошибка проявится только при spawn.
4. `state/process_data.py:264-268` — если строка статуса неверна, `__setstate__` молча ставит `INITIALIZING`. Так повреждённые данные маскируются.
5. `state/process_state_registry.py:45-47` — в дочернем процессе создаётся свой `RLock` и копия реестра. Изменения в дочернем процессе другие процессы не видят.
6. `queues/core/manager.py:308` — `put_nowait(message)` принимает любой объект, а читатель его распаковывает. Проверку типа `dict` я не нашёл, но и не искал по всей цепочке.
7. `memory/format/buffer.py:297` — если запись в SHM не удалась, кадр идёт через pickle по pipe. В `DECISIONS.md:534` записан случай: 15 из 15 кадров ушли этим путём. Есть счётчик `frame_pickle_fallbacks`, но тревоги по нему нет.

**Что осталось открытым**
- Находки 1 и 5 не воспроизведены. Для 1 нужен тест: unpickle SRM, затем `srm._log_error(...)`, затем проверка записи в лог.
- Не проверял, переназначает ли `ProcessModule.initialize()` методы логирования до вызова `reinitialize_in_child`.
- Источники сообщений, которые доходят до `put_nowait` в находке 6, не прослежены.
