"""
Базовый класс конфигурации для проекта.

Универсальный, потокобезопасный класс для работы с конфигурацией.
Поддерживает вложенные ключи через точку, загрузку/сохранение JSON/YAML,
работу с секциями и переменными окружения.

Примеры использования:
    # Простая работа с конфигурацией
    config = Config()
    config.set('database.host', 'localhost')
    host = config.get('database.host')
    
    # Работа через синтаксис словаря
    config['database.port'] = 5432
    port = config['database.port']
    
    # Работа с секциями
    db_config = config.section('database')
    db_config.set('host', 'localhost')
    
    # Загрузка из файла
    config.load('config/app.yaml')
    config.save('config/app.yaml')
"""

from typing import Dict, Any, Optional, Union, Callable, List
from pathlib import Path
import json
import os
import copy
from threading import RLock

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class Config:
    """
    Универсальная конфигурация для всех модулей проекта.
    
    Особенности:
    - Вложенные ключи через точку: "database.host"
    - Потокобезопасность (thread-safe) через RLock
    - Загрузка/сохранение JSON/YAML файлов
    - Работа с секциями конфигурации
    - Поддержка переменных окружения (опционально)
    - Подписка на изменения конфигурации
    - Простой и понятный API
    
    Attributes:
        _data: Внутренний словарь с данными конфигурации
        _lock: Блокировка для потокобезопасности
        _path: Путь к файлу конфигурации (если загружено из файла)
        _env_prefix: Префикс для переменных окружения
        _change_callbacks: Словарь callback-функций для отслеживания изменений
    """
    
    def __init__(
        self, 
        initial_data: Optional[Dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None
    ):
        """
        Инициализация конфигурации.
        
        Args:
            initial_data: Начальные данные конфигурации (словарь)
            env_prefix: Префикс для переменных окружения (например, "APP")
            file_path: Путь к файлу конфигурации для автоматической загрузки
        
        Примеры:
            # Пустая конфигурация
            config = Config()
            
            # С начальными данными
            config = Config({'database': {'host': 'localhost'}})
            
            # С префиксом для переменных окружения
            config = Config(env_prefix='APP')
            # Будет искать APP_DATABASE_HOST в переменных окружения
            
            # С автоматической загрузкой из файла
            config = Config(file_path='config/app.yaml')
        """
        self._data: Dict[str, Any] = copy.deepcopy(initial_data) if initial_data else {}
        self._lock = RLock()
        self._path: Optional[Path] = None
        self._env_prefix: Optional[str] = env_prefix
        self._change_callbacks: Dict[str, List[Callable]] = {}
        
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
        
        Примеры:
            config.set('database.host', 'localhost')
            host = config.get('database.host')  # 'localhost'
            port = config.get('database.port', 5432)  # 5432 (если не задан)
            
            # Поиск в переменных окружения
            # Если APP_DATABASE_HOST установлена, вернет её значение
            host = config.get('database.host', env_fallback=True)
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
    
    def set(self, key: str, value: Any, notify: bool = True) -> 'Config':
        """
        Установить значение по ключу.
        
        Автоматически создает вложенную структуру если нужно.
        Отправляет уведомления подписчикам об изменении.
        
        Args:
            key: Ключ в формате 'section.subsection.key'
            value: Значение для установки
            notify: Отправлять уведомления об изменении
        
        Returns:
            self (для цепочки вызовов)
        
        Примеры:
            config.set('database.host', 'localhost')
            config.set('database.port', 5432)
            
            # Цепочка вызовов
            config.set('db.host', 'localhost').set('db.port', 5432)
        """
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
        
        Примеры:
            config.update({'host': 'localhost', 'port': 5432}, prefix='database')
            # Эквивалентно:
            # config.set('database.host', 'localhost')
            # config.set('database.port', 5432)
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
        """
        Проверить наличие ключа в конфигурации.
        
        Args:
            key: Ключ для проверки
        
        Returns:
            True если ключ существует, False в противном случае
        
        Примеры:
            config.set('database.host', 'localhost')
            config.has('database.host')  # True
            config.has('database.port')  # False
        """
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
        """
        Удалить ключ из конфигурации.
        
        Args:
            key: Ключ для удаления
        
        Returns:
            True если ключ был удален, False если ключ не найден
        
        Примеры:
            config.set('database.host', 'localhost')
            config.remove('database.host')  # True
            config.remove('database.port')  # False
        """
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
        """
        Очистить всю конфигурацию.
        
        Returns:
            self (для цепочки вызовов)
        
        Примеры:
            config.clear()  # Удаляет все данные
        """
        with self._lock:
            old_data = copy.deepcopy(self._data)
            self._data.clear()
            self._notify_change("*", old_data, {})
        
        return self
    
    # ===== РАБОТА С ФАЙЛАМИ =====
    
    def load(self, file_path: Union[str, Path], merge: bool = True) -> 'Config':
        """
        Загрузить конфигурацию из файла.
        
        Поддерживает форматы: JSON (.json), YAML (.yaml, .yml)
        Автоматически определяет формат по расширению файла.
        
        Args:
            file_path: Путь к файлу конфигурации
            merge: Если True, объединяет с существующими данными, иначе заменяет
        
        Returns:
            self (для цепочки вызовов)
        
        Raises:
            FileNotFoundError: Если файл не найден
            ImportError: Если требуется PyYAML но не установлен
        
        Примеры:
            # Загрузка с заменой существующих данных
            config.load('config/app.yaml', merge=False)
            
            # Загрузка с объединением
            config.load('config/app.yaml', merge=True)
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with self._lock:
            # Загружаем данные из файла используя универсальный метод
            data = Config.load_from_file(path)
            
            if merge:
                self._deep_update(self._data, data)
            else:
                self._data = data
            
            self._path = path  # Сохраняем путь для возможного сохранения
        
        return self
    
    def save(self, file_path: Optional[Union[str, Path]] = None) -> 'Config':
        """
        Сохранить конфигурацию в файл.
        
        Если путь не указан, использует путь из которого была загружена конфигурация.
        Автоматически создает директории если их нет.
        
        Args:
            file_path: Путь для сохранения (если None, использует путь загрузки)
        
        Returns:
            self (для цепочки вызовов)
        
        Raises:
            ValueError: Если путь не указан и конфигурация не была загружена из файла
            ImportError: Если требуется PyYAML но не установлен
        
        Примеры:
            # Сохранение в тот же файл
            config.load('config/app.yaml')
            config.save()
            
            # Сохранение в другой файл
            config.save('config/backup.yaml')
        """
        path = Path(file_path) if file_path else self._path
        
        if not path:
            raise ValueError("No file path specified for saving. Use load() first or provide file_path.")
        
        with self._lock:
            # Сохраняем данные используя универсальный метод
            Config.save_to_file(path, self._data)
        
        return self
    
    def reload(self) -> 'Config':
        """
        Перезагрузить конфигурацию из того же файла.
        
        Returns:
            self (для цепочки вызовов)
        
        Raises:
            ValueError: Если конфигурация не была загружена из файла
        
        Примеры:
            config.load('config/app.yaml')
            # ... изменения в файле ...
            config.reload()  # Загружает изменения из файла
        """
        if not self._path:
            raise ValueError("Config was not loaded from file. Use load() first.")
        
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        
        return self.load(self._path, merge=False)
    
    # ===== РАБОТА С СЕКЦИЯМИ =====
    
    def section(self, section_key: str) -> 'ConfigSection':
        """
        Получить доступ к секции конфигурации.
        
        Секция - это часть конфигурации, выделенная по определенному ключу.
        Позволяет работать с поддеревом конфигурации как с отдельным объектом.
        Все изменения в секции автоматически отражаются в основном конфиге.
        
        Args:
            section_key: Ключ секции (например, 'database')
        
        Returns:
            ConfigSection - объект для работы с секцией
        
        Примеры:
            # Получаем секцию database
            db_config = config.section('database')
            
            # Работаем с ней как с отдельным конфигом
            db_config.set('host', 'localhost')
            db_config.set('port', 5432)
            host = db_config.get('host')
            
            # Все изменения отражаются в основном конфиге!
            # config.get('database.host') также вернет 'localhost'
        """
        return ConfigSection(self, section_key)
    
    # ===== ПОДПИСКА НА ИЗМЕНЕНИЯ =====
    
    def subscribe(self, callback: Optional[Callable] = None, key: str = "*") -> Union[None, Callable]:
        """
        Подписаться на изменения конфигурации.
        
        Основной метод для подписки на изменения. Можно подписаться на все изменения
        или на конкретный ключ. Можно использовать как декоратор или вызывать напрямую.
        
        Args:
            callback: Функция обратного вызова (key, old_value, new_value) или None для использования как декоратор
            key: Ключ для отслеживания или "*" для всех изменений (по умолчанию "*")
        
        Returns:
            Декоратор если callback не указан, иначе None
        
        Примеры:
            # Подписка на все изменения (прямой вызов)
            def on_config_change(key, old_value, new_value):
                print(f"Config changed: {key}")
            
            config.subscribe(on_config_change)
            
            # Подписка на конкретный ключ
            def on_db_host_change(key, old_value, new_value):
                print(f"Database host changed: {old_value} -> {new_value}")
            
            config.subscribe(on_db_host_change, key='database.host')
            
            # Использование как декоратор
            @config.subscribe(key='database.host')
            def on_db_host_change(key, old_value, new_value):
                print(f"Database host changed: {old_value} -> {new_value}")
        """
        if callback:
            with self._lock:
                if key not in self._change_callbacks:
                    self._change_callbacks[key] = []
                self._change_callbacks[key].append(callback)
            return None
        else:
            def decorator(func):
                self.subscribe(func, key)
                return func
            return decorator
    
    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        Уведомить подписчиков об изменении конфигурации.
        
        Args:
            key: Измененный ключ
            old_value: Старое значение
            new_value: Новое значение
        """
        callbacks = []
        
        # Собираем все релевантные callback'и
        if key in self._change_callbacks:
            callbacks.extend(self._change_callbacks[key])
        
        if "*" in self._change_callbacks:
            callbacks.extend(self._change_callbacks["*"])
        
        # Вызываем callback'и
        for callback in callbacks:
            try:
                callback(key, old_value, new_value)
            except Exception as e:
                # Логируем ошибку но не прерываем выполнение
                print(f"Error in config change callback for key '{key}': {e}")
    
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
        """
        Получить значение из переменных окружения.
        
        Args:
            key: Ключ конфигурации
        
        Returns:
            Значение из переменных окружения или None
        """
        if not self._env_prefix:
            return None
        
        # Преобразуем ключ в формат переменной окружения
        # database.host -> APP_DATABASE_HOST
        env_key = f"{self._env_prefix}_{key.upper().replace('.', '_')}"
        env_value = os.getenv(env_key)
        
        if env_value is None:
            return None
        
        # Пытаемся определить тип значения
        return self._cast_env_value(env_value)
    
    def _cast_env_value(self, value: str) -> Any:
        """
        Привести значение из переменной окружения к нужному типу.
        
        Args:
            value: Строковое значение из переменной окружения
        
        Returns:
            Значение приведенное к нужному типу
        """
        # Булевы значения
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        # Целые числа
        if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
            return int(value)
        
        # Вещественные числа
        try:
            if value.replace('.', '', 1).replace('-', '', 1).isdigit():
                return float(value)
        except ValueError:
            pass
        
        # Строка (по умолчанию)
        return value
    
    def _deep_update(self, target: Dict, source: Dict) -> None:
        """
        Рекурсивное обновление словаря.
        
        Обновляет вложенные словари, сохраняя существующие ключи.
        
        Args:
            target: Целевой словарь (изменяется)
            source: Источник данных для обновления
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    @staticmethod
    def load_from_file(
        file_path: Union[str, Path],
        format: Optional[str] = None,
        output_format: str = 'dict'
    ) -> Union[Dict[str, Any], str]:
        """
        Универсальный метод загрузки файла конфигурации.
        
        Автоматически определяет формат по расширению, если не указан явно.
        Может возвращать данные в виде словаря или строки.
        
        Args:
            file_path: Путь к файлу конфигурации
            format: Формат файла ('json', 'yaml', 'yml') или None для автоопределения
            output_format: Формат вывода:
                - 'dict': Словарь Python (по умолчанию)
                - 'yaml': YAML строка
                - 'json': JSON строка
        
        Returns:
            Данные конфигурации в указанном формате (словарь или строка)
            
        Raises:
            FileNotFoundError: Если файл не найден
            ImportError: Если требуется PyYAML но не установлен
            ValueError: Если указан неверный формат
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {path}")
        
        # Определяем формат файла используя универсальный метод
        if format is None:
            format = Config.detect_file_format(path, check_content=True)
        
        # Загружаем данные из файла как словарь
        with open(path, 'r', encoding='utf-8') as f:
            if format == 'json':
                data = json.load(f) or {}
            elif format in ['yaml', 'yml']:
                if not YAML_AVAILABLE:
                    raise ImportError(
                        "PyYAML is required for YAML files. "
                        "Install with: pip install PyYAML"
                    )
                data = yaml.safe_load(f) or {}
            else:
                raise ValueError(f"Неверный формат: {format}. Поддерживаются: 'json', 'yaml'")
        
        # Конвертируем в нужный формат вывода используя универсальный метод
        return Config.convert_format(data, output_format)
    
    @staticmethod
    def save_to_file(
        file_path: Union[str, Path],
        data: Union[Dict[str, Any], str],
        format: Optional[str] = None,
        input_format: Optional[str] = None
    ) -> None:
        """
        Универсальный метод сохранения данных в файл.
        
        Может принимать данные как словарь или строку (yaml/json).
        Автоматически определяет формат по расширению, если не указан явно.
        
        Args:
            file_path: Путь к файлу для сохранения
            data: Данные для сохранения (словарь или строка yaml/json)
            format: Формат файла для сохранения ('json', 'yaml', 'yml') или None для автоопределения
            input_format: Формат входных данных ('dict', 'json', 'yaml') или None для автоопределения
                Если data - строка, будет попытка определить формат автоматически
        
        Raises:
            ImportError: Если требуется PyYAML но не установлен
            ValueError: Если указан неверный формат или не удалось определить формат входных данных
        """
        path = Path(file_path)
        
        # Создаем директорию если не существует
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Определяем формат файла для сохранения используя универсальный метод
        if format is None:
            format = Config.detect_file_format(path, check_content=False)
        
        # Определяем формат входных данных используя универсальный метод
        if input_format is None:
            input_format = Config.detect_data_format(data)
        
        # Если данные уже в виде строки нужного формата, записываем напрямую
        if input_format == format and isinstance(data, str):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(data)
            return
        
        # Конвертируем данные в нужный формат используя универсальный метод
        if input_format == 'dict':
            # Если входные данные - словарь, конвертируем в строку нужного формата
            content = Config.convert_format(data, format)
        else:
            # Если входные данные - строка другого формата, сначала парсим в словарь
            if input_format == 'json':
                data_dict = json.loads(data)
            elif input_format == 'yaml':
                if not YAML_AVAILABLE:
                    raise ImportError(
                        "PyYAML is required for YAML parsing. "
                        "Install with: pip install PyYAML"
                    )
                data_dict = yaml.safe_load(data) or {}
            else:
                raise ValueError(f"Неверный формат входных данных: {input_format}")
            
            # Затем конвертируем в нужный формат вывода
            content = Config.convert_format(data_dict, format)
        
        # Записываем в файл
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    @staticmethod
    def detect_file_format(
        file_path: Union[str, Path],
        check_content: bool = True
    ) -> str:
        """
        Определить формат файла по расширению или содержимому.
        
        Args:
            file_path: Путь к файлу
            check_content: Если True и расширение не определено, проверяет содержимое файла
        
        Returns:
            Формат файла: 'json', 'yaml' или 'yml'
        """
        path = Path(file_path)
        
        # Определяем по расширению
        if path.suffix == '.json':
            return 'json'
        elif path.suffix in ['.yaml', '.yml']:
            return 'yaml'
        
        # Если расширение не определено и нужно проверить содержимое
        if check_content and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content.startswith('{') or content.startswith('['):
                        return 'json'
                    else:
                        return 'yaml'
            except Exception:
                pass
        
        # По умолчанию YAML
        return 'yaml'
    
    @staticmethod
    def detect_data_format(
        data: Union[Dict[str, Any], str]
    ) -> str:
        """
        Определить формат данных.
        
        Args:
            data: Данные для проверки (словарь или строка)
        
        Returns:
            Формат данных: 'dict', 'json' или 'yaml'
        
        Raises:
            ValueError: Если тип данных не поддерживается
        """
        if isinstance(data, dict):
            return 'dict'
        elif isinstance(data, str):
            # Пробуем определить формат строки по содержимому
            data_stripped = data.strip()
            if data_stripped.startswith('{') or data_stripped.startswith('['):
                return 'json'
            else:
                return 'yaml'
        else:
            raise ValueError(
                f"Неверный тип данных: {type(data)}. "
                f"Ожидается dict или str (yaml/json)"
            )
    
    @staticmethod
    def convert_format(
        data: Dict[str, Any],
        output_format: str = 'dict'
    ) -> Union[Dict[str, Any], str]:
        """
        Конвертировать данные конфигурации в указанный формат.
        
        Args:
            data: Данные конфигурации (словарь)
            output_format: Формат вывода:
                - 'dict': Словарь Python (по умолчанию)
                - 'yaml': YAML строка
                - 'json': JSON строка
        
        Returns:
            Данные в указанном формате
            
        Raises:
            ImportError: Если требуется PyYAML но не установлен
            ValueError: Если указан неверный формат вывода
        """
        if output_format == 'dict':
            return data
        elif output_format == 'yaml':
            if not YAML_AVAILABLE:
                raise ImportError(
                    "PyYAML is required for YAML output. "
                    "Install with: pip install PyYAML"
                )
            return yaml.dump(data, default_flow_style=False, allow_unicode=True, indent=2)
        elif output_format == 'json':
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            raise ValueError(
                f"Неверный формат вывода: {output_format}. "
                f"Поддерживаются: 'dict', 'yaml', 'json'"
            )
    
    # ===== СВОЙСТВА И МАГИЧЕСКИЕ МЕТОДЫ =====
    
    @property
    def data(self) -> Dict[str, Any]:
        """
        Получить копию всех данных конфигурации.
        
        Returns:
            Глубокая копия всех данных конфигурации
        
        Примеры:
            all_data = config.data
            # Изменения в all_data не повлияют на config
        """
        with self._lock:
            return copy.deepcopy(self._data)
    
    @property
    def file_path(self) -> Optional[Path]:
        """
        Получить путь к файлу конфигурации.
        
        Returns:
            Путь к файлу или None если конфигурация не была загружена из файла
        """
        return self._path
    
    def __getitem__(self, key: str) -> Any:
        """
        Поддержка синтаксиса config['key'].
        
        Args:
            key: Ключ конфигурации
        
        Returns:
            Значение конфигурации
        
        Raises:
            KeyError: Если ключ не найден
        """
        value = self.get(key)
        if value is None and not self.has(key):
            raise KeyError(f"Config key '{key}' not found")
        return value
    
    def __setitem__(self, key: str, value: Any) -> None:
        """
        Поддержка синтаксиса config['key'] = value.
        
        Args:
            key: Ключ конфигурации
            value: Значение для установки
        """
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """
        Поддержка синтаксиса 'key' in config.
        
        Args:
            key: Ключ для проверки
        
        Returns:
            True если ключ существует
        """
        return self.has(key)
    
    def __delitem__(self, key: str) -> None:
        """
        Поддержка синтаксиса del config['key'].
        
        Args:
            key: Ключ для удаления
        
        Raises:
            KeyError: Если ключ не найден
        """
        if not self.remove(key):
            raise KeyError(f"Config key '{key}' not found")
    
    def __repr__(self) -> str:
        """
        Строковое представление конфигурации.
        
        Returns:
            Строка с информацией о конфигурации
        """
        keys_count = len(self._data)
        file_info = f", file={self._path}" if self._path else ""
        return f"Config(keys={keys_count}{file_info})"
    
    def __len__(self) -> int:
        """
        Количество ключей верхнего уровня в конфигурации.
        
        Returns:
            Количество ключей
        """
        return len(self._data)


class ConfigSection:
    """
    Представление секции конфигурации.
    
    Позволяет работать с частью конфигурации как с отдельным объектом,
    при этом все изменения автоматически синхронизируются с родительским конфигом.
    
    Attributes:
        _parent: Родительский объект Config
        _key: Ключ секции
    """
    
    def __init__(self, parent_config: Config, section_key: str):
        """
        Инициализация секции конфигурации.
        
        Args:
            parent_config: Родительский объект Config
            section_key: Ключ секции (например, 'database')
        """
        self._parent = parent_config
        self._key = section_key
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получить значение из секции.
        
        Args:
            key: Ключ внутри секции
            default: Значение по умолчанию
        
        Returns:
            Значение из секции или default
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.get(full_key, default)
    
    def set(self, key: str, value: Any) -> 'ConfigSection':
        """
        Установить значение в секции.
        
        Args:
            key: Ключ внутри секции
            value: Значение для установки
        
        Returns:
            self (для цепочки вызовов)
        """
        full_key = f"{self._key}.{key}" if key else self._key
        self._parent.set(full_key, value)
        return self
    
    def update(self, data: Dict[str, Any]) -> 'ConfigSection':
        """
        Обновить секцию из словаря.
        
        Args:
            data: Словарь с новыми значениями
        
        Returns:
            self (для цепочки вызовов)
        """
        for key, value in data.items():
            self.set(key, value)
        return self
    
    def has(self, key: str) -> bool:
        """
        Проверить наличие ключа в секции.
        
        Args:
            key: Ключ для проверки
        
        Returns:
            True если ключ существует
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.has(full_key)
    
    def remove(self, key: str) -> bool:
        """
        Удалить ключ из секции.
        
        Args:
            key: Ключ для удаления
        
        Returns:
            True если ключ был удален
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.remove(full_key)
    
    @property
    def data(self) -> Dict[str, Any]:
        """
        Получить все данные секции как словарь.
        
        Returns:
            Словарь с данными секции
        """
        return self._parent.get(self._key, {}) or {}
    
    # Магические методы для удобства
    def __getitem__(self, key: str) -> Any:
        """Поддержка синтаксиса section['key']"""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Поддержка синтаксиса section['key'] = value"""
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """Поддержка синтаксиса 'key' in section"""
        return self.has(key)
    
    def __delitem__(self, key: str) -> None:
        """Поддержка синтаксиса del section['key']"""
        if not self.remove(key):
            raise KeyError(f"Section key '{key}' not found")
    
    def __repr__(self) -> str:
        """Строковое представление секции"""
        return f"ConfigSection(parent={self._parent}, key='{self._key}', data={self.data})"
