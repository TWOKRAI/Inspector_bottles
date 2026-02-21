# -*- coding: utf-8 -*-
"""
Регистры пост-обработки.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class PostProcessingRegisters(BaseModel):
    """Регистры пост-обработки"""
    enable_post_processing: bool = Field(default=False, description='Включить пост-обработку')
    regions: List[Dict[str, Any]] = Field(default_factory=list, description='Список регионов')
    region_chains: Dict[str, Any] = Field(default_factory=dict, description='Цепочки обработки по регионам')
    view_mode: str = Field(default='main', description='Режим просмотра: main, region, list')
    selected_region: Optional[str] = Field(default=None, description='Выбранный регион')
    show_region_processed: bool = Field(default=False, description='Показать обработанный регион')
