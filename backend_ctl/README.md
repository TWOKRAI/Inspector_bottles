# backend_ctl — headless driver управления бэкендом (dev-инструмент)

> 🤖 **Агентам:** инструкция по использованию — [`AGENTS.md`](AGENTS.md) (когда звать,
> рецепт Bash+Python, диагностика «нет приёмника»). Этот README — про устройство.

Тонкий внешний клиент к работающей системе: подключается по TCP к `SocketChannel`
хоста (ProcessManager) и шлёт **те же** router-сообщения, что GUI через `CommandSender`.
Назначение — отлаживать бэкенд напрямую (целиться в процессы, слать команды, читать
состояние) без GUI и без qt-mcp. Поверх driver'а есть MCP-обёртка (см. «MCP-сервер»).

> **Инвариант:** всё общение с бэкендом — строго через `RouterManager`. Сокет делает
> только байтовый I/O на границе Claude↔driver. Driver = «GUI по сокету».
> Кадры/SHM через сокет НЕ гоняем (Dict at Boundary).

## Как это устроено

```
backend_ctl.BackendDriver ──TCP(newline-JSON)──► SocketChannel (в ProcessManager)
        │                                              │ on_inbound
        │                                       router.request(msg)   ← P0.5
        │                                              │ _deliver_by_targets
        │                                       любой процесс системы
        │                                              │ reply_to_request
        │                                       router.send(channel="backend_ctl")
        ◄──────────── ответ по request_id ◄───────────┘ SocketChannel.send
```

Одна «дверь» в хабе (ProcessManager) — через неё дотягиваешься до **любого** процесса
по имени (`targets=[process]`). Канал-в-каждом-процессе не нужен.

## Запуск

1. Поднять систему с открытым гейтом. **Два способа** (OR):

   **(a) Через `system.yaml` (основной для dev-прототипа)** —
   `multiprocess_prototype/backend/config/system.yaml`:
   ```yaml
   backend_ctl:
     enabled: true      # сокет поднимается всегда при старте
     port: 8765
     host: "127.0.0.1"
   ```

   **(b) Через env (escape-hatch для тестов/CI, без правки yaml):**
   ```bash
   BACKEND_CTL=1 python run.py            # порт по умолчанию 8765
   BACKEND_CTL=1 BACKEND_CTL_PORT=9001 python run.py
   ```
   Приоритет: гейт открыт если `backend_ctl.enabled` **ИЛИ** `BACKEND_CTL=1`.
   Порт: `BACKEND_CTL_PORT` (env) > `backend_ctl.port` (yaml) > 8765.
   В проде держать `enabled: false` и не выставлять env.

2. Подключиться драйвером:
   ```python
   from backend_ctl import BackendDriver

   with BackendDriver(port=8765) as drv:          # connect/close через контекст
       print(drv.introspect_handlers("preprocessor"))   # что умеет процесс
       print(drv.introspect_registers("preprocessor"))  # регистры (пусто = нет приёмника)
       drv.set_register_verified("preprocessor", "resize", "target_width", 640)   # live field-write
       print(drv.system_command({"cmd": "process.start", "process_name": "camera"}))
   ```

## API (обёртки поверх общего билдера протокола)

