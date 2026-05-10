"""prefs — простой kv-store для UI-предпочтений.

Re-exports:
    UiPrefsStore  — хранитель UI-предпочтений в data/ui_prefs.yaml
    UI_PREFS_PATH — путь к файлу по умолчанию
"""

from .store import UI_PREFS_PATH, UiPrefsStore

__all__ = [
    "UI_PREFS_PATH",
    "UiPrefsStore",
]
