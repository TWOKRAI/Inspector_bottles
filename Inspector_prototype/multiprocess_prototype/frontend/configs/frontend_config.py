# multiprocess_prototype/frontend/configs/frontend_config.py
"""
FrontendConfig — layout MainWindow.

Схема конфигурации окна, header, image_panel, tabs.
Строится из GuiConfigFrontend (app_cfg).
"""

from typing import Any, Dict, List, Optional


def build_frontend_config(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Построить конфиг для MainWindow из app_cfg (GuiConfigFrontend).

    Args:
        app_cfg: dict из get_config("config") — GuiConfigFrontend.model_dump().

    Returns:
        dict с секциями window, header, image_panel, tabs, camera_type.
    """
    window_title = app_cfg.get("window_title", "Inspector Prototype")
    min_width = app_cfg.get("window_width", 1024)
    min_height = app_cfg.get("window_height", 600)
    camera_type = app_cfg.get("camera_type", "simulator")

    return {
        "window": {
            "title": window_title,
            "min_width": min_width,
            "min_height": min_height,
        },
        "window_registry": {
            "main": {"factory_key": "main"},
            "inspector": {"factory_key": "inspector"},
            "loading": {"factory_key": "loading"},
        },
        "header": {
            "logo_path": None,
            "show_admin": True,
            "windows": [
                {"id": "main", "label": "Домой", "callback_key": "on_main_show"},
                {"id": "loading", "label": "Загрузка", "callback_key": "on_loading_show"},
            ],
        },
        "image_panel": {
            "slots": [
                {"id": "original", "label": "Original", "visible_default": True},
                {"id": "mask", "label": "Mask", "visible_default": True},
            ],
        },
        "tabs": [
            {"id": "recipes", "title": "Рецепты", "widget": "recipes"},
            {"id": "settings", "title": "Настройки", "widget": "settings"},
            {"id": "processing", "title": "Обработка", "widget": "processing"},
            {"id": "camera", "title": "Камера", "widget": "camera"},
        ],
        "camera_type": camera_type,
    }
