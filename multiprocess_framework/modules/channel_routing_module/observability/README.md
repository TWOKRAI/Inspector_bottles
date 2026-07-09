# observability — фасад наблюдаемости модуля (ObservabilityHub)

Слой **уровня 0** конструктора (задача Ф5.15). Превращает модуль в «электронное
устройство»: у фасада три выхода-сигнала — **log / error / stats**. Все подмодули
и классы модуля эмитят в них через `ObservableMixin`, а снаружи мониторинг и
доставка работают **только через фасад**, не залезая внутрь модуля.

## Зачем

Раньше, чтобы собрать логи/ошибки/метрики модуля, нужно было знать его
внутренности (какие подмодули и классы что эмитят). ObservabilityHub сводит всё к
одной точке: владелец процесса дренирует три канала фасада и раздаёт записи в
`LoggerManager` / `ErrorManager` / `StatsManager` — сам решая when/where.

## Две плоскости фасада

| Плоскость | Методы | Кто | Разрушающая? |
|-----------|--------|-----|--------------|
| **data-plane** | `drain_logs/errors/stats/all` | владелец процесса (по heartbeat) | да — забирает и опустошает |
| **monitor-plane** | `get_info`, `dropped` | внешний монитор | **нет** — читает, не касаясь внутренностей и не съедая записи |

Мониторинг никогда не лезет внутрь модуля — только читает `get_info()` фасада.

## Компоненты

- **`ObservabilityHub(module_name, capacity, overflow, clock)`** — перехватчик:
  3 `BoundedChannel` + duck-type протоколы `LoggerLike`/`StatsLike`/`ErrorLike`.
- **`BoundedChannel(name, capacity, overflow)`** — потокобезопасный кольцевой
  bounded-буфер (`IChannel`); при переполнении роняет запись по политике
  (`drop_oldest` | `drop_newest`) и растит счётчик потерь.
- **`protocols.py`** — `LoggerLike` / `StatsLike` / `ErrorLike`: контракт слотов
  `ObservableMixin`, который hub реализует целиком.

## Использование (drop-in, ноль правок в модулях)

```python
from multiprocess_framework.modules.channel_routing_module import ObservabilityHub

hub = ObservabilityHub("worker_module", capacity=1024)   # overflow="drop_oldest"

# hub подставляется в слоты ObservableMixin — модуль не меняется:
manager = WorkerManager(..., logger=hub, stats=hub, error=hub)

# владелец процесса, по такту heartbeat:
for rec in hub.drain_logs():   logger_manager.dispatch(rec)
for rec in hub.drain_errors(): error_manager.track(rec)
for rec in hub.drain_stats():  stats_manager.record(rec)

# монитор (не разрушающий):
snapshot = hub.get_info()      # depth/dropped/written по каждому каналу
losses   = hub.dropped         # {'log': N, 'error': N, 'stats': N}
```

## Формат записи (pickle-safe dict, Dict at Boundary)

Общий конверт: `{"kind": "log|error|stats", "module": <tag>, "ts": <float>, ...}`.

- **log:** `severity`, `message`, `context` (из `**kwargs`).
- **error:** `error_type`, `message`, `traceback` (или `None`), `context`,
  `severity` (по умолчанию `"error"`; поднимается через `context["severity"]`).
- **stats:** `metric`, `value`, `metric_type` (`gauge`/`counter`/`timing`), `tags`.

Само исключение через границу процесса не гоняется — только его сериализованная
форма. Записи проходят `pickle` без потерь.

## Дизайн-решения

- **pull-drain, не `IBufferStrategy`** — доставка на дренаже владельцем, не push
  фоновым потоком (идея, pitfall #2). `BoundedChannel` — это `IChannel`, не буфер-стратегия.
- **drop_oldest + счётчик потерь** — переполнение не блокирует hot-path; потерю
  не замалчиваем (урок Ф3.3).
- **`track_error`/`record_error` возвращают non-None** — иначе `ObservableMixin`
  сделает fallback и запишет ошибку дважды.

Полностью — в [`../DECISIONS.md`](../DECISIONS.md) (ADR-CRM-007).

## Что дальше (не входит в Ф5.15)

- **Ф5.16** — wiring в composition root: раздача hub'ов в слоты выбранных
  non-hot-path модулей + сведение фасадов в глобальные менеджеры оркестратора
  (уровень 1) через `RouterManager` + контракты каналов + merge-батч.
- **Ф5.17** — контракт-тест разделения hub (доставка) ↔ `ctx.health` (агрегация).
