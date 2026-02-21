# -*- coding: utf-8 -*-
"""
Улучшенный SliderControl с поддержкой метаданных из RegistersManager.
Упрощает создание слайдеров, автоматически получая min, max, default, описание из моделей.
Поддерживает настройку через свойства благодаря наследованию от ConfigurableWidget.
"""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel, QSlider, QMessageBox
from PyQt5.QtGui import QFont, QIntValidator, QDoubleValidator
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from typing import Optional, Any

from App.Components.keyboard_mini import VirtualKeyboardMini
from App.Components.base_configurable_widget import ConfigurableWidget


class SliderControlEnhanced(ConfigurableWidget):
    """
    Улучшенный SliderControl с автоматической настройкой из метаданных RegistersManager.
    Поддерживает настройку через свойства благодаря наследованию от ConfigurableWidget.
    
    Пример использования:
        # Вариант 1: Через конструктор (как раньше)
        slider = SliderControlEnhanced(
            register_name='draw',
            field_name='dp',
            registers_manager=registers_manager,
            access_level=0,
            ui_elements=ui_elements,
            controls=controls,
            callback=update_callback,
            parent=self
        )
        
        # Вариант 2: Через свойства (новый способ)
        slider = SliderControlEnhanced(registers_manager=rm, parent=self)
        slider.register_name = 'draw'
        slider.field_name = 'dp'  # Автоматически применяется конфигурация
        
        # Вариант 3: Автоматическое определение
        slider = SliderControlEnhanced(registers_manager=rm, parent=self)
        slider.field_name = 'draw.dp'  # Автоматически парсит
    """
    
    def __init__(self, register_name: Optional[str] = None,
                 field_name: Optional[str] = None,
                 field: Optional[Any] = None,  # Может быть FieldInfo (например, DrawRegisters.dp)
                 registers_manager: Optional[Any] = None,
                 access_level: int = 0,
                 ui_elements: Optional[dict] = None,
                 controls: Optional[dict] = None,
                 callback: Optional[callable] = None,
                 parent: Optional[QWidget] = None,
                 label: Optional[str] = None,
                 transfer_k: Optional[float] = None,
                 round_k: Optional[int] = None):
        """
        Args:
            register_name: Имя регистра (например, 'draw', 'processing') или None для автоопределения
            field_name: Имя поля (например, 'dp', 'crop_top') или 'register.field' для автоопределения
            field: Поле модели (например, DrawRegisters.dp) - автоматически определяет register_name и field_name
            registers_manager: Экземпляр RegistersManager (автоматически определяется из parent если не указан)
            access_level: Уровень доступа пользователя (автоматически определяется из parent если не указан)
            ui_elements: Словарь для хранения UI элементов (автоматически определяется из parent если не указан)
            controls: Словарь для хранения значений (автоматически определяется из parent если не указан)
            callback: Функция обратного вызова при изменении значения (автоматически определяется из parent если не указан)
            parent: Родительский виджет (может быть MainWindow для автоматического определения параметров)
            label: Текст метки (если не указан, используется описание из метаданных)
            transfer_k: Коэффициент преобразования (если не указан, определяется из метаданных или автоматически)
            round_k: Количество знаков после запятой (если не указан, определяется из метаданных или автоматически)
        """
        # Автоматическое определение параметров из parent (если это MainWindow)
        if parent:
            if ui_elements is None and hasattr(parent, 'ui_elements'):
                ui_elements = parent.ui_elements
            if controls is None and hasattr(parent, 'controls'):
                controls = parent.controls
            if callback is None and hasattr(parent, 'update_controls'):
                callback = parent.update_controls
        
        # Вызываем конструктор базового класса
        super().__init__(
            register_name=register_name,
            field_name=field_name,
            field=field,
            registers_manager=registers_manager,
            access_level=access_level,
            parent=parent
        )
        
        # Дополнительные параметры
        self.ui_elements = ui_elements
        self.controls = controls
        self.func_update = callback
        self.custom_label = label
        self.transfer_k = transfer_k
        self.round_k = round_k
        
        # UI элементы (будут созданы в _load_metadata)
        self.label = None
        self.value_input = None
        self.slider = None
        self.hbox = None
        self.block = False
        
        # Если конфигурация уже задана, загружаем метаданные
        if self._register_name and self._field_name and self._registers_manager:
            self._load_metadata()
            self._is_initialized = True
    
    def transfer_value(self, value):
        """Преобразование значения слайдера"""
        value_k = value * self.transfer_k
        rounded = round(value_k, self.round_k)
        return int(rounded) if self.round_k == 0 else rounded
    
    def update_slider_value(self, value):
        """Обновление значения из слайдера"""
        self.value = self.transfer_value(value)
        self.value_input.setText(str(self.value))
        
        if not self.block:
            self.block = True
            QTimer.singleShot(100, self.onTimeout)
    
    def _load_metadata(self):
        """Загрузить метаданные и инициализировать виджет"""
        if not self._registers_manager or not self._register_name or not self._field_name:
            return
        
        # Получаем метаданные из RegistersManager
        metadata = self._registers_manager.get_field_metadata(self._register_name, self._field_name)
        
        if not metadata:
            raise ValueError(f"Поле {self._register_name}.{self._field_name} не найдено в RegistersManager")
        
        # Извлекаем значения из метаданных
        min_val = metadata.get('min', 0)
        max_val = metadata.get('max', 100)
        default_val = metadata.get('default', 0)
        description = metadata.get('info') or metadata.get('description', self._field_name)
        unit = metadata.get('unit', '')
        
        # Определяем transfer_k и round_k если не указаны (приоритет: метаданные > автоматическое определение)
        if self.transfer_k is None:
            # Сначала проверяем метаданные
            self.transfer_k = metadata.get('transfer_k', 1.0)
        
        if self.round_k is None:
            # Сначала проверяем метаданные
            self.round_k = metadata.get('round_k')
            if self.round_k is None:
                # Автоматическое определение по типу
                if isinstance(default_val, float):
                    self.round_k = 1
                else:
                    self.round_k = 0
        
        # Проверяем права доступа
        can_modify = self._registers_manager.can_modify_field(
            self._register_name, self._field_name, self._access_level
        )
        
        # Получаем текущее значение из регистра
        current_val = self.get_field_value() or default_val
        
        # Инициализация компоновки (если ещё не создана)
        if self.hbox is None:
            self.hbox = QHBoxLayout(self)
        
        # Настройка шрифтов
        font = QFont("Arial", 11)
        
        # Метка с описанием
        if self.label is None:
            self.label = QLabel()
            self.label.setFont(font)
            self.label.setWordWrap(True)
            self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.hbox.addWidget(self.label, 3)
        
        display_label = self.custom_label if self.custom_label is not None else description
        if unit:
            display_label += f" ({unit})"
        self.label.setText(display_label)
        self.label.setToolTip(description)
        
        # Преобразуем значение
        self.value = self.transfer_value(current_val)
        
        # Поле ввода значения
        if self.value_input is None:
            self.value_input = QLineEdit()
            font.setPointSize(12)
            self.value_input.setFont(font)
            self.value_input.setFixedSize(60, 30)
            self.value_input.setAlignment(Qt.AlignCenter)
            self.value_input.editingFinished.connect(self.update_input_value)
            self.value_input.mousePressEvent = self.show_touch_keyboard
            self.hbox.addSpacing(5)
            self.hbox.addWidget(self.label, 3)
            self.hbox.addWidget(self.value_input)
            self.hbox.addSpacing(20)
        
        self.value_input.setText(str(self.value))
        self.value_input.setEnabled(can_modify)
        
        # Валидатор для поля ввода
        if self.round_k == 0:
            validator = QIntValidator()
        else:
            validator = QDoubleValidator()
            validator.setNotation(QDoubleValidator.StandardNotation)
        self.value_input.setValidator(validator)
        
        # Слайдер
        if self.slider is None:
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setMinimumHeight(45)
            self.slider.valueChanged.connect(self.update_slider_value)
            self.slider.wheelEvent = lambda event: None
            self.slider.setStyleSheet("""
                QSlider::handle:horizontal {
                    height: 50px;
                    width: 25px;
                    margin: -15px 0;
                    border: 2px solid #4682B4;
                    border-radius: 7px;
                    background: gray;
                }
            """)
            self.hbox.addWidget(self.slider, 17)
            self.hbox.addSpacing(25)
        
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(int(current_val / self.transfer_k) if self.transfer_k != 1 else current_val)
        self.slider.setEnabled(can_modify)
        
        # Обновление внешних элементов
        if self.ui_elements is not None:
            self.ui_elements[self._field_name] = {
                'element': self.slider,
                'value': self.value,
                'min_access': metadata.get('access_level', 0),
                'transfer_k': self.transfer_k,
                'round_k': self.round_k
            }
        
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self._field_name] = self.value
            else:
                self.controls[self._field_name] = self.value
    
    def _reload_metadata(self):
        """Перезагрузить метаданные при изменении конфигурации"""
        self._load_metadata()
    
    def _update_access_level(self):
        """Обновить UI при изменении уровня доступа"""
        if not self.slider or not self.value_input:
            return
        
        can_modify = self._registers_manager.can_modify_field(
            self._register_name, self._field_name, self._access_level
        )
        self.slider.setEnabled(can_modify)
        self.value_input.setEnabled(can_modify)
    
    def update_input_value(self):
        """Обновление значения из поля ввода с валидацией"""
        try:
            input_text = self.value_input.text()
            input_text = input_text.replace(',', '.')
            input_value = float(input_text)
            
            # Валидация через базовый класс
            is_valid, error = self.set_field_value(input_value)
            
            if not is_valid:
                # Восстанавливаем предыдущее значение при ошибке валидации
                self.value_input.setText(str(self.value))
                if error:
                    QMessageBox.warning(self, "Ошибка валидации", error)
                return
            
            slider_value = int(round(input_value / self.transfer_k))
            slider_value = max(self.slider.minimum(), min(slider_value, self.slider.maximum()))
            self.slider.setValue(slider_value)
            self.value = self.transfer_value(slider_value)
            
            self.update_external()
        except ValueError:
            self.value_input.setText(str(self.value))
    
    def onTimeout(self):
        """Таймаут для обновления внешних элементов"""
        self.update_external()
        self.block = False
    
    def update_external(self):
        """Обновление внешних элементов и регистра"""
        # Значение уже обновлено через set_field_value в update_input_value
        # Но обновляем для совместимости
        
        if self.ui_elements is not None and self._field_name:
            if self._field_name in self.ui_elements:
                self.ui_elements[self._field_name]['value'] = self.value
        
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    if self._field_name:
                        control[self._field_name] = self.value
            else:
                if self._field_name:
                    self.controls[self._field_name] = self.value
        
        if self.func_update is not None:
            if isinstance(self.func_update, list):
                for func in self.func_update:
                    func()
            else:
                self.func_update()
    
    def show_touch_keyboard(self, event):
        """Показ кастомной клавиатуры"""
        self.keyboard = VirtualKeyboardMini()
        self.keyboard.input = self.value_input
        self.keyboard.enter = self.update_input_value
        self.keyboard.show()
        self.keyboard.raise_()
        self.keyboard.activateWindow()
        super(QLineEdit, self.value_input).mousePressEvent(event)
