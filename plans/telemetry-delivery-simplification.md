# Plan: Упрощение пути доставки live-телеметрии

- **Slug:** telemetry-delivery-simplification
- **Дата:** 2026-06-03 (статус обновлён 2026-07-16)
- **Статус:** **SUPERSEDED** (2026-07-16) → [`gui-telemetry-read-model.md`](gui-telemetry-read-model.md). Gate из решения ниже сработал 2026-07-16 (диагностирован шторм блокирующих подписок при открытии вкладки «Процессы»), но Option D реализована **не** как отдельный snapshot-канал бэкенд→GUI, а как **read-model поверх УЖЕ работающего потока дельт**: coverage-check + async-subscribe + prefix-replay (Фаза 0) + `TelemetryViewModel` (Фаза 1, тот же класс, что задуман здесь) + история из `telemetry_sink` (Фаза 2). Инвариант «0 блокирующего IPC / 0 серверных подписок на покрытых путях» зафиксирован ADR-136 (`multiprocess_framework/DECISIONS.md`). Полный snapshot-канал (третий data-plane путь бэкенд→GUI) остаётся отклонённой альтернативой — см. `gui-telemetry-read-model.md` «Отклонённые альтернативы» / ADR-136. Текст ниже — исторический (запись D-цели и анализ хопов), сохранён без изменений.
- **Ветка:** feat/comm-system-target-architecture (часть comm-system, НЕ новый branch)
- **Родительский план:** [`comm-system-target-architecture.md`](_archive/comm-system-target-architecture.md) §7 (а), §12 P0 «разблокировать телеметрию»
- **Доказательная база:** memory `project_telemetry_subscription_bug`, рантайм-probe сессии 2026-06-03, аудиты [`comm-system-communication-audit.md`](_archive/comm-system-communication-audit.md)

---

## РЕШЕНИЕ (2026-06-03): целевая архитектура = D (snapshot-канал), миграция через A как Шаг 0

> Установка владельца: **сделать сразу ХОРОШО и масштабируемо** (навести порядок, потом масштабировать), а не «лишь бы заработало». Два investigator-аудита (read-only, Opus) дали системный ответ.

**Ключевой факт (HIGH confidence):** реактивное дерево StateStore в рантайме несёт **почти только телеметрию процессов**. Конфиг → `ConfigStore`; cross-tab (recipes/services/topology) → domain `EventBus`; 5 backend-адаптеров (`cameras/services/displays/recipes/registers`) в проде создаются с `state_proxy=None` (no-op). 100% живых GUI-биндингов — на `processes.*`/`system.*`. → **вывести телеметрию из дерева архитектурно ЧИСТО** (живых cross-tab/конфиг-потребителей дерева нет; классы StateStore остаются как capability).

**Целевой поток (D, ~6 хопов вместо ~20):**
```
ProcessMonitor собирает snapshot-dict {processes:{name:{status,fps,latency,uptime,workers}}, system:{active,avg_fps,broken_wires}}
  → RouterManager.send (data-канал, как кадры) → message_processor
  → DataReceiverBridge.dispatch (тот же проверенный bridge, data_type="telemetry_snapshot")
  → TelemetryViewModel (GUI, единый владелец «снимок→виджет») → карточки/health
```
Ноль glob, Dict-at-Boundary естественно, единый IO→Qt bridge (как кадры), throttle не нужен (период задаёт таймер snapshot).

**Почему D, а не A-навсегда:** при масштабе (20 проц × 50 метрик × 10 вкладок) A не масштабируется — двойной glob-матчинг (backend SubscriptionManager + GUI GuiStateBindings) по тысячам дельт. D = O(процессы), не O(метрики×подписки). **Почему не гибрид:** плодит ТРЕТИЙ путь данных бэкенд→GUI (frame+reactive+snapshot) против унификации §2; живого реактивного потребителя статуса вне телеметрии НЕТ.

**Миграция (двухшаговая, инвариант: серверная публикация и кадры hot-path не трогаем):**
- **Шаг 0 = A (Task 1.1+1.2):** убрать `_StateDeltaEmitter`+`invokeMethod`, гнать через bridge, multi-subscriber. Чинит видимый баг минимальным риском И кладёт общий bridge — **фундамент D, не заплатка-тупик**.
- **Шаг 1 = D:** snapshot-publisher в ProcessMonitor (за флагом, параллельно) → `TelemetryViewModel` на GUI → перевод `_panels.py`/`main_window.py` с `bindings.bind(glob)` на чтение view-model → убрать из ПУТИ телеметрии reactive-листья (`subscribe("processes.**")`, throttle-правила, GuiStateBindings для `processes.*`/`system.*`). Классы StateStore/адаптеры — оставить (capability).

