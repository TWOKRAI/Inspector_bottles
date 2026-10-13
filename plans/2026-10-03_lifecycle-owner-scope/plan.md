# lifecycle-owner-scope — один владелец для всего, что нужно закрыть

- **Slug:** `lifecycle-owner-scope` · **Ветка:** `feat/lifecycle-owner-scope` (worktree `.claude/worktrees/lifecycle`) · **Дата:** 2026-10-03
- **Статус:** ЗАКРЫТ 2026-10-13 на достигнутом (решение владельца): Ф0 (0.1–0.5), T1, Ф1 до 1.2b включительно DONE; 1.3–1.5, Ф2–Ф6 — FREEZE, не KILL (код, тесты и стражи остаются; причины и потребители — таблица «Заморожено»). Хвосты 1.2b Т-1…Т-4 — в очереди координатора. История: «Перестройка 2026-10-05».
- **Слой:** framework (`base_manager`, `event_module`, `process_module`, `process_manager_module`, `worker_module`, `frontend_module`, `registers_module`, `router_module`, `state_store_module`, `channel_routing_module`, `config_module`, `actions_module`, `service_module`, `shared_resources_module`), Services, Plugins, прототип (frontend), `backend_ctl`
- **Основание:** решение владельца 2026-10-03 («переделать так, чтобы подобных проблем не было»; «универсальный механизм у всех»; «каждый модуль отвечает за свой функционал, без дублирования, через интерфейсы, без костылей»). Триггер — аварийное завершение `run_framework_tests` ~1 из 4 (Task 5.5d плана `transport-single-policy`).
- **Архитектура и доказательства:** [`DESIGN.md`](DESIGN.md). Диаграммы для чтения: [`docs/diagrams/lifecycle/lifecycle-system.html`](../../docs/diagrams/lifecycle/lifecycle-system.html).

## Перестройка 2026-10-05 — вердикт CTO и решение о GUI

**Почему.** Расследование 2026-10-05 (investigator 5/5, агент-репродуктор с нативными стеками, вердикт CTO с прогонами)
показало: abort гейта — **Python-владеемые Qt-объекты в циклах ссылок, которые сборщик мусора разрушает на НЕ-главном
потоке** (автосборка срабатывает на любом аллоцирующем потоке: роутер, логгер, `QRunnable`). Нативные стеки:
`QWidget::~QWidget → deleteChildren → мусорный указатель` (рабочий поток) и `~QObject → _purecall → abort` под
`Shiboken::BindingManager::runDeletionInMainThread` (главный). Политика «gc выключен + сборка по таймеру на главном +
доставка DeferredDelete»: 5/5 abort → **0/5**. Вердикт CTO: **BLOCK** посылки «Ф5 (миграция GUI-корней) закрывает
abort» — abort закрывает политика памяти GUI-процесса, а не миграция. Отчёты: `docs/reviews/2026-10-05_task-0.{2,3,4}-*`,
артефакты прогонов — в scratchpad сессии aab3cfb2 (`cto_probe/`, `logs/*.native`).

**GUI будет переделан** (решение владельца: GUI — отдельный сервис и конструктор на PyQt; черновики `gui-service`,
`gui-constructor`, `frontend-constructor` сведутся в один мегаплан). Поэтому всё, что чинит **нынешний** GUI-код
(источники утечек во вкладках, Ф2, Ф5), откладывается в мегаплан как требования, а не делается сейчас.

**Что остаётся в этом плане — одна задача:**

- **Task T1 — политика памяти GUI-процесса** [DONE 2026-10-07 — 4c82e0167; приёмка CTO ACCEPTED WITH CONDITIONS,
  [`docs/reviews/2026-10-07_task-T1-cto-acceptance.md`](../../docs/reviews/2026-10-07_task-T1-cto-acceptance.md); merge — по слову владельца]
  (teamlead; облегчённый конвейер: одно ревью спека, слепой тестер,
  инъекции, одно ревью кода; CTO — на приёмке). Расширить `process_module/lifecycle/gc_discipline.py` исполнителем
  сборки (`collect_on`) — один механизм, без второго; тонкий Qt-адаптер в `frontend_module` (тик `QTimer` на главном:
  `gc.collect` + `flush_deferred_deletes` при `loopLevel()==0`); включение — одной функцией в корне композиции GUI;
  наблюдаемость (нарушения `gc.isenabled()`, длительность сборки; ноль цены выключенной); страж на
  `gc.collect`/`gc.enable` в GUI-коде и тестах (сейчас 4 теста ломают политику); сессионная фикстура в
  `modules/conftest.py` вызывает ту же функцию; гейт — `offscreen`, как CI.
  **Приёмка числами:** цепочка `test_base_tree_nav_tab → test_qt_event_bridge → gc в потоке` 0/20 native и offscreen;
  `frontend_module` + `event_module` в обратном порядке 0/5; полный гейт 0/5 native; нарушений gc 0;
  `test_concurrent_attach_from_four_threads` 0/20. После T1 ветка вливается в `main` (по слову владельца) —
  примитивы 0.1–0.4 становятся доступны, их тесты больше не будят механизм.

