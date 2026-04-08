# base_manager — архитектурные решения (ADR)

Локальные решения, касающиеся архитектуры модуля `base_manager`. Глобальные правила фреймворка — см. [`../../../DECISIONS.md`](../../../DECISIONS.md) (особенно ADR-008 Dict at Boundary, ADR-013 channel_routing_module, правила pickle-safe).

---

## ADR-114: Удаление PluginRegistry/ObservablePlugin из base_manager

- Дата: 2026-04-08
- Статус: принято
- Контекст: `base_manager` содержал `PluginRegistry` + `ObservablePlugin` (ABC) + встроенные плагины (`LoggerPlugin`, `StatsPlugin`, `ErrorPlugin`) для создания приватных методов на `ObservableMixin`. Плагины дублировали функциональность: `LoggerPlugin` создавал `_log_*` методы, которые уже нативно были в `ObservableMixin`. Единственное преимущество плагинов — расширение для новых менеджеров, но это могло быть достигнуто наследованием.
- Решение: Удалена вся система плагинов (`mixins/plugins/` целиком, ~340 LOC). Приватные методы остаются нативно на `ObservableMixin`. Расширение для новых сервисов — через подклассы `ObservableMixin` с дополнительными методами.
- Причина: DRY, упрощение архитектуры, избавление от параллельного API.
- Отклонённые альтернативы: Оставить плагины для будущей расширяемости — отклонено (дублирование, не используется в коде).

---

## ADR-115: Удаление ObservableDecorators (logged/timed/monitored)

- Дата: 2026-04-08
- Статус: принято
- Контекст: `base_manager` содержал `ObservableDecorators` с декораторами `@logged`, `@timed`, `@monitored` как параллельный способ логирования, профилирования и трекирования. Это был **4-й способ** наблюдаемости (помимо приватных методов, плагинов и публичных proxy-методов). Декораторы были не pickle-safe (требовали специальной обработки в `__getstate__`/`__setstate__`), что противоречило философии Windows spawn (см. ADR-008 и внутреннюю документацию `docs/OBSERVABLE_ARCHITECTURE.md`).
- Решение: Удалена папка `mixins/decorators/` целиком (~162 LOC). Вместо `@logged` используйте `self._log_info()` внутри метода или создайте оборотень-декоратор на месте, если нужен.
- Причина: Упрощение, дублирование API, конфликт с multiprocessing.
- Отклонённые альтернативы: Переделать декораторы в pickle-safe — отклонено (усложнение, слабый сценарий использования).

---

## ADR-116: Удаление BaseManager.__getattr__ magic-доступа к адаптерам

- Дата: 2026-04-08
- Статус: принято
- Контекст: `BaseManager` содержал `__getattr__` для magic-доступа к адаптерам: `manager.command_adapter` вместо `manager.get_adapter("command")`. Это было удобно, но нарушало типизацию (IDE не видит методов адаптеров), усложняло debug (неясный StackTrace при поиске атрибута), затрудняло unpickle (требовал обработки в `__setstate__` для восстановления no-op заглушек).
- Решение: Удален `BaseManager.__getattr__`; требуется явный `get_adapter(name)`. Все потребители мигрированы синхронно (sql_module, frontend_module и т. д.).
- Причина: Явность (explicit is better than implicit), типизация, упрощение unpickle-логики.
- Отклонённые альтернативы: Оставить, но задокументировать ограничения IDE — отклонено (не решает проблему).

---

## ADR-117: Удаление BaseManager.on_event/emit_event (дублирует dispatch_module)

- Дата: 2026-04-08
- Статус: принято
- Контекст: `BaseManager` содержал встроенную in-process систему событий (`on_event(type, callback)` / `emit_event(type, data)`) для локальной регистрации обработчиков. Это дублировало функциональность `dispatch_module` (ключ → список обработчиков, same API) и `router_module` (события между процессами, см. ADR-008 и `ROUTING_GLOSSARY.md`). Потребители (sql_module, frontend_module) редко использовали; те, что использовали, могли мигрировать на dispatch.
- Решение: Удалены методы `on_event`, `emit_event`, поле `_event_handlers` из `BaseManager`. Потребители мигрированы:
  - sql_module: `emit_event("db_ready")` → `self._log_info("db_ready")` (уведомление через логгер).
  - frontend_module: `emit_event("...") → dispatch.send(...)` (если нужна регистрация обработчика).
- Причина: DRY, снижение дублирования API.
- Отклонённые альтернативы: Переделать на основе dispatch_module — отклонено (API всё равно дублируется и конкурирует).

---

## История модуля

**Фаза 1, Модуль #1, Шаги 4.0–4.6 (рефакторинг):** все перечисленные выше решения применены одновременно.

**Фаза 1, Модуль #1, Шаг 5 (документация):** README переписан, добавлена архитектурная документация (`docs/OBSERVABLE_ARCHITECTURE.md`).

---

## Внешние ссылки

- [`README.md`](README.md) — публичный API и быстрый старт.
- [`docs/OBSERVABLE_ARCHITECTURE.md`](docs/OBSERVABLE_ARCHITECTURE.md) — глубокое погружение в два режима наблюдаемости, почему методы класса, гарантии pickle.
- [`docs/INTERFACES_USAGE.md`](docs/INTERFACES_USAGE.md) — примеры использования `IBaseManager`, `IBaseAdapter`, `IObservableMixin`.
- [`STATUS.md`](STATUS.md) — статус модуля, метрики рефакторинга.
- Глобальные правила: [`../../../DECISIONS.md`](../../../DECISIONS.md) (ADR-008 Dict at Boundary, ADR-013 channel_routing_module).
