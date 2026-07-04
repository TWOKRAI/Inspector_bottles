# DECISIONS — shared_resources_module

Локальные архитектурные решения модуля.  
Глобальный журнал: [../../DECISIONS.md](../../DECISIONS.md)

---

## ADR-SRM-001: Удалён legacy API v1

**Дата:** 2026-04-09  
**Решение:** Удалены методы SRM: `register_process_state`, `register_process_with_config`, `update_process_state`, `get_process_state`, `get_all_process_states`, `add_shared_resource`, `get_shared_resource`, `get_data_manager`, `data_manager`, словарь `shared_resources`. Удалены `register_process_with_config` из PSR.  
**Причина:** Каноничный путь — `register_process()` (ADR-018) и `process_state_registry.register_process` / `update_state` для bundle/тонких сценариев. Доступ к схемам данных — через `DataSchemaAdapter` при необходимости.  
**Миграция:** `process_module`, `process_manager_module` переведены на `process_state_registry`.

## ADR-SRM-002: ProcessHandle как единый паттерн доступа

**Дата:** 2026-04-09  
**Решение:** Введены `ProcessHandle`, `QueueHandle`, `EventHandle`, `MemoryHandle`; методы фасада `for_process()` (не `process()` — конфликт с `BaseManager.process`), `has_process()`, `broadcast()`, `get_all_statuses()`.  
**Причина:** Несколько путей к очередям и отсутствие единого паттерна для памяти; Handle унифицирует доступ.

## ADR-SRM-003: PSR — единственный source of truth для очередей

**Дата:** 2026-04-09  
**Решение:** Удалён локальный кэш `QueueRegistry.registered_queues`; broadcast и статистика идут через PSR.  
**Причина:** Устранение тройного хранения ссылок на `Queue`.

## ADR-SRM-004: MemoryAccessStatus enum вместо bool

**Дата:** 2026-04-09  
**Решение:** `validate_memory_access()` и `validate_write_operation()` возвращают `MemoryAccessStatus`.  
**Причина:** Диагностируемая причина отказа вместо голого `bool`.

## ADR-SRM-005: Менеджеры за фасадом (docstring deprecated)

**Дата:** 2026-04-09  
**Решение:** Properties `config_store`, `process_state_registry`, `queue_registry`, `event_manager`, `memory_manager` помечены в docstring как deprecated; без `warnings.warn` до миграции потребителей. Handle API: `srm.for_process(name)`.  
**Причина:** Инкапсуляция фасада; постепенный переход на Handle API.

## ADR-SRM-006: EventManager.wait_for_event — отложенный put-back

**Дата:** 2026-04-09  
**Решение:** Несовпадающие события копятся в списке и возвращаются в очередь в `finally`, цикл использует `queue.Empty`.  
**Причина:** Устранение гонки при немедленном `put` обратно в цикле ожидания.

## ADR-SRM-007: Имя метода `for_process()` вместо `process()`

**Дата:** 2026-04-09  
**Решение:** Единая точка входа Handle API называется `srm.for_process("name")`, а не `srm.process("name")`.  
**Причина:** `BaseManager` (от которого наследуется SRM) хранит `self.process` — ссылку на родительский ProcessModule. Метод `process()` перекрывался бы атрибутом экземпляра и вызывался бы как `None(...)`.  
**Альтернативы:** (1) переименовать BaseManager.process → _host_process (большой diff); (2) process_handle() (длиннее). Выбран прагматичный компромисс — `for_process()` короткий, однозначный, не конфликтует.

## ADR-SRM-008: SharedResourcesManagerConfig — SchemaBase с параметрами модуля

**Дата:** 2026-04-09  
**Решение:** Конфиг расширен с 3 полей (stub) до 8 полей: default_queue_maxsize, event_wait_poll_interval, default_memory_coll, cleanup_stale_shm_on_init, standard_events.  
**Причина:** Конфиг должен реально управлять поведением модуля (паттерн SchemaBase как во всех модулях), а не быть заглушкой.

## ADR-SRM-009: unregister_process — единая точка снятия процесса

**Дата:** 2026-07-04  
**Решение:** Публичный `SharedResourcesManager.unregister_process(name)` — симметрия к `register_process` (ADR-018): освобождает SHM (`memory_manager.release_process_memory`), удаляет запись PSR (очереди/события/метаданные) и конфиг ConfigStore. Идемпотентен. Контракт `MemoryManager.release_process_memory` СУЖЕН до «только память» — прежний скрытый `psr.unregister_process` внутри него удалён.  
**Причина:** Снятие процесса с PSR выполнялось побочным эффектом освобождения памяти — скрытая связанность: cleanup-фаза hot-swap чистила очереди мёртвого процесса «случайно», через release SHM. При эволюции memory-слоя очереди/события утекали бы в routing_map новых детей (broadcast наполняет никем не читаемые Queue). Потребитель — `PM._cleanup_process_resources` (switch рецепта, rollback).  
**Refs:** plans/2026-07-04_topology-switch-hardening.md (Task 1.4).
