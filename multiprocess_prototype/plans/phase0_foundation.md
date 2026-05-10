# Phase 0: Foundation (Heartbeat)

**Статус:** ✅ DONE

## Цель

Доказать что фреймворк загружается с 1 GenericProcess + 1 плагин.
Минимальный скелет без IPC, без SHM, без GUI.

## Созданные файлы

| Файл | Назначение |
|------|-----------|
| `__init__.py` | Package marker |
| `run.py` | Точка входа, venv-detect, прямой вызов main |
| `main.py` | bootstrap: discover → load JSON → validate → launch |
| `plugins/heartbeat/config.py` | HeartbeatPluginConfig (SchemaBase) |
| `plugins/heartbeat/plugin.py` | HeartbeatPlugin — LOOP worker, логирует "alive" |
| `topology/phase0_heartbeat.json` | JSON topology: 1 процесс "monitor" |

## Верификация

```bash
python multiprocess_prototype/run.py
# Лог: logs/monitor/messages.log
# Ожидаем: "[heartbeat #N] alive" каждые 2 секунды
# Ctrl+C → graceful shutdown
```

## Что доказано

- PluginRegistry.discover() находит плагины автоматически
- SystemBlueprint.model_validate() загружает topology из JSON
- GenericProcess загружает plugin через importlib в дочернем процессе
- Plugin lifecycle работает: configure → start → worker loop → shutdown
- Dict at Boundary соблюдается (config как dict через процессную границу)

## Замечания

- Логи пишутся в файлы (`logs/`), не в stdout — стандартное поведение фреймворка
- Warning "Failed to set priority" — некритично (платформозависимая фича Windows)
- `process_runner.py` требует project root в sys.path дочернего процесса (решено через CWD)
