# lifecycle-owner-scope — один владелец для всего, что нужно закрыть

- **Slug:** `lifecycle-owner-scope` · **Ветка:** `feat/lifecycle-owner-scope` (worktree `.claude/worktrees/lifecycle`) · **Дата:** 2026-10-03
- **Статус:** DRAFT — архитектура принята CTO с условиями (раунды 1–3), условия вписаны в [`DESIGN.md`](DESIGN.md). Ф0 стартует по слову владельца.
- **Слой:** framework (`base_manager`, `event_module`, `process_module`, `process_manager_module`, `worker_module`, `frontend_module`, `registers_module`, `router_module`, `state_store_module`, `channel_routing_module`, `config_module`, `actions_module`, `service_module`, `shared_resources_module`), Services, Plugins, прототип (frontend), `backend_ctl`
- **Основание:** решение владельца 2026-10-03 («переделать так, чтобы подобных проблем не было»; «универсальный механизм у всех»; «каждый модуль отвечает за свой функционал, без дублирования, через интерфейсы, без костылей»). Триггер — аварийное завершение `run_framework_tests` ~1 из 4 (Task 5.5d плана `transport-single-policy`).
- **Архитектура и доказательства:** [`DESIGN.md`](DESIGN.md). Диаграммы для чтения: [`docs/diagrams/lifecycle/lifecycle-system.html`](../../docs/diagrams/lifecycle/lifecycle-system.html).

## Зачем — одной фразой

У подписок, потоков, процессов, окон и виджетов нет владельца, который их закроет; они доживают до случайного момента
и умирают в неправильном месте — отсюда abort тестов фреймворка, 5-секундный ханг останова, утечки GUI и ложный
«остановлен». План вводит одну область-владельца (`IScope`) и переводит на неё всё, что сегодня закрывается по-своему.

## Соседи — кто чем владеет

| План | Что там про это | Что берём | Что отдаём | Граница |
|---|---|---|---|---|
| [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md) (IN PROGRESS, Ф1 DONE) | PM владеет остановкой, `system_stop_event`, ReaderGoneQueue (ADR-SRM-015/016), сироты, ADR-PMM-031 «одно число на оба уровня»; Task 3.1 «остановка как протокол» условная | семантику эскалации `_stop_many` и метки ReaderGone — в `ChildProcessStop` (П1); формулу бюджета — в один `stop_budget.py` (П2) | внутрипроцессную половину Task 3.1 (именованные фазы = сегменты, П3); удаление хука `_before_observability_teardown` | их Task 3.1 сужается до межпроцессного quiesce → ack; `ProcessTreeGuard` и досъём `harness.py` остаются у них (П4). Их план поправлен 2026-10-03 (раньше Ф1, чтобы не было двух задач на одну работу): 3.1 сужена, хук и долги «до старта 3.1» (ADR-PM-045 → ADR-PMM-033, п.4 ADR-PMM-033) — в нашу Task 1.2; их Ф2 ⛔ наша Ф1 |
| [`transport-single-policy`](../transport-single-policy.md) | Task 5.5d (ветка `fix/t55d-qt-gc`) — «сборка Qt-мусора в тестах» | полезное из 5.5d: страж утечки потоков `batch-drain-*`, `unwire` в writethrough-тесте, `close` в тесте 3.3 — в Ф1 | 5.5d становится SUPERSEDED этим планом (abort закрывает Ф5) | ветка `fix/t55d-qt-gc` не вливается |
| [`observability-closure`](../observability-closure/plan.md) (Ф4 в работе) | Ф4 правит `observability_wiring.py` (4.1, 4.3, 4.3b, 4.14) и `process_manager_process.py` | — | ручки tap'ов и форвардеров (Ф3) | Ф3 этого плана стартует после их задач по `observability_wiring.py` или они принимают ручки в своих задачах — сверка на входе Ф3 |
| [`otel-export`](../otel-export.md) | Task 2.4 «otel flush» до снятия форвардеров | — | та же гарантия барьером (`work` закрывается до `transport`/`planes`) | единственная обёртка совместимости (G10) — `Plugins/io/otel_export/plugin.py` чужой полосы, удаляется в Ф6 |
| [`2026-09-22_gui-service`](../2026-09-22_gui-service/plan.md) | GUI как клиент (Remote*Proxy) | — | механизм владения для клиента | продолжает после Ф5 этого плана на его механизме |
| [`framework-architecture-rework`](../framework-architecture-rework/plan.md) (DRAFT) | окно codemod (Р-9) | — | — | файлов не переносим; при открытии окна codemod — сверить порядок |

