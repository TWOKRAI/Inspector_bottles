# Handoff → P2 (иерархическая адресация proc.worker)

- **Дата:** 2026-05-31
- **Ветка:** `refactor/transport-router-hub` (продолжать на ней; НЕ создавать новую)
- **Контекст:** P0 (контракт+ADR) и P1 (хаб на отправке) закрыты. Прототип запускается, кадры идут end-to-end через `router.send` (smoke: дисплей FPS 14, stitcher 56 кадров, 0 ERROR).
- **Старт нового чата:** «продолжаем transport-router-hub, P2». Прочитать `plan.md` §P2 + этот файл + recon.md.

---

## Что уже готово к проводке (P0.2 контракт, ещё НЕ в рантайме)

| Символ | Файл | Статус |
|---|---|---|
| `split_address`/`process_of`/`worker_of`/`normalize_targets`/`validate_address`/`is_broadcast` | `message_module/addressing/address.py` | реализованы, тесты, **прод-потребителей 0** |
| `RouteDecision(process, kind, channel, subpath)` + `resolve_route`/`resolve_routes` | `router_module/routing/address_aware_channel.py` | реализованы, тесты, **в рантайме НЕ вызываются** |
| `MESSAGE_TYPE_TO_CHANNEL` + `resolve_channel_kind` + `channel_name` | `router_module/routing/routing_table.py` | контракт; проводка type→register_route — P3 |

Эти функции — чистые, JSON-safe. **P2 = подключить их в живой путь доставки.**

---

## Точка проводки P2.1 (главная)

**Файл:** `router_module/core/router_manager.py` → `_deliver_by_targets` (сейчас итерирует «сырой» `target` и зовёт `queue_registry.send_to_queue(target, qtype, msg)`).

**Что сделать:** доставлять по `process_of(target)` (address[0]), а нижние уровни (`split_address(target)[1:]`) класть в билет для intra-process резолва. Backward-compat: плоское `"proc"` → `process_of` == `"proc"` (идентично сейчас). Использовать готовый `resolve_routes(msg)` / `resolve_route(target, msg)`.

**Acceptance:** доставка по `address[0]` идентична нынешней для плоских имён (паритет); билет с `"proc.worker"` ложится в очередь `proc` и несёт `worker` в payload; тест prefix-валидации.

**Риск:** низкий — для плоских targets поведение не меняется (`process_of("proc") == "proc"`). Все живые `targets` сейчас плоские (recon #2), dotted ещё нет в данных.

## P2.2 — intra-process роутинг на воркер (address[1])

**Файлы:** `router_module`/`dispatch_module` (на приёме: если `len(address)>1` → искать worker-scoped handler/очередь), `worker_module` (worker как адресуемый приёмник).
**Паттерн:** in-process `queue.Queue` как `chain_queue` (DataReceiver→chain_queue→PipelineExecutor) — НЕ возрождать `WorkerPoolDispatcher`/`chain_module` (мёртвы, ADR-COMM-001/003).
**Acceptance:** билет `[proc, worker]` доходит до worker-приёмника внутри процесса; отсутствующий воркер → дефолт+лог (не падение); нет новых IPC-очередей на воркера.

## P2.3 — реконсиляция с assigned_worker

Связать с `multiprocess_prototype/plans/processes-workers-runtime-debts.md` Фаза 2 (долг #2, вариант A: PipelineExecutor-группа на воркер + in-process `queue.Queue` handoff). P2.2 даёт транспортный дом для адреса «воркер». **Сиквенс S1 (выбран владельцем):** P0–P2 ПЕРЕД assigned_worker Фаза 2 → исполнение по воркерам строится сразу на правильной адресации.

---

## Investigation-first (правило #6 — обязательно в начале P2)

Перед кодом — `qex`/`grep`/`serena` актуализировать:
1. Все ли вызовы доставки идут через `_deliver_by_targets` (после P1.3 `send_to_process` → `router.send` → сюда). Проверить, нет ли других прямых `queue_registry.send_to_queue` вне `channels/`/роутера.
2. Где `worker_module` принимает сообщения (worker как приёмник) — есть ли уже in-process очередь у воркера.
3. Подтвердить, что dotted-адресов в живых `targets` всё ещё нет (иначе учесть).

---

## Долги P1, которые НЕ трогаем в P2 (карта, чтобы не зацепить)

- **broadcast** всё ещё мимо `router.send` (queue_registry.broadcast_message) → P4. В P2 не трогать.
- **type→register_route** проводка → P3 (Event/State-каналы). В P2 `_deliver_by_targets` сохраняет паритет-правило `_select_queue_type`.
- **vestigial `channel="data"`-strip** в `send_to_process` — band-aid до P3.1 (продюсеры перестанут слать channel). В P2 не трогать.

---

## Verify P2

- `python scripts/run_framework_tests.py` зелёные после каждой задачи.
- Паритет-тест: плоский `target` доставляется идентично до/после (тот же queue).
- Smoke прототипа: `QT_MCP_PROBE=1 python multiprocess_prototype/run.py` → дисплей показывает кадры (как сейчас), `region_pipeline` не сломан. qt-mcp: `qt_set_property w8 currentIndex` для вкладок; дисплей-слот — `DisplaySlot "ImageSlot"`.
- **Снять `session_start` baseline ПЕРЕД P2** (в P1 не сняли — не повторять промах); `session_end` после.
- Остановка прототипа: найти `.venv run.py` root PID (`wmic process ... | grep run.py`), `MSYS_NO_PATHCONV=1 taskkill /PID <root> /T /F` (НЕ глобальный taskkill).

---

## Коммиты P0+P1 (для справки)

`f212d1d2` recon → `4e22426e` P0.2 контракт → `73f37d96` trim YAGNI → `c8e68832` P0.3 ADR → `2f417169` P1 channel-guard+qtype → `9dd31d73` P1.3 send_to_process→router.send → `03e712cb` prototype auto_start.
