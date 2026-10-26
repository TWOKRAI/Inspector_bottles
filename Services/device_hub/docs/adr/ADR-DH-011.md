# ADR-DH-011 — полный текст

> Вынесено из [DECISIONS.md](../../DECISIONS.md) по размеру (лимит 32 КБ). Текст ADR перенесён дословно; в `DECISIONS.md` остались заголовок, статус и краткая суть.

## ADR-DH-011: `connect`, `request_stop` и обычный `disconnect` драйвера робота v2 линеаризуются переходами `RobotState`

**Дата:** 2026-10-21
**Статус:** accepted (T5.3g; решения лида inspector-bottles-a9 и владельца 2026-10-19, 2026-10-20); дополнен T5.3h (решение владельца 2026-10-21); дополнен C-29 (решения владельца 2026-10-25, В1–В6)
**Контекст задачи:** `plans/robot-protocol-v2/tasks/T5.3g.md`, `T5.3g.design.md`, `T5.3h.md`, `C-29.md`; уточняет ADR-DH-010 (`_ready` теперь в состоянии,
окна W1, W1′, W2, W4 закрыты); ADR-DH-009 (путь стопа) не меняется.

### Контекст

ADR охватывает `connect`, `request_stop` (T5.3g) и обычный `disconnect` посреди `connect` (T5.3h, решение владельца 2026-10-21).

Проба окон барьером (`T5.3g.probe.md`) подтвердила W1, W4 и WW на коде T5.3f: простой робот, которому `request_stop`
пришёл посреди `connect`, не получал SOFT, а `connect()` возвращал True и делал драйвер «готовым» после выключения;
`connect_reset` после стопа снимал `stopping` и «стоп не подтверждён». Правило владельца 2026-10-20: простой робот
посреди `connect` считается подключённым, получает один SOFT и никогда не «готов» после выключения; правило
2026-10-19: неподключённый простой робот SOFT не получает.

### Решение

- **`_ready` живёт в `RobotState`.** На драйвере `_ready` — свойство: геттер читает `state.ready` без замка,
  сеттер зовёт `state.set_ready` под замком. Замок состояния — `Lock`, не `RLock`, а `is_connected` зовётся под ним
  (`process_stop_plan`, `admit_launch`), поэтому геттер замок не берёт (чтение bool атомарно, все записи под замком;
  прецедент — `returns_done`). Записи `False` в `disconnect`, `_link_lost`, `_close_after_disconnect` идут через сеттер.
- **Переходы `connect`.** `connect_begin` (решение `"shutdown"` / `"busy"` / `"go"` + сброс останова + `_ready = False`
  + `_connecting`), `connect_link_up`, `connect_restore`, `connect_finish`, `connect_end`. `connect_link_up`,
  `connect_restore` и `connect_finish` при `_stopping` или `_shutdown` отказывают, `connect()` возвращает False.
  `connect_end` стоит в `finally` и снимает `_connecting` и `_connect_linked` на любом выходе.
- **Точка линеаризации — `request_stop_begin`.** В той же секции, где ставится `_shutdown`, при первом вызове
  запоминается `_stop_linked = _connecting and _connect_linked`. `process_stop_plan(connected, link_up)` берёт этот
  снимок, а не живые флаги: `connect` мог выйти между секциями `request_stop` (W1′), снимок это переживает.
  Дизъюнкт плана: `connected() or (_stop_linked and link_up())`; `link_up` — `transport.is_connected` без `_ready`.
- **Граница A3 — `connect_link_up`.** У настоящего транспорта внутри `connect()` `is_connected` False до
  `Services/modbus/core/device.py:103`, поэтому «связь поднята» — это переход после подключения транспорта (для
  готового до `connect` робота — сам `connect_begin`). Стоп раньше этой границы: записи нет, «стоп не подтверждён»
  не ставится, `connect()` False, `probe` не зовётся.
- **Нет SERVO и DO после стопа — по возможности.** `_run_on_connect` возвращает bool и проверяет `_sync_cancelled()`
  перед `client.servo` и каждым `client.do_set`. Окно «проверка -> запись» остаётся: закрыть его можно только
  сериализацией с путём стопа — вне T5.3g.
- **Обычный `disconnect` посреди `connect`** (`_stopping` без `_shutdown`) тоже отказывает `connect_finish` и
  `connect_restore`: `connect()` → False, `is_connected` False. Побочный эффект: в пути тика, если
  `desired_connected` остался True, отказ считается неудачным переподключением (`_note_reconnect_failed()`).
