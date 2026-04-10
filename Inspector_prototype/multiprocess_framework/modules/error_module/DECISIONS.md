# error_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) · [`../logger_module/DECISIONS.md`](../logger_module/DECISIONS.md)

## ADR-EM-001: ErrorManager как наследник LoggerManager (не композиция)

- **Дата:** 2026-03-12
- **Статус:** принято
- **Контекст:** ErrorManager нуждается в каналах, буферизации, scope-based routing для DEBUG/INFO — всё есть в LoggerManager. Альтернатива: композиция (ErrorManager содержит LoggerManager).
- **Решение:** Наследование `ErrorManager(LoggerManager)`. Переиспользует CRM-инфраструктуру (ChannelRegistry, BatchBuffer, Dispatcher), добавляет только severity routing через `_level_to_channel` и `log()` override.
- **Не сливать:** ErrorManager остаётся отдельным модулем — severity routing опциональная специализация.
- **Отклонено:** Композиция — избыточная обёртка без выгоды.

## ADR-EM-002: Level-based routing через _level_to_channel dict

- **Дата:** 2026-03-12
- **Статус:** принято
- **Контекст:** Маппинг WARNING → warnings_file, ERROR → errors_file, CRITICAL → critical_file. Альтернатива: через CRM's Dispatcher.
- **Решение:** `Dict[str, str]` с O(1) lookup в `log()`. Проще и быстрее Dispatcher для 3 уровней.
- **Fallback:** Если канал отсутствует — используется `errors_file`.

## ADR-EM-003: _normalize_error_config() как модульная функция

- **Дата:** 2026-03-31
- **Статус:** принято
- **Решение:** Модульная функция в `error_manager.py`, не метод класса. Паттерн совпадает с logger_module.

## ADR-EM-004: expand_error_manager_config() в отдельном файле

- **Дата:** 2026-03-31
- **Статус:** принято
- **Решение:** `core/error_config_assembly.py` — единственное место merge severity-каналов. configs/ содержит только поля, core/ содержит логику сборки.

## ADR-EM-005: _level_to_channel инициализация до super().__init__()

- **Дата:** 2026-04-03
- **Статус:** принято
- **Контекст:** `LoggerManager.__init__()` выставляет `LoggerManager._instance = self`. Косвенные вызовы через `get_logger()` могут дёрнуть `ErrorManager.log()` → `self._level_to_channel` → `AttributeError`.
- **Решение:** `self._level_to_channel = {}` ДО `super().__init__()`. Пустой dict безопасен: все уровни fallback на parent.

## ADR-EM-006: Ленивый экспорт ErrorManager из `core/__init__.py`

- **Дата:** 2026-04-10
- **Статус:** принято
- **Контекст:** Прямой `from .error_manager import ErrorManager` в `core/__init__.py` выполняется при любом `from error_module.core.error_config_assembly import …` и ломает цель ленивой загрузки в `error_module.__init__` (ранний импорт `logger_module` при плоском `pythonpath`).
- **Решение:** `ErrorManager` в `__all__` и доступ через `__getattr__` в `core/__init__.py`; `expand_error_manager_config` импортируется eager как и раньше.
