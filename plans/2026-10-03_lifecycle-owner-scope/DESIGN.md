# lifecycle-owner-scope — архитектура (ред. 3.1)

**Дата:** 2026-10-03 · **Статус:** принята CTO с условиями — раунд 2: ACCEPT WITH CONDITIONS ★1,3,4,5,6; раунд 3
(соседство с `lifecycle-stop-ownership`, наблюдаемость, аудит модулей): ACCEPT WITH CONDITIONS П1–П4. Все условия
вписаны ниже. **Ред. 3.1 (2026-10-04)** — поправки CTO по эскалации ревью спека Task 0.1: Q1 `join` →
`join_until`, Q2 корень через фабрику `open_scope`, Q3 сроки (`kill_reserve_s` у `child`, `min` для срока ребёнка,
резерв сверху, `kill()` не блокирует). Полный текст — [`task-0.1.md`](task-0.1.md).
**Путь решения:** три отчёта investigator'ов → черновик лида → CTO р1 (ACCEPT WITH CONDITIONS) → ревьюер ред. 1 (своя
архитектура, прототип) → ревьюер ред. 2 (по вердикту CTO) + раздел «Ответственность и интерфейсы» → CTO р2 (оценки
ред. 1 / ред. 2, условия) → эта ред. 3 (лид, ред. 2 + условия CTO). Третий раунд ревьюера не проводился: лимит
итераций (2) исчерпан; спек каждой задачи проходит ревьюера по тексту до кода.
Материалы дискуссии (вне репозитория, scratchpad сессии 2026-10-03): `report_*.md`, `DESIGN_draft.md`,
`cto_verdict_r1.md`, `reviewer_r1.md`, `reviewer_r2.md`, `reviewer_r2_sec6.md`, `cto_verdict_r2.md`, прототипы `rv/`.
Ключевые выводы перенесены сюда; прототипы — не код, а доказательство формы.

## 1. Зачем

Решение владельца 2026-10-03: «переделать так, чтобы подобных проблем не было»; «должен быть универсальный механизм у
всех» — подписки, потоки, процессы, окна, виджеты; «каждый модуль отвечает за свой функционал, без дублирования, всё
связано через интерфейсы, без костылей».

Факты (воспроизведены прогоном, дерево `9e9cec47c`):

| Дефект | Доказательство |
|---|---|
| Подписка GUI на регистр неснимаема | `SyncTrait` без `unsubscribe` (3 презентера, 3/0); `RegisterAdapter.unsubscribe` ищет по `id(callback)` — с bound method не находит (repro C: subscribers = 1 после отписки) |
| Кольцо presenter ↔ RegistersManager ↔ view | refcount не освобождает, только gc (42–46 unreachable); при живом менеджере — callback в мёртвый view, `set_field_value` отвечает успехом |
| Abort `run_framework_tests` ~1/4 | живой Python-owned Qt-объект в цикле + gc на неглавном потоке; in-suite 3/3 (access violation в `gc.collect()` на рабочем потоке; abort на главном); синтетика 0/9 — триггер локализован только in-suite. Перепись мусора в точке abort — вкладки (`test_base_tree_nav_tab`: QWidget 22, QLabel 21, CurrentPageStack 12 …), не презентеры |
| Ложный «остановлен», воскрешение | `stop_all_workers` пишет STOPPED живому потоку (1.00 с, alive=True); упавший при стопе воркер перезапускается со свежим невзведённым stop_event |
| 5-с ханг останова ребёнка | `stop_all_workers` до трёх раз по 5 с; камера (`orchestrator.shutdown`) отпускается после join; ребёнок не читает `shutdown_timeout`, который ему передают |
| Нет владельца | 12 механизмов подписки (ручки у 6, четыре формы), 39 мест создания потоков, 18 `join(N)` литералами, 31 Presenter — уборка у 3 под тремя именами; обработчик роутера снять нельзя (13/0) |
| Порядок останова прозой и с инверсией | `process_lifecycle.py:117-240`; `shared_resources.shutdown()` (:143) раньше `router_manager.shutdown()` (:197) |

## 2. Архитектура

Один примитив владения — **область (scope)**. Любой ресурс, который владелец открыл, — запись в его области. Закрыть
владельца = закрыть все его записи к одному сроку и получить отчёт, кто не закрылся. Примитив без Qt и без
multiprocessing; адаптеры живут у своих модулей.