- **SOFT при обычном «Отключить» посреди `connect` (T5.3h, решение владельца 2026-10-21 «да — SOFT и при обычном
  «Отключить» посреди connect»).** Правило T5.3g для `request_stop` переносится на обычный `disconnect`: простой
  робот, связь которого была поднята к стоп-секции `disconnect` (граница A3; у готового до `connect` робота —
  `connect_begin`), получает ровно один SOFT; до A3 записи нет (правило 2026-10-19), `connect()` False.
  Решение держится и на живом пути: переподключение тика против «Отключить» супервизора.
  - **Снимок в D2.** `disconnect_stop_plan(program_level, link_up)` пишет `_stop_linked` — «связь была поднята» —
    в стоп-секции (D2), а не в `disconnect_begin` (D1): между D1 и D2 `connect` ещё может поднять связь. Выражение
    вычисляется ДО `self._stopping = True` (иначе оно читает свой же флаг) и только при `not _shutdown` (снимок
    `request_stop` не переписывается). Терм `link_up()` живой (`transport.is_connected` в D2): без него готовый робот
    с упавшей вне тика связью давал снимок True, хвост `disconnect` закрывал уже закрытый сокет, а тик открывал его
    снова и не закрывал (утечка сокета, проба H18).
  - **Монотонный снимок.** Оба писателя пишут одно выражение: `(_stopping and _stop_linked) or (_connecting and
    _connect_linked)` (в D2 — с живым `link_up()`). Внутри одного выключения значение только растёт: `request_stop`
    целиком между D2 и D3 снимок `disconnect` не обнуляет (H15). Точка сброса — `connect_begin` (снимает
    `_stopping`). Новых полей нет.
  - **Решение одной секцией.** `disconnect_soft_plan(connected, link_up)`: `connected() or (_stop_linked and
    link_up())` и защёлка не покрывает SOFT. Заменяет `is_connected` и `latch_covers` в `_request_stop`. Отступление
    от «правила 1:1» (см. докстринг `RobotState`): `connected()` теперь зовётся под замком состояния, как в
    `process_stop_plan`.
  - **Один владелец закрытия.** Тик после отказа `connect` при `desired_connected` False не закрывает транспорт,
    если `disconnect_owns_close()` (`_stopping and not _shutdown and _stop_linked`): хвост `disconnect` (D6)
    закрывает всегда, уже после решения о SOFT (H16). Без этого тик закрывал сокет раньше решения о SOFT, и
    `disconnect_soft_plan` не видел живой связи.
  - **Повторная проверка в тике.** `_ensure_connected` после захвата `_param_lock` проверяет `desired_connected`
    ещё раз: «Отключить», пришедшее между первой проверкой и замком, не даёт `probe`, PARAM_SET, SERVO и DO (H13).
- **«Отключить» прерывает `connect` (C-29, решения владельца 2026-10-25, В1–В6).** `request_disconnect` (только у
  робота v2, плагин зовёт через `getattr`, как `request_stop`) вызывается из `cmd_device_disconnect` под
  `_workers_lock` до постановки `disconnect` в очередь; без ввода-вывода, `_param_lock` не берёт.
  - **Точка линеаризации — переход `disconnect_request(link_up)`** под замком состояния: счётчик `_disconnect_requests`
    +1 (В1; не в `view()`), а посреди `connect` — монотонный снимок `_stop_linked` ДО `_stopping = True` и сам
    `_stopping`. Снимок переживает выход `connect` (`connect_end` снимает только `_connecting` и `_connect_linked`),
    поэтому при поднятой связи обычный `disconnect` пишет ровно 1 SOFT; до подъёма связи — 0.
  - **Счётчик.** `connect_begin` при счётчике > 0 отвечает `"cancelled"` (раньше `"busy"`), драйвер возвращает False.
    `disconnect_end` стоит в `finally` `disconnect()`: счётчик −1 (не ниже 0). Два «Отключить» подряд — два
    `disconnect` в очереди — 0.
  - **Супервизор.** Ветка `connect` пропускается, если `_desired_connected.get(dev_id) is False` (только `is False`:
    интеграционные тесты кладут `connect` без записи в словарь). После `manager.connect` под `_workers_lock` desired
    True и `reset_reconnect()` не ставятся, если `_desired_connected[dev_id]` (словарь плагина) False или у драйвера
    `disconnect_pending` (ABA
    `[connect₁, disconnect, connect₂]`). Закрытие окна (б) — замком: «Отключить» и чтение супервизора взаимно
    исключены. Новых замков нет; порядок `_workers_lock` → `_registry_lock` → замок состояния (лист).
  - **Статусы (В3).** Прерванный `connect` не публикует `error`: `manager.connect` при `disconnect_pending`
    публикует `disconnecting`; `conn` — `connecting`, `disconnecting`, `disconnected`.
  - **Отказ `TEXT_DISCONNECTING` = «идёт отключение робота» (В4, В5).** `jog_hold` (check и admit, и продление),
    `jog_step`, `enqueue_job`, `return_job`, `admit_launch` (программа, возврат, смена инструмента);
    `take_next_action` в окне ничего не берёт. Возврат, отказанный в окне, возвращается в очередь (`_BUSY_REPLIES`).
    `servo` / `do_set` не трогаются (решение лида).
  - **Очереди (В6).** Хвост `disconnect` (`disconnect_end`) снимает очереди заданий и возвратов; число — в журнал
    (WARNING) и `last_error` (`TEXT_QUEUE_DROPPED`). Голый `disconnect` без «Отключить» очереди не трогает.
  - `_await_tlm` прерывается по `_sync_cancelled()`: SERVO / DO после «Отключить» не шлются, пока ожидание не вышло.
    `sync_cancelled()` учитывает счётчик: пересинхронизация тика на готовом роботе после «Отключить» не шлёт `PARAM_SET`.

