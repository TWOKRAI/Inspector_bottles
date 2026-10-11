# Ответы для ручной оценки точности

## single / q1 / ход 1 / rep1 / A (300 слов)

`RouterManager` — это единая точка маршрутизации сообщений между процессами. Я прочитал `multiprocess_framework/docs/ROUTING_GLOSSARY.md` и `router_module/README.md`, код не запускал.

## Что делает RouterManager

- В каждом процессе создаётся ровно один `RouterManager`, и наружу процесс общается только через него. Он наследует `ChannelRoutingManager`, а тот наследует `BaseManager` вместе с `ObservableMixin`.
- **Исходящие сообщения.**
  - Есть два входа: `send(msg)` и `send_async(msg, priority)`. Второй кладёт сообщение в `AsyncSender` (`PriorityQueue` с фоновым потоком).
  - Сообщение проходит `MiddlewarePipeline` (функции `fn(msg) -> dict | None`) и попадает в `_resolve_channels(msg)`.
  - Канал выбирается двумя способами. Если задан `msg["channel"]`, это поиск за O(1). Иначе работает `channel_dispatcher` (точное совпадение, паттерн или broadcast).
  - Дальше вызывается `IMessageChannel.send(msg)`. Штатная реализация — `QueueChannel`, которая кладёт сообщение в `queue.put()`. Можно написать свои каналы: сокет, БД и т. п.
- **Входящие сообщения.** `AsyncReceiver` в фоновом потоке опрашивает все каналы (`poll_all`). Сообщение проходит `recv`-middleware, и `message_dispatcher` вызывает callbacks, зарегистрированные через `add_message_callback`.

## Канал Router и имя процесса

В проекте это две разные оси адресации, и их нельзя путать.

| | Имя процесса | Канал Router |
|---|---|---|
| Что это | Кто получатель: `renderer`, `processor` | Физическая привязка к очереди из `shared_resources_module`, ключ в реестре каналов |
| Где задаётся | `Message.targets`, `send_message(target, msg)` | `FieldRouting(channel=...)`, `msg["channel"]`, `QueueChannel(name, queue)` |
| Вид | Имя процесса | Часто `control_*` |

Они не обязаны совпадать. Глоссарий приводит пример: поля регистра `draw` идут в канал `control_draw`. При этом `register_update` из GUI уходит в процесс `renderer`, если так указано в `register_dispatch` или `connection_map`.

Есть и третья ось, не связанная с первыми двумя: имя источника наблюдаемости (поле `module` в записи лога). Оно отвечает на вопрос «чья это запись и куда её писать», а не «кому доставить».

## Что осталось непроверенным

- Не читал `router_manager.py` и не проверял, что README совпадает с кодом (например, порядок `_resolve_channels`).
- Не смотрел, как именно `FrontendRegistersBridge` превращает префикс `control_` в имя процесса. Глоссарий упоминает нормализацию, но детали я не проверял.

## single / q1 / ход 1 / rep1 / C (244 слов)

`RouterManager` — внутрипроцессный диспетчер IPC. Он принимает и отправляет сообщения процесса и доставляет их через очереди из `shared_resources_module`. Код — `multiprocess_framework/modules/router_module/core/router_manager.py:123`. Терминологию описывает `docs/ROUTING_GLOSSARY.md`.

## Что делает `RouterManager`

- **Отправка:** `send` и `send_async` (в файле они на строках 528 и 515) пропускают сообщение через send-middleware и кладут его в канал. Исключение — `RouterSendError`.
- **Запрос-ответ:** `request`, `request_async` и `reply_to_request`. Повторный вход защищён исключением `RouterReentrantRequestError`.
- **Приём:** `receive` и `start_listening` опрашивают очереди, прогоняют сообщения через receive-middleware и вызывают обработчики.
- **Регистрация:**
  - каналы и маршруты — `register_channel`, `register_route`, `register_broadcast_route`;
  - обработчики — `register_message_handler`, `register_worker_handler`, сценарии сообщений.
- **Диагностика:** `get_stats`, `get_shm_stats`, `get_ring_info`, `get_dispatcher_info`.
- **База:** наследует `ChannelRoutingManager` из `channel_routing_module`.

## Канал Router и имя процесса

| | Имя процесса | Канал Router |
|---|---|---|
| Что это | Адрес получателя: `renderer`, `processor` | Ключ очереди в реестре, часто вида `control_*` |
| Где задаётся | Аргумент `target` в `send_message(target, msg)`, поле `Message.targets` | `FieldRouting(channel=...)`, поле `msg["channel"]`, `QueueChannel` |
| Отвечает на вопрос | Какому процессу доставить | В какую очередь положить и кто на неё подписан |

Значения не обязаны совпадать. Пример из глоссария: поля регистра `draw` идут в канал `control_draw`. При этом `register_update` из GUI уходит в процесс `renderer`. Процесс берётся из `register_dispatch` или `connection_map`.

Есть и третья ось, не связанная с первыми двумя: имя источника наблюдаемости (`module`). Оно решает, чья это запись лога и куда её писать. К доставке сообщений оно отношения не имеет.

## Что я не проверял

Тела методов `RouterManager` я не читал: список методов взят из сигнатур. Поведение middleware и порядок обработки в `send`/`receive` по коду не сверял.

## single / q1 / ход 1 / rep1 / D (208 слов)

`RouterManager` — это фасад маршрутизации сообщений внутри одного процесса. Он наследует `ChannelRoutingManager` и собирает вместе `AsyncSender`/`AsyncReceiver`, CRM-каналы, `channel_dispatcher` и `event_dispatcher` (`router_module/core/router_manager.py:123`). Он берёт `Message` или dict, отправляет его по очередям из `shared_resources_module` и вызывает зарегистрированные обработчики у получателя. Ещё у него есть relay в хаб `ProcessManager` (параметр `relay_hub`). Через него пересылается сообщение, которое в этом процессе доставить некому. Это я прочитал только в сигнатуре и комментарии, логику relay не проверял.

**Имя процесса и канал Router — разные оси адресации** (`ROUTING_GLOSSARY.md`):

| | Имя процесса | Канал Router |
|---|---|---|
| Вопрос | Кому доставить | Через какую очередь и к какому обработчику |
| Где задаётся | `targets` в `Message`, аргумент `target` в `send_message(target, msg)` | `FieldRouting(channel=...)`, `msg["channel"]`, `QueueChannel` |
| Пример | `renderer`, `processor` | `control_draw` |
| Где живёт | `message_module` | `router_module`, привязка к очередям из `shared_resources_module` |

Значения двух осей не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`, а `register_update` из GUI может уходить в процесс `renderer`. Это определяют `register_dispatch` или `connection_map`.

Есть и третья ось — имя источника наблюдаемости, поле `module` в записи лога. Она отвечает за порог и приёмники записи, а не за доставку, и с первыми двумя не пересекается.

**Что я оставил открытым:** внутреннюю логику dispatch и relay я не читал, только сигнатуру класса и глоссарий. Индекс qex не проверял: Ollama не запущен.

## single / q1 / ход 1 / rep2 / A (280 слов)

## Что делает RouterManager

`RouterManager` — это фасад маршрутизации внутри одного процесса (`router_module/core/router_manager.py:123`). Он наследует `ChannelRoutingManager`, общую базу каналов. Он занимается IPC-транспортом сообщений:

- **Отправка.** `send_async(msg, priority)` кладёт сообщение в `PriorityQueue` у `AsyncSender`. Фоновый поток прогоняет сообщение через middleware, определяет адресата (resolve) и пишет в очередь из `shared_resources_module`.
- **Приём.** `start_listening()` запускает фоновый `AsyncReceiver`. Он читает входящие очереди и передаёт сообщения диспетчерам.
- **Диспетчеризация.** `channel_dispatcher` и `event_dispatcher` вызывают обработчики. Стратегия по умолчанию — `EXACT_MATCH`.
- **Ретрансляция.** Параметр `relay_hub="ProcessManager"` по умолчанию. Через него, судя по параметру, идут сообщения к процессу без прямой очереди. Эту часть я по коду не проверял.

Транспорт при этом отделён от наблюдаемости. `RouterManager` унаследовал `set_sink_enabled`, но операторской командой его не адресовать. Иначе IPC-канал отключался бы одной командой с пульта.

## Канал Router и имя процесса

Это две разные оси адресации (`ROUTING_GLOSSARY.md`):

| | Имя процесса | Канал Router |
|---|---|---|
| Вопрос | «Какому процессу доставить?» | «В какую очередь и к какому обработчику?» |
| Где задаётся | `Message.targets`, `send_message(target, msg)` | `FieldRouting(channel=...)`, `msg["channel"]`, `QueueChannel` |
| Пример | `renderer`, `processor` | `control_draw` |
| Что это физически | Процесс-воркер | Запись в реестре очередей, на которую подписаны обработчики |

Эти значения не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`. Но `register_update` из GUI может уйти в процесс `renderer`. Это определяют `register_dispatch` или `connection_map`.

Есть и третья ось, не связанная с первыми двумя. Это имя источника наблюдаемости (поле `module` в записи лога). Оно отвечает на вопрос, чья это запись и куда её писать, а не кому доставить сообщение.

## Что осталось открытым

Код `RouterManager` я прочитал по заголовку класса и по README модуля, а не целиком (файл больше 1500 строк). Как именно работает `relay_hub` и как `use_kind_channels` меняет разрешение каналов, я не проверял. Индекс qex не использовал: Ollama не запущена.

## single / q1 / ход 1 / rep2 / C (264 слов)

`RouterManager` — это единая точка маршрутизации сообщений процесса. Каждый процесс создаёт один такой менеджер и общается с остальными только через него. Он наследует `ChannelRoutingManager`, который даёт реестр каналов и диспетчер. Источники: `router_module/README.md`, `docs/ROUTING_GLOSSARY.md`. Код я не запускал.

## Что делает RouterManager

**Исходящие сообщения**
- `send_async(msg, priority)` кладёт сообщение в `AsyncSender` (это `PriorityQueue`).
- `send(msg)` пропускает сообщение через middleware-конвейер.
- Каналы выбирает `_resolve_channels(msg)`. Сначала смотрит `msg["channel"]`: если поле задано, канал берётся поиском за O(1). Иначе `channel_dispatcher` ищет канал по точному имени, шаблону или broadcast.
- Отправку выполняет `IMessageChannel.send(msg)`. Для `QueueChannel` это `queue.put()`. Бывают и свои каналы: сокет, БД.

**Входящие сообщения**
- Фоновый `AsyncReceiver` опрашивает все каналы через `ChannelRegistry.poll_all()`.
- Сообщение проходит recv-middleware.
- Затем `message_dispatcher` вызывает колбэки, зарегистрированные через `add_message_callback`.

## Канал Router и имя процесса

Это две разные оси адресации.

| | Имя процесса | Канал Router |
|---|---|---|
| Где задаётся | `target` в `send_message(target, msg)`, `Message.targets` | `msg["channel"]`, `FieldRouting(channel=...)`, `QueueChannel` |
| Что это | Кому доставить, например `renderer`, `processor` | Ключ в реестре очередей из `shared_resources_module`, часто `control_*` |
| Кто использует | Доставка `register_update` из GUI | `RouterSchemaAdapter`, подписка обработчиков в backend |

Значения не обязаны совпадать. Поля регистра `draw` идут в канал `control_draw`, а `register_update` из GUI при этом может уходить в процесс `renderer`. Это задают `register_dispatch` или `connection_map`.

В глоссарии есть и третья ось: имя источника наблюдаемости, то есть поле `module` в записи лога. Она отвечает на вопрос «чья это запись и куда её писать». С адресацией сообщений она не пересекается.

## Что осталось открытым

- Работу `_resolve_channels` и разбор `target` в `FrontendRegistersBridge` я взял из документации, а не из кода.
- Индекс qex не проверял: Ollama не запущена.

## single / q1 / ход 1 / rep2 / D (286 слов)

`RouterManager` доставляет сообщения между процессами. Имя процесса говорит, кому адресовано сообщение. Канал Router говорит, по какой очереди оно физически пойдёт.

**Что делает `RouterManager`**

Он наследует `ChannelRoutingManager` и живёт в каждом процессе (`router_module/core/router_manager.py:123`). Его методы:

- `send(message)` кладёт сообщение в исходящий конвейер, где работают `AsyncSender` и `channel_dispatcher`. Перед отправкой оно проходит через `MiddlewarePipeline`.
- `receive()` опрашивает входящие очереди через `AsyncReceiver` и передаёт сообщения в `event_dispatcher`.
- `request()` и `request_async()` отправляют запрос и ждут ответ. Синхронный `request()` нельзя вызывать из потока, который сам крутит `receive()`. В этом случае он бросает `RouterReentrantRequestError`. Раньше такой вызов молча висел до таймаута 5 с.
- `register_channel()` регистрирует канал в `ChannelRegistry`.

Сами очереди, события и shared memory дают `shared_resources_module`. Роутер только строит на них маршрутизацию.

**Имя процесса и канал Router**

| | Имя процесса | Канал Router |
|---|---|---|
| Что это | Адресат: `renderer`, `processor` | Ключ очереди в реестре каналов |
| Где задаётся | `Message.targets`, аргумент `send_message(target, …)` | `FieldRouting(channel=…)`, `msg["channel"]` |
| Отвечает на вопрос | Кому доставить | По какой очереди это идёт |

Канал строится так: `channel_name(process, kind)` возвращает `"{process}_{kind}"`, например `renderer_system` или `renderer_data`. Часть `kind` берётся из `command` или `type` сообщения (`resolve_channel_kind` в `routing_table.py:72`). Если тип неизвестен, бросается `UnknownMessageTypeError`, а не молчаливая доставка мимо.

Имя процесса и строка канала не обязаны совпадать. По `ROUTING_GLOSSARY.md`: поля регистра `draw` идут в канал `control_draw`, а `register_update` из GUI при этом уходит в процесс `renderer`. Это задаётся через `register_dispatch` или `connection_map`.

Третья ось адресации — имя источника наблюдаемости (`module` в записи лога). Она не связана ни с процессом, ни с каналом.

**Что осталось открытым / ненадёжным:** я прочитал только начало `router_manager.py` (строки 1–90), сигнатуры методов и глоссарий. Тела `send` и `receive` и поведение при нескольких целях я не проверял. Индекс qex сегодня не использовал: Ollama не запущена.

## single / q2 / ход 1 / rep1 / A (222 слов)

К ярусу **core** относятся **17 модулей** из 27 (по `multiprocess_framework/docs/MODULE_TIERS.md`, который сверяется контракт-тестом `test_module_tiers.py`).

**Список core:**
1. `base_manager`: базовый класс менеджеров, `ObservableMixin`, `BaseAdapter`.
2. `message_module`: `Message` и `MessageAdapter`, единица IPC.
3. `channel_routing_module`: общая база Logger, Error, Router и Stats.
4. `logger_module`: логирование процесса.
5. `error_module`: обработка ошибок процесса.
6. `statistics_module`: счётчики и окна агрегации.
7. `dispatch_module`: ядро диспетчеризации (`EXACT_MATCH`).
8. `command_module`: фасад над dispatch, команды процесса.
9. `router_module`: `AsyncSender` и `AsyncReceiver`, транспорт между процессами.
10. `config_module`: конфиг на границе.
11. `data_schema_module`: `SchemaBase`, `FieldMeta`, `FieldRouting`, `DataConverter`.
12. `shared_resources_module`: PSR, ConfigStore, MemoryManager, QueueRegistry.
13. `process_module`: база дочернего процесса, плагинный рантайм.
14. `process_manager_module`: `SystemLauncher`, `ProcessRegistry`, супервизия.
15. `worker_module`: LOOP/TASK-воркеры.
16. `console_module`: `ConsoleManager` создаётся в каждом процессе. Заморожена только фича God-Mode, сам модуль остаётся core.
17. `chain_module`: ярус пересмотрен с frozen на core, потому что pipeline-движок `ProcessModule` теперь стоит на `ChainRunnable`.

**Остальные 10 модулей** относятся к `optional`: `app_module`, `state_store_module`, `registers_module`, `display_module`, `service_module`, `frontend_module`, `recipe`, `actions_module`, `event_module`, `telemetry_readmodel_module`. Модулей яруса `frozen` нет. Заморожены отдельные фичи внутри живых модулей.

**Что осталось открытым или ненадёжным:**
- Я читал только документ, а не сверял каталоги на диске. Актуальность таблицы держится на контракт-тесте, и я его не запускал.
- Документ обновлён 2026-07-26. Позже могли появиться модули или смениться ярусы.
- Перевод `chain_module` в core в самом документе помечен как требующий переподтверждения владельца.

## single / q2 / ход 1 / rep1 / C (132 слов)

К ярусу **core** относятся **17 модулей**. Источник — `multiprocess_framework/docs/MODULE_TIERS.md`, таблица в строках 23–39 и итог в строке 51: core — 17, optional — 10, frozen — 0.

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

**Что осталось открытым или ненадёжным:**
- Вердикт по `chain_module` в `MODULE_TIERS.md` (§2, строка 65) помечен как **требующий переподтверждения владельцем**. Раньше модуль был `frozen`, после C6(d) его перевели в `core`.
- Я читал только строки, где встречается «core». Остальной документ и соответствие таблицы реальному содержимому `modules/` я не проверял. Контракт-тест, который сверяет таблицу с каталогом, не запускал.
- В `CLAUDE.md` указано 27 модулей, а в таблице 17 + 10 = 27. Это совпадает.

## single / q2 / ход 1 / rep1 / D (175 слов)

К ярусу **core** относятся **17 модулей** из 27. Остальные 10 — `optional`, `frozen` пуст. Источник — `multiprocess_framework/docs/MODULE_TIERS.md`, обновлён 2026-07-26.

