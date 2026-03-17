# multiprocess_prototype\stage_reports\archived\STAGE_07_LOGGING_STATS.md
# Этап 7: Обратная связь, статистика и логирование

**Дата:** 2026-03-15  
**Статус:** ✅ Выполнено

---

## Цель

Интеграция с менеджерами фреймворка:
- **Метрики** → StatsManager
- **Логи** → LoggerManager (system.log)
- **Ошибки** → ErrorManager (errors.log)
- **Сообщения** → RouterManager + дублирование в LoggerManager (messages.log) для отладки

Все пути настраиваются через конфигурацию.

---

## Реализовано

### 7.1 Конфигурация приложения (`configs/app_config.py`)

- `get_log_dir()` — путь к каталогу логов (env `INSPECTOR_LOG_DIR`, по умолчанию `logs/`)
- `get_default_managers_config(log_dir)` — конфигурация менеджеров:
  - **logger**: system.log, messages.log, scopes (SYSTEM, BUSINESS, PERFORMANCE), modules (router_messages)
  - **error**: errors.log, critical.log, warnings.log
  - **stats**: enable_logging
  - **router**: duplicate_messages_to_logger

### 7.2 Обновление конфигов процессов

Все конфиги (Camera, Processor, Renderer, Robot, Gui) в `build()` добавляют:
```python
"managers": get_default_managers_config()
```

### 7.3 Изменения в фреймворке (process_module)

**ProcessManagers** (`process_managers.py`):
- LoggerManager: поддержка полного dict-конфига через `LogConfig.from_dict()` при наличии `channels`
- ErrorManager: создаётся при наличии конфига `managers.error`, регистрируется как `errors`
- RouterManager: middleware для дублирования сообщений в LoggerManager (module=`router_messages`) при `duplicate_messages_to_logger=True`

**ErrorManager** (`error_manager.py`):
- Добавлен метод `track_error(error, context)` для интеграции с ObservableMixin

### 7.4 Метрики в процессах

| Процесс | Метрика | Описание |
|---------|---------|----------|
| Camera | `camera.frames_captured` | Каждые 100 кадров |
| Camera | `camera.actual_fps` | Фактический FPS |
| Processor | `processor.processing_time_ms` | Время обработки кадра |
| Processor | `processor.detections_count` | Количество детекций |
| Renderer | `renderer.frames_rendered` | Отрисованные кадры |
| Renderer | `renderer.detections_per_frame` | Детекций на кадр |

### 7.5 Файлы логов

| Файл | Содержимое |
|------|------------|
| `logs/system.log` | Системные логи (SYSTEM, BUSINESS, PERFORMANCE scopes) |
| `logs/errors.log` | Ошибки (ERROR level) |
| `logs/critical.log` | Критические ошибки |
| `logs/warnings.log` | Предупреждения |
| `logs/messages.log` | Дублирование сообщений RouterManager для отладки |

---

## Опциональность (обратная совместимость фреймворка)

Все изменения в `process_module` и `error_module` **опциональны** и не влияют на приложения без конфигурации:

| Функция | Условие включения | Без конфига |
|---------|-------------------|-------------|
| ErrorManager | `managers.error` не пустой | Не создаётся |
| Дублирование сообщений | `managers.router.duplicate_messages_to_logger=True` | Выключено |
| LoggerManager dict-конфиг | `managers.logger.channels` присутствует | Используется старая логика setattr |

Приложения, не передающие `managers` в proc_dict, работают как раньше.

---

## Настройка

### Переменные окружения

- `INSPECTOR_LOG_DIR` — каталог для логов (по умолчанию `logs`)

### Кастомизация конфига

В `configs/app_config.py` можно изменить `get_default_managers_config()` для своих путей и параметров.

---

## Ссылки

- LoggerManager: `multiprocess_framework/refactored/modules/logger_module/README.md`
- ErrorManager: `multiprocess_framework/refactored/modules/error_module/README.md`
- StatsManager: `multiprocess_framework/refactored/modules/statistics_module/README.md`
- RouterManager: `multiprocess_framework/refactored/modules/router_module/README.md`
