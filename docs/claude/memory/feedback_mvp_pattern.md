---
name: MVP pattern preference
description: User prefers full MVP (presenter + view protocol) for GUI tabs — consistency over simplicity
type: feedback
originSessionId: 8df591d7-a341-42e1-8969-5444903c41a4
---
Use full MVP pattern (presenter.py + view.py Protocol + widget.py) for new GUI tabs, not simplified widget-only approach.

**Why:** User values consistency across the codebase. Existing feature widgets (cropped_regions, camera_common, recipes) all use MVP. Mixing patterns causes confusion.

**How to apply:** When creating new tab widgets or feature panels, always include: view.py (runtime_checkable Protocol), presenter.py (business logic without Qt), widget.py (implements Protocol, wires signals to presenter). Model stays separate in models/ dir.
