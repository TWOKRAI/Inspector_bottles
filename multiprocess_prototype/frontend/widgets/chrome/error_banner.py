"""ErrorBannerWidget — баннер ошибок/предупреждений в MainWindow."""
from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Максимальное количество одновременно отображаемых сообщений
_MAX_MESSAGES = 3

# QSS-стили для строк разного уровня
_STYLE_ERROR = (
    "background: rgba(220, 38, 38, 0.15);"
    " border-left: 3px solid #dc2626;"
    " padding: 4px 8px;"
)
_STYLE_WARNING = (
    "background: rgba(234, 179, 8, 0.15);"
    " border-left: 3px solid #eab308;"
    " padding: 4px 8px;"
)

# Иконки для каждого уровня
_ICON_ERROR = "❌"
_ICON_WARNING = "⚠"


class ErrorBannerWidget(QWidget):
    """Виджет баннера для отображения ошибок и предупреждений.

    Отображает не более 3 сообщений одновременно (FIFO: при переполнении
    удаляется самое старое). Автоматически скрывается когда сообщений нет.

    Поддерживает привязку через GuiStateBindings:
        bindings.bind("system.error",   banner, "show_error")
        bindings.bind("system.warning", banner, "show_warning")
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ErrorBanner")

        # Корневой вертикальный layout без отступов
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(2)

        # Список текущих строк-виджетов (FIFO, не более _MAX_MESSAGES)
        self._rows: list[QWidget] = []

        # Изначально баннер скрыт
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def show_error(self, msg: str) -> None:
        """Добавить строку с ошибкой (красный стиль).

        Args:
            msg: текст сообщения об ошибке.
        """
        self._add_row(msg, level="error")

    def show_warning(self, msg: str) -> None:
        """Добавить строку с предупреждением (жёлтый стиль).

        Args:
            msg: текст предупреждения.
        """
        self._add_row(msg, level="warning")

    def dismiss(self, index: int) -> None:
        """Убрать строку по индексу (0 = старейшая).

        Если индекс вне диапазона — ничего не делает.

        Args:
            index: индекс строки для удаления.
        """
        if index < 0 or index >= len(self._rows):
            return
        self._remove_row(index)

    def clear(self) -> None:
        """Убрать все сообщения и скрыть баннер."""
        # Удаляем в обратном порядке, чтобы не сбивать индексы
        for i in range(len(self._rows) - 1, -1, -1):
            self._remove_row(i)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _add_row(self, msg: str, level: Literal["error", "warning"]) -> None:
        """Создать строку сообщения и добавить в layout.

        При переполнении (_MAX_MESSAGES) удаляет самую старую строку (индекс 0).

        Args:
            msg: текст сообщения.
            level: уровень ('error' или 'warning').
        """
        # FIFO: если достигнут предел — удаляем старейшую (первую) строку
        if len(self._rows) >= _MAX_MESSAGES:
            self._remove_row(0)

        # Выбираем стиль и иконку по уровню
        style = _STYLE_ERROR if level == "error" else _STYLE_WARNING
        icon_text = _ICON_ERROR if level == "error" else _ICON_WARNING

        # Создаём контейнер строки
        row_widget = QWidget(self)
        row_widget.setStyleSheet(style)

        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        # Иконка
        icon_label = QLabel(icon_text)
        icon_label.setFixedWidth(20)
        row_layout.addWidget(icon_label)

        # Текст сообщения (растягивается)
        msg_label = QLabel(msg)
        msg_label.setWordWrap(True)
        row_layout.addWidget(msg_label, stretch=1)

        # Кнопка закрытия
        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setFlat(True)
        row_layout.addWidget(dismiss_btn)

        # Привязка кнопки к dismiss — используем lambda с захватом row_widget
        dismiss_btn.clicked.connect(self._make_dismiss_callback(row_widget))

        # Добавляем в список и layout
        self._rows.append(row_widget)
        self._root_layout.addWidget(row_widget)

        # Показываем баннер
        self.setVisible(True)

    def _make_dismiss_callback(self, row_widget: QWidget):
        """Фабрика callback для кнопки × конкретной строки.

        Возвращает callable, который находит строку по ссылке и удаляет её.

        Args:
            row_widget: виджет строки, которую нужно удалить при нажатии.
        """
        def _callback() -> None:
            if row_widget in self._rows:
                idx = self._rows.index(row_widget)
                self._remove_row(idx)
        return _callback

    def _remove_row(self, index: int) -> None:
        """Удалить строку по индексу из layout и списка.

        После удаления последней строки — скрывает баннер.

        Args:
            index: индекс строки в self._rows.
        """
        row_widget = self._rows.pop(index)
        self._root_layout.removeWidget(row_widget)
        row_widget.deleteLater()

        # Скрываем баннер когда сообщений не осталось
        if not self._rows:
            self.setVisible(False)