| # | Модуль | Роль |
|---|--------|------|
| 1 | `base_manager` | база менеджеров, `ObservableMixin`, `BaseAdapter` |
| 2 | `message_module` | `Message` / `MessageAdapter`, единица IPC |
| 3 | `channel_routing_module` | CRM, общая база Logger/Error/Router/Stats |
| 4 | `logger_module` | логирование процесса |
| 5 | `error_module` | обработка ошибок |
| 6 | `statistics_module` | счётчики и окна агрегации |
| 7 | `dispatch_module` | ядро диспетчеризации (`EXACT_MATCH`) |
| 8 | `command_module` | фасад над dispatch, команды процесса |
| 9 | `router_module` | `AsyncSender` / `AsyncReceiver`, транспорт между процессами |
| 10 | `config_module` | конфиг на границе |
| 11 | `data_schema_module` | `SchemaBase`, `FieldMeta`, `FieldRouting` |
| 12 | `shared_resources_module` | PSR, ConfigStore, MemoryManager, QueueRegistry |
| 13 | `process_module` | база дочернего процесса |
| 14 | `process_manager_module` | `SystemLauncher`, оркестратор |
| 15 | `worker_module` | LOOP/TASK-воркеры |
| 16 | `console_module` | `ConsoleManager` создаётся в каждом процессе |
| 17 | `chain_module` | pipeline-движок `ProcessModule` стоит на `ChainRunnable` |

**Что осталось открытым:** `chain_module` в карте G0 (2026-07-06) был `frozen`. По коду его перевели в `core`, и документ помечает это как «требует переподтверждения владельца». Это решение держится на сверке с кодом, а не на новом вердикте владельца. Я проверял только таблицу в документе, а контракт-тест `test_module_tiers.py` не запускал.

## single / q2 / ход 1 / rep2 / A (261 слов)

К ярусу **core** относятся **17 модулей** из 27 (остальные 10 — `optional`, `frozen` — 0). Данные взяты из `multiprocess_framework/docs/MODULE_TIERS.md`, §1. Это единственный источник ярусов, и его сверяет контракт-тест `modules/tests/test_module_tiers.py`.

Критерий core: без модуля не бутится ни одно приложение на фреймворке. Зависимость может быть прямой или транзитивной.

**Базовые и IPC**
1. `base_manager`: базовый класс менеджеров, `ObservableMixin`, `BaseAdapter`.
2. `message_module`: `Message` и `MessageAdapter`.
3. `channel_routing_module`: общая база Logger, Error, Router и Stats.
4. `router_module`: `AsyncSender` и `AsyncReceiver`.
5. `shared_resources_module`: PSR, ConfigStore, MemoryManager, QueueRegistry.

**Менеджеры процесса**
6. `logger_module`
7. `error_module`
8. `statistics_module`
9. `console_module`: `ConsoleManager` создаётся в каждом процессе. Заморожен только режим God-Mode, сам модуль остаётся core.

**Диспетчеризация и команды**
10. `dispatch_module`: ядро `EXACT_MATCH`. Остальные возможности диспетчера (PATTERN, FALLBACK, CHAIN, ScenarioBuilder) заморожены.
11. `command_module`: тонкий фасад над dispatch.

**Конфиг и схемы**
12. `config_module`
13. `data_schema_module`: `SchemaBase`, `FieldMeta`, `FieldRouting`, `DataConverter`.

**Процессы и исполнение**
14. `process_module`: база `ProcessModule` и плагинный рантайм.
15. `process_manager_module`: `SystemLauncher`, `ProcessRegistry`, супервизия.
16. `worker_module`: LOOP/TASK-воркеры.
17. `chain_module`: в core по коду, но не по исходному вердикту (см. ниже).

**Что оставил открытым или ненадёжным**
- Вердикт по `chain_module` помечен в документе как требующий переподтверждения владельца. GATE G0 (2026-07-06) относил модуль к frozen. После C6(d) (merge `22393392`) pipeline-движок `ProcessModule` стоит на `ChainRunnable`, и по коду модуль стал core.
- Документ обновлён 2026-07-26. Я не проверял, что с тех пор не появились новые модули или смена ярусов. Контракт-тест и каталоги на диске я не запускал и не сверял.
- Для сверки с кодом можно запустить `python scripts/validate.py` или тест `test_module_tiers.py`.

## single / q2 / ход 1 / rep2 / C (130 слов)

К ярусу **core** относятся **17 модулей** из 27 (по `MODULE_TIERS.md`, обновлён 2026-07-26):

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

Остальные 10 модулей — `optional`. Ярус `frozen` на уровне целых модулей пуст.

**Что я оставил открытым или ненадёжным:**
- Я сверил число с таблицей в документе, а не с кодом. Контракт-тест `test_module_tiers.py` проверяет, что каталоги на диске совпадают со строками таблицы, но я его не запускал.
- Перевод `chain_module` из `frozen` в `core` в документе помечен как «требует переподтверждения владельца».
- Документ упоминает будущую перекладку модулей по слоям, после которой имена изменятся. Сейчас имена в таблице актуальны, но список устареет после этой перекладки.

## single / q2 / ход 1 / rep2 / D (111 слов)

К ярусу **core** относятся **17 модулей** из 27 (по `multiprocess_framework/docs/MODULE_TIERS.md`, обновлён 2026-07-26):

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

Остальные 10 модулей имеют ярус optional. Ярус frozen на уровне целых модулей пуст.

**Что осталось открытым или ненадёжным:**
- Я прочитал только таблицу в документе и не сверял её с каталогами на диске. Это делает контракт-тест `modules/tests/test_module_tiers.py`, но я его не запускал.
- Перевод `chain_module` в core (раньше он был frozen) документ сам помечает как требующий переподтверждения владельцем.

## single / q3 / ход 1 / rep1 / A (475 слов)

Доставка идёт в три шага: мутация, матчинг по glob-подпискам, буфер и отправка из одного потока. Индекс qex недоступен (Ollama не запущен), поэтому я читал исходники напрямую.

## Путь изменения

**1. Мутация (`manager/state_store_manager.py:181`).** В `handle_state_set`, `handle_state_merge` и `handle_state_delete` порядок такой:
- middleware `before`;
- `TreeStore.set/merge/delete`, который возвращает `Delta` (`path`, `old_value`, `new_value`, `source`, `revision`);
- middleware `after`;
- `self._dispatcher.dispatch_single(delta)` или `dispatch(deltas)`.

**2. Матчинг (`core/subscription_manager.py`).**
- `SubscriptionManager.match(delta)` делит `delta.path` по `.` на сегменты. Затем он обходит снимок всех подписок, сделанный под `RLock`, а сам матчинг идёт без лока.
- Паттерн разбивается через `_split_pattern` с `lru_cache(256)`.
- `_match_pattern` сравнивает сегменты рекурсивно:
  - `*` совпадает ровно с одним сегментом;
  - `**` поглощает ноль или больше сегментов (пробуются обе ветки);
  - остальные сегменты сравниваются буквально и с учётом регистра.
- Если `delta.source` входит в `sub.exclude_sources`, подписка пропускается. Так процесс не получает эхо своих записей.

**3. Группировка и дедуп (`manager/delta_dispatcher.py:127`).**
- `_match_and_group` собирает `{subscriber: [Delta...]}`.
- Если процесс подписан на пересекающиеся паттерны, например `cameras.0.*` и `cameras.**`, каждая дельта попадает к нему один раз. Дедуп идёт по индексу дельты, порядок сохраняется.
- Матчинг происходит в момент мутации, а не при отправке. Иначе подписчик, появившийся между мутацией и тиком, получил бы чужие дельты из буфера.

**4. Коалесцирование (`delta_dispatcher.py:173`).**
- Дельты копятся в буфере `_buffer[subscriber]` под `_buffer_lock`. Дедупа keep-last нет: он рвал бы непрерывность revision и вызывал resync у клиента.
- Daemon-поток `StateCoalesceFlusher` просыпается каждые 0.12 с или раньше. Раньше его будит `_wake`: при достижении `buffer_cap=200` дельт у подписчика и после `enqueue_replay`.
- `_flush_once` меняет буфер местами под локом и шлёт вне лока.
- Отправляет **только** flusher, а не поток-мутатор. Благодаря этому конверты каждому подписчику идут в строгом порядке: иначе приёмник отбросил бы «устаревший» пакет `[1..cap]`, обогнанный пакетом `[cap+1]`.

**5. Конверт (`_send_state_changed`, строка 339).** Каждому подписчику уходит одно сообщение:
- `command: "state.changed"`, `targets: [subscriber]`, `queue_type: "state"`;
- очередь `{proc}_state` с `drop_oldest`, чтобы всплеск не заглушил системную почту команд;
- в `data` лежат `deltas`, `revision` (максимум в пакете) и `first_revision` (минимум), по ним клиент проверяет непрерывность;
- отправка через `router.send_async`, ошибки логируются и не роняют поток.

## Подписка и начальный снимок

`handle_state_subscribe` (строка 393) регистрирует подписку и вызывает `_replay_initial_state`.
- Реплей берёт только листья, совпавшие с паттерном.
- Снимок строится по поддереву статического префикса паттерна (`_static_prefix`), а не по всему дереву.
- Дельты реплея идут с `source="__replay__"`, `old_value=MISSING` и revision на момент снимка.
- Они уходят через `dispatcher.enqueue_replay` в тот же буфер, то есть тем же единственным отправителем.

## Что осталось открытым

- Я не запускал код и тесты, ответ получен чтением. Тесты по теме: `test_delta_dispatcher.py`, `test_delta_coalescing.py`, `test_subscription_manager.py`.
- Стороны клиента (`StateProxy`: проверка непрерывности по `first_revision`, resync) я не читал.
- `match` перебирает все подписки линейно на каждую дельту, индекса по префиксу нет. При большом числе подписок и частых мутациях это O(подписки × дельты). Замеров не делал.
- Задержка до 120 мс по комментарию в коде принята осознанно (Ф6.3).

## single / q3 / ход 1 / rep1 / C (442 слов)

Дельта сначала матчится по подпискам в момент мутации. Потом она копится в буфере подписчика и уходит одним конвертом `state.changed` из единственного потока-flusher'а.

**Путь дельты**

1. Мутация (`state.set`, `state.merge`, `state.delete`) идёт в `StateStoreManager.handle_state_*`, то есть в `manager/state_store_manager.py:181`, `:220` и `:281`. Сначала отрабатывает middleware, затем `TreeStore` формирует `Delta` (или список дельт для merge).
2. `DeltaDispatcher.dispatch` (`manager/delta_dispatcher.py:99`) вызывает `_match_and_group`. Для каждой дельты `SubscriptionManager.match` (`core/subscription_manager.py:310`) перебирает все подписки и проверяет их по сегментам пути.
3. Матчер `_match_pattern` (`core/subscription_manager.py:66`) работает так:
   - `*` — ровно один сегмент;
   - `**` — ноль или больше сегментов, рекурсивно;
   - остальные сегменты сравниваются буквально.
   - Разбор паттерна кэшируется через `lru_cache`.
   - Если `delta.source` входит в `exclude_sources` подписки, подписка пропускается.
4. Дедупликация идёт по подписчику, по индексу дельты. Если процесс подписан на `cameras.0.*` и `cameras.**`, он получит каждую дельту один раз. Порядок дельт сохраняется.
5. `_buffer_deltas` (`manager/delta_dispatcher.py:173`) добавляет дельты в `_buffer[subscriber]` под локом. Дедупликация keep-last запрещена: она рвёт непрерывность revision и вызывает resync-шторм.
6. Daemon-поток `StateCoalesceFlusher` (`_flusher_loop`, `manager/delta_dispatcher.py:265`) просыпается раз в 0,12 с. Он также просыпается раньше: когда в буфере подписчика набралось 200 дельт, и после реплея. Отправляет он только сам: `_flush_once` подменяет буфер под локом, а отправка идёт вне лока.
7. `_send_state_changed` (`manager/delta_dispatcher.py:339`) собирает конверт:
   - `command: "state.changed"`;
   - `targets: [subscriber]`;
   - `queue_type: "state"` — отдельная очередь с `drop_oldest`, чтобы burst не заглушил системную почту процесса;
   - `data: {deltas, revision (max), first_revision (min)}`.
   - Конверт уходит через `router.send_async`.

**Почему устроено так**

- Матчинг идёт в момент мутации, а не при flush. Иначе подписчик, появившийся между мутацией и тиком, получил бы чужие буферизованные дельты.
- Отправляет один поток. Тогда конверты каждому подписчику идут в строгом порядке. Приёмник отбрасывает устаревший пакет целиком, поэтому переупорядочивание дало бы тихую потерю.
- Задержка доставки — до 120 мс. Это принято осознанно: реагирующих потребителей у `state.changed` нет, все только наблюдают.
- `first_revision` нужен приёмнику для проверки непрерывности. `merge` увеличивает revision на каждый изменившийся лист, и один конверт покрывает диапазон `[first..revision]`.

**Подписка и стартовый снимок**

`handle_state_subscribe` (`manager/state_store_manager.py:393`) регистрирует подписку и сразу вызывает `_replay_initial_state`. Он берёт текущие листья по паттерну и шлёт их новому подписчику как дельты с `source="__replay__"`. Для этого используется поддерево статического префикса (`static_prefix`), а не всё дерево. Реплей идёт через `enqueue_replay` в тот же буфер, то есть через того же единственного отправителя.

**Что осталось открытым / ненадёжным**

- Я не читал приёмную сторону (`proxy/state_proxy.py`): как он применяет конверты и когда запрашивает resync, описано только по комментариям в dispatcher.
- Код не запускал. Всё выше — по чтению исходников, без прогона тестов.
- Индекс qex не использовался (Ollama не запущена), поиск шёл по `Glob`/`Grep`.

## single / q3 / ход 1 / rep1 / D (371 слов)

Доставка идёт в три шага: сервер матчит дельты по подпискам в момент мутации, буферизует их, а клиент повторно фильтрует по своему паттерну. Я читал код `state_store_module`, прогонов не делал.

**1. Подписка** (`manager/state_store_manager.py:393`)
- `handle_state_subscribe` кладёт `(pattern, subscriber, exclude_sources)` в `SubscriptionManager.subscribe`.
- Затем `_replay_initial_state` шлёт новому подписчику снимок текущих листьев, подходящих под паттерн. Читается только поддерево статического префикса, то есть часть паттерна до первого `*` или `**`.
- Реплей получает `source="__replay__"` и идёт через `enqueue_replay`.

**2. Матчинг в момент мутации** (`manager/delta_dispatcher.py:99`)
- Мутации в store зовут `DeltaDispatcher.dispatch` или `dispatch_single`.
- `_match_and_group` для каждой дельты вызывает `SubscriptionManager.match`. Он обходит все подписки и пропускает те, у которых `delta.source` входит в `exclude_sources`.
- Остальные проверяет `_match_pattern` (`core/subscription_manager.py:66`). Это рекурсивное сравнение сегментов по точкам: `*` — ровно один сегмент, `**` — ноль или больше, остальное — точное совпадение. Разбор паттерна кэшируется через `lru_cache`.
- Дельты группируются по имени подписчика. Если подписчик подписан на `cameras.0.*` и на `cameras.**`, каждая дельта придёт ему один раз.
- Матчинг делается сразу, а не при отправке. Иначе подписчик, появившийся между мутацией и отправкой, получил бы чужие буферизованные дельты.

**3. Буфер и flusher** (`delta_dispatcher.py:173`, `:265`)
- Дельты копятся в буфере по подписчикам. Дедуп keep-last запрещён: сохраняются все дельты и их порядок по revision.
- Поток `StateCoalesceFlusher` просыпается раз в 0,12 с и отправляет каждому подписчику один конверт `state.changed`: `deltas`, `revision` (максимум) и `first_revision` (минимум).
- Если в буфере 200 дельт и больше, поток-мутатор будит flusher через `_wake`, но сам не отправляет. Так конверты каждого подписчика уходят из одного потока в одном порядке.
- Конверт идёт по `targets=[subscriber]` в очередь класса `state` с политикой `drop_oldest`. Переполнение клиент лечит resync'ом по разрыву revision.

**4. Приёмник** (`proxy/state_proxy.py:1379`)
- В конверте лежат дельты из всех подписок процесса. `_invoke_callbacks` для каждого callback повторно фильтрует их своим паттерном через тот же `match_pattern`, что и на сервере.
- Callback без подходящих дельт не вызывается.
- Перед этим `_apply_deltas` обновляет кэш. Дельта с `MISSING` удаляет путь и всё поддерево под ним.

**Что осталось открытым:**
- Матчинг линейный: каждая дельта проверяется против каждой подписки, индекса по префиксу нет.
- Задержку ≤120 мс и порядок дельт под нагрузкой я не мерил. Это следует из кода и комментариев в нём.
- Resync по разрыву revision (`state.get_subtree` с `paths`) я не разбирал.

## single / q3 / ход 1 / rep2 / A (537 слов)

`StateStoreManager` сам ничего не рассылает. Он вызывает `DeltaDispatcher`, а тот матчит дельты по подпискам, буферизует их и отправляет раз в тик. Я читал `state_store_manager.py`, `subscription_manager.py`, `delta_dispatcher.py` и `glob_walker.py` из `multiprocess_framework/modules/state_store_module/`. Тесты я не запускал.

## Путь изменения

1. **Мутация.** `handle_state_set`, `handle_state_merge` или `handle_state_delete` прогоняют значение через middleware (`before`/`after`). `TreeStore` возвращает `Delta` (`state_store_manager.py:208-213`, `267-271`, `308-310`). Затем идёт `self._dispatcher.dispatch(deltas)` или `dispatch_single(delta)`.

2. **Матчинг по glob.** Матчинг делается в момент мутации, в `dispatch` (`delta_dispatcher.py:118-122`):
   - `SubscriptionManager.match(delta)` копирует список подписок под `RLock` и перебирает его без лока (`subscription_manager.py:310-341`).
   - Если `delta.source` входит в `exclude_sources` подписки, подписка пропускается.
   - Путь и паттерн режутся по `.`, сравнивает их рекурсивный `_match_pattern`. `*` совпадает ровно с одним сегментом, `**` с нулём или более. Остальные сегменты сравниваются буквально и с учётом регистра. Разбор паттерна кэшируется через `lru_cache(256)`.

3. **Группировка и дедуп.** `_match_and_group` собирает `{subscriber: [Delta…]}` (`delta_dispatcher.py:127-156`). Если процесс подписан на пересекающиеся паттерны, например `cameras.0.*` и `cameras.**`, каждая дельта попадёт к нему один раз, в исходном порядке.

