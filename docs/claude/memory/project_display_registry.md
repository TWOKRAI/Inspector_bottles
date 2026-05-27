---
name: DisplayRegistry implementation state
description: display_module в framework — реестр именованных SHM-каналов для отображения
type: project
---

`display_module` в `multiprocess_framework/modules/display_module/` реализует реестр именованных SHM-каналов отображения.

Ключевые решения:
- Singleton по образу ServiceRegistry (ADR-DM-001 ссылается на SVC-001)
- Generic: нет vision-полей (`camera_id`, `region`), только `name/size/format/fps_limit/ring_buffer_size` (ADR-DM-001)
- `persist(path)` — явный аргумент, а не класс-уровень конфиг (ADR-DM-002)
- `cleanup()` даёт только warning, не удаляет SHM принудительно (ADR-DM-003)
- 12 тестов в `tests/`

## Связанные ADR / коммиты
- ADR-130 (DisplayRegistry) — `multiprocess_framework/DECISIONS.md`
- ADR-DM-001/002/003 — `multiprocess_framework/modules/display_module/DECISIONS.md`
- Phase 4 DONE: коммит `b7fa95db`

## Ключевые пути
- `multiprocess_framework/modules/display_module/` — interfaces, registry
- `multiprocess_prototype/backend/config/displays.yaml` — application-specific конфиг дисплеев
- `multiprocess_prototype/backend/state/adapters/display_adapter.py`
- `multiprocess_prototype/frontend/widgets/displays/preview_window.py`

## Статус
Phase 4 DONE (2026-05-27). Stable. Используется в DisplaysTab и как зависимость Pipeline DisplayNodeItem.
