# -*- coding: utf-8 -*-
"""
adapters/dispatch/ — пакет диспетчеризации команд (Phase C / Task C.6).

Экспортирует:
    CommandDispatcherOrchestrator — центральный orchestrator dispatch(cmd) -> events
    ProjectHolder — mutable wrapper над текущим frozen Project

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.6)
"""

from __future__ import annotations

from .command_dispatcher import CommandDispatcherOrchestrator, ProjectHolder

__all__ = [
    "CommandDispatcherOrchestrator",
    "ProjectHolder",
]
