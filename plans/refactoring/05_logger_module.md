# Refactoring plan: `logger_module` (модуль #5)

> **Статус:** 🟢 Выполнено (2026-04-09).  
> **Автор плана:** Opus, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

Первый реальный CRM-наследник. `LoggerManager` **уже мигрирован** на `ChannelRoutingManager` (STATUS: 4/8, фаза 2 CRM-миграции завершена). Однако внутри осталось **два legacy-компонента**, которые дублируют функционал CRM:

1. **`LogDispatcher`** (233 LOC, `core/log_dispatcher.py`) — собственная маршрутизация по каналам/уровням. Заменена CRM's `Dispatcher` + `_level_to_channel` в ErrorManager. Сейчас используется **только для backward compat stats** в ErrorManager.

2. **`BatchManager`** (135 LOC, `batcher/batch_manager.py`) — собственная буферизация. Полностью заменена CRM's `BatchBuffer`. **Ни один файл** вне `batcher/` не импортирует `BatchManager`.

3. **`LogRecord` dataclass** (в `log_dispatcher.py`) — **нужен** (используется LoggerManager + ErrorManager), но должен жить отдельно от LogDispatcher.

**Цель:** удалить LogDispatcher и BatchManager, перенести LogRecord, убрать backward compat. Сократить LOC на ~25%.

**Сложность:** ★★★☆☆ (средняя) — кросс-модульное изменение (ErrorManager).

---

## 1. Текущее состояние (baseline)

- **Файлов:** 16 `.py` (без tests/__pycache__)
- **LOC:** 1 909 (из overview; агент насчитал 1 674 — нужно уточнить в Шаге 0)
- **Тестов:** 1 файл (test_logger_manager.py, 158 LOC, ~30 тестов)
- **Публичный API:** LoggerManager, LoggerManagerConfig, LogLevel, LogScope, LogChannel, FileChannel, ConsoleChannel, HttpChannel, create_channel, LoggerAdapter, ILoggerManager, ILogChannel, get_logger, init_logging, shutdown_logging

### 1.1. Внешние потребители

| Модуль | Что импортирует | Затронут? |
|--------|----------------|-----------|
| **error_module** | `LoggerManager`, `LoggerManagerConfig`, `LogLevel`, `LogScope`, **`LogRecord`** (из log_dispatcher!) | **ДА** — нужно обновить импорт LogRecord |
| process_manager_module | `LoggerManager` | Нет |
| process_module | `LoggerManager`, `LoggerManagerConfig`, `LoggerAdapter` | Нет |
| console_module | `ILogChannel` | Нет |
| statistics_module | `LogLevel`, `resolve_log_file_path` | Нет |

### 1.2. Что удаляется

| Файл | LOC | Причина удаления |
|------|-----|-----------------|
| `core/log_dispatcher.py` | 233 | Заменён CRM's Dispatcher + `_level_to_channel`. LogRecord переносится. |
| `batcher/__init__.py` | 12 | Пакет целиком |
| `batcher/batch_manager.py` | 135 | Заменён CRM's BatchBuffer |
| **Итого** | **380** | |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline и аудит ⬜

1. `pytest logger_module/tests -v` — записать число тестов.
2. Подсчитать LOC: `find modules/logger_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l`
3. Подтвердить, что `BatchManager` НЕ используется вне `batcher/`:
   ```
   grep -rn "BatchManager" --include="*.py" modules/ | grep -v batcher | grep -v __pycache__
   ```
4. Подтвердить, что `LogDispatcher` используется только в:
   - `logger_module/core/logger_manager.py` (создание экземпляра)
   - `error_module/core/error_manager.py` (backward compat stats)
   ```
   grep -rn "LogDispatcher\|log_dispatcher" --include="*.py" modules/ | grep -v __pycache__ | grep -v "\.pyc"
   ```
5. Записать, какие backward compat properties есть в logger_manager.py:
   - `channels` property (возвращает dict из registry)
   - `batcher` property (alias для self._buffer)
   - `self.dispatcher` (LogDispatcher instance)
6. Коммит: `docs(logger_module): baseline audit before cleanup`.

---

### Шаг 1 — Перенести `LogRecord` из `log_dispatcher.py` → `core/log_types.py` ⬜

**Создать** новый файл `core/log_types.py`:

```python
# core/log_types.py
"""Типы данных для logger_module."""

from dataclasses import dataclass, field
from typing import Dict, Any
from .log_enums import LogLevel, LogScope


@dataclass
class LogRecord:
    """Запись лога для передачи между компонентами."""
    timestamp: float
    level: LogLevel
    scope: LogScope
    message: str
    module: str = "main"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для каналов и буферов."""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value if hasattr(self.level, 'value') else str(self.level),
            "scope": self.scope.value if hasattr(self.scope, 'value') else str(self.scope),
            "message": self.message,
            "module": self.module,
            **self.extra,
        }
```

**Скопировать** содержимое `LogRecord` из `log_dispatcher.py` (строки 30-52). Перенести точно, не менять сигнатуру.

