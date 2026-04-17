"""Frontend configuration builder for v3 prototype."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Default image panel slots (original + mask)
DEFAULT_IMAGE_SLOTS: List[Dict[str, Any]] = [
    {"id": "original", "label": "Original", "stretch": 2},
    {"id": "mask", "label": "Mask", "stretch": 1},
]

# Default tab definitions
DEFAULT_TABS: List[Dict[str, str]] = [
    {"id": "camera", "title": "Камера", "widget": "camera"},
    {"id": "processing", "title": "Обработка", "widget": "processing"},
]


def build_frontend_config(app_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build frontend config dict from app config.

    Merges app_cfg values with defaults. Returns dict suitable for
    FrontendManager / MainWindow / TabWidget.
    """
    cfg = app_cfg or {}
    return {
        "window": {
            "title": cfg.get("window_title", "Inspector Prototype v3"),
            "min_width": cfg.get("window_width", 1280),
            "min_height": cfg.get("window_height", 720),
        },
        "header": cfg.get("header", {}),
        "image_panel": {
            "slots": cfg.get("image_panel_slots", DEFAULT_IMAGE_SLOTS),
        },
        "tabs": cfg.get("tabs", DEFAULT_TABS),
        "camera_type": cfg.get("camera_type", "simulator"),
        "poll_interval_ms": cfg.get("poll_interval_ms", 16),
        "camera_tab": cfg.get("camera_tab"),
        "processing_tab_ui": cfg.get("processing_tab_ui"),
        "touch_keyboard": cfg.get("touch_keyboard"),
        "loading_window": {
            "title": cfg.get("loading_title", "Загрузка..."),
            "min_width": 400,
            "min_height": 300,
            "logo_path": cfg.get("loading_logo_path"),
        },
        "recipes_path": cfg.get("recipes_path"),
        "settings_recipes_path": cfg.get("settings_recipes_path"),
        "recipe_access": cfg.get("recipe_access"),
    }
