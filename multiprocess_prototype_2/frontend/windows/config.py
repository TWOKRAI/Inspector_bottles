"""Конфигурация главного окна."""
from pydantic import BaseModel, Field


class WindowConfig(BaseModel):
    """Конфиг окна: размеры, заголовок."""

    title: str = "Inspector v2"
    min_width: int = 1024
    min_height: int = 768


class MainWindowConfig(BaseModel):
    """Конфиг MainWindow — объединяет секции."""

    window: WindowConfig = Field(default_factory=WindowConfig)