### Отклонено

Обратный вызов из перехода, который ставит `_ready` драйвера: код драйвера выполнялся бы под листовым замком, а W2
остался бы открытым.

### Последствия

- Новых замков нет; порядок `_param_lock` → замок состояния сохранён (переходы зовутся из `connect` под `_param_lock`).
  `connect_check`, `connect_reset`, `is_shutdown` остаются (контрактные тесты).
- Окна W1, W1′, W2, W4 и WW закрыты. `request_stop` после `connect_finish` — по-прежнему 1 SOFT, `connect()` True.
- Остаётся открытым: проба `issue_stop` в WW идёт без бюджета срока (на медленной живой связи до 3 чтений и 1 записи).
- T5.3h: обычный `disconnect` посреди `connect` даёт один SOFT связи, поднятой к D2 (H1–H5, H12, H15, H16; блиндовая
  приёмка B1, B2, B5); `request_stop`, прошедший целиком (с записью) до решения D3, и `disconnect` вместе дают всего один SOFT (H14, H15, H17).
- **Остаток I1 (сужен, не закрыт).** Тик прошёл обе проверки `desired_connected` (в `_ensure_connected` и под
  `_param_lock`), затем супервизор ставит `desired_connected = False` и проходит D1–D6, затем `connect_begin` тика
  снимает `_stopping`. Окно «повторная проверка → `connect_begin`» — микросекунды, без ввода-вывода. Эффекты:
  (а) PARAM_SET, SERVO и DO после «Отключить»: тик открывает сокет снова, `sync_params`, `_run_on_connect`
  (`servo(True)` / `do_set`), `connect_finish`, затем закрытие ветки тика; (б) за эту сессию SOFT нет; (в) у настоящего
  транспорта D6 между открытием сокета и вводом-выводом синхронизации даёт исключение, `_sync_cancelled()` False,
  поэтому `_record_err` и `_publish_error(«подключение к роботу не удалось…»)`; «без `_record_err`» верно только
  для порядков, где `_stopping` не снят (I2–I5). **C-29 его НЕ закрывает** (ревью ветки Opus 2026-10-25, чтением):
  счётчик запросов снимается в `finally` D6, поэтому к `connect_begin` тика после полного D1–D6 он уже 0, а
  `connect_begin` `desired_connected` не читает. C-29 закрывает только порядки, где `connect_begin` тика идёт ДО конца
  D6 (`"cancelled"`, C9). Закрытие — C-38 (реестр): `connect_begin` тика проверяет `desired_connected` под замком
  состояния (K пишет его до своей секции).