**Влияние на задачи ниже:** Task 1.1/1.2/2.1 — **остаются** (Шаг 0 + fail-loud). Task 3.1/3.2 — **меняются**: ProcessMonitor агрегирует fps/health в snapshot-dict, а не в reactive-листья. **Task 4.1 (widget-replay) — ОТМЕНЯЕТСЯ**: при snapshot late-binding ленивых вкладок не проблема — новая вкладка читает текущий snapshot из view-model сразу (убирает целый класс багов «разовая дельта пропущена»).

> Если реализацию откладываем — это естественная точка: решение зафиксировано, Шаг 0 (Task 1.1) — первый конкретный шаг в новой сессии. Детальная декомпозиция Шага 1 (D) — отдельным /plan когда дойдём.

> Это **детализация P0-подзадачи телеметрии** из comm-system. Вынесено в отдельный файл: 4 блока задач (доставка / fail-loud / издатели метрик / late-binding) + анализ хопов + сравнение архитектур не помещаются в и без того перегруженный (529 строк) comm-system без потери читаемости. Родительский план содержит ссылку сюда.

---

## Обзор

Вкладка «Процессы» показывает «—» (серые индикаторы, FPS/Latency «—», «Активно: 0»), хотя процессы работают и backend публикует телеметрию. **Доказано рантайм-probe'ами:** сервер (ProcessMonitor → StateStore → DeltaDispatcher) и IPC-доставка РАБОТАЮТ; `GuiStateProxy.on_state_changed` получает дельты 300× в IO-потоке. **Единая точка обрыва:** переход IO→Qt main thread через `QMetaObject.invokeMethod(_StateDeltaEmitter, "_on_state_deltas", QueuedConnection)` молча НЕ доставляет — слот `_on_state_deltas` FIRED 0 раз.

Цель (в духе comm-system: единая коммуникация, чёткая ответственность, fail-loud): **сократить путь доставки, сделать единым владельца «состояние→виджет», убрать молчаливые обрывы на границах потоков.**

---

## 1. Анализ избыточности — где хопы лишние

Текущий путь одного статуса (~23 хопа, 2 процесса, 3 потока, 4 переформатирования):

```
БЭКЕНД (ProcessManager): ProcessMonitor._broadcast_status_change → _publish_state →
  StateStoreManager.handle_state_set → MiddlewarePipeline(throttle) → TreeStore.set→Delta →
  DeltaDispatcher.dispatch → SubscriptionManager.match → _send_state_changed → router.send_async →
  queue_registry {gui}_system (IPC pickle)
GUI: message_processor → message_dispatcher → GuiStateProxy.on_state_changed → _deserialize_deltas →
  _update_cache → _dispatch_via_qt → QMetaObject.invokeMethod(QueuedConnection) ← ☠️ ОБРЫВ →
  _StateDeltaEmitter._on_state_deltas → bridge.dispatch → _deliver signal → _state_multiplexer →
  GuiStateBindings._on_state_msg → match_glob → setter → StatusIndicator.set_state
```

**Лишний слой — GUI-сторона, хопы 4-6 переформатирования и двойной механизм пересечения потока:**

- **Хоп ☠️ (обрыв):** `_dispatch_via_qt` → `_StateDeltaEmitter._on_state_deltas`. Это ОТДЕЛЬНЫЙ механизм пересечения потока (`invokeMethod` к выделенному QObject), который НЕ работает. При этом **рядом, через тот же `DataReceiverBridge`, кадры успешно пересекают IO→Qt** (`frame_received` фаерит) — bridge использует `_deliver = Signal(object)` + `connect(..., AutoConnection)` + `emit()`. State-путь зачем-то изобретает второй механизм.
- **Двойной reformat:** `GuiStateProxy` собирает `Delta`-объекты → `_StateDeltaEmitter` конвертирует каждую в dict `{data_type, path, value}` → `bridge.dispatch` снова классифицирует по `data_type` → `_on_deliver` → `_state_multiplexer` → `GuiStateBindings._on_state_msg` парсит обратно.
- **Closure-мультиплексор** (`app.py:249-257`) `_state_multiplexer` оборачивает `bindings._on_state_msg` ради `topology_bridge.on_state_delta` — single-slot `set_state_callback` не поддерживает несколько подписчиков.

