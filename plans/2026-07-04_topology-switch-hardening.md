# Plan: Отладка переключения рецептов — гарантированная остановка процессов и очистка IPC

- **Slug:** topology-switch-hardening
- **Дата:** 2026-07-04
- **Статус:** DRAFT
- **Ветка:** fix/topology-switch-hardening

## Контекст

Симптом: при переключении рецептов иногда «процессы не останавливаются и начинают конфликтовать» (двойной захват камеры, сообщения уходят в мёртвые очереди, дисплеи привязаны не к тем слотам). Расследование 2026-07-04 показало: сам 5-фазный конвейер (`stop_all → cleanup → provision → create → start`, `FullReplacePlanner` + `TopologyManager`) спроектирован верно, но **аварийные ветки** содержат баги:

1. `_restore_from_snapshot` (rollback) пересоздаёт процессы **без проверки, что старые мертвы** — при `BlueprintInvalid` (валидация до stop-фазы) ни один процесс не остановлен, rollback запускает вторые копии всех процессов, а `remove_process` выбрасывает их `stop_event` из реестра → зомби, неуправляемые до полного выхода приложения.
2. `stop_many` возвращает `False` для имени без Process-объекта («призрак» в `_process_configs`) → любой switch падает на команде №0 и вечно уходит в rollback. Призраки возникают: `create_process` и boot-путь пишут конфиг **до** успешного создания.
3. GUI (Recipes-таб) использует fire-and-forget `proxy.apply_topology` с optimistic-ack `{"success": True}` → при rollback/debounce на backend GUI всё равно активирует slug, перестраивает дисплеи и персистит рецепт в app.yaml → расхождение состояния GUI ↔ backend.
4. Rollback восстанавливает процессы последовательно (register→create→start по одному), без двухфазности → routing_map первых восстановленных не содержит очередей последующих → полусвязанная топология.
5. После `kill()` нет финального `join` и верификации смерти; cleanup/unlink SHM стартует по «сигнал подан», а не по «процесс мёртв».
6. Костыли: мёртвая «очистка» несуществующего `shared_resources._registered` в `_teardown_partial`; снятие процесса с PSR спрятано как побочный эффект `release_process_memory`; `monitor.stop()` — только флаг, авто-рестарт исполняется на потоке монитора (гонка со switch при включении RestartPolicy).

## Цели

- Переключение рецепта **никогда** не оставляет живых процессов старой топологии — включая ветки rollback (невалидный рецепт, provision/create/start-fail). Проверяемо тестами.
- Ошибка/пропуск переключения **виден пользователю**: GUI откатывает активный slug, не персистит, показывает причину (`rolled_back` / `debounced` / текст ошибки).
- Semantics stop-фазы: «нечего останавливать» = успех; «остановлен» = подтверждён `not is_alive()` после эскалации stop_event → terminate → kill → join.
- Cleanup явный: снятие с PSR — прямой вызов, без побочных эффектов через memory manager; мёртвый код удалён.
- `python scripts/validate.py` и framework-тесты зелёные после каждой Task.

## Out of scope

- Включение `RestartPolicy.enabled=True` — отдельное решение владельца после Task 3.1 (сейчас выключен, гонка дремлет).
- Переделка relay-механизма стейл-роутинга GUI (routing-epoch / PM-mediated addressing) — системная тема, отдельный план.
- `IncrementalPlanner` (частичная замена топологии) — не трогаем, only full-replace.
- Windows-специфика SHM (инкарнации работают, не трогаем).

## Phase 1: Framework — стоп-фаза и rollback (P0, корень симптома)

**Цель фазы:** любой исход `apply_topology` оставляет систему в одном из двух состояний — «новая топология работает» или «старая топология полностью восстановлена», без зомби и дублей.