### 2.1 Интерфейсы — `base_manager/interfaces.py` (единственная точка зависимости)

```python
class Stoppable(Protocol):
    """Ресурс со своим потоком управления: поток, процесс, QThread, пул, блокирующее устройство, сток."""
    def request_stop(self) -> None:
        """Фаза 1. Не блокирует, идемпотентно, любой поток. Прерывает блокирующие вызовы.
        Для стока: закрыть вход; дренирование и выход — его дело до join_until (★5б)."""
    def join_until(self, deadline: float) -> bool:
        """Фаза 2. Ждать до абсолютного time.monotonic(). True = остановлен. На таймауте не бросает.
        Не `join`: у Thread/Process/QThread join(timeout) относительный и без результата (Q1, ред. 3.1)."""
    # необязательно: kill() -> None — фаза 3, только после join_until()==False. НЕ блокирует: послать сигнал
    #   и вернуться; ожидание — join_until к сроку резерва (Q3, ред. 3.1)
    # необязательно: close() -> None — освобождение после успешного join_until/kill

Resource = Stoppable | Callable[[], object]          # подписка, сокет, файл, хук плагина — вызываемое

@dataclass(frozen=True)
class CloseReport:                                    # DTO, Dict at Boundary через to_dict()
    path: str
    elapsed_s: float
    survivors: tuple[str, ...]    # живы после срока и kill; поток, закрывающий сам себя, — с пометкой self (совет 8)
    killed: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    emits_after_close: int = 0    # ★5а: доставки в закрытого владельца
    complete: bool = True         # False — ответ реентрантного вызова во время закрытия
    @property
    def ok(self) -> bool: ...
    def to_dict(self) -> dict: ...

Reporter = Callable[[CloseReport], None]

class IHandle(Protocol):
    path: str
    kind: str
    def close(self, budget_s: float | None = None) -> CloseReport:
        """Досрочно освободить одну запись: отцепить от владельца, затем закрыть тем же кодом, что и область
        (одноэлементный сегмент, совет 7). Идемпотентно."""

class IScope(Protocol):
    path: str
    closed: bool
    parent: "IScope | None"                        # только чтение
    def own(self, res: Resource, *, name: str, kind: str = "resource") -> IHandle:
        """После закрытия: освободить res СРАЗУ и бросить ScopeClosedError."""
    def child(self, name: str, *, budget_s: float | None = None,
              kill_reserve_s: float | None = None) -> "IScope": ...   # None = значение родителя
    def barrier(self) -> None:
        """★1. Граница сегментов: всё, зарегистрированное ДО барьера, получает фазу 1 только после того,
        как закрыто всё, зарегистрированное ПОСЛЕ него."""
    def spawn(self, target: Callable[[threading.Event], None], *, name: str) -> IHandle:
        """Поток '<path>/<name>'. В закрытой области не стартует и бросает. Публичен для всех слоёв (★4)."""
    def cancel(self) -> None:
        """Фаза 1 по поддереву верхнего сегмента. Не блокирует, любой поток, идемпотентно."""
    def close(self, budget_s: float | None = None, *, deadline: float | None = None) -> CloseReport:
        """По сегментам сверху вниз: фаза 1 по поддереву сегмента → фаза 2 LIFO вне лока (ребёнок к сроку
        min(срок родителя, now + child.budget_s)) → фаза 3 kill() владельцем записи в СВОЁМ kill_reserve_s, сверх
        срока, родитель резерв не обрезает → следующий сегмент. Срок: deadline | now+budget_s | now+self.budget_s;
        заданы оба → ValueError. Выживший — в reporter сразу.
        Ошибки собираются, close не бросает. Повтор: закрыта → тот же отчёт; этот же поток или её spawn-поток →
        complete=False; чужой поток → ждёт первого закрывающего до своего срока."""
    def live(self) -> list[dict]: ...
```

### 2.2 Владельцы — ровно один на обязанность

