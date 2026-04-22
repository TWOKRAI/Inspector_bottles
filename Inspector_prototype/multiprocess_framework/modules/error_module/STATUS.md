# error_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 10 | _level_to_channel + log() override; severity routing РЕАЛЬНО используется |
| Тесты | 9 | ~25 тестов; level routing, fallback, track_error, integration |
| Документация | 10 | README, DECISIONS.md (ADR-EM-001…006), §6.14 в ARCHITECTURE.md |
| Связанность | 9 | Наследует LoggerManager (→ ChannelRoutingManager); никаких циклов |
| Дублирование | 10 | Нет дублирования — вся channel/buffer/registry логика через CRM |
| Работоспособность | 9 | WARNING/ERROR/CRITICAL → отдельные файлы; DEBUG/INFO → scope-based LoggerManager |

## Обновление 2026-04-03

- **`ErrorManager.__init__`**: `_level_to_channel` и `_include_stacktrace` задаются **до** `LoggerManager.__init__`, чтобы глобальный `LoggerManager._instance` (выставляется в конце `LoggerManager.__init__`) никогда не указывал на `ErrorManager` без `_level_to_channel` и не ловил `AttributeError` при косвенном логировании во время конструктора.

## Что сделано в CRM-миграции (Фаза 3)

- [x] `ErrorManagerConfig(SchemaBase)` в **`configs/error_manager_config.py`** — плоские поля; без кастомного `build()`
  - `critical_file_path`, `error_file_path`, `warnings_file_path` — пути к файлам severity-каналов
  - **`expand_error_manager_config()`** в **`core/error_config_assembly.py`** — единственное место merge severity + `channels` (ADR-107)
- [x] `_normalize_error_config()` — `None | dict | ErrorManagerConfig | build()` → **LoggerManagerConfig** (см. глобальные ADR-103, ADR-107)
- [x] Конфиг: **`configs/error_manager_config.py`** — `ErrorManagerConfig`
- [x] `_level_to_channel: Dict[str, str]` — прямой O(1) маппинг уровня в имя канала
- [x] `_setup_level_routes()` — строит `_level_to_channel` из severity-каналов (без LogDispatcher; см. logger_module ADR-LOG-001)
- [x] `log()` override — WARNING/ERROR/CRITICAL используют `_level_to_channel`; DEBUG/INFO → `super().log()`
- [x] `get_stats()` — включает `level_routes` маппинг

## Решённая архитектурная проблема

До Фазы 3: `_setup_level_routes()` дублировал маршруты в старом LogDispatcher, но `LoggerManager.log()`
никогда не вызывал `route_by_level()` → severity routing был мёртвым кодом. LogDispatcher удалён в logger_module (2026-04-09; см. **ADR-LOG-001**).

После Фазы 3: `ErrorManager.log()` переопределён. При WARNING/ERROR/CRITICAL — прямое обращение
к `_level_to_channel`, `enqueue(channel_name, record_dict)`. Severity routing РАБОТАЕТ.

## Чеклист рефакторинга

- [x] Этап 0: interfaces.py создан, STATUS.md создан
- [x] Этап 1: Модуль запускается — ErrorManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, severity routing, ErrorManagerConfig
- [x] Этап 3: ErrorManagerConfig(SchemaBase), _level_to_channel, log() override — routing РЕАЛЬНО работает
- [x] Этап 4: DECISIONS.md (ADR-EM-001…006), §6.14 в ARCHITECTURE.md
- [x] Этап 5: Тестовое покрытие (level routing, fallback, track_error, integration)
- [ ] Этап 6: Кастомный severity-канал (AlertChannel → Telegram/Slack через channels в конфиге)
- [ ] Этап 7: Интеграционный тест — приём ERROR от RouterManager
- [ ] Этап 8: Graceful shutdown — flush() + router unsubscribe; при необходимости покрытие > 85%; интеграция с process_manager_module

## Известные проблемы / Следующие шаги

- **configs/:** один файл схемы — `error_manager_config.py` (`ErrorManagerConfig`); дубликат `error_config.py` удалён (ADR-107)
- Кастомный AlertChannel (Telegram/Slack) через `channels` в ErrorManagerConfig — не реализован (этап 6).
- DEBUG/INFO в ErrorManager всё ещё идут через scope-based routing LoggerManager.

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | interfaces.py добавлен, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py улучшен (warning/info/critical/get_stats) | 1 |
| 2026-03-12 | Severity channels, level routing, ErrorManagerConfig, README | 2 |
| 2026-03-12 | CRM Фаза 3: ErrorManagerConfig(SchemaBase), _level_to_channel, log() override | 3 |
| 2026-03-31 | ADR-107: `error_config.py` удалён; `expand_error_manager_config`; плоский `ErrorManagerConfig` | 3 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
| 2026-04-10 | DECISIONS.md, ARCHITECTURE.md §6.14, тесты level routing/integration, README fix, `core/__init__.py` export | 4–5 |
