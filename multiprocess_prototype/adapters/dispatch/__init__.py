# -*- coding: utf-8 -*-
"""
adapters/dispatch/ — пакет диспетчеризации команд (Phase C / Task C.6 + D.3).

Экспортирует:
    CommandDispatcherOrchestrator — центральный orchestrator dispatch(cmd) -> events
    ProjectHolder — thread-safe mutable wrapper над текущим frozen Project

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.6)
Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.3)
"""

from __future__ import annotations

from .command_dispatcher import CommandDispatcherOrchestrator
from .project_holder import ProjectHolder

__all__ = [
    "CommandDispatcherOrchestrator",
    "ProjectHolder",
]
