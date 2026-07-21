# backend_ctl — инструкция для агентов

Как агенту **отлаживать живой бэкенд без GUI и без qt-mcp**: целиться в любой процесс
по имени, слать router-команды, читать состояние, делать live-запись регистров.

`backend_ctl.BackendDriver` — тонкий TCP-клиент к `SocketChannel` хоста (ProcessManager).
Шлёт router-сообщения **той же формы**, что GUI через `CommandSender` — но не тем же
путём приёма: у входа драйвера свой класс слепоты, см. раздел «Чего драйвером
проверить нельзя» ниже. Driver = «GUI по сокету» на уровне формы сообщений, не на
уровне мидлвари приёма.

> **Статус:** MCP-обёртка (P3, Ф1 Task 1.7; сервер на MCP SDK — Phase 3) **готова** —
> сервер `backend-ctl` ([`mcp_server_sdk.py`](mcp_server_sdk.py), stdio, `mcp.server.lowlevel`).
> Рукописный `mcp_server.py` (fallback без SDK-зависимостей) удалён в F.1 после
> подтверждённого живого смоука SDK-версии (BCTL-ADR-001). Имена инструментов
> зеркалят методы driver: `mcp__backend-ctl__capabilities` / `get_status` /
> `introspect_handlers` / `send_command` / `set_register` / `state_get` / `log_tail` /
> `events_page` / … Если инструменты доступны в сессии — используй их вместо Bash-сниппетов.
> Включение: плагин `mcp-backend-ctl` (`.claude/plugins/mcp-backend-ctl/`) в
> `.claude/enabled.yaml` (или запись `backend-ctl` в `.mcp.json`:
> `uv run --no-sync python -m backend_ctl.mcp_server_sdk`). Бэкенд поднимается отдельно (`BACKEND_CTL=1`).

## Когда использовать (routing)

| Задача | Инструмент |
|--------|-----------|
| «Что умеет процесс? есть ли приёмник команды/регистра?» | **backend_ctl** (`introspect_*`) |
| «Применить параметр в живой процесс (live field-write)» | **backend_ctl** (`set_register`) |
| «Запустить/остановить процесс, послать system-команду» | **backend_ctl** (`system_command`) |
| «Проверить что GUI-кнопка реально дергает бэкенд» | сперва backend_ctl (доказать backend-путь), потом qt-mcp (GUI-путь) |
| «Что пользователь нажал в GUI?» (события кнопок/табов агенту) | **backend_ctl** (`ui_tap` → события `ui.event` в `events_page(plane="ui")`) |
| Состояние **виджетов**, клики, снимок UI | qt-mcp (`QT_MCP_PROBE=1`) — НЕ backend_ctl |
| Поиск/рефакторинг исходников | qex / Serena / Grep — driver видит только runtime |

## Режимы отладки (бэкенд / фронтенд / совместно)

| Режим | Как | Что видно |
|-------|-----|-----------|
| **Бэкенд отдельно** (headless, без Qt) | `BackendHarness` в тестах или `BACKEND_CTL=1` + strip_gui | introspect/state/логи/регистры — весь этот файл |
| **Фронтенд** (GUI поднят) | полный запуск `BACKEND_CTL=1 python run.py` → `drv.ui_tap("gui")` | нажатия кнопок и переключения табов приходят агенту событиями `ui.event` (`data.record`: kind/text/path/ts); смоук цепочки без клика — `drv.ui_tap_ping("gui")`; инспекция/клики виджетов — qt-mcp (`QT_MCP_PROBE=1`) |
| **Совместно** (корреляция UI ↔ бэкенд) | **`drv.debug_session()` — одна кнопка**: ui_tap (жесты+команды GUI) + log_tail на все процессы + state_subscribe; выключение — `debug_stop()` | единый событийный поток с ts/seq: «клик (ui.event kind=button, seq=41) → команда GUI→бэкенд (kind=command, seq=42) → log.record → state.changed» — разрыв между уровнями локализует баг |

