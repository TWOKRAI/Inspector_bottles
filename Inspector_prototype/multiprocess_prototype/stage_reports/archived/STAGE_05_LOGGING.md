# multiprocess_prototype\stage_reports\archived\STAGE_05_LOGGING.md
# Stage 5: Полноценное логирование

## Цель

Улучшить логирование: консольный канал, поддержка DEBUG через переменную окружения, контекст процесса в логах.

## Изменения

### 1. Консольный канал

В `configs/app_config.py` добавлен канал `console`:

```python
"console": {
    "type": "console",
    "enabled": True,
    "format": "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s",
},
```

Канал подключён к областям SYSTEM, BUSINESS, PERFORMANCE, DEBUG.

### 2. DEBUG логи

- **INSPECTOR_LOG_LEVEL** — переменная окружения для уровня логирования (INFO, DEBUG, WARNING, ERROR, CRITICAL).
- По умолчанию: `INFO`.
- При `INSPECTOR_LOG_LEVEL=DEBUG` в логах появляются DEBUG-сообщения.

Добавлена область **DEBUG** с `min_level: DEBUG` и каналами `system_file`, `console`.

### 3. Контекст процесса

**ProcessLifecycle** (`process_module/lifecycle/process_lifecycle.py`):
- После инициализации: `logger.push_context(proc_name=self.process.name)`
- Перед shutdown: `logger.pop_context()`

**LogChannel / ConsoleChannel** (`logger_module/channels/log_channel.py`):
- В `write()` из `record['extra']` берётся `proc_name` и передаётся в `log_record.proc_name`.
- Формат логов: `[%(proc_name)s]` — имя процесса или `-`, если контекст не задан.

### 4. Формат логов

Все каналы используют единый формат:

```
%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s
```

Пример: `2025-03-15 12:00:00 [INFO] [camera] main: Process 'camera' initialized successfully`

## Результат

- Логи выводятся в консоль и в файлы.
- Уровень логирования задаётся через `INSPECTOR_LOG_LEVEL`.
- В каждой записи лога отображается имя процесса (`proc_name`).
