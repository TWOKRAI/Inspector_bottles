"""
Примеры базового использования Data Schema Module.

Демонстрирует:
- Определение схем данных
- Регистрация схем в реестре
- Создание экземпляров с дефолтными значениями
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional

from ...registry.schema_registry import SchemaManager


# Определение схемы данных
class LoggerConfig(BaseModel):
    """Конфигурация логгера."""
    log_level: str = Field(default="INFO", description="Уровень логирования")
    file_path: str = Field(default="logs/app.log", description="Путь к файлу")
    max_file_size: int = Field(default=10485760, description="Максимальный размер файла")
    rotation: bool = Field(default=True, description="Включить ротацию")
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Валидация уровня логирования."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level должен быть одним из {valid_levels}")
        return v.upper()


class DatabaseConfig(BaseModel):
    """Конфигурация базы данных."""
    host: str = Field(default="localhost")
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default="app_db")
    username: Optional[str] = None
    password: Optional[str] = None
    pool_size: int = Field(default=10, ge=1)


def example_register_schemas():
    """
    Пример 1: Регистрация схем в реестре.
    
    Реестр схем позволяет централизованно управлять всеми схемами данных.
    После регистрации схему можно использовать для создания экземпляров.
    """
    print("\n=== Пример 1: Регистрация схем ===")
    
    # Получаем экземпляр реестра (Singleton)
    schema_manager = SchemaManager.get_instance()
    
    # Регистрируем схемы с именами
    schema_manager.register("LoggerManager", LoggerConfig)
    schema_manager.register("DatabaseManager", DatabaseConfig)
    
    # Получаем список всех зарегистрированных схем
    schemas = schema_manager.list_schemas()
    print(f"Зарегистрированные схемы: {schemas}")
    
    # Проверяем наличие схемы
    has_logger = schema_manager.has_schema("LoggerManager")
    print(f"Схема LoggerManager зарегистрирована: {has_logger}")


def example_create_instances():
    """
    Пример 2: Создание экземпляров с дефолтными значениями.
    
    Реестр схем позволяет создавать экземпляры моделей с автоматическим
    заполнением дефолтных значений из схемы.
    """
    print("\n=== Пример 2: Создание экземпляров ===")
    
    schema_manager = SchemaManager.get_instance()
    
    # Создание с полными данными (перезаписывает дефолты)
    config1 = schema_manager.create_instance(
        "LoggerManager",
        {
            "log_level": "DEBUG",
            "file_path": "logs/debug.log"
        }
    )
    print(f"Конфигурация 1 (с данными): {config1.model_dump()}")
    
    # Создание с частичными данными (недостающие берутся из схемы)
    config2 = schema_manager.create_instance(
        "LoggerManager",
        {"log_level": "ERROR"}  # file_path будет взят из дефолтов
    )
    print(f"Конфигурация 2 (частичные данные): {config2.model_dump()}")
    
    # Создание только с дефолтными значениями (без данных)
    config3 = schema_manager.create_instance("LoggerManager")
    print(f"Конфигурация 3 (только дефолты): {config3.model_dump()}")


def example_get_defaults():
    """
    Пример 3: Получение дефолтных значений схемы.
    
    Можно получить все дефолтные значения схемы без создания экземпляра.
    """
    print("\n=== Пример 3: Дефолтные значения ===")
    
    schema_manager = SchemaManager.get_instance()
    
    # Получаем дефолтные значения схемы
    defaults = schema_manager.get_defaults("LoggerManager")
    print(f"Дефолтные значения LoggerManager: {defaults}")
    
    # Используем дефолты для создания конфигурации
    user_config = {
        "log_level": "WARNING"  # Перезаписываем только нужное поле
    }
    # Объединяем с дефолтами
    final_config = {**defaults, **user_config}
    print(f"Финальная конфигурация: {final_config}")


if __name__ == "__main__":
    print("Примеры базового использования Data Schema Module")
    print("=" * 60)
    
    example_register_schemas()
    example_create_instances()
    example_get_defaults()
    
    print("\n" + "=" * 60)
    print("Все примеры выполнены успешно!")

