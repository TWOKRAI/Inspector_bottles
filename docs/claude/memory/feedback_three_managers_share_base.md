---
name: three-managers-share-base
description: "logger/error/stats — братья-близнецы: общее поднимать в ChannelRoutingManager, а не дописывать третью копию"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 4ed2135f-17e6-4937-9a20-79432d839934
  modified: 2026-07-26T15:17:45.810Z
---

Требование владельца 2026-07-26: «logger_manager, error_manager, statistics_manager — братья-близнецы и должны иметь одну базу, чтоб не дублировать. Наследоваться.»

**Фактическая иерархия (сверена 2026-07-26):** общая база уже есть — `ChannelRoutingManager` (сам от `BaseManager` + `ObservableMixin`). Но она тонкая: хозяйство наблюдаемости лежит в `LoggerCore`, а `StatsManager` наследует CRM напрямую, мимо него.

```
ChannelRoutingManager
    ├── LoggerCore ──┬── LoggerManager
    │                └── ErrorManager
    └── StatsManager   ← мимо LoggerCore
```

Отсюда дубли: резолв путей файлов (`_resolved_file_path` vs прямой импорт `resolve_log_file_path`) и батчинг (`_setup_batcher`/`_flush_batch` vs `_enqueue_to_buffer`/`_do_flush`). И дыры: у stats нет `set_sink_enabled`, `add_log_tap`/`_emit_to_taps`, `_fallback_log`.

**Why:** увидев «у stats нет set_sink_enabled», естественно дописать его в `stats_manager.py` — и получить третью копию. Владелец требует обратного направления: общее едет ВВЕРХ в базу, потомки только специализируются. Совпадает с инвариантом «меньше слоёв»: подъём в существующую базу — не новый слой, а снятие дублей.

**How to apply:** прежде чем добавлять возможность одному из трёх — спросить, не общая ли она. Общая → в `ChannelRoutingManager`. Исключение: то, чего у потомка физически не бывает (напр. `ErrorFloor` — записи severity error/critical, у stats их нет; в базе стал бы мёртвым кодом). Связано: [[all-components-base-manager]], [[logger-error-stats-managers]], [[fewer-layers]].
