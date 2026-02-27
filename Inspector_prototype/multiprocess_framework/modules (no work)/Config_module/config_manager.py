"""
Менеджер конфигураций для управления несколькими экземплярами конфигураций.

Предоставляет централизованное управление несколькими конфигурациями,
Singleton паттерн для глобального доступа и удобные методы для работы
с именованными конфигурациями.

Поддерживает:
- Дефолтные и временные конфиги
- Автоматическое определение класса конфига из метаданных
- Загрузку конфигов из разных путей
- Сброс к дефолтным значениям

Примеры использования:
    # Получение глобального экземпляра (Singleton)
    config = ConfigManager.get_instance()
    config.set('database.host', 'localhost')
    
    # Создание именованной конфигурации
    app_config = ConfigManager.get_instance('app')
    app_config.load('config/app.yaml')
    
    # Работа с несколькими конфигурациями
    db_config = ConfigManager.get_instance('database')
    api_config = ConfigManager.get_instance('api')
    
    # Загрузка всех конфигов проекта
    manager = ConfigManager()
    manager.load_all_configs(config_dir='config')
"""

from typing import Dict, Optional, Union, Type, Any
from pathlib import Path
from threading import RLock
import importlib
import shutil

from .base_config import Config


class ConfigManager:
    """
    Менеджер для управления несколькими экземплярами конфигураций.
    
    Может работать в двух режимах:
    1. Класс-методы (Singleton) - для глобального доступа к именованным конфигурациям
    2. Экземпляр (композиция) - для хранения всех конфигураций проекта в одном объекте
    
    Особенности:
    - Singleton паттерн для глобального доступа через класс-методы
    - Композиция конфигураций через экземпляр
    - Автоматическое создание конфигураций при первом обращении
    - Поддержка дефолтных и временных конфигов
    - Автоматическое определение класса конфига из метаданных
    - Валидация через указанный класс конфига
    - Потокобезопасность
    
    Attributes:
        _instances: Словарь именованных экземпляров конфигураций (для класс-методов)
        _lock: Блокировка для потокобезопасности
        _default_paths: Словарь путей к дефолтным конфигам {name: path}
        _temp_paths: Словарь путей к временным конфигам {name: path}
        
        # Для экземпляра:
        configs: Словарь всех конфигураций проекта {name: Config}
        processes_config: Конфигурация процессов (специальная)
    """
    
    _instances: Dict[str, Config] = {}
    _lock = RLock()
    _default_paths: Dict[str, Path] = {}
    _temp_paths: Dict[str, Path] = {}
    
    def __init__(self):
        """
        Инициализация ConfigManager как композиции конфигураций.
        
        Создает экземпляр для хранения всех конфигураций проекта.
        """
        # Хранилище всех конфигураций проекта
        self.configs: Dict[str, Config] = {}
        
        # Конфигурация процессов (специальная, может использовать ProcessConfig)
        self.processes_config: Optional[Config] = None
    
    @classmethod
    def get_instance(
        cls, 
        name: str = "default",
        env_prefix: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None
    ) -> Config:
        """
        Получить или создать экземпляр конфигурации (Singleton).
        
        Если конфигурация с указанным именем не существует, создается новый экземпляр.
        Если существует, возвращается существующий экземпляр.
        
        Args:
            name: Уникальное имя конфигурации (по умолчанию "default")
            env_prefix: Префикс для переменных окружения
            file_path: Путь к файлу конфигурации для автоматической загрузки
        
        Returns:
            Экземпляр Config с указанным именем
        
        Примеры:
            # Получение дефолтной конфигурации
            config = ConfigManager.get_instance()
            
            # Получение именованной конфигурации
            app_config = ConfigManager.get_instance('app')
            
            # С автоматической загрузкой из файла
            config = ConfigManager.get_instance('app', file_path='config/app.yaml')
            
            # С префиксом для переменных окружения
            config = ConfigManager.get_instance('app', env_prefix='APP')
        """
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = Config(
                    env_prefix=env_prefix,
                    file_path=file_path
                )
            return cls._instances[name]
    
    @classmethod
    def create_instance(
        cls,
        name: str,
        env_prefix: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None,
        initial_data: Optional[Dict] = None
    ) -> Config:
        """
        Создать новый экземпляр конфигурации.
        
        Если конфигурация с таким именем уже существует, она будет заменена.
        
        Args:
            name: Уникальное имя конфигурации
            env_prefix: Префикс для переменных окружения
            file_path: Путь к файлу конфигурации для автоматической загрузки
            initial_data: Начальные данные конфигурации
        
        Returns:
            Новый экземпляр Config
        
        Примеры:
            # Создание новой конфигурации
            config = ConfigManager.create_instance('new_config')
            
            # С начальными данными
            config = ConfigManager.create_instance(
                'app',
                initial_data={'database': {'host': 'localhost'}}
            )
        """
        with cls._lock:
            cls._instances[name] = Config(
                initial_data=initial_data,
                env_prefix=env_prefix,
                file_path=file_path
            )
            return cls._instances[name]
    
    @classmethod
    def remove_instance(cls, name: str) -> bool:
        """
        Удалить экземпляр конфигурации.
        
        Args:
            name: Имя конфигурации для удаления
        
        Returns:
            True если конфигурация была удалена, False если не найдена
        
        Примеры:
            ConfigManager.remove_instance('old_config')
        """
        with cls._lock:
            if name in cls._instances:
                del cls._instances[name]
                return True
            return False
    
    @classmethod
    def clear_all(cls) -> None:
        """
        Очистить все экземпляры конфигураций.
        
        Примеры:
            ConfigManager.clear_all()  # Удаляет все конфигурации
        """
        with cls._lock:
            cls._instances.clear()
    
    @classmethod
    def has_instance(cls, name: str) -> bool:
        """
        Проверить существование экземпляра конфигурации.
        
        Args:
            name: Имя конфигурации
        
        Returns:
            True если конфигурация существует
        
        Примеры:
            if ConfigManager.has_instance('app'):
                config = ConfigManager.get_instance('app')
        """
        with cls._lock:
            return name in cls._instances
    
    @classmethod
    def list_instances(cls) -> list:
        """
        Получить список всех именованных конфигураций.
        
        Returns:
            Список имен конфигураций
        
        Примеры:
            names = ConfigManager.list_instances()
            # ['default', 'app', 'database']
        """
        with cls._lock:
            return list(cls._instances.keys())
    
    @classmethod
    def get_all_instances(cls) -> Dict[str, Config]:
        """
        Получить словарь всех экземпляров конфигураций.
        
        Returns:
            Словарь {имя: экземпляр Config}
        
        Примеры:
            all_configs = ConfigManager.get_all_instances()
            for name, config in all_configs.items():
                print(f"{name}: {config}")
        """
        with cls._lock:
            return cls._instances.copy()
    
    @classmethod
    def load_config(
        cls,
        name: str,
        default_path: Optional[Union[str, Path]] = None,
        temp_path: Optional[Union[str, Path]] = None,
        config_class: Optional[Union[str, Type]] = None,
        env_prefix: Optional[str] = None
    ) -> Config:
        """
        Загрузить конфигурацию с поддержкой дефолтных и временных файлов.
        
        Приоритет загрузки:
        1. Временный файл (если существует)
        2. Дефолтный файл (если существует)
        3. Пустая конфигурация
        
        Если класс конфига не указан явно, автоматически определяется из метаданных файла
        (поле '_meta.config_class' или 'config_class' в корне).
        
        Args:
            name: Имя конфигурации
            default_path: Путь к дефолтному файлу конфигурации
            temp_path: Путь к временному файлу конфигурации
            config_class: Класс конфига (строка вида 'module.Class' или класс).
                         Если не указан, будет попытка определить из метаданных файла.
            env_prefix: Префикс для переменных окружения
            
        Returns:
            Экземпляр Config (или указанного класса)
            
        Примеры:
            # Загрузка с дефолтным и временным файлом
            config = ConfigManager.load_config(
                'processes',
                default_path='config/processes.yaml',
                temp_path='config/temp/processes.yaml'
            )
            
            # С указанием класса конфига
            config = ConfigManager.load_config(
                'processes',
                default_path='config/processes.yaml',
                config_class='src.Modules.Process_manager_module.process_config.ProcessConfig'
            )
            
            # Автоматическое определение класса из метаданных файла
            # (если в файле есть _meta.config_class или config_class)
            config = ConfigManager.load_config(
                'processes',
                default_path='config/processes.yaml'
            )
        """
        with cls._lock:
            # Сохраняем пути
            if default_path:
                cls._default_paths[name] = Path(default_path)
            if temp_path:
                cls._temp_paths[name] = Path(temp_path)
            
            # Определяем файл для загрузки (приоритет: temp > default)
            temp_file = cls._temp_paths.get(name)
            default_file = cls._default_paths.get(name)
            
            file_to_load = None
            if temp_file and temp_file.exists():
                file_to_load = temp_file
            elif default_file and default_file.exists():
                file_to_load = default_file
            
            # Если класс не указан явно, пытаемся определить из метаданных файла
            if not config_class and file_to_load:
                config_class = cls._detect_config_class(file_to_load)
            
            # Определяем класс конфига и создаем экземпляр
            config_instance = cls._create_config_instance(name, config_class, env_prefix)
            
            # Загружаем конфиг
            if file_to_load:
                config_instance.load(file_to_load, merge=False)
            
            cls._instances[name] = config_instance
            return config_instance
    
    @classmethod
    def _create_config_instance(
        cls,
        name: str,
        config_class: Optional[Union[str, Type]] = None,
        env_prefix: Optional[str] = None
    ) -> Config:
        """
        Создать экземпляр конфига с учетом указанного класса.
        
        Если класс не указан, использует базовый Config.
        Определение класса из метаданных должно происходить в вызывающем методе
        (например, в load_config) до вызова этого метода.
        
        Args:
            name: Имя конфигурации (используется для логирования, если нужно)
            config_class: Класс конфига (строка или класс)
            env_prefix: Префикс для переменных окружения
            
        Returns:
            Экземпляр конфига
        """
        # Если класс указан явно
        if config_class:
            if isinstance(config_class, str):
                # Импортируем класс из строки
                try:
                    module_path, class_name = config_class.rsplit('.', 1)
                    module = importlib.import_module(module_path)
                    config_class = getattr(module, class_name)
                except (ImportError, AttributeError, ValueError) as e:
                    # Если не удалось загрузить класс, используем базовый Config
                    print(f"⚠️ Warning: Could not load config class '{config_class}': {e}. Using base Config.")
                    return Config(env_prefix=env_prefix)
            
            if issubclass(config_class, Config):
                return config_class(env_prefix=env_prefix)
            else:
                print(f"⚠️ Warning: '{config_class}' is not a subclass of Config. Using base Config.")
                return Config(env_prefix=env_prefix)
        
        # Используем базовый Config
        return Config(env_prefix=env_prefix)
    
    @classmethod
    def load_all_configs(
        cls,
        config_dir: Union[str, Path] = "config",
        temp_dir: Optional[Union[str, Path]] = None,
        config_mapping: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Config]:
        """
        Загрузить все конфиги из указанной директории.
        
        Args:
            config_dir: Директория с дефолтными конфигами
            temp_dir: Директория с временными конфигами (опционально)
            config_mapping: Маппинг конфигов {name: {default_path, temp_path, config_class}}
            
        Returns:
            Словарь загруженных конфигов
            
        Примеры:
            # Автоматическая загрузка всех конфигов
            configs = ConfigManager.load_all_configs('config')
            
            # С указанием маппинга
            configs = ConfigManager.load_all_configs(
                config_dir='config',
                temp_dir='config/temp',
                config_mapping={
                    'processes': {
                        'default_path': 'config/processes.yaml',
                        'config_class': 'ProcessConfig'
                    }
                }
            )
        """
        config_dir = Path(config_dir)
        temp_dir = Path(temp_dir) if temp_dir else None
        
        loaded_configs = {}
        
        # Если указан маппинг, используем его
        if config_mapping:
            for name, mapping in config_mapping.items():
                config = cls.load_config(
                    name=name,
                    default_path=mapping.get('default_path'),
                    temp_path=mapping.get('temp_path'),
                    config_class=mapping.get('config_class'),
                    env_prefix=mapping.get('env_prefix')
                )
                loaded_configs[name] = config
        else:
            # Автоматически находим все конфиги в директории
            if config_dir.exists():
                for config_file in config_dir.glob('*.yaml'):
                    name = config_file.stem
                    temp_file = temp_dir / config_file.name if temp_dir else None
                    
                    # Пытаемся определить класс из метаданных файла
                    config_class = cls._detect_config_class(config_file)
                    
                    config = cls.load_config(
                        name=name,
                        default_path=config_file,
                        temp_path=temp_file if temp_file and temp_file.exists() else None,
                        config_class=config_class
                    )
                    loaded_configs[name] = config
                
                # Также проверяем JSON файлы
                for config_file in config_dir.glob('*.json'):
                    name = config_file.stem
                    temp_file = temp_dir / config_file.name if temp_dir else None
                    
                    config_class = cls._detect_config_class(config_file)
                    
                    config = cls.load_config(
                        name=name,
                        default_path=config_file,
                        temp_path=temp_file if temp_file and temp_file.exists() else None,
                        config_class=config_class
                    )
                    loaded_configs[name] = config
        
        return loaded_configs
    
    @classmethod
    def _detect_config_class(cls, config_file: Path) -> Optional[str]:
        """
        Определить класс конфига из метаданных файла.
        
        Ищет в файле поле '_meta.config_class' или 'config_class'.
        
        Args:
            config_file: Путь к файлу конфигурации
            
        Returns:
            Строка с путем к классу или None
        """
        try:
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.suffix in ['.yaml', '.yml']:
                    data = yaml.safe_load(f) or {}
                else:
                    import json
                    data = json.load(f) or {}
            
            # Ищем в метаданных
            meta = data.get('_meta', {})
            config_class = meta.get('config_class') or data.get('config_class')
            
            return config_class
        except Exception:
            return None
    
    @classmethod
    def reset_to_default(cls, name: str) -> bool:
        """
        Сбросить конфигурацию к дефолтным значениям.
        
        Копирует дефолтный файл во временный (если существует) или перезагружает дефолтный.
        
        Args:
            name: Имя конфигурации
            
        Returns:
            True если сброс выполнен успешно
            
        Примеры:
            ConfigManager.reset_to_default('processes')
        """
        with cls._lock:
            if name not in cls._instances:
                return False
            
            default_path = cls._default_paths.get(name)
            temp_path = cls._temp_paths.get(name)
            config = cls._instances[name]
            
            if not default_path or not default_path.exists():
                return False
            
            # Если есть временный файл, копируем дефолтный в него
            if temp_path:
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(default_path, temp_path)
                config.load(temp_path, merge=False)
            else:
                # Просто перезагружаем дефолтный
                config.load(default_path, merge=False)
            
            return True
    
    @classmethod
    def save_temp(cls, name: str) -> bool:
        """
        Сохранить конфигурацию во временный файл.
        
        Args:
            name: Имя конфигурации
            
        Returns:
            True если сохранение выполнено успешно
        """
        with cls._lock:
            if name not in cls._instances:
                return False
            
            temp_path = cls._temp_paths.get(name)
            if not temp_path:
                return False
            
            config = cls._instances[name]
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            config.save(temp_path)
            return True
    
    @classmethod
    def get_default_path(cls, name: str) -> Optional[Path]:
        """Получить путь к дефолтному файлу конфигурации."""
        return cls._default_paths.get(name)
    
    @classmethod
    def get_temp_path(cls, name: str) -> Optional[Path]:
        """Получить путь к временному файлу конфигурации."""
        return cls._temp_paths.get(name)
    
    @classmethod
    def load_file_as_dict(
        cls,
        file_path: Union[str, Path],
        output_format: str = 'dict'
    ) -> Union[Dict[str, Any], str]:
        """
        Загрузить файл конфигурации и вернуть данные в указанном формате.
        
        Использует универсальные методы из Config для загрузки и конвертации.
        Автоматически определяет тип файла по расширению (.yaml, .yml, .json).
        
        Args:
            file_path: Путь к файлу конфигурации
            output_format: Формат вывода:
                - 'dict': Словарь Python (по умолчанию)
                - 'yaml': YAML строка
                - 'json': JSON строка
        
        Returns:
            Данные конфигурации в указанном формате
            
        Raises:
            FileNotFoundError: Если файл не найден
            ValueError: Если указан неверный формат вывода
            
        Примеры:
            # Загрузка как словарь
            data = ConfigManager.load_file_as_dict('config/processes.yaml')
            
            # Загрузка как YAML строка
            yaml_str = ConfigManager.load_file_as_dict('config/processes.yaml', 'yaml')
            
            # Загрузка как JSON строка
            json_str = ConfigManager.load_file_as_dict('config/processes.json', 'json')
        """
        # Используем универсальный метод загрузки из Config
        data = Config.load_from_file(file_path)
        
        # Конвертируем в нужный формат используя универсальный метод
        return Config.convert_format(data, output_format)
    
    # ========================================================================
    # МЕТОДЫ ЭКЗЕМПЛЯРА (КОМПОЗИЦИЯ КОНФИГУРАЦИЙ)
    # ========================================================================
    
    def load_process_config(
        self,
        config_source: Optional[Union[str, Path, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Загружает и валидирует конфигурацию процессов.
        
        Автоматически определяет класс валидации из конфига:
        - Приоритет 1: class_config_validation для конкретного процесса
        - Приоритет 2: _meta.class_config_validation (общий для всех процессов)
        - Приоритет 3: Базовый Config (если класс не указан)
        
        Args:
            config_source: Источник конфигурации:
                - str/Path: Путь к файлу конфигурации
                - dict: Словарь конфигурации
                - None: Возвращает пустой словарь
        
        Returns:
            Валидированный словарь конфигурации процессов
            
        Example:
            # В YAML файле:
            _meta:
              class_config_validation: src.Modules.Process_module.process_config.ProcessConfig
            
            processes:
              VisionProcess:
                class_config_validation: src.Modules.Process_module.process_config.ProcessConfig
                class: src.Modules.Vision_module.VisionProcess
                # ...
        """
        # Загружаем сырые данные
        if config_source is None:
            return {}
        
        if isinstance(config_source, dict):
            raw_data = config_source
        elif isinstance(config_source, (str, Path)):
            raw_data = self.load_file_as_dict(config_source, 'dict')
        else:
            raise ValueError(f"Неверный тип config_source: {type(config_source)}")
        
        # Извлекаем секцию processes если есть
        if isinstance(raw_data, dict) and 'processes' in raw_data:
            processes_data = raw_data['processes']
            meta = raw_data.get('_meta', {})
        else:
            processes_data = raw_data
            meta = {}
        
        # Определяем общий класс валидации из метаданных
        # Используем class_config_validation вместо config_class
        default_config_class_path = meta.get('class_config_validation') or raw_data.get('class_config_validation')
        default_config_class = None
        if default_config_class_path:
            default_config_class = self._load_config_class_from_string(default_config_class_path)
        
        # Валидируем через указанный класс или базовый Config
        validated_config = {}
        
        for process_name, process_config in processes_data.items():
            if not isinstance(process_config, dict):
                continue
            
            # Определяем класс валидации для конкретного процесса
            # Приоритет: class_config_validation процесса > общий class_config_validation > базовый Config
            process_config_class_path = process_config.get('class_config_validation')
            
            if process_config_class_path:
                # Используем класс валидации указанный для процесса
                process_config_class = self._load_config_class_from_string(process_config_class_path)
                if process_config_class:
                    temp_config = process_config_class()
                else:
                    # Если не удалось загрузить класс, используем базовый Config
                    temp_config = Config()
            elif default_config_class:
                # Используем общий класс валидации из метаданных
                temp_config = default_config_class()
            else:
                # Используем базовый Config
                temp_config = Config()
            
            # Валидируем конфигурацию через выбранный класс
            # Используем load_from_dict если есть (для ProcessConfig с валидацией), иначе update
            if hasattr(temp_config, 'load_from_dict'):
                temp_config.load_from_dict({process_name: process_config})
            else:
                temp_config.update({process_name: process_config})
            
            # Получаем валидированную конфигурацию
            validated_config[process_name] = temp_config.get(process_name, process_config)
        
        return validated_config
    
    def update_process_config(self, config: Dict[str, Any]):
        """
        Обновляет конфигурацию процессов.
        
        Сохраняет валидированную конфигурацию в processes_config.
        
        Args:
            config: Валидированный словарь конфигурации процессов
        """
        if self.processes_config is None:
            self.processes_config = Config()
        
        # Используем load_from_dict если есть (для ProcessConfig с валидацией), иначе update
        if hasattr(self.processes_config, 'load_from_dict'):
            self.processes_config.load_from_dict(config)
        else:
            self.processes_config.update(config)
    
    def get_process_config(self) -> Dict[str, Any]:
        """
        Получает конфигурацию процессов.
        
        Returns:
            Словарь конфигурации процессов или пустой словарь
        """
        if self.processes_config is None:
            return {}
        
        # Используем свойство data для получения копии данных
        try:
            return self.processes_config.data
        except AttributeError:
            # Если свойство data недоступно, возвращаем пустой словарь
            return {}
    
    def get_all_configs(self) -> Dict[str, Config]:
        """
        Получает все конфигурации проекта.
        
        Returns:
            Словарь всех конфигураций {name: Config}
        """
        return self.configs.copy()
    
    def add_config(self, name: str, config: Config):
        """
        Добавляет конфигурацию в менеджер.
        
        Args:
            name: Имя конфигурации
            config: Экземпляр Config
        """
        self.configs[name] = config
    
    def get_config(self, name: str) -> Optional[Config]:
        """
        Получает конфигурацию по имени.
        
        Args:
            name: Имя конфигурации
            
        Returns:
            Экземпляр Config или None
        """
        return self.configs.get(name)
    
    def _load_config_class_from_string(self, class_path: str) -> Optional[Type[Config]]:
        """
        Загружает класс конфигурации из строки пути.
        
        Args:
            class_path: Путь к классу в формате 'module.path.ClassName'
            
        Returns:
            Класс конфигурации или None
        """
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            config_class = getattr(module, class_name)
            
            # Проверяем что это подкласс Config
            if issubclass(config_class, Config):
                return config_class
            else:
                print(f"⚠️ Warning: '{class_path}' is not a subclass of Config. Using base Config.")
                return None
        except (ImportError, AttributeError, ValueError) as e:
            print(f"⚠️ Warning: Could not load config class '{class_path}': {e}")
            return None
    
    @staticmethod
    def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рекурсивно объединяет два словаря.
        
        Утилита для глубокого слияния конфигураций. Используется при обновлении
        конфигураций процессов, когда нужно переопределить только часть настроек.
        
        Args:
            base: Базовый словарь
            override: Словарь с переопределениями
        
        Returns:
            Объединенный словарь
        
        Example:
            base = {'a': 1, 'b': {'x': 10, 'y': 20}}
            override = {'b': {'x': 15}, 'c': 30}
            result = ConfigManager.deep_merge(base, override)
            # result = {'a': 1, 'b': {'x': 15, 'y': 20}, 'c': 30}
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager.deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def save_worker_to_config(
        self,
        process_name: str,
        worker_name: str,
        worker_class_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        auto_start: bool = True
    ) -> bool:
        """
        Сохраняет конфигурацию воркера в конфиг процесса.
        
        Добавляет или обновляет конфигурацию воркера в секции workers
        конфигурации указанного процесса.
        
        Args:
            process_name: Имя процесса
            worker_name: Имя воркера
            worker_class_path: Путь к классу воркера (опционально)
            config: Конфигурация воркера (опционально)
            priority: Приоритет воркера (по умолчанию "normal")
            auto_start: Автоматически запускать воркер при регистрации (по умолчанию True)
        
        Returns:
            True если конфигурация успешно сохранена, False если процесс не найден
        
        Example:
            config_manager.save_worker_to_config(
                process_name="VisionProcess",
                worker_name="image_processor",
                worker_class_path="src.Modules.Vision_module.ImageProcessor",
                config={"batch_size": 10},
                priority="high",
                auto_start=True
            )
        """
        current_config = self.get_process_config()
        
        if process_name not in current_config:
            return False
        
        process_config = current_config[process_name]
        if not isinstance(process_config, dict):
            process_config = {}
            current_config[process_name] = process_config
        
        # Добавляем конфигурацию воркера
        if 'workers' not in process_config:
            process_config['workers'] = {}
        
        worker_config = {
            'enabled': True,
            'priority': priority,
            'auto_start': auto_start
        }
        
        if worker_class_path:
            worker_config['class'] = worker_class_path
        
        if config:
            worker_config['config'] = config
        
        process_config['workers'][worker_name] = worker_config
        
        # Обновляем конфигурацию
        self.update_process_config(current_config)
        
        return True


# Глобальный экземпляр для быстрого доступа
# Используется для обратной совместимости и удобства
_default_config: Optional[Config] = None


def get_config(name: str = "default") -> Config:
    """
    Удобная функция для получения конфигурации.
    
    Args:
        name: Имя конфигурации (по умолчанию "default")
    
    Returns:
        Экземпляр Config
    
    Примеры:
        config = get_config()
        app_config = get_config('app')
    """
    return ConfigManager.get_instance(name)
