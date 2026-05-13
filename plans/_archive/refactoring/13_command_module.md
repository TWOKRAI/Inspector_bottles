# Plan: Рефакторинг `command_module` (#12)

> **Статус:** done  
> **Дата:** 2026-04-09  
> **Исполнитель:** Cursor Composer v2  
> **Ревью:** Claude Opus 4.6  
> **Ссылки:** [00_overview.md](00_overview.md) · [ARCHITECTURE.md §6.12](../../multiprocess_framework/ARCHITECTURE.md)

---

## Context

`command_module` (#12) — тонкий фасад над `dispatch_module`, предоставляющий семантику «команда» (register_command / handle_command) поверх универсального Dispatcher. Зависит только от `dispatch_module` (#3) и `base_manager` (#1).

Модуль в хорошем состоянии (~8.5/10): 34 теста зелёные, чистый код, README по эталону. Но есть пробелы в документации (нет DECISIONS.md, §6.12 TODO), мёртвый код и неподключённый интерфейс.

**Цель из 00_overview.md:** "Оставить как самостоятельный. README объясняет разницу с `dispatch_module`."

**Сложность:** 1.5/5 — cleanup мёртвого кода + документация. **Публичный API НЕ меняется.**

### Архитектурное позиционирование: CommandManager vs CRM vs Dispatcher

Три уровня абстракции над `Dispatcher`:

| Класс | Паттерн | Что регистрирует | Что маршрутизирует | Каналы | Буфер |
|-------|---------|------------------|--------------------|--------|-------|
| `Dispatcher` | Универсальный | key → handler | Любые dict | Нет | Нет |
| `CommandManager` | Фасад над Dispatcher | command name → handler | Командные сообщения | Нет | Нет |
| `ChannelRoutingManager` | Менеджер каналов | key → IChannel.write | Данные в каналы (файлы, очереди) | ChannelRegistry | IBufferStrategy |

**CommandManager НЕ является и НЕ должен быть наследником CRM.** CRM — для маршрутизации данных в каналы (I/O). CommandManager — для маршрутизации команд к обработчикам (функции).

**Общее:** оба используют Dispatcher через композицию и оба наследуют BaseManager + ObservableMixin.

### Sync vs Async: полная картина dispatch pipeline

Все 5 «похожих» модулей используют `Dispatcher`, но на разных уровнях абстракции и с разной моделью исполнения:

| Компонент | Sync/Async | Буфер | Потоки | Dispatcher |
|---|---|---|---|---|
| **Dispatcher** | Sync | Нет | 0 | Сам (4 стратегии) |
| **CommandManager** | **Sync** | **Нет** | **0** | 1 × Dispatcher (композиция) |
| **CRM** | Configurable | IBufferStrategy (pluggable) | Зависит от буфера | 1 × Dispatcher |
| **LoggerManager** (CRM) | Async (batch) | BatchBuffer (deque + timer) | 1 (timer thread) | 1 × Dispatcher (от CRM) |
| **RouterManager** (CRM) | Async send + Sync receive | AsyncSender (PriorityQueue) | 2+ (sender, receiver, message_processor) | **2 × Dispatcher** (channel + message) |

**CommandManager — синхронный by design.** Полный путь IPC-команды в процессе:

```
[message_processor thread, 10ms poll loop]
  1. router.receive(channel_types=['system'])           ← poll IPC-очередей
  2.   → message_dispatcher.dispatch(msg, key="command") ← Dispatcher #1 (RouterManager)
  3.     → bridge: command_manager.handle_command(msg)    ← мост из ProcessLifecycle
  4.       → dispatcher.dispatch(msg, key="command")      ← Dispatcher #2 (CommandManager)
  5.         → actual_handler(data)                       ← e.g. _cmd_set_fps()
  6.         → return result                              ← sync
```

**Тройной dispatch (шаги 2→3→4) — O(1) dict lookup × 3, не bottleneck.** Команды по дизайну — быстрые управляющие сигналы (set_fps, start_capture, get_parameters). Async-буферизация уже обеспечена на уровне RouterManager (AsyncSender для исходящих, message_processor thread для входящих). CommandManager работает ВНУТРИ потока message_processor и не нуждается в собственном буфере.

**Если handler долгий** (e.g. тяжёлый db.query), правильный паттерн: handler ставит задачу в worker thread через WorkerManager, а не блокирует message_processor. Это ответственность прикладного кода, не фреймворка.

**RouterManager.message_dispatcher — встроенный аналог CommandManager.** Именно в него `ProcessLifecycle._register_commands_with_router()` мостит команды. Но message_dispatcher — generic (роутит по command/type), а CommandManager добавляет семантику (register_command, handle_command, get_commands, tags, metadata, stats).

### Использование в прототипе

6 процессов-наследников ProcessModule активно используют `self.command_manager.register_command()`:
- `CameraProcess` — 16 команд (set_fps, open, close, start/stop_capture, ...)
- `RenderProcess` — 5 команд (set_draw_contours, set_show_original, ...)
- `ProcessorProcess` — 3 команды (set_color_range, set_min/max_area)
- `DatabaseProcess` — 5 команд (query, execute, insert, ...)
- `RobotSimulatorProcess` — 1 команда (reject_item)

Интеграция с RouterManager: `ProcessLifecycle._register_commands_with_router()` мостит все зарегистрированные команды в `router.message_dispatcher`, чтобы команды из IPC-очередей (например, от GUI) доходили до обработчиков.

---

## 1. Текущее состояние

| Метрика | Значение |
|---------|----------|
| Файлов .py (без tests) | 9 |
| LOC (без tests) | 778 |
| Тест-файлов | 3 |
| Тестов (pytest) | 34 passed |
| command_manager.py LOC | 392 |

### Проблемы

| # | Проблема | Серьёзн. | Шаг |
|---|----------|----------|-----|
| P1 | `CommandManager` не реализует `ICommandManager` — интерфейс определён, но не подключён к классу | Средняя | 1 |
| P2 | Legacy backward-compat kwargs в `__init__`: `logger_manager`, `error_manager`, `statistics_manager`, `enable_logging`, `enable_error_tracking`, `enable_statistics` — 0 внешних вызовов через старый API | Средняя | 2 |
| P3 | Dead `except + raise` в `handle_command` (строки 267-273) — `Dispatcher.dispatch()` ловит все исключения, except-блок никогда не выполняется | Низкая | 3 |
| P4 | Нет `DECISIONS.md` | Средняя | 4 |
| P5 | §6.12 в ARCHITECTURE.md — TODO-заглушка | Средняя | 4 |
| P6 | Нет строки command_module в главном `DECISIONS.md` | Средняя | 4 |
| P7 | `self.process_name` backward-compat alias — 1 строка, используется в тесте и `get_stats()` | Низкая | Оставить (ADR) |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline (read-only)

```bash
 && python -m pytest multiprocess_framework/modules/command_module/tests -v
find multiprocess_framework/modules/command_module -name "*.py" ! -path "*/tests/*" ! -path "*/__pycache__/*" -exec wc -l {} + | sort -rn
```

**Ожидаемый результат:** 34 passed, 9 файлов / 778 LOC.

---

### Шаг 1 — Подключить ICommandManager к CommandManager (P1)

**Файлы:**
- ПРАВКА `core/command_manager.py` — добавить `ICommandManager` в наследование

**Действия:**

1. Добавить импорт (строка 13, после импорта Dispatcher):
```python
from ..interfaces import ICommandManager
```

2. Изменить сигнатуру класса (строка 17):
```python
# Было:
class CommandManager(BaseManager, ObservableMixin):
# Стало:
class CommandManager(BaseManager, ObservableMixin, ICommandManager):
```

**Обоснование:** `ICommandManager` определяет контракт (`register_command`, `handle_command`, `get_commands`, `get_command_info`, `get_commands_by_tag`, `update_command_metadata`, `update_command_tags`, `overwrite_command`). CommandManager уже реализует ВСЕ эти методы — просто не объявляет интерфейс. BaseCommandManager намеренно НЕ реализует ICommandManager — это lightweight-класс для тестов с подмножеством API.

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/command_module/tests -v
```

**Коммит:**
```
refactor(command_module): step 1 — wire ICommandManager to CommandManager

- Add ICommandManager to CommandManager class hierarchy
- CommandManager already implements all ICommandManager methods
- BaseCommandManager intentionally omits ICommandManager (lightweight subset)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 2 — Удалить legacy backward-compat kwargs из __init__ (P2)

**Файлы:**
- ПРАВКА `core/command_manager.py`

**Действия:**

1. Удалить параметры из `__init__` (строки 56-62):
```python
# УДАЛИТЬ:
        # Обратная совместимость со старым API
        logger_manager: Optional[Any] = None,
        error_manager: Optional[Any] = None,
        statistics_manager: Optional[Any] = None,
        enable_logging: bool = True,
        enable_error_tracking: bool = True,
        enable_statistics: bool = True,
```

2. Удалить блок маппинга legacy kwargs (строки 88-103):
```python
# УДАЛИТЬ:
        # Поддержка старого API для обратной совместимости
        if managers is None:
            managers = {}
            if logger_manager:
                managers['logger'] = logger_manager
            if error_manager:
                managers['error'] = error_manager
            if statistics_manager:
                managers['statistics'] = statistics_manager
        
        if config is None:
            config = {
                'logger': enable_logging,
                'error': enable_error_tracking,
                'statistics': enable_statistics
            }
```

3. Упростить инициализацию ObservableMixin (после удаления):
```python
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config=config or {}
        )
```

4. Обновить docstring `__init__` — убрать описание удалённых параметров.

**Верификация:** единственный вызывающий код — `process_managers.py:_create_command_manager()` — уже использует новый API (`managers={}`, `config={}`). В тестах используется `CommandManager("test_process")` без legacy-kwargs.

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/command_module/tests -v
 && python -m pytest multiprocess_framework/modules/process_module/tests -v --tb=short
```

**Коммит:**
```
refactor(command_module): step 2 — remove legacy backward-compat kwargs from __init__

- Remove logger_manager, error_manager, statistics_manager params
- Remove enable_logging, enable_error_tracking, enable_statistics params
- Remove legacy-to-new API mapping block
- Only caller (ProcessManagers._create_command_manager) uses new API (managers={}, config={})
- Tests use positional manager_name only

Delta: command_manager.py 392 → ~360 LOC

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 3 — Удалить dead except+raise в handle_command (P3)

**Файлы:**
- ПРАВКА `core/command_manager.py`

**Действия:**

Заменить `handle_command` (строки 231-273) упрощённой версией. `Dispatcher.dispatch()` ВСЕГДА возвращает dict (даже при исключениях), поэтому внешний try/except мёртв:

```python
    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.

        Args:
            message (Dict): Сообщение для обработки. Ожидается поле 'command' с именем команды.

        Returns:
            Any: Результат выполнения команды или {"status": "error", "reason": "..."}
        """
        start_time = time.time()
        command_name = message.get("command", "unknown")
        
        self._log_debug(f"Handling command: {command_name}", module="command_manager", command=command_name)
        self._record_metric("command_manager.command.execution.attempts", tags={"command": command_name})
        
        result = self.dispatcher.dispatch(message, key_field="command", data_field="data")
        
        duration = time.time() - start_time
        if isinstance(result, dict) and result.get("status") == "error":
            self._log_warning(f"Command '{command_name}' failed: {result.get('reason')}", module="command_manager")
            self._record_metric("command_manager.command.execution.errors", tags={"command": command_name})
        else:
            self._log_info(f"Command '{command_name}' executed successfully in {duration:.3f}s", module="command_manager")
            self._record_metric("command_manager.command.execution.success", tags={"command": command_name})
        
        self._record_timing("command_manager.command.execution.duration", duration, tags={"command": command_name})
        return result
```

**Обоснование:** Dispatcher.dispatch() содержит try/except, возвращающий `{"status": "error", "reason": "Dispatch failed: ..."}` для ЛЮБОГО исключения. Поэтому CommandManager.handle_command() НИКОГДА не получает исключение — только dict. Подтверждено в STATUS.md: "Dead code: `raise` в `except`-блоке `handle_command`".

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/command_module/tests -v
```

Тест `test_handle_command_handler_exception_returns_error` продолжит работать — он проверяет `result["status"] == "error"`, что возвращается Dispatcher.

**Коммит:**
```
refactor(command_module): step 3 — remove dead except+raise in handle_command

- Dispatcher.dispatch() catches all exceptions internally
- CommandManager's except block was unreachable dead code
- Confirmed by STATUS.md: "Dead code: raise in except"
- Test test_handle_command_handler_exception_returns_error still passes

Delta: command_manager.py ~360 → ~345 LOC

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 4 — Документация: DECISIONS.md, §6.12, глобальный индекс (P4, P5, P6)

**Файлы:**
- СОЗДАТЬ `modules/command_module/DECISIONS.md` — 5 ADR (168–172)
- ПРАВКА `ARCHITECTURE.md` строка 504 — заполнить §6.12
- ПРАВКА `DECISIONS.md` — строка command_module в индексе

#### DECISIONS.md (создать)

```markdown
# command_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-168: CommandManager реализует ICommandManager

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `ICommandManager(IBaseManager, ABC)` определён в `interfaces.py`, но `CommandManager` не объявлял наследование от него. Все методы интерфейса уже были реализованы.  
**Решение:** Добавить `ICommandManager` в сигнатуру `CommandManager`. `BaseCommandManager` намеренно НЕ реализует `ICommandManager` — это lightweight-класс для тестов с подмножеством API (нет `get_commands_by_tag`, `update_command_metadata`, `update_command_tags`).  
**Последствия:** Формальный контракт. Потребители (ProcessModule) могут типизировать через ICommandManager.

## ADR-169: Удаление legacy backward-compat kwargs

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `CommandManager.__init__()` принимал `logger_manager`, `error_manager`, `statistics_manager`, `enable_logging`, `enable_error_tracking`, `enable_statistics` для совместимости с предыдущим API. Grep подтвердил: единственный вызывающий код (`ProcessManagers._create_command_manager()`) использует новый API через `managers={}` и `config={}`. 0 внешних вызовов через legacy kwargs.  
**Решение:** Удалить legacy kwargs и блок маппинга (~30 LOC).  
**Последствия:** Упрощение __init__. Если пользовательский код вне фреймворка использовал старый API — потребуется миграция на `managers={}`.

## ADR-170: Удаление dead except+raise в handle_command

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `handle_command()` оборачивал `dispatcher.dispatch()` в try/except с `raise` на конце. Но `Dispatcher.dispatch()` внутри себя ловит ВСЕ исключения и возвращает `{"status": "error", "reason": "Dispatch failed: ..."}`. Except-блок в CommandManager никогда не выполнялся. Подтверждено в STATUS.md.  
**Решение:** Удалить try/except. Вызывать `dispatcher.dispatch()` напрямую и проверять результат.  
**Последствия:** Упрощение кода. Все 34 теста продолжают работать без изменений.

## ADR-171: Сохранение self.process_name как backward-compat alias

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `self.process_name = manager_name` (строка 86) — alias для обратной совместимости. Используется в `get_stats()` и тесте `test_initialization`.  
**Решение:** Сохранить alias. Аналогично ADR-161 (worker_module: self.name alias). Причины:
- Минимальная стоимость (1 строка)
- Используется в тесте и get_stats()
- Прототип может использовать в пользовательском коде  
**Последствия:** Alias остаётся. При унификации именования менеджеров — ревизия.

## ADR-172: CommandManager vs ChannelRoutingManager — разные паттерны, синхронный by design

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
```

#### §6.12 (заменить строку 504 в ARCHITECTURE.md)

```markdown
### 6.12 `command_module` — фасад для обработки команд

**Роль:** Тонкий фасад над `dispatch_module` с семантикой «команда». Предоставляет `register_command(name, handler)` / `handle_command(msg)` вместо низкоуровневых `register_handler` / `dispatch`. Зависит от `dispatch_module` (#3) и `base_manager` (#1).

**CommandManager** (BaseManager + ObservableMixin + ICommandManager, ~345 LOC) — фасад: внутренний `Dispatcher` для маршрутизации `msg["command"]` → handler.  
**BaseCommandManager** (~55 LOC) — lightweight конкретный класс для тестов и простых случаев. Только EXACT_MATCH, без ObservableMixin.  
**CommandAdapter** (~109 LOC) — тонкая обёртка для ProcessModule, добавляет `execute_via_message()`.  
**CommandManagerConfig** (SchemaBase) — плоская схема для реестра и UI.

```
CommandManager(BaseManager, ObservableMixin, ICommandManager)
    ├── register_command(name, handler) → dispatcher.register_handler()
    ├── handle_command(msg) → dispatcher.dispatch(msg, key="command")
    ├── get_commands() / get_command_info() / get_commands_by_tag()
    ├── overwrite_command() / update_command_metadata() / update_command_tags()
    └── dispatcher: Dispatcher (composition, all 4 strategies available)
```

**Не путать с CRM:** CommandManager маршрутизирует команды **к функциям**. CRM маршрутизирует данные **в каналы** (файлы, очереди). Общее — оба используют Dispatcher через композицию (ADR-172).

**Синхронный by design (ADR-172).** Async-буферизация обеспечена выше — RouterManager (AsyncSender + message_processor thread). CommandManager работает внутри потока message_processor. Команды — быстрые управляющие сигналы (set_fps, start_capture). Тройной dispatch path: `message_dispatcher → CommandManager → Dispatcher` — O(1) × 3, не bottleneck. Тяжёлые handlers → worker thread, не async command.

Интеграция: `ProcessLifecycle._register_commands_with_router()` мостит команды в `router.message_dispatcher`, чтобы IPC-сообщения (из GUI) доходили до command handlers. `message_dispatcher` — встроенный generic аналог, CommandManager добавляет семантику (tags, metadata, timing stats).

Ключевые решения (ADR-168…172):
- **ICommandManager подключён** к CommandManager (ADR-168)
- **Нет наследования от CRM, синхронный by design** — разные паттерны (ADR-172)
- **Legacy kwargs удалены** — единственный caller использует новый API (ADR-169)

📖 [`modules/command_module/README.md`](modules/command_module/README.md) · [`modules/command_module/DECISIONS.md`](modules/command_module/DECISIONS.md)
```

#### Строка в главный DECISIONS.md (после process_module):

```
| `command_module` | [`modules/command_module/DECISIONS.md`](modules/command_module/DECISIONS.md) | Command & Work | ADR-168…172 (ICommandManager wiring, legacy kwargs removal, dead except removal, process_name alias, CRM distinction) |
```

**Коммит:**
```
docs(command_module): step 4 — create DECISIONS.md (ADR-168..172), fill §6.12

- ADR-168: CommandManager implements ICommandManager
- ADR-169: Legacy backward-compat kwargs removed
- ADR-170: Dead except+raise removed from handle_command
- ADR-171: self.process_name kept as backward-compat alias
- ADR-172: CommandManager vs CRM — distinct patterns (not a CRM descendant)
- ARCHITECTURE.md §6.12 filled
- Global DECISIONS.md index updated

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 5 — Финальная валидация и обновление метрик

**Файлы:**
- ПРАВКА `STATUS.md` — строка в историю версий
- ПРАВКА `00_overview.md` строка 97 — `files_after`, `loc_after`, `tests_after`

**Обновление STATUS.md** — добавить строку:
```
| 2026-04-09 | Systematic refactoring: ICommandManager wired, legacy kwargs removed, dead except removed, DECISIONS.md (ADR-168..172), §6.12 | 8 |
```

**Обновление 00_overview.md строка 97:**
```
| 12 | `command_module`             |   9   |   778  |   3   |  TODO  | TODO | 9 | ~746 | 3 (34 passed) |
```

**Проверка (полная):**
```bash
 && python -m pytest multiprocess_framework/modules/command_module/tests -v
 && python -m pytest multiprocess_framework/modules/process_module/tests -v --tb=short
 && python scripts/run_framework_tests.py
```

**Коммит:**
```
refactor(command_module): step 5 — final validation, update STATUS.md and 00_overview.md

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## 3. Целевые метрики

| Метрика | До | После |
|---------|-----|-------|
| Файлов .py (без tests) | 9 | 9 |
| LOC .py (без tests) | 778 | ~746 |
| command_manager.py | 392 | ~360 |
| Тестов | 34 passed | 34 passed |
| ICommandManager | не подключён | подключён |
| Legacy kwargs | 6 параметров + 15 LOC маппинг | удалены |
| Dead except | 7 LOC | удалены |
| DECISIONS.md | нет | ADR-168…172 |
| §6.12 | TODO | заполнено |

---

## 4. Что НЕ делать

1. **НЕ** наследовать CommandManager от ChannelRoutingManager — разные паттерны (ADR-172)
2. **НЕ** удалять BaseCommandManager — используется в тестах как lightweight альтернатива
3. **НЕ** удалять `self.process_name` — используется в тестах и get_stats() (ADR-171)
4. **НЕ** делать `self.dispatcher` приватным (`self._dispatcher`) — документировано как публичный атрибут в README, используется в тестах
5. **НЕ** менять CommandManagerConfig — чистый SchemaBase, без проблем
6. **НЕ** менять CommandAdapter — стабильный код, протестирован
7. **НЕ** менять тесты — 34/34 зелёные
8. **НЕ** менять `_register_commands_with_router()` в process_lifecycle.py — это мост между command_module и router_module, вне скоупа command_module

---

## 5. Кросс-модульные изменения

| Модуль | Файл | Изменение |
|--------|------|-----------|
| command_module | `core/command_manager.py` | +ICommandManager, удалить legacy kwargs, удалить dead except |
| command_module | `DECISIONS.md` | СОЗДАТЬ (ADR-168..172) |
| command_module | `STATUS.md` | Обновить |
| multiprocess_framework | `ARCHITECTURE.md` | §6.12 (строка 504) |
| multiprocess_framework | `DECISIONS.md` | Строка command_module |
| plans/refactoring | `00_overview.md` | Строка #12 |

---

## 6. Definition of Done

- [x] `CommandManager` реализует `ICommandManager`
- [x] Legacy backward-compat kwargs удалены из `__init__`
- [x] Dead `except + raise` удалён из `handle_command`
- [x] `DECISIONS.md` создан (ADR-168…172)
- [x] `ARCHITECTURE.md` §6.12 заполнен
- [x] Главный `DECISIONS.md` содержит строку command_module
- [x] `STATUS.md` обновлён
- [x] `00_overview.md` метрики after заполнены
- [x] 34 теста command_module passed
- [x] Тесты process_module passed (нет регрессий)

---

## 7. Ключевые файлы

```
multiprocess_framework/
├── ARCHITECTURE.md                              ← строка 504 (§6.12)
├── DECISIONS.md                                 ← индекс
└── modules/command_module/
    ├── core/command_manager.py                   ← +ICommandManager, удалить legacy kwargs, dead except (шаги 1-3)
    ├── core/base_command_manager.py              ← НЕ ТРОГАТЬ
    ├── adapters/command_adapter.py               ← НЕ ТРОГАТЬ
    ├── interfaces.py                            ← НЕ ТРОГАТЬ
    ├── configs/command_manager_config.py         ← НЕ ТРОГАТЬ
    ├── DECISIONS.md                             ← СОЗДАТЬ (шаг 4)
    └── STATUS.md                                ← обновить (шаг 5)

plans/refactoring/
├── 00_overview.md                               ← строка 97
└── 13_command_module.md                         ← этот план
```