| Метод | Что делает |
|-------|-----------|
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command(command)` | system-команда в ProcessManager (`process.command`-обёртка) |
| `introspect_handlers(process)` | ключи `message_dispatcher` + команды `CommandManager` |
| `introspect_registers(process)` | имена регистров + поля (пусто = нет worker-side приёмника) |
| `introspect_status(process)` / `get_status(process)` | имя, воркеры, состояние процесса |
| `introspect_router_stats(process)` / `introspect_queues(process)` | сырой dict: счётчики router'а / глубины очередей |
| `introspect_plugins(process)` | каталог плагинов процесса + `failed_imports` (Ф2.3: «куда делся мой плагин» — модуль с опечаткой виден, не исчезает молча) |
| `router_stats(process)` → `RouterStats` | типизированно: `sent_ok`/`received`/`middleware_dropped`/`errors` (+ `.raw`) |
| `queues(process)` → `QueueDepths` | типизированно: `sizes={тип: глубина\|None}` (+ `.raw`) |
| `worker_status(process)` → `WorkerStatus` | типизированно: `process`/`status`/`workers` (+ `.raw`) |
| `introspect_capabilities(process)` | карточка процесса: команды+descriptions, регистры (поля), handlers |
| `capabilities()` → `Capabilities` | «контактная книжка»: свод по ВСЕМ процессам (fan-out) — топология, каналы, карточки |
| `system_overview(timeout=)` | **B.3**: «один вызов = вся картина» — компактная сводка процессов + anomalies-подсказки; ноль новых IPC-команд |
| `set_register(process, register, field, value)` | live-запись регистра (`register_update`, ключи `{register, field, value}`) |
| `set_register_verified(process, register, field, value)` | verify-probe (Ф1.6): write → readback `introspect.registers` → diff (`verified`/`expected`/`actual`) — ловит молчаливые no-op'ы |
| `set_register(..., confirm_within=N)` | **D.5** commit-confirmed: запись авто-откатится через `N` сек без `register_confirm(commit_id)` (аналог Juniper `commit confirmed`) |
| `register_snapshot(process=None)` / `register_restore(snapshot)` | **D.5**: снимок регистров (один процесс или все — топология одним запросом PM) → откат. Форма `{processes: {proc: {register: {field: value}}}}`; restore пишет только дрейфнувшие поля + сверяет readback'ом (`written`/`skipped`/`mismatches`) |
| `register_confirm(commit_id)` | **D.5**: подтвердить commit-confirmed запись — снять таймер авто-отката; для откатившегося отдаёт `rolled_back` |
| `register_rollback_log(limit=None)` | **D.5**: журнал исходов авто-откатов сессии (`outcome` ok/failed/noop) |
| `state_subscribe(pattern, subscriber=None)` | подписка на state-дерево (`state.subscribe`); пуши `state.changed` идут в событийный канал |
| `subscribe(callback)` / `unsubscribe(callback)` | колбэк на каждое push-событие (зовётся в reader-потоке) |
| `events_page(plane=None, cursor=None, limit=None)` | **B.1**: курсорная страница событий плоскости — недеструктивно, несколько читателей не мешают друг другу; ответ несёт `next_cursor`/`dropped`/`bookmark` |
| `events_stats()` | счётчики hub'а: per-plane seq/размер/вытеснено (вход для overview B.3) |
| `await_condition(kind, spec, timeout=)` | **B.2**: дождаться условия одним вызовом вместо поллинга — `state_path`/`event_matches`/`metric_threshold`; таймаут → диагноз (что ждали/что видели), не пустота |
| `record_start(name, max_events=)` / `record_stop()` | **D.4 flight recorder**: запись потока событий в файл (`BACKEND_CTL_RECORD_DIR`) → offline-реплей; лимит → авто-стоп (footer valid) |
| `record_load(name, position=, ring_maxlen=)` / `record_unload()` | загрузить запись в offline-реплей (сессия → replay) / вернуть live; `position="end"` (финал) \| `"start"` (тайм-трэвел) |
| `record_status()` / `record_dump(name)` | статус записи/реплея; one-shot дамп arrival-кольца (`reason=dump`) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа (или `{"success": False, "error": ...}` при
таймауте/обрыве). Сообщения строятся `message_module.build_command_message` /
`build_system_command_message` — один источник правды с GUI.

### Событийный канал (push без reply) — курсорные плоскости (B.1)

Reply-путь матчит ответы по `request_id`. Push-сообщения **без** `request_id` (или
не матчащие ни один pending) — например `state.changed` — не дропаются, а идут в
`EventHub` ([`events.py`](events.py)): **кольцевые буферы по плоскостям**
(`maxlen=event_queue_maxlen`, по умолчанию 1000 на кольцо; старые вытесняются, не
течёт) + синхронные подписчики. Reader-поток пишет, клиентские потоки читают
курсорами `events_page()`/`subscribe()` (thread-safe). Исключение колбэка не
роняет reader-поток (глотается, видно в `driver.event_errors`).

Плоскости: `state` (state.changed) / `logs` (log.record + observability kind=log) /
`errors` / `stats` / `telemetry` (per-delta зеркало state.changed — курсорный вход
для порогов/ожиданий B.2) / `ui` (ui.event) / `other` (всё мимо классификации — не
теряется молча) / `all` (оригиналы в порядке прихода). Смешанный observability-батч
расщепляется по `kind` только в плоскостных view; оригинал в `all` не тронут.

Чтение — как K8s watch / journald cursor: `events_page(plane, cursor)` возвращает
`{items: [{seq, event}], next_cursor, dropped, bookmark}`. `next_cursor` передаётся
в следующий вызов; `dropped` — сколько событий вытеснено из кольца между курсором и
первым возвращённым (слепая зона ВИДНА, не съедается молча); `bookmark` — курсор
«хвост сейчас». Курсор принимается ТОЛЬКО в полной форме `plane:seq@gen` (как выдают
`next_cursor`/`bookmark`); любая ошибка курсора — усечённый, чужой плоскости, чужого
поколения (реконнект пересоздаёт driver), впереди потока — даёт явный
`reset_required: True` + `bookmark`: начать заново с `cursor=None` (полный re-list —
Phase D). Кавеат: `dropped` разных плоскостей несравним — telemetry получает k
item'ов на одну state.changed с k дельтами и вытесняется быстрее.

```python
with BackendDriver(port=8765) as drv:
    drv.state_subscribe("processes.**")        # подписка → сервер шлёт state.changed
    page = drv.events_page("state")            # первый вызов: с самого старого
    for it in page["items"]:
        print(it["seq"], it["event"]["command"])
    page = drv.events_page("state", cursor=page["next_cursor"])  # только новое
    assert page["dropped"] == 0                # потеря видна, если кольцо переполнялось