**Обновить импорты:**
1. `core/logger_manager.py`: `from .log_dispatcher import LogDispatcher, LogRecord` → `from .log_types import LogRecord` (LogDispatcher пока оставить, удалим в Шаге 2)
2. `error_module/core/error_manager.py`: `from ...logger_module.core.log_dispatcher import LogRecord` → `from ...logger_module.core.log_types import LogRecord`
3. `core/__init__.py`: добавить `from .log_types import LogRecord`, убрать `LogRecord` из `log_dispatcher` строки.

**Тесты зелёные** (и logger_module, и error_module).

Коммит: `refactor(logger_module): extract LogRecord into core/log_types.py`.

---

### Шаг 2 — Удалить `LogDispatcher` и `batcher/` ⬜

#### 2a. Удалить LogDispatcher

1. В `logger_manager.py` — **удалить**:
   - Импорт: `from .log_dispatcher import LogDispatcher` (строка 30)
   - Создание: `self.dispatcher = LogDispatcher(app_name=..., process=process)` (строка 97)
   - Инициализацию: `self.dispatcher.initialize()` (если есть в initialize())
   - Shutdown: `self.dispatcher.shutdown()` (если есть в shutdown())
   - Любые вызовы `self.dispatcher.*`

2. В `error_module/core/error_manager.py` — **удалить**:
   - Строки 196-201 (регистрация в LogDispatcher для backward compat):
     ```python
     # УДАЛИТЬ ВЕСЬ БЛОК:
     d = self.dispatcher
     for level_str, ch_name in self._level_to_channel.items():
         ch = self._channel_registry.get(ch_name)
         if ch is not None:
             d.register_level_route(level_str, ch_name, ch.write)
     ```
   - Комментарий на строке 175 про self.dispatcher.

3. Удалить файл `core/log_dispatcher.py`.

4. Обновить `core/__init__.py` — убрать `from .log_dispatcher import LogDispatcher`.

#### 2b. Удалить batcher/

1. `git rm -r modules/logger_module/batcher/`
2. Проверить, что ничего не ломается (grep из Шага 0 подтвердил, что нет внешних потребителей).

**Тесты зелёные** (logger_module + error_module).

Коммит: `refactor(logger_module): remove LogDispatcher and legacy batcher/`.

---

### Шаг 3 — Убрать backward compat properties из LoggerManager ⬜

В `logger_manager.py`:

1. **Удалить** `channels` property (backward compat, ~5 строк):
   ```python
   # УДАЛИТЬ:
   @property
   def channels(self):
       """Backward compat: dict {name: channel}."""
       ...
   ```
   **Проверить:** `grep -rn "\.channels\b" --include="*.py" modules/error_module/` — ErrorManager использует `self.channels` в `_setup_level_routes()` (строка 179: `has_critical = "critical_file" in self.channels`). Если да — **заменить** на `self._channel_registry.names` или `self._channel_registry.get(name) is not None` в ErrorManager.

2. **Удалить** `batcher` property (alias для self._buffer, ~3 строки).

3. **Удалить** `self.dispatcher` атрибут (уже удалён в Шаге 2, но убедиться, что нет остаточных ссылок).

**ВАЖНО:** Если ErrorManager использует `self.channels` property — нужно обновить ErrorManager тоже. Проверить перед удалением!

Коммит: `refactor(logger_module): remove backward compat properties`.

---

### Шаг 4 — Документация ⬜

#### 4.1. `DECISIONS.md` (новый)

```markdown
# logger_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-140: Удаление LogDispatcher

**Статус:** принято  
**Контекст:** LogDispatcher дублировал CRM's Dispatcher для channel/level routing.  
**Решение:** Удалён. LogRecord перенесён в `core/log_types.py`. ErrorManager использует `_level_to_channel` + прямой `channel.write()`, без LogDispatcher.

## ADR-141: Удаление BatchManager (batcher/)

**Статус:** принято  
**Контекст:** BatchManager (135 LOC) дублировал CRM's BatchBuffer.  
**Решение:** Удалён целиком. LoggerManager использует `BatchBuffer` из `channel_routing_module`.

## ADR-142: LogRecord как отдельный тип

**Статус:** принято  
**Решение:** `LogRecord` (dataclass) вынесен в `core/log_types.py`. Импортируется logger_module и error_module.
```

#### 4.2. Главный DECISIONS.md

Добавить строку:
```
| `logger_module` | [`modules/logger_module/DECISIONS.md`](modules/logger_module/DECISIONS.md) | Services | ADR-140…142 (удаление LogDispatcher, BatchManager, выделение LogRecord) |
```

#### 4.3. ARCHITECTURE.md §6.5

