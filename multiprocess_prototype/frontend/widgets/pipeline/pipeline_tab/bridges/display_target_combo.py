"""DisplayTargetCombo — multi-select дисплеев с popup-меню.

Layout: QToolButton (popup-меню с чекбоксами) + QLabel сводка.
Sentinel «+ Новый дисплей...» в конце меню.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

# Sentinel-текст
_SENTINEL_DISPLAY = "+ Новый дисплей…"


class DisplayTargetCombo(QWidget):
    """Multi-select виджет для display_targets.

    Signals:
        display_targets_changed(list): испускается при изменении выбора.
    """

    display_targets_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = QToolButton()
        self._button.setText("Дисплеи")
        self._button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self._button)

        self._summary_label = QLabel("—")
        layout.addWidget(self._summary_label, 1)

        # Текущее состояние
        self._known_displays: list[str] = []
        self._checked: set[str] = set()
        self._menu: QMenu | None = None

        # Блокировка сигналов
        self._suppress = False

    def set_known_displays(
        self,
        displays: list[str],
        current: list[str] | None = None,
    ) -> None:
        """Перестроить меню с известными дисплеями.

        Args:
            displays: Список известных display id.
            current: Текущий выбор (отмеченные галочками).
        """
        self._known_displays = list(displays)
        self._checked = set(current) if current else set()
        self._rebuild_menu()
        self._update_summary()

    def value(self) -> list[str]:
        """Текущий выбор (порядок как в known_displays)."""
        return [d for d in self._known_displays if d in self._checked]

    def _rebuild_menu(self) -> None:
        """Перестроить popup-меню с чекбоксами и sentinel."""
        menu = QMenu(self)

        for display_id in self._known_displays:
            action = menu.addAction(display_id)
            action.setCheckable(True)
            action.setChecked(display_id in self._checked)
            action.toggled.connect(
                lambda checked, did=display_id: self._on_display_toggled(did, checked),
            )

        if self._known_displays:
            menu.addSeparator()

        # Sentinel
        sentinel_action = menu.addAction(_SENTINEL_DISPLAY)
        sentinel_action.triggered.connect(self._on_add_new_display)

        self._menu = menu
        self._button.setMenu(menu)

    def _on_display_toggled(self, display_id: str, checked: bool) -> None:
        """Обработка переключения чекбокса дисплея."""
        if self._suppress:
            return

        if checked:
            self._checked.add(display_id)
        else:
            self._checked.discard(display_id)

        self._update_summary()
        self.display_targets_changed.emit(self.value())

    def _on_add_new_display(self) -> None:
        """Показать диалог ввода нового дисплея."""
        name, ok = QInputDialog.getText(
            self,
            "Новый дисплей",
            "Имя дисплея:",
        )
        if ok and name.strip():
            new_name = name.strip()
            if new_name not in self._known_displays:
                self._known_displays.append(new_name)
            self._checked.add(new_name)
            self._rebuild_menu()
            self._update_summary()
            self.display_targets_changed.emit(self.value())

    def _update_summary(self) -> None:
        """Обновить текст сводки рядом с кнопкой."""
        selected = self.value()
        count = len(selected)
        if count == 0:
            self._summary_label.setText("—")
        elif count <= 3:
            self._summary_label.setText(", ".join(selected))
        else:
            self._summary_label.setText(f"{count} дисплеев")

    def set_value_silent(self, targets: list[str]) -> None:
        """Установить значение без испускания сигнала (для refresh после undo)."""
        self._suppress = True
        try:
            self._checked = set(targets)
            self._rebuild_menu()
            self._update_summary()
        finally:
            self._suppress = False


__all__ = ["DisplayTargetCombo"]
