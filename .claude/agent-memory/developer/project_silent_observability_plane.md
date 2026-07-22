---
name: silent-observability-plane
description: ObservableMixin._log_* — тихий no-op без зарегистрированного logger; у QueueRegistry/SRM его нет ни в одном продовом процессе, поэтому счётчик может расти при нуле строк в логах
metadata:
  type: project
---

`ObservableMixin._log_*` вызывает `_call_manager("logger", ...)`, а тот при
пустом/выключенном слоте **тихо возвращает `None`**. Ни исключения, ни счётчика.
Значит «в коде есть `self._log_error(...)`» НЕ означает «строка куда-то доедет».

Два независимых механизма опустошают слот:
1. **Никто не передаёт logger.** Все три продовых конструктора SRM идут без него —
   `spawner.py`, `bundle_builder.py`, `process_runner.py`. Параметр
   `SharedResourcesManager(logger=...)` в проде мёртв, поэтому вложенные
   `QueueRegistry` / `MemoryManager` рождаются немыми.
2. **Pickle.** `ObservableMixin.__getstate__` выкидывает `_registry`, а
   `__setstate__` создаёт пустой. `SRM.reinitialize_in_child()` чинит
   EventManager/MemoryManager/PSR, но logger не переригистрирует — после
   Windows-spawn слот пуст даже если его заполнили в родителе.

**Why:** из-за этого 26 тысяч событий потери груза дали 0 строк во всём `logs/`;
расследование установило механизм потери, но не смогло назвать получателя —
именно потому, что несущая имя строка исчезала. Цена — час разбора вместо минуты.

**How to apply:** увидел «счётчик растёт, а лога нет» — сначала проверь
`obj.has_manager("logger")`, не ищи баг в логике. Для сообщений из компонентов,
которым штатную плоскость не проводят, канон проекта — модульный
`_fallback_logger = logging.getLogger(__name__)` (образцы: `logger_module/
channels/log_channel.py`, `core/logger_core.py`, `queues/core/manager.py`).
Важно: этот fallback уходит в stderr — stdlib-logging в проекте не
сконфигурирован ни одним handler'ом, в `logs/*/messages.log` он НЕ попадёт.
Проводить настоящий logger в `QueueRegistry` без правки соседних вызовов опасно:
`send_to_queue` логирует отказ на КАЖДЫЙ промах (на живом рецепте ~17/с,
без троттлинга) — получишь второй случай раздутого лога. См.
[[project_observability_facade_extension]].