4. **Буфер.** `_buffer_deltas` просто добавляет дельты в буфер подписчика под `_buffer_lock`. Дедупликация «оставить последнее» запрещена: она рвёт непрерывность `revision` и вызывает resync у клиента. Когда в буфере накапливается 200 дельт (`_DEFAULT_BUFFER_CAP`), будится flusher через `_wake`. Сам поток-мутатор при этом ничего не отправляет.

5. **Отправка.** Единственный отправитель — daemon-поток `StateCoalesceFlusher`:
   - Он просыпается раз в 0,12 с или по `_wake`.
   - `_flush_once` меняет буфер местами с пустым под локом, а отправляет уже вне лока.
   - Каждому подписчику уходит один конверт через `router.send_async`. Тип сообщения `event`, команда `state.changed`, `targets=[subscriber]`, очередь класса `"state"` (`drop_oldest`). В `data` лежат `deltas`, `revision` (максимум) и `first_revision` (минимум). Минимум нужен, потому что `merge` увеличивает `revision` на каждый изменившийся лист, и клиент проверяет непрерывность по всему диапазону пакета.

   Поток-отправитель один, чтобы сохранялся порядок конвертов для каждого подписчика. Если бы отправляли сами мутаторы, приёмник мог бы отбросить пакет [1..cap], обогнанный пакетом [cap+1], как устаревший. Это было бы тихой потерей.

## Initial replay при подписке

`handle_state_subscribe` создаёт подписку и вызывает `_replay_initial_state` (`state_store_manager.py:415-426`). Новому подписчику уходит снимок текущих листовых значений, которые подходят под паттерн, с `source="__replay__"`. Чтобы не копировать всё дерево, берётся только поддерево статического префикса паттерна, то есть часть до первого `*` или `**` (`_iter_replay_pairs`, строки 477-533). Реплей кладётся в тот же буфер через `enqueue_replay`, а не отправляется напрямую. Иначе он конкурировал бы с flusher и мог быть отброшен как устаревший.

## Свойства доставки

- Задержка доставки до 120 мс. Это осознанная цена: без коалесцирования GUI захлёбывался (в докстринге указаны 1702 потери за 45 с).
- При аварийном `shutdown`, если flusher завис дольше таймаута 2 с, остаток буфера теряется: финальный дренаж пропускается ради единственного отправителя.
- Подписчик, появившийся между мутацией и тиком, чужих буферизованных дельт не получит: матчинг идёт при мутации, а не при flush.

## Что я оставил открытым или не проверил

- Клиентскую сторону не читал: `StateProxy` (приём `state.changed`, проверка разрыва по `first_revision`/`revision`, resync). Про неё я знаю только по комментариям в серверном коде.
- Не проверял, что `RouterManager` в проде доставляет конверт именно в очередь `{proc}_state`, и поведение при переполнении. Это тоже взято из комментариев.
- Утверждение «единственный отправитель» взято из докстрингов. Я не проверял вызовами, что `_send_state_changed` не вызывается откуда-то ещё.

## single / q3 / ход 1 / rep2 / C (418 слов)

Дельты доставляются в четыре шага: мутация, матчинг по подпискам, буфер на подписчика, один конверт `state.changed` на тик flusher'а. Индекс qex не использовался (Ollama не запущен), я читал код напрямую.

**1. Мутация создаёт `Delta`.**
- `handle_state_set` и `handle_state_delete` вызывают `dispatcher.dispatch_single(delta)`.
- `handle_state_merge` вызывает `dispatcher.dispatch(deltas)`.
- Это происходит после `store.set/merge/delete` и middleware `run_after_*` (`state_store_manager.py:213, 271, 310`).

**2. Матчинг идёт в момент мутации.**
- `DeltaDispatcher._match_and_group` для каждой дельты вызывает `SubscriptionManager.match(delta)` (`delta_dispatcher.py:127`).
- Путь делится на сегменты по `.`. Затем он проверяется против каждой подписки рекурсивным `_match_pattern` (`subscription_manager.py:66`).
- `*` совпадает ровно с одним сегментом. `**` совпадает с нулём или более сегментов. Остальные сегменты сравниваются точно, с учётом регистра.
- Разбор паттерна кэширует `lru_cache(256)` в `_split_pattern`.
- Подписка пропускается, если `delta.source` входит в её `exclude_sources`.
- Матчинг при flush не повторяется. Иначе подписчик, появившийся между мутацией и тиком, получил бы чужие буферизованные дельты.

**3. Группировка и дедуп по подписчику.**
- Если процесс подписан на пересекающиеся паттерны (`cameras.0.*` и `cameras.**`), каждая дельта попадёт к нему один раз. Дедуп идёт по индексу дельты. Порядок дельт сохраняется.
- Дедуп «оставить последнее значение» запрещён. Он рвал бы непрерывность revision и вызывал бы resync у клиента.

**4. Буфер и flusher.**
- Дельты копятся в `_buffer[subscriber]` под `_buffer_lock` (`_buffer_deltas`).
- Daemon-поток `StateCoalesceFlusher` просыпается раз в 0,12 с (`_DEFAULT_FLUSH_INTERVAL_SEC`). Он меняет весь буфер местами под локом и отправляет вне лока.
- Каждому подписчику уходит один конверт `state.changed`. В `data` лежат `deltas`, `revision` (максимум по пакету) и `first_revision` (минимум). По ним клиент проверяет непрерывность revision.
- Если в буфере подписчика накопилось 200 дельт (`_DEFAULT_BUFFER_CAP`), flusher будится досрочно через `_wake`. Мутирующий поток при этом сам ничего не отправляет.
- Отправлять может только flusher. Так порядок конвертов на подписчика остаётся строгим: приёмник отбрасывает целиком пакет, который считает устаревшим.
- Конверт уходит через `router.send_async` в очередь `{subscriber}_state` (класс `state`, политика `drop_oldest`). Burst `state.set` не забивает системную почту подписчика. Переполнение очереди клиент увидит как разрыв revision и сделает resync.

**Initial replay.**
- При `state.subscribe` менеджер читает текущие листовые значения по паттерну. Читается только поддерево статического префикса, то есть сегментов до первого `*`/`**` (`_iter_replay_pairs`).
- Дельты реплея получают `source="__replay__"` и revision снимка.
- Реплей идёт через `enqueue_replay` в тот же буфер, а не напрямую. Он ложится после накопленных дельт, и flusher будится сразу.

**Что остаётся открытым.**
- Доставка отложена до 120 мс. Это осознанная цена, описана в докстринге модуля.
- Если flusher завис и `stop_flusher` не дождался join за 2 с, финальный дренаж буфера пропускается. Хвост дельт теряется ради порядка.
- Клиентскую сторону (`StateProxy.state.changed`, проверка `first_revision`, resync) я не читал.

## single / q3 / ход 1 / rep2 / D (381 слов)

StateStoreManager не рассылает дельты сразу. Он матчит их по glob-паттернам в момент мутации, складывает в буфер каждого подписчика, и отдельный поток отправляет буфер одним конвертом `state.changed`.

**1. Подписка.** Команда `state.subscribe` с `{pattern, subscriber, exclude_sources}` попадает в `handle_state_subscribe` (`state_store_manager.py:393`). Он вызывает `SubscriptionManager.subscribe()`, который кладёт `Subscription` в реестр под `RLock`. Сразу после этого `_replay_initial_state` ставит новому подписчику снимок текущих листьев, подходящих под паттерн, с `source="__replay__"`.

**2. Мутация.** `handle_state_set`, `handle_state_merge` и `handle_state_delete` меняют `TreeStore`, получают `Delta` и вызывают `DeltaDispatcher.dispatch()`.

**3. Матчинг** (`subscription_manager.py:310`, `_match_pattern`).
- Путь дельты делится по `.`, паттерн берётся из кэша `lru_cache`.
- `*` совпадает ровно с одним сегментом, `**` — с нулём или несколькими, остальные сегменты совпадают буквально.
- Если `delta.source` есть в `exclude_sources` подписки, она пропускается.
- Реестр копируется под локом, а сопоставление идёт уже без лока.
- Перебираются все подписки подряд, индекса по префиксу нет.

**4. Группировка** (`delta_dispatcher.py:127`, `_match_and_group`).
- Дельты группируются по имени подписчика.
- Если у подписчика совпали две подписки (`cameras.0.*` и `cameras.**`), дельта попадёт к нему один раз. Дедуп идёт по индексу дельты в пачке.
- Порядок дельт сохраняется.

**5. Буфер** (`_buffer_deltas`, строка 173).
- Дельты добавляются в `_buffer[subscriber]` под `_buffer_lock`.
- Схлопывание по ключу «оставить последнее» запрещено: оно рвёт непрерывность revision и вызывает resync-шторм.
- Если в буфере набралось 200 дельт, мутирующий поток только будит flusher через `_wake.set()` и сам ничего не отправляет.

**6. Отправка** (`_flusher_loop`, строка 265).
- Daemon-поток `StateCoalesceFlusher` просыпается каждые 0,12 с или по `_wake`.
- `_flush_once` под локом меняет буфер на пустой, затем вне лока для каждого подписчика вызывает `_send_state_changed`.
- Отправителей конвертов ровно один, поэтому порядок конвертов для подписчика не нарушается.
- Конверт: `command="state.changed"`, `targets=[subscriber]`, `queue_type="state"`. В `data` лежат `deltas`, `revision` (максимум) и `first_revision` (минимум).
- Уходит он через `router.send_async` в очередь `{subscriber}_state` с политикой `drop_oldest`. При переполнении очереди клиент замечает разрыв revision и делает resync через `state.get_subtree`.

Задержка доставки — до 120 мс, реплей новому подписчику будит flusher сразу (`enqueue_replay`). При `shutdown` буфер дренируется финальным `_flush_once`. Если flusher завис и не завершился за 2 с, дренаж пропускается, и хвост дельт теряется.

**Что осталось открытым / ненадёжно**
- Клиентскую сторону (`StateProxy`, применение конвертов и проверка непрерывности revision) я не читал. Её описание выше взято из комментариев диспетчера.
- Живой стенд не запускал, поведение подтверждено только чтением кода. qex недоступен: Ollama выключен, поэтому поиск шёл через `Glob` и `Read`.

## single / q4 / ход 1 / rep1 / A (402 слов)

## Почему только `dict`

Правило записано в `multiprocess_framework/DECISIONS.md` (ADR-008, 2026-03-11) и в `multiprocess_framework/docs/DESIGN_RULES.md` (R-3).

- **Причина из ADR-008.** Pydantic-модели не всегда сериализуются для `multiprocessing.Queue`, а `dict` гарантированно pickle-able. `DESIGN_RULES.md` уточняет: Pydantic-объекты не всегда проходят pickle под Windows `spawn`, поэтому plain `dict` — единственный гарантированно pickle-safe формат.
- **Что решили.** На границе процессов идёт `dict`, внутри процесса Pydantic допустим. Вариант «Pydantic везде» отклонили из-за проблем с сериализацией.
- **Как это выглядит в коде.** Отправитель вызывает `msg.to_dict()` или `model_dump()`, получатель — `Message.from_dict()` или `model_validate()`. Это зафиксировано в docstring `message_module/interfaces.py`.
- **Что запрещено по R-3.** В `Queue`, `Pipe` и `SharedResourcesManager` нельзя класть:
  - `BaseModel` и `SchemaBase` напрямую;
  - lambdas, closures и закрытые методы;
  - незарегистрированные классы.
- **Связанное правило R-19.** Конфиг на границе принимается как `dict | None | SchemaBase`. Внутри менеджера `normalize_config()` приводит его к runtime-форме.

## Где проверяется

Единого автоматического чекера «в очередь ушёл не dict» я не нашёл. Проверка складывается из трёх слоёв:

1. **Тесты с `pickle.dumps`.** Это способ проверки, который указан в R-3 (`pickle.dumps(payload)` должен работать без ошибок). Такие вызовы нашлись в тестах десятков модулей. Например, `message_module/tests/test_message.py:517–586` проверяет pickle-roundtrip для `Message` и результата `to_dict()`. Ещё они есть в `shared_resources_module`, `router_module`, `base_manager`, `channel_routing_module`, `app_module`.
2. **Ревью.** В сводной таблице `DESIGN_RULES.md` для R-3 указан только `pickle.dumps` в тесте. Для соседних правил (R-4, R-6, R-7) там прямо написано «ревью».
3. **Соседний чекер: `scripts/transport_boundary/transport_boundary.py`.** Он проверяет другое: прямые вызовы транспорта (`send_to_queue`, `broadcast_message`, `RingBufferWriter` и т.п.) допустимы только внутри `router_module/**` и `shared_resources_module/**`. Он работает по AST в ratchet-режиме: старые нарушения помечены как `KNOWN DEBT`, новые роняют CI. Запускается из `scripts/ci.py:122`. Формат payload он не проверяет. Но он держит в одном месте точки, через которые payload уходит в очередь.

## Что осталось открытым

- Я не запускал ни тесты, ни `scripts/ci.py`. Вывод про отсутствие единого чекера сделан по `Grep`, а не по прогону.
- Результаты `Grep` в нескольких поисках были обрезаны `head_limit` (40 и 20 файлов). Возможно, я не увидел отдельный контракт-тест или правило в `.sentrux/rules.toml`. Могу проверить точечно.
- qex недоступен: Ollama не запущен, поэтому семантического поиска не было, только `Grep`.
- Нужно ли создавать чекер, решаете вы. Он мог бы искать по AST `BaseModel`/`SchemaBase` в аргументах `put`/`send`. Для такого чекера логично взять за образец `transport_boundary.py` с ratchet-режимом.

## single / q4 / ход 1 / rep1 / C (246 слов)

**Почему только dict.** Это ADR-008 (2026-03-11, `multiprocess_framework/DECISIONS.md:262`). Данные между процессами идут через `multiprocessing.Queue`, то есть через pickle. По ADR, Pydantic-модели не всегда сериализуются для такой очереди, а dict гарантированно pickle-able. Поэтому на границе процессов остаётся `dict` (`to_dict`/`from_dict`), а внутри процесса Pydantic допустим. Альтернатива «Pydantic везде» отклонена из-за проблем с сериализацией. Родственные решения: ADR-019 (SharedMemory передаётся по именам, pickle-safe) и ADR-020 (`reinitialize_in_child()` восстанавливает состояние после unpickle).

**Где правило проверяется.**
- **Автоматически, на уровне свойства.** Такие проверки лежат в `multiprocess_framework/modules/message_module/tests/test_message.py`, например `test_message_dict_is_pickle_safe` (строка 529) и pickle-roundtrip для `Message` (строки 514–564). Аналогичные pickle-тесты есть в `shared_resources_module/tests`, `process_module/tests`, `router_module/tests`. Они проверяют, что конкретные объекты выдерживают pickle.
- **Автоматически, на уровне транспорта.** `scripts/transport_boundary/transport_boundary.py` запускается из `scripts/ci.py:122`. Он ловит прямые вызовы `send_to_queue`, `broadcast_message` и SHM-примитивов вне `router_module/**` и `shared_resources_module/**` через AST. Это соседний инвариант (отправка только через `router.send`), а не сама проверка «в сообщении dict».
- **Вручную, в ревью.** Правило записано в `.claude/skills/project-rules/SKILL.md` и в промптах `developer`, `teamlead`, `reviewer`. Проверяет его ревьюер.

**Что осталось открытым.** Я не нашёл автоматической проверки вида «в `send_message` ушёл не-dict». Ни `.sentrux/rules.toml` (совпадений на `pickle`/`dict` нет), ни `scripts/validate.py` такого не делают. Я искал по ключевым словам и не читал `validate.py` целиком, поэтому проверки под другим названием не исключены. Индекс qex не использовался: Ollama не запущен.

## single / q4 / ход 1 / rep1 / D (233 слов)

**Почему dict.** На Windows процессы создаются через `spawn`: каждый объект в `Queue`, `Pipe` или `SharedResourcesManager` сериализуется pickle и заново собирается в дочернем процессе. Pydantic-объекты при этом не всегда pickle-safe. Простой `dict` pickle-safe всегда. Это записано в ADR-008 (`multiprocess_framework/DECISIONS.md:262`, 2026-03-11) и в правиле R-3 (`multiprocess_framework/docs/DESIGN_RULES.md:49`).

Внутри процесса Pydantic разрешён. На границе работает пара `to_dict()` / `model_dump()` на отправке и `Message.from_dict()` / `model_validate()` на приёме. Запрещено класть в очередь `BaseModel`/`SchemaBase`, lambdas, closures и незарегистрированные классы.

**Где проверяется.**
- **Тесты:** `DESIGN_RULES.md` называет проверкой `pickle.dumps(payload)` в тесте. Такие вызовы есть в `message_module/tests/test_message.py` (строки 517–586): `Message` и его `dict`-форма проходят round-trip через pickle.
- **Ревью:** общего автоматического сторожа я не нашёл. Таблица в `DESIGN_RULES.md:290` даёт R-3 только эту pickle-проверку, а для R-6 (канал ≠ имя процесса) прямо пишет «ревью».
- **`.sentrux/rules.toml`:** про dict там ничего нет. Он держит только границы слоёв импортов.

**Что осталось открытым или ненадёжным.**
- Я не запускал тесты. Что они зелёные, не проверено.
- Проверка идёт только на уровне `Message` в `message_module`. Что любой путь в очередь проходит через `Message`/`to_dict()`, я не доказал. Прямой `queue.put(obj)` в обход `MessageAdapter` эта проверка не поймает.
- Файлы тестов `process_manager_module` (`test_system_launcher.py`, `test_t59a_review_author.py`) и `process_module` попали в поиск по «dict boundary», но я их не открывал. Возможно, часть проверок лежит там.

## single / q4 / ход 1 / rep2 / A (342 слов)

## Почему только `dict`

Решение записано как **ADR-008** (2026-03-11) в `multiprocess_framework/DECISIONS.md:262`. Причины такие:

