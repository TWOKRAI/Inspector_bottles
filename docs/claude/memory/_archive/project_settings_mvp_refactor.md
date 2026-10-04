---
name: Settings MVP Refactoring
description: Active refactoring of Settings tab to modular MVP architecture — branch refactor/settings-mvp, plan crystalline-whistling-hellman.md, 6 phases
type: project
originSessionId: 43255063-69e2-4666-ae65-c58b98a1329a
---
Settings tab refactoring to modular MVP is in progress.

**Branch:** `refactor/settings-mvp`
**Plan:** `~/.claude/plans/crystalline-whistling-hellman.md`
**Status:** Phase 0 not started yet (2026-05-13)

**Key decisions:**
- Phase 1 = SettingsPresenter first (reviewer recommended, not sections first)
- SectionProtocol + CurrentPageStack → framework (`frontend_module/widgets/tabs/`)
- BaseAdminPanel stays in prototype (app-specific, depends on AuthContext)
- InterfaceSection — no MVP (too simple, 81 LOC)
- Appearance: presenter owns data, vars_editor emits var_changed (no batch flush)
- Presenters extend existing `TabPresenterBase` from framework
- Green-bar constraint: all existing tests must pass on every phase

**Why:** Settings is the only tab without MVP. This refactoring creates a template for Recipes and other tabs. Two monoliths: tab.py (749 LOC) and theme_editor_section.py (869 LOC).

**How to apply:** In new chat, read the plan file and start from Phase 0. Each phase = separate commit.
