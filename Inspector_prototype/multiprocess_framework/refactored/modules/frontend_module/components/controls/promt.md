Промт для рефакторинга SliderControl и CheckboxControl
Контекст: исходные файлы
У нас есть два компонента с одинаковой структурой:
SliderControl (widget.py, value_mapping.py, legacy_sync.py, styles.py):
Числовое поле: QLabel + QLineEdit + QSlider
Логика: transfer_k, round_k, debounce при движении слайдера
Запись в регистр: отложенная (debounce) для слайдера, немедленная для поля ввода
Наследуется от BaseConfigurableWidget (получает RegistersManager, читает ResolvedMeta)
CheckboxControl (widget(1).py, layout_builder.py, styles(1).py):
Булево поле: QLabel + QCheckBox
Логика: immediate write, нет debounce, нет трансформации значений
Позиция метки: left/right/top/bottom через layout_builder.py
Общие проблемы исходного кода:
BaseConfigurableWidget — "божественный" класс, знает про всё
Магические getattr(parent, "ui_elements") и getattr(parent, "controls")
Дублирование: value_mapping.py только для слайдера, но логика transfer_k должна быть универсальной
legacy_sync.py — разбросан по методам, нет единой точки
View и Presenter смешаны: SliderControl одновременно рисует UI и пишет в регистр
Цель рефакторинга
Создать архитектуру Traits + Facade.

**Ключевой принцип — конструктор/сборщик (Composable Builder):**
Все компоненты проектируются как переиспользуемые «кубики», из которых можно собирать любые виджеты и новые контролы. Traits, View, Presenter — максимально универсальны и гибки. Добавление нового типа контрола (например, SpinBox, ComboBox, ColorPicker) должно сводиться к композиции существующих traits + новый View при необходимости, без дублирования логики. Архитектура допускает создание пользовательских композиций и расширение без изменения ядра.
Traits: переиспользуемые куски логики (SchemaTrait, SyncTrait, DebounceTrait, AccessTrait)
Presenter: композиция traits для конкретного типа данных (NumericPresenter, BooleanPresenter)
View: чистый Qt, только отрисовка (SliderView, CheckboxView)
Facade: простой API NumericControl.create() → QWidget
Сохранить интеграцию с data_schema (SchemaBase, FieldMeta, ResolvedMeta) и RegistersManager.
Структура результирующих файлов
plain
Copy
frontend_module/components/controls/
├── __init__.py                      # Экспорт NumericControl, BooleanControl, конфиги
│
├── facade/                          # Простой API для пользователя
│   ├── __init__.py
│   ├── numeric_control.py           # class NumericControl с методом create()
│   └── boolean_control.py           # class BooleanControl с методом create()
│
├── presenters/
│   ├── __init__.py
│   ├── traits/                      # Переиспользуемые behaviors
│   │   ├── __init__.py
│   │   ├── schema_trait.py          # Работа с ResolvedMeta из data_schema
│   │   ├── sync_trait.py            # Чтение/запись через RegisterAdapter
│   │   ├── debounce_trait.py        # Debounce логика (для слайдера)
│   │   └── access_trait.py          # Проверка access_level
│   │
│   ├── base_presenter.py            # Интерфейс/базовая логика для всех Presenter
│   ├── numeric_presenter.py         # Композиция traits для float (с debounce)
│   └── boolean_presenter.py         # Композиция traits для bool (без debounce)
│
├── views/                           # Чистый Qt, никаких схем
│   ├── __init__.py
│   ├── interfaces.py                # IControlView[T] Protocol
│   ├── slider_view.py               # QLabel + QLineEdit + QSlider
│   ├── spinbox_view.py              # Альтернатива слайдеру (опционально)
│   └── checkbox_view.py             # QLabel + QCheckBox с позиционированием
│
├── infrastructure/                  # Адаптеры и утилиты
│   ├── __init__.py
│   ├── register_adapter.py          # Мост к вашему RegistersManager
│   ├── value_transformer.py         # Transfer/round/clamp (из value_mapping.py)
│   ├── debouncer.py                 # Существующий debouncer (перенести)
│   ├── signal_utils.py              # RAII block_signals (контекстный менеджер)
│   └── legacy_sync.py               # Обертка для ui_elements/controls (опционально)
│
└── schemas/                         # Pydantic-схемы (сохраняем ваши SchemaBase)
    ├── __init__.py
    ├── binding_config.py            # register_name, field_name, access_level
    ├── numeric_view_config.py         # UI для числовых: view_type, ticks, label...
    └── checkbox_view_config.py        # UI для bool: position, label...