**Киллер-фича:** `introspect_handlers(process)` за секунду ловит баг «нет приёмника»
(команда есть в `CommandManager`, но не в router `message_dispatcher`, или у плагина нет
worker-side обработчика регистра) — без единого клика в GUI.

## Предусловия

1. Система должна **работать** с открытым гейтом сокета. По умолчанию гейт уже открыт:
   [`backend/config/system.yaml`](../multiprocess_prototype/backend/config/system.yaml) →
   `backend_ctl.enabled: true`, `port: 8765`, `host: 127.0.0.1`.
   Escape-hatch без правки yaml: `BACKEND_CTL=1 [BACKEND_CTL_PORT=9001] python run.py`.
2. Запуск системы в фоне (НЕ блокировать сессию), из корня репозитория:
   ```bash
   python multiprocess_prototype/run.py     # run_in_background: true
   ```
   Дать ~6-8 c на старт. Останавливать — **только** через TaskStop по task_id
   (НЕ `taskkill /IM python.exe` — это убьёт чужие процессы).

## Канонический рецепт (Bash + Python)

Driver — синхронный, контекст-менеджер сам connect/close. Запускать одним сниппетом:

```bash
# из корня репозитория:
python - <<'PY'
from backend_ctl import BackendDriver
with BackendDriver(port=8765) as drv:
    print("HANDLERS:", drv.introspect_handlers("preprocessor"))
    print("REGISTERS:", drv.introspect_registers("preprocessor"))
    print("STATUS:", drv.introspect_status("preprocessor"))
PY
```

## Шпаргалка API

