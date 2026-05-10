"""PluginCardWidget — карточка одного плагина в цепочке.

Отображает имя, категорию, входные/выходные порты.
Кнопки: переместить вверх/вниз, удалить.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# Цвета категорий плагинов
_CATEGORY_COLORS: dict[str, str] = {
    "source": "#4A9EFF",
    "processing": "#66BB6A",
    "output": "#FF7043",
}

# Цвет по умолчанию для неизвестных категорий
_DEFAULT_CATEGORY_COLOR = "#888888"

# Стиль рамки карточки (нормальное состояние)
_CARD_STYLE = """
QFrame#PluginCard {
    border: 1px solid #555;
    border-radius: 6px;
    background: #2b2b2b;
    padding: 4px;
}
"""

# Стиль рамки карточки (выбранная)
_CARD_SELECTED_STYLE = """
QFrame#PluginCard {
    border: 2px solid #4A9EFF;
    border-radius: 6px;
    background: #333;
    padding: 3px;
}
"""


class PluginCardWidget(QFrame):
    """Карточка плагина в цепочке.

    Отображает:
        - Заголовок: имя плагина + категория (цветной badge) + кнопки управления
        - Порты: входы слева, выходы справа в формате "name: dtype"

    Signals:
        selected(int): клик по карточке — передаёт индекс
        remove_requested(int): кнопка X — передаёт индекс
        move_requested(int, int): кнопки ↑/↓ — (индекс, направление: -1 вверх / +1 вниз)
    """

    selected = Signal(int)
    remove_requested = Signal(int)
    move_requested = Signal(int, int)

    def __init__(
        self,
        plugin_data: dict,
        index: int,
        inputs: list | None = None,
        outputs: list | None = None,
        parent=None,
    ) -> None:
        """Инициализировать карточку плагина.

        Args:
            plugin_data: Словарь с ключами plugin_class, plugin_name, category и пр.
            index: Позиция плагина в цепочке (0-based).
            inputs: Список объектов Port (входы). None если registry недоступен.
            outputs: Список объектов Port (выходы). None если registry недоступен.
            parent: Родительский виджет.
        """
        super().__init__(parent)
        self.setObjectName("PluginCard")

        self._plugin_data = plugin_data
        self._index = index
        self._inputs = inputs
        self._outputs = outputs
        self._is_selected = False

        self._setup_ui()
        self._apply_style(selected=False)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def plugin_data(self) -> dict:
        """Данные плагина (dict)."""
        return self._plugin_data

    @property
    def index(self) -> int:
        """Текущий индекс в цепочке."""
        return self._index

    @index.setter
    def index(self, value: int) -> None:
        self._index = value

    @property
    def is_selected(self) -> bool:
        return self._is_selected

    def set_selected(self, selected: bool) -> None:
        """Установить/снять выделение карточки."""
        self._is_selected = selected
        self._apply_style(selected)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout карточки."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(2)

        # --- Заголовок ---
        header = QHBoxLayout()
        header.setSpacing(6)

        # Имя плагина
        name = self._plugin_data.get("plugin_name", "???")
        name_label = QLabel(f"<b>{name}</b>")
        name_label.setObjectName("pluginName")
        header.addWidget(name_label)

        # Badge категории
        category = self._plugin_data.get("category", "")
        if category:
            cat_color = _CATEGORY_COLORS.get(category, _DEFAULT_CATEGORY_COLOR)
            cat_label = QLabel(category)
            cat_label.setStyleSheet(
                f"background: {cat_color}; color: white; "
                f"border-radius: 3px; padding: 1px 6px; font-size: 11px;"
            )
            cat_label.setFixedHeight(18)
            header.addWidget(cat_label)

        header.addStretch()

        # Кнопка ↑
        btn_up = QPushButton("↑")
        btn_up.setFixedSize(24, 24)
        btn_up.setToolTip("Переместить вверх")
        btn_up.clicked.connect(lambda: self.move_requested.emit(self._index, -1))
        header.addWidget(btn_up)

        # Кнопка ↓
        btn_down = QPushButton("↓")
        btn_down.setFixedSize(24, 24)
        btn_down.setToolTip("Переместить вниз")
        btn_down.clicked.connect(lambda: self.move_requested.emit(self._index, 1))
        header.addWidget(btn_down)

        # Кнопка X (удалить)
        btn_remove = QPushButton("✕")
        btn_remove.setFixedSize(24, 24)
        btn_remove.setToolTip("Удалить плагин")
        btn_remove.setStyleSheet("color: #FF5252;")
        btn_remove.clicked.connect(lambda: self.remove_requested.emit(self._index))
        header.addWidget(btn_remove)

        main_layout.addLayout(header)

        # --- Порты ---
        ports_layout = QHBoxLayout()
        ports_layout.setSpacing(12)

        # Входы (слева)
        inputs_text = self._format_ports(self._inputs, "Входы")
        inputs_label = QLabel(inputs_text)
        inputs_label.setObjectName("portsLabel")
        inputs_label.setStyleSheet("color: #aaa; font-size: 11px;")
        ports_layout.addWidget(inputs_label)

        ports_layout.addStretch()

        # Выходы (справа)
        outputs_text = self._format_ports(self._outputs, "Выходы")
        outputs_label = QLabel(outputs_text)
        outputs_label.setObjectName("portsLabel")
        outputs_label.setStyleSheet("color: #aaa; font-size: 11px;")
        outputs_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        ports_layout.addWidget(outputs_label)

        main_layout.addLayout(ports_layout)

    @staticmethod
    def _format_ports(ports: list | None, label: str) -> str:
        """Форматировать список портов в строку.

        Args:
            ports: Список Port-объектов или None.
            label: Префикс ("Входы" / "Выходы").

        Returns:
            Строка вида "Входы: frame: image/bgr" или "Входы: —" если нет данных.
        """
        if ports is None:
            return f"{label}: ?"
        if not ports:
            return f"{label}: —"
        parts = [f"{p.name}: {p.dtype}" for p in ports]
        return f"{label}: {', '.join(parts)}"

    def _apply_style(self, selected: bool) -> None:
        """Применить стиль рамки в зависимости от состояния выбора."""
        self.setStyleSheet(_CARD_SELECTED_STYLE if selected else _CARD_STYLE)

    # ------------------------------------------------------------------
    # События
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        """Клик по карточке — сигнал selected."""
        self.selected.emit(self._index)
        super().mousePressEvent(event)
