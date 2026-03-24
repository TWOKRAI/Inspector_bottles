#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Упрощенный менеджер конфигураций для компонентов
Работает со словарями и merge по ключам
"""

import os
import json
from typing import Optional, Dict, Any, List


class ConfigManager:
    """
    Упрощенный класс для управления конфигурациями компонентов.
    Загружает JSON в словари и мержит по ключам в правильной иерархии.
    """
    
    def __init__(self, components_base_path: str = "app/core/Components"):
        """
        Инициализация менеджера конфигураций
        
        Args:
            components_base_path: Базовый путь к папке с компонентами
        """
        self.components_base_path = components_base_path
        self.merged_config = None
        self.current_component = None
        self.current_version = None
    
    def load_config(self, 
                   component_name: str,
                   element_name: Optional[str] = None,
                   window_config_path: Optional[str] = None,
                   global_theme_version: Optional[str] = None,
                   global_theme_path: str = "app/core/Theme") -> Dict:
        """
        Загружает и объединяет конфигурацию с трёхуровневой иерархией:
        1. Base_Config компонента (базовые настройки)
        2. Global Theme (глобальная тема, если указана версия)
        3. Window config (конфигурация окна, если указана)
        
        Args:
            component_name: Название компонента (например, 'Checkbox', 'Label')
            element_name: Название конкретного элемента для поиска в window config
            window_config_path: Путь к файлу конфигурации окна
            global_theme_version: Версия глобальной темы (например, 'v1.0.0')
            global_theme_path: Путь к папке с глобальными темами
        
        Returns:
            Объединенная конфигурация
        """
        self.current_component = component_name
        self.current_version = global_theme_version
        
        # Уровень 1: Базовая конфигурация компонента
        base_dict = self._load_base_config(component_name)
        
        # Уровень 2: Глобальная тема (если указана)
        theme_dict = {}
        if global_theme_version:
            theme_dict = self._load_global_theme(component_name, global_theme_version, global_theme_path)
        
        # Уровень 3: Конфигурация окна (если указана)
        window_dict = {}
        if window_config_path and element_name:
            window_dict = self._load_window_config(window_config_path, element_name)
        
        # Мержим по иерархии: base <- theme <- window
        self.merged_config = self._merge_dicts(base_dict, theme_dict, window_dict)
        
        return self.merged_config
    
    def load_nested_config(self,
                          parent_component: str,
                          child_component: str,
                          element_name: Optional[str] = None,
                          window_config_path: Optional[str] = None,
                          global_theme_version: Optional[str] = None,
                          global_theme_path: str = "app/core/Theme") -> Dict:
        """
        Загружает конфигурацию для вложенного компонента с расширенной иерархией:
        1. Base_Config дочернего компонента
        2. Надстройки из Base_Config родительского компонента
        3. Надстройки из Global Theme родительского компонента
        4. Надстройки из Window config
        
        Пример: Label внутри Checkbox
        - Base_Config Label
        - Надстройки Label из Checkbox/Base_Config
        - Надстройки Label из Theme/Checkbox/vX.X.X
        - Надстройки Label из window config
        
        Args:
            parent_component: Родительский компонент (например, 'Checkbox')
            child_component: Дочерний компонент (например, 'Label')
            element_name: Название элемента
            window_config_path: Путь к конфигурации окна
            global_theme_version: Версия глобальной темы
            global_theme_path: Путь к глобальным темам
        
        Returns:
            Объединенная конфигурация дочернего компонента
        """
        # Уровень 1: Базовая конфигурация дочернего компонента
        child_base_dict = self._load_base_config(child_component)
        
        # Уровень 2: Надстройки из базовой конфигурации родителя
        parent_base_dict = self._load_base_config(parent_component)
        parent_overrides = parent_base_dict.get(child_component, {})
        
        # Уровень 3: Надстройки из глобальной темы родителя
        theme_overrides = {}
        if global_theme_version:
            parent_theme_dict = self._load_global_theme(parent_component, global_theme_version, global_theme_path)
            theme_overrides = parent_theme_dict.get(child_component, {})
        
        # Уровень 4: Надстройки из конфигурации окна
        window_overrides = {}
        if window_config_path and element_name:
            window_dict = self._load_window_config(window_config_path, element_name)
            window_overrides = window_dict.get(child_component, {})
        
        # Мержим: child_base <- parent_overrides <- theme_overrides <- window_overrides
        merged = self._merge_dicts(child_base_dict, parent_overrides, theme_overrides, window_overrides)
        
        return merged
    
    def _load_base_config(self, component_name: str) -> Dict:
        """
        Загружает базовую конфигурацию компонента из Base_Config
        
        Args:
            component_name: Название компонента
        
        Returns:
            Словарь конфигурации
        """
        config_path = os.path.join(
            self.components_base_path,
            component_name,
            "Base_Config",
            "config.json"
        )
        
        return self._load_json(config_path, f"Base_Config для {component_name}")
    
    def _load_global_theme(self, component_name: str, version: str, theme_path: str) -> Dict:
        """
        Загружает конфигурацию из глобальной темы
        
        Args:
            component_name: Название компонента
            version: Версия темы
            theme_path: Путь к глобальным темам
        
        Returns:
            Словарь конфигурации темы
        """
        config_path = os.path.join(theme_path, component_name, version, "config.json")
        return self._load_json(config_path, f"Global Theme {version} для {component_name}")
    
    def _load_window_config(self, window_config_path: str, element_name: str) -> Dict:
        """
        Загружает конфигурацию конкретного элемента из файла окна
        
        Args:
            window_config_path: Путь к файлу конфигурации окна
            element_name: Название элемента для поиска
        
        Returns:
            Словарь конфигурации элемента
        """
        full_config = self._load_json(window_config_path, "Window config")
        
        # Ищем конфигурацию для конкретного элемента
        if isinstance(full_config, list):
            for item in full_config:
                if item.get('name') == element_name:
                    return item
        elif isinstance(full_config, dict) and full_config.get('name') == element_name:
            return full_config
        
        # Если не нашли, возвращаем пустой словарь
        return {}
    
    def _load_json(self, file_path: str, description: str = "") -> Dict:
        """
        Загружает JSON файл в словарь
        
        Args:
            file_path: Путь к JSON файлу
            description: Описание для логирования
        
        Returns:
            Словарь из JSON или пустой словарь при ошибке
        """
        try:
            if not os.path.exists(file_path):
                if description:
                    print(f"[ConfigManager] Файл не найден: {description} ({file_path})")
                return {}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if description and self._get_print_info():
                print(f"[ConfigManager] Загружен: {description}")
            
            return data
            
        except json.JSONDecodeError as e:
            print(f"[ConfigManager] Ошибка парсинга JSON в {file_path}: {e}")
            return {}
        except Exception as e:
            print(f"[ConfigManager] Ошибка загрузки {file_path}: {e}")
            return {}
    
    def _merge_dicts(self, *dicts: Dict) -> Dict:
        """
        Мержит несколько словарей по ключам.
        Последующие словари переопределяют значения предыдущих.
        
        Args:
            *dicts: Словари для объединения
        
        Returns:
            Объединенный словарь
        """
        result = {}
        
        for d in dicts:
            if not d:
                continue
            result = self._deep_merge(result, d)
        
        return result
    
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """
        Рекурсивно объединяет два словаря.
        Если ключ есть в обоих словарях и оба значения - словари, рекурсивно мержит.
        Иначе значение из update переопределяет значение из base.
        
        Args:
            base: Базовый словарь
            update: Словарь с обновлениями
        
        Returns:
            Объединенный словарь
        """
        result = base.copy()
        
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Рекурсивно мержим вложенные словари
                result[key] = self._deep_merge(result[key], value)
            else:
                # Переопределяем значение
                result[key] = value
        
        return result
    
    def get_value(self, key_path: str, default=None):
        """
        Получает значение из конфигурации по пути
        
        Args:
            key_path: Путь к значению через точку (например, 'default_style.colors.text_color')
            default: Значение по умолчанию
        
        Returns:
            Значение или default
        """
        if not self.merged_config:
            return default
        
        keys = key_path.split('.')
        value = self.merged_config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_style_path(self) -> Optional[str]:
        """
        Получает путь к файлу стилей для текущего компонента
        
        Returns:
            Путь к файлу стилей или None
        """
        if not self.current_component:
            return None
        
        # Проверяем путь из конфигурации
        style_path = self.get_value('path_style')
        if style_path and os.path.exists(style_path):
            return style_path
        
        # Иначе используем базовый путь
        base_style_path = os.path.join(
            self.components_base_path,
            self.current_component,
            "Base_Config",
            "style.css"
        )
        
        return base_style_path if os.path.exists(base_style_path) else None
    
    def _get_print_info(self) -> bool:
        """Получает значение флага print_info из конфигурации"""
        return self.get_value('behavior.print_info', False)
    
    def reload(self) -> Dict:
        """
        Перезагружает текущую конфигурацию
        
        Returns:
            Обновленная конфигурация
        """
        if self.merged_config:
            # TODO: Сохранить параметры последней загрузки для перезагрузки
            pass
        return self.merged_config or {}
    
    def save_to_file(self, file_path: str):
        """
        Сохраняет текущую конфигурацию в файл
        
        Args:
            file_path: Путь для сохранения
        """
        if not self.merged_config:
            print("[ConfigManager] Нет конфигурации для сохранения")
            return
        
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.merged_config, f, indent=2, ensure_ascii=False)
            
            if self._get_print_info():
                print(f"[ConfigManager] Конфигурация сохранена: {file_path}")
        
        except Exception as e:
            print(f"[ConfigManager] Ошибка сохранения конфигурации: {e}")
