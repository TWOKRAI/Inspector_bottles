---
name: feedback-logger-error-stats-managers
description: Логирование через logger_manager, ошибки через error_manager, статистика через statistics_manager — все три заложены в base_manager через ObservableMixin. Никаких print/logging.getLogger/local counters.
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