Детальные требования к каждому файлу
1. infrastructure/register_adapter.py
Задача: Инкапсулировать всё общение с RegistersManager и ResolvedMeta.
Python
Copy
class RegisterAdapter:
    def __init__(self, registers_manager: RegistersManager):
        self._rm = registers_manager
        self._subscribers: dict[tuple[str, str], list[Callable]] = {}
        
    def resolve_meta(self, register_name: str, field_name: str) -> ResolvedMeta:
        """Получить ResolvedMeta из вашей data_schema."""
        # Используйте существующий метод вашего RM
        return self._rm.resolve_field_meta(register_name, field_name)
        
    def read(self, register_name: str, field_name: str) -> Any:
        return self._rm.get_field_value(register_name, field_name)
        
    def write(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        """
        Возвращает (success, error_message).
        error_message — строка для показа пользователю или None.
        """
        return self._rm.set_field_value(register_name, field_name, value)
        
    def subscribe(self, register_name: str, field_name: str, callback: Callable[[Any], None]) -> None:
        """
        Подписка на изменения поля.
        Реализовать через существующий механизм RM или хранить callbacks.
        """
        key = (register_name, field_name)
        if key not in self._subscribers:
            self._subscribers[key] = []
            # Регистрируемся в RM один раз на поле
            self._rm.subscribe_field(register_name, field_name, 
                                   lambda v: self._notify(key, v))
        self._subscribers[key].append(callback)
        
    def _notify(self, key: tuple[str, str], value: Any) -> None:
        for cb in self._subscribers.get(key, []):
            cb(value)
2. infrastructure/value_transformer.py
Задача: Перенести логику из value_mapping.py, использовать ResolvedMeta.
Python
Copy
class ValueTransformer:
    """
    Трансформация значений на основе transfer_k, round_k из ResolvedMeta.
    """
    def __init__(self, meta: ResolvedMeta):
        self._transfer_k = meta.transfer_k if meta else 1.0
        self._round_k = meta.round_k if meta else 0
        self._min = getattr(meta, 'min_val', None)
        self._max = getattr(meta, 'max_val', None)
        
    def to_storage(self, ui_value: float) -> int | float:
        """UI → Регистр (с учетом transfer_k)."""
        v = float(ui_value) * self._transfer_k
        if self._round_k == 0:
            return int(round(v))
        return round(v, self._round_k)
        
    def to_ui(self, storage_value: int | float) -> float:
        """Регистр → UI."""
        if not self._transfer_k:
            return float(storage_value)
        return float(storage_value) / self._transfer_k
        
    def clamp_to_range(self, ui_value: float) -> float:
        """Ограничение диапазоном (в UI-координатах)."""
        if self._min is None or self._max is None:
            return ui_value
        ui_min = self.to_ui(self._min)
        ui_max = self.to_ui(self._max)
        return max(ui_min, min(ui_value, ui_max))
        
    def get_step(self) -> float:
        """Шаг для QSlider (в UI-координатах)."""
        return 1.0 / self._transfer_k if self._transfer_k else 1.0
3. infrastructure/signal_utils.py
Задача: RAII для блокировки сигналов (замена ручных try/finally).
Python
Copy
from contextlib import contextmanager
from typing import Union

@contextmanager
def block_signals(*widgets):
    """Блокирует сигналы всех виджетов в блоке, восстанавливает после."""
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)
4. presenters/traits/schema_trait.py
Задача: Инкапсулировать доступ к метаданным поля.
Python
Copy
from dataclasses import dataclass
from frontend_module.components.controls.infrastructure.register_adapter import RegisterAdapter
from frontend_module.components.controls.schemas.binding_config import BindingConfig
from data_schema_module import ResolvedMeta  # ваш импорт

