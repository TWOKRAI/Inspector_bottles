# -*- coding: utf-8 -*-
"""
CheckboxControlEnhanced — чекбокс с автоматической привязкой к RegistersManager.

Зеркало SliderControlEnhanced, наследуется от ConfigurableWidget.
Читает метаданные поля (описание, access_level) из RegistersManager и реагирует
на изменения поля через observer-паттерн.

Поддерживает три способа конфигурации:

    # Вариант 1: через field-ссылку (рекомендуется)
    cb = CheckboxControlEnhanced(field=CameraRegisters.enabled, parent=self)

    # Вариант 2: явные имена
    cb = CheckboxControlEnhanced(
        register_name='camera', field_name='enabled',
        registers_manager=rm, parent=self,
    )

    # Вариант 3: строка с точкой
    cb = CheckboxControlEnhanced(field_name='camera.enabled', registers_manager=rm)
"""
from typing import Any, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from App.Core.base_configurable_widget import ConfigurableWidget


class CheckboxControlEnhanced(ConfigurableWidget):
    """
    Чекбокс с автоматической конфигурацией из метаданных RegistersManager.

    Наследует observer-паттерн ConfigurableWidget:
      - подписывается на изменения поля через RegistersManager.subscribe()
      - обновляет QCheckBox без сигналов (_update_value_silent)
      - записывает изменения обратно в RegistersManager (update_external)
      - учитывает access_level (setEnabled)

    Args:
        register_name:      Имя регистра ('draw', 'camera', …) или None для автоопределения.
        field_name:         Имя поля или строка 'register.field' для автоопределения.
        field:              Поле модели (например CameraRegisters.enabled) — авторезолв.
        registers_manager:  RegistersManager. Если None — ищется у parent-виджета.
        access_level:       Текущий уровень доступа. Если 0 — ищется у parent-виджета.
        parent:             Родительский виджет.
        label:              Текст метки (если None — берётся из metadata['info']).
        position:           Расположение метки: 'top' | 'bottom' | 'left' | 'right'.
    """

    def __init__(
        self,
        register_name: Optional[str] = None,
        field_name: Optional[str] = None,
        field: Optional[Any] = None,
        registers_manager: Optional[Any] = None,
        access_level: int = 0,
        parent: Optional[QWidget] = None,
        label: Optional[str] = None,
        position: str = "top",
    ) -> None:
        # Инициализируем атрибуты ДО super().__init__() — базовый класс может
        # вызвать _load_metadata() через setter field_name → _apply_configuration()
        self._custom_label = label
        self._position = position
        self._label: Optional[QLabel] = None
        self._checkbox: Optional[QCheckBox] = None

        super().__init__(
            register_name=register_name,
            field_name=field_name,
            field=field,
            registers_manager=registers_manager,
            access_level=access_level,
            parent=parent,
        )

        if self._register_name and self._field_name and self._registers_manager:
            self._load_metadata()
            self._is_initialized = True

    # ------------------------------------------------------------------
    # ConfigurableWidget template methods
    # ------------------------------------------------------------------

    def _load_metadata(self) -> None:
        """Загрузить метаданные и построить / перенастроить UI."""
        if not (self._registers_manager and self._register_name and self._field_name):
            return

        metadata = self._registers_manager.get_field_metadata(
            self._register_name, self._field_name
        )
        if not metadata:
            raise ValueError(
                f"Поле {self._register_name}.{self._field_name} "
                "не найдено в RegistersManager"
            )

        description = metadata.get("info") or metadata.get("description", self._field_name)
        can_modify = self._registers_manager.can_modify_field(
            self._register_name, self._field_name, self._access_level
        )
        current_val = bool(self.get_field_value() or metadata.get("default", False))

        if self._checkbox is None:
            self._build_ui(description, current_val, can_modify)
        else:
            self._apply_state(current_val, can_modify)

    def _reload_metadata(self) -> None:
        self._load_metadata()

    def _update_access_level(self) -> None:
        if self._checkbox is None or not self._registers_manager:
            return
        can_modify = self._registers_manager.can_modify_field(
            self._register_name, self._field_name, self._access_level
        )
        self._checkbox.setEnabled(can_modify)

    def _update_value_silent(self, value: Any) -> None:
        """Обновить QCheckBox без эмитирования сигналов.

        Вызывается RegistersManager, когда другой компонент изменил то же поле.
        blockSignals предотвращает рекурсивный вызов update_external.
        """
        if self._checkbox is None:
            return
        self._checkbox.blockSignals(True)
        try:
            self._checkbox.setChecked(bool(value))
        finally:
            self._checkbox.blockSignals(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, description: str, value: bool, can_modify: bool) -> None:
        font = QFont("Arial", 11)
        display_text = self._custom_label if self._custom_label is not None else description

        self._label = QLabel(display_text)
        self._label.setFont(font)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setToolTip(description)

        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(44, 44)
        self._checkbox.setChecked(value)
        self._checkbox.setEnabled(can_modify)
        self._checkbox.stateChanged.connect(self._on_state_changed)

        if self._position in ("top", "bottom"):
            layout = QVBoxLayout(self)
            items = (
                [self._label, self._checkbox]
                if self._position == "top"
                else [self._checkbox, self._label]
            )
        else:
            layout = QHBoxLayout(self)
            items = (
                [self._label, self._checkbox]
                if self._position == "left"
                else [self._checkbox, self._label]
            )

        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        for item in items:
            layout.addWidget(item)

    def _apply_state(self, value: bool, can_modify: bool) -> None:
        if self._checkbox:
            self._checkbox.blockSignals(True)
            self._checkbox.setChecked(value)
            self._checkbox.setEnabled(can_modify)
            self._checkbox.blockSignals(False)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: int) -> None:
        value = state == Qt.Checked
        self.set_field_value(value)
        self.update_external(value)

    def update_external(self, value: bool) -> None:
        """Синхронизировать Pydantic-модель, уведомить observers, роутить в бэкенд."""
        # 1. Синхронизируем Pydantic-модель (единственный источник истины).
        if self._registers_manager and self._register_name and self._field_name:
            register = self._registers_manager.get_register(self._register_name)
            if register is not None and hasattr(register, self._field_name):
                try:
                    setattr(register, self._field_name, value)
                except Exception:
                    pass

        # 2. Уведомляем field-specific observers (другие UI-компоненты на том же поле).
        #    Используем notify_field_changed, а не set_field_value, чтобы не дублировать
        #    глобальный observer (бэкенд вызывается ниже напрямую через send_register_update).
        if (
            self._registers_manager
            and self._register_name
            and self._field_name
            and hasattr(self._registers_manager, "notify_field_changed")
        ):
            self._registers_manager.notify_field_changed(
                self._register_name, self._field_name, value
            )

        # 3. Единый путь отправки в бэкенд через MainWindow.send_register_update.
        parent = self.parent()
        if parent is not None and getattr(parent, "send_register_update", None) is not None:
            parent.send_register_update(self._register_name, self._field_name, value)