## Порядок выполнения

- Task 0.1: ADR и интерфейсы владения в base_manager [PENDING]
- Task 0.2: Scope и Handle — примитив и контракт-тесты G1 [PENDING] (после 0.1)
- Task 0.3: Subscribers в event_module [PENDING] (после 0.2)
- Task 0.4: qt_lifetime — attach_qt, flush_deferred_deletes, QThreadHandle [PENDING] (после 0.2)
- Task 0.5: стражи G2–G6, G10 и база in-suite пробы abort [PENDING] (после 0.3, 0.4)
- Task 1.1: stop_budget и ChildProcessStop поверх эскалации PM [PENDING] (после 0.5)
- Task 1.2: корень процесса с барьерами, один close в раннере, G7 [PENDING] (после 1.1)
- Task 1.3: WorkerManager и PluginContext на области, G8 [PENDING] (после 1.2)
- Task 1.4: наблюдаемость процесса как ручки сегмента planes, перенос полезного из 5.5d [PENDING] (после 1.2)
- Task 1.5: стенд и приёмка Ф1 [PENDING] (после 1.3, 1.4)
- Task 2.1: регистры GUI на Subscribers с owner [PENDING] (после 1.5)
- Task 2.2: презентеры и Python-owned QObject компонентов на attach_qt, G5 fail в components [PENDING] (после 2.1)
- Task 5.1: вкладки, формы, окна, bindings, ThreadManager на области [PENDING] (после 2.2)
- Task 5.2: корень GUI и рестарт UI, слушатели моста [PENDING] (после 5.1)
- Task 5.3: гейт abort — in-suite проба 3 раза и G5 ноль по frontend [PENDING] (после 5.2)
- Task 3.1: EventBus, ActionBus, события SRM на Subscribers [PENDING] (после 5.3)
- Task 3.2: StateProxy и Config с owner [PENDING] (после 3.1)
- Task 3.3: роутер — ручки обработчиков и push-слушателей [PENDING] (после 3.1)
- Task 3.4: tap'ы и проводка наблюдаемости на ручках [PENDING] (после 3.1)
- Task 3.5: backend_ctl — списки подписчиков на Subscribers [PENDING] (после 3.1)
- Task 4.1: инфраструктурные потоки фреймворка на spawn [PENDING] (после 3.4)
- Task 4.2: Services на spawn, ServiceHost — область на сервис [PENDING] (после 4.1)
- Task 4.3: Plugins на spawn, адаптер пулов [PENDING] (после 4.1)
- Task 4.4: backend_ctl — потоки и таймеры на spawn [PENDING] (после 4.1)
- Task 6.1: удалить обёртки совместимости, все стражи в fail, документы, приёмка CTO [PENDING] (после 4.2, 4.3, 4.4, 3.2, 3.3, 3.5)

## Ф0 — механизм и стражи (без миграции потребителей)

### Task 0.1 — ADR и интерфейсы владения в base_manager
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** в `base_manager/interfaces.py` живут `Stoppable`, `CloseReport`, `Reporter`, `IHandle`, `IScope`, `ScopeClosedError`; ADR фиксирует решения DESIGN §4.
**Files:** `multiprocess_framework/modules/base_manager/interfaces.py`, `base_manager/DECISIONS.md` (новый ADR-BM-xxx), `multiprocess_framework/DECISIONS.md` (индекс через `python -m scripts.sync`), `base_manager/README.md`, `STATUS.md`, `base_manager/docs/INTERFACES_USAGE.md`. Полный спек — [`task-0.1.md`](task-0.1.md).
**Acceptance:**
- [ ] Протоколы и DTO — ровно как в DESIGN §2.1 (имена, сигнатуры, keyword-only).
- [ ] `CloseReport.to_dict()` — только примитивы (Dict at Boundary); `Scope`/`Handle` не пиклятся (проверяется в 0.2).
- [ ] ADR перечисляет отвергнутое с причиной: отдельный `lifetime_module`, WeakMethod, три корня процесса, передача close владельцу-потоку, shim-список.
- [ ] `python scripts/validate.py` зелёный (sync разделов DECISIONS).
**Out of scope:** реализация `Scope` (0.2), миграция потребителей.