- Между процессами данные идут через `multiprocessing.Queue`, `Pipe` и `SharedResourcesManager`. Всё это pickle'ится.
- ADR говорит, что Pydantic-модели «не всегда сериализуются», а `dict` pickle-safe гарантированно.
- `docs/DESIGN_RULES.md` (R-3) уточняет причину: под **Windows spawn** дочерний процесс заново импортирует классы. Pydantic-объект, lambda, closure или незарегистрированный класс могут не восстановиться на приёмной стороне.
- Внутри процесса Pydantic разрешён. Конфиг на границе принимается как `dict | None | SchemaBase`, а внутри менеджера `normalize_config()` приводит его к рабочей форме (R-19).

Цикл такой: `Message.to_dict()` или `model_dump()` на отправке и `Message.from_dict()` или `model_validate()` на приёме.

## Где это проверяется

Единого автоматического гейта я не нашёл. Проверка точечная:

| Что | Где |
|---|---|
| Описание проверки | `DESIGN_RULES.md`, R-3 и R-11: `pickle.dumps(payload)` должен проходить без ошибок |
| Реальные проверки | тесты в модулях вызывают `pickle.dumps`: 74 вхождения в 37 файлах. Например, `message_module/tests/test_message.py` (6), `router_module/tests/test_claim_check_*`, `process_module/tests/test_claim_check_any_key_receive.py`, `shared_resources_module/tests/test_handles.py` |
| Просмотр контрактов | `/message-contracts` выводит классы `Message`, `SchemaBase` и `BaseModel` с полями, то есть что реально идёт через границу |
| Ревью | для R-6 и R-7 в таблице стоит «ревью», для R-3 сказано только про pickle-тест |

`.sentrux/rules.toml` это правило **не** проверяет. Там только границы слоёв импортов. `python scripts/validate.py` проверяет структуру и дрейф документации, про `dict` в нём ничего нет.

## Что осталось открытым или ненадёжным

- Я нашёл тесты по ключевым словам, но не проверял, что они покрывают **все** точки отправки в очередь. Автоматического сторожа вроде «никто не кладёт `BaseModel` в `Queue`» я не нашёл.
- Из ADR-008 и R-3 видно, что формулировки причины слегка расходятся: «не всегда сериализуются» и «Windows spawn». Конкретного воспроизведённого случая я не видел. Если он нужен, его надо искать в git log или в `docs/claude/memory/`.
- Индекс qex сегодня недоступен (Ollama не запущен). Поэтому я искал только через `Grep`, без семантического поиска.

Хотите, найду все места, где в очередь кладут что-то кроме `dict`, и проверю, есть ли дыры в покрытии?

## single / q4 / ход 1 / rep2 / C (301 слов)

**Почему только dict.** Это ADR-008 (2026-03-11, `multiprocess_framework/DECISIONS.md:262`). Pydantic-модели не всегда сериализуются через `multiprocessing.Queue`, а dict гарантированно pickle-safe. Поэтому граница процесса несёт `dict`, получаемый через `to_dict()` или `model_dump()`. Внутри процесса Pydantic остаётся. На приёмной стороне вызывают `Message.from_dict()` или `model_validate()`. Эта же идея лежит в основе правила R-19: конфиг на границе принимается как `dict | None | SchemaBase`.

**Где это записано.**
- Правило R-3 в `multiprocess_framework/docs/DESIGN_RULES.md:49`. Оно запрещает класть в `Queue`, `Pipe` и `SharedResourcesManager` объекты `BaseModel` и `SchemaBase`, lambdas, closures и незарегистрированные классы.
- Правило 1 в корневом `CLAUDE.md`.
- Докстринг `message_module/interfaces.py:10`.

**Где это проверяется.** Единой автоматической проверки правила нет.
- Таблица в `DESIGN_RULES.md:290` задаёт проверку для R-3: `pickle.dumps(payload)` в тесте.
- В `multiprocess_framework/modules/*/tests/` я нашёл 74 вызова `pickle.dumps` в 37 файлах (первые 15 файлов из выдачи). Пример: `process_module/tests/test_claim_check_any_key_receive.py`, `test_types.py`. Каждый такой тест проверяет свой payload. Они не ловят нового отправителя, который положил в очередь объект.
- Для R-6 (канал ≠ имя процесса) таблица называет ревью и `ipc-routing-checker` «если есть». Для R-3 такой инструмент не указан.
- `scripts/message_contracts/message_contracts.py` (скилл `/message-contracts`) делает AST-дамп классов `Message`, `SchemaBase` и `BaseModel` с полями. Он показывает, что проходит через границу, но не блокирует нарушение.

**Что осталось открытым или ненадёжным.**
- Я не открывал `scripts/validate.py` и `.sentrux/rules.toml`. Поэтому не знаю, ловит ли какой-то из них R-3. Судя по таблице, нет.
- Я не проверял, что все 74 теста действительно проходят через реальные очереди. Урок проекта «дублёр верен форме, не протоколу» говорит, что `pickle.dumps` на готовом dict не доказывает, что реальный отправитель кладёт dict.
- Индекс qex недоступен (ollama DOWN), поэтому поиск шёл только грепом по первым 30 совпадениям. Файлов с правилом может быть больше.

## single / q4 / ход 1 / rep2 / D (277 слов)

**Почему dict.** Это ADR-008 (2026-03-11, `multiprocess_framework/DECISIONS.md:262`), он же правило R-3 в `multiprocess_framework/docs/DESIGN_RULES.md:49`. Причина в том, что на Windows процессы стартуют через `spawn`. Всё, что идёт в `multiprocessing.Queue`, `Pipe` или `SharedResourcesManager`, проходит через pickle. Pydantic-объекты, lambdas, closures и незарегистрированные классы там ломаются или ведут себя непредсказуемо. Plain `dict` — единственный формат, который проходит pickle гарантированно. Внутри процесса Pydantic разрешён. Конфиг на границе — `dict | None | SchemaBase`, внутри — `normalize_config()` (R-19).

**Где проверяется.** Автоматической проверки нет. Я нашёл только тесты и ревью:

- В `DESIGN_RULES.md:290` способ проверки R-3 — `pickle.dumps(payload)` в тесте. Такие вызовы есть в 37 файлах тестов модулей, например в `shared_resources_module`, `base_manager`, `router_module`, `process_module`, `app_module`.
- Тест правила для сообщений — `test_message_dict_is_pickle_safe` (`message_module/tests/test_message.py:529`). Это единственный тест, который проверяет именно dict-форму `Message`.
- Статического сторожа я не нашёл. В `scripts/` нет упоминаний pickle или R-3. В `.sentrux/rules.toml` я не искал. Он проверяет границы слоёв, а не типы payload.
- Таблица правил показывает, что R-4 и R-6 держатся на ревью. Отдельного шага `/dev:review` для R-3 я не нашёл.

**Что осталось открытым:**
- ADR-MSG-005 говорит, что `Message` не гарантируется pickle-safe и через границу идёт только `to_dict()`. При этом `test_message.py` (строки 514–564) pickle'ит сам объект `Message` и ожидает успех. Эти два утверждения расходятся, и я не выяснял, какое из них актуально.
- Раз статического сторожа нет, я не проверял, что реальный `send_message` сам превращает `Message` в dict. Это видно только по коду отправки или по тесту, который собирает настоящие объекты. Такого теста я не искал.
- Я не запускал тесты. Проверил только их наличие по grep.

## single / q5 / ход 1 / rep1 / A (475 слов)

`ProcessManagerProcess` напрямую нигде не вызывается как `ProcessManagerProcess(...)`. Его создаёт дочерний процесс по строковому пути класса, который передаёт `ProcessSpawner`. В прототипе вместо него подставлен подкласс `ProcessManagerProcessApp`.

## Где создаётся

| Шаг | Место |
|---|---|
| Класс | `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:71` |
| Путь класса по умолчанию | `launcher/spawner.py:37`, константа `PROCESS_MANAGER_CLASS_PATH` |
| Создание `Process(...)` с PM | `launcher/spawner.py:122-140`, `ProcessSpawner.launch_orchestrator()` |
| Вызывающий | `launcher/system_launcher.py:488`, `SystemLauncher.run()` (и `start()` на `:518`) |
| Прототип | `multiprocess_prototype/backend/launch.py:735` передаёт `orchestrator_class_path` = `multiprocess_prototype.orchestrator.ProcessManagerProcessApp` |

Сам объект PM строит `run_process_function`: он импортирует класс по строке и создаёт экземпляр уже внутри нового процесса.

## Порядок запуска

**1. `SystemLauncher.run()` / `start()` в главном процессе**
1. `_prepare_pid_registry()` записывает путь PID-файла в env и убивает осиротевшие процессы прошлого запуска.
2. `_cleanup_shm_at_startup()` чистит висящие SHM-сегменты. Эта очистка ничего не освобождает на Windows.
3. `_create_spawner()`.

**2. `ProcessSpawner.launch_orchestrator()`**
1. Поднимаются `SharedResourcesManager` и логгер `spawner`.
2. `ProcessTreeGuard.install()` вызывается до спавна PM. На Windows это Job Object, чтобы дети наследовались по job.
3. В `Process(target=run_process_function, ...)` передаются `system_ready_event`, `system_stop_event` и `bundle`. Этот процесс запускается как `.start()`.
4. `guard.adopt(pid)`, затем обработчики SIGINT и SIGTERM.

**3. `ProcessManagerProcess.initialize()` (`process_manager_process.py:248`)**
1. PM регистрируется в `shared_resources`.
2. `super().initialize()`, затем консоль, `TopologyManager`, `StateStore` и встроенные команды.
3. Чистка осиротевших лог-каталогов.
4. `_create_processes_from_config()` (`:3344`):
   - Для всех процессов из `processes_config` регистрируются конфиги и очереди (фаза 1).
   - `_plan_boot_waves()` строит волны. Если флаг `FW_DEPENDS_ON_BOOT_ORDER` выключен или ни у кого нет `depends_on`, волна одна, в порядке конфига. Если есть `depends_on`, волны строятся топосортом (алгоритм Кана). Цикл в графе даёт плоский старт.
   - Перед каждой следующей волной PM ждёт ready апстримов (`boot-deps`, до `boot_ready_timeout_s`, по умолчанию 5 с). Если апстрим не стал ready, зависимые всё равно стартуют, в лог идёт WARNING.
   - Внутри волны каждый процесс проходит `_boot_create_and_start()`: `create_and_register` строит `Process` со свежими `ready_event`, `stop_event` и `exit_report`, затем `process.start()` и `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются.
5. `ProcessMonitor.start()`.
6. Регистрируется обработчик `process.command`, затем поднимается `backend_ctl` (если включён).
7. `_wait_boot_ready()` ждёт ready всех детей, до 5 с. После таймаута система стартует всё равно.
8. Готовность `system_ready_event` объявляет не `initialize()`, а `_announce_ready()` последней строкой `run()`, когда команды PM уже зарегистрированы.

**4. Главный процесс**
`SystemLauncher.wait_until_ready(timeout)` ждёт `system_ready_event`. Уровень готовности «minimum+»: дети запущены, но их `initialize()` может ещё идти.

## Что осталось открытым / ненадёжно
- `_wait_processes_ready` и `_announce_ready` я не читал. Про них известно только из docstring'ов и комментариев в прочитанном коде.
- Классов-наследников PM кроме `ProcessManagerProcessApp` я не искал. Его код в `multiprocess_prototype/orchestrator.py` не читал, значит возможное переопределение `initialize()` или порядка запуска не проверил.
- Конкретные `depends_on` и `priority` в рецептах и `processes_config` прототипа не смотрел, поэтому реальный состав и порядок волн для приложения не назван.
- Топология меняется и позже: `topology.apply` запускает процессы через `process.start`, и это идёт отдельным путём, не волнами.
- qex не использовал: Ollama не запущен, поэтому поиск шёл только через `Grep`.

## single / q5 / ход 1 / rep1 / C (445 слов)

`ProcessManagerProcess` нигде не создаётся прямым вызовом `ProcessManagerProcess(...)`. Его запускает отдельный OS-процесс по пути к классу из строки. В прототипе подставлен подкласс `ProcessManagerProcessApp`.

## Где создаётся

1. `multiprocess_prototype/backend/launch.py:735` собирает `SystemLauncher` с `orchestrator_class_path="multiprocess_prototype.orchestrator.ProcessManagerProcessApp"` (константа в строке 38). Эта часть прочитана выборочно.
2. Общий путь для приложений на `app_module` — `multiprocess_framework/modules/app_module/builder.py:408`. Класс по умолчанию там — `GenericProcessManagerApp`.
3. `SystemLauncher.run()` или `start()` (`launcher/system_launcher.py:481` и `:510`) создаёт `ProcessSpawner`.
4. `ProcessSpawner.launch_orchestrator()` (`launcher/spawner.py:86`) собирает `Process(target=run_process_function, args=(class_path, "orchestrator", ...))` и вызывает `.start()` (строка 140). Класс по умолчанию — `PROCESS_MANAGER_CLASS_PATH` (строка 37). `run_process_function` потом импортирует класс по строке и создаёт его уже в дочернем процессе.

## Порядок запуска

**В главном процессе (`SystemLauncher` и `ProcessSpawner`):**
1. `_prepare_pid_registry()` записывает путь PID-файла в env и убирает осиротевшие процессы прошлого запуска.
2. `_cleanup_shm_at_startup()` чистит висящие SHM-сегменты. Сбой уборки не срывает запуск, его пишут в журнал.
3. `launch_orchestrator()` по шагам:
   - создаёт `SharedResourcesManager`;
   - ставит `ProcessTreeGuard.install()` до спавна: на Windows это Job Object, чтобы дети наследовали его;
   - собирает `bundle` с `processes_config`, `system_ready_event` и `shutdown_timeout`;
   - запускает процесс оркестратора;
   - вызывает `guard.adopt(pid)` и ставит обработчики сигналов.

**Внутри оркестратора (`ProcessManagerProcess.initialize()`, `process_manager_process.py:248`):**
1. Регистрирует себя в `shared_resources` и вызывает `ProcessModule.initialize()`.
2. Поднимает консоль, `TopologyManager`, `StateStore` и встроенные команды.
3. Вызывает `_create_processes_from_config()` (строка 3344) в два этапа:
   - Сначала для всех процессов вызывается `register_process` (очереди и ресурсы).
   - Затем `_plan_boot_waves` делит процессы на волны. Если флаг `FW_DEPENDS_ON_BOOT_ORDER` включён и задан хоть один `depends_on`, это топосорт по Kahn. Иначе, а также при цикле, волна одна, в порядке конфига.
   - Перед каждой следующей волной `_wait_processes_ready` ждёт ready апстримов, максимум `boot_ready_timeout_s` (по умолчанию 5 с). Если апстрим не стал ready, зависимые всё равно стартуют, с WARNING.
   - Внутри волны для каждого процесса `_boot_create_and_start` делает `create_and_register`, затем `process.start()`, `_mark_instance_started` и `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются.
4. Запускает `_process_monitor.start()`.
5. Регистрирует эндпоинт `process.command` и канал `backend_ctl`.
6. `_wait_boot_ready()` ждёт ready всех детей, тоже до 5 с. По таймауту система стартует всё равно.
7. `attach_ready_event(system_ready_event)` лишь передаёт событие. Взводит его сам PM через `_announce_ready()` последней строкой `run()`, когда команды уже зарегистрированы. `SystemLauncher.wait_until_ready()` ждёт именно это событие.

## Что осталось открытым или ненадёжным

- Порядок процессов внутри волны — это порядок ключей `processes_config`. Как прототип формирует этот порядок (рецепты, `orchestrator.py`), я не смотрел.
- Содержимое `ProcessManagerProcessApp` и `GenericProcessManagerApp` не читал. Возможно, они переопределяют часть пути запуска.
- Включён ли `FW_DEPENDS_ON_BOOT_ORDER` и задан ли `depends_on` в реальных конфигах прототипа, не проверял.
- `ProcessRegistry.start_all` (`core/process_registry.py:312`) существует. Используется ли он на boot, не проверял: этот путь идёт через `_boot_create_and_start`.
- qex недоступен, потому что Ollama не запущен. Поиск шёл через `Grep`, то есть только по точным именам.

## single / q5 / ход 1 / rep1 / D (370 слов)

ProcessManagerProcess нигде не создаётся прямым вызовом `ProcessManagerProcess(...)`. Его создаёт дочерний процесс по строке с путём к классу. Строку передают в `Process(target=run_process_function, ...)` в `ProcessSpawner.launch_orchestrator`: `multiprocess_framework/modules/process_manager_module/launcher/spawner.py:122-140`.

## Откуда берётся класс
- Класс определён в `process_manager_module/process/process_manager_process.py:71`.
- Прототип подставляет свой подкласс: `ProcessManagerProcessApp` в `multiprocess_prototype/orchestrator.py:34`. Путь к нему лежит в `_ORCHESTRATOR_CLASS_PATH` (`multiprocess_prototype/backend/launch.py:38`) и уходит в `assemble_launcher` на строке 733.
- Без явного пути берётся `GENERIC_ORCHESTRATOR_CLASS_PATH` (`app_module/builder.py:408`).

## Порядок запуска
1. **`SystemLauncher.start()` или `run()`** (`launcher/system_launcher.py:481-518`):
   - `_prepare_pid_registry()` убирает хвосты прошлого запуска.
   - `_cleanup_shm_at_startup()` чистит старые SHM-сегменты.
   - `_create_spawner()` создаёт `ProcessSpawner`.
   - `launch_orchestrator()` запускает оркестратор.
2. **`ProcessSpawner.launch_orchestrator()`** (`spawner.py:86-146`), по шагам:
   - создаёт `SharedResourcesManager`;
   - ставит `ProcessTreeGuard` до спавна оркестратора;
   - собирает `process_config` с `processes_config` и `orchestrator_config`;
   - запускает `Process(...)` с `system_stop_event` отдельным аргументом;
   - привязывает его к guard через `adopt(pid)`;
   - ставит обработчики SIGINT и SIGTERM.
