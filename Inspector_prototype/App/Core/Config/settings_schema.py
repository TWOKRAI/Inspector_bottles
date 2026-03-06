# App/Core/Config/app_config.py
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field
import yaml
import os


class WindowConfig(BaseModel):
    """Конфигурация окон (read-only после старта)."""
    theme: Literal["dark", "light"] = "dark"
    language: str = "ru"
    
    fullscreen: bool = False
    limit_fullscreen_resolution: bool = True
    fullscreen_max_width: int = 1920
    fullscreen_max_height: int = 1080
    
    window_min_width: int = 800
    window_min_height: int = 600


class PerformanceConfig(BaseModel):
    """Производительность."""
    max_display_fps: int = Field(default=60, ge=30, le=144)
    enable_fps_overlay: bool = True
    overlay_update_interval_ms: int = 500  # Не чаще чем раз в 500мс


class PathConfig(BaseModel):
    """Пути (авто-создание директорий)."""
    data_dir: Path = Path("App/Data")
    recipes_dir: Path = Path("App/Data/Recipes")
    logs_dir: Path = Path("App/Data/Logs")
    temp_dir: Path = Path("App/Data/Temp")
    
    def __init__(self, **data):
        super().__init__(**data)
        # Авто-создание при старте
        for path in [self.data_dir, self.recipes_dir, self.logs_dir, self.temp_dir]:
            path.mkdir(parents=True, exist_ok=True)


class AppConfig(BaseModel):
    """Корневой конфиг — НЕ регистр! Нет FieldMeta, нет IPC routing."""
    
    window: WindowConfig = WindowConfig()
    performance: PerformanceConfig = PerformanceConfig()
    paths: PathConfig = PathConfig()
    
    # Development
    debug_mode: bool = False
    mock_camera: bool = False  # Для тестирования без реальной камеры
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """Загрузка из YAML или defaults."""
        if path is None:
            path = Path("App/Data/config.yaml")
        
        if not path.exists():
            config = cls()
            config.save(path)
            return config
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls.model_validate(data or {})
    
    def save(self, path: Optional[Path] = None) -> None:
        """Сохранение в YAML."""
        if path is None:
            path = Path("App/Data/config.yaml")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(self.model_dump(), f, allow_unicode=True, default_flow_style=False)


# Singleton accessor (опционально, но удобно)
_config_instance: Optional[AppConfig] = None

def get_config() -> AppConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig.load()
    return _config_instance

def set_config(config: AppConfig) -> None:
    global _config_instance
    _config_instance = config