# multiprocess_prototype/frontend/configs/frontend_config.py
"""
FrontendConfig — корневая схема всего frontend-процесса.

Композиция только из дочерних пакетов (main_window, loading, tabs, settings_tab).
Секции UI живут рядом с виджетами; здесь — склейка и build_dict.
"""

from typing import Any, Dict, Literal

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import (
    DataConverter,
    SchemaBase,
    register_schema,
)

from multiprocess_prototype.frontend.windows.loading import LoadingWindowConfig
from multiprocess_prototype.frontend.windows.main_window import MainWindowConfig
from multiprocess_prototype.frontend.widgets.settings_tab import SettingsTabConfig
from multiprocess_prototype.frontend.widgets.tabs import TabsConfig


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
    """Корневая конфигурация frontend: main_window + tabs + settings_tab + runtime."""

    # MainWindow layout
    main_window: MainWindowConfig = Field(default_factory=MainWindowConfig)

    loading_window: LoadingWindowConfig = Field(default_factory=LoadingWindowConfig)

    # Tabs
    tabs: TabsConfig = Field(default_factory=TabsConfig)

    # Settings tab — привязка контролов к регистрам
    settings_tab: SettingsTabConfig = Field(default_factory=SettingsTabConfig)

    # Runtime (из app_cfg)
    camera_type: Literal["simulator", "webcam", "hikvision"] = "simulator"
    poll_interval_ms: int = 16

    def build_dict(self, app_cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Построить dict для FrontendManager и MainWindow.

        Мержит app_cfg (GuiConfig) с дефолтами. Dict at Boundary.

        Args:
            app_cfg: dict из get_config("config") — GuiConfig.model_dump().

        Returns:
            dict с window, header, image_panel, tabs, window_registry,
            camera_type, poll_interval_ms, settings_tab.
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

        result = {
            "window": mw_data["window"],
            "header": mw_data["header"],
            "image_panel": mw_data["image_panel"],
            "tabs": self.tabs.to_tabs_dict_list(),
            "window_registry": default_window_registry(),
            "camera_type": app_cfg.get("camera_type", self.camera_type),
            "poll_interval_ms": app_cfg.get("poll_interval_ms", self.poll_interval_ms),
            "settings_tab": self.settings_tab.model_dump(),
            "loading_window": self.loading_window.model_dump(),
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