### Task 1.1: `stop_many`/`stop_one` — верификация смерти + idempotent-семантика
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/core/process_registry.py`, `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`_topology_stop_all`), `multiprocess_framework/modules/process_manager_module/tests/`
- **Acceptance:**
  - имя без Process/stop_event → `True` («уже остановлен», idempotent — паритет с `PM.stop_process`);
  - после `terminate`/`kill` — финальный `join`, результат по факту `not is_alive()`;
  - `_topology_stop_all` логирует карту `{name: bool}` при частичном провале;
  - unit-тесты: ghost-имя не валит stop-фазу; застрявший процесс (не реагирует на stop_event) добивается и подтверждается мёртвым.
- **Module contract:** public-api-change (семантика возвращаемого значения `stop_many` — обновить docstring-контракт; вызывающие: `_topology_stop_all` + тесты)

### Task 1.2: rollback через 5-фазный конвейер вместо `_restore_from_snapshot`
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`apply_topology`, `_restore_from_snapshot`, `_teardown_partial`)
- **Acceptance:**
  - rollback = тот же порядок side-effect'ов, что и apply: **stop_all живых** (snapshot-имена + частично созданные новые) → cleanup → provision (все) → create (все) → start (все) — двухфазность сохранена, routing_map восстановленных полный;
  - сценарий «BlueprintInvalid поверх работающей топологии»: после rollback ни одного дубля, все процессы старой топологии живы и **останавливаемы** (stop_event в реестре) — интеграционный тест;
  - сценарий «fail на provision/create №k»: старая топология восстановлена полностью связанной — тест;
  - `_teardown_partial` больше не трогает несуществующий `shared_resources._registered` (мёртвый код удалён, реальная очистка — через cleanup-фазу rollback).
- **Module contract:** impl-only (публичный контракт `apply_topology` не меняется: `success`/`rolled_back`)

Заметка по реализации: не чинить `_restore_from_snapshot` точечно — выделить общий приватный хелпер (например `_run_replace_pipeline(proc_dicts, to_stop)`), который использует существующие сиды `_topology_stop_all`/`_topology_cleanup`/`_topology_provision`/`_topology_create`/`_topology_start`. Rollback вызывает его с snapshot-конфигами. Защита от рекурсии: rollback-прогон не запускает вторичный rollback (best-effort + подробный лог).

### Task 1.3: убрать «призраков» `_process_configs`
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`create_process`, `_create_processes_from_config`)
- **Acceptance:** конфиг пишется в `_process_configs` **только после** успешного `create_and_register`; при провале создания записи нет; тест: boot с битым class-path у одного процесса → следующий switch не блокируется stop-фазой.
- **Module contract:** impl-only

### Task 1.4: явная очистка PSR + сопутствующие хвосты
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`_cleanup_process_resources`), `multiprocess_framework/modules/shared_resources_module/memory/core/manager.py` (`release_process_memory`), `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py`, локальные `DECISIONS.md`
- **Acceptance:**
  - `psr.unregister_process(name)` вызывается явно из `_cleanup_process_resources`; `release_process_memory` чистит **только память** (контракт сужен — ADR-запись в `shared_resources_module/DECISIONS.md` + `python -m scripts.sync`);
  - при cleanup имени чистятся `_last_heartbeat`, `_restart_counts`, `_workers_status`, `previous_states` монитора и запись ConfigStore;
  - существующие тесты shared_resources/process_manager зелёные, добавлен тест «после cleanup в PSR нет ни очередей, ни событий, ни memory-метаданных процесса».
- **Module contract:** public-api-change (контракт `release_process_memory`)

## Phase 2: Prototype — GUI видит фактический результат (P1)

**Цель фазы:** состояние GUI (активный slug, дисплеи, app.yaml) меняется только по подтверждённому результату backend.

