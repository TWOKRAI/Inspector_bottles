#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный менеджер версий для компонентов
"""

import os
import re
import shutil
import json
from typing import Optional, List, Dict, Tuple
from packaging import version


class VersionManager:
    """
    Универсальный класс для управления версиями любых компонентов.
    Автоматически адаптируется под структуру каждого компонента.
    """
    
    def __init__(self, components_base_path: str = "app/core/Components"):
        """
        Инициализация универсального менеджера версий
        
        Args:
            components_base_path: Базовый путь к папке с компонентами
        """
        self.components_base_path = components_base_path
        self._version_cache = {}
        self._component_cache = {}
    
    def get_component_path(self, component_name: str) -> str:
        """
        Получает путь к папке компонента
        
        Args:
            component_name: Название компонента (например, 'Checkbox')
        
        Returns:
            Путь к папке компонента
        """
        return os.path.join(self.components_base_path, component_name)
    
    def get_base_config_path(self, component_name: str) -> str:
        """
        Получает путь к папке Base_Config компонента
        
        Args:
            component_name: Название компонента
        
        Returns:
            Путь к папке Base_Config
        """
        return os.path.join(self.get_component_path(component_name), "Base_Config")
    
    def get_available_versions(self, component_name: str) -> List[str]:
        """
        Получает список доступных версий для компонента
        
        Args:
            component_name: Название компонента
        
        Returns:
            Список версий, отсортированный по убыванию
        """
        component_path = self.get_component_path(component_name)
        
        if not os.path.exists(component_path):
            return []
        
        versions = []
        
        # Ищем версии в папке компонента
        for item in os.listdir(component_path):
            item_path = os.path.join(component_path, item)
            if os.path.isdir(item_path) and self._is_valid_version(item):
                versions.append(item)
        
        # Сортируем версии по убыванию
        try:
            versions.sort(key=lambda v: version.parse(v), reverse=True)
        except version.InvalidVersion:
            # Если версии не в стандартном формате, сортируем как строки
            versions.sort(reverse=True)
        
        return versions
    
    def get_latest_version(self, component_name: str) -> Optional[str]:
        """
        Получает последнюю версию компонента
        
        Args:
            component_name: Название компонента
        
        Returns:
            Последняя версия или None, если версии не найдены
        """
        versions = self.get_available_versions(component_name)
        return versions[0] if versions else None
    
    def get_version_path(self, component_name: str, version: Optional[str] = None) -> Optional[str]:
        """
        Получает путь к папке с версией компонента
        
        Args:
            component_name: Название компонента
            version: Версия (если None, возвращает путь к Base_Config)
        
        Returns:
            Путь к папке с версией или None, если не найдена
        """
        if version is None:
            # Возвращаем путь к Base_Config
            base_path = self.get_base_config_path(component_name)
            return base_path if os.path.exists(base_path) else None
        
        version_path = os.path.join(self.get_component_path(component_name), version)
        return version_path if os.path.exists(version_path) else None
    
    def get_config_path(self, component_name: str, version: Optional[str] = None) -> Optional[str]:
        """
        Получает путь к файлу конфигурации
        
        Args:
            component_name: Название компонента
            version: Версия (если None, используется Base_Config)
        
        Returns:
            Путь к файлу конфигурации или None, если не найден
        """
        version_path = self.get_version_path(component_name, version)
        if not version_path:
            return None
        
        config_path = os.path.join(version_path, 'config.json')
        return config_path if os.path.exists(config_path) else None
    
    def get_style_path(self, component_name: str, version: Optional[str] = None) -> Optional[str]:
        """
        Получает путь к файлу стилей
        
        Args:
            component_name: Название компонента
            version: Версия (если None, используется Base_Config)
        
        Returns:
            Путь к файлу стилей или None, если не найден
        """
        version_path = self.get_version_path(component_name, version)
        if not version_path:
            return None
        
        style_path = os.path.join(version_path, 'style.css')
        return style_path if os.path.exists(style_path) else None
    
    def resolve_version(self, component_name: str, requested_version: Optional[str] = None) -> Tuple[str, str, str]:
        """
        Разрешает версию компонента и возвращает пути к файлам
        
        Args:
            component_name: Название компонента
            requested_version: Запрошенная версия (может быть None)
        
        Returns:
            Кортеж (resolved_version, config_path, style_path)
        """
        # Определяем версию
        if requested_version is None:
            resolved_version = "Base_Config"
        else:
            resolved_version = requested_version
        
        # Получаем пути к файлам
        config_path = self.get_config_path(component_name, None if resolved_version == "Base_Config" else resolved_version)
        style_path = self.get_style_path(component_name, None if resolved_version == "Base_Config" else resolved_version)
        
        if config_path is None:
            raise ValueError(f"Не найден файл конфигурации для '{component_name}' версии '{resolved_version}'")
        
        if style_path is None:
            raise ValueError(f"Не найден файл стилей для '{component_name}' версии '{resolved_version}'")
        
        return resolved_version, config_path, style_path
    
    def _is_valid_version(self, version_str: str) -> bool:
        """
        Проверяет, является ли строка валидной версией
        
        Args:
            version_str: Строка для проверки
        
        Returns:
            True, если строка является валидной версией
        """
        # Исключаем служебные папки
        if version_str in ['Base_Config', 'Base', '__pycache__', 'base', 'base_class', 'managers', 'Managers']:
            return False
        
        # Проверяем формат версии (например, v1.0.0, 1.0.0, v2.1.3)
        version_pattern = r'^v?\d+\.\d+\.\d+$'
        return bool(re.match(version_pattern, version_str))
    
    def get_version_info(self, component_name: str, version: Optional[str] = None) -> Dict:
        """
        Получает информацию о версии компонента
        
        Args:
            component_name: Название компонента
            version: Версия (если None, используется Base_Config)
        
        Returns:
            Словарь с информацией о версии
        """
        try:
            resolved_version, config_path, style_path = self.resolve_version(component_name, version)
            
            return {
                'component_name': component_name,
                'version': resolved_version,
                'config_path': config_path,
                'style_path': style_path,
                'version_path': os.path.dirname(config_path),
                'is_base': resolved_version == "Base_Config",
                'is_latest': resolved_version == self.get_latest_version(component_name)
            }
        except ValueError as e:
            return {
                'error': str(e),
                'component_name': component_name,
                'requested_version': version
            }
    
    def list_all_components(self) -> List[str]:
        """
        Получает список всех доступных компонентов
        
        Returns:
            Список названий компонентов
        """
        if not os.path.exists(self.components_base_path):
            return []
        
        components = []
        for item in os.listdir(self.components_base_path):
            item_path = os.path.join(self.components_base_path, item)
            if os.path.isdir(item_path) and item not in ['Managers', '__pycache__', 'Test']:
                # Проверяем, есть ли Base_Config или хотя бы одна версия
                if (os.path.exists(self.get_base_config_path(item)) or 
                    self.get_available_versions(item)):
                    components.append(item)
        
        return sorted(components)
    
    def create_base_config(self, component_name: str, 
                           config_template: Optional[Dict] = None, 
                           style_template: Optional[str] = None) -> bool:
        """
        Создает базовую конфигурацию для компонента
        
        Args:
            component_name: Название компонента
            config_template: Шаблон конфигурации (если None, используется дефолтный)
            style_template: Шаблон стилей (если None, используется дефолтный)
        
        Returns:
            True, если создание прошло успешно
        """
        try:
            # Создаем папку для Base_Config
            base_config_path = self.get_base_config_path(component_name)
            os.makedirs(base_config_path, exist_ok=True)
            
            # Создаем конфигурацию
            config_path = os.path.join(base_config_path, 'config.json')
            if not os.path.exists(config_path):
                config = config_template or self._get_default_config_template(component_name)
                self._save_json_file(config_path, config)
            
            # Создаем стили
            style_path = os.path.join(base_config_path, 'style.css')
            if not os.path.exists(style_path):
                style = style_template or self._get_default_style_template(component_name)
                self._save_text_file(style_path, style)
            
            return True
            
        except Exception as e:
            print(f"Ошибка создания базовой конфигурации: {e}")
            return False
    
    def create_version_from_base(self, component_name: str, version: str) -> bool:
        """
        Создает новую версию компонента, копируя Base_Config
        
        Args:
            component_name: Название компонента
            version: Версия для создания
        
        Returns:
            True, если создание прошло успешно
        """
        try:
            base_config_path = self.get_base_config_path(component_name)
            if not os.path.exists(base_config_path):
                print(f"Base_Config для компонента '{component_name}' не найден")
                return False
            
            version_path = os.path.join(self.get_component_path(component_name), version)
            if os.path.exists(version_path):
                print(f"Версия '{version}' для компонента '{component_name}' уже существует")
                return False
            
            # Копируем Base_Config в новую версию
            shutil.copytree(base_config_path, version_path)
            
            # Обновляем версию в конфигурации
            config_path = os.path.join(version_path, 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                config['version'] = version
                self._save_json_file(config_path, config)
            
            return True
            
        except Exception as e:
            print(f"Ошибка создания версии: {e}")
            return False
    
    def _get_default_config_template(self, component_name: str) -> Dict:
        """Возвращает дефолтный шаблон конфигурации для компонента"""
        from datetime import datetime
        return {
            "component_name": component_name,
            "version": "Base_Config",
            "metadata": {
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "author": "System",
                "description": f"Базовая конфигурация для {component_name}"
            },
            # TODO: Сделать шаблоны специфичными для каждого типа компонента
            "default_style": {
                "size": {"width": 60, "height": 30},
                "colors": {
                    "background_unchecked": "#e0e0e0",
                    "background_checked": "#4CAF50",
                    "border_color": "#cccccc",
                    "text_color": "#333333",
                    "hover_color": "#f0f0f0"
                },
                "border": {"radius": 15, "width": 2},
                "animation": {"duration": 200, "easing": "ease-in-out"},
                "font": {"family": "Arial, sans-serif", "size": 12, "weight": "normal"}
            },
            "images": {
                "unchecked_icon": "",
                "checked_icon": "",
                "custom_icons": False
            },
            "layout": {
                "default_position": "right",
                "spacing": 10,
                "alignment": "center"
            },
            "behavior": {
                "enable_hover_effects": True,
                "enable_animations": True,
                "enable_sound": False
            }
        }
    
    def _get_default_style_template(self, component_name: str) -> str:
        """Возвращает дефолтный шаблон стилей для компонента"""
        # TODO: Сделать шаблоны стилей специфичными для каждого компонента
        return f"""/* Дефолтные стили для {component_name} */ 
