"""
Примеры конвертации данных между форматами.

Демонстрирует:
- Конвертация Pydantic моделей в различные форматы (dict, JSON, YAML)
- Конвертация из форматов обратно в модели
- Универсальная конвертация через FormatType
"""

from pydantic import BaseModel, Field
from pathlib import Path

from ...registry.schema_registry import SchemaRegistry
from ...utils.converters import DataConverter, FormatType


class LoggerConfig(BaseModel):
    """Конфигурация логгера."""
    log_level: str = Field(default="INFO")
    file_path: str = Field(default="logs/app.log")
    max_file_size: int = Field(default=10485760)


def example_model_to_dict():
    """
    Пример 1: Конвертация модели в словарь.
    
    Самый простой способ получить словарь из Pydantic модели.
    """
    print("\n=== Пример 1: Модель -> Словарь ===")
    
    schema_registry = SchemaRegistry.get_instance()
    config = schema_registry.create_instance(
        "LoggerManager",
        {"log_level": "DEBUG", "file_path": "logs/debug.log"}
    )
    
    # Конвертация модели в словарь
    data_dict = DataConverter.model_to_dict(config)
    print(f"Модель -> Словарь: {data_dict}")
    print(f"Тип результата: {type(data_dict)}")


def example_model_to_json():
    """
    Пример 2: Конвертация модели в JSON.
    
    Полезно для сериализации данных для передачи по сети или сохранения.
    """
    print("\n=== Пример 2: Модель -> JSON ===")
    
    schema_registry = SchemaRegistry.get_instance()
    config = schema_registry.create_instance(
        "LoggerManager",
        {"log_level": "DEBUG", "file_path": "logs/debug.log"}
    )
    
    # Конвертация модели в JSON строку
    json_str = DataConverter.model_to_json(config)
    print(f"Модель -> JSON:\n{json_str}")
    
    # С красивым форматированием (indent)
    json_pretty = DataConverter.model_to_json(config, indent=2)
    print(f"\nКрасивый JSON:\n{json_pretty}")


def example_model_to_yaml():
    """
    Пример 3: Конвертация модели в YAML.
    
    YAML удобен для конфигурационных файлов - более читаемый чем JSON.
    """
    print("\n=== Пример 3: Модель -> YAML ===")
    
    schema_registry = SchemaRegistry.get_instance()
    config = schema_registry.create_instance(
        "LoggerManager",
        {"log_level": "DEBUG", "file_path": "logs/debug.log"}
    )
    
    # Конвертация модели в YAML строку
    yaml_str = DataConverter.model_to_yaml(config)
    print(f"Модель -> YAML:\n{yaml_str}")


def example_json_to_model():
    """
    Пример 4: Конвертация JSON обратно в модель.
    
    Десериализация JSON строки в Pydantic модель с валидацией.
    """
    print("\n=== Пример 4: JSON -> Модель ===")
    
    # JSON строка
    json_str = '{"log_level": "ERROR", "file_path": "logs/error.log", "max_file_size": 2048000}'
    
    # Конвертация JSON в модель
    config = DataConverter.json_to_model(json_str, LoggerConfig)
    print(f"JSON -> Модель: {config.model_dump()}")
    print(f"Тип результата: {type(config)}")
    print(f"log_level: {config.log_level}")


def example_universal_conversion():
    """
    Пример 5: Универсальная конвертация через FormatType.
    
    Используйте FormatType для конвертации между любыми поддерживаемыми форматами.
    """
    print("\n=== Пример 5: Универсальная конвертация ===")
    
    schema_registry = SchemaRegistry.get_instance()
    config = schema_registry.create_instance(
        "LoggerManager",
        {"log_level": "DEBUG"}
    )
    
    # MODEL -> JSON
    json_str = DataConverter.convert(
        config,
        FormatType.MODEL,
        FormatType.JSON
    )
    print(f"MODEL -> JSON: {json_str[:50]}...")
    
    # MODEL -> DICT
    data_dict = DataConverter.convert(
        config,
        FormatType.MODEL,
        FormatType.DICT
    )
    print(f"MODEL -> DICT: {data_dict}")
    
    # DICT -> JSON
    json_from_dict = DataConverter.convert(
        data_dict,
        FormatType.DICT,
        FormatType.JSON
    )
    print(f"DICT -> JSON: {json_from_dict[:50]}...")


if __name__ == "__main__":
    print("Примеры конвертации данных между форматами")
    print("=" * 60)
    
    # Регистрируем схему для примеров
    SchemaRegistry.get_instance().register("LoggerManager", LoggerConfig)
    
    example_model_to_dict()
    example_model_to_json()
    example_model_to_yaml()
    example_json_to_model()
    example_universal_conversion()
    
    print("\n" + "=" * 60)
    print("Все примеры выполнены успешно!")

