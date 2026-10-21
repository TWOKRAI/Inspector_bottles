# command_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-CMD-001 (was ADR-168): CommandManager реализует ICommandManager

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ICommandManager(IBaseManager, ABC)` определён в `interfaces.py`, но `CommandManager` не объявлял наследование от него. Все методы интерфейса уже были реализованы.  
**Решение:** Добавить `ICommandManager` в сигнатуру `CommandManager`. `BaseCommandManager` намеренно НЕ реализует `ICommandManager` — это lightweight-класс для тестов с подмножеством API (нет `get_commands_by_tag`, `update_command_metadata`, `update_command_tags`).  
**Последствия:** Формальный контракт. Потребители (ProcessModule) могут типизировать через ICommandManager.

## ADR-CMD-002 (was ADR-169): Удаление legacy backward-compat kwargs

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `CommandManager.__init__()` принимал `logger_manager`, `error_manager`, `statistics_manager`, `enable_logging`, `enable_error_tracking`, `enable_statistics` для совместимости с предыдущим API. Grep подтвердил: единственный вызывающий код (`ProcessManagers._create_command_manager()`) использует новый API через `managers={}` и `config={}`. 0 внешних вызовов через legacy kwargs.  
**Решение:** Удалить legacy kwargs и блок маппинга (~30 LOC).  
**Последствия:** Упрощение __init__. Если пользовательский код вне фреймворка использовал старый API — потребуется миграция на `managers={}`.

## ADR-CMD-003 (was ADR-170): Удаление dead except+raise в handle_command

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `handle_command()` оборачивал `dispatcher.dispatch()` в try/except с `raise` на конце. Но `Dispatcher.dispatch()` внутри себя ловит ВСЕ исключения и возвращает `{"status": "error", "reason": "Dispatch failed: ..."}`. Except-блок в CommandManager никогда не выполнялся. Подтверждено в STATUS.md.  
**Решение:** Удалить try/except. Вызывать `dispatcher.dispatch()` напрямую и проверять результат.  
**Последствия:** Упрощение кода. Все 34 теста продолжают работать без изменений.

## ADR-CMD-004 (was ADR-171): Сохранение self.process_name как backward-compat alias

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `self.process_name = manager_name` — alias для обратной совместимости. Используется в `get_stats()` и тесте `test_initialization`.  
**Решение:** Сохранить alias. Аналогично ADR-161 (worker_module: self.name alias). Причины:
- Минимальная стоимость (1 строка)
- Используется в тесте и get_stats()
- Прототип может использовать в пользовательском коде  
**Последствия:** Alias остаётся. При унификации именования менеджеров — ревизия.

## ADR-CMD-005 (was ADR-172): CommandManager vs ChannelRoutingManager — разные паттерны, синхронный by design

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Оба класса используют `Dispatcher` (композиция) и наследуют `BaseManager + ObservableMixin`. Возникают два вопроса: (1) не должен ли CommandManager быть наследником CRM? (2) не нужна ли CommandManager собственная async-буферизация?  

**Решение по наследованию:** НЕТ. Это разные паттерны:
- **CRM** = ChannelRegistry + Dispatcher + Buffer → маршрутизация данных **в каналы** (файлы, очереди, сокеты, Prometheus). Наследники: LoggerManager, RouterManager, ErrorManager.
- **CommandManager** = Dispatcher → маршрутизация команд **к обработчикам** (функции). Нет каналов, нет буферов, нет ChannelRegistry.

CRM добавляет channel lifecycle (register/unregister/close), буферизацию (batch/async), normalize_config(). CommandManager ничего из этого не использует.

**Решение по async:** НЕТ. CommandManager — синхронный by design. Обоснование:
1. **Async уже обеспечен выше:** RouterManager (AsyncSender для исходящих, message_processor thread для входящих) буферизует на уровне IPC. CommandManager работает ВНУТРИ потока message_processor.
2. **Команды — быстрые сигналы:** set_fps, start_capture, get_parameters — O(μs). Добавление async для таких операций — overhead без выигрыша.
3. **Тяжёлые handlers — ответственность прикладного кода:** если handler долгий (db.query), он должен поставить задачу в worker thread через WorkerManager, а не блокировать message_processor.
4. **Тройной dispatch (message_dispatcher → CommandManager → Dispatcher) — O(1) × 3:** три dict lookup, суммарно ~1μs. Не bottleneck.

**RouterManager.message_dispatcher — встроенный аналог CommandManager.** В него `ProcessLifecycle._register_commands_with_router()` мостит все зарегистрированные команды. Но message_dispatcher — generic (роутит по command/type), а CommandManager добавляет семантику (register_command, handle_command, get_commands, tags, metadata, timing stats).

**Последствия:** CommandManager остаётся отдельным синхронным модулем без собственного буфера. Интеграция с RouterManager через мост `_register_commands_with_router()` — осознанная. Async-расширение CommandManager не планируется.

## ADR-CMD-006: развилка «исполнить на месте / отдать исполнителю» по регистрации команды (Task 1.9a)

**Статус:** accepted (2026-10-21, Task 1.9a плана `lifecycle-stop-ownership`; решение владельца 2026-10-20 — D1a).
Уточняет ADR-CMD-005: своих потоков у `CommandManager` по-прежнему нет — исполнитель передаётся снаружи.

**Контекст.** Только `CommandManager` знает регистрацию команды, поэтому развилку делает он, а не роутер (CTO р.2).
Граница «сам / отдать» — свойство обработчика (ждёт другой процесс или нет), не вид почты.

**Решение.**
- `register_command(..., executor=None, key_from=None, targets=None)` — только новые необязательные kwarg, прежние
  аргументы и умолчания не меняются. Отказ (`False` + WARNING, команда не зарегистрирована): `executor` не ровно с
  одним из `key_from` / `targets="all"`; `targets` вне `{None, "all"}`; `key_from` / `targets` без `executor`;
  `executor` при `metadata.manages_own_reply` (no-op `reply` проглотил бы отказы `system_stopping` / `executor_busy`).
- Реестр исполнителей `_executors` — вне `metadata` (`get_handler_info` отдаёт `metadata` по ссылке). В `metadata`
  (копия словаря вызывающего) — только строки `executor` (имя), `key_from`, `targets`.
- Ключ извлекает приёмник: `targets="all"` → `None`; `key_from` → `frozenset({data[key_from]})`. Значение не непустая
  `str` → возврат `{"success": False, "error": "key_missing", "command": <имя>}` + WARNING без значения поля;
  обработчик и `reply` не вызываются, и с `reply`, и без (решение лида); роутер отвечает на это как на любой
  синхронный результат.
- `handle_command(message, *, reply=None)` (и `ICommandManager`): команда с исполнителем и `reply` → `action` =
  `dispatcher.dispatch` в обёртке (исключение → `{"status": "error", "reason": ...}`, как у роутера); весь блок после
  диспетчеризации (лог, метрики, длительность) — после исполнения, на потоке исполнителя; `execution.attempts` — при
  подаче; возврат — сентинел `DEFERRED` (экспорт `command_module`). Без `reply` (консоль, тесты, вложенные вызовы) →
  исполнение на месте + один WARNING на имя «исполнено вне очереди ключа»; без `reply` `DEFERRED` не возвращается
  никогда.
- `overwrite_command` снимает исполнителя — команда снова синхронная. `update_command_metadata`, стёршая строку
  `executor`, ведёт к исполнению на месте + WARNING: роутер не передаёт `reply` (ADR-RTR-015), `DEFERRED` не утекает.

- Отказ исполнителя (`system_stopping` / `executor_busy`, `action` не стартовала) — тоже исход команды: CM оборачивает
  `reply` и проводит отказ через блок после диспетчеризации как ошибку (WARNING + метрика `errors`), без метрики
  длительности — исполнения не было (ревью р.1).

**Отвергнуто.** Развилка в роутере (решение владельца 2026-10-20). Объект исполнителя в `metadata` (утёк бы в карточки
и по ссылке). `DEFERRED` без `reply` (инициатор не получил бы ответа). Молчаливый `key=None` при пропавшем поле
(команда встала бы за всеми операциями).

**Следствия.** Строка сигнатуры `handle_command` в `command_manager.py` и `interfaces.py` изменилась (добавлен
keyword-only `reply`) — подделки CM и `BaseCommandManager` не тронуты: роутер зовёт их по-старому. Вывод `executor` /
`key_from` / `targets` в `introspect.capabilities` — не в 1.9a.

**Reversible:** yes (убрать kwarg и реестр; ни одна команда в 1.9a не помечена).
**Refs:** `plans/lifecycle-stop-ownership/tasks/T1.9a.md` (D3), ADR-WRK-005, ADR-RTR-015,
`tests/test_command_executor_fork_acceptance.py`, `tests/test_command_executor_fork_hazards.py`.
