"""
Класс Config - контейнер данных для одной конфигурации.

Это НЕ менеджер, а простой класс для работы с данными одной конфигурации.
Используется ConfigManager для управления множеством таких конфигураций.

Интегрирован с data_schema_module для валидации и конвертации форматов.

Разница с ConfigManager:
- Config: работает с ОДНОЙ конфигурацией (данные, файлы, валидация)
- ConfigManager: управляет МНОЖЕСТВОМ Config объектов + интеграция с системой
"""
from typing import Dict, Any, Optional, Union, Callable, List, Type, TYPE_CHECKING
from pathlib import Path
import copy
from threading import RLock

if TYPE_CHECKING:
    from pydantic import BaseModel

from ...data_schema_module.utils.converters import DataConverter, FormatType
from ...data_schema_module.utils.validators import DataValidator


class Config:
    """
    Универсальная конфигурация с интеграцией data_schema_module.
    
    Особенности:
    - Вложенные ключи через точку: "database.host"
    - Потокобезопасность (thread-safe) через RLock
    - Загрузка/сохранение JSON/YAML файлов через DataConverter
    - Опциональная валидация через Pydantic схемы
    - Работа с секциями конфигурации
    - Поддержка переменных окружения (опционально)
    - Подписка на изменения конфигурации
    
    Attributes:
        _data: Внутренний словарь с данными конфигурации
        _lock: Блокировка для потокобезопасности
        _path: Путь к файлу конфигурации (если загружено из файла)
        _env_prefix: Префикс для переменных окружения
        _change_callbacks: Словарь callback-функций для отслеживания изменений
        _validation_schema: Опциональная Pydantic схема для валидации
        _validate_on_set: Валидировать ли данные при установке
    """
    
    def __init__(
        self, 
        initial_data: Optional[Dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None,
        validation_schema: Optional[Type["BaseModel"]] = None,
        validate_on_set: bool = False
    ):
        """
        Инициализация конфигурации.
        
        Args:
            initial_data: Начальные данные конфигурации (словарь)
            env_prefix: Префикс для переменных окружения (например, "APP")
            file_path: Путь к файлу конфигурации для автоматической загрузки
            validation_schema: Опциональная Pydantic схема для валидации
            validate_on_set: Валидировать ли данные при установке (по умолчанию False)
        
        Примеры:
            # Пустая конфигурация
            config = Config()
            
            # С начальными данными
            config = Config({'database': {'host': 'localhost'}})
            
            # С префиксом для переменных окружения
            config = Config(env_prefix='APP')
            
            # С автоматической загрузкой из файла
            config = Config(file_path='config/app.yaml')
            
            # С валидацией через Pydantic схему
            from pydantic import BaseModel
            class AppConfig(BaseModel):
                database_host: str = "localhost"
            
            config = Config(validation_schema=AppConfig, validate_on_set=True)
        """
        self._data: Dict[str, Any] = copy.deepcopy(initial_data) if initial_data else {}
        self._lock = RLock()
        self._path: Optional[Path] = None
        self._env_prefix: Optional[str] = env_prefix
        self._change_callbacks: Dict[str, List[Callable]] = {}
        self._validation_schema: Optional[Type["BaseModel"]] = validation_schema
        self._validate_on_set: bool = validate_on_set
        
        # Автоматическая загрузка из файла если указан путь
        if file_path:
            self.load(file_path)
    
    # ===== ОСНОВНЫЕ МЕТОДЫ РАБОТЫ С ДАННЫМИ =====
    
    def get(self, key: str, default: Any = None, env_fallback: bool = True) -> Any:
        """
        Получить значение по ключу.
        
        Поддерживает вложенные ключи через точку: "database.host"
        Опционально ищет значение в переменных окружения.
        
        Args:
            key: Ключ в формате 'section.subsection.key' или простой ключ
            default: Значение по умолчанию если ключ не найден
            env_fallback: Искать в переменных окружения если ключ не найден
        
        Returns:
            Значение конфигурации или default
        """
        with self._lock:
            # Разбиваем путь на части
            parts = key.split('.')
            value = self._data
            
            # Идем по вложенной структуре
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    # Ключ не найден, пробуем переменные окружения
                    if env_fallback and self._env_prefix:
                        env_value = self._get_from_env(key)
                        if env_value is not None:
                            return env_value
                    return default
            
            return value
    
    def set(self, key: str, value: Any, notify: bool = True, validate: Optional[bool] = None) -> 'Config':
        """
        Установить значение по ключу.
        
        Автоматически создает вложенную структуру если нужно.
        Опционально валидирует данные через Pydantic схему.
        Отправляет уведомления подписчикам об изменении.
        
        Args:
            key: Ключ в формате 'section.subsection.key'
            value: Значение для установки
            notify: Отправлять уведомления об изменении
            validate: Валидировать ли данные (если None, используется _validate_on_set)
        
        Returns:
            self (для цепочки вызовов)
        
        Raises:
            ValidationError: Если валидация включена и данные невалидны
        """
        # Определяем нужно ли валидировать
        should_validate = validate if validate is not None else self._validate_on_set
        
        # Валидация если включена
        if should_validate and self._validation_schema:
            # Валидируем полную конфигурацию после изменения
            temp_data = copy.deepcopy(self._data)
            parts = key.split('.')
            data = temp_data
            
            # Создаем вложенную структуру
            for part in parts[:-1]:
                if part not in data:
                    data[part] = {}
                elif not isinstance(data[part], dict):
                    data[part] = {}
                data = data[part]
            
            data[parts[-1]] = value
            
            # Валидируем через Pydantic схему
            success, validated_instance, error = DataValidator.validate(
                temp_data,
                self._validation_schema,
                strict=False
            )
            
            if not success:
                from pydantic import ValidationError
                raise ValidationError(f"Validation failed for key '{key}': {error}")
        
        with self._lock:
            old_value = self._get_internal(key)
            
            parts = key.split('.')
            data = self._data
            
            # Создаем вложенную структуру если нужно
            for part in parts[:-1]:
                if part not in data:
                    data[part] = {}
                elif not isinstance(data[part], dict):
                    # Если на пути не dict, заменяем его на dict
                    data[part] = {}
                data = data[part]
            
            # Устанавливаем значение
            data[parts[-1]] = value
            
            # Уведомляем об изменении
            if notify and old_value != value:
                self._notify_change(key, old_value, value)
        
        return self
    
    def update(self, data: Dict[str, Any], prefix: str = "") -> 'Config':
        """
        Обновить конфигурацию из словаря.
        
        Рекурсивно обновляет вложенные словари, сохраняя существующие значения.
        
        Args:
            data: Словарь с новыми значениями
            prefix: Префикс для ключей (например, "database")
        
        Returns:
            self (для цепочки вызовов)
        """
        with self._lock:
            if prefix:
                # Обновляем с префиксом
                for key, value in data.items():
                    self.set(f"{prefix}.{key}", value, notify=False)
                self._notify_change(prefix, None, data)
            else:
                # Обновляем корневой уровень
                self._deep_update(self._data, data)
                self._notify_change("*", None, data)
        
        return self
    
    def has(self, key: str) -> bool:
        """Проверить наличие ключа в конфигурации."""
        with self._lock:
            parts = key.split('.')
            value = self._data
            
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return False
            
            return True
    
    def remove(self, key: str) -> bool:
        """Удалить ключ из конфигурации."""
        with self._lock:
            parts = key.split('.')
            data = self._data
            
            # Идем до родительского элемента
            for part in parts[:-1]:
                if isinstance(data, dict) and part in data:
                    data = data[part]
                else:
                    return False
            
            # Удаляем конечный ключ
            if isinstance(data, dict) and parts[-1] in data:
                old_value = data[parts[-1]]
                del data[parts[-1]]
                self._notify_change(key, old_value, None)
                return True
            
            return False
    
    def clear(self) -> 'Config':
        """Очистить всю конфигурацию."""
        with self._lock:
            old_data = copy.deepcopy(self._data)
            self._data.clear()
            self._notify_change("*", old_data, {})
        
        return self
    
    # ===== РАБОТА С ФАЙЛАМИ (через DataConverter) =====
    
    def load(self, file_path: Union[str, Path], merge: bool = True) -> 'Config':
        """
        Загрузить конфигурацию из файла.
        
        Использует DataConverter из data_schema_module для загрузки.
        Поддерживает форматы: JSON (.json), YAML (.yaml, .yml)
        
        Args:
            file_path: Путь к файлу конфигурации
            merge: Если True, объединяет с существующими данными, иначе заменяет
        
        Returns:
            self (для цепочки вызовов)
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with self._lock:
            # Определяем формат по расширению
            if path.suffix.lower() in ['.yaml', '.yml']:
                data = DataConverter.yaml_to_dict(path)
            elif path.suffix.lower() == '.json':
                data = DataConverter.json_to_dict(path.read_text(encoding='utf-8'))
            else:
                # Пробуем определить формат по содержимому
                try:
                    data = DataConverter.yaml_to_dict(path)
                except Exception:
                    data = DataConverter.json_to_dict(path.read_text(encoding='utf-8'))
            
            # Валидация если схема указана
            if self._validation_schema:
                success, validated_instance, error = DataValidator.validate(
                    data,
                    self._validation_schema,
                    strict=False
                )
                if not success:
                    from pydantic import ValidationError
                    raise ValidationError(f"Validation failed when loading '{path}': {error}")
                # Используем валидированные данные
                data = validated_instance.model_dump() if validated_instance else data
            
            if merge:
                self._deep_update(self._data, data)
            else:
                self._data = data
            
            self._path = path
        
        return self
    
    def save(self, file_path: Optional[Union[str, Path]] = None) -> 'Config':
        """
        Сохранить конфигурацию в файл.
        
        Использует DataConverter из data_schema_module для сохранения.
        
        Args:
            file_path: Путь для сохранения (если None, использует путь загрузки)
        
        Returns:
            self (для цепочки вызовов)
        """
        path = Path(file_path) if file_path else self._path
        
        if not path:
            raise ValueError("No file path specified for saving. Use load() first or provide file_path.")
        
        # Создаем директорию если её нет
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._lock:
            # Определяем формат по расширению
            if path.suffix.lower() in ['.yaml', '.yml']:
                yaml_str = DataConverter.dict_to_yaml(self._data)
                path.write_text(yaml_str, encoding='utf-8')
            elif path.suffix.lower() == '.json':
                json_str = DataConverter.dict_to_json(self._data)
                path.write_text(json_str, encoding='utf-8')
            else:
                # По умолчанию используем YAML
                yaml_str = DataConverter.dict_to_yaml(self._data)
                path.write_text(yaml_str, encoding='utf-8')
        
        return self
    
    def reload(self) -> 'Config':
        """Перезагрузить конфигурацию из того же файла."""
        if not self._path:
            raise ValueError("Config was not loaded from file. Use load() first.")
        
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        
        return self.load(self._path, merge=False)
    
    # ===== РАБОТА С PYDANTIC МОДЕЛЯМИ =====
    
    def to_model(self, model_class: Type["BaseModel"]) -> "BaseModel":
        """
        Конвертировать конфигурацию в Pydantic модель.
        
        Использует DataConverter из data_schema_module.
        
        Args:
            model_class: Класс Pydantic модели
        
        Returns:
            Экземпляр Pydantic модели
        
        Raises:
            ValidationError: Если данные невалидны
        """
        return DataConverter.dict_to_model(self._data, model_class, strict=False)
    
    def from_model(self, model: "BaseModel") -> 'Config':
        """
        Загрузить конфигурацию из Pydantic модели.
        
        Использует DataConverter из data_schema_module.
        
        Args:
            model: Экземпляр Pydantic модели
        
        Returns:
            self (для цепочки вызовов)
        """
        with self._lock:
            self._data = DataConverter.model_to_dict(model)
            self._notify_change("*", None, self._data)
        
        return self
    
    # ===== РАБОТА С СЕКЦИЯМИ =====
    
    def section(self, section_key: str):
        """
        Получить доступ к секции конфигурации.
        
        Args:
            section_key: Ключ секции (например, 'database')
        
        Returns:
            ConfigSection - объект для работы с секцией
        """
        from ..sections.config_section import ConfigSection
        return ConfigSection(self, section_key)
    
    # ===== ПОДПИСКА НА ИЗМЕНЕНИЯ =====
    
    def subscribe(self, callback: Optional[Callable] = None, key: str = "*") -> Union[None, Callable]:
        """
        Подписаться на изменения конфигурации.
        
        Args:
            callback: Функция обратного вызова (key, old_value, new_value) или None для использования как декоратор
            key: Ключ для отслеживания или "*" для всех изменений
        
        Returns:
            Декоратор если callback не указан, иначе None
        """
        if callback is None:
            # Использование как декоратор
            def decorator(func: Callable) -> Callable:
                self.subscribe(func, key)
                return func
            return decorator
        else:
            # Прямая подписка
            with self._lock:
                if key not in self._change_callbacks:
                    self._change_callbacks[key] = []
                self._change_callbacks[key].append(callback)
            return None
    
    def unsubscribe(self, callback: Callable, key: str = "*") -> bool:
        """Отписаться от изменений конфигурации."""
        with self._lock:
            if key in self._change_callbacks:
                if callback in self._change_callbacks[key]:
                    self._change_callbacks[key].remove(callback)
                    return True
        return False
    
    # ===== СВОЙСТВА =====
    
    @property
    def data(self) -> Dict[str, Any]:
        """Получить копию всех данных конфигурации."""
        with self._lock:
            return copy.deepcopy(self._data)
    
    @property
    def file_path(self) -> Optional[Path]:
        """Получить путь к файлу конфигурации."""
        return self._path
    
    @property
    def validation_schema(self) -> Optional[Type["BaseModel"]]:
        """Получить схему валидации."""
        return self._validation_schema
    
    def set_validation_schema(self, schema: Optional[Type["BaseModel"]], validate_on_set: bool = False):
        """
        Установить схему валидации.
        
        Args:
            schema: Pydantic схема для валидации или None для отключения
            validate_on_set: Валидировать ли данные при установке
        """
        self._validation_schema = schema
        self._validate_on_set = validate_on_set
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def _get_internal(self, key: str) -> Any:
        """Внутренний метод для получения значения без блокировки."""
        parts = key.split('.')
        value = self._data
        
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        
        return value
    
    def _get_from_env(self, key: str) -> Optional[Any]:
        """Получить значение из переменных окружения."""
        if not self._env_prefix:
            return None
        
        import os
        # Преобразуем ключ в формат переменной окружения
        env_key = f"{self._env_prefix}_{key.upper().replace('.', '_')}"
        value = os.getenv(env_key)
        
        if value is None:
            return None
        
        # Пробуем преобразовать в нужный тип
        try:
            # JSON
            import json
            return json.loads(value)
        except (ValueError, json.JSONDecodeError):
            # Булевы значения
            if value.lower() in ['true', '1', 'yes', 'on']:
                return True
            if value.lower() in ['false', '0', 'no', 'off']:
                return False
            # Числа
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                pass
            # Строка
            return value
    
    def _deep_update(self, target: Dict, source: Dict) -> None:
        """Рекурсивно обновить словарь."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """Уведомить подписчиков об изменении."""
        # Уведомляем подписчиков на конкретный ключ
        if key in self._change_callbacks:
            for callback in self._change_callbacks[key]:
                try:
                    callback(key, old_value, new_value)
                except Exception:
                    pass  # Игнорируем ошибки в callback
        
        # Уведомляем подписчиков на все изменения
        if "*" in self._change_callbacks and key != "*":
            for callback in self._change_callbacks["*"]:
                try:
                    callback(key, old_value, new_value)
                except Exception:
                    pass
    
    # ===== МАГИЧЕСКИЕ МЕТОДЫ =====
    
    def __getitem__(self, key: str) -> Any:
        """Получить значение через синтаксис словаря."""
        value = self.get(key)
        if value is None:
            raise KeyError(f"Config key not found: {key}")
        return value
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Установить значение через синтаксис словаря."""
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """Проверить наличие ключа через оператор 'in'."""
        return self.has(key)
    
    def __delitem__(self, key: str) -> None:
        """Удалить ключ через оператор 'del'."""
        if not self.remove(key):
            raise KeyError(f"Config key not found: {key}")
    
    def __len__(self) -> int:
        """Количество ключей верхнего уровня."""
        with self._lock:
            return len(self._data)
    
    def __repr__(self) -> str:
        """Строковое представление конфигурации."""
        return f"Config(path={self._path}, keys={len(self._data)})"