| Метод | Назначение |
|-------|-----------|
| `system_overview(timeout=)` | **B.3, первая команда сессии**: компактная сводка всех процессов (статус/воркеры/router/очереди/память) + telemetry fps + счётчики driver'а + `anomalies`-подсказки (router_dropped, queue_depth, fps_zero_while_running, recent_recovery, late_replies, events_evicted, …) |
| `introspect_handlers(process)` | ключи router `message_dispatcher` + команды `CommandManager` |
| `introspect_registers(process)` | имена регистров + поля (**пусто = нет worker-side приёмника**) |
| `introspect_status(process)` / `get_status(process)` | имя, воркеры, состояние процесса |
| `router_stats(p)` / `queues(p)` / `worker_status(p)` | типизированно (dataclass + `.raw`): счётчики router'а / глубины очередей / статус воркеров |
| `capabilities()` / `introspect_capabilities(p)` | «контактная книжка»: свод команд/регистров/каналов по всем процессам (или карточка одного). MCP-инструмент принимает `format="concise"` (только имена, кратно дешевле) / `"help"` (пример вызова + какое push-событие в какую плоскость + корреляционные ключи) / `"detailed"` (дефолт) и `process`-фильтр (B.4) |
| `set_register(process, register, field, value)` | live-запись регистра (`register_update`, ключи `{register, field, value}`) |
| `set_register_verified(process, register, field, value)` | verify-probe (Ф1.6): write → readback `introspect.registers` → diff (`verified`/`expected`/`actual`) — ловит молчаливые no-op'ы |
| `set_register(..., confirm_within=N)` | **commit-confirmed** (D.5): запись авто-откатится через `N` сек, если не вызвать `register_confirm(commit_id)`. Аналог Juniper `commit confirmed` |
| `register_snapshot(process=None)` / `register_restore(snapshot)` | снимок регистров (один процесс или все — топология одним запросом PM) → откат: `{processes: {proc: {register: {field: value}}}}`; restore пишет ТОЛЬКО дрейфнувшие поля + сверяет readback'ом (`success`/`written`/`skipped`/`mismatches`) |
| `register_confirm(commit_id)` | подтвердить commit-confirmed запись — снять таймер авто-отката; для уже откатившегося отдаёт `rolled_back` (исход) (D.5) |
| `register_rollback_log(limit=None)` | журнал исходов авто-откатов сессии: `outcome` ok/failed(+error)/noop — узнать, чем кончился откат без register_confirm (D.5) |
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command({"cmd": ..., ...})` | system-команда в ProcessManager (`process.start`/`stop`/`worker.*`/…) |
| `state_subscribe(pattern)` | подписка на state-дерево; пуши `state.changed` → событийный канал |
| `ui_tap("gui")` / `ui_untap("gui")` | подписка на UI-события gui: жесты (kind=button/tab) И намерения — команды GUI→бэкенд через перехват двери CommandSender (kind=command/system_command) → пуши `ui.event` (общий seq) |
| `ui_tap_ping("gui", note=...)` | синтетическое `ui.event` тем же путём доставки — проверка цепочки без клика |
| `debug_session(logs_level=, state_pattern=, log_processes=)` / `debug_stop()` | ВСЯ отладочная плоскость одним вызовом: ui_tap + log_tail (по умолчанию на все процессы топологии) + state_subscribe; дизайн — `plans/2026-07-06_constructor-master/debug-plane-idea.md` |
| `events_page(plane=, cursor=, limit=)` | **B.1**: курсорное НЕдеструктивное чтение событий по плоскостям (`state`/`logs`/`errors`/`stats`/`telemetry`/`ui`/`other`/`all`); ответ `{items[{seq,event}], next_cursor, dropped, bookmark}` — несколько читателей не мешают друг другу, потеря из кольца видна в `dropped`, `bookmark` = «читать только новое» |
| `await_condition(kind, spec, timeout=)` | **B.2**: серверное ожидание вместо поллинга — `state_path` (`{path, value}` в read-model), `event_matches` (`{plane, pattern}` glob по command/path), `metric_threshold` (`{path, op, value}`); таймаут возвращает диагноз (`waited`/`last_seen`/`events_seen`), не пустоту; требует активной подписки (watch_like_gui/state_subscribe) |
| `subscribe(cb)` | событийный канал: колбэк на каждый push (исполняется в reader-потоке — держи лёгким) |
| `events(timeout, max_items)` | MCP-инструмент «новое с прошлого вызова»: курсорная обёртка над `events_page` со своим приватным курсором. Деструктивный дренаж `driver.events()` **удалён** (F.1) — единственный публичный способ читать события это `events_page` |
| `events_stats()` | счётчики hub'а: per-plane seq/размер/вытеснено |
| `telemetry_set(process, metric, enabled=, interval_sec=, plane=)` | **точечно** поменять ОДНУ метрику/правило телеметрии (merge — соседей не сносит); `plane="publisher"` (частота публикации) или `"throttle"` (central rate-limit) |
| `telemetry_reconfigure(process="all", publish=, throttle=, mode=)` | секцией: publisher-gate и/или central-троттл; `mode="replace"` (дефолт) применяет ЦЕЛИКОМ (**wipe** неуказанных) — для одной метрики предпочитай `telemetry_set` |
| `telemetry_snapshot(process=None, metric=None)` | **локальный** снимок телеметрии (0 IPC): read-model поверх `state.changed`; наполняется после `watch_like_gui`; фильтр по процессу/суффиксу метрики + ключ process/worker |
| `telemetry_history(path, limit=None)` | **локальная** история метрики (спарклайн без БД): кольцевой буфер (fps/latency_ms/uptime/effective_hz/cycle_duration_ms) |
| `record_start(name, max_events=)` / `record_stop()` | **D.4 flight recorder**: ЗАПИСЬ потока событий в файл (`BACKEND_CTL_RECORD_DIR`, имя без разделителей). Пиши то, на что подписан (без подписок — hint про пустую ленту); лимит → авто-стоп |
| `record_load(name, position="end"\|"start", ring_maxlen=)` / `record_unload()` | загрузить запись в OFFLINE-реплей (сессия → replay-режим) / вернуть live. `end` — финал сразу; `start` — тайм-трэвел (playhead двигают `await_condition`'ы) |
| `record_status()` | активная запись (файл/`events_written`/`dropped`) ЛИБО загруженный реплей (имя/позиция/total/`truncated`) |
| `record_dump(name)` | one-shot дамп чёрного ящика: снимок + текущее arrival-кольцо (`reason=dump`); грузится тем же `record_load` |
| `observability_tail(process)` / `observability_untail(process)` | live ЛОГИ+ОШИБКИ+СТАТИСТИКА процесса (то, что GUI получает через `ObservabilityTailActivator`); записи по плоскостям — `observability_records(kind=)` |
| `watch_like_gui()` / `unwatch()` | ВЕСЬ приёмный профиль GUI одной командой: state.subscribe (processes/system/devices/calibration) + observability.tail на все процессы + **авто-переподписка** после авто-рестарта |
| `introspect_memory(process)` | инвентарь памяти (SHM/пул займов/очереди) — только статистика; секции best-effort (`null`, не ошибка) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа, либо `{"success": False, "error": "timeout"/"not connected"/...}`.
Все имена доступны как MCP-инструменты (полный каталог — `tools/list`).
После реконнекта MCP-сервера подписки (`state_subscribe`/`log_tail`/`ui_tap`/`watch`) восстанавливаются автоматически (Task 0.3/F2).

**Safety-режимы MCP-сервера** (Phase 3, флаги сервера или env `BACKEND_CTL_MCP_MODE`):
`--read-only` — только чтение+подписки (write/escalated скрыты и блокируются;
`send_command` пропускает лишь `introspect.*`/`state.get*`); `--disable-destructive` —
блок разрушающих. Инструменты несут annotations (`readOnlyHint`/`destructiveHint`).
Неизвестный инструмент → подсказка ближайших имён; блок → список доступных.

**Мультиклиент (D.2, streamable-HTTP):** `python -m backend_ctl.mcp_server_sdk --http`
[`--http-bind 127.0.0.1:8901`] — несколько агентов на одной живой системе одновременно
(каждая MCP-сессия = свой driver/сокет/`session`, изоляция поверх D.1a; завершение сессии
снимает её подписки). **Требует бэкенд с `session_isolation=ON`** (`BACKEND_CTL_SESSION_ISOLATION=1`)
— иначе fail-fast отказ. Safety-режим per-server (нужны разные — два инстанса на разных портах).
Дефолт остаётся stdio. Детали — [`DECISIONS.md`](DECISIONS.md) BCTL-ADR-005, [`README.md`](README.md).

**Flight recorder (D.4, offline-реплей):** `record_start(name)` пишет снимок + ленту
событий; `record_load(name)` прогружает запись в ТОТ ЖЕ read-model **без живой системы**
(detached driver) — `telemetry_snapshot`/`telemetry_history`/`events_page`/`state_get`/
`system_overview`/`await_condition` отвечают ПО ЗАПИСИ. В replay-режиме прочие инструменты
(write/IPC/subscribe) дают обучающую ошибку «требует живой системы — `record_unload()`».
Все `record_*` = **read-safety** (бэкенд не мутируется). `await_condition` над записью —
навигация playhead'ом: прокручивает ленту до попадания и ОСТАЁТСЯ там (snapshot после =
момент срабатывания); конец без попадания → `end_of_recording`. Файлы — только в
`BACKEND_CTL_RECORD_DIR` (default `./backend_ctl_records/`) по ИМЕНИ, не пути.
**⚠️ Запись содержит состояние системы (пути/конфиги/параметры рецептов) — не прикладывай
её к публичным issue** (v1 без редакции; dev-only, локальный файл). Детали —
[`DECISIONS.md`](DECISIONS.md) BCTL-ADR-006.

### Примеры

```python
# Live field-write: применить параметр плагина в работающий процесс
drv.set_register_verified("preprocessor", "resize", "target_width", 640)

