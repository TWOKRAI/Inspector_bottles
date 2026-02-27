# Использование метаданных полей в компонентах

## Обзор

Все компоненты приложения могут использовать метаданные полей из Pydantic моделей через `RegistersManager`. Это включает:
- **Описания** параметров (для таблиц и подсказок)
- **Диапазоны** значений (min/max для валидации и UI слайдеров)
- **Уровни доступа** (для ограничения редактирования)
- **Единицы измерения** (unit)
- **Примеры** значений
- **Флаги** (readonly, hidden)

## Пример модели с расширенными метаданными

```python
from pydantic import BaseModel, Field

class ProcessingRegisters(BaseModel):
    """Регистры обработки изображений"""
    
    crop_top: int = Field(
        default=0,
        description='Обрезка сверху',
        json_schema_extra={
            'info': 'Координата верхней границы области обрезки изображения в пикселях',
            'unit': 'px',
            'min': 0,
            'max': 10000,
            'range': '0-10000',
            'access_level': 0,  # Доступно всем
            'examples': [0, 100, 500]
        }
    )
    
    hl: int = Field(
        default=0,
        description='Hue нижний',
        json_schema_extra={
            'info': 'Нижняя граница диапазона Hue для цветовой фильтрации',
            'unit': '',
            'min': 0,
            'max': 179,
            'range': '0-179',
            'access_level': 0,
            'examples': [0, 50, 100]
        }
    )
    
    # Параметр только для администраторов
    advanced_processing_mode: bool = Field(
        default=False,
        description='Расширенный режим обработки',
        json_schema_extra={
            'info': 'Включает расширенные алгоритмы обработки. Доступно только администраторам.',
            'access_level': 1,  # Требуется уровень администратора
            'examples': [False, True]
        }
    )
    
    # Скрытый параметр (только для разработчиков)
    debug_mode: bool = Field(
        default=False,
        description='Режим отладки',
        json_schema_extra={
            'info': 'Включает детальное логирование для отладки',
            'access_level': 2,  # Требуется уровень разработчика
            'hidden': True,  # Скрыт в обычном UI
            'examples': [False, True]
        }
    )
    
    # Только для чтения параметр
    image_width: int = Field(
        default=1024,
        description='Ширина изображения',
        json_schema_extra={
            'info': 'Ширина обрабатываемого изображения (только для чтения)',
            'unit': 'px',
            'readonly': True,  # Нельзя изменять через UI
            'access_level': 0
        }
    )
```

## Использование в компонентах

### 1. Таблица параметров (SortWidget)

```python
from App.Registers import RegistersManager

class SortWidget(QWidget):
    def __init__(self, registers_manager: RegistersManager, access_level: int = 0):
        self.registers_manager = registers_manager
        self.access_level = access_level
        
    def populate_table(self):
        # Получаем все метаданные для текущего уровня доступа
        all_metadata = self.registers_manager.get_all_fields_metadata(
            access_level=self.access_level
        )
        
        for field_key, metadata in all_metadata.items():
            # Проверяем, можно ли редактировать
            can_edit = self.registers_manager.can_modify_field(
                *field_key.split('.', 1),
                access_level=self.access_level
            )
            
            # Получаем описание
            description = metadata.get('info') or metadata.get('description', '')
            
            # Получаем диапазон для отображения
            min_val = metadata.get('min')
            max_val = metadata.get('max')
            range_str = metadata.get('range', '')
            
            # Добавляем строку в таблицу
            row = QTreeWidgetItem(self.tree)
            row.setText(0, field_key)
            row.setText(1, description)
            row.setText(2, f"{range_str} {metadata.get('unit', '')}".strip())
            
            # Делаем редактируемым только если есть права
            if not can_edit:
                row.setFlags(row.flags() & ~Qt.ItemIsEditable)
```

### 2. Слайдер (SliderControl)

