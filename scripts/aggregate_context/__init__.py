"""aggregate_context — per-module markdown aggregator.

Generic фреймворк для per-module knowledge файлов (CONTEXT.md, DECISIONS.md).
Сканирует проект, парсит per-module файлы, рендерит сводный root-registry
с marker-based replacement. Plugin-архитектура через `SyncModule` Protocol.

См. README.md рядом — конвенции, sync-модули, CLI.

Public API (re-exported для plugin-авторов):
    SyncModule, MarkerNotFound, apply_sync — core механика
    discover_modules, ModuleEntry           — discovery
"""

from .discover import ModuleEntry, discover_modules
from .registry import MarkerNotFound, SyncModule, apply_sync

__all__ = [
    "MarkerNotFound",
    "ModuleEntry",
    "SyncModule",
    "apply_sync",
    "discover_modules",
]
