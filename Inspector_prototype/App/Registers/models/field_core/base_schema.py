from typing import Any, Dict

"""
Базовые словари-схемы для всех полей (регистров и дата-моделей).

Задача этого модуля — задать единый «каркас» метаданных, который затем
наследуют/расширяют конкретные профили (регистры, данные и т.п.).
"""


BASE_FIELD_SCHEMA: Dict[str, Any] = {
    "info": "",
    "info_i18n": {
        "ru": "",
        "en": "",
        "de": "",
    },
    "description_i18n": {
        "ru": "",
        "en": "",
        "de": "",
    },
    "unit": "",
    "access_level": 0,
    "examples": [],
    "routing": {"router": "", "channel": ""},
    "readonly": False,
    "hidden": False,
}


# Расширение для числовых полей регистров управления (слайдеры и т.п.)
REGISTER_NUMERIC_EXTENSION: Dict[str, Any] = {
    "min": 0,
    "max": 1000,
    "transfer_k": 1.0,
    "round_k": 1,
}


# Расширение для числовых полей дата-моделей (как правило, просто диапазон)
DATA_NUMERIC_EXTENSION: Dict[str, Any] = {
    "min": None,
    "max": None,
}


DEFAULT_REGISTER_FIELD_SCHEMA: Dict[str, Any] = {
    **BASE_FIELD_SCHEMA,
    **REGISTER_NUMERIC_EXTENSION,
}

DEFAULT_DATA_FIELD_SCHEMA: Dict[str, Any] = {
    **BASE_FIELD_SCHEMA,
    **DATA_NUMERIC_EXTENSION,
}


__all__ = [
    "BASE_FIELD_SCHEMA",
    "REGISTER_NUMERIC_EXTENSION",
    "DATA_NUMERIC_EXTENSION",
    "DEFAULT_REGISTER_FIELD_SCHEMA",
    "DEFAULT_DATA_FIELD_SCHEMA",
]

