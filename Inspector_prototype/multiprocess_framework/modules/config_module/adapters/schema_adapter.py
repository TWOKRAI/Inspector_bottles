# -*- coding: utf-8 -*-
"""
ConfigSchemaAdapter — преобразование SchemaBase в дерево параметров ConfigManager.

Назначение:
    Адаптер читает FieldMeta каждого поля схемы и строит описание параметров
    конфигурации: тип, значение по умолчанию, ограничения, описание, i18n.
    ConfigManager использует этот словарь для валидации, UI-отображения и
    сохранения конфигурации.

Паттерн: Dependency Inversion
    ConfigSchemaAdapter реализует ISchemaAdapter (из data_schema_module.interfaces).
    data_schema_module ничего не знает о config_module — зависимость однонаправленная.

Расширяемость:
    - Переопределить _build_param_info() для кастомного формата параметра.
    - Добавить поддержку секций через опцию group_by_prefix=True.
    - Добавить фильтрацию readonly-полей через опцию include_readonly=False.
    - Добавить экспорт в JSON Schema через adapt_to_json_schema().

Использование:
    from modules.config_module.adapters.schema_adapter import ConfigSchemaAdapter
    from my_module.config.my_config import MyConfig

    adapter = ConfigSchemaAdapter()
    params = adapter.adapt(MyConfig)
    # {
    #     "timeout": {
    #         "type": "float",
    #         "default": 5.0,
    #         "description": "Таймаут, сек",
    #         "constraints": {"min": 0.1, "max": 60.0},
    #         "unit": "s",
    #     },
    #     ...
    # }
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type


class ConfigSchemaAdapter:
    """
    Адаптер для преобразования SchemaBase в реестр параметров ConfigManager.

    Реализует протокол ISchemaAdapter из data_schema_module.interfaces:
        adapt(schema_class, **options) -> Dict[str, Any]
        adapt_instance(schema_instance, **options) -> Dict[str, Any]

    Результат adapt():
        {
            "<field_name>": {
                "type": "float",
                "default": 1.4,
                "description": "Разрешение",
                "constraints": {"min": 0.1, "max": 20.0},  # если есть
                "unit": "px",                               # если есть
                "access_level": 0,                         # если > 0
                "readonly": True,                          # если True
                "info": "...",                             # если есть
                "examples": [...],                         # если есть
                "description_i18n": {...},                 # если есть
            },
            ...
        }
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]:
        """
        Преобразовать класс схемы в реестр параметров конфигурации.

        Args:
            schema_class: Класс схемы (наследник SchemaBase).
            **options:
                include_readonly (bool): Включить readonly-поля (по умолчанию True).
                max_access_level (int): Максимальный уровень доступа для включения.
                group_by_prefix (bool): Группировать поля по префиксу имени (через "_").

        Returns:
            Dict[field_name, param_info_dict]
        """
        result: Dict[str, Any] = {}
        include_readonly: bool = options.get("include_readonly", True)
        max_level: Optional[int] = options.get("max_access_level")

        if not hasattr(schema_class, "get_all_fields_meta"):
            return result

        for field_name, meta in schema_class.get_all_fields_meta().items():
            # Фильтр readonly
            if not include_readonly and getattr(meta, "readonly", False):
                continue

            # Фильтр по уровню доступа
            if max_level is not None and getattr(meta, "access_level", 0) > max_level:
                continue

            field_info = None
            if hasattr(schema_class, "model_fields"):
                field_info = schema_class.model_fields.get(field_name)

            result[field_name] = self._build_param_info(field_name, meta, field_info)

        if options.get("group_by_prefix"):
            result = self._group_by_prefix(result)

        return result

    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """
        Преобразовать экземпляр схемы в параметры с текущими значениями.

        Args:
            schema_instance: Экземпляр SchemaBase.
            **options: Передаются в adapt().

        Returns:
            Dict[field_name, param_info_dict] с добавленным ключом "value".
        """
        params = self.adapt(type(schema_instance), **options)

        if hasattr(schema_instance, "model_dump"):
            values = schema_instance.model_dump()
            for field_name, param_info in params.items():
                if isinstance(param_info, dict) and "fields" not in param_info:
                    param_info["value"] = values.get(field_name)

        return params

    def adapt_to_json_schema(self, schema_class: Type) -> Dict[str, Any]:
        """
        Преобразовать схему в JSON Schema (draft-07).

        Полезно для интеграции с UI-фреймворками и валидаторами.
        """
        properties: Dict[str, Any] = {}
        required = []

        if not hasattr(schema_class, "get_all_fields_meta"):
            return {"type": "object", "properties": {}}

        for field_name, meta in schema_class.get_all_fields_meta().items():
            field_info = None
            if hasattr(schema_class, "model_fields"):
                field_info = schema_class.model_fields.get(field_name)

            prop: Dict[str, Any] = {
                "description": getattr(meta, "description", field_name) or field_name,
            }

            # Тип
            annotation = getattr(field_info, "annotation", None) if field_info else None
            json_type = self._annotation_to_json_type(annotation)
            prop["type"] = json_type

            # Ограничения
            if getattr(meta, "min", None) is not None:
                prop["minimum"] = meta.min
            if getattr(meta, "max", None) is not None:
                prop["maximum"] = meta.max

            # Значение по умолчанию
            default = getattr(field_info, "default", None) if field_info else None
            if default is not None:
                prop["default"] = default
            else:
                required.append(field_name)

            properties[field_name] = prop

        schema: Dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": schema_class.__name__,
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema

    # -------------------------------------------------------------------------
    # Внутренние методы (переопределяемые в подклассах)
    # -------------------------------------------------------------------------

    def _build_param_info(
        self,
        field_name: str,
        meta: Any,
        field_info: Any,
    ) -> Dict[str, Any]:
        """Построить словарь описания параметра из FieldMeta и Pydantic FieldInfo."""
        annotation = getattr(field_info, "annotation", None) if field_info else None
        default = getattr(field_info, "default", None) if field_info else None

        param: Dict[str, Any] = {
            "type": self._get_type_name(annotation),
            "default": default,
            "description": getattr(meta, "description", None) or field_name,
        }

        # Опциональные поля из FieldMeta
        info = getattr(meta, "info", None)
        if info:
            param["info"] = info

        unit = getattr(meta, "unit", None)
        if unit:
            param["unit"] = unit

        min_val = getattr(meta, "min", None)
        max_val = getattr(meta, "max", None)
        if min_val is not None or max_val is not None:
            param["constraints"] = {}
            if min_val is not None:
                param["constraints"]["min"] = min_val
            if max_val is not None:
                param["constraints"]["max"] = max_val

        access_level = getattr(meta, "access_level", 0)
        if access_level > 0:
            param["access_level"] = access_level

        if getattr(meta, "readonly", False):
            param["readonly"] = True

        examples = getattr(meta, "examples", None)
        if examples:
            param["examples"] = examples

        description_i18n = getattr(meta, "description_i18n", None)
        if description_i18n:
            param["description_i18n"] = description_i18n

        return param

    def _group_by_prefix(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Сгруппировать параметры по префиксу имени (разделитель "_").

        Пример: {"draw_dp": ..., "draw_min_dist": ..., "enabled": ...}
            -> {"draw": {"dp": ..., "min_dist": ...}, "enabled": ...}
        """
        grouped: Dict[str, Any] = {}
        for field_name, param_info in params.items():
            parts = field_name.split("_", 1)
            if len(parts) == 2:
                prefix, rest = parts
                grouped.setdefault(prefix, {})[rest] = param_info
            else:
                grouped[field_name] = param_info
        return grouped

    def _get_type_name(self, annotation: Any) -> str:
        """Преобразовать type annotation в строку."""
        if annotation is None:
            return "any"
        if hasattr(annotation, "__name__"):
            return annotation.__name__
        # Обработка Optional[X], Annotated[X, ...] и т.д.
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            args = getattr(annotation, "__args__", ())
            # Optional[X] -> X
            if len(args) == 2 and type(None) in args:
                real = next(a for a in args if a is not type(None))
                return self._get_type_name(real)
            return str(origin)
        return str(annotation)

    def _annotation_to_json_type(self, annotation: Any) -> str:
        """Преобразовать Python type в JSON Schema type."""
        mapping = {
            "int": "integer",
            "float": "number",
            "str": "string",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }
        name = self._get_type_name(annotation)
        return mapping.get(name, "string")
