# Refactoring plan: `channel_routing_module` (модуль #4)

> **Статус:** 🟡 Ожидает выполнения.  
> **Автор плана:** Opus, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

Модуль **полностью функционален** (STATUS.md: 8/8, оценки 8–10/10). Паттерн CRM (ChannelRoutingManager + buffer + dispatcher + channels) работает, все 3 наследника мигрированы (LoggerManager, ErrorManager, RouterManager). 58 тестов зелёные.

**Это лёгкий модуль для рефакторинга** — основная работа документационная:

1. **Нет `DECISIONS.md`** — ADR-013…016, ADR-108 упоминаются в STATUS.md и README, но не оформлены как файл.
2. **ARCHITECTURE.md §6.4** — пустой placeholder.
3. **`base_buffer.py`** (14 строк) — shim re-export `IBufferStrategy` из `interfaces.py`. Можно удалить.
4. **Мелкая уборка:** проверить, нет ли стёртого backward compat после рефакторинга dispatch_module (мы удалили `AdvancedDispatcher`, `logger_manager=` и т.д.).

**Сложность:** ★☆☆☆☆ (минимальная). Для Composer — ~15 минут.

---

## 1. Текущее состояние (baseline)

- **Файлов:** 14 `.py` (без tests/__pycache__)
- **LOC:** 1 348
- **Тестов:** 3 файла, 58 тестов
- **Публичный API:** `ChannelRoutingManager`, `ChannelRegistry`, `normalize_config`, `ChannelRoutingConfig`, `ChannelRoutingManagerConfig`, `IChannel`, `IBufferStrategy`, `IChannelRoutingManager`, `AsyncSenderBuffer`, `BatchBuffer`, `BatchConfig`, `DirectBuffer`
- **Внешние потребители:** 3 модуля (logger_module, router_module, statistics_module) + error_module (через logger)

---

## 2. Атомарные шаги

### Шаг 0 — Baseline ⬜

1. `pytest channel_routing_module/tests -v` — записать результат.
2. Проверить, что `channel_routing_module` не импортирует ничего удалённого из dispatch_module:
   ```
   grep -rn "AdvancedDispatcher\|logger_manager=\|error_manager=" --include="*.py" modules/channel_routing_module/
   ```
3. Проверить, что `base_buffer.py` действительно только re-export:
   - Открыть `buffers/base_buffer.py` — подтвердить, что это 14 строк с `from ..interfaces import IBufferStrategy`.
   - Grep: `from channel_routing_module.buffers.base_buffer` — есть ли внешние потребители?
   - Grep: `from .base_buffer` внутри `buffers/__init__.py`.
4. Записать результаты.

---

### Шаг 1 — Удалить `base_buffer.py` (если безопасно) ⬜

**Условие:** grep из Шага 0 подтвердил, что никто не импортирует из `base_buffer.py` напрямую.

1. Удалить `buffers/base_buffer.py`.
2. Если `buffers/__init__.py` импортирует из `base_buffer`, убрать эту строку (IBufferStrategy уже экспортируется из `__init__.py` верхнего уровня через `interfaces.py`).
3. Тесты зелёные.
4. Коммит: `refactor(channel_routing_module): remove base_buffer.py re-export shim`.

**Если есть внешний потребитель** — оставить, пометить в `# TODO: remove after migration`.

---

### Шаг 2 — Создать `DECISIONS.md` ⬜

Файл: `modules/channel_routing_module/DECISIONS.md`

Собрать ADR из STATUS.md и README:

```markdown
# channel_routing_module — Архитектурные решения

> Ссылки на глобальные решения: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-013: Паттерн CRM (ChannelRoutingManager)

**Статус:** принято (2026-03-12)  
**Контекст:** LoggerManager, ErrorManager, RouterManager дублировали логику маршрутизации.  
**Решение:** Единый базовый класс ChannelRoutingManager = BaseManager + ObservableMixin + ChannelRegistry + Dispatcher + IBufferStrategy.  
**Следствие:** Все канальные менеджеры наследуют CRM, добавляя только domain-логику.

## ADR-014: Три стратегии буферизации

**Статус:** принято  
- `DirectBuffer` — без буферизации (тесты, простые случаи).  
- `BatchBuffer` — deque + timer (LoggerManager: batch flush по size/interval).  
- `AsyncSenderBuffer` — PriorityQueue + фоновый поток (RouterManager: async send).

## ADR-015: RouterManager не использует IBufferStrategy из CRM

**Статус:** принято  
**Контекст:** RouterManager имеет собственный async_sender_buffer, интегрированный с channel_dispatcher.  
**Решение:** RouterManager передаёт `buffer_strategy=None` в CRM, управляет буфером самостоятельно.

## ADR-016: register_broadcast() для мультиканальной доставки

**Статус:** принято  
**Решение:** `register_broadcast(key, [ch1, ch2])` регистрирует обёртку, которая вызывает write() на всех указанных каналах.

## ADR-108: Две роли конфигов (ChannelRoutingConfig vs ChannelRoutingManagerConfig)

**Статус:** принято (2026-03-31)  
- `core/config.py: ChannelRoutingConfig(SchemaBase)` — базовый runtime-конфиг, от него наследуют LoggerManagerConfig, RouterManagerConfig.  
- `configs/channel_routing_manager_config.py: ChannelRoutingManagerConfig(SchemaBase)` — flat-схема для реестра/UI.  
**Причина:** build() у ChannelRoutingConfig возвращал разные структуры при наследовании; flat-schema решает проблему регистрации.
```