### Task 0.2 — Scope и Handle: примитив и контракт-тесты G1
**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework
**Goal:** `base_manager/core/lifetime.py` (только stdlib) реализует `IScope`/`IHandle` с барьерами, тремя фазами, отчётом, `unclosed_roots()`.
**Files:** `base_manager/core/lifetime.py`, `base_manager/tests/test_lifetime_*.py`, `BaseManager.scope` + шаблонный `shutdown()` (`base_manager/core/base_manager.py`).
**Acceptance (G1, литералами):**
- [ ] (a) цикл «презентер ↔ издатель» освобождается refcount'ом после `close()` — `gc.disable()`, `unreachable == 0`.
- [ ] (b) поток игнорирует стоп 3 с при бюджете 1 с: `close()` возвращается за ≤ 1.2 с, `survivors` содержит путь, `live()` показывает `survivor`.
- [ ] (c) `own`/`spawn` после закрытия: ресурс освобождён сразу, `ScopeClosedError`; перезапуск во время close отклонён.
- [ ] (d) close изнутри рассылки: доставка прекращается на закрывшем; close из освобождения фазы 2 — `complete=False`, внешний `complete=True`.
- [ ] (e) второй close из чужого потока ждёт первого и получает тот же отчёт; (f) поток закрывает свою область без дедлока, в отчёте `self`, не «остановлен» (совет 8).
- [ ] Барьер: сегмент ниже барьера получает фазу 1 только после закрытия сегмента выше; сток, дренирующий при `request_stop`, доставляет N/N.
- [ ] `kill()` фазы 3: упрямый ресурс в `killed`, не в `survivors`.
- [ ] `Handle.close()` идёт тем же путём, что и область (одноэлементный сегмент), отцепление не оставляет цикла.
- [ ] `unclosed_roots()` видит брошенный незакрытый корень после gc (recorder держит только weakref на флаг — совет 9) и не красит закрытый.
- [ ] `pickle.dumps(scope)` / `(handle)` → `TypeError` с понятным текстом.
- [ ] Инъекции ведущего (предсказание до прогона): без проверки `active` → (d) красный; без проверки состояния в `own` → (c) красный; без барьера → тест стока красный.
**Out of scope:** Subscribers (0.3), Qt (0.4).

### Task 0.3 — Subscribers в event_module
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** один список подписчиков для всех издателей: `add(cb, *, owner: IScope) -> IHandle`, `emit` по снимку вне лока, `errors`, `emits_after_close` в отчёт владельца.
**Files:** `event_module/subscribers.py`, `event_module/interfaces.py`, `event_module/tests/`, README/STATUS, `multiprocess_framework/docs/MODULE_TIERS.md` (строка `event_module`: leaf → зависит от `base_manager.interfaces`; перенесено из 0.1 — зависимость появляется здесь).
**Acceptance:** реентрантная отписка во время `emit`; исключение подписчика изолировано и посчитано; доставка в закрытого владельца не происходит и посчитана; ручка держит издателя слабо (короткоживущий издатель не удерживается); `EventBus` пока не мигрирует (Ф3).

### Task 0.4 — qt_lifetime
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** `frontend_module/core/qt_lifetime.py`: `attach_qt`, `flush_deferred_deletes`, `QThreadHandle` (DESIGN §2.4).
**Acceptance:** закрытие области с Qt-объектом из чужого потока → `destroyed` на главном, `ownedByPython == False`, обёртка мертва после flush; без цикла событий и после `exec()` — то же после `flush_deferred_deletes()`; обработчик `destroyed` не держит объект (обёртка не бессмертна — проба CTO `cto_l6_probe2`); проверка Qt-предка при освобождении пишет `qt-tree mismatch` в `errors`.