**Заморожено (FREEZE, не KILL — код и тесты остаются, задачи ждут потребителя):**

| Что | Статус | Куда и когда |
|---|---|---|
| 0.1–0.3 `Scope`/`Handle`, `Subscribers`, канал `emits_after_close` | DONE, заморожены до потребителя | лечат ханг останова и утечки подписок, не abort; потребитель — Ф1 или мегаплан GUI |
| 0.4 `qt_lifetime` | DONE, используется | правило «Qt-объект умирает на своём потоке» — вход мегаплана GUI |
| 0.5 стражи | ВОЗОБНОВЛЕНА 2026-10-11 по слову владельца (очередь п.2): G2, G3, G4, G6, G10 и проба abort сделаны (0.5a, 0.5b); G5 вынесен — в мегаплан GUI | счётчик Qt-мусора на тест (храповик) — в мегаплан GUI; под T1 `SAVEALL`-колбэк делает мусор бессмертным (урок `feedback_gc_saveall_census_under_a_freezing_boundary_keeps_garbage_forever.md`) |
| Ф1 останов процесса | DONE до 1.2b включительно (1.1, 1.2a, 1.2b-1, 1.2b-2, 1.2b-ki `427c3cba0`, 1.2b-3 `4bd81f468`); 1.3–1.5 — FREEZE (строка ниже) | 5-с ханг: 0/30 до и после 1.2a (`reports/1.2.stand.md`); хвосты 1.2b — в очереди координатора |
| Ф2, Ф5 | FREEZE, не KILL — решение владельца 2026-10-13: требования уходят в [мегаплан GUI](../2026-09-22_gui-service/plan.md); abort закрыт T1 (`4c82e0167`, в main с 2026-10-07; 2026-10-13 — 3 полных прогона без abort), вердикт CTO 2026-10-05 «Ф5 закрывает abort» отвергнут, нынешний GUI будет заменён | требования 2.1, 2.2, 5.1–5.3 и гейт abort (in-suite проба 3×, G5 ноль по frontend) — вход мегаплана GUI; возврат — по потребителю |
| 1.3, 1.4, 1.5, Ф3, Ф4, Ф6 | FREEZE — решение владельца 2026-10-12 (очередь `14b610faf`) | ханг 0/30 до и после 1.2a (`reports/1.2.stand.md`); возврат — по потребителю |

**Требование к мегаплану GUI (сценарий «панель — отдельное устройство»):** одна архитектура, два развёртывания.
GUI — всегда клиент бэкенда по протоколу «dict на границе» через подключаемый транспорт (`gui-service`: клиент вне
дерева, `SocketChannel`, N бэкендов): локально — тот же клиент, запущенный рядом (лаунчер может стартовать его для
удобства), удалённо — тот же клиент на панели по Ethernet. Бэкенд headless всегда (принцип 6 владельца). Видео — отдельный
транспорт кадров (локально разделяемая память, по сети — поток вроде `mjpeg_sink`). Политика памяти GUI-процесса (T1)
нужна клиенту в обоих развёртываниях.

### Решение владельца 2026-10-06 — T1 фундамент, лечение в мегаплане GUI (черновик требований)

T1 — страховочная сетка и счётчики (один владелец сборки, исполнитель-протокол, Qt-адаптер, граница теста, страж).
Корень abort — **владение Qt-объектами между потоками**, а не сборщик; T1 закрывает самый частый путь (автосборка на
чужом потоке), остальные пути остаются. Мегаплан GUI **начинается** с инварианта, который держится устройством кода:

