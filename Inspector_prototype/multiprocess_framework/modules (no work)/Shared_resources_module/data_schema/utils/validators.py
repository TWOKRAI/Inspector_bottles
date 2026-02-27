"""
Валидатор данных на основе Pydantic v2.

Использует встроенную валидацию Pydantic v2.
Предоставляет удобные методы для валидации данных.
"""

from typing import Any, Dict, Optional, Type, TypeVar, List
from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)


class DataValidator:
    """
    Валидатор данных на основе Pydantic v2.
    
    Предоставляет методы для валидации данных по Pydantic схемам.
    """
    
    @staticmethod
    def validate(
        data: Dict[str, Any],
        model_class: Type[T],
        strict: bool = False
    ) -> tuple[bool, Optional[T], Optional[str]]:
        """
        Валидировать данные по модели.
        
        Args:
            data: Данные для валидации
            model_class: Класс Pydantic модели
            strict: Строгий режим валидации
            
        Returns:
            Кортеж (успех, экземпляр модели или None, сообщение об ошибке или None)
            
        Example:
            class Config(BaseModel):
                log_level: str = "INFO"
            
            success, instance, error = DataValidator.validate(
                {"log_level": "DEBUG"},
                Config
            )
            
            if success:
                print(f"Валидация успешна: {instance.log_level}")
            else:
                print(f"Ошибка валидации: {error}")
        """
        try:
            instance = model_class.model_validate(data, strict=strict)
            return True, instance, None
        except ValidationError as e:
            error_msg = "; ".join([f"{err['loc']}: {err['msg']}" for err in e.errors()])
            return False, None, error_msg
    
    @staticmethod
    def validate_json(
        json_str: str,
        model_class: Type[T],
        strict: bool = False
    ) -> tuple[bool, Optional[T], Optional[str]]:
        """
        Валидировать JSON строку по модели.
        
        Args:
            json_str: JSON строка
            model_class: Класс Pydantic модели
            strict: Строгий режим валидации
            
        Returns:
            Кортеж (успех, экземпляр модели или None, сообщение об ошибке или None)
        """
        try:
            instance = model_class.model_validate_json(json_str, strict=strict)
            return True, instance, None
        except ValidationError as e:
            error_msg = "; ".join([f"{err['loc']}: {err['msg']}" for err in e.errors()])
            return False, None, error_msg
        except Exception as e:
            return False, None, f"Ошибка парсинга JSON: {str(e)}"
    
    @staticmethod
    def validate_partial(
        data: Dict[str, Any],
        model_class: Type[T],
        strict: bool = False
    ) -> tuple[bool, Optional[T], Optional[str]]:
        """
        Частичная валидация данных.
        
        Валидирует только переданные поля, остальные игнорируются.
        Полезно для обновления части данных модели.
        
        Args:
            data: Частичные данные для валидации
            model_class: Класс Pydantic модели
            strict: Строгий режим валидации
            
        Returns:
            Кортеж (успех, экземпляр модели или None, сообщение об ошибке или None)
            
        Example:
            # Валидация только части полей
            success, instance, error = DataValidator.validate_partial(
                {"log_level": "ERROR"},  # Только это поле валидируется
                Config
            )
        """
        try:
            # Создаем экземпляр с дефолтными значениями
            instance = model_class()
            
            # Обновляем только переданные поля
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            
            # Валидируем обновленный экземпляр
            validated = model_class.model_validate(instance.model_dump(), strict=strict)
            return True, validated, None
        except ValidationError as e:
            error_msg = "; ".join([f"{err['loc']}: {err['msg']}" for err in e.errors()])
            return False, None, error_msg
        except Exception as e:
            return False, None, f"Ошибка валидации: {str(e)}"
    
    @staticmethod
    def get_validation_errors(
        data: Dict[str, Any],
        model_class: Type[T],
        strict: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Получить список ошибок валидации без создания экземпляра.
        
        Args:
            data: Данные для валидации
            model_class: Класс Pydantic модели
            strict: Строгий режим валидации
            
        Returns:
            Список словарей с ошибками валидации
        """
        try:
            model_class.model_validate(data, strict=strict)
            return []
        except ValidationError as e:
            return e.errors()
    
    @staticmethod
    def is_valid(
        data: Dict[str, Any],
        model_class: Type[T],
        strict: bool = False
    ) -> bool:
        """
        Проверить валидность данных без создания экземпляра.
        
        Args:
            data: Данные для проверки
            model_class: Класс Pydantic модели
            strict: Строгий режим валидации
            
        Returns:
            True если данные валидны, False иначе
        """
        try:
            model_class.model_validate(data, strict=strict)
            return True
        except ValidationError:
            return False
    
    @staticmethod
    def validate_nested(
        data: Dict[str, Any],
        model_class: Type[T],
        nested_path: str,
        strict: bool = False
    ) -> tuple[bool, Optional[T], Optional[str]]:
        """
        Валидировать вложенную структуру данных.
        
        Args:
            data: Данные для валидации
            model_class: Класс Pydantic модели для вложенной структуры
            nested_path: Путь к вложенной структуре (точечная нотация)
            strict: Строгий режим валидации
            
        Returns:
            Кортеж (успех, экземпляр модели или None, сообщение об ошибке или None)
            
        Example:
            data = {
                "config": {
                    "log_level": "DEBUG",
                    "file_path": "logs/app.log"
                }
            }
            
            success, instance, error = DataValidator.validate_nested(
                data,
                LoggerConfig,
                "config"
            )
        """
        from .helpers import get_nested_value
        
        nested_data = get_nested_value(data, nested_path)
        if nested_data is None:
            return False, None, f"Путь {nested_path} не найден в данных"
        
        if not isinstance(nested_data, dict):
            return False, None, f"Значение по пути {nested_path} не является словарем"
        
        return DataValidator.validate(nested_data, model_class, strict)