```python
from App.Registers import RegistersManager

class SliderControl(QWidget):
    def __init__(self, register_name: str, field_name: str, 
                 registers_manager: RegistersManager, access_level: int = 0):
        self.registers_manager = registers_manager
        self.register_name = register_name
        self.field_name = field_name
        self.access_level = access_level
        
        # Получаем метаданные
        metadata = self.registers_manager.get_field_metadata(register_name, field_name)
        
        # Настраиваем слайдер на основе метаданных
        min_val = metadata.get('min', 0)
        max_val = metadata.get('max', 100)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        
        # Проверяем права на редактирование
        if not self.registers_manager.can_modify_field(
            register_name, field_name, access_level
        ):
            self.slider.setEnabled(False)
        
        # Подсказка с описанием
        tooltip = metadata.get('info', '')
        if metadata.get('unit'):
            tooltip += f" ({metadata.get('unit')})"
        self.slider.setToolTip(tooltip)
        
    def set_value(self, value: int):
        # Валидация перед установкой значения
        is_valid, error = self.registers_manager.validate_field_value(
            self.register_name, self.field_name, value, self.access_level
        )
        
        if not is_valid:
            QMessageBox.warning(self, "Ошибка валидации", error)
            return
        
        self.slider.setValue(value)
```

### 3. Форма редактирования параметров

```python
from App.Registers import RegistersManager

class ParameterEditForm(QWidget):
    def __init__(self, register_name: str, registers_manager: RegistersManager, 
                 access_level: int = 0):
        self.registers_manager = registers_manager
        self.register_name = register_name
        self.access_level = access_level
        
        # Получаем все поля регистра для текущего уровня доступа
        fields = self.registers_manager.get_fields_for_access_level(
            register_name, access_level
        )
        
        layout = QFormLayout()
        
        for field_name, metadata in fields.items():
            # Пропускаем скрытые поля
            if metadata.get('hidden', False):
                continue
            
            # Создаём виджет в зависимости от типа
            widget = self._create_widget(field_name, metadata)
            
            # Проверяем права на редактирование
            if not self.registers_manager.can_modify_field(
                register_name, field_name, access_level
            ):
                widget.setEnabled(False)
            
            # Добавляем в форму
            label = f"{field_name}"
            if metadata.get('unit'):
                label += f" ({metadata.get('unit')})"
            layout.addRow(label, widget)
            
            # Подсказка
            tooltip = metadata.get('info', '')
            widget.setToolTip(tooltip)
    
    def _create_widget(self, field_name: str, metadata: Dict[str, Any]):
        # Определяем тип виджета на основе метаданных
        if metadata.get('readonly', False):
            widget = QLabel()
            widget.setEnabled(False)
        elif metadata.get('min') is not None and metadata.get('max') is not None:
            # Числовой диапазон - слайдер
            widget = QSlider(Qt.Horizontal)
            widget.setMinimum(metadata['min'])
            widget.setMaximum(metadata['max'])
        else:
            # Обычное поле ввода
            widget = QLineEdit()
        
        return widget
```

### 4. Валидация при изменении значения

```python
def on_parameter_changed(self, register_name: str, field_name: str, new_value: Any):
    """Обработчик изменения параметра"""
    
    # Валидация значения
    is_valid, error = self.registers_manager.validate_field_value(
        register_name, field_name, new_value, self.access_level
    )
    
    if not is_valid:
        QMessageBox.warning(self, "Ошибка валидации", error)
        return False
    
    # Проверка прав на изменение
    if not self.registers_manager.can_modify_field(
        register_name, field_name, self.access_level
    ):
        QMessageBox.warning(self, "Доступ запрещён", 
                           "У вас нет прав на изменение этого параметра")
        return False
    
    # Применяем изменение
    register = self.registers_manager.get_register(register_name)
    setattr(register, field_name, new_value)
    
    return True
```

## Уровни доступа

### Определение уровней доступа

- **0** - Обычный пользователь (оператор)
  - Может изменять базовые параметры
  - Не может изменять критичные настройки
  
- **1** - Администратор
  - Может изменять все параметры, включая расширенные
  - Может изменять метаданные (диапазоны, уровни доступа)
  
- **2** - Разработчик
  - Полный доступ, включая скрытые параметры
  - Может изменять все метаданные

### Пример использования уровней доступа

```python
# В MainWindow
class MainWindow(QMainWindow):
    def __init__(self):
        self.registers_manager = RegistersManager()
        self.access_level = 0  # Текущий уровень доступа пользователя
        
    def login_as_admin(self):
        """Вход как администратор"""
        self.access_level = 1
        self.refresh_ui()  # Обновить UI с учётом новых прав
        
    def refresh_ui(self):
        """Обновить UI с учётом текущего уровня доступа"""
        # Получаем все доступные поля
        all_fields = self.registers_manager.get_all_fields_metadata(
            access_level=self.access_level
        )
        
        # Обновляем виджеты
        for widget in self.parameter_widgets:
            widget.update_access_level(self.access_level)
```