### Task 2.1: Recipes-таб на async request/response
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py`, `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py`, `multiprocess_prototype/frontend/bridge/process_manager_proxy.py` (docstring/ack), тесты `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/`
- **Acceptance:**
  - «Сделать активным» использует `proxy.apply_topology(source, on_result=...)` (канал уже существует — как в Pipeline-табе);
  - на время применения кнопка disabled + видимый busy-статус; повторный клик не отправляет второй запрос;
  - `on_result` с `success=False` (включая `rolled_back`, `debounced`): откат `store.set_active(prev)`, компенсирующая синхронизация дисплеев/state, **нет** persist в app.yaml, ошибка показана пользователю;
  - `success=True`: persist + load() — как сейчас;
  - pytest-qt тесты: fail→откат, debounce→откат, success→persist.
- **Module contract:** impl-only (сигнатуры presenter не меняются; порядок эффектов — внутренняя логика)

Заметка: порядок отката `ActivateRecipe`/дисплеев решить при реализации (компенсирующий dispatch `ActivateRecipe(prev)` или отложенный dispatch до подтверждения) — зафиксировать выбор в Decisions log плана.

### Task 2.2: readiness-барьер после start
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` (`apply_topology`, после успешного `TopologyManager.apply`), конфиг (`start_ready_timeout_s`), тесты
- **Acceptance:**
  - после успешной start-фазы PM ждёт (poll `is_alive` + первый heartbeat/статус running) до `start_ready_timeout_s` (дефолт ~5с);
  - результат `apply_topology` содержит `ready: {name: bool}`; процессы, умершие в `initialize()` (exitcode 0 — сейчас выглядит как успех), попадают в `ready=False`;
  - GUI (Task 2.1) показывает частичный успех («топология применена, N процессов не поднялись: …»);
  - тест: процесс с падающим `initialize()` → `success=True, ready[name]=False` (политика: не rollback, но честный репорт — см. Открытые вопросы).
- **Module contract:** public-api-change (новое поле `ready` в результате `topology.apply`)

## Phase 3: Монитор — убрать гонку с переключением (P2)

**Цель фазы:** пауза монитора синхронна, авто-рестарт не может исполняться параллельно со switch.

### Task 3.1: синхронный `monitor.stop()` + рестарт вне потока монитора
- **Статус:** [PENDING]
- **Файлы:** `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py`, `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
- **Acceptance:**
  - `stop()` дожидается завершения текущей итерации цикла (Event/lock, таймаут с warning), после возврата ни один restart не в полёте;
  - `_try_auto_restart` не вызывает `restart_process` на потоке монитора и не спит backoff в цикле — рестарт уходит командой в PM (router-поток), pending-рестарты отменяются при старте `apply_topology`;
  - тест: имитация «crash во время switch» → рестарт либо до, либо после замены, никогда параллельно.
- **Module contract:** impl-only

## Порядок исполнения и валидация

1. Task 1.1 → 1.2 → 1.3 → 1.4 (framework-ядро, каждая — отдельный коммит с `Refs:`);
2. Task 2.1 → 2.2 (prototype + PM-результат);
3. Task 3.1;
4. после каждой Task: `python scripts/validate.py` + `python scripts/run_framework_tests.py`; для Phase 2 — pytest-qt тесты recipes-таба; финально `make gate`;
5. ревью после каждой фазы: `/review` (reviewer, Opus) — фокус: lifecycle/IPC/thread-safety.

## Открытые вопросы

- [ ] Task 2.2: политика при `ready=False` — оставить топологию (честный репорт, оператор решает) или авто-rollback? Предлагаю: оставить + репорт; rollback по ready — отдельным решением. — владелец
- [ ] Включать ли `RestartPolicy.enabled=True` после Task 3.1 (снять TODO в `restart_policy.py`)? — владелец
- [ ] Нужен ли отдельный план на routing-epoch для protected-процессов (замена relay-костыля)? — владелец

## Решения (decisions log)

- **2026-07-04:** rollback реализуем через тот же конвейер сидов, что и прямое применение (общий хелпер), а НЕ точечной починкой `_restore_from_snapshot` — два расходящихся пути восстановления и были источником багов (aliveness, однофазность).
- **2026-07-04:** семантика stop для топологии — «ensure stopped» (idempotent), подтверждение смерти обязательно до cleanup/unlink SHM.
- **2026-07-04:** снятие процесса с PSR — явная операция cleanup-фазы, не побочный эффект освобождения памяти.