**Целевое число хопов GUI-стороны:** убрать выделенный emitter + invokeMethod (минус 1 механизм + 1 обрыв). `GuiStateProxy.on_state_changed` (IO-поток) → `bridge.dispatch(dict)` напрямую (тот же проверенный путь, что кадры) → `_deliver.emit()` пересекает поток → `_on_deliver` → подписчики. Минус ~2 хопа, минус целый класс `_StateDeltaEmitter`, и главное — **единый проверенный механизм пересечения потока для frame и state**.

> Серверную сторону (≈12 хопов до IPC) НЕ трогаем — она доказанно работает и несёт реальную ответственность (throttle, дельты, glob-match подписок, дедупликация). Оптимизация серверных хопов — вне scope.

---

## 2. Варианты целевой архитектуры доставки IO→Qt

| Вариант | Суть | Хопы GUI-стороны | Trade-off |
|---|---|---|---|
| **A. Reuse bridge-пути кадров (РЕКОМЕНДАЦИЯ)** | Удалить `_StateDeltaEmitter` + `_dispatch_via_qt`/`invokeMethod`. `GuiStateProxy` в IO-потоке вызывает callback (новый параметр `delta_sink`), который в `GuiProcess` = `lambda deltas: [bridge.dispatch({...}) for d in deltas]`. `bridge._deliver.emit()` (AutoConnection) пересекает поток — ТОТ ЖЕ механизм, что у кадров. | `on_state_changed` → delta_sink → bridge.dispatch → emit → _on_deliver → подписчики (≈4) | + Единый проверенный механизм (кадры доказали). + Минус класс + минус обрыв. + `GuiStateProxy` остаётся generic (Qt не импортирует — sink это callback). − Нужно multi-subscriber у bridge (bindings + topology_bridge) — но это уже нужно (см. C). |
| **B. Оставить как есть + точечно починить invokeMethod** | Найти, почему `invokeMethod` к `_state_emitter` не доставляет (thread-affinity? нет event loop?), и починить регистрацию emitter / connection. | без изменений (≈6, обрыв убран) | + Минимальная дельта. − Сохраняет ДВА механизма пересечения потока (загадка «почему frame работает, а state нет» остаётся технической миной). − Не упрощает, лечит симптом. − `invokeMethod` со строковым именем слота — хрупкий (нет проверки на compile-time). |
| **C. Прямой Signal на GuiStateProxy без bridge** | Дать `GuiStateProxy` собственный `Signal(list)`, GUI подключает слот напрямую. | `on_state_changed` → emit signal → слот → подписчики (≈3) | + Самый короткий. − `GuiStateProxy` живёт во framework и НЕ должен импортировать PySide6 (тестируется без Qt) — нарушает ADR. − Дублирует механизм bridge третьим вариантом. |

**Рекомендация — Вариант A.** Он реализует прямой тезис comm-system §7 (а) «убрать второй no-op hop, использовать проверенный bridge» и §9.10 «worker→main для state через DataReceiverBridge». `GuiStateProxy` остаётся Qt-free (sink — обычный callback, инжектируется из GuiProcess). Кадры уже доказали, что bridge-механизм надёжно пересекает IO→Qt из non-QThread.

**Сопутствующее (нужно для A и само по себе полезно):** `DataReceiverBridge.set_state_callback` — single-slot; `_state_multiplexer`-closure (app.py) обходит это вручную. Заменить на multi-subscriber (`add_state_listener`) — bindings и topology_bridge подписываются независимо, closure удаляется. Это §7 (г) comm-system.

---

## 3. Принцип приёмки (для всех задач блока «доставка»)

**Главный verify-критерий — рантайм, не unit:**
1. `QT_MCP_PROBE=1 python -u multiprocess_prototype/run.py` (или `/run-proto`).
2. Открыть вкладку «Процессы».
3. qt-mcp скриншот (`qt_screenshot`) + `qt_snapshot` карточек.
4. **Acceptance:** индикаторы статуса ЗЕЛЁНЫЕ (running), FPS/Latency — числа (не «—»), «Активно: N» (N = число running-процессов, не 0).

> pytest-qt unit-тесты НЕ доказывают реальную сборку (memory `feedback_qt_mcp_smoke_verification`). Каждая задача доставки закрывается qt-mcp smoke.

---

## Порядок выполнения

### Phase 1: Упрощение и починка доставки IO→Qt (vertical slice)

- Task 1.1: **[VERTICAL SLICE]** Reuse bridge-пути для state-дельт + удалить _StateDeltaEmitter [DONE 4e186997]
  - **Module contract:** public-api-change (GuiStateProxy)
  - Доказано: unit + threaded IO→Qt integration тест (воспроизводит исходный баг) + live smoke (0 исключений). **Находка:** видимый «зелёный» эффект требует Task 4.1 (разовая status-дельта на старте теряется для ленивой вкладки) + отдельный backend-баг «process.stop таймаут→crashed, process.start no-op».