### Task 0.5 — стражи и база пробы
**Level:** Middle+ · **Assignee:** developer · **Layer:** tests/scripts
**Goal:** G2 (сигнатуры, литеральный список издателей из DESIGN §2.6), G3/G4/G5 в режиме отчёта, G6 AST в `scripts/validate.py` с allowlist причин (fail), G10 (счётчик = 1); in-suite проба abort (`crashprobe offmain_gc`) в репозитории как приёмочная, база записана числом (сегодня crash 3/3).
**Acceptance:** каждый страж краснеет на своей инъекции из DESIGN §3; режим отчёта не меняет код возврата гейта, но печатает список.

## Ф1 — путь останова процесса (закрывает 5-секундный ханг)
Задачи 1.1–1.5 по DESIGN §2.2–2.3 и П1–П3: один `stop_budget.py` (пять чисел, четыре места чтения `"shutdown_timeout"` мигрируют), `ChildProcessStop` с меткой ReaderGone, корень процесса `planes | transport | work` с барьерами, `stop()` = `cancel()`, один `close()` в раннере, `os._exit` при выживших, golden G7 (включая два инварианта приёмки stop-ownership 09-26), WorkerManager с перезапуском в том же потоке и STOPPED по отчёту, `PluginContext.scope` (камера и воркер в одной области), G8 < 1.5 с; ручной порядок `app_module/orchestrator.py:85` и `state_store_manager.py:134` — регистрацией в области. Task 1.2 закрывает долги stop-ownership «до старта Task 3.1»: указатель ADR-PM-045 → ADR-PMM-033 и формулировку п.4 ADR-PMM-033. Детализация спеков — на входе фазы, ревью спека до тестера.

## Ф2 — регистры и контролы GUI
`RegistersManager`/`SyncTrait`/`RegisterAdapter` на `Subscribers` с обязательным `owner`; `NumericControl.create(..., owner)` и все контролы; `DebounceTrait` и 8 `QTimer()` без родителя; `BaseConfigurableWidget`; G5 fail в `components/`. Необходима для abort, не достаточна.

## Ф5 — GUI-корни (закрывает abort фреймворк-тестов)
Вкладки (`BaseTreeNavTab` и др. — основной мусор в точке abort), формы, окна, `bindings.py:266`, `ThreadManager` → `QThreadHandle`, четыре `add_change_callback` фронта и прототипа, корень GUI и рестарт UI (+3 слушателя моста на запуск). Гейт 5.3: in-suite проба 3× survived **и** G5 = 0 по frontend-тестам.

## Ф3 — остальные издатели (атомарно: издатель + все вызывающие)
EventBus/ActionBus/события SRM, StateProxy/Config, роутер (`register_message_handler` → ручка, `unregister`, push-слушатели), tap'ы и проводка наблюдаемости (после сверки с closure Ф4), списки `backend_ctl`. Удаляются `Subscription`/`_Subscription`, `remove_tap/close_all_taps`, `BindingHandle`, `wire_/unwire_`.

## Ф4 — потоки
Инфраструктура фреймворка (sweeper, окно статистики, async-sender, flusher, роутер, сокеты, консоль, ready-gate, старт сервисов), Services (`ServiceHost` — область на сервис), Plugins (`spawn`; пулы — адаптер с `kill = cancel_futures`), `backend_ctl` (рекордер, таймер автоотката). G4 и G6 в fail для всех слоёв.

## Ф6 — финал
Удалить обёртку otel (G10 = 0), все стражи в fail, allowlist без причин — пуст, README/STATUS/MODULE_TIERS, приёмка CTO с пассивной серией штатных гейтов Ф3–Ф6 (ни одного abort).

## Исполнение (конвенция проекта)
Каждая задача: ревью спека (`reviewer`, MODE: plan) → независимый `tester` в worktree на коммите до правки → реализация → инъекции ведущего против обоих наборов тестов с предсказаниями → стенд, где применимо → `reviewer` синхронно. Тестер один раз на механизм. Слияние — только ведущий, формат `merge: суть` + Why/Layer/Refs.

## Открыто до старта
- DESIGN §6 (барьер не прогнан через `cancel()`/`Handle.close()`; гонка стока; E5b; `os._exit`; проверка Qt-предка; оценки `EXIT_MARGIN`/`INFRA_RESERVE`; числа 85/39 — пересчёт в 0.5).
- Ленивые импорты `process_module/__init__.py:118-126` в `process_manager_module` — в `OPEN_QUESTIONS.md`, вне плана.
