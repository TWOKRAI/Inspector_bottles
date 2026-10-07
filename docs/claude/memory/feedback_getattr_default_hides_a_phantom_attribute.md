---
name: feedback_getattr_default_hides_a_phantom_attribute
description: "getattr(x, 'name', None) на несуществующем имени (phantom attribute) даёт вечный тихий None: ветка мертва, ошибки нет — перед удалением holder/bridge грепнуть все getattr против класса"
module: [frontend_module, process_manager_module]
mechanism: [dead-code, error-handling]
metadata:
  type: feedback
---

**Ловушка.** `getattr(obj, "name", None)` на имени, которого у класса нет и не было, возвращает `None` всегда. Ветка «если есть» никогда не исполняется, а читатель считает её живой.

**Доказательства (cross-tab Ф.G, по сводке аудита 2026-10-04):**
- `getattr(services.commands, "action_bus", None)` стоял в 9 местах; метода у orchestrator не было никогда. `bus.execute` при `bus=None` молча терял правки полей — боевой баг.
- `getattr(services.topology, "_holder", None)`: при удалении holder вернёт `None` без ошибки.
- `TopologyBridge` не имеет свойства `topology` — пикер пуст.
- три `getattr(services.registers, "_rm")`.

Проверка 2026-10-04: `git grep -n 'getattr(services.commands, "action_bus"'` по коду даёт 0 мест (остались только планы); это исторические доказательства, живых сайтов нет.

**Правило.** Перед удалением или переездом holder / bridge грепнуть все `getattr(..., "имя", None)` против определения класса. Заменить атрибутом Protocol или громким отказом (`AttributeError` / явная ошибка).

Родня: [[feedback_unused_paths_are_contracts]], [[feedback_unparsed_is_not_absent]].
