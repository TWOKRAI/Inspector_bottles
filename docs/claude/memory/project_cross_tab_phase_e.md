---
name: project-cross-tab-phase-e
description: Phase E (per-tab migration на AppServices DI) cross-tab-architecture refactor — статус, паттерн миграции, направление работ
metadata:
  type: project
---

**Phase E — Per-tab migration AppContext → AppServices DI** на ветке `refactor/cross-tab-architecture`.

**Прогресс (2026-05-28):**
- E.1 Pipeline — **DONE** (Senior+, teamlead). Коммиты `8566f994` + `e7bd3d97`. Reviewer APPROVED итерация 2/2. 322 теста, sentrux 7141 (-20 принято).
- E.2 Processes — **NEXT** (Middle, developer). ~3 файла, 1 legacy ctx.plugin_registry().
- E.3 Recipes (Middle) → E.4 Services (Middle) → E.5 Plugins (Middle+, 25 точек) → E.6 Displays (Junior).

**Why:** Pipeline = крупнейший consumer legacy API (21+ ctx.* вызовов). Успешная миграция Pipeline даёт template для остальных 5 табов. После E.6 — Phase F (удаление ctx.extras, dataclass-обёрток).

**How to apply:**
- Перед стартом каждого Ei — перечитать [[project-cross-tab-phase-d]] migration guide (`docs/refactors/2026-05_phase_e_migration_guide.md`)
- Settings tab (D.5) + Pipeline (E.1) — два template'а паттерна
- Bridge через приватные атрибуты (`adapter._rm`, `getattr(services.X, "_internal")`) **разрешён** при наличии TODO Phase F комментария с обоснованием Protocol gap
- Sentrux регрессия от bridges принимаема (TODO Phase F вернёт score)
- `holder.on_changed` остаётся как fallback для batch scene reload — typed events это Phase G
- Тесты: `make_test_app_services()` или per-tab builder (`tests/_helpers.py` в pipeline) — bridge-моки без spec OK для legacy API
- Qt-MCP smoke не работает с multiprocess архитектурой (GUI в дочернем процессе) — deferred к cumulative ручной проверке после E.6 перед merge в main

**Ключевые артефакты:**
- Plan: `plans/2026-05-27_cross-tab-architecture/phase-e-per-tab-migration.md`
- Master: `plans/2026-05-27_cross-tab-architecture/plan.md`
- Migration guide: `docs/refactors/2026-05_phase_e_migration_guide.md`
- E.1 template: `multiprocess_prototype/frontend/widgets/tabs/pipeline/` (tab.py + presenter.py + inspector_panel.py + tests/_helpers.py)
- D.5 template: `multiprocess_prototype/frontend/widgets/tabs/settings/`

**Открытые вопросы:**
- Split ConfigStore (follow-up D.1): Pipeline read-only OK, решение для E.4 Services (когда будет мутация config)
- PortSpec.direction — новое поле из E.1 (расширение Protocol домена) — следующие табы должны это знать