3. **`ProcessManagerProcess.initialize()`** (`process_manager_process.py:248-334`), в порядке вызова:
   - `register_process` и `super().initialize()`;
   - консоль, `TopologyManager`, `StateStore`, встроенные команды;
   - **`_create_processes_from_config(processes_config)`**, где стартуют дети;
   - `_process_monitor.start()`;
   - канал `backend_ctl`;
   - `_wait_boot_ready()`;
   - `attach_ready_event(system_ready_event)`.
4. **`_create_processes_from_config`** (`process_manager_process.py:3344-3391`):
   - Сначала для всех детей в `shared_resources.register_process` регистрируются очереди.
   - `_plan_boot_waves` делит процессы на волны, по `depends_on` и топосорту Kahn.
   - Если `FW_DEPENDS_ON_BOOT_ORDER` выключен, нет ни одного `depends_on` или в графе цикл, получается одна плоская волна в порядке конфига.
   - Перед каждой волной, кроме первой, PM ждёт ready её апстримов через `_wait_processes_ready`. Таймаут — `boot_ready_timeout_s`, по умолчанию 5 с. По таймауту зависимые всё равно стартуют, в лог идёт WARNING.
   - Внутри волны `_boot_create_and_start` по порядку выполняет `create_and_register`, `process.start()`, `_mark_instance_started` и `apply_priority`.
5. **Готовность системы**: `_wait_boot_ready()` ждёт ready всех детей до 5 с. Сигнал `system_ready_event` PM взводит последней строкой `run()`, через `_announce_ready()`. К этому моменту уже зарегистрированы `introspect.*` и `router.relay`. `SystemLauncher.wait_until_ready()` ждёт именно этот сигнал.

## Что осталось непроверенным
- Тело `run_process_function` я не читал. То, что он резолвит класс по строке и создаёт экземпляр, следует из сигнатуры и из комментариев в `spawner.py`.
- Реальный порядок детей в прототипе зависит от `depends_on` и порядка в `system.yaml` и рецепте. Эти файлы я не открывал.
- Флаг `FW_DEPENDS_ON_BOOT_ORDER` по умолчанию включён или выключен — я не проверял.
- Ollama не запущен, поэтому `qex` был недоступен. Весь поиск шёл через `Grep` и `Read`.

## single / q5 / ход 1 / rep2 / A (475 слов)

Сейчас собираю итог: поиск по коду закончен, ниже результат.

## Где создаётся ProcessManagerProcess

Прямого вызова `ProcessManagerProcess(...)` в коде нет. Класс передаётся строкой с путём, и экземпляр создаёт runner в дочернем процессе.

| Шаг | Место |
|---|---|
| Определение класса | `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:71` |
| Путь класса для прототипа | `multiprocess_prototype/backend/launch.py:38` — `"multiprocess_prototype.orchestrator.ProcessManagerProcessApp"` |
| Передача пути в лончер | `launch.py:733` — `assemble_launcher(..., orchestrator_class_path=...)` |
| Выбор класса лончером | `launcher/system_launcher.py:357` `_create_spawner` — если путь не задан, берётся дефолт `PROCESS_MANAGER_CLASS_PATH` |
| Сам спавн | `launcher/spawner.py:122` — `Process(target=run_process_function, args=(class_path, ORCHESTRATOR_PROCESS_NAME, ...))`, затем `.start()` на строке 140 |
| Создание экземпляра | `runner/process_runner.py:246` `run_process_function`, уже в дочернем процессе |

Для приложений без своего оркестратора есть `GENERIC_ORCHESTRATOR_CLASS_PATH` (`app_module/builder.py:35`).

## Порядок запуска

**1. В главном процессе** (`SystemLauncher.run()` / `start()`, `system_launcher.py:481` и `:510`):
1. `_prepare_pid_registry`: путь PID-файла пишется в env, затем идёт реап осиротевших процессов прошлого запуска.
2. `_cleanup_shm_at_startup`: уборка висящих SHM-сегментов.
3. `_create_spawner`.
4. `spawner.launch_orchestrator()` (`spawner.py:86`):
   - `setup_multiprocessing`;
   - `SharedResourcesManager.initialize()`;
   - `ProcessTreeGuard.install()` до спавна: на Windows создаётся job, и дети наследуют его;
   - `Process(...).start()` для оркестратора;
   - `guard.adopt(pid)` и `_setup_signals`.
5. Главный процесс ждёт: `wait_until_ready` смотрит на `system_ready_event`, либо `run()` крутит join с интервалом 0.5 с.

