"""ProcessListWidget — список процессов с кнопками Add / Remove."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProcessListWidget(QWidget):
    """Виджет списка процессов.

    Показывает QListWidget с именами процессов.
    Кнопки Add/Remove инициируют соответствующие сигналы.
    """

    # Пользователь выбрал процесс (имя процесса)
    process_selected = Signal(str)
    # Пользователь нажал Add (запрос на добавление нового процесса)
    process_add_requested = Signal()
    # Пользователь нажал Remove (имя выбранного процесса)
    process_remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Построить UI виджета."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Список процессов
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        # Кнопки Add / Remove
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("Add")
        self._btn_remove = QPushButton("Remove")
        self._btn_remove.setEnabled(False)
        self._btn_add.clicked.connect(self.process_add_requested)
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def refresh(self, process_names: list[str]) -> None:
        """Обновить список процессов."""
        from PySide6.QtCore import Qt

        # Запомнить текущий выбор
        current = self.selected_process()

        self._list.blockSignals(True)
        self._list.clear()
        for name in process_names:
            self._list.addItem(QListWidgetItem(name))

        # Восстановить выбор если возможно
        if current:
            items = self._list.findItems(current, Qt.MatchExactly)
            if items:
                self._list.setCurrentItem(items[0])

        self._list.blockSignals(False)
        self._btn_remove.setEnabled(bool(process_names))

    def selected_process(self) -> str | None:
        """Имя выбранного процесса или None."""
        item = self._list.currentItem()
        return item.text() if item else None

    # ------------------------------------------------------------------ #
    #  Приватные слоты                                                     #
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        """Слот: изменился выбранный элемент."""
        if current:
            self._btn_remove.setEnabled(True)
            self.process_selected.emit(current.text())
        else:
            self._btn_remove.setEnabled(False)

    def _on_remove_clicked(self) -> None:
        """Слот: нажата кнопка Remove."""
        name = self.selected_process()
        if name:
            self.process_remove_requested.emit(name)
