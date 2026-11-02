# health — наблюдаемость отказов процесса (Ф2 Task 2.1, ADR-PM-010)

Примитив, на который опираются волны C (2.4/2.5, ~30 сайтов `report_error`) и
breaker (2.2). Плагин видит только фасад `ctx.health`.

## API для плагинов (`ctx.health`)

```python
def configure(self, ctx):
    try:
        frame = self.camera.grab()
    except CameraError as exc:
        ctx.health.report_error(exc, context="camera.grab")  # учесть + last_error
        ctx.health.degraded("камера недоступна")              # явная деградация
```

- `report_error(exc, context=None, throttle=5.0)` — инкремент счётчика `errors`,
  запись `last_error` (тип/сообщение/context/ts), дросселированный лог. Счётчик
  растёт всегда (честность для breaker), даже под throttle/лог-only.
- `set_status(status, reason=None)` / `degraded(reason)` / `failed(reason)` /
  `ok(reason=None)` — заявка статуса от имени этого плагина (`ok`|`degraded`|`failed`).

## Заявки владельцев (ADR-PM-058, C-66)

Статус процесса один, заявлять его могут несколько владельцев: плагины (`ctx.health`, владелец —
`source`, то есть имя экземпляра плагина), breaker и прямые вызовы `HealthState` без `owner` (команда
`health.report`, анонимный владелец `""`, один на процесс).

- `ok` снимает только заявку этого владельца. Статус процесса станет `ok`, когда заявок не осталось.
- `degraded`/`failed` заменяют заявку владельца целиком, и она становится самой поздней. Повтор тех же
  `(status, reason)` позицию не меняет.
- Закрытие breaker снимает только заявку breaker. Заявку, которую гонка оставила при закрытом breaker,
  снимает следующий такт `poll()` (heartbeat).
- `health.report status=ok` снимает только заявку анонимного владельца, чужие заявки не трогает.
- Эффективный статус: самая поздняя `failed`, иначе самая поздняя `degraded`, иначе `ok`. Причина берётся
  из выбранной заявки. При `ok` причина — текст этого вызова `ok("текст")`.
- `failed` breaker'ом не понижается. При открытом breaker причина плагина, поставленная раньше открытия,
  наверх не выходит: оператор видит `breaker open…` до закрытия.
- Журнал, dirty и `updated_at` меняются только при изменении эффективного значения. Наружу уходит прежняя
  одна строка `degraded_reason`, схема полей не менялась.

## Контракт путей state-дерева (`schema.py`)

```
processes.<name>.health.status           # "ok" | "degraded" | "failed"
processes.<name>.health.errors           # int — счётчик report_error
processes.<name>.health.last_error        # dict|None: {type,message,context,ts}
processes.<name>.health.degraded_reason  # str|None
processes.<name>.health.updated_at        # float epoch
```

Пути/поля зафиксированы как контракт (`health_root`/`health_path`, `HealthField`,
`HEALTH_FIELDS`) — стережёт `tests/test_health_schema.py`. Менять дословно дорого.

## Как это публикуется

`ctx.health` → единый на процесс `HealthState` (на `services._health_state`) →
`ProcessHeartbeat._publish_health_to_tree()` снимает грязный снапшот и шлёт через
`_state_proxy.set(...)` (тот же self-publish канал, что телеметрия fps/latency).
Rate-limit: state — по такту heartbeat; лог — окно `throttle`.

## Диагностика через backend_ctl

```python
drv.send_command("preprocessor", "health.report", {"context": "selftest", "message": "boom"})
drv.send_command("preprocessor", "health.status")   # снапшот здоровья
```

## Откат

`INSPECTOR_HEALTH_LOG_ONLY=1` — `report_error`/`set_status` только логируют,
state-дерево не трогают (публикация вырождается в no-op).
```
