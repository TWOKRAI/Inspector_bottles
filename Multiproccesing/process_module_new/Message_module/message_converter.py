import json
from typing import Dict, List, Any, Optional, Union, Set
import yaml 
from dataclasses import asdict


class MessageConverter:
    """
    Базовый класс для конвертации сообщений в различные форматы.
    Предоставляет методы для конвертации в словарь, JSON, YAML и текстовый формат.
    """

    def to_dict(self, exclude_none: bool = True, exclude_fields: Set[str] = None, include_fields: Set[str] = None) -> Dict:
        """
        Конвертирует сообщение в словарь.

        Args:
            exclude_none (bool): Исключать поля со значением None.
            exclude_fields (Set[str]): Множество имен полей, которые нужно исключить.
            include_fields (Set[str]): Множество имен полей, которые нужно включить.

        Returns:
            Dict: Словарь с данными сообщения.
        """
        data = asdict(self)
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        if exclude_fields:
            data = {k: v for k, v in data.items() if k not in exclude_fields}
        if include_fields:
            data = {k: v for k, v in data.items() if k in include_fields}
        return data

    def to_json(self, exclude_none: bool = True, exclude_fields: Set[str] = None, include_fields: Set[str] = None) -> str:
        """
        Конвертирует сообщение в JSON.

        Args:
            exclude_none (bool): Исключать поля со значением None.
            exclude_fields (Set[str]): Множество имен полей, которые нужно исключить.
            include_fields (Set[str]): Множество имен полей, которые нужно включить.

        Returns:
            str: JSON строка с данными сообщения.
        """
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return json.dumps(data)

    def to_yaml(self, exclude_none: bool = True, exclude_fields: Set[str] = None, include_fields: Set[str] = None) -> str:
        """
        Конвертирует сообщение в YAML.

        Args:
            exclude_none (bool): Исключать поля со значением None.
            exclude_fields (Set[str]): Множество имен полей, которые нужно исключить.
            include_fields (Set[str]): Множество имен полей, которые нужно включить.

        Returns:
            str: YAML строка с данными сообщения.
        """
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return yaml.dump(data)

    def to_text(self, exclude_none: bool = True, exclude_fields: Set[str] = None, include_fields: Set[str] = None) -> str:
        """
        Конвертирует сообщение в текстовый формат.

        Args:
            exclude_none (bool): Исключать поля со значением None.
            exclude_fields (Set[str]): Множество имен полей, которые нужно исключить.
            include_fields (Set[str]): Множество имен полей, которые нужно включить.

        Returns:
            str: Текстовая строка с данными сообщения.
        """
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return "\n".join(f"{k}: {v}" for k, v in data.items())
