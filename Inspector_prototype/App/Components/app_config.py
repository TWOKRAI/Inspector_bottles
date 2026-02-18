# -*- coding: utf-8 -*-
"""
Менеджер конфигурации приложения.
Хранит настройки приложения отдельно от рецептов (камеры, регионы, обработка).
Конфигурация сохраняется в Data/app_config.json
"""
import json
import os
from PyQt5.QtCore import QObject, pyqtSignal


class AppConfigManager(QObject):
    """
    Менеджер конфигурации приложения.
    Управляет настройками приложения, которые не относятся к рецептам.
    """
    
    config_changed = pyqtSignal()  # Сигнал изменения конфигурации
    
    def __init__(self, config_file_path=None):
        super().__init__()
        if config_file_path is None:
            # Путь по умолчанию: Data/app_config.json относительно корня проекта
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            config_file_path = os.path.join(base_dir, 'Data', 'app_config.json')
        self.config_file_path = config_file_path
        
        # Значения по умолчанию
        self._default_config = {
            'fullscreen_limit_width': 1920,
            'fullscreen_limit_height': 1080,
            'limit_fullhd': False,
        }
        
        # Загружаем конфигурацию
        self._config = self._load_config()
    
    def _load_config(self):
        """Загрузить конфигурацию из файла"""
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Объединяем с дефолтными значениями на случай если в файле нет каких-то ключей
                    result = self._default_config.copy()
                    result.update(config)
                    return result
            else:
                # Если файла нет, создаем с дефолтными значениями
                self._save_config(self._default_config)
                return self._default_config.copy()
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            import traceback
            traceback.print_exc()
            return self._default_config.copy()
    
    def _save_config(self, config=None):
        """Сохранить конфигурацию в файл"""
        try:
            # Создаем директорию если её нет
            config_dir = os.path.dirname(self.config_file_path)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            
            config_to_save = config if config is not None else self._config
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            import traceback
            traceback.print_exc()
    
    def get(self, key, default=None):
        """Получить значение конфигурации"""
        return self._config.get(key, default)
    
    def set(self, key, value):
        """Установить значение конфигурации и сохранить"""
        self._config[key] = value
        self._save_config()
        self.config_changed.emit()
    
    def get_fullscreen_limit_width(self):
        """Получить ширину ограничения fullscreen"""
        return self._config.get('fullscreen_limit_width', 1920)
    
    def get_fullscreen_limit_height(self):
        """Получить высоту ограничения fullscreen"""
        return self._config.get('fullscreen_limit_height', 1080)
    
    def set_fullscreen_limit_size(self, width, height):
        """Установить размер ограничения fullscreen"""
        self._config['fullscreen_limit_width'] = width
        self._config['fullscreen_limit_height'] = height
        self._save_config()
        self.config_changed.emit()
    
    def get_limit_fullhd(self):
        """Получить состояние ограничения fullscreen"""
        return self._config.get('limit_fullhd', False)
    
    def set_limit_fullhd(self, value):
        """Установить состояние ограничения fullscreen"""
        self._config['limit_fullhd'] = value
        self._save_config()
        self.config_changed.emit()
    
    def get_all_config(self):
        """Получить всю конфигурацию"""
        return self._config.copy()
    
    def set_config(self, config_dict):
        """Установить всю конфигурацию"""
        self._config.update(config_dict)
        self._save_config()
        self.config_changed.emit()
    
    def reset_to_defaults(self):
        """Сбросить конфигурацию к значениям по умолчанию"""
        self._config = self._default_config.copy()
        self._save_config()
        self.config_changed.emit()
