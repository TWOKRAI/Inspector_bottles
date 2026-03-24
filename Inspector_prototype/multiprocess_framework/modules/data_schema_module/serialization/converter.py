# -*- coding: utf-8 -*-
"""
DataConverter — конвертер между различными форматами данных.

Поддерживает конвертацию:
    Pydantic Model <-> Dict
    Pydantic Model <-> JSON
    Pydantic Model <-> YAML
    Dict <-> JSON
    Dict <-> YAML
    И другие комбинации

Использует возможности Pydantic v2 для эффективной сериализации.
"""
import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class FormatType(str, Enum):
    """Типы форматов данных."""

    DICT = "dict"
    JSON = "json"
    YAML = "yaml"
    MODEL = "model"


class DataConverter:
    """
    Конвертер данных между различными форматами.

    Все методы статические — не требует создания экземпляра.
    """

    @staticmethod
    def model_to_dict(
        model: BaseModel,
        include: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        mode: str = "python",
    ) -> Dict[str, Any]:
        """Конвертировать Pydantic модель в словарь."""
        return model.model_dump(
            include=include,
            exclude=exclude,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            mode=mode,
        )

    @staticmethod
    def dict_to_model(
        data: Dict[str, Any],
        model_class: Type[T],
        strict: bool = False,
    ) -> T:
        """Конвертировать словарь в Pydantic модель."""
        return model_class.model_validate(data, strict=strict)

    @staticmethod
    def model_to_json(
        model: BaseModel,
        indent: Optional[int] = 2,
        ensure_ascii: bool = False,
        include: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> str:
        """Конвертировать Pydantic модель в JSON строку (Pydantic v2 model_dump_json)."""
        if ensure_ascii:
            data = model.model_dump(
                include=include,
                exclude=exclude,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            )
            return json.dumps(data, indent=indent, ensure_ascii=True)
        return model.model_dump_json(
            indent=indent,
            include=include,
            exclude=exclude,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )

    @staticmethod
    def json_to_model(
        json_str: Union[str, bytes],
        model_class: Type[T],
        strict: bool = False,
    ) -> T:
        """Конвертировать JSON строку в Pydantic модель."""
        if isinstance(json_str, bytes):
            json_str = json_str.decode("utf-8")
        return model_class.model_validate_json(json_str, strict=strict)

    @staticmethod
    def model_to_yaml(
        model: BaseModel,
        include: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        default_flow_style: bool = False,
        sort_keys: bool = False,
    ) -> str:
        """Конвертировать Pydantic модель в YAML строку."""
        try:
            import yaml
        except ImportError:
            raise ImportError("Для работы с YAML установите PyYAML: pip install pyyaml")

        data_dict = DataConverter.model_to_dict(
            model,
            include=include,
            exclude=exclude,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )
        return yaml.dump(
            data_dict,
            allow_unicode=True,
            default_flow_style=default_flow_style,
            sort_keys=sort_keys,
        )

    @staticmethod
    def yaml_to_model(
        yaml_str: Union[str, Path],
        model_class: Type[T],
        strict: bool = False,
    ) -> T:
        """Конвертировать YAML строку или файл в Pydantic модель."""
        try:
            import yaml
        except ImportError:
            raise ImportError("Для работы с YAML установите PyYAML: pip install pyyaml")

        if isinstance(yaml_str, Path):
            with open(yaml_str, "r", encoding="utf-8") as f:
                data_dict = yaml.safe_load(f) or {}
        else:
            data_dict = yaml.safe_load(yaml_str) or {}

        return DataConverter.dict_to_model(data_dict, model_class, strict)

    @staticmethod
    def dict_to_json(
        data: Dict[str, Any],
        indent: Optional[int] = 2,
        ensure_ascii: bool = False,
    ) -> str:
        """Конвертировать словарь в JSON строку."""
        return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=str)

    @staticmethod
    def json_to_dict(json_str: Union[str, bytes]) -> Dict[str, Any]:
        """Конвертировать JSON строку в словарь."""
        if isinstance(json_str, bytes):
            json_str = json_str.decode("utf-8")
        return json.loads(json_str)

    @staticmethod
    def dict_to_yaml(
        data: Dict[str, Any],
        default_flow_style: bool = False,
        sort_keys: bool = False,
    ) -> str:
        """Конвертировать словарь в YAML строку."""
        try:
            import yaml
        except ImportError:
            raise ImportError("Для работы с YAML установите PyYAML: pip install pyyaml")
        return yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=default_flow_style,
            sort_keys=sort_keys,
        )

    @staticmethod
    def yaml_to_dict(yaml_str: Union[str, Path]) -> Dict[str, Any]:
        """Конвертировать YAML строку или файл в словарь."""
        try:
            import yaml
        except ImportError:
            raise ImportError("Для работы с YAML установите PyYAML: pip install pyyaml")
        if isinstance(yaml_str, Path):
            with open(yaml_str, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return yaml.safe_load(yaml_str) or {}

    @staticmethod
    def convert(
        data: Any,
        from_format: FormatType,
        to_format: FormatType,
        model_class: Optional[Type[T]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Универсальный метод конвертации между форматами.

        Example:
            json_str = DataConverter.convert({"key": "value"}, FormatType.DICT, FormatType.JSON)
            model = DataConverter.convert('{"v": 1}', FormatType.JSON, FormatType.MODEL, model_class=MyModel)
        """
        if from_format == to_format:
            return data

        if from_format == FormatType.MODEL:
            if not isinstance(data, BaseModel):
                raise TypeError("Для from_format=MODEL данные должны быть экземпляром BaseModel")
            intermediate = DataConverter.model_to_dict(data, **kwargs)
        elif from_format == FormatType.JSON:
            intermediate = DataConverter.json_to_dict(data)
        elif from_format == FormatType.YAML:
            intermediate = DataConverter.yaml_to_dict(data)
        elif from_format == FormatType.DICT:
            intermediate = data
        else:
            raise ValueError(f"Неизвестный исходный формат: {from_format}")

        if to_format == FormatType.MODEL:
            if model_class is None:
                raise ValueError("model_class обязателен для конвертации в MODEL")
            return DataConverter.dict_to_model(intermediate, model_class, **kwargs)
        elif to_format == FormatType.JSON:
            return DataConverter.dict_to_json(intermediate, **kwargs)
        elif to_format == FormatType.YAML:
            return DataConverter.dict_to_yaml(intermediate, **kwargs)
        elif to_format == FormatType.DICT:
            return intermediate
        else:
            raise ValueError(f"Неизвестный целевой формат: {to_format}")

    @staticmethod
    def save_to_file(
        data: Any,
        file_path: Union[str, Path],
        format_type: Optional[FormatType] = None,
        model_class: Optional[Type[T]] = None,
        **kwargs: Any,
    ) -> None:
        """Сохранить данные в файл (JSON или YAML)."""
        path = Path(file_path)

        if format_type is None:
            if path.suffix in (".json",):
                format_type = FormatType.JSON
            elif path.suffix in (".yaml", ".yml"):
                format_type = FormatType.YAML
            else:
                format_type = FormatType.JSON

        if isinstance(data, BaseModel):
            from_format = FormatType.MODEL
            if model_class is None:
                model_class = type(data)
        elif isinstance(data, dict):
            from_format = FormatType.DICT
        elif isinstance(data, str):
            from_format = (
                FormatType.JSON
                if data.strip().startswith(("{", "["))
                else FormatType.YAML
            )
        else:
            raise TypeError(f"Неподдерживаемый тип данных: {type(data)}")

        if format_type == FormatType.JSON:
            content = DataConverter.convert(data, from_format, FormatType.JSON, model_class, **kwargs)
        elif format_type == FormatType.YAML:
            content = DataConverter.convert(data, from_format, FormatType.YAML, model_class, **kwargs)
        else:
            raise ValueError(f"Формат {format_type} не поддерживается для сохранения в файл")

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def load_from_file(
        file_path: Union[str, Path],
        format_type: Optional[FormatType] = None,
        model_class: Optional[Type[T]] = None,
        strict: bool = False,
    ) -> Union[Dict[str, Any], Any]:
        """Загрузить данные из файла (JSON или YAML)."""
        path = Path(file_path)

        if format_type is None:
            if path.suffix in (".json",):
                format_type = FormatType.JSON
            elif path.suffix in (".yaml", ".yml"):
                format_type = FormatType.YAML
            else:
                format_type = FormatType.JSON

        if format_type == FormatType.JSON:
            data = DataConverter.json_to_dict(path.read_text(encoding="utf-8"))
        elif format_type == FormatType.YAML:
            data = DataConverter.yaml_to_dict(path)
        else:
            raise ValueError(f"Формат {format_type} не поддерживается для загрузки из файла")

        if model_class:
            return DataConverter.dict_to_model(data, model_class, strict)

        return data