# Управление жизненным циклом процесса
drv.system_command({"cmd": "process.start", "process_name": "camera"})
drv.system_command({"cmd": "process.stop",  "process_name": "camera"})

# Управление воркерами процесса (worker.* команды процесса-владельца)
drv.send_command("camera", "worker.stop",  {"worker_name": "grabber"})
drv.send_command("camera", "worker.start", {"worker_name": "grabber"})
```

### Диагностика «нет приёмника» (Этап 2 proof)

```python
h = drv.introspect_handlers("preprocessor")
# если "register_update" ОТСУТСТВУЕТ в router-handlers → у плагина нет worker-side
# приёмника: GUI/driver шлёт, но никто не читает. Диагноз без GUI.
```

## Тесты против живого бэкенда (headless)

Нужен живой бэкенд в тесте — используй `BackendHarness` (headless, без GUI, с
гарантированным teardown), не поднимай прототип вручную:

```python
from backend_ctl.harness import BackendHarness
with BackendHarness(with_base=True) as drv:      # старт → driver → гарантированный стоп
    print(drv.worker_status("preprocessor").status)
```

Или фикстура `headless_backend`. Прогон: `python -m pytest backend_ctl -m harness_smoke`.

> Регресс 1.1 ЗАКРЫТ (Ф1.1b): push `state.changed` доходит до внешнего сокет-driver'а
> через мост push→канал в `RouterManager._deliver_by_targets` (у не-процесса нет
> очереди → доставка через одноимённый `SocketChannel`).

## Подводные камни

- **`request()` нельзя звать из reader-потока driver'а** — дедлок: ответ обязан доставить
  тот же поток, который сейчас заблокирован в ожидании. Это **грозит и агенту**: колбэк
  `subscribe()` исполняется синхронно в reader-потоке, и `request()` оттуда (или любая
  обёртка команды поверх него) повесил бы сессию до таймаута. С Task 1.3 стоит guard —
  немедленный error-dict с описанием правильного паттерна вместо зависания. Паттерн:
  слушатель кладёт намерение в `queue.Queue` и сразу возвращается, отдельный applier-поток
  разбирает очередь и уже там зовёт `request()` (живой образец — `WatchController` в
  [`watch.py`](watch.py): `_on_event` → `_resub_queue` → `_resub_loop`).
  Отдельно — контракт P0.5 внутри бэкенда: `request()` из приёмного потока хоста тоже
  дедлок, но туда агент не попадает (driver — внешний процесс, запросы идут через сокет).
- **ProcessManager — отдельный OS-процесс.** Дотянуться до процесса можно только через
  «дверь» (SocketChannel в PM); без запущенной системы driver вернёт `not connected`.
- **Таймаут = не баг по умолчанию.** `{"error": "timeout"}` часто значит «нет приёмника /
  процесс не отвечает» — это сам по себе диагностический результат.
- **Только localhost, без аутентификации** — dev-инструмент. В проде гейт `enabled: false`.
- **Кадры/SHM через сокет НЕ гоняем** (Dict at Boundary) — только команды/состояние.

## Чек-лист нового сигнала (BCTL-ADR-007)

Добавляешь счётчик, поле ответа, флаг или аномалию — сигнал считается подключённым
только после того, как показан **отклоняющимся от дефолта на живой системе**. До этого
он заглушка, даже если код выглядит рабочим и юнит-тесты зелёные.

| # | Требование | Как выглядит выполненным |
|---|---|---|
| 1 | **Live-ненуль** | `@pytest.mark.harness_smoke` на `BackendHarness`: сигнал показан отличным от дефолта. Fake-transport НЕ засчитывается — 85% покрытия инструмента именно на нём, и ultra-ревью нашло там 23 бага в «покрытых» фичах |
| 2 | **Провенанс** | «значения нет» отличимо от «значение равно дефолту»: `missing: List[str]` у обёрток интроспекции, `ingest_active`/`ingested_total`/`tracked` у телеметрии. Ноль обязан объявлять причину |
| 3 | **Имя сверяемо** | опечатка даёт громкий признак (`unknown_metric` + кандидаты), а не пустоту и не вечное ожидание |

**Первый вопрос при проектировании сигнала: достижимо ли плечо OFF?**
`ingested_total` — достижимо (строго 0 до `watch_like_gui()`, >0 после), атрибуция законна.
Счётчики router'а — недостижимо (фон живой системы двигает `received` на ~40 за 3 c, замерено),
поэтому доказуемо лишь «не заморожен», и эту слабость надо писать в докстроке теста, а не
прятать. Приём: держать рядом **контрольный** замер без целевого действия — зелёный контроль
означает, что атрибуции нет. Образец с разбором — [`tests/test_signal_liveness_live.py`](tests/test_signal_liveness_live.py).

**Гоночное и флаговое поведение принимается только парой ON/OFF.** Одиночный зелёный при
включённом механизме неотличим от «фикс ни на что не влияет». Образец —
[ADR-SS-019](../multiprocess_framework/modules/state_store_module/DECISIONS.md) / `b1a6ef37`:
`приёмка парой ON/OFF (ON 4/4 зелёных, OFF призраки 2/2)`. Плечо OFF доказывает, что
дефект воспроизводим; без него ON-зелёное не значит ничего.

**То же правило — для утверждений, не только для счётчиков.** «Тесты зелёные» без вывода
прогона не принимается; «не проверено» — принимается. Заход 2026-07-21 стартовал с плана,
утверждавшего один красный live-тест, — замер дал три плюс непойманную регрессию на ветке.

Полностью — [`DECISIONS.md`](DECISIONS.md) BCTL-ADR-007.

## Чего драйвером проверить НЕЛЬЗЯ

Инъекция через `backend_ctl` — не полный эквивалент инъекции через настоящий peer-канал:
у входа драйвера есть класс слепоты на приёме. Ниже — какая плоскость мидлвари судит
трафик драйвера, а какая нет, и почему (проверено чтением кода, не из докстрингов).

| Плоскость | Судит трафик драйвера? | Почему |
|---|---|---|
| **Receive-мидлварь ХОСТА** (`RouterManager._recv_mw` процесса ProcessManager) | **Нет** | Inbound драйвера идёт push'ем: `on_inbound(msg)` ([socket_bridge_adapter.py:60](../multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py#L60)) → `router.request(msg)` (:86) → `send()` — это SEND-путь хоста, не его receive-цикл. `receive()` прогоняет `_recv_mw.apply()` ([router_manager.py:902](../multiprocess_framework/modules/router_module/core/router_manager.py#L902)) только над тем, что вернул `_poll_all_channels(input_channels_only=True)` (:893) — а тот опрашивает лишь каналы с префиксом `<имя_процесса>_*`. `SocketChannel` драйвера зарегистрирован под голым именем `backend_ctl` и под этот опрос не попадает; вдобавок его `poll()` — осознанный no-op, всегда `[]` ([socket_channel.py:248-254](../multiprocess_framework/modules/router_module/channels/socket_channel.py#L248)). |
| **Receive-мидлварь ПРОЦЕССА-ПОЛУЧАТЕЛЯ**, когда получатель — дочерний `ProcessModule` (camera/preprocessor/...) | **Да** | Не резолвнув канал по имени процесса, `_do_send()` падает в `_deliver_by_targets()` ([router_manager.py:416](../multiprocess_framework/modules/router_module/core/router_manager.py#L416)), который кладёт билет НАПРЯМУЮ в очередь целевого процесса — тем же путём, что обычная internal-адресация. Дальше это ЧУЖОЙ `receive()`-цикл: собственный `_recv_mw` этого процесса (fence-фильтр + contract-check, если включены) отрабатывает над билетом драйвера штатно, как над любым другим отправителем. **Но:** если target — само `"ProcessManager"` (`system_command`, `state.*`, большинство `introspect.*` — обычная цель драйвера), «получатель» — хост, а у хоста receive-мидлвари нет вовсе (см. строку выше): `BuiltinCommands._register_message_guards()` — метод, вешающий и fence, и contract-check — инстанциируется ТОЛЬКО в [process_module.py:654](../multiprocess_framework/modules/process_module/core/process_module.py#L654), т.е. только для дочерних `ProcessModule`; `process_manager_module/` нигде не зовёт `add_receive_middleware`/`add_send_middleware`. Это не обход конкретно для драйвера — судьи на этой плоскости нет ни для кого, когда target = хаб. |
| **Fence-фильтр** (`make_fence_filter_middleware`) | **Пропускает прозрачно — это не «обход»** | Драйвер не штампует `_fence`: штамп ставит `make_fence_stamp_middleware`, которая висит ТОЛЬКО там же, где и фильтр (`_register_message_guards()`) — у хост-пути её тоже нет. Фильтр на нештампованном сообщении срабатывает первой веткой: `if fence is None: return message` ([token.py:124-126](../multiprocess_framework/modules/message_module/fencing/token.py#L124)) — легаси-проход по конструкции, а не дыра, вырезанная под драйвера. |
| **State-мидлварь** (`before_set`/`before_merge`, напр. `TopologyGateMiddleware`) | **Да, полностью** | Отдельная плоскость: не router receive-pipeline, а мидлварь ЕДИНСТВЕННОГО канонического `StateStoreManager` (живёт в ProcessManager), вызывается ВНУТРИ обработчика команды `state.merge`/`state.set` — транспорт и личность отправителя ей не видны и не важны. Судит только путь `processes.<name>.*` (fail-open на остальном дереве — [topology_gate.py](../multiprocess_framework/modules/state_store_module/middleware/topology_gate.py)). Живой прецедент (ADR-SS-019): `state.merge` от драйвера с именем процесса, которого нет в топологии, → `{'status': 'rejected', 'reason': 'topology_gate'}`. Проводка — [orchestrator.py:191-212](../multiprocess_framework/modules/app_module/orchestrator.py#L191). |

**Прямые следствия:**
- Инъекцией через драйвер **нельзя** проверить фильтры приёма ХОСТА — они физически не запускаются на его трафике (а для команд с target=ProcessManager — не запускаются вообще ни для кого, драйвер тут не исключение и не особый случай).
- Fence-поведение драйвером **не проверить**: его сообщения фильтру не судимы, а прозрачны (нет штампа). Детерминированный live-тест стейл-дропа нужно строить над настоящим peer-процессом или unit-инвариантом фильтра, не e2e через драйвер — см. Task 5.1 плана `backend-ctl-proof-discipline.md`.
- State-записи драйвера (`state.merge`/`state.set`/`state.delete`) **судятся полностью**, включая гейт топологии: обращение к несуществующему в топологии процессу под `processes.<name>.*` будет отклонено — это ожидаемое поведение инструмента, а не баг.
- Если когда-нибудь понадобится судимость драйвер-трафика именно на receive-плоскости хоста — это ОТДЕЛЬНОЕ архитектурное решение («парадная дверь»: доставка через канал, попадающий под `input_channels_only`-опрос), а не «оно и так работает». Здесь оно сознательно не реализуется — см. план `backend-ctl-proof-discipline.md`, раздел «Что сознательно НЕ входит».

См. также память `project_backend_ctl_socket_bypasses_mw` (класс слепоты в целом), `project_state_topology_gate` (живой прецедент гейта топологии, ADR-SS-019) и `project_fencing_test_race` (почему это же ограничение не даёт детерминировать fencing-тест через драйвер).

## Связанное

- **«Контактная книжка» — ЧИТАЙ ПЕРВОЙ:** [`docs/contracts/CAPABILITIES.md`](../docs/contracts/CAPABILITIES.md)
  — полный каталог команд (с описаниями), регистров и каналов всех процессов; генерируется
  из runtime (`python -m backend_ctl.dump_capabilities`), исходники читать не нужно.
  Runtime-эквивалент: `drv.capabilities()`.
- Dev-README (устройство, запуск): [`backend_ctl/README.md`](README.md)
- Готовый прогон-пример: [`backend_ctl/probes/smoke_proof.py`](probes/smoke_proof.py)
- Driver: [`backend_ctl/driver.py`](driver.py)
- Поднятие endpoint: [`process_manager_module/process/backend_ctl_endpoint.py`](../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py)
- MCP-сервер: [`backend_ctl/mcp_server_sdk.py`](mcp_server_sdk.py) (stdio JSON-RPC, MCP SDK), инструменты: [`backend_ctl/mcp_tools.py`](mcp_tools.py)
- План/статус: [`plans/_archive/2026-05-31_backend-control-mcp/`](../plans/_archive/2026-05-31_backend-control-mcp/) (P3 закрыт Ф1 Task 1.7, см. `plans/2026-07-06_constructor-master/plan.md`)
- ADR-RTR-008 (request-response в RouterManager)
```
