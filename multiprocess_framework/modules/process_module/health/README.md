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
  `ok(reason=None)` — явная смена статуса (`ok`|`degraded`|`failed`).

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
