# logger_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-LOG-001 (was ADR-140): Удаление LogDispatcher

**Статус:** принято  
**Контекст:** LogDispatcher дублировал CRM's Dispatcher для channel/level routing.  
**Решение:** Удалён. LogRecord перенесён в `core/log_types.py`. ErrorManager использует `_level_to_channel` + прямой `channel.write()`, без LogDispatcher.

## ADR-LOG-002 (was ADR-141): Удаление BatchManager (batcher/)

**Статус:** принято  
**Контекст:** BatchManager (135 LOC) дублировал CRM's BatchBuffer.  
**Решение:** Удалён целиком. LoggerManager использует `BatchBuffer` из `channel_routing_module`.

## ADR-LOG-003 (was ADR-142): LogRecord как отдельный тип

**Статус:** принято  
**Решение:** `LogRecord` (dataclass) вынесен в `core/log_types.py`. Импортируется из `logger_module` и `error_module`.