1. **`QObject` рождается и умирает только на главном потоке.** Рабочие потоки не держат ссылок на Qt-объекты — только
   данные (dict, numpy, сообщения). Страж: тест/AST-проверка, что воркеры не получают `QObject`; храповик Qt-мусора.
2. **Между потоками — только сообщения.** Воркер отдаёт результат сигналом/очередью; создаёт и удаляет Qt-объекты только
   GUI. Доведённый до конца принцип «GUI — сервис-клиент по транспорту»: GUI-процесс — однопоточный потребитель сообщений.
3. **Время жизни — через scope-владельца, без циклов.** Дерево `QObject` с родителем; presenter не держит view сильной
   ссылкой; без лямбд на `destroyed`; `QTimer` с родителем; `QObject` не создаётся в `QRunnable` (см. строку Ф2/Ф5 выше).
4. **Сторож, а не надежда.** Храповик Qt-мусора на тест (`DEBUG_SAVEALL`, база — `foreign_collections`/счётчики T1).

Остаточные пути к той же болезни после T1 (вход для мегаплана, не задачи T1): явный `gc.collect()` на рабочем потоке
GUI-процесса (виден как `foreign_collections`, в `chain` = 1); последняя ссылка на `QObject`, отпущенная на рабочем
потоке (refcount, не gc); сторонние библиотеки с `gc.*` (R1 их не видит); окно heartbeat до `install` в проде.
Политика T1 после мегаплана остаётся сеткой под правильной архитектурой, а не единственной защитой.

### Итог приёмки T1 (2026-10-07)

**Хвост (2026-10-07): хелпер фикстуры заменён изоляцией** — тесты механизма gc идут в своём интерпретаторе, страж R4
([`task-T1-gc-isolation.md`](task-T1-gc-isolation.md)); CI Linux на `main` был красен из-за хелпера и клона без истории.
Полный гейт native на слитом дереве `d59772337`: **11521 passed, 0 failed, 0 abort**, нарушений gc 0, пауза границы ≤ 89 мс (первый тест сессии), остальные ≤ 33 мс (было до 282 мс — причина и правка фикстуры `0d6d031e5`+`70ba0e2f5`). Контроль скорости D3 0.88–1.03×; soak 1 ч: утечки в GUI нет. Все числа, причина пауз и список «не перемерено» — [`docs/reviews/2026-10-07_task-T1-acceptance-numbers.md`](../../docs/reviews/2026-10-07_task-T1-acceptance-numbers.md).

## Зачем — одной фразой

У подписок, потоков, процессов, окон и виджетов нет владельца, который их закроет; они доживают до случайного момента
и умирают в неправильном месте — отсюда abort тестов фреймворка, 5-секундный ханг останова, утечки GUI и ложный
«остановлен». План вводит одну область-владельца (`IScope`) и переводит на неё всё, что сегодня закрывается по-своему.

## Соседи — кто чем владеет

| План | Что там про это | Что берём | Что отдаём | Граница |
|---|---|---|---|---|
| [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md) (IN PROGRESS, Ф1 DONE) | PM владеет остановкой, `system_stop_event`, ReaderGoneQueue (ADR-SRM-015/016), сироты, ADR-PMM-031 «одно число на оба уровня»; Task 3.1 «остановка как протокол» условная | семантику эскалации `_stop_many` и метки ReaderGone — в `ChildProcessStop` (П1); формулу бюджета — в один `stop_budget.py` (П2) | внутрипроцессную половину Task 3.1 (именованные фазы = сегменты, П3); удаление хука `_before_observability_teardown` | их Task 3.1 сужается до межпроцессного quiesce → ack; `ProcessTreeGuard` и досъём `harness.py` остаются у них (П4). Их план поправлен 2026-10-03 (раньше Ф1, чтобы не было двух задач на одну работу): 3.1 сужена, хук и долги «до старта 3.1» (ADR-PM-054 → ADR-PMM-033, п.4 ADR-PMM-033) — в нашу Task 1.2; их Ф2 ⛔ наша Ф1 |
| [`transport-single-policy`](../transport-single-policy.md) | Task 5.5d (ветка `fix/t55d-qt-gc`) — «сборка Qt-мусора в тестах» | полезное из 5.5d: страж утечки потоков `batch-drain-*`, `unwire` в writethrough-тесте, `close` в тесте 3.3 — в Ф1 | 5.5d становится SUPERSEDED этим планом (abort закрывает Ф5) | ветка `fix/t55d-qt-gc` не вливается |
| [`observability-closure`](../observability-closure/plan.md) (Ф4 в работе) | Ф4 правит `observability_wiring.py` (4.1, 4.3, 4.3b, 4.14) и `process_manager_process.py` | — | ручки tap'ов и форвардеров (Ф3) | Ф3 этого плана стартует после их задач по `observability_wiring.py` или они принимают ручки в своих задачах — сверка на входе Ф3 |
| [`otel-export`](../otel-export.md) | Task 2.4 «otel flush» до снятия форвардеров | — | та же гарантия барьером (`work` закрывается до `transport`/`planes`) | единственная обёртка совместимости (G10) — `Plugins/io/otel_export/plugin.py` чужой полосы, удаляется в Ф6 |
| [`2026-09-22_gui-service`](../2026-09-22_gui-service/plan.md) | GUI как клиент (Remote*Proxy) | — | механизм владения для клиента | продолжает после Ф5 этого плана на его механизме |
| [`framework-architecture-rework`](../framework-architecture-rework/plan.md) (DRAFT) | окно codemod (Р-9) | — | — | файлов не переносим; при открытии окна codemod — сверить порядок |

