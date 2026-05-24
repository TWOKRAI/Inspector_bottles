# Phase 3 — ServiceRegistry + первые сервисы

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/service-registry`
> **Дней**: 3-4
> **Зависимости**: Phase 0 (для StateAdapterBase + регистрации сервисов)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

ServiceRegistry для long-running объектов (камеры, БД, auth) с lifecycle, отдельно от PluginRegistry. В pipeline сервисы используются через плагин-обёртки (как `hikvision_camera`).

## Реюз готового

- Паттерн `PluginRegistry` (262 строки) — копируем структуру.
- `Services/hikvision_camera/` — образец плагина-обёртки.
- `backup/services/camera/CameraService` — первый сервис для демо (webcam через OpenCV).
- ADR-121, ADR-122 — границы слоя.

## Новое (минимально)

- `multiprocess_framework/modules/service_module/registry.py` — `ServiceRegistry` (singleton, `@register_service`, `list/get/filter`).
- `multiprocess_framework/modules/service_module/lifecycle.py` — `ServiceLifecycle` enum (UNREGISTERED → READY → RUNNING → STOPPED → ERROR), `IService` Protocol (`start/stop/health/status_dict`).
- `multiprocess_framework/modules/service_module/scanner.py` — `discover(*dirs)` сканирует `service.py`.
- `Services/sql/service.py`, `Services/hikvision_camera/service.py`, `Services/auth/service.py` — точки регистрации `@register_service`.
- `Services/webcam_camera/service.py` — **новый сервис из backup** (CameraService адаптированный) — нужен для демо в Phase 7.
- `multiprocess_prototype/backend/state/adapters/service_state_adapter.py` — двусторонняя sync ServiceRegistry ↔ `state.services.*`.
- ADR в `multiprocess_framework/DECISIONS.md`: «ServiceRegistry: гибрид с PluginRegistry, lifecycle, scanner».

## ServicesTab

- `tabs/services/tab.py` — переключить на `ServiceRegistry.list()`.
- Подвкладка «Пути» — аналог Phase 2 для `service_paths`.
- Action-кнопки: «Запустить / Остановить / Перезапустить» → `ServiceRegistry.get(name).start()/stop()`.
- Статус: из `state.services.<name>.status`.
- Утилитарные (Operation_crop, Region_processors) — показываются как «library, не запускаются».

## Acceptance

- В ServicesTab видны 5+ сервисов.
- `webcam_camera` можно запустить → state переходит в RUNNING → активный сервис доступен для sandbox в Phase 6 и для демо в Phase 7.
- Минимум 15-20 unit-тестов на ServiceRegistry+lifecycle.