**2. Внутри PM, `initialize()`** (`process_manager_process.py:248`):
1. Регистрация PM в `shared_resources`.
2. `super().initialize()`, затем консоль, topology manager, state store, builtin-команды.
3. Подметание старых лог-каталогов.
4. `_create_processes_from_config` (`:3344`):
   - сначала всем процессам регистрируются очереди и ресурсы;
   - `_plan_boot_waves` (`:3418`) строит волны старта топосортом Kahn по `depends_on`, если флаг `FW_DEPENDS_ON_BOOT_ORDER` включён и зависимости есть;
   - без `depends_on`, при выключенном флаге или цикле в графе будет одна плоская волна в порядке словаря;
   - перед каждой волной, кроме нулевой, `_wait_processes_ready` ждёт готовности апстримов (по умолчанию `boot_ready_timeout_s` = 5 с). По таймауту зависимые всё равно стартуют, в лог идёт WARNING;
   - каждый процесс стартует через `_boot_create_and_start` (`:3393`): `create_and_register`, `process.start()`, `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются.
5. `process_monitor.start()`.
6. Регистрация `process.command` и backend_ctl-канала.
7. `_wait_boot_ready()`: барьер на готовность всех стартованных детей.
8. `attach_ready_event`. Событие готовности взводится не здесь, а последней строкой `run()` через `_announce_ready()`, когда уже зарегистрированы `introspect.capabilities` и `router.relay` (комментарий на `:314-326`).

**3. Готовность.** `system_ready_event` означает минимум: все дети запущены, PM отвечает. Дети могут ещё выполнять свой `initialize()` (см. докстринг `wait_until_ready`). Источники кадров ждут это же событие перед первым `produce()` (ADR-PMM-034).

## Что я оставил открытым или ненадёжным

- Индекс qex недоступен, потому что Ollama не запущена, поэтому я искал только `Grep`ом и `Read`ом. Другие места, где класс создаётся или импортируется (тесты, `frontend/app.py`, `backend_ctl`), я не проверял.
- Цепочку `ProcessManagerProcessApp → GenericProcessManagerApp → ProcessManagerProcess` я не читал, подтверждено только имя `ProcessManagerProcessApp(GenericProcessManagerApp)` в `orchestrator.py:34`. Наследование от `ProcessManagerProcess` предполагаю по README.
- Сам момент создания экземпляра в `process_runner.py` (строки ~300–365) я прочитал только по найденным строкам grep.
- Запуск вживую я не проверял. Всё описано по чтению кода, без прогона.

## single / q5 / ход 1 / rep2 / C (440 слов)

`ProcessManagerProcess` в коде нигде не создаётся вызовом `ProcessManagerProcess(...)`. Его запускает `ProcessSpawner` в отдельном процессе по строке-пути класса. Индекс qex не использовал: Ollama не запущен. Все выводы получены чтением файлов.

## Где он создаётся

1. `SystemLauncher.run()` или `.start()` (`process_manager_module/launcher/system_launcher.py:481` и `:510`) создаёт спаунер: `_create_spawner(processes_config)`.
2. `ProcessSpawner.launch_orchestrator()` (`launcher/spawner.py:86`) собирает `multiprocessing.Process(target=run_process_function, args=(self._orchestrator_class_path, ORCHESTRATOR_PROCESS_NAME, stop_event, bundle, system_stop_event))`. Затем вызывает `.start()` (`spawner.py:140`).
3. `run_process_function` (`runner/process_runner.py`) загружает класс через `_load_process_class(class_path)` (`:315`). Он создаёт экземпляр, вызывает `initialize()` (`:362`), затем `run()` (`:139`).
4. По умолчанию путь класса — `PROCESS_MANAGER_CLASS_PATH` (`spawner.py:37`), то есть сам `ProcessManagerProcess`. Прототип подставляет подкласс: `multiprocess_prototype.orchestrator.ProcessManagerProcessApp` (`multiprocess_prototype/backend/launch.py:38`). Через `app_module/builder.py:408` по умолчанию идёт `GENERIC_ORCHESTRATOR_CLASS_PATH`.

Сам класс — `process_manager_module/process/process_manager_process.py:71`.

## Порядок запуска дочерних процессов

Шаги идут в `ProcessManagerProcess.initialize()` (`process_manager_process.py:248`).

1. **Подготовка до спавна детей.**
   - `SystemLauncher` готовит реестр PID и чистит осиротевшие SHM-сегменты.
   - Спаунер создаёт `SharedResourcesManager` и ставит `ProcessTreeGuard` (Job Object на Windows) до старта PM.
2. **Старт PM.** Внутри PM по порядку:
   - регистрация в SRM;
   - `super().initialize()`;
   - консоль;
   - `TopologyManager`;
   - `StateStore`;
   - встроенные команды;
   - лог активных `FW_*`-флагов;
   - уборка осиротевших каталогов логов.
3. **Дети создаются из `processes_config`.** Метод `_create_processes_from_config` (`:3344`) работает так:
   - Сначала для всех процессов в `_process_configs` пишется конфиг и вызывается `register_process` в SRM, то есть очереди создаются заранее.
   - `_plan_boot_waves` (`:3418`) строит волны по `depends_on` (топосорт Kahn, ADR-PMM-018). Это работает при включённом `FW_DEPENDS_ON_BOOT_ORDER`. Без `depends_on`, при выключенном флаге или при цикле — одна плоская волна в порядке dict.
   - Перед волной с индексом больше 0 PM ждёт self-reported ready апстримов (`_wait_processes_ready`, таймаут `boot_ready_timeout_s`, по умолчанию 5 с). Не-ready апстрим даёт WARNING, но следующая волна всё равно стартует.
   - Внутри волны для каждого процесса вызывается `_boot_create_and_start` (`:3393`): `create_and_register`, затем `process.start()`, затем `_mark_instance_started` и `apply_priority`. Если создание не удалось, конфиг и ресурсы откатываются.
4. **Монитор и эндпоинты.**
   - `ProcessMonitor.start()`;
   - команда `process.command`;
   - канал `backend_ctl` (по `BACKEND_CTL=1`).
5. **Boot-барьер.** `_wait_boot_ready` (`:4133`) ждёт ready всех стартованных детей до `boot_ready_timeout_s`. По таймауту система стартует всё равно, не-ready попадают в WARNING.
6. **Сигнал готовности.** В конце `initialize()` PM только вызывает `attach_ready_event(system_ready_event)`. Само событие он взводит в конце `run()` через `_announce_ready()`, когда уже зарегистрированы команды `introspect.*` и `router.relay`. `SystemLauncher.wait_until_ready()` ждёт именно его.

## Что осталось неясным

- Тела `_create_spawner` и `_compute_boot_waves` я не читал, только их вызовы и описание.
- Дочерний `ProcessModule.initialize()` не прослеживал.
- Порядок слотов `processes_config` в самом прототипе (какие процессы и в каком порядке) не смотрел. Он задаётся рецептом и `depends_on` в `multiprocess_prototype/backend/launch.py`.
- Горячее применение топологии (`topology.apply`) идёт другим путём и `depends_on` не переупорядочивает (ADR-PMM-018, «Границы»).

## single / q5 / ход 1 / rep2 / D (447 слов)

`ProcessManagerProcess` нигде не создаётся прямым вызовом `ProcessManagerProcess(...)`. Его запускает `ProcessSpawner` в отдельном OS-процессе по строке `class_path`, а класс загружает `run_process_function`. В прототипе подставляется подкласс `ProcessManagerProcessApp`.

## Где создаётся

| Шаг | Место |
|---|---|
| Класс | `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:71` |
| Подкласс прототипа | `multiprocess_prototype/orchestrator.py:34` (`ProcessManagerProcessApp`, путь задан в `backend/launch.py:38`) |
| Сборка `SystemLauncher` | `multiprocess_prototype/backend/launch.py` (`SystemBuilder.build`, строка 615) |
| `SystemLauncher.start()` | `launcher/system_launcher.py:510` → `_create_spawner` (357) → `launch_orchestrator()` (518) |
| Реальный спавн | `launcher/spawner.py:86–146`: `Process(target=run_process_function, args=(class_path, "ProcessManager", ...))` и `.start()` на строке 140 |
| Загрузка класса | `runner/process_runner.py:246`: `_load_process_class(class_path)` внутри нового процесса |

## Порядок запуска

**1. В главном процессе (`SpawnProcess.launch_orchestrator`):**
- `setup_multiprocessing()`.
- Создаётся `SharedResourcesManager`.
- Устанавливается `ProcessTreeGuard` (на Windows это Job Object). Это делается до спавна PM, чтобы дети попали в job.
- Собирается bundle с `processes_config`, `system_ready_event` и `shutdown_timeout`.
- Стартует процесс PM, затем `guard.adopt(pid)` и обработчики сигналов.

**2. Внутри процесса PM** (`run_process_function`):
- Запускается сторож родителя (`_start_parent_watcher`).
- Процесс регистрируется в PID-реестре.
- Загружается класс и из bundle строится `SharedResourcesManager`.
- Дальше идёт `initialize()` PM (строки 248–334).

**3. `ProcessManagerProcess.initialize()`:**
1. `register_process` для самого PM.
2. `super().initialize()`.
3. Консоль, `TopologyManager`, `StateStore`, встроенные команды.
4. Очистка осиротевших log-директорий.
5. `_create_processes_from_config`, то есть запуск детей (шаги ниже).
6. `_process_monitor.start()`.
7. Регистрация `process.command` и `backend_ctl`.
8. `_wait_boot_ready()` и `attach_ready_event`.

**4. Запуск детей (`_create_processes_from_config`, строка 3344):**
- Берутся только записи с ключом `class`.
- Для всех сначала вызывается `register_process`, то есть очереди создаются заранее. Затем идёт create и start.
- `_plan_boot_waves` строит волны топосортом по `depends_on`. Это работает при включённом флаге `FW_DEPENDS_ON_BOOT_ORDER` и хотя бы одном `depends_on`. Иначе, и при цикле, будет одна плоская волна в порядке конфига.
- Перед каждой волной, кроме первой, PM ждёт ready её апстримов (`_wait_processes_ready`). Если апстрим не ready, волна всё равно стартует, но пишется WARNING.
- Внутри волны `_boot_create_and_start`: `create_and_register` → `process.start()` → `_mark_instance_started` → `apply_priority`. При провале create откатываются конфиг и ресурсы.

**5. Boot-барьер** (`_wait_boot_ready`, строка 4133): PM ждёт ready всех детей до `boot_ready_timeout_s` (по умолчанию 5 с, значение 0 отключает барьер). Если время вышло, система стартует всё равно, а не-ready дети попадают в WARNING.

**6. Сигнал готовности:** `system_ready_event` взводится не в конце `initialize()`, а последней строкой `run()` (`_announce_ready`). К этому моменту встроенные команды уже зарегистрированы. `SystemLauncher.wait_until_ready` опрашивает это событие каждые 50 мс.

## Что я не проверял
- Я не читал `ProcessRegistry.create_and_register` и не видел, как именно ребёнок запускается через `run_process_function` с `parent_pid`. Это следует из докстринга (`process_runner.py:264`).
- Я не читал продолжение `run_process_function` после строки 335. Вызов `initialize()` и затем `run()` взят из комментариев в PM.
- Значения флага `FW_DEPENDS_ON_BOOT_ORDER` и `depends_on` в реальных рецептах не смотрел, поэтому не знаю, идёт ли боевой запуск волнами.
- qex не использовал: Ollama не запущена, поэтому поиск шёл через Grep.

## single / q6 / ход 1 / rep1 / A (125 слов)

Вот текст для коллеги:

> Привет! Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня репозитория.
>
> Почему: `pytest.ini` лежит в `multiprocess_framework/modules`, а не в корне. Скрипт сам выставляет нужный cwd, поэтому настройки pytest подхватываются так же, как в CI. Голый `pytest` из корня запускается с другим cwd и без этого конфига, так что результат может отличаться от CI.
>
> Если нужен ручной запуск, делай его из `multiprocess_framework/modules`. Общая проверка проекта — `python scripts/validate.py`.

**Что я оставил открытым:** я не запускал `pytest` из корня, поэтому не знаю, какой именно сбой даст голый запуск (падения импортов, другой набор тестов или что-то ещё). Причина в тексте взята из `CLAUDE.md`. Если коллега спросит про конкретный симптом, надо проверить это запуском.

## single / q6 / ход 1 / rep1 / C (116 слов)

Готовое сообщение:

> Привет! Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня.
>
> Почему: `pytest.ini` с `testpaths` лежит в `multiprocess_framework/modules/`. Из корня pytest этот конфиг не подхватывает. Он собирает не тот набор тестов и работает с другим cwd. Скрипт сам запускает `python -m pytest` с `cwd=multiprocess_framework/modules`, так что конфиг и `testpaths` подхватываются.
>
> Аргументы скрипт передаёт в pytest как есть: `python scripts/run_framework_tests.py base_manager/tests -q --maxfail=1`.
>
> Если нужен ручной pytest, запускай его из `multiprocess_framework/modules`.

Что осталось непроверенным: я прочитал скрипт и `CLAUDE.md`, но голый `pytest` из корня не запускал. Конкретную поломку (какие тесты соберутся не так) я не воспроизводил, поэтому в тексте её нет.

## single / q6 / ход 1 / rep1 / D (103 слов)

Вот текст сообщения:

> Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня.
>
> Почему: `pytest.ini` лежит в `multiprocess_framework/modules`, а не в корне. Из корня pytest этот конфиг не подхватит. Скрипт сам выставляет нужный cwd, поэтому запуск одинаковый у всех и в CI.
>
> Если нужен ручной pytest, запускай его из `multiprocess_framework/modules`. Полная проверка проекта: `python scripts/validate.py`.

**Что осталось непроверенным:** причину я взял из корневого `CLAUDE.md` (правило 4). Сам `scripts/run_framework_tests.py` я не открывал, поэтому не знаю, делает ли он ещё что-то, кроме смены cwd. Если коллега спросит про детали, сначала посмотри скрипт.

## single / q6 / ход 1 / rep2 / A (127 слов)

Привет! Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня репозитория.

**Почему:** `pytest.ini` лежит в `multiprocess_framework/modules`, не в корне. Если запустить `pytest` из корня, он не подхватит эту конфигурацию. Результат может отличаться от CI: тесты могут не собраться, упасть на импортах или вести себя иначе. `run_framework_tests.py` сам выставляет нужный cwd, так что ничего настраивать не надо.

Если нужен ручной запуск отдельного теста, делай `cd multiprocess_framework/modules`, а потом `pytest ...`.

Перед коммитом полезно прогнать ещё `python scripts/validate.py`.

**Что я не проверял:** содержимое самого `run_framework_tests.py` я не открывал. Объяснение про `pytest.ini` и cwd взято из `CLAUDE.md` проекта. Если хочешь добавить к сообщению конкретные симптомы (какие ошибки видны при запуске из корня), скажи, и я воспроизведу их.

## single / q6 / ход 1 / rep2 / C (110 слов)

Вот текст для коллеги:

> Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня.
>
> `pytest.ini` лежит в `multiprocess_framework/modules`, а не в корне. Из корня pytest этот конфиг не подхватит, и тесты пойдут с другими настройками. `run_framework_tests.py` сам выставляет нужный cwd, поэтому результат одинаковый у всех и в CI.
>
> Если нужен ручной запуск, делай его из `multiprocess_framework/modules`. Общую проверку проекта делает `python scripts/validate.py`.

**Что я оставил открытым.** Скрипт `run_framework_tests.py` я не открывал. Объяснение про `pytest.ini` и cwd взято из корневого `CLAUDE.md`. Какие именно настройки теряются при запуске из корня, я не проверял. Если коллега спросит, нужна проверка запуском.

## single / q6 / ход 1 / rep2 / D (120 слов)

Готовое сообщение:

> Привет! Тесты фреймворка запускай через `python scripts/run_framework_tests.py`, а не голым `pytest` из корня.
>
> Почему: `pytest.ini` с `testpaths` лежит в `multiprocess_framework/modules/`, а не в корне. Голый `pytest` из корня этот конфиг не подхватывает. Он собирает тесты не по тому набору путей и берёт другой rootdir. Скрипт сам запускает pytest с `cwd=multiprocess_framework/modules` и явно передаёт этот `pytest.ini`.
>
> Если нужен ручной запуск, делай его из `multiprocess_framework/modules`. Для общей проверки есть `python scripts/validate.py`.

Я прочитал только `scripts/run_framework_tests.py`: там `cwd=modules` и путь к `pytest.ini`. Конкретные ошибки голого запуска из корня я не воспроизводил, так что формулировку «собирает не тот набор» берите как следствие из конфига, а не как замер.

## single / q7 / ход 1 / rep1 / A (425 слов)

Вывод сделан по коду `core/chain.py`, `core/dag.py` и `README.md` модуля. Вызывающий код в прототипе, который выбирает исполнитель, я не смотрел. Индекс qex не использовал: Ollama не запущен.

## Коротко

- **`ChainRunnable`** подходит для линейного pipeline: шаги идут один за другим, выход предыдущего становится входом следующего.
- **`DagRunnable`** нужен, когда в графе есть ветвление (1→N) или слияние (N→1). Данные в нём идут по именованным портам.

## Сравнение

| | `ChainRunnable` | `DagRunnable` |
|---|---|---|
| Конструктор | `steps` | `steps`, `topology` (порядок `node_id`), `node_inputs` (входные соединения) |
| Передача данных | один `current_frame` по цепочке | `port_data[node_id][port]`, вход каждой ноды собирается по её соединениям |
| Тип payload | duck-typed: `ndarray` или `list[dict]` | `np.ndarray` по сигнатуре |
| Вызов операции | `operation.execute(frame, ctx)` | `execute_dag(inputs, ctx)`, иначе `execute(...)` с обёрткой в `{"out": ...}` |
| Результат | последний `current_frame` | выход последней ноды в топологии: порт `out`, иначе первый `ndarray` среди портов |
| Ошибка с `skip` | цепочка идёт дальше с прежним кадром | `port_data[node_id] = {}`, у потребителей этой ноды вход будет `None` |
| Ошибка `fail_*` | `break`, `failed=True` | то же самое |
| Cross-process шаг | `execute_remote`, кадр не меняется | `execute_remote`, на выход ноды уходит её входной кадр |

Оба исполнителя работают в одном потоке и последовательно. Параллельность даёт только `ParallelChainRunnable` (бандлы через `ChainThreadPool`) и `WorkerPoolDispatcher` для cross-process шагов.

## Когда что использовать

- **Линейный список шагов** (`blur → threshold → detect`): `ChainRunnable`. Он проще, и в нём нет накладных расходов на порты.
- **Есть ветвление или merge** (например, один кадр идёт в две ветки, а результаты сливаются): `DagRunnable`. `ChainRunnable` не умеет вести несколько значений одновременно.
- **Не знаешь заранее, какой нужен:** вызови `is_nonlinear_graph(nodes)`. По README он как раз определяет, нужен ли `DagRunnable` вместо `ChainRunnable`. Его тесты (`test_topology.py`) проверяют ветвление и merge как `True`, линейный граф и пустой как `False`.
- **Нужна параллельность внутри уровня графа:** `ParallelChainRunnable` вместе с `detect_parallel_bundles`. Ни один из двух исполнителей этого не делает.

Оба реализуют `IRunnableChain` (`execute(payload, metadata) -> ChainResult`), поэтому снаружи их можно подменять друг другом.

## Что я оставил открытым или ненадёжным

- **Кто выбирает исполнитель в прототипе.** По README это делает `builder.py`, но сам файл я не открывал. Что `is_nonlinear_graph` вызывается именно там, не проверено: grep по `.py` показал его только в `chain_module` (определение, `__init__` и тесты).
- **Расхождение по payload.** `ChainRunnable.execute` принимает любой payload, включая `list[dict]` для processing-pipeline. `DagRunnable.execute` типизирован как `np.ndarray`, а внутри использует `np.ndarray` для выбора итогового кадра. Для `list[dict]` через DAG код, по-видимому, не рассчитан. Это вывод из чтения кода, прогона не было.
- **Skip в DAG.** `{}` вместо выхода ноды превращается у потребителей в `None` на входе. Как это переживают конкретные операции, я не проверял. Для ветки со слиянием это выглядит рискованным местом.

## single / q7 / ход 1 / rep1 / C (313 слов)

Закончил чтение кода обоих исполнителей и сейчас отвечаю.

**Коротко:** `ChainRunnable` берите для линейной цепочки, `DagRunnable` — только когда в графе есть ветвление (1→N) или слияние (N→1). Выбор делает `is_nonlinear_graph(nodes)` в `graph/topology.py:62`. Он возвращает `True`, если у ноды больше одного активного входа или один источник кормит больше одной ноды.

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Топология | Список шагов, порядок = порядок списка | `topology` (порядок нод) + `node_inputs` (связи) |
| Передача данных | `current_frame`: выход шага — вход следующего | `port_data[node_id][port]`, именованные порты |
| Тип `payload` | Любой (ndarray или `list[dict]`), исполнитель его не разбирает | `frame: np.ndarray` по аннотации, источник — виртуальная нода `"frame"` |
| Интерфейс операции | `operation.execute(frame, ctx)` | `execute_dag(inputs, ctx) → dict`, иначе `execute(...)` с обёрткой в `{"out": ...}` |
| Результат | Выход последнего шага | `out` последней ноды в `topology` |
| Накладные расходы | Минимальные | Словарь портов на каждый вызов |

**Различия в обработке ошибок** (по чтению кода, не по запуску):
- При `on_error="skip"` у `ChainRunnable` следующий шаг получает прежний `current_frame`.
- У `DagRunnable` упавшая нода записывает `port_data[node_id] = {}`. Потребитель получит `None` на своём входе.

**Где что используется:**
- `ChainRunnable` работает в боевом коде: `process_module/generic/pipeline_executor.py:116`. Он гоняет `list[dict]` items через плагины, один экземпляр на стабильное окно.
- `DagRunnable` нашёлся в `chain_module` (код и тесты) и в экспортах `__init__.py`. Вызовов из `multiprocess_prototype`, `Services` и `Plugins` grep не показал.

**Третий вариант:** `ParallelChainRunnable` (`core/parallel.py`) запускает шаги внутри бандла параллельно в `ChainThreadPool`, а сами бандлы идут по очереди. Он нужен, когда независимые шаги можно считать одновременно.

**Что я оставил открытым или ненадёжным:**
- Ничего не запускал, вывод только из чтения кода. Поведение `skip` в DAG (`None` на входе потребителя) не проверено тестом.
- Не читал `parallel.py`, `builder.py` в прототипе и `DECISIONS.md` модуля. Строка про `ParallelChainRunnable` взята из README.
- «`DagRunnable` не используется в проде» — результат одного grep по `*.py`. Динамическую сборку по имени класса он бы не поймал.
- qex не использовал: Ollama не запущена, индекс недоступен.

## single / q7 / ход 1 / rep1 / D (365 слов)

`ChainRunnable` берите для линейной цепочки, `DagRunnable` — для графа с ветвлениями (1→N) или слияниями (N→1). Выбор делает функция `is_nonlinear_graph` (`graph/topology.py:62`): она возвращает `True`, если у какой-то ноды больше одного активного входа или нода служит источником для двух и более нод.

## Сравнение

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Топология | линейная: шаг i → шаг i+1 | граф с ветвлениями и слияниями |
| Конструктор | `steps` | `steps`, `topology` (порядок `node_id`), `node_inputs` (входные соединения) |
| Передача данных | один `current_frame`, выход шага становится входом следующего | `port_data[node_id] = {порт: значение}`, вход ноды собирается по её соединениям |
| Интерфейс операции | `operation.execute(frame, ctx) → frame` | `execute_dag(inputs, ctx) → dict`; без него вызывается `execute()`, результат оборачивается в `{"out": ...}` |
| Вход без соединений | не применимо | виртуальный источник `"frame"`; нода без входов получает `inputs["in"] = frame` |
| Итоговый кадр | `current_frame` после последнего шага | `out` последней ноды в топологии, иначе первый `np.ndarray` среди её выходов |
| Ошибка шага | `apply_on_error_policy`: `break` или `continue` | то же, при `continue` дополнительно `port_data[node_id] = {}`, нижестоящие ноды получают `None` |
| Тип `payload` | duck-typed: `np.ndarray` или `list[dict]` | аннотирован как `np.ndarray` |

## Общее

- Оба исполнителя синхронные и однопоточные.
- Оба возвращают `ChainResult`, поддерживают cross-process шаги через `_is_cross_process` и реализуют протокол `IRunnableChain`.

## Нюансы `DagRunnable`

- **Cross-process шаг.** Его вход берётся из `inputs["in"]`. Выход в `port_data` — это просто вход (`{"out": inputs["in"]}`), а детекции из ответа добавляются в `result`. В DAG такой шаг прозрачен для данных.
- **Ветки не исполняются параллельно.** Ноды идут строго по `topology`, одна за другой. DAG здесь описывает зависимости данных, а не параллелизм.
- **Тип `payload`.** Аннотация `np.ndarray` уже, чем у `ChainRunnable`. Для `list[dict]` из processing-pipeline берите `ChainRunnable`. Рантайм-проверки типа нет, поэтому для DAG это проверьте отдельно.

## Третий вариант: `ParallelChainRunnable`

Для параллельного исполнения есть `ParallelChainRunnable` (`core/parallel.py`). Он исполняет бандлы по уровням: между бандлами барьер, шаги внутри бандла идут параллельно через `ChainThreadPool`. Бандлы строит `detect_parallel_bundles`. Если нужна параллельность, а не просто ветвление, берите его.

## Что осталось открытым

- Я не смотрел `parallel.py` и `dispatcher.py` и не проверял, как прототип выбирает исполнитель. Grep по `multiprocess_prototype` не нашёл прямых вызовов `DagRunnable(`/`ChainRunnable(`. Вероятно, создание идёт через фабрику или плагин, но это не проверено.
- Индекс qex не использовался: Ollama выключен. Выводы основаны на чтении файлов и grep.

## single / q7 / ход 1 / rep2 / A (485 слов)

`ChainRunnable` исполняет линейную цепочку, `DagRunnable` — граф с ветвлениями и слияниями. Это выводы из `core/chain.py`, `core/dag.py`, `graph/topology.py` и README модуля. Тесты и живой стенд я не запускал.

## Сравнение

| | `ChainRunnable` | `DagRunnable` |
|---|---|---|
| Топология | Линейная: шаг 1 → шаг 2 → … → шаг N | Граф с ветвлением (1→N) и слиянием (N→1) |
| Конструктор | `ChainRunnable(steps)` | `DagRunnable(steps, topology, node_inputs)` |
| Передача данных | Выход шага — вход следующего (`current_frame`) | `port_data`: у каждой ноды именованные порты, вход собирается по соединениям `source`/`output_port`→`input_port` |
| Тип `payload` | Любой, не интерпретируется: `np.ndarray` или `list[dict]` | В сигнатуре `frame: np.ndarray`; стартовый порт `frame.out` |
| Интерфейс операции | Только `execute(frame, ctx) → frame` | Сначала `execute_dag(inputs, ctx) → dict`; без него — `execute(...)`, результат оборачивается в `{"out": ...}` |
| Итоговый кадр | Выход последнего шага | Порт `out` последней ноды в топологии, иначе первый `ndarray` среди её выходов |
| Ошибка с политикой `skip` | Кадр остаётся прежним, идём дальше | Нода получает пустые выходы `{}`, зависимые ноды получают `None` на входе |
| Cross-process шаг | `execute_remote`, детекции пишутся в результат, кадр не меняется | То же; в `port_data` кладётся неизменённый вход |

Общее у обоих:
- Они реализуют один протокол `IRunnableChain.execute(payload, metadata) → ChainResult`, поэтому вызывающему коду всё равно, какой из них ему дали.
- Политика `on_error` у них общая, в `error_policy.apply_on_error_policy`.
- Cross-process шаги они определяют одинаково, через `_is_cross_process`.

## Когда что использовать

- **`ChainRunnable`** — по умолчанию, если граф линейный. Он проще, у него меньше косвенности, а в принципах владельца «меньше слоёв строго лучше». Он же единственный, кому подходит `list[dict]` как payload в processing-pipeline.
- **`DagRunnable`** — когда в графе есть хотя бы одна нода с двумя и более входами или с двумя и более потребителями. Примеры: один кадр идёт в две ветки (детектор плюс измеритель) и результаты сливаются, или два входа у одной ноды.
- **Как выбирать автоматически:** `graph.is_nonlinear_graph(nodes)` возвращает `True`, если какая-то нода имеет больше одного активного входа или больше одного потребителя. Тогда нужен `DagRunnable`. Топологию для него даёт `topological_sort`, который бросает `ValueError` на цикле.
- **`ParallelChainRunnable`** — третий вариант: шаги внутри бандла идут параллельно в `ChainThreadPool`, сами бандлы — по очереди. Это для случая, когда нужен параллелизм, а не передача данных между ветками.

## Подводные камни

1. Линейный граф на `DagRunnable` работает, но дороже: сборка словарей портов на каждый шаг. Берите его только для нелинейного графа.
2. У `DagRunnable` ветка со `skip` молча даёт `None` на входе следующих нод. Операции в графе со слияниями должны это переживать.
3. Для cross-process шага в `DagRunnable` выходом ноды становится её собственный вход, а результат удалённой обработки доходит только через `result.detections`. Нода, чьи потребители ждут преобразованный кадр, получит непреобразованный.

## Что осталось открытым

- Где в проекте код выбирает между двумя исполнителями, я не нашёл. README называет `builder.py` в прототипе, но поиск `is_nonlinear_graph|DagRunnable(|ChainRunnable(` по `multiprocess_prototype/*.py` ничего не дал. Возможно, сборка переехала в `Plugins/` или `Services/`, туда я не смотрел.
- Пункты 2 и 3 из подводных камней выведены из чтения кода, их поведение я не воспроизводил.
- Индекс qex недоступен: Ollama не запущена, и `get_indexing_status` я не вызывал.

## single / q7 / ход 1 / rep2 / C (337 слов)

`ChainRunnable` годится для линейной цепочки, `DagRunnable` нужен, когда в графе есть ветвление или слияние. Критерий в коде — `is_nonlinear_graph()` (`graph/topology.py:62`). Он возвращает `True`, если у ноды больше одного входа или больше одного потребителя.

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Топология | Список шагов, один за другим | Топологический порядок + карта входов `node_inputs` |
| Передача данных | Выход шага — вход следующего (`current_frame`) | `port_data[node_id][port]`, ноды связаны именованными портами |
| Ветвление 1→N, слияние N→1 | Нет | Да |
| Интерфейс операции | `execute(frame, ctx) → frame` | `execute_dag(inputs, ctx) → dict`, иначе legacy `execute` с обёрткой в `{"out": …}` |
| Тип payload | Любой, исполнитель его не разбирает: `np.ndarray` или `list[dict]` | Заявлен `np.ndarray` |
| Ошибка шага | `on_error`: `break` или `continue`, кадр остаётся прежним | `on_error`: `break` или `continue`, выход ноды = `{}` |
| Итоговый кадр | Выход последнего шага | `out` последней ноды в топологии, иначе первый `ndarray` из её выходов |
| Cross-process шаг | `execute_remote`, кадр идёт дальше без изменений | `execute_remote`, но в `port_data` кладётся входной кадр, а не ответ |

**Когда что брать**
- **`ChainRunnable`:**
  - граф линейный, это большинство цепочек;
  - payload не кадр, например processing-pipeline с `list[dict]`;
  - нужно минимум накладных расходов: нет словарей портов и разбора соединений.
- **`DagRunnable`:**
  - есть разветвление одного выхода на несколько нод или слияние нескольких входов в одну;
  - ноды должны различать входы по именам портов.

**Ограничения `DagRunnable`**
- Исполнение строго последовательное: ветви идут по очереди в порядке топологии, параллелизма нет.
- У cross-process ноды единственный порт — `"out"`, и в нём лежит входной кадр, а не результат удалённой ноды. Поэтому следующие за ней ноды видят кадр до обработки.
- Если ноде не хватает данных от источника, она получает `None` на этом порту.

**Третий вариант: `ParallelChainRunnable`** (`core/parallel.py`)
- Бандлы идут последовательно, шаги внутри бандла — параллельно через `ChainThreadPool`.
- Берите его, когда нужна параллельность независимых шагов.
- Cross-process шаги в нём исполняются синхронно.

**Что я не проверял**
- Как именно приложение выбирает исполнитель: вызывает ли оно `is_nonlinear_graph()` и где. Проверял только `chain.py`, `dag.py`, `parallel.py` и `topology.py`. Qex недоступен, потому что Ollama не запущен.
- Поведение `DagRunnable` при нескольких конечных нодах: итог берётся только из последней ноды в топологии.

## single / q7 / ход 1 / rep2 / D (355 слов)

`ChainRunnable` годится для линейной цепочки, `DagRunnable` нужен при ветвлении 1→N или слиянии N→1. Оба исполняют шаги последовательно в одном потоке, параллельности ни у одного нет.

## Сравнение

| | `ChainRunnable` (`core/chain.py`) | `DagRunnable` (`core/dag.py`) |
|---|---|---|
| Топология | Линия: шаг N получает выход шага N−1 | Граф с ветвлениями 1→N и слияниями N→1 |
| Конструктор | `steps` | `steps` + `topology` (порядок `node_id`) + `node_inputs` (связи) |
| Передача данных | Одна переменная `current_frame` | `port_data[node_id] = {порт: значение}` |
| Интерфейс операции | `operation.execute(frame, ctx)` | `execute_dag(inputs, ctx)` → `dict`. Если его нет, вызывается `execute(frame, ctx)`, результат кладётся в `{"out": frame}` |
| Payload | Любой (duck-typed): `ndarray` или `list[dict]` | Аннотирован как `np.ndarray`. Начальные данные лежат в виртуальном источнике `"frame"`, порт `"out"` |
| Результат | Выход последнего выполненного шага | Порт `"out"` последнего узла в топологии. Если порта нет, берётся первый `ndarray` из его выходов |
| Cross-process шаг | Детекции добавляются, кадр идёт дальше без изменений | То же, но `port_data[node_id] = {"out": вход}` |
| Ошибка с `skip` | Шаг пропущен, `current_frame` остаётся прежним | `port_data[node_id] = {}`, у потребителей вход станет `None` |

## Когда что использовать

- **`ChainRunnable`:** pipeline из шагов «blur → threshold → detect». Подходит и для processing-pipeline над `list[dict]`, потому что исполнитель payload не интерпретирует.
- **`DagRunnable`:** один кадр идёт в две ветки (например, детекция и измерение), а потом результаты сливаются. Нужны именованные порты.
- **Выбор между ними:** `is_nonlinear_graph(nodes)` из `graph/topology.py` возвращает `True` при ветвлении или merge. Тогда строят `DagRunnable`, иначе `ChainRunnable`. Тесты этой функции лежат в `tests/test_topology.py`.
- **Параллельное исполнение:** это отдельный третий класс, `ParallelChainRunnable`. Он использует `ChainThreadPool` и `detect_parallel_bundles`: бандлы идут по очереди (barrier), шаги внутри бандла — параллельно. Для остальных случаев `WorkerPoolDispatcher` выносит шаги в другие процессы.

## Что надо учитывать

- Если у линейного графа есть `DagRunnable`-ветка, цепочка работает медленнее и сложнее. `ChainRunnable` проще и не требует `topology`/`node_inputs`.
- В `DagRunnable` падение узла с `skip` даёт `None` во входах следующих узлов. Операции должны это переносить.

## Что я оставил открытым / ненадёжным

- Я не нашёл в этом запуске, где прототип выбирает между классами. Поиск `is_nonlinear_graph` показал только фреймворк и тесты. Код `builder.py` в `multiprocess_prototype/` я не читал.
- Бандлы `ParallelChainRunnable` описаны по README. Исходник этого класса я не открывал.
- Ничего не запускал, вывод построен только на чтении кода.

## single / q8 / ход 1 / rep1 / A (698 слов)

Ниже находки по pickle в `shared_resources_module`. Ни одну из них я не воспроизводил запуском: всё это чтение кода и grep. `ollama` не запущен, поэтому `qex` не использовал.

В коде модуля нет ни одного `pickle.loads`/`dumps` вне тестов. Pickle идёт неявно: через spawn `multiprocessing.Process` и `mp.Queue`. Постоянных pickle-файлов на диск я не нашёл.

## Находки

| # | Риск | Файл | Суть |
|---|------|------|------|
| 1 | Высокий (по коду, не проверено запуском) | `core/shared_resources_manager.py:37-55,471-476`, `events/core/manager.py:270-296` | `__getstate__` работает по denylist. Ключ `_windowed_voices` (`threading.Lock`) исключён только в `ObservableMixin.__getstate__` (`base_manager/mixins/observable_mixin.py:941`). SRM и `EventManager` переопределяют `__getstate__` без `super()` и этот ключ не исключают. Холдер создаётся лениво при первом «голосе» (`observable_mixin.py:299-303`). Если SRM или `EventManager` озвучат что-то до spawn, ждите `TypeError: cannot pickle '_thread.lock'`. Тот же список исключений скопирован в трёх местах. |
| 2 | Высокий | `queues/core/manager.py:305-309` | `put_nowait` в `mp.Queue` возвращает `True` до сериализации. Pickle идёт в feeder-потоке, поэтому непиклуемый payload теряется. Об этом знает только stderr feeder-потока, а `send_to_queue` вернул `True`. Ветка `except` в `send_to_queue` такой случай не ловит. Тест `test_observability_queue_split.py:168` имитирует `TypeError("cannot pickle…")` как исключение внутри `put`, а в реальности оно приходит из feeder-потока. |
| 3 | Средний | `state/process_data.py:245-255` против `:221-239` | `to_dict()` фильтрует `custom` по типам, а `__getstate__` пиклит `custom` целиком. Комментарий в `core/shared_resources_manager.py:115-118` говорит, что `custom` рассылается через Queue. Значит, любой не-pickle объект в `custom` ломает рассылку. `data_schema_module/storage/storage_manager.py:117-122,280` кладёт в `custom` `MANAGERS_KEY`. Я не проверил, живые это объекты или данные. |
| 4 | Средний | `queues/core/reader_gone.py:53-59` | `ReaderGoneQueue` опирается на приватный формат `mp.Queue.__getstate__()` (кортеж в CPython). Тесты уже оговаривают, что в Python 3.14+ `Queue`/`Event` ведут себя иначе (`tests/test_handles.py:188`). Обновление Python может молча сломать spawn-pickle этого класса. |
| 5 | Средний | `core/shared_resources_manager.py:437-446` | После unpickle `__getattr__` отдаёт `_noop` на любой `_log_*`/`_record_*`/`_track_*`. Если `__setstate__` что-то потеряет, SRM будет молча терять логи и метрики. Это противоречит правилу «Log errors, don't suppress». |
| 6 | Средний (если путь живой) | `memory/format/buffer.py:221,297` | Кадр, не влезший в SHM, уходит pickle-fallback'ом по pipe. На стенде 2026-09-29 так падал каждый mono-кадр (комментарий в коде). Это скрытая деградация: pickle мегабайтного ndarray блокирует и греет CPU, а ошибки нет. |
| 7 | Низкий (для локального приложения) | `modules/**` (кроме тестов) | grep по `weights_only|Unpickler|find_class|authkey|hmac` ничего не нашёл. Allowlist классов нет, `pickle.loads` в `mp.Queue` выполняет любой reduce-gadget. Граница доверия — только ОС (pipe-хэндлы детей одного пользователя). Для сети или файлов это было бы критично, для локального приложения — нет. |
| 8 | Низкий | `memory/core/manager.py:139-153` | `reinitialize_handles` открывает SHM по именам из `custom["memory_names"]` через `po.open_shm_block(shm_name)`. Я не видел проверки префикса или принадлежности имени. Тот, кто может писать в `custom`, получит чужой блок. |
| 9 | Низкий | `config_store/config_store.py:22`, `state/process_data.py:83-86,122-126` | Классы пиклятся по пути модуля (`ProcessStatus`, `EventType`, `ProcessData`). Сейчас это безопасно: родитель и ребёнок на одном коде и ничего не лежит на диске. Если кто-то начнёт сохранять pickle на диск, переименование модулей (как при carve-out `sql_module`) сломает загрузку. |

## Что оставил открытым / ненадёжно

- Не определил, какой путь передачи SRM живой. Документация (ADR-021) говорит про прямой pickle SRM, а `process_manager_module/runner/bundle_builder.py:53,122` собирает в ребёнке новый SRM из bundle (соседям там кладутся пустые конфиги). Если живой путь — bundle, то находки 1 и 5 переходят из «прямого» риска в «только если SRM пиклят где-то ещё».
- Находка 1 — чтение кода. Я не запускал `pickle.dumps(srm)` после вызова `_voice`.
- Находка 2 опирается на то, как устроен `multiprocessing.Queue` в CPython. Я не прогонял это на проекте.
- В `custom` не проверял, что реально лежит в рантайме (находка 3). Нужен дамп `ProcessData.custom` на живом стенде через `backend_ctl`.
- Не смотрел тесты на покрытие этих путей. Pickle-тесты SRM идут без очередей, потому что `Queue` пиклится только через spawn (`tests/test_process_data.py:38`, `tests/test_shared_resources_manager.py:90-91`). Реальный путь покрывает только интеграционный тест.

Если нужно, возьму находки 1 и 2: напишу падающие тесты и проверю их в изоляции.

## single / q8 / ход 1 / rep1 / C (586 слов)

Главные риски: неотлавливаемая потеря непиклуемого payload, зависимость от приватных внутренностей `multiprocessing` и зависание выхода процесса на пиклуемой записи. Всё найдено чтением кода. Тесты и код я не запускал.

**Высокий риск**

1. **Непиклуемый payload теряется молча.** `send_to_queue` кладёт сообщение через `put_nowait` (`queues/core/manager.py:306-308`). `mp.Queue` пиклит его в feeder-потоке, а не в вызывающем. Отправитель получает `True`, ошибка остаётся в stderr feeder-потока. Это поведение stdlib, в этом коде я его не воспроизводил. Защита стоит только на сборке: `_pickle_sanity` в `app_module/builder.py:507-527` проверяет blueprint, `proc_dicts`, `initial_state` и `throttle_rules`. Рантайм-сообщения не проверяются.

2. **Выход процесса может висеть без срока.** Пиклёный кадр крупнее свободного места в pipe блокирует feeder. Выход интерпретатора ждёт его бесконечно (`queues/core/reader_gone.py:1-29`). Лечение через `ReaderGoneQueue` оставляет потери: до одного сообщения в полёте и всё, что уже в pipe, пропадает без счёта (`reader_gone.py:90-91`, `107-110`). У немаркированной очереди таймера нет (`reader_gone.py:24-28`). Зависший живой читатель держит писателя бессрочно.

3. **`ReaderGoneQueue` держится на приватном API `multiprocessing`.**
   - `from multiprocessing.queues import _sentinel` (`reader_gone.py:36`).
   - Поля `_buffer`, `_notempty`, `_thread` (`reader_gone.py:87-93`, `132`).
   - Формат состояния `super().__getstate__()` (`reader_gone.py:53-59`).

   Смена версии Python может сломать spawn или выход процесса.

**Средний риск**

4. **`SharedResourcesManager.__getstate__` — denylist.** Метод копирует весь `__dict__` и вычитает 15 имён из `_PICKLE_EXCLUDE` (`core/shared_resources_manager.py:37-55`, `471-476`). Новое непиклуемое поле в `BaseManager` или `ObservableMixin` ломает spawn при старте процесса, а не на этапе тестов.

5. **Queue и Event пиклятся только через `Process(args=…)`.** Прямой `pickle.dumps` падает (`tests/test_handles.py:186-193`, `tests/test_process_data.py:38`). Юнит-тесты round-trip гоняют SRM без очередей (`tests/test_shared_resources_manager.py:90`). Реальный путь покрывают только интеграционные тесты через `Process`. `ProcessData` с очередями нельзя отправить в очередь или сохранить на диск. Поэтому `_system_stop_event` держат вне `custom` (`shared_resources_manager.py:115-119`).

6. **Pickle-fallback для кадров остаётся.** Если запись в SHM не удалась, numpy-кадр идёт через pipe (`router_module/middleware/frame_shm_middleware.py:716-728`, `840`, `1304`; `memory/format/buffer.py:297`). Прошлый случай: mono-кадры `(H, W)` падали в fallback 15 из 15 (`DECISIONS.md:535`, `memory/tests/test_format.py:131`). Исправлено, но форма кадра зависит от способа доставки (`buffer.py:47`). Счётчик `frame_pickle_fallbacks` есть, порога тревоги я не нашёл.

7. **Ребёнок получает снимок, а не общее состояние.** SRM копируется в момент spawn, а PSR рассчитан на один процесс (`state/process_state_registry.py:4-5`). Позднее `register_process` в родителе до детей не дойдёт. Для очередей это смягчено через `reuse_queues` (`shared_resources_manager.py:175-181`).

**Низкий риск**

8. **`unpickle` исполняет код.** Любой процесс с дескриптором очереди может подсунуть `__reduce__`. Границы доверия между процессами фреймворка нет. Каналы — анонимные pipes, внешнему атакующему они недоступны. `pickle.loads` на внешних данных в `multiprocess_framework` вне тестов нет: grep нашёл только `pickle.dumps` в `app_module/builder.py:527`.

9. **Ручные `__getstate__`/`__setstate__` в пяти местах:** SRM, PSR (`state/process_state_registry.py:39-47`), `ReaderGoneQueue`, `QueuesProxy` и `EventsProxy` (`state/process_data.py:83`, `122`). Каждый нужно править вместе с полями класса.

**Что я оставил открытым или ненадёжным**
- Не проверил, что `EventManager` исключает `_event_queue` из pickle после замены на `queue.Queue` (`events/core/manager.py:104`). Это видно из `tests/test_event_manager.py:117-127`, но тесты я не запускал.
- Пункт 1 опирается на знание stdlib, без воспроизведения. Как именно `tests/test_observability_queue_split.py:168` обрабатывает `TypeError`, я не читал.
- Не смотрел `Services/` и `Plugins/`. Там могут быть свои `pickle.loads` и непиклуемые payload.
- Qex и sentrux не использовал, только `Grep` и `Read`. Вывод grep был обрезан `head_limit`, возможны пропуски `__getstate__` в других файлах.

## single / q8 / ход 1 / rep1 / D (610 слов)

Pickle в `shared_resources_module` неявный: он идёт через `multiprocessing` (`Process(args)` и `Queue`). Прямых `pickle.load` в `multiprocess_framework/` нет, кроме проверки `pickle.dumps` в `app_module/builder.py:527`. Файл читал статически, ничего не воспроизводил. Находки по убыванию важности:

1. **Копии состояния расходятся.**
   - Каждый ребёнок получает собственную копию `ProcessData.custom/metadata/status` и конфигов.
   - Поэтому правки родителя после spawn ребёнок не видит. Это относится к `custom["memory_names"]`, статусу и `routing_epoch`.
   - Файлы: `state/process_data.py:245-270`, `core/shared_resources_manager.py:471-479`. Бандл и снимок `routing_meta` на момент спавна — `process_manager_module/runner/bundle_builder.py:43-140`, `core/process_registry.py:217`.

2. **Логи теряются после spawn.**
   - Комментарий в `queues/core/manager.py:30-56` фиксирует замер: `ObservableMixin.__getstate__` выкидывает `_registry`, и логгер не переживает pickle. Итог: 26 тысяч событий потери дали 0 строк в `logs/`.
   - Обход сделан только в `queues/core/manager.py` (через `get_std_logger`).
   - В `core/shared_resources_manager.py:446-447` любой `_log_*` по-прежнему возвращает `_noop`. Поэтому `_log_error` в строках 143, 155, 221, 315 молчит, если logger не передан. По комментарию, ни один продовый вызов его не передаёт.

3. **Ошибка pickle в feeder-потоке не доходит до отправителя.**
   - `send_to_queue` (`queues/core/manager.py:298-309`) возвращает `True` после `put_nowait`.
   - Сериализация идёт позже, в фоновом потоке `mp.Queue`. Непиклябельный payload, по моему знанию CPython, теряется с traceback в stderr (не воспроизводил).

4. **Две несовпадающие denylist-ы для `custom`.**
   - `process_registry.py:195-196` вычищает 5 ключей: `stop_event`, `error_manager`, `pause_event`, `system_ready_event`, `system_stop_event`.
   - `process_data.py:224-229` (`to_dict`) вычищает 3 ключа плюс фильтр по типам.
   - Новый ключ с `Event` или `Queue` вне списков роняет `Process.start()`. Прямой `pickle.dumps` очереди и события падает с `RuntimeError "only through inheritance"`. Это отражено в `shared_resources_manager.py:115-119`.

5. **`__getstate__` строится как denylist.**
   - `__dict__.copy()` минус 15 имён: `shared_resources_manager.py:37-55`, `471-476`.
   - Тот же список продублирован в `events/core/manager.py:270-296`.
   - Новое замыкание в `ObservableMixin` или новый сырой `Event` в атрибутах ломает spawn. `_system_stop_event` (строка 119) защищён только дисциплиной «SRM не кладут в очередь».

6. **Зависимость от приватного формата `mp.Queue`.**
   - `ReaderGoneQueue.__getstate__` (`queues/core/reader_gone.py:53-59`) оборачивает `super().__getstate__()` в кортеж.
   - Формат приватный. Смена версии Python (в тестах уже упомянут 3.14: `tests/test_handles.py:188`) может его сломать.

7. **Кадры уходят в pickle-fallback.**
   - При любом исключении в `pack_images` кадр целиком пиклится в pipe: `memory/format/buffer.py:297`.
   - Замер из `DECISIONS.md:534`: 15 из 15 кадров ушли в fallback. Для mono это исправлено на `buffer.py:221`, остальные ошибки остаются видны только по счётчику `frame_pickle_fallbacks`.

8. **Границы доверия при unpickle.**
   - `__setstate__` делают `__dict__.update(state)` без проверок: `process_data.py:257`, `shared_resources_manager.py:478`, `events/core/manager.py:298`.
   - Это безопасно, пока все процессы свои. Любой, кто пишет в pipe очереди, получает исполнение кода. Это общее свойство pickle, в коде не проверял.

9. **Конфиги целиком в pickle.**
   - `ConfigStore.store` копирует весь dict (`config_store/config_store.py:36`), `process_config` едет в `custom` (`bundle_builder.py:56-57`).
   - Ребёнок получает только свой конфиг, соседям ставится пустой (`bundle_builder.py:122`). Процесс-менеджер из `spawner.py:89` держит все. Секреты в конфиге уходят в pipe без фильтра.

10. **Юнит-тесты не проверяют настоящий pickle.**
    - `tests/test_shared_resources_manager.py:90-91`, `tests/test_handles.py:197-203` и `tests/test_process_data.py:125-131` пиклят SRM без Queue/Event.
    - Реальный spawn проверяет только интеграционный тест через `multiprocessing.Process`.

**Что оставил открытым или ненадёжно:**
- Пункты 3 и 8 опираются на знание CPython, а не на запуск.
- Пункт 2 взят из комментария в коде и не перемерен.
- `pickle.load` и `pickle.dump` искал только в `multiprocess_framework/`. `Services/`, `Plugins/` и `multiprocess_prototype/` не смотрел.
- Фактическое содержимое `process_data.custom` в боевом запуске не снимал. Нужен прогон `backend_ctl`.
- qex не использовал: Ollama не запущен, поиск шёл через Grep.

## single / q8 / ход 1 / rep2 / A (835 слов)

Прямого `pickle.load*` в `shared_resources_module` нет: grep по нетестовому коду пуст. Pickle работает неявно. `multiprocessing` пиклит объекты при `spawn`, а `__getstate__`/`__setstate__` модуль пишет сам. Из-за этого риски лежат в этих методах и в допущениях вокруг них. Ни одну находку я не воспроизвёл запуском: Bash в этой сессии отключён, всё получено чтением кода.

## Находки

**1. `__getstate__` работает по чёрному списку (высокий риск).**
- `shared_resources_manager.py:37-55` и `:471-476` берут `self.__dict__.copy()` и вычёркивают известные плохие ключи. То же сделано в `events/core/manager.py:270-296` и в `ObservableMixin.__getstate__` (`base_manager/mixins/observable_mixin.py:917`).
- Любой новый атрибут уезжает в pickle молча. Пример уже есть: `_system_stop_event` (сырой `mp.Event`) лежит в `__dict__` SRM (`:119`, ставится в `process_runner.py:336`). Комментарий на `:115-118` признаёт, что Event пиклится только через inheritance.
- Если SRM пиклить вне spawn, он упадёт с `RuntimeError`. Белого списка нет.

**2. У `MemoryManager` нет `__getstate__` (средний риск, гипотеза).**
- `memory/core/manager.py:77-88` держит `_local_handles` (`SharedMemory`) и `_owned_names`. В SRM-пикле они едут целиком.
- Если `_owned_names` доедет до ребёнка, он сочтёт блоки родителя своими и сделает `unlink` на shutdown. Это ровно тот сценарий, который правка A-1 в комментарии `:81-87` должна была закрыть.
- Не воспроизведено.

**3. Документ и боевой путь расходятся (средний риск).**
- ADR-021 и docstring (`shared_resources_manager.py:4-12`) говорят «прямой pickle SRM».
- Боевой путь другой: ребёнок собирает SRM из bundle-словаря (`process_runner.py:319-322`, `bundle_builder.py:53-132`). Прямой pickle остаётся запасной веткой.
- Тесты `test_shared_resources_manager.py:90-135` пиклят SRM без Queue и Event. С реальными объектами пикл проверен только в интеграционном тесте через `Process`. Ветка, которая заявлена как основная, на практике почти не исполняется.

**4. Формулировка «Queue/Event нативно pickle-able» вводит в заблуждение (средний риск).**
- Так написано в `process_data.py:137`, `process_state_registry.py:6`, `queues/README.md:5`. На деле пикл работает только во время spawn.
- `test_handles.py:188` прямо говорит, что в Python 3.14+ `pickle.dumps()` на них не работает.
- `ReaderGoneQueue.__getstate__` (`reader_gone.py:53-59`) наследует это ограничение. Передать `ProcessData` или очередь через другую очередь нельзя, для границы остаётся только `to_dict()` (`process_data.py:221`).
- Тот же файл опирается на приватные внутренности CPython: `multiprocessing.queues._sentinel` (`:36`), `_buffer`, `_thread`, `_notempty` (`:92`, `:132`). Это сломается при смене версии Python.

**5. `__getattr__` молча глотает логи после unpickle (средний риск).**
- `shared_resources_manager.py:437-446` отдаёт `_noop` на любые `_log_*`, `_record_*`, `_track_*`.
- `queues/core/manager.py:30-56` описывает последствие: 26 тысяч событий потери и 246 вытеснений дали 0 строк в `logs/`.
- Корень в том, что `_registry` не переживает pickle, поэтому лог-плоскость в ребёнке мертва. Этим нарушено правило «Log errors, don't suppress». Из этого файла её обошли отдельным `get_std_logger`, но сам механизм остался.

**6. Ребёнок получает снимок состояния, а не общее состояние (средний риск).**
- `process_state_registry.py:39-47` копирует `states`, а `RLock` создаёт заново. `ConfigStore` тоже копируется.
- Общими остаются только `Queue`, `Event` и SHM. Статусы, `custom` и список процессов, изменённые в родителе после spawn, ребёнок не увидит.
- Это компенсируется routing-epoch (`bundle_builder.py:59-124`), то есть ещё одним механизмом поверх.

**7. Конфиги всех процессов уезжают в каждого ребёнка (низкий–средний риск, гипотеза).**
- `ConfigStore` (`config_store.py:22`) пиклится целиком. Если в конфигах есть секреты, их получит каждый процесс.
- В bundle-пути соседям кладут пустой конфиг (`bundle_builder.py:122`), так что там проблемы нет. Она есть только в прямом пикле. Содержимое реальных конфигов я не смотрел.

**8. Кадры падают в pickle-fallback через pipe (средний риск).**
- Если запись в SHM сорвалась, `write_images` возвращает `None`, и кадр идёт через pickle (`memory/format/buffer.py:221`, `:297`). В `DECISIONS.md:534` описан случай, когда так ушли 15 кадров из 15.
- Большие кадры в pipe держат feeder-поток. Именно поэтому понадобился ADR-SRM-016 (`reader_gone.py`): процесс вис на выходе.
- Счётчик `frame_pickle_fallbacks` есть, но громкого сигнала нет.

**9. Откат на `INITIALIZING` при неизвестном статусе (низкий риск).**
- `process_data.py:264-268` при `ValueError` молча ставит `INITIALIZING`. Расхождение версий `ProcessStatus` маскируется.
- Родитель и дети собраны из одного кода, поэтому сейчас это скорее запас на будущее.

**10. Небезопасная десериализация (низкий, условный риск).**
- `pickle.loads` исполняет код. Каналы здесь локальные: pipe и spawn между доверенными процессами.
- Риск появится, если объект из внешнего источника (Hikvision, OPC UA, файл) попадёт в `Queue` как есть. Правило Dict at Boundary это сдерживает, но сам модуль ничего не проверяет.

## Что я оставил открытым или ненадёжным
- Пункты 2 и 7 — гипотезы по чтению кода. Проверить пункт 2 можно так: `register_process` с `memory`, затем `pickle.loads(pickle.dumps(srm))`, затем сравнить `_owned_names` до и после. Bash недоступен, поэтому я этого не запускал.
- Не проверил, что `BaseManager` кладёт в `self.process` и пиклится ли это в SRM (пункт 1).
- Не смотрел, что именно лежит в `ProcessData.custom` в боевом запуске, и какие объекты туда можно положить.
- Индекс qex не использовал: Ollama не запущен. Всё найдено через `Grep` и `Read` только в `shared_resources_module` и трёх файлах `process_manager_module/runner/`. Остальные модули на `pickle` не проверялись.

Если нужно, подготовлю порядок исправлений. Начать стоит с пунктов 1 и 3: перейти на whitelist в `__getstate__` и привести ADR-021 к реальному bundle-пути.

## single / q8 / ход 1 / rep2 / C (539 слов)

Явных `pickle.loads` в боевом коде `multiprocess_framework`, `Services`, `Plugins` и `multiprocess_prototype` нет: они только в тестах. Pickle работает неявно, через `multiprocessing` (spawn на Windows и `Queue`). Ниже находки; я читал код, но ничего не запускал и не воспроизводил.

## Находки

1. **Чёрный список вместо белого в `SharedResourcesManager.__getstate__`.** Метод копирует весь `__dict__` и вычёркивает 14 имён из `_PICKLE_EXCLUDE`. Любой новый непиклуемый атрибут (замок, сокет, handle) попадёт в pickle и упадёт при spawn. Тот же шаблон в `events/core/manager.py:270`, где 19 имён вычёркиваются списком `_EXCLUDE`. Файл: `core/shared_resources_manager.py:37,471`.

2. **`self.process` сериализуется вместе с SRM.** `BaseManager` кладёт `self.process = process` (`base_manager/core/base_manager.py:49`). `ObservableMixin.__getstate__` его не вычёркивает (`observable_mixin.py:917`), `SharedResourcesManager.__getstate__` тоже. Если SRM создан с `process=<ProcessModule>`, в pickle уедет весь объект процесса. Это моё предположение по чтению кода, живым прогоном я его не проверял.

3. **`__getattr__` подавляет ошибки после unpickle.** `_log_*`, `_record_*`, `_track_*` и `_call_manager` молча возвращают `_noop`. Если атрибут потерялся при unpickle, метод логирования ничего не делает и не падает. Сбой логирования в дочернем процессе остаётся невидимым. Файл: `core/shared_resources_manager.py:31,437-446`.

4. **`_system_stop_event` лежит в `__dict__` SRM.** Комментарий в `core/shared_resources_manager.py:115-118` объясняет: сырой `mp.Event` пиклится только через inheritance при spawn. Блокировки при этом нет. Если SRM-копию когда-нибудь отправят через `Queue`, она упадёт с `RuntimeError`, а не при spawn.

5. **`ProcessData.custom` — произвольный `Dict[str, Any]` и едет в pickle целиком** (`state/process_data.py:142,245-255`). Туда кладут `stop_event`, `ready_event`, `error_manager`, `process_config` (`process_manager_module/runner/process_runner.py:202`, `launcher/spawner.py:111`, `core/process_registry.py:233`). Защита есть только в `to_dict()`: он оставляет в `custom` примитивы, `dict` и `list`. Прямой pickle `ProcessData` ничего не фильтрует. Контракт «в `custom` нет непиклуемого» держится на дисциплине вызывающих.

6. **Десериализация без проверки доверия.** Если `Queue` когда-нибудь станет доступна за пределами доверенных процессов, например через сеть, это даст возможность выполнить произвольный код. Сейчас очереди создаются внутри одной машины и наследуются дочерними процессами. Риск теоретический.

7. **Pickle-путь для кадров как запасной, и этот запасной путь дорогой.** Если запись кадра в SHM не удалась, кадр идёт через pickle по pipe. Известный случай: mono-кадры `(H, W)` падали в этот путь (`memory/format/buffer.py:221`, стенд `code_reader_sdk` 2026-09-29, исправлено). Тест на это: `memory/tests/test_format.py:131`. Другие кадры по-прежнему могут молча уходить в тот же запасной путь.

8. **Хрупкость между версиями Python.** Тесты это признают: `Queue` и `Event` в Python 3.14+ пиклятся только через `Process` (spawn), не через `pickle.dumps()` (`tests/test_handles.py:188`). Поэтому юнит-тесты берут SRM без `Queue`/`Event` (`tests/test_shared_resources_manager.py:90`), а полный round-trip покрыт только интеграционными тестами.

9. **Нет проверки версии при unpickle.** `__setstate__` (`core/shared_resources_manager.py:478`, `state/process_data.py:257`) делает `__dict__.update(state)` без версии схемы. Это работает, пока родитель и ребёнок — один и тот же код в одном процессе-дереве. Версионного поля или миграции нет.

## Что остаётся открытым и ненадёжным

- Находки 2, 4, 6, 7 — по чтению кода, без воспроизведения; воспроизводить нужно `pickle.dumps` от SRM с реальным `process=...`.
- Список вызывающих, которые кладут в `ProcessData.custom`, неполный: я смотрел только `process_manager_module` и `data_schema_module`, `Services` и `Plugins` — нет.
- Индекс qex не проверял, Ollama не запущен. Поиск шёл грепом по путям.

## single / q8 / ход 1 / rep2 / D (639 слов)

Явных `pickle.load`/`dumps` вне тестов в `shared_resources_module` нет, это проверено grep. Pickle идёт неявно: при spawn SRM уходит в дочерний процесс, а `Queue.put` сериализует сообщение. Сетевого или файлового входа pickle в модуле нет. Классический риск (RCE при чтении чужих данных) ограничен каналом OS-pipe между своими процессами. Ниже находки по убыванию значимости.

## Надёжность

1. **Непикловое значение в конфиге не ловится при регистрации.** `ConfigStore.store` проверяет только `isinstance(config, dict)` и делает неглубокую копию (`config_store/config_store.py:32-36`). Лямбда, Lock или логгер во вложенном значении пройдут. Упадёт это позже, при `Process.start()` или при отправке.
2. **`ProcessData.custom` пиклится целиком, фильтр типов есть только в `to_dict`.** См. `state/process_data.py:250` против `:224-229`. Комментарии в `spawner.py:112` и `shared_resources_manager.py:115` подтверждают, что сырой `mp.Event` в `custom` ломает рассылку через Queue. Из знаний о CPython (в репо не проверял): `mp.Queue` пикует в feeder-потоке. Тогда `put_nowait` в `queues/core/manager.py:308` вернёт `True`, а сообщение пропадёт с трейсбеком только в stderr.
3. **Каждый ребёнок получает свою копию PSR.** Общими остаются только Queue, Event и SHM. Статусы, `metadata` и `custom` в детях расходятся с родителем; сам PSR заявляет «только из одного процесса» (`state/process_state_registry.py:4-5`). Очереди убитых процессов остаются в копии (`process_manager_process.py:3014`). Частично лечат `clear_queues` (`process_data.py:180-192`) и `unregister_process` (`shared_resources_manager.py:223-261`).
4. **`reinitialize_in_child()` вызывается вручную.** `EventManager.__setstate__` обнуляет `_event_queue` и `_router_manager` (`events/core/manager.py:298-303`). `reinitialize()` возвращает только очередь (`:97-111`). Если вызов забыт, `emit_event` молча не кладёт событие в очередь (`:155`). Роутер к ProcessManager не вернётся и после вызова, пока владелец не вставит его заново.
5. **Сбои в ребёнке тихие.** `SRM.__setstate__` просто делает `__dict__.update` (`shared_resources_manager.py:478-479`). Он не вызывает `ObservableMixin.__setstate__`, поэтому нет `_registry` и публичных `log_*`. Приватные `_log_*` отдаёт `_noop` (`:446-447`). Ни один продовый вызов `SharedResourcesManager(...)` не передаёт logger (`queues/core/manager.py:30-47`). Значит, `_log_error` в `register_process` (`:220`) и `reinitialize_in_child` (`:315`) ничего не пишут.
6. **Список исключений из pickle продублирован трижды.** Он есть в `shared_resources_manager.py:37-55`, `events/core/manager.py:272-292` и `base_manager/mixins/observable_mixin.py:920-942`. Только в миксине есть `_windowed_voices` (с Lock). Сейчас `_voice` зовёт только `QueueRegistry` (`queues/core/manager.py:290,362,564`), у него `__getstate__` из миксина, поэтому дефект латентный. Первый же `_voice` в SRM или EventManager даст `TypeError` при spawn.
7. **Queue и Event пиклятся только во время spawn.** Тесты это отмечают (`tests/test_process_data.py:38`, `tests/test_handles.py:188`). Поэтому SRM с зарегистрированными процессами не скопировать и не снять snapshot в родителе. Юнит-тесты берут SRM без очередей (`tests/test_shared_resources_manager.py:90-91`), реальная форма покрыта только интеграционно.
8. **`SRM.__getattr__` возвращает `_noop` для любого имени `_log_*`, `_record_*`, `_track_*`** (`shared_resources_manager.py:446-447`). Опечатка в таком имени не падает. Любое имя без `_` трактуется как имя процесса (`:459-465`).

## Безопасность

9. **Allowlist для unpickle нет.** Используются штатные `mp.Queue` и spawn-args без `find_class`. Любой процесс с дескриптором очереди может отправить вредоносный pickle. Это внутренний канал, внешнего входа в модуле нет.
10. **SHM не несёт pickle.** Кадры пишутся через `struct` и `numpy` (`memory/format/buffer.py:207-222`), открываются по именам из PSR (`memory/core/manager.py:127-129`). Через SHM исполнение кода не вставить. Pickle-fallback кадра в `router_module/middleware/frame_shm_middleware.py:1303` даёт латентность ×3, а не дыру.

## Что осталось открытым / недостоверно

- Ничего не запускал: Bash в сессии отключён. Находки 2, 5, 6 выведены чтением кода и знанием CPython, у них нет воспроизведения «вход → выход».
- Внешние источники pickle (`Services/*`, загрузка рецептов с диска) не смотрел. Вывод про отсутствие сетевого входа относится только к `shared_resources_module`.
- Индекс qex не проверял: Ollama не запущен. Использовал `Grep` и `Read` по путям модуля.
- Не проверил, получают ли дети конфиги чужих процессов целиком. `process_manager_module/STATUS.md:64` пишет, что в `ConfigStore` ребёнка кладётся срез. Это сверить с кодом.