```

Легаси-деструктивный дренаж `events(timeout)` (обёртка над hub'ом) удалён в F.1 —
единственный публичный способ читать события Python-driver'а теперь `events_page`.
MCP-инструмент `events` (для агентов) остался под тем же именем, но переписан
поверх `events_page` со своим приватным курсором (см. раздел MCP-сервера ниже).

### UI-tap — отладка фронтенда (события кнопок агенту)

GUI-процесс несёт `UiEventTap` (frontend_module.debug) — глобальный фильтр
QApplication (как WheelGuard), ВЫКЛЮЧЕННЫЙ по умолчанию. `drv.ui_tap("gui")`
включает его: нажатия кнопок и переключения табов едут push'ем `ui.event`
(`data.record`: kind=button|tab, text, path, ts) тем же маршрутом, что log-tail
(мост 1.1b / relay 1.7), и читаются через `events_page("ui")`. `drv.ui_tap_ping("gui")` —
синтетическое событие тем же путём: смоук всей цепочки без физического клика.

```python
with BackendDriver(port=8765) as drv:
    drv.ui_tap("gui")                     # включить тап
    drv.ui_tap_ping("gui", note="smoke")  # проверить цепочку доставки
    for it in drv.events_page("ui")["items"]:
        print(it["event"]["data"]["record"])   # {'kind': 'button', 'text': 'Запустить', ...}
