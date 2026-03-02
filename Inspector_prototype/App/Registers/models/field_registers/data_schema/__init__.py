# Схема и миксины из field_core (один источник истины — класс).
from App.Registers.models.field_core import (
    NumericFieldMeta,
    RegisterMetadataHelper,
    RegistersContainerMetadataMixin,
)

DEFAULT_FIELD_SCHEMA = NumericFieldMeta.schema_defaults()

__all__ = [
    "DEFAULT_FIELD_SCHEMA",
    "RegisterMetadataHelper",
    "RegistersContainerMetadataMixin",
]
