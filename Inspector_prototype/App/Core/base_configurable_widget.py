# -*- coding: utf-8 -*-
"""
Базовый класс для конфигурируемых виджетов с поддержкой свойств и автоматического применения конфигурации.
"""
import inspect
from PyQt5.QtWidgets import QWidget
from typing import Optional, Any
from pydantic.fields import FieldInfo


class ConfigurableWidget(QWidget):
    """
    Базовый класс для виджетов, которые могут быть сконфигурированы через свойства.
    
    Поддерживает:
    - Настройку через свойства (@property/@setter)
    - Автоматическое применение конфигурации при изменении свойств
    - Автоматическое определение register_name из field_name
    - Обратную совместимость с конструктором
    
    Пример использования:
        # Вариант 1: Через конструктор
        widget = MyWidget(register_name='draw', field_name='dp', registers_manager=rm)
        
        # Вариант 2: Через свойства
        widget = MyWidget(registers_manager=rm)
        widget.register_name = 'draw'
        widget.field_name = 'dp'  # Автоматически применяется конфигурация
        
        # Вариант 3: Автоматическое определение
        widget = MyWidget(registers_manager=rm)
        widget.field_name = 'draw.dp'  # Автоматически парсит
    """
    
    def __init__(self, register_name: Optional[str] = None,
                 field_name: Optional[str] = None,
                 field: Optional[Any] = None,  # Может быть FieldInfo или tuple (model_class, field_name)
                 registers_manager: Optional[Any] = None,
                 access_level: int = 0,
                 parent: Optional[QWidget] = None):
        """
        Args:
            register_name: Имя регистра (например, 'draw', 'processing')
            field_name: Имя поля (например, 'dp', 'crop_top') или 'register.field' для автоопределения
            field: Поле модели (например, DrawRegisters.dp) или tuple (model_class, field_name)
            registers_manager: Экземпляр RegistersManager
            access_level: Уровень доступа пользователя (0 = обычный, 1+ = администратор)
            parent: Родительский виджет (может быть MainWindow для автоматического определения параметров)
        """
        super().__init__(parent)
        
        # Приватные атрибуты
        self._register_name: Optional[str] = None
        self._field_name: Optional[str] = None
        self._registers_manager: Optional[Any] = registers_manager
        self._access_level: int = access_level
        self._is_initialized: bool = False
        
        # Обработка передачи поля модели напрямую
        if field is not None:
            register_name_from_field, field_name_from_field = self._extract_from_field(field, parent)
            if register_name_from_field:
                register_name = register_name_from_field
            if field_name_from_field:
                field_name = field_name_from_field
        
        # Автоматическое определение параметров из parent (если это MainWindow)
        if parent and not registers_manager:
            registers_manager = self._get_registers_manager_from_parent(parent)
        if parent and not access_level:
            access_level = self._get_access_level_from_parent(parent)
        
        self._registers_manager = registers_manager
        
        # Устанавливаем значения через свойства для автоматического применения
        if register_name:
            self.register_name = register_name
        if field_name:
            self.field_name = field_name
        if registers_manager:
            self.registers_manager = registers_manager
        if access_level is not None:
            self.access_level = access_level
    
    def _extract_from_field(self, field: Any, parent: Optional[QWidget] = None) -> tuple[Optional[str], Optional[str]]:
        """
        Извлечь register_name и field_name из поля модели.
        
        Args:
            field: Может быть:
                - FieldInfo (например, DrawRegisters.dp) - пытается определить через inspect
                - tuple (model_class, field_name) или (model_class, FieldInfo)
                - строка вида "DrawRegisters.dp" или "draw.dp"
            parent: Родительский виджет (для получения registers_manager и поиска по всем регистрам)
        
        Returns:
            tuple: (register_name, field_name)
        """
        # Если это tuple (model_class, field_name) или (model_class, FieldInfo)
        if isinstance(field, tuple) and len(field) == 2:
            model_class, field_info = field
            register_name = self._get_register_name_from_model(model_class)
            # Если второй элемент - строка, это field_name
            if isinstance(field_info, str):
                return register_name, field_info
            # Если второй элемент - FieldInfo, пытаемся извлечь имя
            if isinstance(field_info, FieldInfo):
                # Ищем имя поля в модели
                if hasattr(model_class, 'model_fields'):
                    for name, info in model_class.model_fields.items():
                        if info is field_info:
                            return register_name, name
            if hasattr(field_info, '__name__'):
                return register_name, field_info.__name__
            return register_name, None
        
        # Если это строка вида "DrawRegisters.dp" или "draw.dp"
        if isinstance(field, str):
            if '.' in field:
                parts = field.split('.', 1)
                if len(parts) == 2:
                    model_or_register_name, field_name = parts
                    # Нормализуем имя модели к имени регистра (например, "DrawRegisters" -> "draw")
                    register_name = self._normalize_register_name(model_or_register_name)
                    return register_name, field_name
            else:
                # Если нет точки, это просто имя поля - попробуем автоопределение
                return None, field
        
        # Если это FieldInfo - пытаемся определить через поиск по всем регистрам
        if isinstance(field, FieldInfo):
            # Если есть parent с registers_manager, ищем поле во всех регистрах
            if parent:
                registers_manager = self._get_registers_manager_from_parent(parent)
                if registers_manager:
                    register_name, field_name = self._find_field_in_registers(registers_manager, field)
                    if register_name and field_name:
                        return register_name, field_name
            
            # Пытаемся извлечь через inspect (анализ стека вызовов)
            try:
                frame = inspect.currentframe()
                # Идём на 2 уровня выше (вызов конструктора -> вызов _extract_from_field)
                if frame and frame.f_back and frame.f_back.f_back:
                    caller_frame = frame.f_back.f_back
                    # Ищем переменные в локальной области видимости вызывающего кода
                    caller_locals = caller_frame.f_locals
                    # Ищем модели регистров
                    for name, value in caller_locals.items():
                        if hasattr(value, 'model_fields') and isinstance(value, type):
                            if field in value.model_fields.values():
                                register_name = self._get_register_name_from_model(value)
                                # Находим имя поля
                                for field_name, field_info in value.model_fields.items():
                                    if field_info is field:
                                        return register_name, field_name
            except Exception:
                pass
        
        # Если это FieldInfo - пытаемся извлечь через атрибуты
        if hasattr(field, '__qualname__'):
            qualname = field.__qualname__
            if '.' in qualname:
                parts = qualname.split('.')
                if len(parts) >= 2:
                    model_name = parts[-2]  # Предпоследняя часть - имя модели
                    field_name = parts[-1]  # Последняя часть - имя поля
                    register_name = self._normalize_register_name(model_name)
                    return register_name, field_name
        
        # Если это FieldInfo без qualname, пытаемся через __name__
        if hasattr(field, '__name__'):
            field_name = field.__name__
            # Не можем определить модель без дополнительной информации
            return None, field_name
        
        return None, None
    
    def _find_field_in_registers(self, registers_manager: Any, field: FieldInfo) -> tuple[Optional[str], Optional[str]]:
        """
        Найти поле FieldInfo во всех регистрах RegistersManager.
        
        Args:
            registers_manager: Экземпляр RegistersManager
            field: FieldInfo для поиска
        
        Returns:
            tuple: (register_name, field_name) или (None, None) если не найдено
        """
        register_names = [
            'camera', 'processing', 'post_processing', 'visual',
            'draw', 'robot', 'conveyor', 'neuroun', 'hikvision', 'frame_process'
        ]
        
        for register_name in register_names:
            register = registers_manager.get_register(register_name)
            if register and hasattr(register, 'model_fields'):
                for field_name, field_info in register.model_fields.items():
                    if field_info is field:
                        return register_name, field_name
        
        return None, None
    
    def _get_register_name_from_model(self, model_class: Any) -> Optional[str]:
        """Получить имя регистра из класса модели"""
        if model_class is None:
            return None
        
        # Маппинг классов моделей на имена регистров
        model_to_register = {
            'CameraRegisters': 'camera',
            'ProcessingRegisters': 'processing',
            'PostProcessingRegisters': 'post_processing',
            'VisualRegisters': 'visual',
            'DrawRegisters': 'draw',
            'RobotRegisters': 'robot',
            'ConveyorRegisters': 'conveyor',
            'NeurounRegisters': 'neuroun',
            'HikvisionRegisters': 'hikvision',
            'FrameProcessRegisters': 'frame_process',
        }
        
        model_name = model_class.__name__ if hasattr(model_class, '__name__') else str(model_class)
        return model_to_register.get(model_name)
    
    def _normalize_register_name(self, model_name: str) -> str:
        """Нормализовать имя модели к имени регистра"""
        model_to_register = {
            'CameraRegisters': 'camera',
            'ProcessingRegisters': 'processing',
            'PostProcessingRegisters': 'post_processing',
            'VisualRegisters': 'visual',
            'DrawRegisters': 'draw',
            'RobotRegisters': 'robot',
            'ConveyorRegisters': 'conveyor',
            'NeurounRegisters': 'neuroun',
            'HikvisionRegisters': 'hikvision',
            'FrameProcessRegisters': 'frame_process',
        }
        return model_to_register.get(model_name, model_name.lower().replace('_registers', ''))
    
    def _get_registers_manager_from_parent(self, parent: QWidget) -> Optional[Any]:
        """Попытаться получить RegistersManager из parent (если это MainWindow)"""
        if hasattr(parent, 'registers_manager'):
            return parent.registers_manager
        # Проверяем родительские виджеты
        current = parent
        for _ in range(5):  # Максимум 5 уровней вверх
            if hasattr(current, 'registers_manager'):
                return current.registers_manager
            if hasattr(current, 'parent'):
                current = current.parent()
            else:
                break
        return None
    
    def _get_access_level_from_parent(self, parent: QWidget) -> int:
        """Попытаться получить access_level из parent (если это MainWindow)"""
        if hasattr(parent, 'access_level'):
            return parent.access_level
        # Проверяем родительские виджеты
        current = parent
        for _ in range(5):  # Максимум 5 уровней вверх
            if hasattr(current, 'access_level'):
                return current.access_level
            if hasattr(current, 'parent'):
                current = current.parent()
            else:
                break
        return 0
    
    @property
    def register_name(self) -> Optional[str]:
        """Имя регистра (можно определить автоматически из field_name)"""
        return self._register_name
    
    @register_name.setter
    def register_name(self, value: str):
        """Установить имя регистра и применить конфигурацию"""
        if value != self._register_name:
            self._register_name = value
            self._apply_configuration()
    
    @property
    def field_name(self) -> Optional[str]:
        """Имя поля (может быть в формате 'register.field' для автоопределения)"""
        return self._field_name
    
    @field_name.setter
    def field_name(self, value: str):
        """Установить имя поля и применить конфигурацию"""
        if value != self._field_name:
            # Проверяем формат 'register.field' для автоматического определения
            if '.' in value and not self._register_name:
                parts = value.split('.', 1)
                if len(parts) == 2:
                    self._register_name = parts[0]
                    self._field_name = parts[1]
                else:
                    self._field_name = value
            else:
                self._field_name = value
            
            # Пытаемся автоматически определить register_name если не указан
            if not self._register_name:
                self._auto_detect_register()
            
            self._apply_configuration()
    
    @property
    def registers_manager(self) -> Optional[Any]:
        """Экземпляр RegistersManager"""
        return self._registers_manager
    
    @registers_manager.setter
    def registers_manager(self, value: Any):
        """Установить RegistersManager и применить конфигурацию"""
        if value != self._registers_manager:
            self._registers_manager = value
            self._apply_configuration()
    
    @property
    def access_level(self) -> int:
        """Уровень доступа пользователя"""
        return self._access_level
    
    @access_level.setter
    def access_level(self, value: int):
        """Установить уровень доступа и обновить UI"""
        if value != self._access_level:
            self._access_level = value
            if self._is_initialized:
                self._update_access_level()
    
    def _auto_detect_register(self):
        """
        Автоматически определить register_name по field_name.
        Ищет поле во всех доступных регистрах.
        """
        if not self._registers_manager or not self._field_name:
            return
        
        # Список всех регистров для поиска
        register_names = [
            'camera', 'processing', 'post_processing', 'visual',
            'draw', 'robot', 'conveyor', 'neuroun', 'hikvision', 'frame_process'
        ]
        
        for reg_name in register_names:
            register = self._registers_manager.get_register(reg_name)
            if register and hasattr(register, self._field_name):
                # Проверяем что поле действительно существует в модели
                if self._field_name in register.model_fields:
                    self._register_name = reg_name
                    return
    
    def _apply_configuration(self):
        """
        Применить конфигурацию при изменении свойств.
        Вызывается автоматически при изменении register_name, field_name или registers_manager.
        Должен быть переопределён в дочерних классах.
        """
        if not self._registers_manager or not self._register_name or not self._field_name:
            return
        
        # Проверяем что поле существует
        metadata = self._registers_manager.get_field_metadata(self._register_name, self._field_name)
        if not metadata:
            # Пытаемся автоматически определить register_name
            self._auto_detect_register()
            if not self._register_name:
                return
        
        # Вызываем метод загрузки метаданных (должен быть переопределён)
        if not self._is_initialized:
            self._load_metadata()
            self._is_initialized = True
        else:
            self._reload_metadata()
    
    def _load_metadata(self):
        """
        Загрузить метаданные и инициализировать виджет.
        Должен быть переопределён в дочерних классах.
        """
        pass
    
    def _reload_metadata(self):
        """
        Перезагрузить метаданные при изменении конфигурации.
        Должен быть переопределён в дочерних классах.
        """
        self._load_metadata()
    
    def _update_access_level(self):
        """
        Обновить UI при изменении уровня доступа.
        Должен быть переопределён в дочерних классах.
        """
        pass
    
    def get_metadata(self) -> dict:
        """
        Получить метаданные текущего поля.
        
        Returns:
            dict: Метаданные поля или пустой словарь
        """
        if not self._registers_manager or not self._register_name or not self._field_name:
            return {}
        
        return self._registers_manager.get_field_metadata(self._register_name, self._field_name)
    
    def get_field_value(self) -> Any:
        """
        Получить текущее значение поля из регистра.
        
        Returns:
            Текущее значение поля или None
        """
        if not self._registers_manager or not self._register_name or not self._field_name:
            return None
        
        register = self._registers_manager.get_register(self._register_name)
        if not register:
            return None
        field_obj = getattr(register, self._field_name, None)
        if field_obj is not None and hasattr(field_obj, "value"):
            return field_obj.value
        return field_obj
    
    def set_field_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Установить значение поля в регистре с валидацией.
        
        Args:
            value: Значение для установки
            
        Returns:
            tuple: (success: bool, error_message: Optional[str])
        """
        if not self._registers_manager or not self._register_name or not self._field_name:
            return False, "Конфигурация не завершена"
        
        # Валидация
        is_valid, error = self._registers_manager.validate_field_value(
            self._register_name, self._field_name, value, self._access_level
        )
        
        if not is_valid:
            return False, error
        
        # Проверка прав
        if not self._registers_manager.can_modify_field(
            self._register_name, self._field_name, self._access_level
        ):
            return False, "Недостаточно прав доступа"
        
        # Установка значения (поддержка полей-объектов с .value и примитивов)
        register = self._registers_manager.get_register(self._register_name)
        if not register:
            return False, "Регистр не найден"
        field_obj = getattr(register, self._field_name, None)
        if field_obj is not None and hasattr(field_obj, "value"):
            field_obj.value = value
        else:
            setattr(register, self._field_name, value)
        return True, None