Обновить главный `DECISIONS.md` — добавить строку в таблицу «Модульные решения»:

```
| `channel_routing_module` | [`modules/channel_routing_module/DECISIONS.md`](modules/channel_routing_module/DECISIONS.md) | Foundation | ADR-013…016 (CRM pattern, buffers, broadcast), ADR-108 (dual config) |
```

Коммит: `docs(channel_routing_module): create DECISIONS.md with ADR-013…016, ADR-108`.

---

### Шаг 3 — Заполнить ARCHITECTURE.md §6.4 ⬜

Заменить строку `### 6.4 channel_routing_module — *TODO (после модуля #4)*` на:

```markdown
### 6.4 `channel_routing_module` — паттерн CRM

**Роль:** Базовый класс для всех менеджеров с канальной маршрутизацией. Устраняет дублирование между Logger, Error, Router, Stats — все наследуют `ChannelRoutingManager`.

**`ChannelRoutingManager`** (`BaseManager` + `ObservableMixin`) — фасад, объединяющий:
- `ChannelRegistry` — потокобезопасный реестр каналов (`IChannel`)
- `Dispatcher` — маршрутизация ключ → канал (из dispatch_module)
- `IBufferStrategy` — опциональная буферизация (Direct / Batch / AsyncSender)
- `normalize_config()` — Dict at Boundary для конфигов

```
ChannelRoutingManager (BaseManager + ObservableMixin)
    ├── ChannelRegistry    — register/get/unregister каналов
    ├── Dispatcher         — key → handler (dispatch_module)
    ├── IBufferStrategy    — Direct / Batch / AsyncSender
    └── normalize_config() — dict ← None | dict | SchemaBase

Наследники:
    ├── LoggerManager   (BatchBuffer, scope/level → ILogChannel)
    │       └── ErrorManager   (severity → channel)
    └── RouterManager   (AsyncSender, IMessageChannel)
```

Ключевые решения (ADR-013…016, ADR-108):
- CRM-паттерн как единая основа канальных менеджеров.
- Три буфера для разных сценариев (sync/batch/async).
- Две роли конфигов: runtime (для наследования) и flat (для реестра/UI).

📖 Подробнее: [`modules/channel_routing_module/README.md`](modules/channel_routing_module/README.md) · [`modules/channel_routing_module/DECISIONS.md`](modules/channel_routing_module/DECISIONS.md)
```

Коммит: `docs(channel_routing_module): fill ARCHITECTURE.md §6.4`.

---

### Шаг 4 — Обновить STATUS.md ⬜

1. Обновить дату.
2. Добавить запись о Phase 0.5 (DECISIONS.md, ARCHITECTURE.md).
3. Если `base_buffer.py` удалён — отразить.

Коммит: `docs(channel_routing_module): update STATUS.md after cleanup`.

---

### Шаг 5 — Финальная валидация ⬜

1. `pytest channel_routing_module/tests -v` — зелёные.
2. `python Inspector_prototype/scripts/validate.py` — зелёный.
3. `python Inspector_prototype/scripts/run_framework_tests.py` — все зелёные.
4. Собрать метрики «после».
5. Обновить `plans/refactoring/00_overview.md` — строка `channel_routing_module`.
6. Коммит: `docs(channel_routing_module): final validation and metrics`.

---

## 3. Что НЕ делать

1. **НЕ** менять `channel_routing_manager.py` — он чистый (373 LOC, хорошая структура).
2. **НЕ** менять `interfaces.py` — контракты стабильны, используются 4 наследниками.
3. **НЕ** менять буферы (DirectBuffer, BatchBuffer, AsyncSenderBuffer) — работают, протестированы.
4. **НЕ** менять `configs/` — двойная роль конфигов зафиксирована в ADR-108.
5. **НЕ** менять внешние модули (logger, router, error, stats).
6. **НЕ** рефакторить логику — модуль стабилен.

---

## 4. Definition of Done (модуль #4)

- [ ] `DECISIONS.md` создан (ADR-013…016, ADR-108).
- [ ] Главный `DECISIONS.md` обновлён — ссылка на `channel_routing_module/DECISIONS.md`.
- [ ] ARCHITECTURE.md §6.4 заполнен.
- [ ] `base_buffer.py` удалён (или обоснованно оставлен).
- [ ] STATUS.md обновлён.
- [ ] Все тесты зелёные.
- [ ] `validate.py` зелёный.
- [ ] Метрики «после» в `00_overview.md`.

---

## 5. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| Файлов (без tests) | 14 | 13 (−1: base_buffer.py) |
| LOC | 1 348 | ~1 334 (−1%) |
| Тестов | 3 файла, 58 tests | Без изменений |
| Публичный API | 12 экспортов | Без изменений |

**Примечание:** Это самый «лёгкий» модуль в плане рефакторинга. Основная ценность — формализация ADR и заполнение ARCHITECTURE.md. Код менять не нужно.
