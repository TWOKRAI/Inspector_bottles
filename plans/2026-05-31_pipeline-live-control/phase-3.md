# Этап 3 — Granular live-управление по router-адресу (сложный, отдельный)

**Цель этапа:** управлять элементами пайплайна **точечно по иерархическому
router-адресу** — остановить отдельный воркер (в API сейчас НЕТ — только процесс
целиком), адресно удалить плагин/воркер/процесс из живого графа без полной пересборки.
Поверх transport-router-hub P3 и hierarchical addressing.

**Сложность этапа:** Senior+ (Opus, extended thinking) · **Риск:** высокий
(новый метод фреймворка, новый IPC-контракт, гонки и полукадры при отцепке ноды).
**Что переиспользуется:** паттерн `SetPluginConfig → PluginConfigChanged → rm.set_value`
(параметр плагина вживую УЖЕ работает — копировать структуру команда→событие→применение),
иерархическая доставка по `address[0]` (P2.1 DONE), worker-handler роутинг по адресу (P2.2 DONE),
proxy/IPC из Этапа 1.
**Что пишется заново:** метод фреймворка `stop_worker(address)` (per-worker), новый
IPC-контракт адресного управления, логика консистентности живого графа.

> **Зависимость от transport-router-hub P3:** P3 там = транспортная доставка по адресу
> (per-worker stop на уровне транспорта). Этот этап = pipeline-сторона (IPC-контракт из GUI +
> консистентность графа). **Синхронизировать, не дублировать.** Начинать только после/совместно с P3.

---

### Task 3.1 — Метод фреймворка stop_worker(address) / per-worker управление

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** во фреймворке появляется API остановки/запуска **отдельного воркера** по
иерархическому адресу (процесс → воркер), а не только процесса целиком.

