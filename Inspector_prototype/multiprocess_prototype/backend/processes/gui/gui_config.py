# multiprocess_prototype/backend/processes/gui/gui_config.py
"""
Конфигурация GUI-процесса (GuiProcess): frontend_module + FrontendLauncher.

Единственная схема процесса gui — импорт из ``multiprocess_prototype.backend.configs``.
"""

from typing import Annotated, Any, Dict, Optional

from multiprocess_prototype.camera_policy import CameraTypeStr, DEFAULT_CAMERA_TYPE

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.backend.configs.base_config import ProcessConfigBase, class_path_from_type

from .gui_process import GuiProcess


@register_schema("GuiConfig")
class GuiConfig(ProcessConfigBase):
    """Конфигурация GUI-процесса. Layout UI — ``FrontendConfig``, мерж в ``FrontendLauncher`` из app_cfg."""

    process_name: str = "gui"
    class_path: str = class_path_from_type(GuiProcess)
    camera_type: CameraTypeStr = DEFAULT_CAMERA_TYPE
    window_title: str = "Inspector Prototype"
    window_width: Annotated[
        int, FieldMeta("Ширина окна", min=400, max=1920)
    ] = 1024
    window_height: Annotated[
        int, FieldMeta("Высота окна", min=300, max=1080)
    ] = 600
    poll_interval_ms: Annotated[
        int, FieldMeta("Интервал опроса сообщений, мс", min=5, max=100)
    ] = 16

    recipes_path: Annotated[
        Optional[str],
        FieldMeta(
            "Путь к YAML рецептов",
            info="По умолчанию — multiprocess_prototype/data/recipes.yaml внутри RecipeManager.",
        ),
    ] = None

    recipe_access: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Доступ к редактированию рецептов",
            info="Словарь для AccessContext: level, bypass_readonly, show_hidden.",
        ),
    ] = None

    ui_diagnostics: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Телеметрия UI (опционально)",
            info=(
                "enabled, log_level, logger_name, include_prefixes, buffer_max. "
                "Либо env INSPECTOR_UI_DIAGNOSTICS=1 (включает с дефолтами в build_dict)."
            ),
        ),
    ] = None
