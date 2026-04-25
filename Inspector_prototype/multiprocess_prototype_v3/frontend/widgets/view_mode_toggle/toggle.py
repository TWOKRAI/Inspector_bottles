# multiprocess_prototype_v3/frontend/widgets/view_mode_toggle/toggle.py
"""Переключатель режима отображения: карточки (0) / таблица (1)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QWidget,
    Signal,
)


class ViewModeToggle(QWidget):
    """Два чекабельных QPushButton: карточки и таблица."""

    mode_changed = Signal(int)  # 0=карточки, 1=таблица

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._btn_cards = QPushButton("⊞")  # ⊞
        self._btn_cards.setCheckable(True)
        self._btn_cards.setToolTip("Карточки")
        self._btn_cards.setFixedSize(32, 28)

        self._btn_table = QPushButton("≡")  # ≡
        self._btn_table.setCheckable(True)
        self._btn_table.setToolTip("Таблица")
        self._btn_table.setFixedSize(32, 28)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.addButton(self._btn_cards, 0)
        self._group.addButton(self._btn_table, 1)

        layout.addWidget(self._btn_cards)
        layout.addWidget(self._btn_table)

        # По умолчанию -- карточки
        self._btn_cards.setChecked(True)

        # Qt6: buttonClicked(int) удалён, idClicked(int) — новое имя
        self._group.idClicked.connect(self._on_button_clicked)

    def _on_button_clicked(self, button_id: int) -> None:
        self.mode_changed.emit(button_id)

    def set_mode(self, mode: int) -> None:
        """Установить режим программно (0=карточки, 1=таблица)."""
        btn = self._group.button(mode)
        if btn is not None:
            btn.setChecked(True)

    def current_mode(self) -> int:
        """Текущий режим: 0 или 1."""
        return self._group.checkedId()
