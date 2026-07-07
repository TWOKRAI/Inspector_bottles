# Идея: ObservabilityHub — фасад наблюдаемости модуля (входы/выходы + каналы err/log/stats)

> Статус: идея владельца (2026-07-07), зафиксирована для триажа на ближайшем гейте.
> Прецедент оформления: debug-plane-idea.md.

## Желание владельца (дословно по смыслу)

У каждого модуля — фасад со своим интерфейсом: входы, выходы, **канал ошибок**,
**канал логирования** (и статистики). Все ошибки/логи модуля заходят в эти каналы,
а владелец только контролирует каналы и считывает с них, отправляя в LoggerManager /
ErrorManager / StatsManager сам.

## Ключевой вывод оценки

**Это не новая система, а один недостающий слой поверх существующих примитивов.**

Что уже есть:

| Примитив | Что даёт | Где |
|---|---|---|
| `ObservableMixin` | точка эмиссии: весь модуль пишет через `_log_*`/`_record_*`/`_track_error`, доставка определяется содержимым слотов `{'logger','stats','error'}` | `base_manager/mixins/observable_mixin.py` |
| `channel_routing_module` | готовый примитив канала: `IChannel`, thread-safe `ChannelRegistry`, `IBufferStrategy` | `channel_routing_module/` |
| Порты плагинов | «входы/выходы» уже first-class у плагинов (Port), у framework-модулей — `interfaces.py` | `process_module/plugins/port.py` |
| `ctx.health` (Ф2) | агрегация отказов (счётчик/статус/breaker) — НЕ доставка | `process_module/health/` |

Чего нет: **фасада-перехватчика** между модулем и менеджерами.

## Эскиз

`ObservabilityHub(module_name)` — объект, реализующий duck-type протоколы
logger (`debug/info/warning/error/critical`), stats (`record_metric/increment/
record_timing/gauge`), error (`track_error/record_error`). Вместо доставки —
кладёт записи в свои bounded-каналы (`log_channel`, `error_channel`,
`stats_channel`, на базе `IChannel`/`IBufferStrategy`) с тегом модуля.

Вставка — в слоты ObservableMixin при сборке:

```python
hub = ObservabilityHub("worker_module", capacity=1024, overflow="drop_oldest")
manager = WorkerManager(..., logger=hub, stats=hub, error=hub)  # duck-type
# владелец (composition root процесса):
for rec in hub.drain_logs():   logger_manager.dispatch(rec)
for rec in hub.drain_errors(): error_manager.track(rec)
for rec in hub.drain_stats():  stats_manager.record(rec)
```

Дренаж — по такту heartbeat процесса (прецедент: health self-publish Ф2.1)
или колбэком/потоком; политика — у владельца.

## Что это даёт

- Единая контролируемая точка per-module: фильтр/троттлинг/глушение/снятие метрик.
- Владелец сам решает, когда и куда сливать (в т.ч. в несколько приёмников).
- **Ноль изменений внутри модулей** — ObservableMixin уже развязал эмиссию от
  доставки; миграция = только wiring в composition root.
- Тестируемость: assert по содержимому канала вместо моков менеджеров.
- Шаг к нарративу «конструктор»: модуль = компонент с портами
  (data in/out + err/log/stats out).

## Подводные камни (в дизайн обязательно)

1. **Hot-path**: лишний хоп на каждый лог/метрику → bounded-буфер, политика
   drop-oldest + СЧЁТЧИК потерь (урок Ф3.3: терять можно, молчать — нельзя).
2. **Асинхронность доставки**: лог уезжает на дренаже, не в момент эмиссии
   (идеологический прецедент — BatchBuffer в LoggerManager).
3. **Метаданные**: сохранить severity-роутинг ErrorManager и context; записи
   каналов — pickle-safe dict (Dict at Boundary).
4. **Не дублировать health**: канал = доставка содержимого, health = агрегация.
   Кормятся из одной точки эмиссии, живут раздельно.
5. **Кто дренирует при смерти владельца** — teardown-политика (flush или drop).

## Куда в план

Кандидат: Ф5 (generic bootstrap «рыбы» — hub логично раздаётся из рыбы) или
Ф7 G-track (QoS/hot-path). Не блокирует Ф2/Ф3. Триаж — на ближайшем гейте
с владельцем.