## Изменение метаданных (только для администраторов)

```python
def update_parameter_range(self, register_name: str, field_name: str, 
                          min_val: int, max_val: int):
    """Обновить диапазон параметра (требует администраторский доступ)"""
    
    if self.access_level < 1:
        QMessageBox.warning(self, "Доступ запрещён", 
                           "Требуется администраторский уровень доступа")
        return
    
    # Обновляем метаданные
    success, error = self.registers_manager.update_field_metadata(
        register_name, field_name,
        {'min': min_val, 'max': max_val, 'range': f'{min_val}-{max_val}'},
        access_level=self.access_level
    )
    
    if success:
        QMessageBox.information(self, "Успех", "Диапазон параметра обновлён")
        self.refresh_ui()  # Обновить UI
    else:
        QMessageBox.warning(self, "Ошибка", error)
```

## Динамическое изменение диапазонов

### Пример: изменение диапазона на основе размера изображения

```python
def update_crop_range_based_on_image_size(self, image_width: int, image_height: int):
    """Обновить диапазоны обрезки на основе размера изображения"""
    
    if self.access_level < 1:
        return
    
    # Обновляем диапазоны для crop параметров
    updates = {
        'crop_left': {'min': 0, 'max': image_width, 'range': f'0-{image_width}'},
        'crop_right': {'min': 0, 'max': image_width, 'range': f'0-{image_width}'},
        'crop_top': {'min': 0, 'max': image_height, 'range': f'0-{image_height}'},
        'crop_bottom': {'min': 0, 'max': image_height, 'range': f'0-{image_height}'},
    }
    
    for field_name, metadata_updates in updates.items():
        self.registers_manager.update_field_metadata(
            'processing', field_name, metadata_updates, 
            access_level=self.access_level
        )
    
    # Обновляем UI
    self.refresh_ui()
```

## Интеграция с RecipeManager

`RecipeManager` автоматически использует метаданные из `RegistersManager`:

```python
# RecipeManager уже использует RegistersManager для получения описаний
recipe_manager = RecipeManager(registers_manager=registers_manager)

# При получении описания параметра используется единый источник истины
info = recipe_manager.get_parameter_info('processing.crop_top')
# Вернёт описание из json_schema_extra['info'] модели ProcessingRegisters
```

## Рекомендации

1. **Всегда используйте RegistersManager** для получения метаданных
2. **Проверяйте права доступа** перед изменением значений
3. **Валидируйте значения** перед применением
4. **Используйте единый источник истины** - метаданные в Pydantic моделях
5. **Сохраняйте динамические изменения** метаданных в отдельный файл конфигурации (для будущей реализации)

## Настройка через свойства (Property-based Configuration)

### Базовый класс ConfigurableWidget

Все компоненты могут наследоваться от `ConfigurableWidget` для поддержки настройки через свойства:

```python
from App.Core.base_configurable_widget import ConfigurableWidget

class MyWidget(ConfigurableWidget):
    def _load_metadata(self):
        """Загрузить метаданные и инициализировать виджет"""
        metadata = self.get_metadata()
        # Используем метаданные для настройки UI
```

### Использование свойств

#### Вариант 1: Через конструктор (как раньше)
```python
slider = SliderControlEnhanced(
    register_name='draw',
    field_name='dp',
    registers_manager=registers_manager,
    access_level=0,
    parent=self
)
```

#### Вариант 2: Через свойства (новый способ)
```python
slider = SliderControlEnhanced(registers_manager=rm, parent=self)
slider.register_name = 'draw'
slider.field_name = 'dp'  # Автоматически применяется конфигурация
slider.access_level = 1
# UI автоматически обновляется при изменении свойств
```

#### Вариант 3: Автоматическое определение register_name
```python
slider = SliderControlEnhanced(registers_manager=rm, parent=self)
slider.field_name = 'draw.dp'  # Автоматически парсит 'draw.dp' -> register='draw', field='dp'
```

### Доступные свойства

- `register_name` - Имя регистра (например, 'draw', 'processing')
- `field_name` - Имя поля (например, 'dp', 'crop_top') или 'register.field' для автоопределения
- `registers_manager` - Экземпляр RegistersManager
- `access_level` - Уровень доступа пользователя (0 = обычный, 1+ = администратор)

### Автоматическое применение конфигурации