| Обязанность | Владелец (реализация) | Интерфейс для остальных | Что удаляется как дубль |
|---|---|---|---|
| Примитив области | `base_manager/core/lifetime.py`: `Scope`, `Handle`, `unclosed_roots()` (только stdlib) | `IScope`, `IHandle`, `Stoppable`, `CloseReport`, `Reporter` | поля `thread`/`stop_event` в `WorkerRegistry`; реестр `ThreadManager`; `BindingHandle`; пары `wire_/unwire_`; `close_all_taps`; `weakref.finalize` в `store_tap.py:293` |
| Список подписчиков | `event_module/subscribers.py`: `Subscribers` (★3); `EventBus` — типизированная обёртка над ним | издатель отдаёт свой `subscribe(..., *, owner: IScope) -> IHandle` в своём `interfaces.py`; `Subscribers` — деталь издателя | 12 самописных списков; `RegisterAdapter._subscriptions` по `id()`; корзины `EventBus`; Protocol `Subscription` (`event_module/interfaces.py:23`) |
| Потоки | `IScope.spawn` (★4: публичен всем); воркер с политикой — `IWorkerManager.create_worker(..., owner=)` | — | сырой `threading.Thread(` (39 мест); `_restart_worker_internal`; `ThreadManager.terminate()` |
| Эскалация останова процесса | `ChildProcessStop` (Stoppable) в `process_manager_module` — внутрипроцессная форма существующих фаз `_stop_many` (`process_registry.py:413-490`; семантика — план `lifecycle-stop-ownership`, ADR-SRM-016, ADR-PMM-031). П1: `request_stop` = сигнал стопа; `join_until` = ожидание к общему сроку; `kill()` = terminate → `TERMINATE_GRACE_S` → kill (**ред. 3.1: `kill()` обязан не блокировать — форма неблокирующей эскалации terminate→kill решается в спеке Task 1.1**); `kill_reserve_s` области детей = `TERMINATE_GRACE_S + KILL_CONFIRM_S`; `close()` = `_mark_confirmed_dead` (метка ReaderGone, Task 1.2 stop-ownership). Имя `ProcessHandle` занято (`shared_resources_module/handles/process_handle.py:147`, доступ к ресурсам процесса, 12 ссылок) | `children.close()`; `ProcessRegistry` — клиент | цепочка terminate→kill и метка существуют один раз |
| Связь с Qt | `frontend_module/core/qt_lifetime.py`: `attach_qt`, `flush_deferred_deletes`, `QThreadHandle` | `frontend_module/interfaces.py` | автоотвязка `bindings.py:266` (утечка: замыкание держит виджет); отписка в `closeEvent` `BaseConfigurableWidget`; три имени уборки presenter; `QTimer()` без родителя (`debounce_trait.py:19`, 8 мест) |
| Бюджет останова | `process_manager_module/.../stop_budget.py` (П2): одна функция `stop_budget(shutdown_timeout)` и пять чисел — `work`, `infra`, `pm_graceful`, `pm_total`, `outer`; spawner и PM импортируют её; константы `process_registry.py:21-25` переезжают туда. Продолжение «одно число на оба уровня» ADR-PMM-031 на уровень ребёнка | ребёнку словарь в конфиге `{"stop_budget": {...}}` (Dict at Boundary, импорта PM у ребёнка нет) | сегодня ДВЕ копии формулы: `outer_stop_budget` (`spawner.py:27-34`) и `_pm_graceful_budget` (`spawner.py:160-170`); `get_config("shutdown_timeout") or 5.0` (`process_manager_process.py:3529,3667`); чтение `spawner.py:102,165`; `stop_all_workers(timeout=5.0)`; 18 `join(N)`. Эти четыре места чтения `"shutdown_timeout"` мигрируют в Ф1, иначе G6 красный в день 1 |
| Приёмник отчётов | `ProcessLifecycle` — `reporter` корня процесса: живой логгер, после закрытия сегмента логов — `emergency_log` | `IProcessServices.lifetime_snapshot() -> dict` для `introspect.lifetime` | строки «не остановился за …» в `worker_lifecycle.py`, `process_registry.py` → записи отчёта |
| Порядок останова процесса | `ProcessLifecycle`: ОДИН корень с барьерами (★1) | `ProcessModule.stop()` = `root.cancel()` | три пути останова (`stop`, `shutdown`→`orchestrator.shutdown`, `finally` раннера); проза `process_lifecycle.py:117-240` |

### 2.3 Процесс: один корень, три сегмента

```python
root = open_scope(f"proc/{name}", budget_s=budget["work_s"] + budget["infra_s"], reporter=lifecycle.report)
# open_scope — единственная дверь создания корня, из пакета base_manager; класс Scope не экспортируется (Q2)
planes = root.child("planes")        # logger → error/stats/observation (сток дренирует при request_stop, ★5б)
root.barrier()
transport = root.child("transport")  # SRM → router → command/console: чинит инверсию :143/:197
root.barrier()
work = root.child("work")            # hooks → plugins (камера и её воркер в одной области) → workers
# stop():       root.cancel()        — фаза 1 только верхнего сегмента (work)
# раннер:       report = root.close() один раз; survivors → flush + os._exit(EXIT_SURVIVORS)
```
Порядок = порядок регистрации; golden-тест G7 проверяет его целиком вместе с барьерами.

