---
name: Component Design System (Phase 5+)
description: React-style component design system for PySide6 framework — plan saved, deferred until custom components replace raw Qt widgets
type: project
originSessionId: 9761a818-dd8a-4b54-b995-0de68ea6ca15
---
User wants React-like Component Design System: each framework component encapsulates its styles (widget.py + widget.qss + tokens.yaml), registered via @component_style decorator in ComponentStyleRegistry, ThemeManager assembles QSS from registry.

**Why:** Constructor philosophy — different apps on same framework should get pre-styled components out of the box, customizable through ThemeEditor.

**How to apply:**
1. Full plan saved in `multiprocess_prototype/plans/component_scoped_styles.md` (14 tasks, 7 phases, ~80 files)
2. DEFERRED: do NOT implement until custom components (frontend_module/components/) replace raw Qt widgets in prototype
3. Correct order: design tokens (current) → custom components with built-in styles → THEN Design System (registry + manifest)
4. Key constraint: Qt QSS has no real scoping — use `WrapperClass InnerQtWidget` selectors (e.g., `ButtonControl QPushButton`) for component isolation
5. Current components use composition pattern (QWidget with private Qt fields), NOT direct inheritance from Qt primitives
6. Inline styles in framework components (11 places with setStyleSheet) must be migrated to QSS files when Design System is implemented
7. tokens.yaml per component: prefer declaring token NAMES only (not values), values from theme's variables.yaml (single source of truth)