QCheckBox {{
    font-family: Arial, sans-serif;
    font-size: 12px;
    color: #333333;
    spacing: 10px;
}}

QCheckBox::indicator {{
    width: 60px;
    height: 30px;
    border: 2px solid #cccccc;
    border-radius: 15px;
    background-color: #e0e0e0;
}}

QCheckBox::indicator:hover {{
    background-color: #f0f0f0;
    border-color: #999999;
}}

QCheckBox::indicator:checked {{
    background-color: #4CAF50;
    border-color: #45a049;
}}

QCheckBox::indicator:checked:hover {{
    background-color: #45a049;
    border-color: #3d8b40;
}}

QCheckBox::indicator:focus {{
    outline: none;
    border-color: #2196F3;
}}

QCheckBox::text {{
    color: #333333;
    font-weight: normal;
    padding-left: 5px;
}}

QCheckBox::text:hover {{
    color: #555555;
}}

QCheckBox::indicator:disabled {{
    background-color: #f5f5f5;
    border-color: #e0e0e0;
    color: #999999;
}}

QCheckBox::text:disabled {{
    color: #999999;
}}

QCheckBox::indicator:pressed {{
    background-color: #cccccc;
}}

QCheckBox::indicator:checked:pressed {{
    background-color: #3d8b40;
}}
"""
    
    def _save_json_file(self, file_path: str, data: Dict):
        """Сохраняет данные в JSON файл"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _save_text_file(self, file_path: str, content: str):
        """Сохраняет текст в файл"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def ensure_component_exists(self, component_name: str) -> bool:
        """
        Убеждается, что компонент существует, создает Base_Config если нужно
        
        Args:
            component_name: Название компонента
        
        Returns:
            True, если компонент существует или был создан
        """
        # Проверяем, есть ли Base_Config для компонента
        base_config_path = self.get_base_config_path(component_name)
        if not os.path.exists(base_config_path):
            print(f"Base_Config для компонента '{component_name}' не найден, создаем...")
            return self.create_base_config(component_name)
        
        return True
    
    def get_component_info(self, component_name: str) -> Dict:
        """
        Получает полную информацию о компоненте
        
        Args:
            component_name: Название компонента
        
        Returns:
            Словарь с информацией о компоненте
        """
        return {
            'name': component_name,
            'path': self.get_component_path(component_name),
            'base_config_path': self.get_base_config_path(component_name),
            'has_base_config': os.path.exists(self.get_base_config_path(component_name)),
            'available_versions': self.get_available_versions(component_name),
            'latest_version': self.get_latest_version(component_name),
            'exists': os.path.exists(self.get_component_path(component_name))
        }