- **Остатки C-29.** О1: окно «проверка → запись» SERVO / DO, `jog_step`, задание остаётся (T5.3g), закрыть можно
  только сериализацией с вводом-выводом под замком. О2: обмен в полёте не прерывается. О3: «Отключить» в миллисекунды
  создания драйвера внутри первого `manager.connect`. О6: общая очередь — C-31. О7: `request_disconnect` без
  `disconnect` вне плагина держит `connect` в `"cancelled"`. О8: пути счётчика без `disconnect_end` (остановка
  плагина, `remove`) — драйвер выключается или выбрасывается. О9: `servo` / `do_set` в окне не отказывают, как и `param_set`, `param_apply`, `point_capture`. О10:
  продление «hold» активного jog после «Отключить» отказывает — поводок истекает. О12: при живом воркере тика между
  `connecting` и `disconnecting` возможны `disconnected` или `error`. О13: задание со своим чтением TLM, пережившим
  весь `disconnect`, встанет в очередь после хвоста; так же возврат, взятый тиком до K: если весь `disconnect` с
  хвостом пройдёт между отказом `admit_launch` и `requeue_return` (jobs.py:133-134), возврат встанет в очищенную
  очередь и исполнится после «Подключить» (микросекунды, чтением).
- **Остаток О14 (C-29).** «Отключить» посреди `connect` ставит `_stopping`: `jog_hold_check`, `jog_hold_admit` и
  `admit_launch` отвечают `TEXT_STOPPING`, а `jog_step`, `enqueue_job`, `return_job` — `TEXT_DISCONNECTING`.
  `_stopping` держится до следующего `connect_begin` — отказ есть всегда, текст разный. Принято владельцем 2026-10-25
  (jog — только в ручном режиме); тексты выровнять в C-39 (режим ручной/авто драйвера v2).
- **Остаток: `_shutdown` и «Отключить» одновременно.** `disconnect_owns_close` при `_shutdown` возвращает False: тик
  закрывает сокет сам, и `process_stop_plan` может увидеть `link_up()` False (нет SOFT). Не регресс: до T5.3h тик
  закрывал безусловно при `desired_connected` False.
- **Остаток: снимок от завершённого `disconnect`.** `_stopping` от прошлого `disconnect` без `connect` между ними
  делает снимок D2 монотонным (принято): безопасно только с живым `link_up()`. Лишний SOFT возможен, лишь если D6
  прошлого `disconnect` упал и сокет остался открытым.
- **Остаток: `request_stop` после решения D3 (до D6) или с записью, ещё идущей в момент решения D3, — 2 SOFT.** Как у подключённого робота на main: `request_stop_begin`
  открывает новое поколение защёлки (ADR-DH-009), снимок монотонен, `link_up()` True до D6 — `process_stop_plan` пишет
  второй SOFT (между решением D3 и записью, после записи до D6). Воспроизведено ревью ветки; закреплено H19. Каждое
  выключение получает свой SOFT; один SOFT при любом порядке — отдельная задача, решение владельца.
- **Остаток: готовый робот, ручной `connect` на живой связи, связь падает между D2 и открытием сокета (C3).**
  Сокет открывает C3 самого `connect` (`if not transport.is_connected and not transport.connect()` в
  `_connect_locked`) уже после D6, и его никто не закрывает. Тик до этого не доходит: `_param_lock.acquire(blocking=False)`
  не берётся, пока идёт `connect`. Супервизор сериализует ручные `connect` и `disconnect` — практически недостижимо;
  пробой не покрыто.
- **Остаток: поток `disconnect` обрывается между D2 и D6.** Ввод-вывод в `_request_stop`, `_close_thread` и
  `transport.disconnect` ловится, но `disconnect_stop_plan(..., link_up=...)` и `disconnect_soft_plan(lambda:
  self.is_connected, ...)` стоят вне `try`: исключение из `transport.is_connected` (у `ModbusDevice` невозможно, у
  подмены или моста возможно) и `BaseException` завершают `disconnect` до D6. До T5.3h тик закрыл бы сокет в этом
  случае, теперь не закрывает (`disconnect_owns_close()`): сокет открыт до следующего `connect` (он закрывает старый
  сокет) или до остановки процесса (`_on_shutdown` → D6). Для `ModbusDevice` практически недостижимо; разбор
  чтением, не воспроизведено.
- `_note_reconnect_failed` не менялся: для GUI «Отключить» не важен (супервизор ставит `desired_connected = False`
  до `manager.disconnect`, тик идёт в ветку закрытия); неудачной попыткой отказ считается только при `disconnect()`
  без смены `desired_connected` (`manager.remove`, `manager._on_shutdown`) — драйвер выбрасывается или выключается.

### Связь

- Related: ADR-DH-009 (путь стопа), ADR-DH-010 (состояние и окна), `plans/robot-protocol-v2/tasks/T5.3g.md`, `plans/robot-protocol-v2/tasks/T5.3h.md`
