# -*- coding: utf-8 -*-
"""
Регистры управления камерой.
"""
from pydantic import BaseModel, Field


class CameraRegisters(BaseModel):
    """Регистры управления камерой"""
    source: str = Field(default='camera', description='Источник кадров: camera или image')
    image_path: str = Field(default='Data/last_frame.png', description='Путь к изображению при source=image')
    enable_main_processing: bool = Field(default=True, description='Главный выключатель обработки')
