# error_module — Статус рефакторинга

## Текущий этап: 3 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 10 | _level_to_channel + log() override; severity routing РЕАЛЬНО используется |
| Тесты | 7 | ~30 тестов; все проходят; нужны: интеграционный тест severity routing |
| Документация | 9 | README переписан в стиле router_module с диаграммой |
| Связанность | 9 | Наследует LoggerManager (→ ChannelRoutingManager); никаких циклов |
| Дублирование | 10 | Нет дублирования — вся channel/buffer/registry логика через CRM |
| Работоспособность | 9 | WARNING/ERROR/CRITICAL → отдельные файлы; DEBUG/INFO → scope-based LoggerManager |

## Обновление 2026-04-03

- **`ErrorManager.__init__`**: `_level_to_channel` и `_include_stacktrace` задаются **до** `LoggerManager.__init__`, чтобы глобальный `LoggerManager._instance` (выставляется в конце `LoggerManager.__init__`) никогда не указывал на `ErrorManager` без `_level_to_channel` и не ловил `AttributeError` при косвенном логировании во время конструктора.

## Что сделано в CRM-миграции (Фаза 3)

- [x] `ErrorManagerConfig(SchemaBase)` в **`configs/error_manager_config.py`** — плоские поля; без кастомного `build()`
  - `critical_file_path`, `error_file_path`, `warnings_file_path` — пути к файлам severity-каналов
  - **`expand_error_manager_config()`** в **`core/error_config_assembly.py`** — единственное место merge severity + `channels` (ADR-107)
- [x] `_normalize_error_config()` — `None | dict | ErrorManagerConfig | build()` → **LoggerManagerConfig** (см. ADR-103, ADR-107)
- [x] Конфиг: **`configs/error_manager_config.py`** — `ErrorManagerConfig`
- [x] `_level_to_channel: Dict[str, str]` — прямой O(1) маппинг уровня в имя канала
- [x] `_setup_level_routes()` — строит `_level_to_channel` из severity-каналов
- [x] `log()` override — WARNING/ERROR/CRITICAL используют `_level_to_channel`; DEBUG/INFO → `super().log()`
- [x] `get_stats()` — включает `level_routes` маппинг

## Решённая архитектурная проблема

До Фазы 3: `_setup_level_routes()` регистрировал маршруты в LogDispatcher, но `LoggerManager.log()`
никогда не вызывал `route_by_level()` → severity routing был мёртвым кодом.

После Фазы 3: `ErrorManager.log()` переопределён. При WARNING/ERROR/CRITICAL — прямое обращение
к `_level_to_channel`, `enqueue(channel_name, record_dict)`. Severity routing РАБОТАЕТ.

## Чеклист рефакторинга

- [x] Этап 0: interfaces.py создан, STATUS.md создан
- [x] Этап 1: Модуль запускается — ErrorManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, severity routing, ErrorManagerConfig
- [x] Этап 3: ErrorManagerConfig(ChannelRoutingConfig), _level_to_channel, log() override — routing РЕАЛЬНО работает
- [ ] Этап 4: Кастомный severity-канал (AlertChannel → Telegram/Slack через channels в конфиге)
- [ ] Этап 5: Интеграционный тест — приём ERROR от RouterManager
- [ ] Этап 6: Graceful shutdown — flush() + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85% (level routes, get_stats, severity channels)
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы / Следующие шаги

- **configs/:** один файл схемы — `error_manager_config.py` (`ErrorManagerConfig`); дубликат `error_config.py` удалён (ADR-107)
- Кастомный AlertChannel (Telegram/Slack) через `channels` в ErrorManagerConfig — не реализован (этап 4).
- Интеграционный тест с реальной записью в файл не написан.
- DEBUG/INFO в ErrorManager всё ещё идут через scope-based routing LoggerManager.

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | interfaces.py добавлен, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py улучшен (warning/info/critical/get_stats) | 1 |
| 2026-03-12 | Severity channels, level routing, ErrorManagerConfig, README | 2 |
| 2026-03-12 | CRM Фаза 3: ErrorManagerConfig(ChannelRoutingConfig), _level_to_channel, log() override | 3 |
| 2026-03-31 | ADR-107: `error_config.py` удалён; `expand_error_manager_config`; плоский `ErrorManagerConfig` | 3 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