- Task 1.2: Multi-subscriber bridge + удалить _state_multiplexer closure [PENDING]
  - **Module contract:** public-api-change (DataReceiverBridge)

### Phase 2: Fail-loud на границах (убрать молчаливые drop)

- Task 2.1: Fail-loud в доставке IO→Qt и десериализации дельт [PENDING]
  - **Module contract:** impl-only

### Phase 3: Издатели метрик (FPS / latency / health)

- Task 3.1: Воркеры репортят hz → ProcessMonitor агрегирует processes.X.state.fps/latency_ms [PENDING] (зависит от 1.1)
  - **Module contract:** public-api-change (worker_module interfaces)
- Task 3.2: ProcessMonitor публикует system.health.active/avg_fps/broken_wires [PENDING] (зависит от 3.1)
  - **Module contract:** impl-only

### Phase 4: Widget-level late-binding для ленивых вкладок

- Task 4.1: Replay закэшированного значения при GuiStateBindings.bind() [DONE] (зависит от 1.1)
  - **Module contract:** impl-only
  - **qt-mcp smoke ПОДТВЕРДИЛ:** статус-индикаторы ЗЕЛЁНЫЕ сразу при открытии ленивой вкладки «Процессы». Видимый баг серых индикаторов закрыт (1.1 доставка + 4.1 replay). FPS/«Активно: N» остаются «—» до Task 3.1/3.2 (издатели метрик).

---

## Задачи

### Task 1.1 — Reuse bridge-пути для state-дельт + удалить _StateDeltaEmitter

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** State-дельты пересекают IO→Qt через ТОТ ЖЕ механизм `DataReceiverBridge._deliver`, что и кадры; класс `_StateDeltaEmitter` и путь `invokeMethod` удалены; индикаторы статуса становятся зелёными.
**Context:** Единственная доказанная точка обрыва всей state-телеметрии — `QMetaObject.invokeMethod(_StateDeltaEmitter, "_on_state_deltas", QueuedConnection)` в `GuiStateProxy._dispatch_via_qt` (slot FIRED 0×). Рядом кадры через `bridge._deliver.emit()` (AutoConnection) успешно пересекают тот же поток. Заменяем сломанный второй механизм на проверенный.
**Files:**
- `multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py` — заменить `signal_emitter`/`_dispatch_via_qt`/`invokeMethod` на generic callback-sink (`delta_sink: Callable[[list], None]`), вызываемый из `on_state_changed` в текущем (IO) потоке. PySide6 НЕ импортировать (остаётся Qt-free).
- `multiprocess_prototype/frontend/process.py` — удалить класс `_StateDeltaEmitter`; в `_init_application_threads` вместо `signal_emitter=self._state_emitter` передать `delta_sink=self._on_state_deltas_to_bridge`, где новый приватный метод гонит каждую дельту в `self._bridge.dispatch({"data_type": "state_delta", "path": d.path, "value": d.new_value})`.
- `multiprocess_framework/modules/state_store_module/tests/` — обновить/добавить тесты GuiStateProxy на callback-sink (fallback `_invoke_callbacks` при sink=None сохранить для legacy/тестов).

**Steps:**
1. В `GuiStateProxy.__init__` заменить параметр `signal_emitter: QObject | None` на `delta_sink: Callable[[list], None] | None`. Сохранить backward: если `delta_sink is None` → fallback `_invoke_callbacks` (как сейчас при `signal_emitter is None`).
2. В `on_state_changed`: после `_deserialize_deltas` + `_update_cache` — если `delta_sink` задан, вызвать `delta_sink(deltas)` напрямую (IO-поток; маршалинг в Qt — ответственность sink через bridge). Удалить `_dispatch_via_qt` и весь `QMetaObject.invokeMethod`-блок.
3. Обновить docstring модуля (убрать пример с `GuiEmitter`/`@Slot`, заменить на пример с `delta_sink` через bridge).
4. В `process.py` удалить класс `_StateDeltaEmitter` (строки 25-41) и атрибут `self._state_emitter`. Добавить метод `_on_state_deltas_to_bridge(self, deltas)` который для каждой дельты зовёт `self._bridge.dispatch(...)`.
5. В создании `GuiStateProxy` заменить `signal_emitter=self._state_emitter` на `delta_sink=self._on_state_deltas_to_bridge`.
6. Проверить, что подписка `subscribe("processes.**", lambda _deltas: None, ...)` остаётся (нужна, чтобы DeltaDispatcher слал дельты на gui).