```

Режимы отладки (бэкенд отдельно / фронтенд / совместно) — таблица в [AGENTS.md](AGENTS.md).

### Типизированные обёртки (Ф1 Task 1.2)

`router_stats()`/`queues()`/`worker_status()` возвращают dataclass'ы (`RouterStats`/
`QueueDepths`/`WorkerStatus`) — форма, а не логика: сырой introspect-ответ приводится к
явным полям, сырой dict всегда лежит в `.raw` (ничего не теряется). Отдельной
`introspect.wire`-команды в системе НЕТ (есть только `wire.configure`/`deconfigure` —
это действия), поэтому `wire_status()` не вводится.

```python
with BackendDriver(port=8765) as drv:
    rs = drv.router_stats("preprocessor")   # RouterStats(sent_ok=10, received=21, ...)
    print(rs.sent_ok, rs.middleware_dropped, rs.errors)
    print(drv.queues("preprocessor").sizes)          # {'system': None, 'data': 3}
    print(drv.worker_status("preprocessor").status)  # 'running'
```

## MCP-сервер (Ф1 Task 1.7, P3; SDK — Phase 3, BCTL-ADR-001)

`backend_ctl/mcp_server_sdk.py` — stdio-MCP-сервер на официальном SDK (`mcp`, extra
`ctl`) поверх driver'а: Claude (или любой MCP-клиент) вызывает бэкенд инструментами
вместо Bash+Python-сниппетов. Даёт tool-annotations, safety-режимы, actionable-ошибки.
Рукописный tools-only сервер без SDK-зависимости (`mcp_server.py`) удалён в F.1 после
подтверждённого живого смоука SDK-версии.

- **Транспорт:** stdio по умолчанию (`mcp.server.lowlevel` + newline-delimited
  JSON-RPC/MCP-протокол); `--http` — streamable-HTTP мультиклиент (см. ниже).
- **Инструменты** ([`mcp_tools.py`](mcp_tools.py)) зеркалят методы driver:
  `capabilities` (B.4: `format=concise|help|detailed` + `process`-фильтр — холодный
  старт за 1 вызов без взрыва контекста), `system_overview` (B.3),
  `get_status`, `introspect_handlers|registers|router_stats|queues`,
  `send_command`, `system_command`, `set_register` (+`confirm_within` — commit-confirmed D.5),
  `register_snapshot`/`register_restore`/`register_confirm`/`register_rollback_log`
  (снимок/откат регистров + журнал откатов D.5),
  `state_get`, `state_get_subtree`,
  `state_subscribe`, `events_page` (курсорные плоскости B.1), `events` (простой
  дренаж «новое с прошлого вызова» поверх `events_page`, F.1), `await_condition`
  (серверное ожидание B.2),
  `log_tail`/`log_untail`, `ui_tap`/`ui_untap`/`ui_tap_ping`,
  `config_reload`, `logger_sink_enable|disable`,
  `telemetry_reconfigure`/`telemetry_set` (управление частотой/метриками телеметрии — Task 0.5).
- **Жизненный цикл:** driver подключается лениво при первом вызове; бэкенд поднимается
  отдельно (`BACKEND_CTL=1`). Нет бэкенда → инструмент возвращает `isError` с понятным
  текстом (сервер живёт, после подъёма бэкенда переподключается сам). При реконнекте
  durable-подписки (`state_subscribe`/`log_tail`/`ui_tap`) восстанавливаются автоматически
  (Task 0.3), в ответе — `reconnected`/`resubscribed`.

```bash
python -m backend_ctl.mcp_server_sdk [--host 127.0.0.1] [--port 8765] [--timeout 5]
                                      [--read-only | --disable-destructive]
