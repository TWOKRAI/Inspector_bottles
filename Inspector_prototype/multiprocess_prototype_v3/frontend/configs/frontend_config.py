# multiprocess_prototype_v3/frontend/configs/frontend_config.py
"""
FrontendConfig — корневая схема всего frontend-процесса.

Композиция только из дочерних пакетов (main_window, loading, tabs_setting, виджеты вкладок).
Секции UI живут рядом с виджетами; здесь — склейка и build_dict.

Конфиг приложения (вложенные схемы: tabs, settings_tab, recipes_tab, main_window и т.д.)
непосредственно участвует в UI: подписи, заголовки вкладок, раскладка, привязки контролов к
полям регистров там, где это задано в схемах. Это отдельно от снимков рецептов регистров
(алгоритм) и app_recipes (пресеты схем UI).
"""

import os
from typing import Any, Dict, Optional

from multiprocess_prototype_v3.camera_policy import CameraTypeStr, DEFAULT_CAMERA_TYPE

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    DataConverter,
    SchemaBase,
    register_schema,
)

from multiprocess_prototype_v3.frontend.windows.loading import LoadingWindowConfig
from multiprocess_prototype_v3.frontend.windows.main_window import MainWindowConfig
from multiprocess_prototype_v3.frontend.widgets.tabs_setting import SettingsTabConfig, TabsConfig
from multiprocess_prototype_v3.frontend.widgets.cropped_regions_widget.schemas import (
    CroppedRegionsTabUiConfig,
)
from multiprocess_prototype_v3.frontend.widgets.post_processing_widget.schemas import (
    PostProcessingTabUiConfig,
)
from multiprocess_prototype_v3.frontend.widgets.recipes.settings_recipe_widget.schemas import RecipesTabConfig


@register_schema("WindowRegistryEntry")
class WindowRegistryEntry(SchemaBase):
    """Запись реестра окон (factory_key сопоставляется в FrontendLauncher)."""

    factory_key: str = "main"


def default_window_registry() -> Dict[str, Dict[str, Any]]:
    return {
        "main": {"factory_key": "main"},
        "inspector": {"factory_key": "inspector"},
        "loading": {"factory_key": "loading"},
    }