@dataclass
class SchemaTrait:
    """Трейт: работа с ResolvedMeta из data_schema."""
    binding: BindingConfig
    adapter: RegisterAdapter
    
    def __post_init__(self):
        self._meta = self.adapter.resolve_meta(
            self.binding.register_name, 
            self.binding.field_name
        )
    
    @property
    def meta(self) -> ResolvedMeta:
        return self._meta
    
    @property
    def label(self) -> str:
        """Метка с учетом unit."""
        base = self._meta.label or self.binding.field_name
        if self._meta.unit:
            return f"{base} ({self._meta.unit})"
        return base
    
    @property
    def effective_access_level(self) -> int:
        """Максимум из конфига и метаданных."""
        meta_access = getattr(self._meta, 'access_level', 0)
        return max(self.binding.access_level, meta_access)
    
    @property
    def description(self) -> str:
        return getattr(self._meta, 'description', '')
5. presenters/traits/sync_trait.py
Задача: Инкапсулировать чтение/запись и подписку.
Python
Copy
from typing import Callable, Any, Optional

class SyncTrait:
    """Трейт: синхронизация с регистром."""
    
    def __init__(self, binding: BindingConfig, adapter: RegisterAdapter):
        self._binding = binding
        self._adapter = adapter
        
    def read(self) -> Any:
        return self._adapter.read(
            self._binding.register_name, 
            self._binding.field_name
        )
        
    def write(self, value: Any) -> tuple[bool, Optional[str]]:
        return self._adapter.write(
            self._binding.register_name,
            self._binding.field_name, 
            value
        )
        
    def subscribe(self, callback: Callable[[Any], None]) -> None:
        self._adapter.subscribe(
            self._binding.register_name,
            self._binding.field_name,
            callback
        )
6. presenters/traits/debounce_trait.py
Задача: Перенести существующий debouncer, адаптировать под trait.
Python
Copy
from typing import Callable, Optional

class DebounceTrait:
    """Трейт: отложенная запись (для слайдера)."""
    
    def __init__(self, ms: int = 300):
        self._ms = ms
        self._timer: Optional[QTimer] = None
        self._pending: Optional[Callable] = None
        
    def schedule(self, callback: Callable[[], None]) -> None:
        """Запланировать вызов callback через ms."""
        self.cancel()
        self._pending = callback
        # Используйте существующий механизм debounce из вашего кода
        # или создайте QTimer здесь
        
    def cancel(self) -> None:
        """Отменить отложенный вызов."""
        pass
        
    def flush(self) -> None:
        """Немедленно выполнить отложенный вызов."""
        if self._pending:
            self._pending()
            self._pending = None
7. presenters/traits/access_trait.py
Python
Copy
class AccessTrait:
    """Трейт: проверка прав доступа."""
    
    def __init__(self, required_level: int):
        self._required = required_level
        self._current = 0
        
    def update(self, current_level: int) -> None:
        self._current = current_level
        
    def can_modify(self) -> bool:
        return self._current >= self._required
8. views/interfaces.py
Python
Copy
from typing import Protocol, TypeVar, Callable

T = TypeVar('T')

class IControlView(Protocol[T]):
    """Контракт для всех View."""
    
    def setup(self, label: str, tooltip: str, enabled: bool) -> None: ...
    def set_value(self, value: T) -> None: ...           # с эмитом on_changed
    def set_value_silent(self, value: T) -> None: ...    # без эмита
    def get_value(self) -> T: ...
    def set_enabled(self, enabled: bool) -> None: ...
    def on_changed(self, callback: Callable[[T], None]) -> None: ...
    def on_finished(self, callback: Callable[[T], None]) -> None: ...
