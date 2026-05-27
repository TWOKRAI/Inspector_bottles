---
name: ServiceRegistry implementation state
description: service_module в framework — реестр и lifecycle long-running сервисов
type: project
---

`service_module` в `multiprocess_framework/modules/service_module/` реализует реестр долгоживущих сервисов.

Ключевые решения:
- Singleton через `__new__` + `Lock` (ADR-SVC-001) — потокобезопасный доступ из нескольких воркеров
- `IService` Protocol (ADR-SVC-002) — start/stop/restart/status без наследования
- Хранит классы, не экземпляры (ADR-SVC-003) — lifecycle управляется явно
- 91 тест в `tests/`
- 4 сервиса зарегистрированы: `webcam_camera`, `sql`, `hikvision_camera`, `auth`

## Связанные ADR / коммиты
- ADR-129 (ServiceRegistry) — `multiprocess_framework/DECISIONS.md`
- ADR-SVC-001/002/003 — `multiprocess_framework/modules/service_module/DECISIONS.md`
- Phase 3 DONE: коммит `3ed4ec4`

## Ключевые пути
- `multiprocess_framework/modules/service_module/` — interfaces, registry, lifecycle, scanner
- `multiprocess_prototype/backend/state/adapters/service_adapter.py`
- `Services/webcam_camera/`, `Services/sql/`, `Services/hikvision_camera/`, `Services/auth/`

## Статус
Phase 3 DONE (2026-05-27). Stable. Используется в ServicesTab и как зависимость RecipesManager.