# дефолты из env BACKEND_CTL_HOST / BACKEND_CTL_PORT — те же, что у driver/harness
```

Регистрация для Claude Code — плагин `mcp-backend-ctl`
(`.claude/plugins/mcp-backend-ctl/`): включить в `.claude/enabled.yaml`
(`mcp-backend-ctl: {enabled: true}`) и пересобрать конфигурацию (`/core:plugin:sync`),
либо вручную добавить в `.mcp.json`:

```json
"backend-ctl": {"command": "uv", "args": ["run", "--no-sync", "python", "-m", "backend_ctl.mcp_server_sdk"]}
```

### streamable-HTTP мультиклиент (D.2, BCTL-ADR-005)

`--http` поднимает **streamable-HTTP** транспорт: несколько агентов (наблюдатель/
экспериментатор/ревьюер) на одной живой системе одновременно. Каждая MCP-сессия получает
свой `DriverSession` → сокет → `session`-uuid (изоляция поверх D.1a); завершение сессии
(DELETE / idle-timeout / обрыв) снимает её durable-подписки.

```bash
python -m backend_ctl.mcp_server_sdk --http [--http-bind 127.0.0.1:8901] [--read-only]
# --http-bind — адрес HTTP-СЕРВЕРА (не путать с --host/--port БЭКЕНДА)
# env: BACKEND_CTL_HTTP_BIND, BACKEND_CTL_HTTP_IDLE_TIMEOUT (сек, default 1800)
```

**Инвариант:** HTTP-режим ТРЕБУЕТ бэкенд с `session_isolation=ON` (иначе broadcast течёт
между сессиями). Сервер fail-fast проверяет флаг через `introspect.router_stats` и громко
отказывает, если бэкенд поднят broadcast'ом. Подними бэкенд с `BACKEND_CTL_SESSION_ISOLATION=1`.
**Safety-режим — per-server:** нужны одновременно read-only и full — два инстанса на разных
портах (не per-session). `.mcp.json` с HTTP-транспортом:

```json
"backend-ctl-http": {"type": "http", "url": "http://127.0.0.1:8901/mcp"}
```

### Flight recorder — запись → offline-реплей (D.4, BCTL-ADR-006)

Живая сессия отладки невоспроизводима. `record_start` пишет снимок состояния + JSONL-ленту
событий; `record_load` прогружает запись в **тот же** read-model **без живой системы**
(«detached driver» — реплей качает события через ту же точку входа `_emit_event`, что живой
транспорт; второго read-model/классификатора не появляется). Над записью работают
`telemetry_snapshot` / `telemetry_history` (с записанными ts) / `events_page` / `state_get` /
`system_overview` (записанный, `recorded=true`) / `await_condition`; прочие инструменты
(write/IPC/subscribe) в replay-режиме дают обучающую ошибку «требует живой системы —
`record_unload()`».

```bash
# в live-сессии:
record_start(name="bug_repro")   # пиши то, на что подписан (watch_like_gui/state_subscribe)
# …активность… → record_stop()
# позже, без живой системы:
record_load(name="bug_repro", position="end")   # end — финал сразу; start — тайм-трэвел
telemetry_snapshot(); telemetry_history(path=...); await_condition(...)
record_unload()                                  # вернуться к live
```

- **`await_condition` над записью** — навигация playhead'ом: прокручивает ленту до попадания и
  ОСТАЁТСЯ там (snapshot после = момент срабатывания); конец без попадания → `end_of_recording`.
  `position="start"` + серия `await_condition` = пошаговый тайм-трэвел.
- **Границы:** все `record_*` = read-safety (бэкенд не мутируется). Файлы — только в
  `BACKEND_CTL_RECORD_DIR` (default `./backend_ctl_records/`) по ИМЕНИ (без разделителей/`..`).
  Файл без footer (crash) → `truncated:true`, но грузится.
- **⚠️ Запись содержит состояние системы** (пути/конфиги/параметры рецептов) — v1 без редакции,
  dev-only, локальный файл. **Не прикладывай запись к публичным issue.**

### Доверие: аудит / валидация / limits (Phase E)

- **E.1 аудит-журнал.** Каждый write/escalated-вызов сессии (`set_register`/`send_command`/…) оседает
  записью JSONL: инструмент, аргументы, время, исход (`ok`/`error`). Read/subscribe в журнал не шумят.
  `session_log(limit?)` — хвост журнала ЭТОЙ сессии (in-memory кольцо, без протечки чужих сессий);
  durable-файл — `BACKEND_CTL_AUDIT` или `<record_dir>/audit.jsonl`. Best-effort: сбой журнала не роняет вызов.
- **E.2 валидация `send_command`.** Перед отправкой args сверяются со схемой (`params_schema`) из
  capabilities-кэша сессии: неполные аргументы / неизвестный адресат → обучающая ошибка (`validation:true`)
  вместо таймаута. Консервативно: незаявленная команда / деградированный свод → пропуск (не ложный блок).
- **E.3 limits тяжёлых ответов.** `telemetry_history` — дефолт `limit=100`; `state_get_subtree`/
  `system_overview`/`telemetry_history` крупнее `RESPONSE_BYTE_CAP` (12K) усекаются до карты формы
  (ключи→тип/размер) + подсказка. `full=true` — полный объём.

## Тесты и headless-harness (Ф1 Task 1.3)

`backend_ctl/harness.py::BackendHarness` — pytest-инструмент headless-запуска прототипа
**без GUI** с гарантированным teardown (никаких висящих процессов — урок Ф0.4):

- **Честный headless:** процесс презентации (`gui`) исключается из топологии функцией
  `strip_gui()` ДО сборки `SystemBuilder` — Qt/LoginDialog не спавнится. Прод-код не
  трогается: harness собирает launcher из тех же публичных помощников прототипа.
- **Гарантированный teardown:** `stop()` зовёт `launcher.shutdown()` в watchdog-потоке с
  таймаутом и добивает поддерево **своего** оркестратора (scoped по pid — чужой бэкенд не
  трогает). Переживает зависший shutdown.

```bash
python -m pytest backend_ctl -m harness_smoke   # live: старт → introspect → стоп (<30с)
python -m pytest backend_ctl -q                 # весь модуль (быстрые + harness)
```

Фикстура `headless_backend` (session-scope, `backend_ctl/tests/conftest.py`) отдаёт
подключённый `BackendDriver` к headless-системе.

> **Регресс 1.1 ЗАКРЫТ (Ф1.1b):** push `state.changed` доходит до внешнего сокет-driver'а
> через мост push→канал (`RouterManager._deliver_by_targets`: у адресата-не-процесса нет
> очереди → доставка через одноимённый зарегистрированный `SocketChannel`). Бывший xfail
> снят, есть live-регресс-тест.

## Proof of value (сценарий Этапа 2)

```python
with BackendDriver(port=8765) as drv:
    h = drv.introspect_handlers("preprocessor")
    # "register_update" ОТСУТСТВУЕТ в router_handlers → у плагина нет worker-side
    # приёмника. Диагноз за секунды, без единого клика в GUI.
```

## Безопасность

Dev-инструмент: bind `127.0.0.1`, гейт `BACKEND_CTL=1`, без аутентификации. В проде
endpoint не поднимается. Остановка — PID-specific (закрытие канала при shutdown PM),
без глобального taskkill.

## Связанное

- **«Контактная книжка» (полный каталог команд/регистров/каналов):**
  [`docs/contracts/CAPABILITIES.md`](../docs/contracts/CAPABILITIES.md) — генерируется
  `python -m backend_ctl.dump_capabilities`, дрейф ловит CI. Список команд здесь НЕ дублируем.
- Канал: [`router_module/channels/socket_channel.py`](../multiprocess_framework/modules/router_module/channels/socket_channel.py)
- Адаптер: [`router_module/adapters/socket_bridge_adapter.py`](../multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py)
- Поднятие: [`process_manager_module/process/backend_ctl_endpoint.py`](../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py)
- Билдер: [`message_module/builders/command_envelopes.py`](../multiprocess_framework/modules/message_module/builders/command_envelopes.py)
- ADR-RTR-008, план [`backend-control-mcp`](../plans/_archive/2026-05-31_backend-control-mcp/plan.md) (P0-P3 закрыты; P3 = Ф1 Task 1.7 constructor-master)