@register_schema("FrontendConfig")
class FrontendConfig(SchemaBase):
    """
    Корневая конфигурация frontend: main_window + tabs + settings_tab + runtime.

    Вложенные секции — часть конфигурации приложения, которая участвует в построении UI
    (тексты, вкладки; вкладка «Настройки» — таблица app-рецепта по `recipes_tab` + схемам UI).
    """

    # MainWindow layout
    main_window: MainWindowConfig = Field(default_factory=MainWindowConfig)

    loading_window: LoadingWindowConfig = Field(default_factory=LoadingWindowConfig)

    # Tabs
    tabs: TabsConfig = Field(default_factory=TabsConfig)

    # Settings tab — секция конфига (legacy fields); виджет: только таблица app-рецепта
    settings_tab: SettingsTabConfig = Field(default_factory=SettingsTabConfig)

    recipes_tab: RecipesTabConfig = Field(default_factory=RecipesTabConfig)

    cropped_regions_tab: CroppedRegionsTabUiConfig = Field(default_factory=CroppedRegionsTabUiConfig)

    post_processing_tab: PostProcessingTabUiConfig = Field(default_factory=PostProcessingTabUiConfig)

    # Путь к YAML рецептов (опционально; по умолчанию multiprocess_prototype/data/recipes.yaml)
    recipes_path: Optional[str] = None

    # Путь к YAML app-пресетов (опционально; по умолчанию рядом с recipes_path)
    settings_recipes_path: Optional[str] = None

    # Путь к YAML профилей настроек приложения (Phase 0; по умолчанию data/settings_profiles.yaml)
    settings_profiles_path: Optional[str] = None

    # Runtime (из app_cfg)
    camera_type: CameraTypeStr = DEFAULT_CAMERA_TYPE
    poll_interval_ms: int = 16

    # Touch-клавиатура для панелей (деревья/таблицы/QLineEdit): dict для TouchKeyboardConfig
    touch_keyboard: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {"mode": "full"},
        description="По умолчанию full (полная клавиатура); mini — только цифры; off — выкл. Перекрывается GuiConfig.",
    )

    def build_dict(self, app_cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Построить dict для FrontendManager и MainWindow.

        Мержит app_cfg (GuiConfig) с дефолтами. Dict at Boundary.

        Args:
            app_cfg: dict из get_config("config") — GuiConfig.model_dump().

        Returns:
            dict с window, header, image_panel, tabs, window_registry,
            camera_type, poll_interval_ms, settings_tab, touch_keyboard, …
        """
        app_cfg = app_cfg or {}

        # Переопределить main_window из app_cfg
        mw_data = self.main_window.model_dump()
        if app_cfg.get("window_title"):
            mw_data["window"]["title"] = app_cfg["window_title"]
        if app_cfg.get("window_width") is not None:
            mw_data["window"]["min_width"] = app_cfg["window_width"]
        if app_cfg.get("window_height") is not None:
            mw_data["window"]["min_height"] = app_cfg["window_height"]

        camera_tab = dict(app_cfg.get("camera_tab") or {})
        if (
            "webcam_enum_max_index" not in camera_tab
            and app_cfg.get("webcam_enum_max_index") is not None
        ):
            camera_tab["webcam_enum_max_index"] = app_cfg["webcam_enum_max_index"]

        recipes_path = app_cfg.get("recipes_path", self.recipes_path)
        settings_recipes_path = app_cfg.get("settings_recipes_path", self.settings_recipes_path)
        settings_profiles_path = app_cfg.get("settings_profiles_path", self.settings_profiles_path)

        ui_diag = dict(app_cfg.get("ui_diagnostics") or {})
        env_on = os.environ.get("INSPECTOR_UI_DIAGNOSTICS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if env_on and not ui_diag.get("enabled"):
            ui_diag["enabled"] = True

        tk = app_cfg.get("touch_keyboard")
        if tk is None:
            tk = self.touch_keyboard

        result = {
            "window": mw_data["window"],
            "header": mw_data["header"],
            "image_panel": mw_data["image_panel"],
            "tabs": self.tabs.to_tabs_dict_list(),
            "window_registry": default_window_registry(),
            "camera_type": app_cfg.get("camera_type", self.camera_type),
            "poll_interval_ms": app_cfg.get("poll_interval_ms", self.poll_interval_ms),
            "settings_tab": self.settings_tab.model_dump(),
            "recipes_tab": self.recipes_tab.model_dump(),
            "cropped_regions_tab": self.cropped_regions_tab.model_dump(),
            "post_processing_tab": self.post_processing_tab.model_dump(),
            "recipes_path": recipes_path,
            "settings_recipes_path": settings_recipes_path,
            "settings_profiles_path": settings_profiles_path,
            "recipe_access": dict(app_cfg.get("recipe_access") or {}),
            "loading_window": self.loading_window.model_dump(),
            "camera_tab": camera_tab,
            "ui_diagnostics": ui_diag,
            "touch_keyboard": tk,
        }
        return result

    def to_json(self, indent: int = 2) -> str:
        """Сериализация в JSON."""
        return DataConverter.model_to_json(self, indent=indent)

    def to_yaml(self) -> str:
        """Сериализация в YAML."""
        return DataConverter.model_to_yaml(self)

    @classmethod
    def from_json(cls, json_str: str) -> "FrontendConfig":
        """Десериализация из JSON."""
        data = DataConverter.json_to_dict(json_str)
        return cls(**data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "FrontendConfig":
        """Десериализация из YAML."""
        data = DataConverter.yaml_to_dict(yaml_str) or {}
        return cls(**data)


def build_frontend_config(app_cfg: dict | None) -> dict:
    """
    Построить dict конфига для FrontendManager. Dict at Boundary.

    Обратная совместимость: launcher импортирует отсюда.
    """
    return FrontendConfig().build_dict(app_cfg)