9. views/slider_view.py
Задача: Чистый Qt, перенести логику из widget.py и styles.py.
Python
Copy
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit, QSlider
from PyQt5.QtCore import Qt, pyqtSignal
from frontend_module.components.controls.infrastructure.signal_utils import block_signals

class SliderView(QWidget):
    """
    Чистый Qt: QLabel + QLineEdit + QSlider.
    Не знает про transfer_k, ResolvedMeta, RegistersManager.
    """
    # Внутренние сигналы для связи с Presenter
    _value_changing = pyqtSignal(float)   # движение слайдера
    _value_finished = pyqtSignal(float)   # Enter/LostFocus
    
    def __init__(self, show_ticks: bool = False, tick_interval: int = 10, parent=None):
        super().__init__(parent)
        
        self._label = QLabel()
        self._line_edit = QLineEdit()
        self._slider = QSlider(Qt.Horizontal)
        self._step = 1.0
        
        # Layout из styles.py
        layout = QHBoxLayout(self)
        layout.addWidget(self._label)
        layout.addSpacing(5)  # LAYOUT_SPACING_AFTER_LABEL_PX
        layout.addWidget(self._line_edit)
        layout.addSpacing(20)  # LAYOUT_SPACING_BEFORE_SLIDER_PX
        layout.addWidget(self._slider, 17)
        layout.addSpacing(25)  # LAYOUT_SPACING_AFTER_SLIDER_PX
        
        # Стили из styles.py
        self._slider.setMinimumHeight(45)
        self._slider.setStyleSheet("""
            QSlider::handle:horizontal {
                height: 50px; width: 25px; margin: -15px 0;
                border: 2px solid #4682B4; border-radius: 7px; background: gray;
            }
        """)
        
        if show_ticks:
            self._slider.setTickPosition(QSlider.TicksBelow)
            self._slider.setTickInterval(tick_interval)
            
        # Внутренние коннекты
        self._slider.valueChanged.connect(self._on_slider_moved)
        self._line_edit.editingFinished.connect(self._on_input_finished)
        
    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self._label.setText(label)
        self._label.setToolTip(tooltip)
        self.set_enabled(enabled)
        
    def set_range(self, min_val: float, max_val: float, step: float) -> None:
        """Диапазон в UI-координатах."""
        self._step = step
        self._slider.setMinimum(int(min_val / step))
        self._slider.setMaximum(int(max_val / step))
        
    def set_value(self, value: float) -> None:
        self._set_internal(value, emit=True)
        
    def set_value_silent(self, value: float) -> None:
        self._set_internal(value, emit=False)
        
    def _set_internal(self, value: float, emit: bool) -> None:
        slider_pos = int(value / self._step)
        
        with block_signals(self._slider, self._line_edit):
            self._slider.setValue(slider_pos)
            self._line_edit.setText(f"{value:.{self._get_decimals()}f}")
            
        if emit:
            self._value_changing.emit(value)
            
    def get_value(self) -> float:
        return float(self._line_edit.text().replace(",", "."))
        
    def set_enabled(self, enabled: bool) -> None:
        self._slider.setEnabled(enabled)
        self._line_edit.setEnabled(enabled)
        
    def on_changed(self, callback: Callable[[float], None]) -> None:
        """Движение слайдера или ввод в поле."""
        self._value_changing.connect(callback)
        
    def on_finished(self, callback: Callable[[float], None]) -> None:
        """Enter или завершение редактирования."""
        self._value_finished.connect(callback)
        
    def _on_slider_moved(self, position: int) -> None:
        value = position * self._step
        self._line_edit.setText(f"{value:.{self._get_decimals()}f}")
        self._value_changing.emit(value)
        
    def _on_input_finished(self) -> None:
        try:
            value = float(self._line_edit.text().replace(",", "."))
            self._value_finished.emit(value)
        except ValueError:
            # Возврат к слайдеру при ошибке
            self._on_slider_moved(self._slider.value())
            
    def _get_decimals(self) -> int:
        """Определение знаков по step."""
        step_str = str(self._step)
        if '.' in step_str:
            return len(step_str.split('.')[1].rstrip('0'))
        return 0
