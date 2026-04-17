"""UI diagnostics (minimal stub for v3)."""

from typing import Any, Dict, Optional


def attach_ui_diagnostics(window: Any, config: Dict[str, Any]) -> Optional[Any]:
    """Attach UI diagnostics if enabled in config."""
    diag_cfg = config.get("ui_diagnostics")
    if not diag_cfg or not diag_cfg.get("enabled"):
        return None
    # TODO: implement full diagnostics if needed
    return None