```markdown
### 6.5 `logger_module` — первый CRM-наследник

**Роль:** Логирование со scope-based маршрутизацией (SYSTEM / BUSINESS / PERFORMANCE / AUDIT / SECURITY). Первый реальный наследник CRM-паттерна.

**`LoggerManager`** (`ChannelRoutingManager`) — scope + level → каналы (FileChannel / ConsoleChannel / HttpChannel). Использует `BatchBuffer` из CRM для пакетной записи. Поддержка per-module файлов, thread-local контекста, динамического should_log().

```
LoggerManager (ChannelRoutingManager)
    ├── _channel_registry  — FileChannel / ConsoleChannel / HttpChannel
    ├── _buffer (BatchBuffer) — batch flush по size/interval
    ├── _dispatcher (Dispatcher) — scope/level → handler
    ├── LogRecord (core/log_types.py) — dataclass записи
    └── LoggerAdapter — обёртка для multiprocess

Наследник: ErrorManager (severity routing: WARNING/ERROR/CRITICAL → отдельные файлы)
```

Ключевые решения (ADR-140…142):
- Удалён LogDispatcher (дублировал CRM's Dispatcher).
- Удалён BatchManager (дублировал CRM's BatchBuffer).
- LogRecord — отдельный тип в `core/log_types.py`.

📖 Подробнее: [`modules/logger_module/README.md`](modules/logger_module/README.md) · [`modules/logger_module/DECISIONS.md`](modules/logger_module/DECISIONS.md)
```

#### 4.4. README.md, STATUS.md — обновить

- README: убрать секции про LogDispatcher и BatchManager.
- STATUS: дата, этап 5/8, Phase 3 complete.

Коммит: `docs(logger_module): add DECISIONS.md, fill ARCHITECTURE.md §6.5`.

---

### Шаг 5 — Финальная валидация ⬜

1. `pytest logger_module/tests -v` — зелёные.
2. `pytest error_module/tests -v` — зелёные (кросс-модульное изменение!).
3. `python scripts/validate.py` — зелёный.
4. `python scripts/run_framework_tests.py` — все зелёные.
5. Собрать метрики «после».
6. Обновить `plans/refactoring/00_overview.md` — строка `logger_module`.
7. Коммит: `refactor(logger_module): final validation and metrics`.

---

## 3. Что НЕ делать

1. **НЕ** менять `channels/log_channel.py` — каналы стабильны.
2. **НЕ** менять `configs/logger_manager_config.py` — конфиг сложный, но работает.
3. **НЕ** менять `adapters/logger_adapter.py` — адаптер для multiprocess, стабилен.
4. **НЕ** менять `log_paths.py`, `log_enums.py` — утилиты, стабильны.
5. **НЕ** менять `log_config.py` — re-export, оставить.
6. **НЕ** рефакторить `logger_manager.py` deeper — 582 LOC → ~520 LOC после удаления backward compat. Дальнейшее сжатие не оправдано (setup-методы необходимы для scope/module/context).
7. **НЕ** менять тесты — только добавить, если нужно.
8. **НЕ** трогать другие модули кроме `error_module` (и то только импорт LogRecord + удаление LogDispatcher вызовов).

---

## 4. Кросс-модульные изменения (ВАЖНО для Composer)

Этот план затрагивает **два модуля**:

| Модуль | Файл | Что меняется |
|--------|------|-------------|
| **logger_module** | `core/logger_manager.py` | Удалить `self.dispatcher = LogDispatcher(...)`, backward compat properties |
| **logger_module** | `core/log_dispatcher.py` | УДАЛИТЬ файл (после переноса LogRecord) |
| **logger_module** | `batcher/` | УДАЛИТЬ директорию |
| **logger_module** | `core/log_types.py` | СОЗДАТЬ (LogRecord dataclass) |
| **error_module** | `core/error_manager.py` | Обновить импорт LogRecord, удалить LogDispatcher регистрацию (строки 196-201) |

**Порядок:** Шаг 1 (перенос LogRecord) → Шаг 2 (удаление LogDispatcher + batcher) → Шаг 3 (backward compat). Именно в таком порядке, иначе ErrorManager сломается.

---

## 5. Definition of Done (модуль #5)

- [x] `core/log_types.py` создан с `LogRecord`.
- [x] `core/log_dispatcher.py` удалён.
- [x] `batcher/` удалён.
- [x] Backward compat properties удалены (channels, batcher, self.dispatcher).
- [x] ErrorManager обновлён (импорт LogRecord, без LogDispatcher).
- [x] Все тесты logger_module зелёные.
- [x] Все тесты error_module зелёные.
- [x] `validate.py` зелёный.
- [x] `DECISIONS.md` создан (ADR-140…142).
- [x] Главный `DECISIONS.md` обновлён.
- [x] ARCHITECTURE.md §6.5 заполнен.
- [x] Метрики «после» в `00_overview.md`.

---

## 6. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| Файлов (без tests) | 16 | 13 (−3: log_dispatcher, batcher/*) + 1 (log_types) = 14 |
| LOC | ~1 909 | ~1 450 (−24%) |
| `logger_manager.py` | 582 | ~520 (−11%, удалён backward compat) |
| Тестов | 1 файл | 1 файл (без изменений) |
| Публичный API | Без изменений (LogDispatcher не был в `__init__.py`) |