**Acceptance criteria:**
- [ ] `python scripts/run_framework_tests.py` без новых fail; тесты GuiStateProxy зелёные.
- [ ] grep по `_StateDeltaEmitter`, `invokeMethod`, `signal_emitter` в `state_store_module` и `frontend` — 0 совпадений (кроме CHANGELOG/доков).
- [ ] **qt-mcp smoke (главный критерий):** `/run-proto` → вкладка «Процессы» → индикаторы статуса ЗЕЛЁНЫЕ (running). Скриншот приложить.
- [ ] `GuiStateProxy` по-прежнему НЕ импортирует PySide6 (grep `PySide6`/`QtCore` в gui_state_proxy.py — 0).

**Out of scope:** НЕ трогать серверную сторону (`ProcessMonitor`, `StateStoreManager`, `DeltaDispatcher`, IPC). НЕ менять формат дельт в IPC. НЕ чинить FPS/latency-издателей (Task 3.x).
**Edge cases:** `delta_sink=None` (тесты без Qt) → fallback `_invoke_callbacks` обязан работать как раньше. Пустой `deltas` → ранний return (уже есть). Исключение в sink — см. Task 2.1 (fail-loud), пока не глушить.
**Dependencies:** —
**Module contract:** public-api-change

---

### Task 1.2 — Multi-subscriber bridge + удалить _state_multiplexer closure

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `DataReceiverBridge` поддерживает несколько подписчиков на state (вместо single-slot `set_state_callback`); closure `_state_multiplexer` в app.py удалена; bindings и topology_bridge подписываются независимо.
**Context:** Сейчас `set_state_callback` — single-slot, поэтому `app.py:249-257` оборачивает `bindings._on_state_msg` closure'ой ради `topology_bridge.on_state_delta`. Это хрупко и скрывает порядок вызова. comm-system §7 (г): «multi-subscriber listener вместо single-slot set_*_callback (убрать closure _state_multiplexer)».
**Files:**
- `multiprocess_prototype/frontend/bridge_impl.py` — добавить `add_state_listener(cb)` (список callbacks); `_on_deliver` для kind=="state" вызывает всех слушателей + emit `state_updated`. Сохранить `set_state_callback` как тонкий шим (append в список) для backward, ИЛИ заменить полностью если нет других вызывателей (проверить grep).
- `multiprocess_prototype/frontend/app.py` — удалить closure `_state_multiplexer` (249-257); вместо неё `process._bridge.add_state_listener(bindings._on_state_msg)` и `process._bridge.add_state_listener(_topology_state_listener)` где listener фильтрует `data_type=="state_delta"` и зовёт `topology_bridge.on_state_delta`.

**Steps:**
1. В `DataReceiverBridge`: заменить `self._state_cb: Callable | None` на `self._state_listeners: list[Callable]`. Добавить `add_state_listener(cb)`. В `_on_deliver` kind=="state": итерировать `_state_listeners`. Решить судьбу `set_state_callback` — grep вызывающих; если только bindings/app — заменить, иначе шим.
2. В `app.py`: удалить `_original_state_cb`/`_state_multiplexer`/`set_state_callback`-вызов. Подписать `bindings._on_state_msg` через `add_state_listener`. Вынести логику topology в именованный метод-listener (не closure).
3. Проверить grep `set_state_callback` и `_state_multiplexer` по проекту.

**Acceptance criteria:**
- [ ] grep `_state_multiplexer` → 0; grep `set_state_callback` → 0 (или только шим-определение).
- [ ] **qt-mcp smoke:** карточки обновляются И topology_bridge получает дельты (вкладка «Процессы» зелёная + переход на «Pipeline» не ломается).
- [ ] `python scripts/run_framework_tests.py` без новых fail.

**Out of scope:** НЕ трогать `set_frame_callback`/`set_command_callback` (frame-путь не меняем). НЕ менять классификацию `dispatch()`.
**Edge cases:** Порядок listener'ов — bindings раньше topology (как сейчас в closure). Listener бросил исключение — не должен блокировать остальных (см. Task 2.1).
**Dependencies:** Task 1.1 (после него state-дельты реально текут через bridge).
**Module contract:** public-api-change

---

