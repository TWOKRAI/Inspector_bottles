# -*- coding: utf-8 -*-
"""
Менеджер переводов (интернационализация).
Поддерживает переводы из метаданных Pydantic и файлов переводов (JSON/YAML).
"""
import os
import json
import yaml
from typing import Dict, Optional, Any
from PyQt5.QtCore import QObject, pyqtSignal


class TranslationManager(QObject):
    """
    Менеджер переводов для интернационализации приложения.
    
    Поддерживает:
    - Переводы из метаданных Pydantic (json_schema_extra['*_i18n'])
    - Файлы переводов (JSON/YAML)
    - Django-like ключи переводов
    - Автоматическое определение языка
    
    Пример использования:
        translation_manager = TranslationManager(default_language='ru')
        translation_manager.set_language('en')
        text = translation_manager.translate('draw.dp.info', default='Обратное разрешение')
    """
    
    # Сигнал изменения языка
    language_changed = pyqtSignal(str)
    
    def __init__(self, default_language: str = 'ru', translations_path: Optional[str] = None):
        """
        Args:
            default_language: Язык по умолчанию (например, 'ru', 'en', 'de')
            translations_path: Путь к директории с файлами переводов (опционально)
        """
        super().__init__()
        
        self.default_language = default_language
        self.current_language = default_language
        self.translations_path = translations_path
        
        # Кэш переводов из файлов
        self._file_translations: Dict[str, Dict[str, str]] = {}
        
        # Загружаем переводы из файлов если указан путь
        if self.translations_path and os.path.isdir(self.translations_path):
            self._load_file_translations()
    
    def set_language(self, language: str):
        """
        Установить текущий язык.
        
        Args:
            language: Код языка (например, 'ru', 'en', 'de')
        """
        if language != self.current_language:
            self.current_language = language
            self.language_changed.emit(language)
    
    def get_language(self) -> str:
        """Получить текущий язык"""
        return self.current_language
    
    def translate(self, key: str, default: Optional[str] = None, 
                  metadata: Optional[Dict[str, Any]] = None,
                  field: str = 'info') -> str:
        """
        Перевести ключ или значение из метаданных.
        
        Приоритет:
        1. Метаданные поля (metadata['*_i18n'][language])
        2. Файлы переводов (translations[key][language])
        3. Значение по умолчанию (default)
        4. Ключ (key)
        
        Args:
            key: Ключ перевода (например, 'draw.dp.info') или ключ из файла переводов
            default: Значение по умолчанию (используется если перевод не найден)
            metadata: Метаданные поля из RegistersManager (опционально)
            field: Поле для перевода из метаданных ('info', 'description', и т.д.)
            
        Returns:
            str: Переведённый текст
        """
        # 1. Проверяем метаданные поля (если переданы)
        if metadata:
            i18n_key = f"{field}_i18n"
            if i18n_key in metadata:
                translations = metadata[i18n_key]
                if isinstance(translations, dict):
                    translated = translations.get(self.current_language)
                    if translated:
                        return translated
                    # Fallback на язык по умолчанию
                    translated = translations.get(self.default_language)
                    if translated:
                        return translated
        
        # 2. Проверяем файлы переводов
        if key in self._file_translations:
            lang_translations = self._file_translations[key]
            translated = lang_translations.get(self.current_language)
            if translated:
                return translated
            # Fallback на язык по умолчанию
            translated = lang_translations.get(self.default_language)
            if translated:
                return translated
        
        # 3. Возвращаем значение по умолчанию или ключ
        return default if default is not None else key
    
    def translate_metadata(self, metadata: Dict[str, Any], field: str = 'info') -> str:
        """
        Перевести значение из метаданных поля.
        
        Args:
            metadata: Метаданные поля из RegistersManager
            field: Поле для перевода ('info', 'description', и т.д.)
            
        Returns:
            str: Переведённый текст
        """
        # Проверяем i18n версию поля
        i18n_key = f"{field}_i18n"
        if i18n_key in metadata:
            translations = metadata[i18n_key]
            if isinstance(translations, dict):
                translated = translations.get(self.current_language)
                if translated:
                    return translated
                # Fallback на язык по умолчанию
                translated = translations.get(self.default_language)
                if translated:
                    return translated
        
        # Возвращаем обычное значение поля
        return metadata.get(field, metadata.get('description', ''))
    
    def _load_file_translations(self):
        """Загрузить переводы из файлов (JSON/YAML)"""
        if not self.translations_path or not os.path.isdir(self.translations_path):
            return
        
        # Ищем файлы переводов
        for filename in os.listdir(self.translations_path):
            filepath = os.path.join(self.translations_path, filename)
            
            # Определяем формат по расширению
            if filename.endswith('.json'):
                self._load_json_translations(filepath)
            elif filename.endswith('.yaml') or filename.endswith('.yml'):
                self._load_yaml_translations(filepath)
    
    def _load_json_translations(self, filepath: str):
        """Загрузить переводы из JSON файла"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._merge_translations(data)
        except Exception as e:
            print(f"Ошибка загрузки JSON переводов из {filepath}: {e}")
    
    def _load_yaml_translations(self, filepath: str):
        """Загрузить переводы из YAML файла"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                self._merge_translations(data)
        except Exception as e:
            print(f"Ошибка загрузки YAML переводов из {filepath}: {e}")
    
    def _merge_translations(self, data: Dict[str, Any]):
        """
        Объединить переводы в кэш.
        
        Ожидаемый формат:
        {
            'draw.dp.info': {
                'ru': 'Обратное разрешение аккумулятора',
                'en': 'Inverse accumulator resolution',
                'de': 'Inverse Akkumulatorauflösung'
            },
            ...
        }
        """
        if isinstance(data, dict):
            for key, translations in data.items():
                if isinstance(translations, dict):
                    self._file_translations[key] = translations
    
    def add_translation(self, key: str, language: str, translation: str):
        """
        Добавить перевод программно.
        
        Args:
            key: Ключ перевода
            language: Код языка
            translation: Переведённый текст
        """
        if key not in self._file_translations:
            self._file_translations[key] = {}
        self._file_translations[key][language] = translation
    
    def get_available_languages(self) -> list:
        """
        Получить список доступных языков из загруженных переводов.
        
        Returns:
            list: Список кодов языков
        """
        languages = set()
        
        # Из файлов переводов
        for translations in self._file_translations.values():
            languages.update(translations.keys())
        
        return sorted(list(languages))
    
    def reload_translations(self):
        """Перезагрузить переводы из файлов"""
        self._file_translations.clear()
        if self.translations_path:
            self._load_file_translations()
