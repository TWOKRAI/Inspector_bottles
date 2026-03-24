#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Упрощенный менеджер стилей для компонентов
Работает со словарями и собирает CSS из конфигурации
"""

import os
from typing import Optional, Dict, Any
from PyQt5.QtWidgets import QWidget


class StyleManager:
    """
    Упрощенный класс для управления стилями компонентов.
    Загружает CSS шаблоны и подставляет переменные из конфигурации.
    """
    
    def __init__(self, config_manager):
        """
        Инициализация менеджера стилей
        
        Args:
            config_manager: Экземпляр ConfigManager
        """
        self.config_manager = config_manager
        self.widget = None
        self.component_type = None
    
    def set_widget(self, widget: QWidget, component_type: str = None):
        """
        Устанавливает виджет для применения стилей
        
        Args:
            widget: Виджет для применения стилей
            component_type: Тип компонента (Checkbox, Label, Slider, etc.)
        """
        self.widget = widget
        self.component_type = component_type
    
    def apply_styles(self):
        """
        Применяет стили к виджету.
        Загружает CSS шаблон из файла и подставляет переменные из конфигурации.
        """
        if not self.widget:
            print("[StyleManager] Виджет не установлен")
            return
        
        # Получаем путь к файлу стилей
        style_path = self.config_manager.get_style_path()
        
        if not style_path or not os.path.exists(style_path):
            print(f"[StyleManager] Файл стилей не найден: {style_path}")
            self._apply_minimal_styles()
            return
        
        # Загружаем CSS шаблон
        css_template = self._load_css_template(style_path)
        
        # Получаем переменные из конфигурации
        style_vars = self._extract_style_vars()
        
        # Подставляем переменные в шаблон
        css_content = self._substitute_variables(css_template, style_vars)
        
        # Применяем стили
        self.widget.setStyleSheet(css_content)
        
        if self._get_print_info():
            print(f"[StyleManager] Стили применены для {self.component_type}")
    
    def _load_css_template(self, style_path: str) -> str:
        """
        Загружает CSS шаблон из файла
        
        Args:
            style_path: Путь к файлу CSS
        
        Returns:
            Содержимое CSS файла
        """
        try:
            with open(style_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if self._get_print_info():
                print(f"[StyleManager] CSS шаблон загружен: {style_path}")
            
            return content
            
        except Exception as e:
            print(f"[StyleManager] Ошибка загрузки CSS: {e}")
            return ""
    
    def _extract_style_vars(self) -> Dict[str, Any]:
        """
        Извлекает переменные стилей из конфигурации и формирует словарь для подстановки
        
        Returns:
            Словарь переменных {название: значение}
        """
        config = self.config_manager.merged_config
        if not config:
            return {}
        
        style_vars = {}
        
        # Извлекаем переменные из default_style
        default_style = config.get('default_style', {})
        
        # Размеры
        size = default_style.get('size', {})
        style_vars['width'] = size.get('width', 60)
        style_vars['height'] = size.get('height', 30)
        
        # Цвета
        colors = default_style.get('colors', {})
        style_vars['background_unchecked'] = colors.get('background_unchecked', '#e0e0e0')
        style_vars['background_checked'] = colors.get('background_checked', '#4CAF50')
        style_vars['border_color'] = colors.get('border_color', '#cccccc')
        style_vars['text_color'] = colors.get('text_color', '#333333')
        style_vars['hover_color'] = colors.get('hover_color', '#f0f0f0')
        style_vars['background_color'] = colors.get('background_color', 'transparent')
        
        # Границы
        border = default_style.get('border', {})
        style_vars['border_radius'] = border.get('radius', 15)
        style_vars['border_width'] = border.get('width', 2)
        
        # Шрифт
        font = default_style.get('font', {})
        style_vars['font_family'] = font.get('family', 'Arial, sans-serif')
        style_vars['font_size'] = font.get('size', 12)
        style_vars['font_weight'] = font.get('weight', 'normal')
        
        # Выравнивание
        style_vars['alignment'] = default_style.get('alignment', 'center')
        
        # Изображения (если есть)
        images = config.get('images', {})
        if images:
            style_vars['unchecked_path'] = images.get('unchecked_icon', '')
            style_vars['checked_path'] = images.get('checked_icon', '')
        
        return style_vars
    
    def _substitute_variables(self, template: str, variables: Dict[str, Any]) -> str:
        """
        Подставляет переменные в CSS шаблон
        
        Args:
            template: CSS шаблон с плейсхолдерами {variable_name}
            variables: Словарь переменных
        
        Returns:
            CSS с подставленными значениями
        """
        result = template
        
        for var_name, var_value in variables.items():
            placeholder = f"{{{var_name}}}"
            result = result.replace(placeholder, str(var_value))
        
        return result
    
    def _apply_minimal_styles(self):
        """
        Применяет минимальные стили на случай ошибки загрузки
        """
        minimal_css = """
        QWidget {
            font-family: Arial, sans-serif;
            font-size: 12px;
            color: #333333;
        }
        """
        self.widget.setStyleSheet(minimal_css)
        print(f"[StyleManager] Применены минимальные стили для {self.component_type}")
    
    def build_css_from_dict(self, style_dict: Dict[str, Any]) -> str:
        """
        Собирает CSS из словаря конфигурации (для динамического создания стилей)
        
        Args:
            style_dict: Словарь со стилями
        
        Returns:
            CSS строка
        """
        # TODO: Реализовать сборку CSS из словаря для runtime изменений
        # Это будет полезно для динамического обновления стилей без перезапуска
        pass
    
    def reload_styles(self):
        """
        Перезагружает и применяет стили заново
        """
        self.apply_styles()
    
    def set_custom_css(self, css_content: str):
        """
        Устанавливает кастомный CSS напрямую
        
        Args:
            css_content: CSS содержимое
        """
        if self.widget:
            self.widget.setStyleSheet(css_content)
            
            if self._get_print_info():
                print("[StyleManager] Применены кастомные стили")
    
    def get_current_style_vars(self) -> Dict[str, Any]:
        """
        Возвращает текущие переменные стилей
        
        Returns:
            Словарь переменных стилей
        """
        return self._extract_style_vars()
    
    def _get_print_info(self) -> bool:
        """Получает значение флага print_info из конфигурации"""
        return self.config_manager.get_value('behavior.print_info', False)