## Порядок выполнения

- Task 0.1: ADR и интерфейсы владения в base_manager [DONE 2026-10-04 — dad6ef9c9]
- Task 0.2: Scope и Handle — примитив и контракт-тесты G1 [DONE 2026-10-05 — dbd0d7b23] (после 0.1)
- Task 0.3: Subscribers в event_module [DONE 2026-10-05 — a3fddf721] (после 0.2)
- Task 0.4: qt_lifetime — attach_qt, flush_deferred_deletes, QThreadHandle [DONE 2026-10-05 — 41fc28c29] (после 0.2)
- Task 0.5: стражи G2–G6, G10 и база in-suite пробы abort [DONE 2026-10-11 — 0.5a, 0.5b, слияние 5d13d6bc3; G5 вынесен] (после 0.3, 0.4)
- Task 1.1: stop_budget и ChildProcessStop поверх эскалации PM [DONE 2026-10-12 — 92972804f, слияние 47cf7c272] (после 0.5)
- Task 1.2: разделена лидом 2026-10-12 на 1.2a и 1.2b по замеру брифа (1.2a ≈ 20 файлов; 1.2b ≈ 52 файла однотипной правки: 47 подклассов `BaseManager`, свой `shutdown()` у 33) — `tasks/1.2a.md`, `tasks/1.2b.inventory.md` [SUPERSEDED 2026-10-12 — разделена на 1.2a и 1.2b]
- Task 1.2a: корень процесса planes | transport | work с барьерами, `stop()` = `cancel()`, один close в раннере, `os._exit` при выживших, G7, удаление хука `_before_observability_teardown`, долги stop-ownership, читатель `stop_budget` [DONE 2026-10-12 — a4fcae8b6, исправление 1.1 b8b961afc; слияние в main — коммит «merge: lifecycle-owner-scope 1.2a»; стенд 30+30: медиана 2,03 → 1,76 с, ханг 0/30 до и после; tasks/1.2a.result.md] (после 1.1)
- Task 1.2b: `BaseManager.scope` + шаблонный `shutdown()` — кодмод подклассов по слоям [DONE — 1.2b-1 DONE 2026-10-12 (`a0354d823`, `5e65823fa`; `tasks/1.2b-1.result.md`); 1.2b-2 DONE 2026-10-13 (`005df1350`; `tasks/1.2b-2.result.md`, `reports/1.2b-2.full-run.md`); 1.2b-ki DONE 2026-10-13 (`tasks/1.2b-ki.result.md`, `reports/1.2b-ki.injections-run.md`); 1.2b-3 DONE 2026-10-13 (`tasks/1.2b-3.result.md`, `reports/1.2b-3.injections-run.md`, `reports/1.2b-3.full-run.md`)] (после 1.2a)
  - Хвосты 1.2b (2026-10-13; задачи без брифа, после решения владельца по Ф2/Ф5; подробности — `docs/claude/OPEN_QUESTIONS.md`, разделы 1.2b-ki и 1.2b-3):
    - [ ] Т-1: повторная инициализация по решению владельца (ADR-BM-009 «Повторная инициализация») — сброс записи жизни в цикле `initialize()` → `shutdown()`, повторная привязка области, hazard-тест на гонку со ждущим; не тривиально.
    - [ ] Т-2: G-28 по эффекту тела (`DeviceManager._save` и отключение драйверов, останов потока `AuditWriter`) — тесты.
    - [ ] Т-3: Post `IBaseManager.shutdown` о `BaseException` (тело и `scope.close()`).
    - [ ] Т-4: живой поток `Scope` после `KeyboardInterrupt` в записи не попадает в `survivors` (`lifetime.py`) — механизм, нужен бриф.
    - [x] Т-5: документы — примеры `ProcessModule` с `super()._on_shutdown()`, заголовок ADR-BM-009 без «мягкий режим», счётчик STATUS (ветка `docs/lifecycle-1.2b-tails`).
