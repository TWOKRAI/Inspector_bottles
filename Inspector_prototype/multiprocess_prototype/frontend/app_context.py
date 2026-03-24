# multiprocess_prototype/frontend/app_context.py
"""
Явный контекст зависимостей вкладок и окон прототипа.

Один объект вместо длинного списка аргументов у create_tab_widget_factory; слои (launcher,
FrontendManager, MVP) не сливаются — меняется только способ передачи ссылок.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FrontendAppContext:
    """
    Снимок зависимостей, нужных фабрике вкладок и (при необходимости) другим хелперам UI.

    Attributes:
        config: dict после FrontendConfig.build_dict (вкладки, recipe_access, ui_diagnostics, …).
        registers_manager: мост/менеджер регистров с процесса (или None в тестах).
        camera_callbacks_map: колбэки камеры (уже собранные из GuiCommandHandler).
        camera_type: режим камеры для CameraTabWidget.
        recipe_manager: менеджер YAML рецептов (или None).
        command_handler: GuiCommandHandler — для будущих вкладок / диагностики; сейчас колбэки
            камеры уже замкнуты на него в launcher.
    """

    config: Dict[str, Any]
    registers_manager: Optional[Any]
    camera_callbacks_map: Dict[str, Any]
    camera_type: str
    recipe_manager: Optional[Any] = None
    command_handler: Optional[Any] = None
    style_session: Optional[Any] = None
    extras: Dict[str, Any] = field(default_factory=dict)