### Task 2.1 — Fail-loud на границах доставки IO→Qt

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Молчаливые `except: pass` / тихие drop на пути state-доставки заменены на громкие (warning/error лог с контекстом + метрика); единственный сигнал «дельта потерялась» теперь видим, а не молчит.
**Context:** comm-system §12 P0 пп.20-22 + §11 п.21: `GuiStateProxy._dispatch_via_qt` нарушал main-thread контракт молча; `bindings._on_state_msg` setter падает в `except: pass` (строки 202-211); listener-исключения не логируются. Принцип comm-system: границы потоков/процессов падают ГРОМКО. После Task 1.1 механизм другой — но fail-loud дисциплину закрепляем здесь отдельной задачей.
**Files:**
- `multiprocess_prototype/frontend/state/bindings.py` — в `_on_state_msg`, блоки `except Exception: pass` (setter, ~202 и ~210) → лог warning через доступный логгер + метрика; первое исключение на путь — не глушить полностью (хотя бы первое логировать с path+prop).
- `multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py` — в `on_state_changed`/`_deserialize_deltas`: если десериализация дала пусто при непустом msg — `_log_warning` (сейчас тихий return). Исключение в `delta_sink` — логировать `_log_error` (не глушить молча).
- `multiprocess_prototype/frontend/bridge_impl.py` — `_on_deliver`: исключение listener'а → лог + продолжить остальных (не молчаливый pass).

**Steps:**
1. `bindings.py`: ввести лёгкий логгер (передать в `GuiStateBindings.__init__` опц. `logger`, fallback на `print`/`logging`); в setter-`except` логировать `(path, prop, type(exc))` хотя бы раз на handle (можно флаг `_warned`). НЕ менять happy-path.
2. `gui_state_proxy.py`: `_deserialize_deltas` вернул `[]` при наличии полезной нагрузки → `_log_warning` с кратким msg-сигнатурой. Обернуть `delta_sink(deltas)` в try → `_log_error`.
3. `bridge_impl.py`: listener-цикл — try/except на listener с логом, continue.
4. Подтвердить: нет НОВЫХ молчаливых `pass` (ruff/grep `except Exception:\s*pass` на затронутых файлах).

**Acceptance criteria:**
- [ ] grep `except Exception:\s*pass` в bindings.py / gui_state_proxy.py / bridge_impl.py на state-пути — заменены на логирующие.
- [ ] Намеренно сломанный setter (тест: bind на несовместимый widget) → в логе появляется warning с path+prop (не тишина).
- [ ] `python scripts/run_framework_tests.py` без новых fail.

**Out of scope:** НЕ вводить fail-fast (краш приложения) — телеметрия не критична, цель видимость, не падение. НЕ трогать frame-путь exception-handling.
**Edge cases:** Логирование не должно спамить (1 раз на handle/path, не на каждую дельту 10 Гц). Логгер недоступен → `logging.getLogger`.
**Dependencies:** Task 1.1 (новый путь), желательно после 1.2.
**Module contract:** impl-only

---