- Task 1.3: WorkerManager и PluginContext на области, G8 [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 1.2b)
- Task 1.4: наблюдаемость процесса как ручки сегмента planes, перенос полезного из 5.5d [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 1.2a)
- Task 1.5: стенд и приёмка Ф1 [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 1.3, 1.4)
- Task 2.1: регистры GUI на Subscribers с owner [DEFERRED 2026-10-13 — FREEZE, решение владельца: требования в мегаплан GUI] (после 1.2b)
- Task 2.2: презентеры и Python-owned QObject компонентов на attach_qt, G5 fail в components [DEFERRED 2026-10-13 — FREEZE, решение владельца: требования в мегаплан GUI] (после 2.1)
- Task 5.1: вкладки, формы, окна, bindings, ThreadManager на области [DEFERRED 2026-10-13 — FREEZE, решение владельца: требования в мегаплан GUI] (после 2.2)
- Task 5.2: корень GUI и рестарт UI, слушатели моста [DEFERRED 2026-10-13 — FREEZE, решение владельца: требования в мегаплан GUI] (после 5.1)
- Task 5.3: гейт abort — in-suite проба 3 раза и G5 ноль по frontend [DEFERRED 2026-10-13 — FREEZE, решение владельца: требования в мегаплан GUI] (после 5.2)
- Task 3.1: EventBus, ActionBus, события SRM на Subscribers [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 5.3)
- Task 3.2: StateProxy и Config с owner [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 3.1)
- Task 3.3: роутер — ручки обработчиков и push-слушателей [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 3.1)
- Task 3.4: tap'ы и проводка наблюдаемости на ручках [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 3.1)
- Task 3.5: backend_ctl — списки подписчиков на Subscribers [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 3.1)
- Task 4.1: инфраструктурные потоки фреймворка на spawn [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 3.4)
- Task 4.2: Services на spawn, ServiceHost — область на сервис [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 4.1)
- Task 4.3: Plugins на spawn, адаптер пулов [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 4.1)
- Task 4.4: backend_ctl — потоки и таймеры на spawn [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 4.1)
- Task 6.1: удалить обёртки совместимости, все стражи в fail, документы, приёмка CTO [DEFERRED 2026-10-12 — FREEZE, очередь владельца `14b610faf`] (после 4.2, 4.3, 4.4, 3.2, 3.3, 3.5)

## Ф0 — механизм и стражи (без миграции потребителей)

### Task 0.1 — ADR и интерфейсы владения в base_manager
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** в `base_manager/interfaces.py` живут `Stoppable`, `CloseReport`, `Reporter`, `IHandle`, `IScope`, `ScopeClosedError`; ADR фиксирует решения DESIGN §4.
**Files:** `multiprocess_framework/modules/base_manager/interfaces.py`, `base_manager/DECISIONS.md` (новый ADR-BM-xxx), `multiprocess_framework/DECISIONS.md` (индекс через `python -m scripts.sync`), `base_manager/README.md`, `STATUS.md`, `base_manager/docs/INTERFACES_USAGE.md`. Полный спек — [`task-0.1.md`](task-0.1.md).
**Acceptance:**
- [ ] Протоколы и DTO — как в DESIGN §2.1 ред. 3.1 (имена, сигнатуры, keyword-only); уточнения (property, `from_dict`, семантика, тексты ошибок) — [`task-0.1.md`](task-0.1.md).
- [ ] `CloseReport.to_dict()` — только примитивы (Dict at Boundary); `Scope`/`Handle` не пиклятся (проверяется в 0.2).
- [ ] ADR перечисляет отвергнутое с причиной: отдельный `lifetime_module`, WeakMethod, три корня процесса, передача close владельцу-потоку, shim-список.
- [ ] `python scripts/validate.py` зелёный (sync разделов DECISIONS).
**Out of scope:** реализация `Scope` (0.2), миграция потребителей.

