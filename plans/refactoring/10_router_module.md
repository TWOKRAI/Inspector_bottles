# Refactoring plan: `router_module` (module #9)

> **Статус:** Выполнено (2026-04-09)  
> **Автор плана:** Claude (Opus 4.6), 2026-04-09  
> **Исполнитель:** Cursor Composer Agent v2  
> **Ревью:** Claude (Opus 4.6) — после реализации  
> **Ссылки:** [00_overview.md](plans/refactoring/00_overview.md) · [ARCHITECTURE.md](Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

`router_module` (#9) — масштабируемая маршрутизация IPC-сообщений. Зависит от #4 `channel_routing_module`, #7 `message_module`, #3 `dispatch_module`. Потребитель: #11 `process_module`.

CRM-миграция (Фаза 4 STATUS.md) завершена: RouterManager(ChannelRoutingManager), IMessageChannel(IChannel), _channel_registry из CRM. Но осталось: мёртвый код, thread-safety баг, нет DECISIONS.md, нет §6.9 в ARCHITECTURE.md, нет тестов адаптеров.

**Место в архитектуре «конструктора»:**
```
dispatch_module (Layer 0: чистая логика key→handler)
  ├── channel_routing_module (Layer 1a: + каналы + буферы + route→write)
  │     └── router_module (Layer 2: + AsyncSender + middleware + dual dispatchers)
  └── command_module (Layer 1b: + командная семантика, без каналов)
```
Анализ подтвердил: **дублирования между модулями нет.** `register_channel_handler` / `register_channel_scenario` — инфраструктура для Phase 8 (config-driven channels), аналог `command_manager.register_command()` (см. v2 прототип).

**Сложность:** ★★☆☆☆ — cleanup + documentation + tests, без изменения публичного API.

---

## 1. Текущее состояние и оценка

### Baseline метрики

| Метрика | Значение |
|---------|----------|
| Файлов (без tests) | 16 |
| LOC (без tests) | 1995 |
| `router_manager.py` | 624 LOC |
| Тест-файлов | 2 |
| Тест LOC | 968 (798 + 166) |
| STATUS.md этап | 4/8 (CRM-миграция завершена) |

### LOC-разбивка (top files)

```
624  core/router_manager.py         ← основной кандидат на сжатие
228  interfaces.py
156  core/_receiver.py
154  core/_channel_registry.py      ← МЁРТВЫЙ КОД (подтверждено)
154  adapters/router_adapter.py
152  adapters/schema_adapter.py
150  channels/queue_channel.py
138  core/_sender.py
 80  core/_middleware.py
 71  channels/base_channel.py
 28  __init__.py
 27  configs/router_manager_config.py
```

### Оценка состояния (0–10)

| Критерий | Балл | Обоснование |
|----------|------|-------------|
| Код | 7 | `router_manager.py` 624 LOC; мёртвый `_channel_registry.py` (154 LOC); `_stats` не thread-safe |
| Тесты | 5 | 798+166 LOC, но нет тестов RouterAdapter, SchemaAdapter, _attach_logger, channel_types |
| Документация | 4 | README хороший, но нет DECISIONS.md, нет §6.9 в ARCHITECTURE.md |
| Связанность (CRM) | 8 | CRM-интеграция завершена, наследование чистое |
| Дублирование | 7 | _channel_registry.py — мёртвая копия CRM-класса |
| Работоспособность | 7 | Отсутствует correlation_id, ErrorManager, StatsManager, config-driven setup |
| **Среднее** | **6.3** | Крепкий фундамент от CRM-миграции, но значительный технический долг |

### Контекст из v2 прототипа

Анализ `multiprocess_prototype_v2/` показывает будущий паттерн config-driven setup:
- Каналы создаются из `queues` dict в `ProcessConfigBase` (→ `proc_assembly.py:build_proc_dict()`)
- Команды регистрируются per-process через `command_manager.register_command()`
- Routing — декларативный: `COMMAND_TO_REGISTER_KEY` dict → `RoutedCommandSender`
- `channel_types` фильтрация активно используется (`receive_message(channel_types=["data"])`)

**Следствие:** `register_channel_handler`, `register_channel_scenario`, `cleanup()` — инфраструктура для Phase 8 (config-driven channels). **НЕ удалять.**

### Выявленные проблемы

| # | Проблема | Серьёзность | Шаг |
|---|----------|------------|-----|
| P1 | `core/_channel_registry.py` (154 LOC) — мёртвый код. Не импортируется нигде. CRM предоставляет `_channel_registry`. | Высокая | 1 |
| P2 | `_stats` dict не thread-safe: `+=` из main и AsyncSender thread | Высокая | 2 |
| P3 | `router_manager.py` 624 LOC — можно ужать (docstring, suffix logic) | Средняя | 3 |
| P4 | Нет DECISIONS.md (ADR-153..158) | Средняя | 4 |
| P5 | Нет тестов RouterAdapter, SchemaAdapter | Высокая | 5 |
| P6 | Нет §6.9 в ARCHITECTURE.md | Средняя | 6 |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline Audit (read-only)

**Файлы:** нет изменений.

**Действия:**
1. Запустить тесты: `cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v`
2. Подсчитать LOC: `find multiprocess_framework/modules/router_module -name "*.py" ! -path "*/tests/*" ! -path "*/__pycache__/*" -exec wc -l {} + | sort -rn`
3. Подтвердить мёртвый код: `grep -rn "from ._channel_registry\|from ..core._channel_registry" multiprocess_framework/modules/router_module/` → 0 совпадений
4. Подтвердить 0 потребителей: `grep -rn "register_channel_handler\|register_channel_scenario" multiprocess_framework/ --include="*.py" | grep -v "router_module"`→ 0 совпадений

**Коммит:** нет (checkpoint-аудит).

---

### Шаг 1 — Удалить мёртвый код (P1)

**Файлы:**
- УДАЛИТЬ `modules/router_module/core/_channel_registry.py` (154 LOC)
- ПРАВКА `modules/router_module/core/__init__.py` — убрать строку 10 (`_channel_registry.py — ChannelRegistry`)

**Важно: НЕ удалять:**
- `register_channel_handler()` — инфраструктура для config-driven channel setup (Phase 8)
- `register_channel_scenario()` — аналогично, нужен для сценарной маршрутизации
- `cleanup()` — стандартный alias-паттерн

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
refactor(router_module): step 1 — remove dead _channel_registry.py (154 LOC)

Step 1 — Dead code removal:
- Delete core/_channel_registry.py (dead after CRM migration, zero imports confirmed)
- RouterManager uses self._channel_registry from ChannelRoutingManager (CRM)
- Update core/__init__.py docstring

Delta: -154 LOC, source files 16 → 15

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 2 — Thread-safety fix для `_stats` (P5)

**Файлы:**
- ПРАВКА `modules/router_module/core/router_manager.py`
- ПРАВКА `modules/router_module/tests/test_router_manager.py`

**Действия в `router_manager.py`:**

1. Добавить `import threading` (если ещё нет).

2. В `__init__` добавить lock:
```python
self._stats_lock = threading.Lock()
```

3. Создать helper:
```python
def _inc_stat(self, key: str, value: int = 1) -> None:
    with self._stats_lock:
        self._stats[key] += value
```

4. Заменить все `self._stats["key"] += 1` на `self._inc_stat("key")`:
   - `_do_send()`: 5 мест (sent_attempted, middleware_dropped, errors ×2, sent_ok)
   - `receive()`: 3 места (middleware_dropped, received, errors)

5. В `get_stats()` читать под lock'ом:
```python
with self._stats_lock:
    stats_snap = dict(self._stats)
```

**Действия в тестах:**
Добавить тест в `TestThreadSafety`:
```python
def test_concurrent_stats_consistency(self):
    """Проверить что _stats корректны при параллельных send и send_async."""
    # Зарегистрировать канал, spawn N threads send() + N threads send_async()
    # После join: stats["sent_attempted"] == 2*N
```

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
fix(router_module): step 2 — thread-safe _stats with Lock

Step 2 — Fix P5:
- Add _stats_lock (threading.Lock) for atomic counter updates
- Add _inc_stat() helper replacing bare self._stats[key] += 1
- get_stats() reads _stats under lock
- Add test_concurrent_stats_consistency

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 3 — Slim `router_manager.py` (P6)

**Файлы:**
- ПРАВКА `modules/router_module/core/router_manager.py`

**Действия:**

1. **Сжать module docstring** (строки 1–21, 21 LOC → 5 LOC):
```python
"""
RouterManager — наследник ChannelRoutingManager.

Координирует AsyncSender (outgoing pipeline), AsyncReceiver (incoming poll),
channel_dispatcher (outgoing routing) и message_dispatcher (incoming handling).
"""
```

2. **Упростить suffix-логику в `_poll_all_channels`** (строки 309–312):
```python
# Было:
suffix = (
    ch_name[len(prefix):] if prefix and len(ch_name) > len(prefix)
    else ch_name.split("_")[-1] if "_" in ch_name else ch_name
)
# Стало:
suffix = ch_name.rsplit("_", 1)[-1] if "_" in ch_name else ch_name
```

3. **Inline переменные в `get_stats()`** — убрать промежуточные `_ch_handlers`, `_msg_handlers` (вызвать `.get_all_handlers()` inline).

4. **Переименовать секцию `# BACKWARD COMPAT`** → `# REGISTRATION API (config-driven, Phase 8)` — отражает будущую роль этих методов.

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
refactor(router_module): step 3 — slim router_manager.py (624 → ~590 LOC)

Step 3 — Code compression:
- Compress module docstring (21 → 5 LOC)
- Simplify _poll_all_channels suffix extraction
- Inline get_stats() intermediate variables
- Rename BACKWARD COMPAT section → REGISTRATION API (Phase 8)

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 4 — Создать DECISIONS.md (P7)

**Файлы:**
- СОЗДАТЬ `modules/router_module/DECISIONS.md`

**Содержимое:**

```markdown
# router_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary, ADR-013 CRM, ADR-015 AsyncSender)

## ADR-153: RouterManager наследует ChannelRoutingManager

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** RouterManager, LoggerManager, ErrorManager дублировали ChannelRegistry + Dispatcher.  
**Решение:** `RouterManager(ChannelRoutingManager)`. CRM даёт `_channel_registry`, `_dispatcher`, `_buffer` (не используется). RouterManager добавляет: AsyncSender (outgoing pipeline с middleware), AsyncReceiver, message_dispatcher.  
**Последствия:** Удалён локальный `_channel_registry.py` (мёртвый код после миграции). Единый паттерн для всех CRM-наследников.

## ADR-154: Name-returning handler pattern

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** CRM `register_route()` вызывает `channel.write()` напрямую. RouterManager'у нужен middleware pipeline перед send.  
**Решение:** `register_route("key", "channel_name")` регистрирует `lambda msg: "channel_name"`. `_resolve_channels()` получает строку → `_channel_registry.get(name)`.  
**Последствия:** Middleware всегда применяется. Dispatch возвращает имя канала, не результат отправки.

## ADR-155: Два dispatcher'а — channel + message

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Routing outgoing (в какой канал?) и handling incoming (какой handler?) — разные задачи.  
**Решение:** `channel_dispatcher` = CRM's `_dispatcher` (исходящие). `message_dispatcher` = отдельный Dispatcher (входящие).  
**Последствия:** Чёткое разделение; нет путаницы между routes и handlers.

## ADR-156: Thread-safe _stats с Lock

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `_do_send()` вызывается из main thread (sync `send()`) и AsyncSender thread (`send_async()`). `dict["key"] += 1` — не атомарная операция.  
**Решение:** `_stats_lock = threading.Lock()`. Helper `_inc_stat()` для всех мутаций. `get_stats()` читает под lock'ом.  
**Последствия:** Корректные счётчики при параллельных sync и async отправках.

## ADR-157: IMessageChannel(IChannel) — осознанный cross-module import

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `interfaces.py` строка 17: `from ..channel_routing_module.interfaces import IChannel`. Это sibling-module relative import.  
**Решение:** Осознанная связь. IMessageChannel расширяет IChannel → QueueChannel совместим с CRM `ChannelRegistry` и `RouterManager`.  
**Последствия:** Единая иерархия каналов. Документировано как допустимое зацепление.

## ADR-158: Сохранение registration API (register_channel_handler, register_channel_scenario, cleanup)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Методы `register_channel_handler()`, `register_channel_scenario()`, `cleanup()` не имеют внешних вызовов на момент рефакторинга. Однако анализ `multiprocess_prototype_v2` показывает паттерн config-driven setup: каналы из конфига (`queues` dict в ProcessConfigBase), команды через `command_manager.register_command()`. Phase 8 STATUS.md предусматривает config-driven channel setup в RouterManager.  
**Решение:** Сохранить все registration-методы. Они образуют инфраструктуру для:
- `register_channel_handler` — аналог `command_manager.register_command()` для каналов
- `register_channel_scenario` — сценарная маршрутизация (multi-step pipelines)
- `cleanup()` — стандартный alias-паттерн для shutdown  
**Последствия:** LOC не сокращается на ~28 строк, но API готов к Phase 8 без breaking changes.
```

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
docs(router_module): step 4 — create DECISIONS.md (ADR-153..158)

Step 4 — Architectural Decision Records:
- ADR-153: RouterManager inherits CRM
- ADR-154: Name-returning handler pattern
- ADR-155: Dual dispatchers (channel + message)
- ADR-156: Thread-safe _stats with Lock
- ADR-157: IMessageChannel(IChannel) cross-module import

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 5 — Добавить недостающие тесты (P8)

**Файлы:**
- СОЗДАТЬ `modules/router_module/tests/test_router_adapter.py` (~120 LOC)
- СОЗДАТЬ `modules/router_module/tests/test_schema_adapter.py` (~100 LOC)
- ПРАВКА `modules/router_module/tests/test_router_manager.py` (~40 LOC)

**5a. `test_router_adapter.py`**

```python
"""Tests for RouterAdapter."""
import pytest
from unittest.mock import MagicMock, patch
from ..adapters.router_adapter import RouterAdapter

# Тесты:
# - test_setup_returns_true_with_manager
# - test_setup_returns_false_without_manager
# - test_send_delegates_to_manager
# - test_send_without_manager_returns_error
# - test_send_async_delegates_to_manager
# - test_send_to_channel_adds_sender_field
# - test_receive_delegates_to_manager
# - test_register_channel_delegates
# - test_add_message_handler_delegates
# - test_get_stats_includes_manager_stats
# - test_start_stop_listening
```

**5b. `test_schema_adapter.py`**

```python
"""Tests for RouterSchemaAdapter."""
import pytest
from ..adapters.schema_adapter import RouterSchemaAdapter

# Тесты с мок-SchemaBase:
# - test_adapt_extracts_channels_from_field_routing
# - test_adapt_returns_empty_for_no_routing
# - test_adapt_instance_includes_values (если include_values=True)
# - test_get_all_channels
# - test_extract_channel_info_dict_format
# - test_extract_channel_info_object_format (FieldRouting object)
```

**5c. Дополнения в `test_router_manager.py`**

- `test_receive_with_channel_types_filter`: зарегистрировать два канала (`proc_system`, `proc_data`), положить сообщения в оба, вызвать `receive(channel_types=["system"])`, проверить что вернулись только system-сообщения.
- `test_attach_logger_injects_callbacks`: зарегистрировать канал с `_attach_logger`, проверить что log-callbacks установлены.
- `test_middleware_exception_continues_pipeline`: два middleware, первый бросает Exception, второй обогащает. Проверить что второй применился.

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
test(router_module): step 5 — add tests for RouterAdapter, SchemaAdapter, channel_types, _attach_logger

Step 5 — Improve coverage:
- test_router_adapter.py: 11 tests for adapter delegation and error handling
- test_schema_adapter.py: 6 tests for schema-to-route conversion
- test_router_manager.py: 3 new tests (channel_types filter, logger injection, middleware recovery)

Test files: 2 → 4

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 6 — Обновить ARCHITECTURE.md и главный DECISIONS.md (P9)

**Файлы:**
- ПРАВКА `Inspector_prototype/multiprocess_framework/ARCHITECTURE.md` — заполнить `### 6.9 router_module`
- ПРАВКА `Inspector_prototype/multiprocess_framework/DECISIONS.md` — добавить строку в таблицу «Модульные решения»

**6a. §6.9 в ARCHITECTURE.md**

```markdown
### 6.9 `router_module` — маршрутизация сообщений

**Роль:** Масштабируемая маршрутизация IPC-сообщений между процессами. CRM-наследник (#4), использует Message (#7), Dispatcher (#3).

**RouterManager** (CRM-наследник, ~555 LOC) — facade: AsyncSender (outgoing pipeline), AsyncReceiver (incoming poll), dual dispatchers.
**RouterAdapter** (~155 LOC) — thin wrapper для ProcessModule (добавляет sender context).
**RouterSchemaAdapter** (~152 LOC) — FieldRouting → channel map.

```
RouterManager(ChannelRoutingManager)
    ├── send() / send_async() → _send_mw → _resolve_channels → channel.send()
    ├── receive() → _poll_all_channels → _recv_mw → message_dispatcher
    ├── channel_dispatcher (= CRM._dispatcher) — outgoing (name-returning handlers)
    ├── message_dispatcher — incoming handler dispatch
    ├── AsyncSender — PriorityQueue + background thread
    └── AsyncReceiver — poll thread + callbacks
```

Ключевые решения (ADR-153…158):
- **CRM inheritance:** _channel_registry, _dispatcher из CRM; AsyncSender — отдельный pipeline (ADR-153)
- **Name-returning handlers:** dispatch возвращает имя канала, не результат (ADR-154)
- **Thread-safe _stats:** Lock-protected counters (ADR-156)

📖 [`modules/router_module/README.md`](modules/router_module/README.md) · [`modules/router_module/DECISIONS.md`](modules/router_module/DECISIONS.md)
```

**6b. Строка в главный DECISIONS.md** (после `message_module` в разделе «Модульные решения»):

```
| `router_module` | [`modules/router_module/DECISIONS.md`](modules/router_module/DECISIONS.md) | Messaging/IPC | ADR-153…158 (CRM inheritance, name-returning handlers, dual dispatchers, thread-safe stats) |
```

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v
```

**Коммит:**
```
docs(router_module): step 6 — fill ARCHITECTURE.md §6.9 and add to global DECISIONS.md

Step 6 — Framework documentation:
- ARCHITECTURE.md §6.9: RouterManager architecture and key decisions
- Main DECISIONS.md: add router_module row with ADR-153..158 reference

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

### Шаг 7 — Финальная валидация и обновление метрик

**Файлы:**
- ПРАВКА `modules/router_module/STATUS.md`
- ПРАВКА `plans/refactoring/00_overview.md` — заполнить строку #9

**Действия:**
1. Запустить тесты router_module: `cd Inspector_prototype && python -m pytest multiprocess_framework/modules/router_module/tests -v`
2. Запустить тесты зависимых модулей (process_module): `cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v`
3. Запустить полную валидацию: `cd Inspector_prototype && python scripts/run_framework_tests.py`
4. Подсчитать финальные метрики
5. Обновить STATUS.md: этап 5/8, обновить оценки и чеклист
6. Обновить `00_overview.md` строку #9

**Проверка:**
```bash
cd Inspector_prototype && python scripts/run_framework_tests.py
```

**Коммит:**
```
refactor(router_module): step 7 — final validation, update STATUS.md and 00_overview.md

Step 7 — Final metrics:
- Source files: 16 → 15 (-1 dead _channel_registry.py)
- Source LOC: 1995 → ~1815
- router_manager.py: 624 → ~555
- Test files: 2 → 4
- All framework tests green

Updated STATUS.md (phase 5/8) and 00_overview.md row #9.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

## 3. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|---------------|
| Файлов (без tests) | 16 | 15 (-1: удалён `_channel_registry.py`) |
| LOC (без tests) | 1995 | ~1850 (-154 dead file, ~+10 thread-safety) |
| `router_manager.py` | 624 | ~590 (docstring + suffix + inline) |
| Тест-файлов | 2 | 4 (+test_router_adapter, +test_schema_adapter) |
| Тест LOC | 968 | ~1230 (+260 новых тестов) |
| STATUS.md этап | 4/8 | 5/8 |

---

## 4. Что НЕ делать

1. **НЕ** удалять `register_channel_handler`, `register_channel_scenario`, `cleanup()` — инфраструктура для Phase 8 config-driven setup (см. ADR-158, v2 прототип: `command_manager.register_command()` паттерн).
2. **НЕ** добавлять `correlation_id` — это Phase 5 STATUS.md, отдельная задача.
3. **НЕ** интегрировать ErrorManager — зависит от модуля #14.
4. **НЕ** интегрировать StatsManager — зависит от модуля #15.
5. **НЕ** менять публичный API: `send`, `send_async`, `receive`, `register_channel`, `register_route`, `register_message_handler` — сигнатуры неизменны.
6. **НЕ** переносить `_poll_all_channels` в CRM — router-specific логика (process prefix, channel_types suffix).
7. **НЕ** удалять embedded import `from ...message_module import Message` в `receive()` (строка 248) — осознанный обход circular import.
8. **НЕ** трогать `interfaces.py` (кроме документации) — IMessageChannel(IChannel) cross-import осознанный (ADR-157).
9. **НЕ** переименовывать `channel_dispatcher` / `message_dispatcher` — стабильные имена, используются в process_module.
10. **НЕ** добавлять config-driven channel setup — Phase 8 STATUS.md (только сохранить API для неё).

---

## 5. Кросс-модульные изменения

| Модуль | Файл | Что меняется |
|--------|------|-------------|
| **router_module** | `core/_channel_registry.py` | УДАЛИТЬ (мёртвый код) |
| **router_module** | `core/router_manager.py` | Thread-safety + slim (registration API сохранён) |
| **router_module** | `core/__init__.py` | Обновить docstring |
| **router_module** | `DECISIONS.md` | СОЗДАТЬ (ADR-153..158) |
| **router_module** | `STATUS.md` | Обновить этап и оценки |
| **router_module** | `tests/test_router_adapter.py` | СОЗДАТЬ |
| **router_module** | `tests/test_schema_adapter.py` | СОЗДАТЬ |
| **router_module** | `tests/test_router_manager.py` | Обновить (cleanup + новые тесты) |
| **multiprocess_framework** | `ARCHITECTURE.md` | Заполнить §6.9 |
| **multiprocess_framework** | `DECISIONS.md` | Добавить строку router_module |
| **plans/refactoring** | `00_overview.md` | Обновить строку #9 |

**Нет** изменений в process_module, message_module, channel_routing_module.

---

## 6. Definition of Done

- [x] `core/_channel_registry.py` удалён
- [x] `register_channel_handler`, `cleanup`, `register_channel_scenario` **сохранены** (ADR-158)
- [x] `_stats` мутации защищены `threading.Lock`
- [x] `router_manager.py` ≤ 600 LOC (**600**)
- [x] `DECISIONS.md` создан (ADR-153..158)
- [x] `ARCHITECTURE.md` §6.9 заполнен
- [x] Главный `DECISIONS.md` содержит строку `router_module`
- [x] Тесты RouterAdapter существуют и проходят
- [x] Тесты RouterSchemaAdapter существуют и проходят
- [x] Тест channel_types фильтрации существует и проходит
- [x] Тест _attach_logger инъекции существует и проходит
- [x] `00_overview.md` строка #9 заполнена (`files_after`, `loc_after`, `tests_after`)
- [ ] `python scripts/run_framework_tests.py` — все зелёные, нет регрессий *(локально: pytest 3.14 — `router_module` + `process_module` 170 passed; полный прогон упирается в отсутствие `sqlalchemy` / `PyQt5` в окружении валидатора)*
- [x] `STATUS.md` обновлён до этапа 5/8

---

## 7. Ключевые файлы для реализации

```
Inspector_prototype/multiprocess_framework/modules/router_module/
├── core/router_manager.py             ← главный файл (шаги 1-3)
├── core/_channel_registry.py          ← УДАЛИТЬ (шаг 1)
├── core/__init__.py                   ← обновить docstring (шаг 1)
├── adapters/router_adapter.py         ← read-only (для тестов в шаге 5)
├── adapters/schema_adapter.py         ← read-only (для тестов в шаге 5)
├── DECISIONS.md                       ← СОЗДАТЬ (шаг 4)
├── STATUS.md                          ← обновить (шаг 7)
├── tests/test_router_manager.py       ← правки (шаги 1, 2, 5)
├── tests/test_router_adapter.py       ← СОЗДАТЬ (шаг 5)
└── tests/test_schema_adapter.py       ← СОЗДАТЬ (шаг 5)

Inspector_prototype/multiprocess_framework/
├── ARCHITECTURE.md                    ← §6.9 (шаг 6)
└── DECISIONS.md                       ← строка router_module (шаг 6)

plans/refactoring/00_overview.md       ← строка #9 (шаг 7)
```
