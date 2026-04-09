# dispatch_module — Архитектурные решения

## ADR-130: Извлечение ScenarioManager из Dispatcher

Сценарии (CRUD + `dispatch_scenario`) вынесены в `core/scenarios.py`. `Dispatcher` хранит `ScenarioManager` через композицию и делегирует вызовы публичным методам без изменения сигнатур.

## ADR-131: Удаление backward compat API

Параметры `logger_manager=`, `error_manager=`, `statistics_manager=`, `enable_logging`, `enable_error_tracking`, `enable_statistics` удалены из `Dispatcher.__init__`. Атрибуты `self.handlers`, `self.name`, `self.strategy` удалены. Используйте `managers={'logger': ..., 'error': ..., 'statistics': ...}` и `config={...}`. Для чтения стратегии по умолчанию — свойство `default_strategy`.

## ADR-132: Удаление AdvancedDispatcher alias

`AdvancedDispatcher` был alias на `Dispatcher`. Удалён из публичного API — используйте `Dispatcher`.
