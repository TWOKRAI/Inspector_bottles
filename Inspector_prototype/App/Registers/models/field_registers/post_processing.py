# -*- coding: utf-8 -*-
"""
Регистры пост-обработки.
Поля заданы через общую схему полей регистров.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema.field_schema import DEFAULT_FIELD_SCHEMA
from App.Registers.models.field_registers.data_schema.metadata_helper import RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class PostProcessingRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры пост-обработки"""

    enable_post_processing: bool = field_from_schema(False, description='Включить пост-обработку', info='Включить пост-обработку')
    regions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Список регионов',
        json_schema_extra={**DEFAULT_FIELD_SCHEMA, 'info': 'Список регионов'},
    )
    region_chains: Dict[str, Any] = Field(
        default_factory=dict,
        description='Цепочки обработки по регионам',
        json_schema_extra={**DEFAULT_FIELD_SCHEMA, 'info': 'Цепочки обработки по регионам'},
    )
    view_mode: str = field_from_schema('main', description='Режим просмотра: main, region, list', info='Режим просмотра')
    selected_region: Optional[str] = field_from_schema(None, description='Выбранный регион', info='Выбранный регион')
    show_region_processed: bool = field_from_schema(False, description='Показать обработанный регион', info='Показать обработанный регион')
