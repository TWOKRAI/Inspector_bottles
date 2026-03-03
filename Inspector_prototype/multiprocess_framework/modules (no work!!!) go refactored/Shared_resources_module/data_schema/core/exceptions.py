"""
Исключения модуля data_schema.

Иерархия исключений для удобной обработки ошибок и интеграции с ExceptionManager.
"""


class DataSchemaError(Exception):
    """Базовое исключение модуля data_schema."""
    
    def __init__(self, message: str, context: dict = None):
        """
        Инициализация исключения.
        
        Args:
            message: Сообщение об ошибке
            context: Дополнительный контекст ошибки
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
    
    def to_dict(self) -> dict:
        """Преобразовать исключение в словарь для логирования."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context
        }


class SchemaNotFoundError(DataSchemaError):
    """Схема не найдена в реестре."""
    
    def __init__(self, schema_name: str, available_schemas: list = None):
        """
        Инициализация исключения.
        
        Args:
            schema_name: Имя схемы, которая не найдена
            available_schemas: Список доступных схем
        """
        message = f"Схема '{schema_name}' не найдена в реестре"
        if available_schemas:
            message += f". Доступные схемы: {', '.join(available_schemas[:10])}"
        super().__init__(message, {
            "schema_name": schema_name,
            "available_schemas": available_schemas or []
        })
        self.schema_name = schema_name
        self.available_schemas = available_schemas or []


class SchemaValidationError(DataSchemaError):
    """Ошибка валидации данных по схеме."""
    
    def __init__(self, schema_name: str, validation_errors: list, data: dict = None):
        """
        Инициализация исключения.
        
        Args:
            schema_name: Имя схемы
            validation_errors: Список ошибок валидации от Pydantic
            data: Данные, которые не прошли валидацию
        """
        error_messages = "; ".join([
            f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg', 'Unknown error')}"
            for err in validation_errors
        ])
        message = f"Ошибка валидации схемы '{schema_name}': {error_messages}"
        super().__init__(message, {
            "schema_name": schema_name,
            "validation_errors": validation_errors,
            "data": data
        })
        self.schema_name = schema_name
        self.validation_errors = validation_errors
        self.data = data


class SchemaRegistrationError(DataSchemaError):
    """Ошибка регистрации схемы."""
    
    def __init__(self, schema_name: str, reason: str, schema_class: type = None):
        """
        Инициализация исключения.
        
        Args:
            schema_name: Имя схемы
            reason: Причина ошибки
            schema_class: Класс схемы (если доступен)
        """
        message = f"Ошибка регистрации схемы '{schema_name}': {reason}"
        super().__init__(message, {
            "schema_name": schema_name,
            "reason": reason,
            "schema_class": str(schema_class) if schema_class else None
        })
        self.schema_name = schema_name
        self.reason = reason
        self.schema_class = schema_class


class InvalidParameterError(DataSchemaError):
    """Ошибка валидации параметра."""
    
    def __init__(self, parameter_name: str, value: any, reason: str):
        """
        Инициализация исключения.
        
        Args:
            parameter_name: Имя параметра
            value: Значение параметра
            reason: Причина ошибки
        """
        message = f"Неверный параметр '{parameter_name}': {reason}"
        super().__init__(message, {
            "parameter_name": parameter_name,
            "value": str(value),
            "reason": reason
        })
        self.parameter_name = parameter_name
        self.value = value
        self.reason = reason


class DataManagerError(DataSchemaError):
    """Ошибка работы с DataManager."""
    pass


class VersionManagerError(DataSchemaError):
    """Ошибка работы с VersionManager."""
    pass

