"""WireInspectorPanel — панель редактирования свойств wire-соединения.

Фаза 3: правые панели конструктора.
Отображается в правой панели при клике на wire-соединение на канвасе.

Принимает и возвращает только dict (Dict at Boundary).
SchemaBase/WireDefinition в API не используются.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
    ShmConfigPanel,
)


class WireInspectorPanel(QWidget):
    """Панель инспектора wire-соединения.

    Отображает адреса source/target (read-only), редактируемые transport
    и description, а также встроенный ShmConfigPanel для конфигурации
    SharedMemory (видимость зависит от выбранного transport).

    Все данные принимаются и возвращаются как dict (Dict at Boundary).
    """

    # Сигнал эмитируется при изменении любого поля пользователем.
    # Аргументы: wire_key (str) и dict с изменёнными полями.
    # НЕ эмитируется при программном заполнении (show_wire).
    wire_changed = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wire_key: str | None = None
        self._init_ui()
        self._connect_signals()
        # Начальное состояние — пустая панель
        self.clear()

    def _init_ui(self) -> None:
        """Построить layout панели."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Заголовок: отображается текущий wire_key
        self._title_label = QLabel("Wire:", self)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        layout.addWidget(self._title_label)

        # Форма с полями wire
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        # source — read-only QLabel (НЕ QLineEdit)
        self._source_label = QLabel("", self)
        self._source_label.setTextInteractionFlags(
            self._source_label.textInteractionFlags()
        )
        form.addRow("source:", self._source_label)

        # target — read-only QLabel
        self._target_label = QLabel("", self)
        form.addRow("target:", self._target_label)

        # transport — редактируемый QComboBox
        self._transport = QComboBox(self)
        self._transport.addItems(["router", "direct"])
        form.addRow("transport:", self._transport)

        # description — редактируемый QLineEdit
        self._description = QLineEdit(self)
        self._description.setPlaceholderText("описание соединения")
        form.addRow("description:", self._description)

        layout.addLayout(form)

        # Горизонтальный разделитель
        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Встроенная панель SHM-конфига
        self._shm_panel = ShmConfigPanel(self)
        layout.addWidget(self._shm_panel)

        # Растяжка снизу
        layout.addStretch()

    def _connect_signals(self) -> None:
        """Подключить сигналы внутренних виджетов к слотам-обработчикам."""
        self._transport.currentTextChanged.connect(self._on_transport_changed)
        self._description.textChanged.connect(self._on_description_changed)
        self._shm_panel.config_changed.connect(self._on_shm_config_changed)

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    def _on_transport_changed(self, value: str) -> None:
        """Обновить видимость ShmConfigPanel и эмитировать wire_changed."""
        # SHM-панель показываем для "router" и "direct"
        self._shm_panel.setVisible(value in ("router", "direct"))
        if self._wire_key is not None:
            self.wire_changed.emit(self._wire_key, {"transport": value})

    def _on_description_changed(self, value: str) -> None:
        """Эмитировать wire_changed при изменении описания."""
        if self._wire_key is not None:
            self.wire_changed.emit(self._wire_key, {"description": value})

    def _on_shm_config_changed(self, config_dict: dict) -> None:
        """Эмитировать wire_changed при изменении SHM-конфига."""
        if self._wire_key is not None:
            self.wire_changed.emit(self._wire_key, {"shm_config": config_dict})

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def show_wire(self, wire_key: str, wire_data: dict) -> None:
        """Заполнить панель данными wire-соединения.

        Все поля заполняются с блокировкой сигналов (blockSignals),
        чтобы не вызвать бесконечный цикл обновлений.

        Args:
            wire_key: уникальный ключ wire (например "proc_a→proc_b").
            wire_data: dict с полями source, target, transport,
                       description, shm_config (Dict at Boundary).
        """
        self._wire_key = wire_key

        # Обновить заголовок
        self._title_label.setText(f"Wire: {wire_key}")

        # Адреса source/target — read-only, сигналы не нужны
        self._source_label.setText(wire_data.get("source", ""))
        self._target_label.setText(wire_data.get("target", ""))

        # Блокируем сигналы редактируемых виджетов при программном заполнении
        self._transport.blockSignals(True)
        self._description.blockSignals(True)
        try:
            transport = wire_data.get("transport", "router")
            idx = self._transport.findText(transport)
            if idx >= 0:
                self._transport.setCurrentIndex(idx)
            else:
                # Если transport неизвестен — выбрать "router"
                self._transport.setCurrentIndex(0)

            self._description.setText(wire_data.get("description", ""))
        finally:
            self._transport.blockSignals(False)
            self._description.blockSignals(False)

        # Определить имена процессов из адресов source/target (первая часть до точки)
        source_addr: str = wire_data.get("source", "")
        target_addr: str = wire_data.get("target", "")
        source_proc = source_addr.split(".")[0] if source_addr else ""
        target_proc = target_addr.split(".")[0] if target_addr else ""

        # Заполнить ShmConfigPanel
        shm_config: dict = wire_data.get("shm_config", {})
        self._shm_panel.set_config(shm_config, source_proc, target_proc)

        # Видимость ShmConfigPanel зависит от transport
        actual_transport = self._transport.currentText()
        self._shm_panel.setVisible(actual_transport in ("router", "direct"))

        # Показать панель (если была скрыта через clear)
        self.setVisible(True)

    def clear(self) -> None:
        """Сбросить и скрыть панель."""
        self._wire_key = None
        self._title_label.setText("Wire:")

        self._source_label.setText("")
        self._target_label.setText("")

        self._transport.blockSignals(True)
        self._description.blockSignals(True)
        try:
            self._transport.setCurrentIndex(0)  # "router"
            self._description.clear()
        finally:
            self._transport.blockSignals(False)
            self._description.blockSignals(False)

        self._shm_panel.clear()
        self._shm_panel.setVisible(False)

    def current_wire_key(self) -> str | None:
        """Вернуть текущий wire_key или None, если панель пуста."""
        return self._wire_key


__all__ = ["WireInspectorPanel"]
