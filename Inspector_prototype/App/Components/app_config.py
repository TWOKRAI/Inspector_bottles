# -*- coding: utf-8 -*-
"""
Менеджер конфигурации приложения.
Хранит настройки приложения отдельно от рецептов (камеры, регионы, обработка).
Конфигурация сохраняется в App/Data/app_config.json
"""
import json
import os
from PyQt5.QtCore import QObject, pyqtSignal
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Pydantic модель конфигурации приложения"""
    fullscreen_limit_width: int = Field(default=1920, description='Ширина ограничения fullscreen')
    fullscreen_limit_height: int = Field(default=1080, description='Высота ограничения fullscreen')
    limit_fullhd: bool = Field(default=False, description='Ограничить fullscreen до заданного разрешения')


class AppConfigManager(QObject):
    """
    Менеджер конфигурации приложения.
    Управляет настройками приложения, которые не относятся к рецептам.
    """
    
    config_changed = pyqtSignal()  # Сигнал изменения конфигурации
    
    def __init__(self, config_file_path=None):
        super().__init__()
        if config_file_path is None:
            # Путь по умолчанию: App/Data/app_config.json
            base_dir = os.path.dirname(os.path.dirname(__file__))
            config_file_path = os.path.join(base_dir, 'Data', 'app_config.json')
        self.config_file_path = config_file_path
        
        # Загружаем конфигурацию в Pydantic модель
        self._config: AppConfig = self._load_config()
    
    def _load_config(self) -> AppConfig:
        """Загрузить конфигурацию из файла"""
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    config_dict = json.load(f)
                    # Pydantic автоматически использует значения по умолчанию для отсутствующих полей
                    return AppConfig.model_validate(config_dict)
            else:
                # Если файла нет, создаем с дефолтными значениями
                default_config = AppConfig()
                self._save_config(default_config)
                return default_config
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            import traceback
            traceback.print_exc()
            # Возвращаем конфиг с дефолтными значениями
            return AppConfig()
    
    def _save_config(self, config: AppConfig = None):
        """Сохранить конфигурацию в файл"""
        try:
            # Создаем директорию если её нет
            config_dir = os.path.dirname(self.config_file_path)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            
            config_to_save = config if config is not None else self._config
            # Преобразуем Pydantic модель в dict для сохранения в JSON
            config_dict = config_to_save.model_dump()
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            import traceback
            traceback.print_exc()
    
    def get(self, key, default=None):
        """Получить значение конфигурации (для обратной совместимости)"""
        return getattr(self._config, key, default)
    
    def set(self, key, value):
        """Установить значение конфигурации и сохранить (для обратной совместимости)"""
        setattr(self._config, key, value)
        self._save_config()
        self.config_changed.emit()
    
    def get_fullscreen_limit_width(self):
        """Получить ширину ограничения fullscreen"""
        return self._config.fullscreen_limit_width
    
    def get_fullscreen_limit_height(self):
        """Получить высоту ограничения fullscreen"""
        return self._config.fullscreen_limit_height
    
    def set_fullscreen_limit_size(self, width, height):
        """Установить размер ограничения fullscreen"""
        self._config.fullscreen_limit_width = width
        self._config.fullscreen_limit_height = height
        self._save_config()
        self.config_changed.emit()
    
    def get_limit_fullhd(self):
        """Получить состояние ограничения fullscreen"""
        return self._config.limit_fullhd
    
    def set_limit_fullhd(self, value):
        """Установить состояние ограничения fullscreen"""
        self._config.limit_fullhd = value
        self._save_config()
        self.config_changed.emit()
    
    def get_all_config(self):
        """Получить всю конфигурацию как словарь"""
        return self._config.model_dump()
    
    def set_config(self, config_dict):
        """Установить всю конфигурацию из словаря"""
        self._config = AppConfig.model_validate(config_dict)
        self._save_config()
        self.config_changed.emit()
    
    def reset_to_defaults(self):
        """Сбросить конфигурацию к значениям по умолчанию"""
        self._config = AppConfig()
        self._save_config()
        self.config_changed.emit()