10. views/checkbox_view.py
Задача: Перенести из widget(1).py и layout_builder.py.
Python
Copy
from PyQt5.QtWidgets import QWidget, QCheckBox, QLabel, QHBoxLayout, QVBoxLayout
from PyQt5.QtCore import Qt
from typing import Literal, Callable
from frontend_module.components.controls.infrastructure.signal_utils import block_signals

Position = Literal["left", "right", "top", "bottom"]

class CheckboxView(QWidget):
    """QLabel + QCheckBox с настраиваемой позицией."""
    
    def __init__(self, position: Position = "left", parent=None):
        super().__init__(parent)
        self._position = position
        self._label = QLabel()
        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(44, 44)  # из styles(1).py
        
        self._build_layout()
        
    def _build_layout(self) -> None:
        # Логика из layout_builder.py
        if self._position in ("top", "bottom"):
            layout = QVBoxLayout(self)
            items = (self._label, self._checkbox) if self._position == "top" else (self._checkbox, self._label)
        else:
            layout = QHBoxLayout(self)
            items = (self._label, self._checkbox) if self._position == "left" else (self._checkbox, self._label)
            
        layout.setContentsMargins(4, 4, 4, 4)  # LAYOUT_CONTENT_MARGINS_PX
        layout.setSpacing(4)  # LAYOUT_SPACING_PX
        
        for w in items:
            layout.addWidget(w)
            
    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self._label.setText(label)
        self._label.setToolTip(tooltip)
        self.set_enabled(enabled)
        
    def set_value(self, value: bool) -> None:
        self._checkbox.setChecked(value)
        
    def set_value_silent(self, value: bool) -> None:
        with block_signals(self._checkbox):
            self._checkbox.setChecked(value)
            
    def get_value(self) -> bool:
        return self._checkbox.isChecked()
        
    def set_enabled(self, enabled: bool) -> None:
        self._checkbox.setEnabled(enabled)
        
    def on_changed(self, callback: Callable[[bool], None]) -> None:
        self._checkbox.stateChanged.connect(lambda state: callback(state == Qt.Checked))
        
    def on_finished(self, callback: Callable[[bool], None]) -> None:
        # Для чекбокса on_finished = on_changed (immediate)
        self.on_changed(callback)
11. presenters/numeric_presenter.py
Задача: Композиция traits для слайдера.
Python
Copy
from typing import Optional
from frontend_module.components.controls.presenters.traits import (
    SchemaTrait, SyncTrait, DebounceTrait, AccessTrait
)
from frontend_module.components.controls.infrastructure import (
    RegisterAdapter, ValueTransformer
)
from frontend_module.components.controls.schemas import BindingConfig, NumericViewConfig
from frontend_module.components.controls.views.interfaces import IControlView

