"""scripts.sync — sync-каркас для генерируемых разделов документации.

Публичный API:
    from scripts.sync.registry import apply_sync, replace_between_markers, MarkerNotFound
"""

from scripts.sync.registry import MarkerNotFound, SyncModule, apply_sync, replace_between_markers

__all__ = ["MarkerNotFound", "SyncModule", "apply_sync", "replace_between_markers"]