### Task 0.2 — Scope и Handle: примитив и контракт-тесты G1
**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework
**Goal:** `base_manager/core/lifetime.py` (только stdlib) реализует `IScope`/`IHandle` с барьерами, тремя фазами, отчётом, `unclosed_roots()`.
**Files:** `base_manager/core/lifetime.py`, `base_manager/__init__.py` (фабрика `open_scope` + `unclosed_roots`, класс `Scope` не экспортируется — решение CTO 2026-10-04, [`task-0.1.md`](task-0.1.md) «Дверь»), `base_manager/tests/test_lifetime_*.py`, `interfaces.py` (три правки DTO из код-ревью 0.1). Полный спек — [`task-0.2.md`](task-0.2.md). `BaseManager.scope` + шаблонный `shutdown()` перенесены в Task 1.2 (корня процесса до 1.2 нет; шаблон меняет 30 подклассов — миграция).
**Acceptance (G1, литералами):**
- [x] (a) цикл «презентер ↔ издатель» освобождается refcount'ом после `close()` — `gc.disable()`, `unreachable == 0`.
- [x] (b) поток игнорирует стоп 3 с при бюджете 1 с: `close()` возвращается за ≤ 1.2 с, `survivors` содержит путь, `live()` показывает `survivor`.
- [x] (c) `own`/`spawn` после закрытия: ресурс освобождён сразу, `ScopeClosedError`; перезапуск во время close отклонён.
- [x] (d) close изнутри рассылки: доставка прекращается на закрывшем; close из освобождения фазы 2 — `complete=False`, внешний `complete=True`.
- [x] (e) второй close из чужого потока ждёт первого и получает тот же отчёт; (f) поток закрывает свою область без дедлока, в отчёте `self`, не «остановлен» (совет 8).
- [x] Барьер: сегмент ниже барьера получает фазу 1 только после закрытия сегмента выше; сток, дренирующий при `request_stop`, доставляет N/N.
- [x] `kill()` фазы 3: упрямый ресурс в `killed`, не в `survivors`.
- [x] `Handle.close()` идёт тем же путём, что и область (одноэлементный сегмент), отцепление не оставляет цикла.
- [x] `unclosed_roots()` видит брошенный незакрытый корень после gc (recorder держит только weakref на флаг — совет 9) и не красит закрытый.
- [x] `pickle.dumps(scope)` / `(handle)` → `TypeError` с понятным текстом.
- [x] Инъекции ведущего (предсказание до прогона; полный список — `task-0.2.md`): без проверки `active` → (d) красный — **перенесено в 0.3** (флаг `active` — деталь `Subscribers`); без проверки состояния в `own` → (c) красный; без барьера → тест стока красный.
**Итог (2026-10-05):** код-ревью р1 — 3 major (F1–F3), р2 — 1 major в правке F2; все закрыты (`324ad1170`, `bf7b27d6e`, `dbd0d7b23`); `base_manager` 559 passed / 2 skipped; инъекции ведущего 7/7 по предсказанию — [`docs/reviews/2026-10-05_task-0.2-fix-injections.md`](../../docs/reviews/2026-10-05_task-0.2-fix-injections.md).
**Out of scope:** Subscribers (0.3), Qt (0.4).

### Task 0.3 — Subscribers в event_module
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** один список подписчиков для всех издателей: `add(cb, *, owner: IScope) -> IHandle`, `emit` по снимку вне лока, `errors`, `emits_after_close` в отчёт владельца.
**Files:** `event_module/subscribers.py`, `event_module/interfaces.py`, `event_module/tests/`, README/STATUS, `multiprocess_framework/docs/MODULE_TIERS.md` (строка `event_module`: leaf → зависит от `base_manager.interfaces`; перенесено из 0.1 — зависимость появляется здесь).
**Acceptance:** реентрантная отписка во время `emit`; исключение подписчика изолировано и посчитано; доставка в закрытого владельца не происходит и посчитана; ручка держит издателя слабо (короткоживущий издатель не удерживается); `EventBus` пока не мигрирует (Ф3).
**Итог (2026-10-05):** спек ред. 3 (ревью р1–р2, исправление «A»), слепой тестер 26 тестов, ревью кода р1–р2 + вердикт CTO (b) `CloseReport.kind`; `event_module`+`base_manager` 610 passed / 2 skipped; инъекции ведущего 17/17 — [`docs/reviews/2026-10-05_task-0.3-injections.md`](../../docs/reviews/2026-10-05_task-0.3-injections.md).