### Task 3.1 — Воркеры репортят hz → ProcessMonitor агрегирует processes.X.state.fps/latency_ms

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Появляется издатель `processes.{name}.state.fps` и `processes.{name}.state.latency_ms` (на которые подписаны карточки), агрегированный из per-worker `effective_hz`/`cycle_duration_ms`.
**Context:** memory: за ~12000 publish'ей НИ ОДНОГО `workers.*.effective_hz` — `WorkerManager.get_worker_status` подмешивает `effective_hz`/`cycle_duration_ms` ТОЛЬКО если у target есть `get_cycle_metrics` (IdleWorker и наследники; `worker_manager.py:259-269`). Обычные application-воркеры hz не репортят. Карточки же подписаны на `state.fps` (агрегат процесса), `state.latency_ms` — издателя нет вообще. Нужно: (1) воркеры репортят hz; (2) ProcessMonitor агрегирует в `state.fps`/`state.latency_ms`. comm-system выбор владельца — Option A (бэкенд публикует ожидаемые пути).
**Files:**
- `multiprocess_framework/modules/worker_module/core/worker_manager.py` — обеспечить, чтобы `get_worker_status` отдавал `effective_hz`/`cycle_duration_ms` для application-воркеров в LOOP-режиме (источник тайминга цикла уже есть для IdleWorker; распространить на base loop-механику или измерять в самом worker-runner). Если контракт меняется — `interfaces.py`.
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` — в `_on_heartbeat_received` (после публикации per-worker метрик, ~163) агрегировать: `state.fps` = сумма/макс/среднее `effective_hz` running-воркеров процесса (выбрать семантику — задокументировать); `state.latency_ms` = макс `cycle_duration_ms`. Опубликовать через `_publish_state`.

**Steps:**
1. Определить семантику агрегата (предложение: `state.fps` = effective_hz главного/data-воркера или max по воркерам; `state.latency_ms` = max cycle_duration_ms). Зафиксировать в docstring + DECISIONS если спорно.
2. worker_module: распространить cycle-метрику (`effective_hz`/`cycle_duration_ms`) на application loop-воркеры, а не только IdleWorker. Минимально — измерять длительность итерации в loop-runner и считать hz = 1/interval. Обновить `interfaces.py` если расширяется контракт `get_worker_status`.
3. process_monitor: в `_on_heartbeat_received` собрать per-process агрегат и `_publish_state("processes.{sender}.state.fps", ...)` / `state.latency_ms`.
4. Тесты: unit на агрегацию (несколько воркеров → ожидаемый fps/latency); тест что application-воркер отдаёт effective_hz.

**Acceptance criteria:**
- [ ] Probe `BACKEND_CTL=1 python -m backend_ctl.probes.telemetry_probe` (или аналог) показывает `processes.X.state.fps` и `state.latency_ms` непустыми для running-процессов.
- [ ] **qt-mcp smoke:** карточки показывают FPS — число (не «—»), Latency — число.
- [ ] `python scripts/run_framework_tests.py` без новых fail.

**Out of scope:** НЕ менять формат heartbeat-конверта помимо добавления метрик (не трогать `subtype`/`workers_status` структуру сверх hz). НЕ публиковать system.health (Task 3.2).
**Edge cases:** Воркер не в running → не учитывать в агрегате. effective_hz=None (нет цикла, event-mode) → пропустить, не публиковать 0. Процесс без воркеров с hz → `state.fps` не публикуется (карточка остаётся «—», это корректно, не «0»).
**Dependencies:** Task 1.1 (иначе не видно в GUI).
**Module contract:** public-api-change (worker_module interfaces)

---

### Task 3.2 — ProcessMonitor публикует system.health.active/avg_fps/broken_wires

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Появляется издатель `system.health.active`, `system.health.avg_fps`, `system.health.broken_wires` (health-метки внизу вкладки «Процессы»).
**Context:** memory: фреймворковый `state_store_module/health/monitor.py` публикует другие ключи (`system.health.overall/<name>`) и не подключён в прототипе; карточки подписаны на `active/avg_fps/broken_wires` — издателя нет → «Активно: 0», «Средний FPS: —». ProcessMonitor — естественный издатель (знает все процессы, их статусы и теперь fps из 3.1).
**Files:**
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` — в monitoring loop (рядом с `_publish_uptime`, ~204) добавить `_publish_health`: `active` = число running-процессов; `avg_fps` = среднее `state.fps` по running; `broken_wires` = число оборванных связей (источник — wire/topology state, если доступен; иначе 0 с TODO).

**Steps:**
1. Добавить метод `_publish_health(all_states)` в ProcessMonitor: посчитать `active` (running), `avg_fps` (среднее последних опубликованных fps; держать локальный кэш fps по процессам или читать из store). Вызвать в monitoring loop после `_publish_uptime`.
2. `broken_wires`: если есть доступ к wire-статусам (WireStatus/topology) — посчитать оборванные; если нет — публиковать 0 и оставить TODO-комментарий со ссылкой на источник (не выдумывать данные).
3. `_publish_state("system.health.active"/"avg_fps"/"broken_wires", ...)`.
4. Тест: N running-процессов → `active=N`; пустой → `active=0`.

**Acceptance criteria:**
- [ ] Probe показывает `system.health.active`/`avg_fps`/`broken_wires` непустыми.
- [ ] **qt-mcp smoke:** «Активно: N» (N>0 при работающих процессах), «Средний FPS: <число>».
- [ ] `python scripts/run_framework_tests.py` без новых fail.

**Out of scope:** НЕ подключать фреймворковый `health/monitor.py` (другой контракт ключей — отдельное решение). Если `broken_wires` источник недоступен — НЕ блокироваться, публиковать 0 + TODO.
**Edge cases:** 0 running → `active=0`, `avg_fps` не публиковать (или «—»), `broken_wires=0`. Деление на ноль в avg_fps — guard.
**Dependencies:** Task 3.1 (avg_fps зависит от state.fps).
**Module contract:** impl-only

---