class NumericPresenter:
    """
    Presenter для числовых полей.
    Композиция: Schema + Sync + Debounce + Access + ValueTransformer
    """
    
    def __init__(self, binding: BindingConfig, adapter: RegisterAdapter):
        # Трейты — явные зависимости
        self._schema = SchemaTrait(binding, adapter)
        self._sync = SyncTrait(binding, adapter)
        self._debounce = DebounceTrait(ms=300)  # как в исходном коде
        self._access = AccessTrait(self._schema.effective_access_level)
        self._transform = ValueTransformer(self._schema.meta)
        
        self._view: Optional[IControlView[float]] = None
        
    def attach_view(self, view: IControlView[float]) -> None:
        """Внедрение View."""
        self._view = view
        
        # Настройка из метаданных
        self._view.setup(
            label=self._schema.label,
            tooltip=self._schema.description,
            enabled=self._access.can_modify()
        )
        
        # Диапазон (в UI-координатах)
        self._view.set_range(
            min_val=self._transform.to_ui(self._schema.meta.min_val),
            max_val=self._transform.to_ui(self._schema.meta.max_val),
            step=self._transform.get_step()
        )
        
        # Подключение сигналов
        self._view.on_changed(self._on_changing)
        self._view.on_finished(self._on_finished)
        
        # Подписка на внешние изменения
        self._sync.subscribe(self._on_external_change)
        
        # Первичная загрузка
        self._sync_from_model()
        
    def _on_changing(self, ui_value: float) -> None:
        """Движение слайдера — с debounce."""
        if not self._access.can_modify():
            self._sync_from_model()
            return
            
        # Clamp и преобразование
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        
        # Debounce
        self._debounce.schedule(lambda: self._write(storage_value))
        
    def _on_finished(self, ui_value: float) -> None:
        """Enter/LostFocus — immediate, отменяем debounce."""
        self._debounce.cancel()
        
        if not self._access.can_modify():
            self._sync_from_model()
            return
            
        ui_value = self._transform.clamp_to_range(ui_value)
        storage_value = self._transform.to_storage(ui_value)
        self._write(storage_value)
        
    def _write(self, storage_value: float) -> None:
        ok, err = self._sync.write(storage_value)
        if not ok:
            # Откат к значению регистра
            self._sync_from_model()
            # TODO: показать ошибку через View (добавить метод show_error?)
        # Legacy sync здесь если нужно
        
    def _on_external_change(self, storage_value) -> None:
        """Изменение из другого места (через RegistersManager)."""
        ui_value = self._transform.to_ui(storage_value)
        self._view.set_value_silent(ui_value)
        
    def _sync_from_model(self) -> None:
        """Прочитать из регистра и обновить View."""
        current = self._sync.read()
        ui_value = self._transform.to_ui(current)
        self._view.set_value_silent(ui_value)
        
    def set_access_level(self, level: int) -> None:
        """Обновление прав доступа."""
        self._access.update(level)
        self._view.set_enabled(self._access.can_modify())
12. presenters/boolean_presenter.py
Задача: Проще, без debounce и трансформации.
Python
Copy
class BooleanPresenter:
    """Presenter для bool-полей. Без debounce, immediate write."""
    
    def __init__(self, binding: BindingConfig, adapter: RegisterAdapter):
        self._schema = SchemaTrait(binding, adapter)
        self._sync = SyncTrait(binding, adapter)
        self._access = AccessTrait(self._schema.effective_access_level)
        self._view: Optional[IControlView[bool]] = None
        
    def attach_view(self, view: IControlView[bool]) -> None:
        self._view = view
        
        self._view.setup(
            label=self._schema.label,
            tooltip=self._schema.description,
            enabled=self._access.can_modify()
        )
        
        # Нет set_range для чекбокса
        
        self._view.on_changed(self._on_changed)  # immediate
        self._sync.subscribe(self._on_external_change)
        self._sync_from_model()
        
    def _on_changed(self, value: bool) -> None:
        if not self._access.can_modify():
            self._sync_from_model()
            return
            
        ok, err = self._sync.write(value)
        if not ok:
            self._sync_from_model()
            
    def _on_external_change(self, value) -> None:
        self._view.set_value_silent(bool(value))
        
    def _sync_from_model(self) -> None:
        self._view.set_value_silent(bool(self._sync.read()))
        
    def set_access_level(self, level: int) -> None:
        self._access.update(level)
        self._view.set_enabled(self._access.can_modify())
13. facade/numeric_control.py
Задача: Простой API для пользователя.
Python
Copy
from typing import Union
from PyQt5.QtWidgets import QWidget
from frontend_module.core.registers_manager import RegistersManager
from frontend_module.components.controls.infrastructure.register_adapter import RegisterAdapter
from frontend_module.components.controls.presenters.numeric_presenter import NumericPresenter
from frontend_module.components.controls.views.slider_view import SliderView
from frontend_module.components.controls.views.spinbox_view import SpinboxView  # если делаете
from frontend_module.components.controls.schemas import BindingConfig, NumericViewConfig

