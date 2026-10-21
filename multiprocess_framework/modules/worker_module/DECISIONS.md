# worker_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-WRK-001 (was ADR-159): Удаление ложного ребра worker → dispatch

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** ARCHITECTURE.md содержал ребро `worker --> dispatch`, подразумевая, что WorkerManager использует Dispatcher. Grep подтвердил 0 импортов из dispatch_module. WorkerManager — менеджер жизненного цикла потоков (create/start/stop/restart), а не маршрутизатор сообщений. Dispatcher используется в CommandManager и RouterManager для routing ключ→обработчик.  
**Решение:** Удалить ребро из графа. worker_module зависит только от base_manager (#1).  
**Последствия:** Граф зависимостей точнее отражает реальность. Упрощает анализ для process_module (#11).

## ADR-WRK-002 (was ADR-160): Сохранение двух конфигурационных подходов (ThreadConfig + SchemaBase)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Модуль имеет два конфигурационных подхода:
1. `core/thread_config.py` — `ThreadConfig` (plain class, `to_dict()`/`from_dict()`) — runtime-объект, используется в WorkerManager/WorkerLifecycle.
2. `configs/thread_worker_config.py` — `ThreadWorkerConfig(SchemaBase)` — Pydantic-схема для декларативного конфига процесса.

STATUS.md явно отмечал: «рантайм ThreadConfig не заменён».  
**Решение:** Сохранить оба. Причины:
- `ThreadConfig` — лёгкий runtime-объект внутри процесса (не пересекает границу процессов сам по себе).
- `ThreadWorkerConfig(SchemaBase)` — декларативная схема для конфигов процесса (`proc_dict["thread"]`), с Pydantic-валидацией.
- Паттерн ADR-008 (Dict at Boundary): Pydantic на границе (`ThreadWorkerConfig.model_dump()` → dict → `ThreadConfig.from_dict()`), plain class внутри.
- Замена ThreadConfig на SchemaBase добавит тяжёлый Pydantic в горячий путь lifecycle без выигрыша.  
**Последствия:** Два объекта с похожими полями, но разными ролями. Документировано.

## ADR-WRK-003 (was ADR-161): Сохранение self.name = manager_name (compatibility alias)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `worker_manager.py:42` содержит `self.name = manager_name` с комментарием «Синоним для совместимости». Grep показал: используется в `test_worker_manager.py`. Внешних потребителей (process_module) через `.name` не обнаружено.  
**Решение:** Сохранить alias. Причины:
- Минимальная стоимость (1 строка).
- BaseManager может иметь `.name` в будущем (стандартный паттерн).
- Удаление требует правки теста без выигрыша.  
**Последствия:** Alias остаётся. Если BaseManager добавит `.name`, убрать дубликат.

## ADR-WRK-004 (was ADR-162): WorkerInfo как TypedDict (документация) + plain dict (runtime)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `types/types.py` определяет `WorkerInfo(TypedDict)`, но `registry.register()` конструирует plain dict литерал. TypedDict служит документацией полей, не runtime-проверкой.  
**Решение:** Оставить как есть. TypedDict используется IDE и mypy для подсказок. Runtime-конструкция через dict литерал — стандартный паттерн Python (TypedDict не создаёт экземпляры иначе чем dict).  
**Последствия:** Тип-безопасность обеспечивается IDE/mypy, не runtime.

## ADR-WRK-005: `KeyedExecutor` — исполнитель с порядком по ключу (Task 1.9a, L-9)

**Статус:** accepted (2026-10-21, Task 1.9a плана `lifecycle-stop-ownership`; стадия 0 — reviewer Opus, 2 раунда).

**Контекст.** Обработчик команды, который ждёт другой процесс, занимает приёмный поток (L-9). В PM уже есть ядро
«FIFO на ключ + поток на занятый ключ» (`_run_when_child_ready` / `_drain_child_actions`, ADR-PMM-024), но без потолка
очереди, без `reply` ровно раз, без закрытия к сроку и без ключей-множеств. Вердикт CTO (О5, р.2): один исполнитель
во фреймворке, потоки — через `WorkerManager`, не второй механизм.

**Решение.** Протокол `OrderedExecutor` (`interfaces.py`) и реализация `keyed_executor.KeyedExecutor` (Stability: lite).
- Устройство — обобщение ADR-PMM-024: одна общая `pending: deque` в порядке подачи + `running: Counter[str]` + флаг
  `running_all`. Запись исполнима, если её ключ не пересекается с исполняемыми, нет `running_all` и ключ не
  пересекается с ключами всех более ранних записей; `None` исполнима, только когда ничего не исполняется и впереди
  никого нет. Рабочий под `Condition` берёт первую исполнимую запись (O(`max_pending`)). Одной «deque на ключ» мало:
  `None` должен задерживать ключи, которых ещё нет ни в одной очереди, а `{a,b}` в голове очереди `a` держал бы
  рабочего, пока занят `b`.
- `reply` ровно раз: «закрыт?» + постановка, опустошение + `closed=True` — под одним локом; запись уходит из `pending`
  только под локом (QUEUED→TAKEN/REJECTED), `reply` зовёт её владелец вне лока. Лок не держится поверх `action`,
  `reply`, `should_reject`. `reply` исполненной операции зовётся до снятия её ключей: ответы операций с
  пересекающимися ключами уходят в порядке подачи.
- `max_pending=64` считает только ждущие операции (решение лида). Потолок транспорта — system-очередь процесса
  `maxsize: 100` (`process_manager_process.py:66`, `process_launch_config.py:15`); худший всплеск PM
  (start-all/restart-all на 8 процессах × start + relay + telemetry ≈ 24, плюс `topology.apply` / `wire.*`) < 32 —
  запас ×2, и ниже 100.
- `max_workers=4`: R2 нужен ≥ 2; рабочие ждут на `Condition.wait(0.1)` и CPU не берут. Это только умолчание: 1.9b
  задаёт его для исполнителя готовности явно, не меньше числа детей (ADR-PMM-024: поток на неготового ребёнка).
- Рабочие — постоянные SYSTEM-воркеры `keyed-<name>-<i>` (`WorkerManager.create_worker`, `auto_start=True`,
  `restart_on_failure=False`, LOOP): `pause_all` и GUI worker CRUD их не трогают; на эпизод не создаются (имя
  уникально, STOPPED остаётся в реестре). Имя занято → `ValueError`. `stop_event` от `stop_all_workers` →
  `request_stop()` всего исполнителя, иначе очередь осталась бы без ответа.
- Повторный вход (`submit` из `action`): ключ ⊆ ключа текущей операции (при `serial` — любой) → на месте, часть
  родителя; иначе обычная постановка. Признак «внутри операции» — thread-local ключ на время любого `action` этого
  исполнителя (рабочим и на месте при `inline_if_idle`).
- Закрытие — `Stoppable`: `request_stop()` снимает очередь (`system_stopping`), `join_until(deadline)` ждёт текущие
  операции и выход рабочих, `False` + WARNING с именами операций; `shutdown = request_stop + join_until`.

**Отвергнуто.** «deque на ключ» как в ADR-PMM-024 (дедлок `{a,b}` при одном рабочем; `None` не задерживает новые
ключи). Поток на операцию (нет потолка и join). `WorkerPoolExecutor` (нет ключей; план кадров). Блокирующий `submit`
на потолке (приёмный поток ждал бы — ровно L-9).

**Следствия.** PM в 1.9a не меняется (ни одна команда не помечена). 1.9b: `_run_when_child_ready` — тонкая обёртка
над `submit(inline_if_idle=True)`, исполнитель — во владении `Scope` PM.

**Reversible:** yes (новый файл; до 1.9b потребитель — только `CommandManager` через протокол).
**Refs:** `plans/lifecycle-stop-ownership/tasks/T1.9a.md` (D1, D2), ADR-PMM-024, ADR-CMD-006,
`tests/test_keyed_executor_acceptance.py`, `tests/test_keyed_executor_hazards.py`.
