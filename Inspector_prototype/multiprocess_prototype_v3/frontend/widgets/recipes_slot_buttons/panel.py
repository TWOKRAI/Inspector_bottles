# multiprocess_prototype_v3/frontend/widgets/recipes_slot_buttons/panel.py
"""
RecipesSlotButtonsPanel — слева во вкладке «Рецепты»:

- вертикальный список кнопок-сортов (выбор для просмотра)
- кнопки Применить / Копировать / Вставить внизу

Сигналы:
  slot_selected(int) — клик по слоту (visual switch, без apply)
  slot_apply_requested(int) — клик «Применить» (нужно подтверждение в parent)
  slot_copy_requested(int) — клик «Копировать»
  slot_paste_requested(int) — клик «Вставить»

Подсветка:
  selected = checked (выбран для просмотра)
  applied  = QSS-класс «applied» (рамка/цвет — реально применённый сейчас)
"""

from __future__ import annotations

from collections.abc import Callable

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Signal,
)

_APPLIED_QSS = (
    "QPushButton[applied=\"true\"] { "
    "border: 2px solid #2e86de; "
    "background-color: #d5e8fb; "
    "font-weight: bold; "
    "}"
)


class RecipesSlotButtonsPanel(QWidget):
    """Слот-кнопки + Apply/Copy/Paste."""

    slot_selected = Signal(int)
    slot_apply_requested = Signal(int)
    slot_save_requested = Signal(int)
    slot_copy_requested = Signal(int)
    slot_paste_requested = Signal(int)

    def __init__(
        self,
        *,
        slot_min: int = 0,
        slot_max: int = 21,
        label_provider: Callable[[int], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._slot_min = slot_min
        self._slot_max = slot_max
        self._label_provider = label_provider
        self._buttons: dict[int, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._selected_slot: int | None = None
        self._applied_slot: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(_APPLIED_QSS)
        self._inner_layout = QVBoxLayout(inner)
        self._inner_layout.setContentsMargins(4, 4, 4, 4)
        self._inner_layout.setSpacing(2)
        self._scroll.setWidget(inner)
        outer.addWidget(self._scroll, 1)

        # Разделитель
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        # Save / Apply (две кнопки в один ряд)
        sa_row = QHBoxLayout()
        sa_row.setContentsMargins(0, 0, 0, 0)
        sa_row.setSpacing(2)
        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить отредактированные параметры в YAML слота")
        self._btn_save.clicked.connect(self._emit_save)
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setToolTip("Применить параметры слота к текущим регистрам")
        self._btn_apply.clicked.connect(self._emit_apply)
        sa_row.addWidget(self._btn_save)
        sa_row.addWidget(self._btn_apply)
        outer.addLayout(sa_row)

        # Copy / Paste в одну строку
        cp_row = QHBoxLayout()
        cp_row.setContentsMargins(0, 0, 0, 0)
        cp_row.setSpacing(2)
        self._btn_copy = QPushButton("Копир.")
        self._btn_copy.setToolTip("Копировать параметры выбранного слота в буфер")
        self._btn_copy.clicked.connect(self._emit_copy)
        self._btn_paste = QPushButton("Вставить")
        self._btn_paste.setToolTip("Вставить параметры из буфера в выбранный слот")
        self._btn_paste.clicked.connect(self._emit_paste)
        cp_row.addWidget(self._btn_copy)
        cp_row.addWidget(self._btn_paste)
        outer.addLayout(cp_row)

        self._rebuild()
        self._update_action_buttons()

    def _rebuild(self) -> None:
        """Очистить и построить кнопки слотов заново."""
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                self._group.removeButton(w)  # type: ignore[arg-type]
                w.deleteLater()
        self._buttons.clear()

        for slot_id in range(self._slot_min, self._slot_max + 1):
            btn = QPushButton(self._label_for(slot_id))
            btn.setCheckable(True)
            btn.setProperty("applied", False)
            sid = slot_id
            btn.clicked.connect(lambda _checked, s=sid: self._on_slot_clicked(s))
            self._group.addButton(btn)
            self._inner_layout.addWidget(btn)
            self._buttons[slot_id] = btn

        self._inner_layout.addStretch()
        if self._selected_slot is not None:
            self.set_selected_slot(self._selected_slot, emit=False)
        if self._applied_slot is not None:
            self.set_applied_slot(self._applied_slot)

    def _label_for(self, slot_id: int) -> str:
        if self._label_provider is not None:
            try:
                text = self._label_provider(slot_id)
                if text:
                    return text
            except Exception:  # noqa: BLE001
                pass
        return f"#{slot_id}"

    def _on_slot_clicked(self, slot_id: int) -> None:
        self._selected_slot = slot_id
        self._update_action_buttons()
        self.slot_selected.emit(slot_id)

    def set_selected_slot(self, slot_id: int, *, emit: bool = False) -> None:
        """Подсветить выбранный слот (checked) — без сигнала по умолчанию."""
        self._selected_slot = slot_id
        btn = self._buttons.get(slot_id)
        if btn is not None and not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        self._update_action_buttons()
        if emit:
            self.slot_selected.emit(slot_id)

    def set_applied_slot(self, slot_id: int | None) -> None:
        """Подсветить реально применённый слот (отдельная подсветка)."""
        prev = self._applied_slot
        self._applied_slot = slot_id
        # Сбросить старый
        if prev is not None and prev in self._buttons:
            self._buttons[prev].setProperty("applied", False)
            self._refresh_style(self._buttons[prev])
        # Применить новый
        if slot_id is not None and slot_id in self._buttons:
            self._buttons[slot_id].setProperty("applied", True)
            self._refresh_style(self._buttons[slot_id])

    @staticmethod
    def _refresh_style(btn: QPushButton) -> None:
        """Перерисовать кнопку после изменения dynamic property."""
        style = btn.style()
        if style is not None:
            style.unpolish(btn)
            style.polish(btn)
        btn.update()

    def set_label(self, slot_id: int, text: str) -> None:
        btn = self._buttons.get(slot_id)
        if btn is not None:
            btn.setText(text)

    def selected_slot(self) -> int | None:
        return self._selected_slot

    def _update_action_buttons(self) -> None:
        has_sel = self._selected_slot is not None
        self._btn_apply.setEnabled(has_sel)
        self._btn_save.setEnabled(has_sel)
        self._btn_copy.setEnabled(has_sel)
        self._btn_paste.setEnabled(has_sel)

    def _emit_apply(self) -> None:
        if self._selected_slot is not None:
            self.slot_apply_requested.emit(self._selected_slot)

    def _emit_save(self) -> None:
        if self._selected_slot is not None:
            self.slot_save_requested.emit(self._selected_slot)

    def _emit_copy(self) -> None:
        if self._selected_slot is not None:
            self.slot_copy_requested.emit(self._selected_slot)

    def _emit_paste(self) -> None:
        if self._selected_slot is not None:
            self.slot_paste_requested.emit(self._selected_slot)

    def rebuild(self, slot_min: int, slot_max: int) -> None:
        self._slot_min = slot_min
        self._slot_max = slot_max
        self._rebuild()
