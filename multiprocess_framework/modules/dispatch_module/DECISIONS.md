# dispatch_module — Архитектурные решения

## ADR-DSP-001 (was ADR-130): Извлечение ScenarioManager из Dispatcher

Сценарии (CRUD + `dispatch_scenario`) вынесены в `core/scenarios.py`. `Dispatcher` хранит `ScenarioManager` через композицию и делегирует вызовы публичным методам без изменения сигнатур.

## ADR-DSP-002 (was ADR-131): Удаление backward compat API

Параметры `logger_manager=`, `error_manager=`, `statistics_manager=`, `enable_logging`, `enable_error_tracking`, `enable_statistics` удалены из `Dispatcher.__init__`. Атрибуты `self.handlers`, `self.name`, `self.strategy` удалены. Используйте `managers={'logger': ..., 'error': ..., 'statistics': ...}` и `config={...}`. Для чтения стратегии по умолчанию — свойство `default_strategy`.

## ADR-DSP-003 (was ADR-132): Удаление AdvancedDispatcher alias

`AdvancedDispatcher` был alias на `Dispatcher`. Удалён из публичного API — используйте `Dispatcher`.

## ADR-DSP-004: Асимметрия дефолта `expects_full_message` (Dispatcher vs RouterManager)

`expects_full_message` — НЕ vestigial-флаг (ошибочно помечался таким; ревью M4 — refuted). Он реально ветвит поведение вызова handler'а: `True` → handler получает полный конверт сообщения (`dict` со всеми полями), `False` → только `data`-полезную нагрузку. Ветвление: `core/dispatcher.py` (`_invoke_handler`), `core/base_dispatcher.py`, `strategies/chain_match.py`, `core/scenarios.py`.

**Асимметрия дефолтов (намеренная, фиксируется здесь чтобы не путать):**
- `Dispatcher.register_handler(...)` — дефолт `expects_full_message=False` (handler получает `data`).
- `RouterManager.register_message_handler(...)` — дефолт `expects_full_message=True` (handler получает полный конверт; это полный relay в `message_dispatcher`, не сужённый контракт).

Следствие: builtin worker-команды (`worker.create/remove/update/start/stop/restart`) регистрируются через `Dispatcher` с дефолтом `False` → получают только `data`. Хендлеры, регистрируемые напрямую через `RouterManager.register_message_handler` без явного указания, получают полный конверт.

**Правило:** при регистрации handler'а указывай `expects_full_message` ЯВНО, не полагайся на дефолт пути регистрации. Удалять флаг нельзя (несёт реальное поведение). Кандидат на будущее (вне scope §11.19): унифицировать дефолт либо запретить регистрацию без явного указания.