class NumericControl:
    """
    Фасад для создания числового контрола.
    Возвращает готовый QWidget.
    """
    
    @staticmethod
    def create(
        registers_manager: RegistersManager,
        binding: BindingConfig,
        view_config: NumericViewConfig
    ) -> QWidget:
        """
        Создает QWidget (Slider или SpinBox) с полной логикой.
        
        Пример:
            widget = NumericControl.create(
                rm,
                BindingConfig(register_name="proc", field_name="min_area"),
                NumericViewConfig(view_type="slider", show_ticks=True)
            )
            layout.addWidget(widget)
        """
        adapter = RegisterAdapter(registers_manager)
        presenter = NumericPresenter(binding, adapter)
        
        # Выбор View по конфигу
        view = NumericControl._create_view(view_config)
        
        presenter.attach_view(view)
        
        # Сохраняем presenter, чтобы не уничтожился GC
        view.setProperty("_presenter", presenter)
        
        return view
        
    @staticmethod
    def _create_view(config: NumericViewConfig) -> QWidget:
        if config.view_type == "slider":
            return SliderView(
                show_ticks=getattr(config, 'show_ticks', False),
                tick_interval=getattr(config, 'tick_interval', 10)
            )
        elif config.view_type == "spinbox":
            return SpinboxView()  # или бросить NotImplemented
        else:
            raise ValueError(f"Unknown view_type: {config.view_type}")
14. facade/boolean_control.py
Аналогично, но проще (только CheckboxView).
15. Схемы (schemas/)
binding_config.py:
Python
Copy
from data_schema_module import SchemaBase, FieldMeta
from typing import Optional

class BindingConfig(SchemaBase):
    """Привязка к регистру — источник истины."""
    register_name: Annotated[str, FieldMeta("Имя регистра")]
    field_name: Annotated[str, FieldMeta("Имя поля")]
    access_level: Annotated[int, FieldMeta("Уровень доступа")] = 0
numeric_view_config.py:
Python
Copy
from typing import Optional, Literal
from data_schema_module import SchemaBase, FieldMeta

class NumericViewConfig(SchemaBase):
    """Настройки отображения числового поля."""
    view_type: Literal["slider", "spinbox"] = "slider"
    label: Optional[str] = None  # переопределяет ResolvedMeta.label
    show_ticks: bool = False
    tick_interval: Optional[int] = None
checkbox_view_config.py:
Python
Copy
class CheckboxViewConfig(SchemaBase):
    """Настройки отображения чекбокса."""
    position: Literal["left", "right", "top", "bottom"] = "left"
    label: Optional[str] = None
Что удалить/переместить
Table
Исходный файл	Действие
widget.py (SliderControl)	Удалить, логика разнесена по presenters/numeric_presenter.py и views/slider_view.py
widget(1).py (CheckboxControl)	Удалить, разнесена по presenters/boolean_presenter.py и views/checkbox_view.py
value_mapping.py	Удалить, перенести в infrastructure/value_transformer.py
legacy_sync.py	Перенести в infrastructure/legacy_sync.py как опциональную обертку
layout_builder.py	Логика встроена в views/checkbox_view.py
styles.py, styles(1).py	Константы перенести в views/, QSS — в соответствующие View
config.py, config(1).py	Разделить на schemas/binding_config.py и schemas/*_view_config.py
register_example.py, register_example(1).py	Оставить как есть (примеры для приложения)
Критерии приемки
Создание слайдера — 3 строки: NumericControl.create(rm, binding, config)
Тестируемость — NumericPresenter тестируется с MockAdapter и MockView
Смена View — замена view_type="slider" на "spinbox" без изменения Presenter
Сохранение функциональности:
transfer_k, round_k — работают через ValueTransformer
Debounce на слайдере — есть
Immediate write на поле ввода — есть
Access level — проверяется
Legacy sync — можно добавить обертку
Нет регрессий — существующие регистры (processor.min_area, renderer.show_mask) работают без изменений в схемах
Выполни рефакторинг согласно этому плану. Все docstrings — на русском языке.