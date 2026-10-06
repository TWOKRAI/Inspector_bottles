---
name: feedback-logger-error-stats-managers
description: "Логирование через logger_manager, ошибки через error_manager, статистика через statistics_manager — заложены в base_manager через ObservableMixin (inheritance / наследование); общее поднимать в ChannelRoutingManager, не писать третью копию"
module: [base_manager, logger_module]
mechanism: [architecture]
merged_from: [feedback_all_components_base_manager, feedback_three_managers_share_base]
metadata:
  type: feedback
---

**Rule:** В framework-коде логирование, ошибки и статистика идут **только** через инжектируемые менеджеры из `base_manager`:

- **Логирование** → `logger_manager` (`multiprocess_framework/modules/logger_module/`). Использовать `self._log_info("...")`, `self._log_warning("...")`, `self._log_error("...")` из `ObservableMixin`. Никаких `print()`, `logging.getLogger(...)`, `loguru.logger.info()` в продуктовом коде.
- **Ошибки** → `error_manager` (`multiprocess_framework/modules/error_module/`). Использовать `self._track_error(exc, context={...})`. Не подавлять, не превращать в `print(e)`.
- **Статистика** → `statistics_manager` (`multiprocess_framework/modules/statistics_module/`). Использовать `self._record_metric("counter.name", 1, tags={...})`, `self._record_timing("op.duration", ms)`. Никаких локальных `self._counter += 1` для метрик.

Все три менеджера встроены в базовый менеджер: класс наследует `BaseManager` + `ObservableMixin`, инициализирует `ObservableMixin.__init__(self, managers={'logger': ..., 'stats': ..., 'error': ...})`. Контракт — `IObservableMixin` (`base_manager/interfaces.py`), документация — `base_manager/docs/OBSERVABLE_ARCHITECTURE.md`.

**Why:** Единая точка наблюдения за системой. Менеджеры pickle-safe (multiprocessing spawn на Windows работает), маршрутизируются через RouterManager, агрегируются на уровне процесса. Локальные `print`/`logging` обходят эту инфраструктуру → нечего трассировать, нечего собирать в дашборд, нечего фильтровать по level. Пользователь явно подчёркивает: «они заложены в базовый менеджер» — то есть это **архитектурный инвариант**, не рекомендация.

**How to apply:**
- Любой новый класс-менеджер в `multiprocess_framework/modules/` или в `multiprocess_prototype/backend/` наследует `BaseManager` + `ObservableMixin` и принимает зависимости через `__init__(..., logger=None, stats=None, error=None)`.
- Если правишь существующий код и видишь `print(...)` или `logging.getLogger(...)` — это технический долг, заменять на `self._log_*`/`self._track_error`/`self._record_metric` при ближайшей итерации.
- В тестах создавать mock-менеджеры через `MagicMock()` и инжектить в `ObservableMixin`.
- В GUI-слое (`frontend/`) — пока нет инжекции BaseManager, можно использовать `loguru.logger` напрямую (это исключение для view-слоя, не для бизнес-логики). Уточнять у пользователя если непонятно.

См. [[project-processes-tab]], [[feedback-dict-at-boundary-gui]] — связанные правила про IPC и слой.

## Слито из feedback_all_components_base_manager (_archive/feedback_all_components_base_manager.md)

Владелец (2026-06-07, при Phase 2 recipe-orchestrator-unify) выбрал: **все компоненты наследуют `BaseManager + ObservableMixin`** для доступа к logger/error/stats менеджерам — даже чистые стратегии (FullReplacePlanner), где side-effects нет.

**Why:** предсказуемость «все компоненты одинаковые, исключений нет» важнее минимализма. Принял осознанно lifecycle-церемонию (initialize/shutdown) как цену единообразия — после честного разбора, что ObservableMixin даёт observability и без наследования.

**How to apply:** новый долгоживущий компонент → паттерн `ProcessModule`: `class X(BaseManager, ObservableMixin)`, `BaseManager.__init__(self, name)` + `ObservableMixin.__init__(self, managers={'logger': pm.logger_manager, 'error': pm.error_manager, 'stats': pm.stats_manager})` + реализовать `initialize`/`shutdown`. PM держит менеджеры как `self.logger_manager/error_manager/stats_manager`. Исключение — чистые трансформеры уже в проде (BlueprintAssembler): не ретрофитить, ошибки через исключение ловит вызывающий. Балансирует с [[feedback_framework_first]] (владелец явно перевесил в сторону единообразия здесь) и [[feedback_logger_error_stats_managers]].

## Слито из feedback_three_managers_share_base (_archive/feedback_three_managers_share_base.md)

Требование владельца 2026-07-26: «logger_manager, error_manager, statistics_manager — братья-близнецы и должны иметь одну базу, чтоб не дублировать. Наследоваться.»

**Фактическая иерархия (сверена 2026-07-26):** общая база уже есть — `ChannelRoutingManager` (сам от `BaseManager` + `ObservableMixin`). Но она тонкая: хозяйство наблюдаемости лежит в `LoggerCore`, а `StatsManager` наследует CRM напрямую, мимо него.

```
ChannelRoutingManager
    ├── LoggerCore ──┬── LoggerManager
    │                └── ErrorManager
    └── StatsManager   ← мимо LoggerCore
```

Настоящие дыры: у stats нет `set_sink_enabled`, `add_log_tap`/`_emit_to_taps`, `_fallback_log` — их поднимать.

**Ревью Fable поправило первичный диагноз (важно, чтобы не повторить):**
- **Резолв путей — НЕ дубль:** stats импортирует ТУ ЖЕ `resolve_log_file_path`. Проблемы другие — направление зависимости `statistics → logger` и отсутствие per-process подпапки у stats.
- **Батчинг — НЕ дубль:** общий механизм уже поднят (`IBufferStrategy` + `CRM._buffer`). `BatchBuffer` = pass-through, `AggregationWindow` = lossy-агрегация с анти-дубль-счётом при N каналах. Слить = сломать.
- **`ErrorManager` уже имеет** sink-control и tap'ы (от `LoggerCore`); его дыра — адресуемость командой, не методы.
- **Риск подъёма:** `RouterManager` тоже наследует CRM (транспорт, не наблюдаемость) — получит `set_sink_enabled` и станет адресуем командой, снимающей message-канал. Нужен whitelist `logger|error|stats` + тест.
- **Не вводить** промежуточный `ObservabilityManagerBase(CRM)` — это новый слой в MRO, запрещён инвариантом «меньше слоёв».

**Why:** увидев «у stats нет set_sink_enabled», естественно дописать его в `stats_manager.py` — и получить третью копию. Владелец требует обратного направления: общее едет ВВЕРХ в базу, потомки только специализируются. Совпадает с инвариантом «меньше слоёв»: подъём в существующую базу — не новый слой, а снятие дублей.

**How to apply:** прежде чем добавлять возможность одному из трёх — спросить, не общая ли она. Общая → в `ChannelRoutingManager`. Исключение: то, чего у потомка физически не бывает (напр. `ErrorFloor` — записи severity error/critical, у stats их нет; в базе стал бы мёртвым кодом). Связано: [[all-components-base-manager]], [[logger-error-stats-managers]], [[fewer-layers]].
