# mixins — общие паттерны для подменеджеров SRM

## ManagerStatsMixin

Единый паттерн `get_stats()` для memory, queues, events.

### Использование

```python
from ..mixins import ManagerStatsMixin

class XxxManager(BaseManager, ..., ManagerStatsMixin):
    def get_stats(self) -> Dict[str, Any]:
        section_stats = {
            **self._stats,
            # ... специфичные метрики
        }
        return self._merge_stats("section_name", section_stats)
```

### Эталон

- **memory** — [memory/memory_manager.py](../memory/memory_manager.py), секция `"memory"`
- **queues** — секция `"queues"`
- **events** — секция `"events"`
