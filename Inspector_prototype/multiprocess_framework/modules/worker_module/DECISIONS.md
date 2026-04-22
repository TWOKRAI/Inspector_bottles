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
