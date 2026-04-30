"""
Примеры валидации данных.

Демонстрирует:
- Валидация данных по схемам
- Получение ошибок валидации
- Проверка валидности без создания экземпляра
"""

from pydantic import BaseModel, Field, field_validator

from ...utils.validators import DataValidator


class LoggerConfig(BaseModel):
    """Конфигурация логгера с валидацией."""
    log_level: str = Field(default="INFO", description="Уровень логирования")
    file_path: str = Field(default="logs/app.log", description="Путь к файлу")
    max_file_size: int = Field(default=10485760, ge=0, description="Максимальный размер файла")
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Валидация уровня логирования."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level должен быть одним из {valid_levels}")
        return v.upper()


def example_validate_success():
    """
    Пример 1: Успешная валидация данных.
    
    Валидация возвращает кортеж (success, instance, error).
    При успехе instance содержит созданный экземпляр модели.
    """
    print("\n=== Пример 1: Успешная валидация ===")
    
    # Валидные данные
    valid_data = {
        "log_level": "DEBUG",
        "file_path": "logs/app.log",
        "max_file_size": 10485760
    }
    
    # Валидация
    success, instance, error = DataValidator.validate(valid_data, LoggerConfig)
    
    print(f"Валидация успешна: {success}")
    if success:
        print(f"Созданный экземпляр: {instance.model_dump()}")
        print(f"log_level: {instance.log_level}")
        print(f"file_path: {instance.file_path}")


def example_validate_failure():
    """
    Пример 2: Неудачная валидация данных.
    
    При ошибке валидации success=False, instance=None, error содержит описание ошибки.
    """
    print("\n=== Пример 2: Неудачная валидация ===")
    
    # Невалидные данные (неправильный log_level)
    invalid_data = {
        "log_level": "INVALID_LEVEL",  # Неправильное значение
        "file_path": "logs/app.log"
    }
    
    # Валидация
    success, instance, error = DataValidator.validate(invalid_data, LoggerConfig)
    
    print(f"Валидация успешна: {success}")
    if not success:
        print(f"Ошибка валидации: {error}")
        print(f"Экземпляр не создан: {instance is None}")


def example_is_valid():
    """
    Пример 3: Проверка валидности без создания экземпляра.
    
    Быстрая проверка валидности данных без создания объекта модели.
    """
    print("\n=== Пример 3: Проверка валидности ===")
    
    # Валидные данные
    valid_data = {"log_level": "INFO"}
    is_valid = DataValidator.is_valid(valid_data, LoggerConfig)
    print(f"Данные валидны: {is_valid}")
    
    # Невалидные данные
    invalid_data = {"log_level": "INVALID"}
    is_valid = DataValidator.is_valid(invalid_data, LoggerConfig)
    print(f"Данные валидны: {is_valid}")


def example_get_validation_errors():
    """
    Пример 4: Получение детальных ошибок валидации.
    
    Получаем список всех ошибок валидации с детальной информацией.
    """
    print("\n=== Пример 4: Детальные ошибки валидации ===")
    
    # Данные с несколькими ошибками
    invalid_data = {
        "log_level": "INVALID",  # Неправильный уровень
        "max_file_size": -1  # Отрицательное значение (нарушает ge=0)
    }
    
    # Получаем список ошибок
    errors = DataValidator.get_validation_errors(invalid_data, LoggerConfig)
    
    print(f"Найдено ошибок: {len(errors)}")
    for i, error in enumerate(errors, 1):
        print(f"\nОшибка {i}:")
        print(f"  Поле: {error.get('field', 'N/A')}")
        print(f"  Сообщение: {error.get('message', 'N/A')}")
        print(f"  Значение: {error.get('value', 'N/A')}")


def example_strict_validation():
    """
    Пример 5: Строгая валидация.
    
    Строгая валидация не допускает дополнительные поля, не определенные в схеме.
    """
    print("\n=== Пример 5: Строгая валидация ===")
    
    # Данные с дополнительным полем
    data_with_extra = {
        "log_level": "INFO",
        "file_path": "logs/app.log",
        "extra_field": "не должно быть здесь"  # Дополнительное поле
    }
    
    # Обычная валидация (extra_field игнорируется)
    success1, instance1, _ = DataValidator.validate(data_with_extra, LoggerConfig, strict=False)
    print(f"Обычная валидация: {success1}")
    if success1:
        print(f"Дополнительное поле игнорировано: {instance1.model_dump()}")
    
    # Строгая валидация (extra_field вызывает ошибку)
    success2, instance2, error2 = DataValidator.validate(data_with_extra, LoggerConfig, strict=True)
    print(f"\nСтрогая валидация: {success2}")
    if not success2:
        print(f"Ошибка из-за дополнительного поля: {error2}")


if __name__ == "__main__":
    print("Примеры валидации данных")
    print("=" * 60)
    
    example_validate_success()
    example_validate_failure()
    example_is_valid()
    example_get_validation_errors()
    example_strict_validation()
    
    print("\n" + "=" * 60)
    print("Все примеры выполнены успешно!")