**Context:** `start/stop/restart_process` (PM:964-1004) работают по имени процесса.
Per-worker stop отсутствует (блокер #4 расследования). Hierarchical addressing
(процесс → воркер → глубже) и worker-handler роутинг по адресу (P2.2 DONE) дают основу
адресации. Защищённый main worker не должен останавливаться (см. workers architecture).

**Files:**
- `multiprocess_framework/modules/process_manager_module/interfaces.py` — объявить контракт
  `stop_worker(address) / start_worker(address)` (новый public API)
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
  (рядом с ~964-1004) — реализация делегирования адреса в нужный процесс/WorkerManager
- `multiprocess_framework/modules/.../worker_module` (WorkerManager) — точечная
  остановка/запуск воркера (реальные потоки, см. workers architecture)
- `multiprocess_framework/modules/process_manager_module/DECISIONS.md` — ADR на новый API

**Steps:**
1. Изучить hierarchical addressing (`project_hierarchical_addressing`) и P2.2 worker-handler
   роутинг — формат адреса `[process, worker, ...]`.
2. Объявить в `interfaces.py` контракт per-worker stop/start (Dict at Boundary: адрес — dict/список примитивов).
3. Реализовать в PM: разобрать адрес → найти процесс → делегировать в WorkerManager целевого процесса.
4. Защитить main worker (нельзя остановить protected worker — вернуть ошибку/no-op со статусом).
5. Покрыть тестами (framework tests), ADR в DECISIONS.md (+ `python -m scripts.sync`).

**Acceptance criteria:**
- [ ] `stop_worker(address)` / `start_worker(address)` в `interfaces.py`, реализованы в PM
- [ ] Адрес и payload — dict/примитивы (Dict at Boundary); SHM напрямую не трогается
- [ ] Защищённый main worker не останавливается
- [ ] Новые framework-тесты зелёные: `python scripts/run_framework_tests.py`
- [ ] ADR записан, `python scripts/validate.py` без дрифта документации

**Out of scope:** GUI-сторона (Task 3.2/3.3); транспортная доставка по адресу (это P3 transport-router-hub).
**Edge cases:** несуществующий адрес; адрес процесса без воркера; повторная остановка
уже остановленного воркера (idempotent); воркер в середине цикла (graceful stop).
**Dependencies:** transport-router-hub P3 (транспорт), P2.2 (worker-handler роутинг)
**Module contract:** public-api-change (interfaces.py process_manager_module)

---

### Task 3.2 — IPC-контракт адресного управления (плагин / воркер / процесс)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** новый IPC-контракт «команда → событие → применение» для адресного управления
из GUI (удалить/остановить элемент по router-адресу), построенный по образцу уже
работающего `SetPluginConfig → PluginConfigChanged → rm.set_value`.

**Context:** Параметр плагина вживую УЖЕ работает через эту цепочку — копировать паттерн,
не изобретать. Нужны аналогичные команды для остановки/удаления воркера/процесса по адресу
и подтверждающие события для синхронизации GUI-графа.

**Files:**
- `multiprocess_prototype/frontend/bridge/process_manager_proxy.py` (из Task 1.1) — добавить
  адресные методы (`stop_worker(address)`, `remove_node(address)` и т.п.)
- `multiprocess_prototype/frontend/` / `command_module` — определить command-типы и event-типы
  по образцу `SetPluginConfig`/`PluginConfigChanged`
- `multiprocess_framework/modules/process_manager_module/` — приёмник команд → вызов API Task 3.1
- соответствующий модуль контрактов/interfaces, где живут command/event типы

**Steps:**
1. Зафиксировать структуру по образцу: команда `Stop/RemoveByAddress` → обработка в backend →
   событие `WorkerStopped/NodeRemoved` → синхронизация GUI-графа.
2. Реализовать GUI-сторону в proxy (dict-payload с адресом).
3. Реализовать backend-приёмник, делегирующий в API Task 3.1.
4. Эмиссия подтверждающего события → подписка GUI (по образцу `PluginConfigChanged`).

**Acceptance criteria:**
- [ ] Команда и событие объявлены и проходят round-trip GUI→backend→GUI (dict на границе)
- [ ] Паттерн повторяет `SetPluginConfig` (нет нового параллельного механизма)
- [ ] Тесты на сериализацию/round-trip зелёные
- [ ] qt-mcp smoke: адресная остановка воркера → точечный эффект на дисплее (qt_snapshot)

**Out of scope:** консистентность графа при гонках (Task 3.3); per-worker API (Task 3.1).
**Edge cases:** событие-подтверждение не пришло (timeout, откат UI); адрес устарел
(элемент уже удалён другим путём).
**Dependencies:** Task 3.1, Этап 1 (proxy)
**Module contract:** new-lite (новый command/event-контракт)

---

### Task 3.3 — Консистентность живого графа при отцепке ноды (гонки, полукадры)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** при адресном удалении/отцепке ноды на лету не возникает полукадров, зависших
буферов и рассинхрона GUI-графа с runtime; гонки между авто-apply (Этап 2), ручными
кнопками (Этап 1) и адресными командами (Task 3.2) разрешаются детерминированно.

**Context:** Отцепка ноды в работающем пайплайне (кадры через трубы-pipes, команды через
mailbox — гибрид P1 DONE) рискует оставить полукадр/повисший потребитель. Нужна
протокол-последовательность отцепки (drain → detach → stop) и единый арбитр изменений графа.

**Files:**
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` — арбитраж источников изменений
  (ручные/авто/адресные), порядок применения
- `multiprocess_framework/modules/process_manager_module/` / transport — последовательность
  drain→detach→stop при отцепке (координация с transport-router-hub)
- relevant worker/channel модуль — корректное закрытие pipe/потребителя без полукадра

**Steps:**
1. Определить протокол отцепки ноды: остановить продюсера → дренировать канал →
   отцепить потребителя → освободить ресурсы.
2. Ввести единый арбитр изменений графа (serialize): команды из Этапа 1/2/3 не пересекаются.
3. Обработать полукадры: гарантировать, что после detach дисплей не показывает «застывший» кадр.
4. Стресс-тест: быстрые add/remove/stop в Live-режиме.

**Acceptance criteria:**
- [ ] qt-mcp smoke + стресс: серия быстрых отцепок/подключений нод → нет зависших кадров,
      GUI-граф == runtime (qt_snapshot, лог консистентности)
- [ ] Гонки Этап1/2/3 разрешаются детерминированно (последний/арбитр), без deadlock
- [ ] Нет утечек ресурсов (pipe/поток закрыты после detach)
- [ ] Тесты зелёные; `python scripts/validate.py` чистый

**Out of scope:** новые типы нод; изменение транспорта (это transport-router-hub).
**Edge cases:** отцепка ноды-источника (split) при активных потребителях; одновременная
ручная и адресная команда на один адрес; backend упал во время отцепки.
**Dependencies:** Task 3.1, Task 3.2, Этап 2 (для арбитража с авто-apply), transport-router-hub P3
**Module contract:** impl-only