### Task 0.4 — qt_lifetime
**Level:** Senior · **Assignee:** teamlead · **Layer:** framework
**Goal:** `frontend_module/core/qt_lifetime.py`: `attach_qt`, `flush_deferred_deletes`, `QThreadHandle` (DESIGN §2.4).
**Acceptance:** закрытие области с Qt-объектом из чужого потока → `destroyed` на главном, `ownedByPython == False`, обёртка мертва после flush; без цикла событий и после `exec()` — то же после `flush_deferred_deletes()`; обработчик `destroyed` не держит объект (обёртка не бессмертна — проба CTO `cto_l6_probe2`); проверка Qt-предка при освобождении пишет `qt-tree mismatch` в `errors`.
**Итог (2026-10-05):** спек ред. 3 (ревью р1–р2, вердикт CTO — правило C без якоря), слепой тестер 10 тестов, код-ревью р1 (3 находки: abort QThread, gc под локом, flush в цикле) и р2 APPROVED; `frontend_module` 684 passed / 1 skipped; инъекции ведущего 16/16 — [`docs/reviews/2026-10-05_task-0.4-injections.md`](../../docs/reviews/2026-10-05_task-0.4-injections.md).

### Task 0.5 — стражи и база пробы
**Level:** Middle+ · **Assignee:** developer · **Layer:** tests/scripts
**Goal:** G2 (сигнатуры, литеральный список издателей из DESIGN §2.6), G3/G4/G5 в режиме отчёта, G6 AST в `scripts/validate.py` с allowlist причин (fail), G10 (счётчик = 1); in-suite проба abort (`crashprobe offmain_gc`) в репозитории как приёмочная, база записана числом (сегодня crash 3/3).
**Acceptance:** каждый страж краснеет на своей инъекции из DESIGN §3; режим отчёта не меняет код возврата гейта, но печатает список.
**Итог (2026-10-11):** задача поделена по ревью спека (р.1–р.2): [`0.5a`](tasks/0.5a.md) — G2, G6, G10 в `validate.py` (52 издателя, 71 запись allowlist; итог [`0.5a.result.md`](tasks/0.5a.result.md)), [`0.5b`](tasks/0.5b.md) — плагин G3/G4 и проба abort с живой осью (итог [`0.5b.result.md`](tasks/0.5b.result.md)). G5 не реализован: под политикой T1 колбэк `DEBUG_SAVEALL` держит циклы вечно. «Сегодня crash 3/3» не воспроизводится: проба на наборе 3 из 3 survived (с T1 — 0 обёрток; без conftest — 4853 собранных объекта и тоже нет падения); живая ось — `python -m scripts.lifecycle_guards.probe axis` (`thread` падает 3 из 3, `main` выживает 3 из 3). Отчёты ревью — `reports/0.5.review-r1.md`, `r2.md`, `0.5a.review-code-r1.md`, `0.5b.review-code-r1.md`; инъекции — `tasks/0.5a.injections.json` (22), `tasks/0.5b.injections.json` (18).

## Ф1 — путь останова процесса (закрывает 5-секундный ханг)
Задачи 1.1–1.5 по DESIGN §2.2–2.3 и П1–П3: один `stop_budget.py` (пять чисел, четыре места чтения `"shutdown_timeout"` мигрируют), `ChildProcessStop` с меткой ReaderGone, корень процесса `planes | transport | work` с барьерами, `stop()` = `cancel()`, один `close()` в раннере, `os._exit` при выживших, golden G7 (включая два инварианта приёмки stop-ownership 09-26), `BaseManager.scope` + шаблонный `shutdown()` (из 0.2), WorkerManager с перезапуском в том же потоке и STOPPED по отчёту, `PluginContext.scope` (камера и воркер в одной области), G8 < 1.5 с; ручной порядок `app_module/orchestrator.py:85` и `state_store_manager.py:134` — регистрацией в области. Task 1.2 закрывает долги stop-ownership «до старта Task 3.1»: указатель ADR-PM-054 → ADR-PMM-033 и формулировку п.4 ADR-PMM-033. Детализация спеков — на входе фазы, ревью спека до тестера.

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