При изменении любого свойства автоматически вызывается `_apply_configuration()`, который:
1. Загружает метаданные из RegistersManager
2. Вызывает `_load_metadata()` для инициализации UI
3. Обновляет все элементы интерфейса

## Интернационализация (i18n)

### Структура метаданных с переводами

```python
json_schema_extra={
    'info': 'Обратное разрешение аккумулятора',  # По умолчанию (русский)
    'info_i18n': {
        'ru': 'Обратное разрешение аккумулятора для детектора кругов',
        'en': 'Inverse accumulator resolution for circle detector',
        'de': 'Inverse Akkumulatorauflösung für Kreiserkennung'
    },
    'description_i18n': {
        'ru': 'Обратное разрешение аккумулятора',
        'en': 'Inverse accumulator resolution',
        'de': 'Inverse Akkumulatorauflösung'
    },
    # ... остальные метаданные
}
```

### TranslationManager

```python
from App.Core.Managers.translation_manager import TranslationManager

# Создание менеджера переводов
translation_manager = TranslationManager(
    default_language='ru',
    translations_path='App/Data/Translations'  # Опционально: путь к файлам переводов
)

# Установка языка
translation_manager.set_language('en')

# Перевод из метаданных
metadata = registers_manager.get_field_metadata('draw', 'dp', language='en')
info = translation_manager.translate_metadata(metadata, field='info')
```

### Интеграция с RegistersManager

```python
# Создание RegistersManager с TranslationManager
translation_manager = TranslationManager(default_language='ru')
registers_manager = RegistersManager(translation_manager=translation_manager)

# Получение описания с учётом языка
description = registers_manager.get_field_description(
    'draw', 'dp', language='en'
)

# Получение метаданных с переводами
metadata = registers_manager.get_field_metadata(
    'draw', 'dp', language='en'
)
```

### Файлы переводов

Поддерживаются файлы переводов в формате JSON или YAML:

**translations.json:**
```json
{
    "draw.dp.info": {
        "ru": "Обратное разрешение аккумулятора",
        "en": "Inverse accumulator resolution",
        "de": "Inverse Akkumulatorauflösung"
    }
}
```

**translations.yaml:**
```yaml
draw.dp.info:
  ru: "Обратное разрешение аккумулятора"
  en: "Inverse accumulator resolution"
  de: "Inverse Akkumulatorauflösung"
```

### Использование в компонентах

```python
class MyWidget(ConfigurableWidget):
    def __init__(self, translation_manager=None, ...):
        super().__init__(...)
        self.translation_manager = translation_manager
    
    def _load_metadata(self):
        metadata = self.get_metadata()
        
        # Получаем перевод через TranslationManager
        if self.translation_manager:
            description = self.translation_manager.translate_metadata(
                metadata, field='info'
            )
        else:
            description = metadata.get('info', '')
        
        # Используем переведённое описание
        self.label.setText(description)
```

### Автоматическое обновление при смене языка

```python
# Подключение к сигналу изменения языка
translation_manager.language_changed.connect(self.on_language_changed)

def on_language_changed(self, language: str):
    """Обновить все компоненты при смене языка"""
    # Перезагружаем метаданные с новым языком
    self._reload_metadata()
```

## Примеры комбинированного использования

### Пример 1: Слайдер с свойствами и i18n

```python
# Создание менеджеров
translation_manager = TranslationManager(default_language='ru')
registers_manager = RegistersManager(translation_manager=translation_manager)

# Создание слайдера через свойства
slider = SliderControlEnhanced(
    registers_manager=registers_manager,
    parent=self
)
slider.field_name = 'draw.dp'  # Автоматически определяет register='draw'
slider.access_level = 1

# Смена языка
translation_manager.set_language('en')
# Слайдер автоматически обновляется с переведёнными метками
```

### Пример 2: Динамическое изменение конфигурации

```python
slider = SliderControlEnhanced(registers_manager=rm, parent=self)

# Начальная конфигурация
slider.register_name = 'draw'
slider.field_name = 'dp'

# Изменение на другой параметр
slider.field_name = 'minDist'  # Автоматически применяется новая конфигурация

# Изменение уровня доступа
slider.access_level = 0  # UI автоматически обновляется
```

## Будущие улучшения

- Сохранение динамических метаданных в `App/Data/Registers/metadata_overrides.yaml`
- Синхронизация метаданных с Backend через API
- Автоматическая генерация UI форм на основе метаданных
- Визуальный редактор метаданных для администраторов
- Расширенная поддержка i18n для всех компонентов UI
