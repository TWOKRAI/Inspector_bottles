---
paths:
  - "multiprocess_prototype/**"
  - "multiprocess_framework/**"
  - "Plugins/**"
  - "Services/**"
---

# Правило: только LoggerManager

В коде проекта **запрещён** `import logging` (stdlib). Все логи — через единый `LoggerManager` из `multiprocess_framework.modules.logger_module`.

## Почему

- Единый формат, каналы (file/console/http), батчинг и фильтрация по scope/module.
- Без LoggerManager строки stdlib-`logging` теряются в multiprocess-окружении или конфликтуют с настройками очередей.
- Контролируемый шум: фильтр `module=` позволяет легко выключить/включить трассировку конкретного слоя.

## Как использовать

### Минимум для нового файла

```python
from multiprocess_framework.modules.logger_module import get_logger


def _log(msg: str, level: str = "info") -> None:
    """Записать в LoggerManager (если инициализирован), иначе тихо."""
    lm = get_logger()
    if lm is None:
        return
    getattr(lm, level)(msg, module="my_module")


def do_thing(x):
    _log(f"[trace my_module] do_thing(x={x!r})")
```

### В плагине (есть `ctx`)

В `PluginContext` уже есть тонкая обёртка:
```python
ctx.log_info("hello")
ctx.log_warning("...")
ctx.log_error("...")
```
Использовать её — не нужно ничего импортировать.

### Уровни

- `debug` — детальная трассировка (отключена в production)
- `info` — нормальный поток (один раз на event)
- `warning` — отклонения от happy path, восстановимые
- `error` — поломка, требует внимания
- `critical` — фатально, процесс остановлен

## Запрещено

- `import logging` в production-коде (тесты — допускают `caplog` fixture pytest)
- `print()` для отладки (используй `_log(...)` или `ctx.log_info`)
- `logger = logging.getLogger(__name__)` — заменить на helper выше

## Допустимо

- В тестах: `caplog` fixture pytest для проверки вывода
- В одноразовых dev-скриптах вне основной кодовой базы (`scripts/`) — `print()` допустим
- В существующих файлах с `logger = logging.getLogger(...)`: тонкий shim делегирующий в `get_logger()` — приемлем как переходный шаг, но новый код пишет напрямую через `_log()` helper

## Шаблон trace-логов для диагностики

При отладке cross-layer проблем (GUI → ActionBus → IPC → worker) используйте префикс `[trace <модуль>]`:

```
[trace bus_rm] set_field_value: pilot_widgets.enabled = False (old=True)
[trace field_set] apply: pilot_widgets.enabled = False (bridge=True)
[trace bridge] on_field_set(pilot_widgets.enabled=False) → resolved=ResolvedCommand(...)
[trace bridge] send_field_command(target=pilot, cmd=set_config, ...)
```

После закрытия диагностики trace-строки переводят в `debug` или удаляют — но `module=` фильтрация позволяет оставлять их в коде безопасно.
