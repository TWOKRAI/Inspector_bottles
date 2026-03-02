# Схема полей дата-моделей — из BaseFieldMeta (один источник истины).
from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema

from App.Registers.models.field_core import BaseFieldMeta

DEFAULT_DATA_FIELD_SCHEMA = BaseFieldMeta.schema_defaults()
field_from_schema = FieldSchema(DEFAULT_DATA_FIELD_SCHEMA)

__all__ = ["DEFAULT_DATA_FIELD_SCHEMA", "field_from_schema"]