### Task 4.1 — Replay закэшированного значения при GuiStateBindings.bind()

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** При `GuiStateBindings.bind(path, widget, prop)` виджет СРАЗУ получает последнее известное значение из кэша (если оно есть) — ленивая вкладка, созданная после прохождения разовых дельт, не пропускает статус.
**Context:** memory: вкладка «Процессы» — LazyTabWidget; `AllProcessesPanel._connect_bindings` регистрирует биндинги ПОСЛЕ того, как разовые status-дельты прошли. process-level initial replay (`16e14084`) покрывает подписку GuiProcess на старте, но НЕ позднее создание виджета. `GuiStateProxy._cache` уже хранит значения (`_update_cache`). Нужно: при `bind()` прочитать кэш и применить setter немедленно.
**Files:**
- `multiprocess_prototype/frontend/state/bindings.py` — `GuiStateBindings` получает доступ к снимку кэша (источник: `GuiStateProxy.get` или переданный provider `cache_getter: Callable[[str], Any]`). В `bind()` после регистрации handle — если для конкретного пути (не glob с `*`, либо резолв через iter_matches) есть значение в кэше → применить setter сразу.
- `multiprocess_prototype/frontend/app.py` — пробросить в `GuiStateBindings` доступ к кэшу `GuiStateProxy` (например `cache_getter=process._gui_state_proxy.get` или snapshot-метод).
- `multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py` — при необходимости публичный геттер кэша по пути/паттерну (если ещё нет).

**Steps:**
1. Решить источник значения: предпочтительно публичный `GuiStateProxy.get(path)` / `snapshot(pattern)` (proxy уже держит `_cache`). Если приватно — добавить тонкий публичный геттер.
2. `GuiStateBindings.__init__` принимает опц. `cache_getter`. В `bind()`: для конкретного пути взять текущее значение; для glob-паттерна — пройти по снимку кэша совпадающие пути и применить каждый. Применять тем же setter-механизмом, что `_on_state_msg`.
3. app.py: передать `cache_getter` при создании `GuiStateBindings`.
4. Тест: положить значение в кэш → `bind()` → setter вызван немедленно (без прихода новой дельты).

**Acceptance criteria:**
- [ ] Unit: bind на путь с уже закэшированным значением → setter применён сразу.
- [ ] **qt-mcp smoke:** открыть вкладку «Процессы» ПОСЛЕ старта (lazy) → индикаторы сразу зелёные, FPS/Latency числа без ожидания следующей дельты.
- [ ] `python scripts/run_framework_tests.py` без новых fail.

**Out of scope:** НЕ менять механизм live-дельт (только добавить initial-read при bind). НЕ дублировать process-level replay (`16e14084`) — это widget-level дополнение.
**Edge cases:** Кэш пуст для пути → не применять (виджет остаётся с дефолтом «—»). glob `*` — резолвить по снимку, не подписываться повторно. `cache_getter=None` (legacy) → bind работает как раньше без replay.
**Dependencies:** Task 1.1 (кэш заполняется только если путь доставки рабочий).
**Module contract:** impl-only

---

## Риски и ограничения

- **Hot-path Qt:** Task 1.1/1.2 трогают доставку в main thread — обязательна qt-mcp smoke-проверка после КАЖДОЙ (memory `feedback_qt_mcp_smoke_verification`), pytest-qt недостаточно.
- **Не задеть кадры:** frame-путь (`set_frame_callback`, `FrameShmMiddleware`) использует тот же bridge — не сломать классификацию `dispatch()` и `frame_received`.
- **GuiStateProxy остаётся Qt-free:** Task 1.1 не должен внести импорт PySide6 во framework-модуль (sink — generic callback). Enforced grep'ом в acceptance.
- **Семантика агрегата FPS (3.1)** — выбор (sum/max/main-worker) влияет на отображаемое число; зафиксировать в docstring/DECISIONS, согласовать с владельцем если неочевидно.
- **broken_wires источник (3.2)** может быть недоступен — допустимо публиковать 0 + TODO, не блокироваться.
- **Связь с P2 comm-system:** когда P2 внесёт авто-reply по `request_id` в `receive()`, часть серверной асимметрии исчезнет — но GUI-доставка (этот план) ортогональна и нужна независимо.
- **Параллельность агентов:** Task 1.1 (teamlead) и 3.1 (teamlead) — разные слои, но 3.x/4.x зависят от 1.1 → СНАЧАЛА 1.1, потом веер. Макс 2 параллельных без worktree (memory `feedback_parallel_agents_commit_race`).

## Связь с родительским планом

После завершения: обновить comm-system §12 P0 пункт «Fix подписки GUI на телеметрию» — отметить выполненным, со ссылкой на этот файл и хеши коммитов. Обновить memory `project_telemetry_subscription_bug` (закрыть остаток GUI-side).