**П3 — сегменты = внутрипроцессная половина Task 3.1 плана `lifecycle-stop-ownership`.** Этот план забирает
«именованные фазы останова внутри процесса»; их Task 3.1 сужается до межпроцессного quiesce → ack (триггер по числам
их Ф2 остаётся). Хук `_before_observability_teardown` (заглушка Task 1.6, принятая CTO 2026-09-26 как «не паттерн»)
удаляется: у PM область `children` — в сегменте `work`, сводка стопа — вызываемое, зарегистрированное после
`children` (LIFO выполнит её до снятия tap'ов). G7 пинит два инварианта приёмки 09-26: запись сводки в стор — до
`_flush_observability`; `shutdown()` без `stop()` идемпотентен по детям.

**Наблюдаемость по сегментам** (CTO р3, по `observability_wiring.py` и порядку вызовов `process_module.py`):

| Что | Где | Сегмент и порядок регистрации | Фаза |
|---|---|---|---|
| logger / error / stats / observation менеджеры | `process_module.py:346`, `_create_observation_manager` | `planes`, первыми (закрываются последними) | Ф1 |
| store-tap'ы + `BatchDrainWorker` (поток на tap) | `wire_observability_store` (:590), `batch_drain.py:358` | `planes`, ПОСЛЕ менеджеров — LIFO дренирует tap до закрытия логгера | Ф3 |
| форвардеры через роутер | `wire_observability_forward` (:1333, динамически при подписке брокера) | `transport`, после роутера — иначе снятие форвардера после роутера шлёт в закрытый канал | Ф3 |
| финальный фан-аут хаба `drain_process_observability` | :165 | вызываемое после форвардеров (выполняется первым в `transport`) | Ф1 ручкой, Ф3 контрактом |
| `wire_document_sink`, свипы ретенции и истории | :544 | `planes` после менеджеров | Ф3 |
| внутренние потоки менеджеров: retention sweeper (`logger_core.py:877`), окно статистики (`aggregation_window.py:312`), `async_sender_buffer` (:89) | — | `self.scope.spawn` своего менеджера | Ф4 |

`BatchDrainWorker` уже соблюдает ★5б кодом (`batch_drain.py:343-346, 399-430`: вход закрыт под локом, выход только при
пустом канале, недописанное считается); адаптер расщепляет его `close()`: `request_stop` = закрыть вход + wake,
`join_until` = join потока, `close()` = дожим и итог. `ObservabilityBroker.subscribe_all` — удалённый реестр по имени
процесса, остаётся; ручкой становится его локальный форвард-tap. otel Task 2.4 («otel flush: N дожато, M потеряно» до
снятия форвардеров) под этой схемой — `plugin.shutdown(ctx)` в `work`, закрывается до `transport` и `planes`: та же
гарантия барьером, конфликта нет. Прототип CTO
(`cto_barrier_e1.py`): 0.50–0.53 с против 1.02 с у «только своя область» и против потери логов у «один корень без
барьера» (0/2).

### 2.4 Qt

`attach_qt(scope, obj)`: `scope.close` → `obj.deleteLater()` (thread-safe; PySide 6.10.3 передаёт владение C++);
`obj.destroyed` → `scope.close()` через weakref на scope; обработчик не держит `obj`. Обязателен для каждого QObject
без Qt-родителя и корня компонента. Синхронный `delete` отвергнут: удаление отправителя внутри его сигнала — крах.
Без цикла событий (тесты, после `aboutToQuit`) — `flush_deferred_deletes()` на главном потоке (прогон E2: обёртки
мертвы во всех трёх случаях). Проверка «Qt-родитель в цепочке якоря области-предка» — при освобождении, не при
привязке (родитель ставится после create); не прогнано.

### 2.5 Сток «никогда молча» (★5)

«Невозможно» недостижимо, «никогда молча» — достижимо: (а) `Subscribers.emit` при закрытом owner → счётчик
`emits_after_close` в отчёте корня; (б) контракт стока: `request_stop` = закрыть вход → дренировать → выйти, не
«выйти по флагу» (CTO: потеря последней строки 1/5 при `report.ok=True` у стока, выходящего по флагу);
(в) литеральный тест на настоящем logger-drain: N/N после `root.close()`.

### 2.6 Другие самописные механизмы (аудит CTO р3 + агент-инвентаризатор + греп лида, 2026-10-03)

Глобальные счёты (греп вне тестов): `threading.Thread(` — 59 сырых строк (вкл. `robot/`, `tools/`, пробы);
`threading.Timer(` — 3; `ThreadPoolExecutor(` — 5; `weakref.finalize(` — 1; `atexit.register(` — 0; методов
`start/stop/shutdown/close/dispose/teardown` — 289 определений. Классов `*Subscription*` — 5 разных
(`_Subscription`, `Subscription` ×2, `_ConfigSubscription`, `_SubscriptionRegistry`), классов-ручек — 7.

Правило: **удалённый реестр** (ключ — имя процесса/клиента, Dict at Boundary) на `Subscribers` не мигрирует;
мигрирует его локальная сторона (tap, поток, колбэк). **Каталог ресурсов** (учёт, а не жизненный цикл) остаётся.

| Модуль | Что там (file:line) | Решение | Фаза |
|---|---|---|---|
| `service_module` | поток старта без join (`host.py:143`); `ServiceRegistry` — каталог | `ServiceHost` — область на сервис, поток → `spawn`; каталог остаётся | Ф4 |
| `state_store_module` | `SubscriptionManager` (`core/subscription_manager.py:219`, sub_id по подписчику) — удалённый; `StateProxy.subscribe` (`proxy/state_proxy.py:361`) — 12 мест, отписок 6 (`frontend/process.py` ×4, `telemetry_sink` ×2, `scene_source` ×1 — без отписки); поток flusher (`delta_dispatcher.py:288`); `threading.Timer` persistence (`persistence_manager.py:258`); свой порядок останова (`state_store_manager.py:134`) | реестр остаётся; `StateProxy.subscribe(owner=)` → Subscribers; потоки и таймер → spawn; порядок — регистрацией в области | Ф3 / Ф4 |
| `chain_module`, Plugins `worker_pool`/`chain_executor` | `WorkerPoolDispatcher`, `WorkerPoolExecutor` со своим `shutdown` и ручкой `_PoolTask` — вызывающих вне тестов 0 (контракт); Plugins: `shutdown(wait=True)` без срока (`worker_pool/plugin.py:106`), `wait=False` (:218, `chain_executor/plugin.py:108`) | адаптер пула: Stoppable, `kill` = `shutdown(cancel_futures=True)`; классы chain — на области владельца | Ф4 |
| `frontend_module/application/thread_manager.py` | реестр QThread (`:26`), `stop` с `terminate()` (`:116`); регистраций вне тестов 0 | `QThreadHandle`, реестр удаляется | Ф5 |
| `config_module` | `Config.subscribe/unsubscribe` (`config.py:115/139`, 1 вызывающий — `frontend_manager.py:89`, снятие не найдено); поток `ConfigFileWatcher` (`tools/watcher.py:141`, 1 вызывающий — `observability_reload.py:2341`); прототип `_ConfigSubscription` (`adapters/stores/config_store.py:39`) — ещё один тип ручки | Subscribers; watcher → spawn; `_ConfigSubscription` → `IHandle` | Ф3 / Ф4 |
| `app_module` | ручной порядок останова (`orchestrator.py:85`: watcher наблюдаемости → watcher рецептов L2 → state_store → super) | порядок — регистрацией в области | Ф1 |
| `command_module` | `register_command` (`command_manager.py:166`) — таблица обработчиков, снятия нет, ~32 места | `owner.own(...)` для команд с жизнью короче процесса; таблица остаётся | Ф3 |
| `Services/sql` | `threading.Timer` (`action_log/log_writer.py:167`) | spawn / таймер в области | Ф4 |
| `router_module` | `register_message_handler` (снятия нет), `SocketClient.add_push_listener` (снятия нет) | ручка + `unregister` | Ф3 |
| `channel_routing_module` | `add_tap/remove_tap/close_all_taps` | `add_tap(..., owner=) -> IHandle` | Ф3 |
| `actions_module` | `ActionBus.add_post_execute_callback` (`bus.py:147`, снятие `:159`), `add_change_callback` (`:429`, снятие `:434`) — 5 мест подписки, вызовов снятия 0; `register_handler` (`:101`) без снятия | Subscribers, `owner=` | Ф3 |
| `frontend_module` + прототип | ещё четыре `add_change_callback`: `entity_editor/base_editor_model.py:162`, `prototype/adapters/dispatch/command_dispatcher.py:277`, `prototype/domain/topology_session.py:95` (+ вызов `tab_layouts/_abstract_columnar.py:94`); 4 подписки на EventBus в `frontend/app.py` (:679, :697, :698, :766) выбрасывают ручку | Subscribers, `owner=`; подписки app.py — в корень GUI | Ф5 |
| `shared_resources_module` | `events/core/manager.py:167/172` — свой список колбэков, вызывающих вне тестов 0 (контракт) | Subscribers | Ф3 |
| `shared_resources_module` | `ShmRegistry`, `QueueRegistry`, `ProcessStateRegistry`, `ProcessHandle` (доступ к ресурсам) | каталоги ресурсов, остаются; SRM — одна ручка в `transport` | — |
| `display_module`, кольцевой буфер SRM | `DisplayRegistry` (`registry.py:37`) — каталог входов; `consumer_id` только в Protocol `IDisplayChannel` (реализаций не найдено); реестр потребителей — `shared_resources_module/buffers/ring_buffer.py:47` (`register_consumer` :57 / `unregister_consumer` :62, вызывающих вне тестов 0) | каталог и реестр по id остаются | — |
| `backend_ctl` (клиентский инструмент) | два списка `subscribe/unsubscribe` (`events.py:424/629`), `_SubscriptionRegistry` (`subscriptions.py:19`), поток рекордера (`recorder.py:317`), `threading.Timer` автоотката (`registers.py:360`), поток `harness.py:270`; watch/tail/ui_tap — удалённые на стороне PM | списки → Subscribers; потоки/таймер → spawn; удалённые остаются, их локальные tap'ы на стороне PM — ручки | Ф3 / Ф4 |
| `recipe` | только инжектированные колбэки миграций (ADR-SS-003); реестра, потоков, таймеров нет | не затронут | — |
| Services и Plugins с собственными потоками | `threading.Thread(`: `Services/code_reader` 5, `auth` 1, `phone_gateway` 1, `robot_comm` 2, `Plugins/sim` 4; `Plugins/sources` — 26 методов start/stop | spawn в области сервиса/плагина | Ф4 |

Не установлено (на вход Ф0/Ф4): реализация `IDisplayChannel`; отменяет ли `PersistenceManager.save_now` таймер;
поточность debounce `ConfigFileWatcher`; тела start/stop `Plugins/sources` и потоков `Services/*`.

## 3. Стражи (каждый с инъекцией)

| Страж | Ловит | Инъекция → красный |
|---|---|---|
| G1 контракт `lifetime.py` (сценарии a–h, барьер, E2–E5 литералами) | реентрантность, add-after-close, выжившие, цикл ручки, порядок сегментов | убрать проверку `active` в emit → доставка A,B,C; убрать проверку состояния в `own` → воскрешение; убрать барьер → потеря строки |
| G2 сигнатуры издателей | подписка без владельца | `owner=None` или `owner: Scope` у любого издателя из литерального списка |
| G3 незакрытые корни: WeakSet + recorder на `weakref.finalize`, держит только weakref на флаг (совет 9) | забытый `close` | тест создаёт корень и не закрывает; брошенный корень |
| G4 перепись потоков | живой поток без префикса пути области | сырой `Thread` |
| G5 Qt-мусор: `DEBUG_SAVEALL`, `isValid and ownedByPython` → отчёт с Ф0, fail по каталогам из литеральной таблицы по мере обнуления | Python-owned QObject в цикле (класс abort) | убрать `attach_qt` в обнулённом каталоге |
| G6 AST (★6 вобрал G11): сырой `threading.Thread(` в Plugins/Services; `QTimer()` без родителя; `.join(<литерал>)`; `.terminate(`/`.kill(` вне `child_process_stop.py`; `"shutdown_timeout"` вне `stop_budget.py`; `.deleteLater(` вне `qt_lifetime.py`; импорт `base_manager.core.lifetime` вне base_manager; `lifetime.py` — только stdlib; один allowlist с причинами | регресс миграции, второй владелец | вернуть `process.terminate()` в `process_registry.py` |
| G7 golden порядка корня процесса с барьерами | перестановка | поменять местами создание SRM и router |
| G8 время стопа ребёнка < 1.5 с (фейк-камера блокирует `read()` до `request_stop`) | 5-с ханг | камера в другой области, чем воркер |
| G9 `introspect.lifetime` в backend_ctl | выживший на стенде | плагин со `sleep(3)` |
| G10 счётчик shim = 1 (только `Plugins/io/otel_export/plugin.py` чужой полосы) до Ф6, 0 в Ф6 | новая обёртка | добавить обёртку без строки в списке |

## 4. Решения по развилкам (итог)

| Развилка | Решение | Почему |
|---|---|---|
| D1 дом | `base_manager/core/lifetime.py`, интерфейсы в `base_manager/interfaces.py` | core-ярус, импортируется всеми; довод «Pydantic» снят прогоном — любой импорт фреймворка тянет его через `multiprocess_framework/__init__.py` |
| D2 протокол | один `Stoppable` (+ необязательные `kill`, `close`) и `Callable` для одноразового | один срок на всё; подписке второй этап не нужен — она вызываемое |
| D3 слабые ссылки | нет; обязательный `owner` + `emits_after_close` + `Subscribers.errors` | WeakMethod молча перестаёт доставлять |
| D4 порядок | LIFO по регистрации + барьеры + golden G7 | порядок перестаёт быть прозой |
| D5 Qt-детектор | отчёт с Ф0, fail по каталогам при нуле | мусор в точке abort — вкладки; fail в Ф2 краснел бы на чужих файлах |
| D6 слом API | атомарно издатель + все вызывающие; единственная обёртка — для чужой полосы otel | обёртка = флаг; флаг закрыт, когда удалён |
| Сток | «никогда молча» (★5) | «невозможно» недостижимо |
| Abort-гейт | in-suite crashprobe `offmain_gc` 3× survived + G5 = 0 по frontend; серия штатных гейтов Ф3–Ф6 — пассивное наблюдение | проба детерминирована на базе (crash 3/3, контроли survived) |

## 5. Не в этом плане

- Межпроцессный протокол останова (quiesce → ack), метки очередей, ReaderGoneQueue, сироты — план
  `lifecycle-stop-ownership` (Ф1 DONE, ADR-PMM-031; Ф2 ждёт L-6; Task 3.1 сужается до межпроцессной половины, П3).
  Этот план даёт им внутрипроцессную половину: `cancel()` = «прекратите», `close()` = «выходите» внутри ребёнка.
- П4: `ProcessTreeGuard` (Job-объект / `killpg` снаружи PM) и досъём поддерева в `backend_ctl/harness.py`
  (Task 1.4/1.5 stop-ownership) **сохраняются**: они бьют деревья ОС, а не владеют ручками — дубля нет.
- Коллизия по файлам: Ф3 этого плана переписывает пары `wire_/unwire_` в `observability_wiring.py`, которые правят
  задачи Ф4 `observability-closure` (4.1, 4.3, 4.3b, 4.14). Ф3 стартует после этих задач, либо closure принимает ручки
  в своих задачах — сверка с `plans/observability-closure/phase-4-scale-and-form.md` на входе Ф3.
- Отделение GUI в клиент — план `2026-09-22_gui-service`; идёт после Ф5 этого плана на его механизме.
- Ленивые импорты `process_module/__init__.py:118-126` в `process_manager_module` (нарушение направления) —
  `OPEN_QUESTIONS.md`.

## 6. Открыто и ненадёжно

- Барьер — 12-строчная заплата CTO поверх прототипа; `cancel()` и `Handle.close()` через барьер не прогнаны.
- Гонка потери последней строки (1/5, 1/9) объяснена «сток выходит по флагу» по чтению — Task 0.x доказывает
  дренирующим стоком.
- E5b (сторож корней) в демо не сошёлся: recorder держал `__dict__`; исправление не прогнано.
- In-suite crashprobe и `os._exit` при выживших не запускались в этой дискуссии.
- Проверка Qt-потомка при освобождении и гонка `destroyed` vs освобождение из чужого потока — не прогнаны.
- `EXIT_MARGIN`/`INFRA_RESERVE` — оценки (0.5 с), замер в Ф1.
- Числа 85 / 39 / 7–13 — из отчётов investigator'ов, полного пересчёта нет; G2-список издателей строится в Ф0 грепом.
- Флаг `active` без лока опирается на GIL 3.12; free-threaded сборке не годится.
