"""ControlPanelWidget — карточка сервиса «Пульт».

Рендерит контролы ДИНАМИЧЕСКИ из набора (list[dict] из state): кнопка/тумблер/
слайдер/поле числа-текста. Операция над контролом эмитит сигнал виджета
``control_operated(id, value)``. Снизу — форма «Добавить контрол».

Виджет НЕ знает про bridge/recipe — только сигналы наверх (секция → presenter).
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# Метка типа в форме → внутренний тип контрола.
_TYPE_LABELS: list[tuple[str, str]] = [
    ("Кнопка", "button"),
    ("Тумблер", "toggle"),
    ("Слайдер", "slider"),
    ("Число", "number"),
    ("Текст", "text"),
]
_LABEL_TO_TYPE = dict(_TYPE_LABELS)


class ControlPanelWidget(QWidget):
    """Пульт: динамические контролы (наблюдение + операция) + форма добавления."""

    # Операция над контролом: (control_id, value). value игнорируется для кнопки.
    control_operated = Signal(str, object)
    # Запрос добавить контрол: спецификация (dict).
    control_add_requested = Signal(dict)
    # Запрос удалить контрол: control_id.
    control_remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controls: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("<b>Пульт — контролы → сигналы в pipeline</b>")
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel(
            "Добавь контролы — каждый шлёт значение на свой порт (out_N). "
            "Привяжи порт к потребителю в редакторе Pipeline. Набор хранится в рецепте."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "placeholder-italic")
        layout.addWidget(hint)

        # Контейнер контролов (перестраивается из set_controls).
        self._rows = QVBoxLayout()
        self._rows.setSpacing(6)
        layout.addLayout(self._rows)
        self._empty_label = QLabel("Контролов нет — добавь ниже.")
        self._empty_label.setProperty("role", "placeholder-italic")
        self._rows.addWidget(self._empty_label)

        # Разделитель + форма добавления.
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)
        layout.addWidget(QLabel("<b>Добавить контрол</b>"))
        layout.addLayout(self._build_add_form())

        layout.addStretch()

    # ------------------------------------------------------------------ #
    # Форма добавления
    # ------------------------------------------------------------------ #

    def _build_add_form(self) -> QVBoxLayout:
        form = QVBoxLayout()
        form.setSpacing(6)

        row1 = QHBoxLayout()
        self._add_type = QComboBox()
        for label, _type in _TYPE_LABELS:
            self._add_type.addItem(label)
        self._add_type.currentIndexChanged.connect(self._on_type_changed)
        self._add_label = QLineEdit()
        self._add_label.setPlaceholderText("Подпись (напр. «Старт» или «Скорость»)")
        self._add_port = QComboBox()
        for i in range(1, 9):
            self._add_port.addItem(f"out_{i}")
        row1.addWidget(QLabel("Тип:"))
        row1.addWidget(self._add_type)
        row1.addWidget(self._add_label, 1)
        row1.addWidget(QLabel("Порт:"))
        row1.addWidget(self._add_port)
        form.addLayout(row1)

        # Диапазон (для слайдера/числа).
        self._range_row = QHBoxLayout()
        self._add_min = QDoubleSpinBox()
        self._add_min.setRange(-1e6, 1e6)
        self._add_min.setValue(0.0)
        self._add_max = QDoubleSpinBox()
        self._add_max.setRange(-1e6, 1e6)
        self._add_max.setValue(100.0)
        self._range_row.addWidget(QLabel("Мин:"))
        self._range_row.addWidget(self._add_min)
        self._range_row.addWidget(QLabel("Макс:"))
        self._range_row.addWidget(self._add_max)
        self._range_row.addStretch()
        form.addLayout(self._range_row)

        btn = QPushButton("Добавить контрол")
        btn.clicked.connect(self._on_add_clicked)
        form.addWidget(btn)

        self._on_type_changed()  # выставить видимость диапазона
        return form

    def _on_type_changed(self) -> None:
        """Показывать диапазон только для слайдера/числа."""
        ctype = _LABEL_TO_TYPE.get(self._add_type.currentText(), "button")
        show_range = ctype in ("slider", "number")
        for i in range(self._range_row.count()):
            item = self._range_row.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setVisible(show_range)

    def _on_add_clicked(self) -> None:
        ctype = _LABEL_TO_TYPE.get(self._add_type.currentText(), "button")
        label = self._add_label.text().strip() or self._add_type.currentText()
        spec = {
            "id": self._gen_id(label),
            "type": ctype,
            "label": label,
            "port": self._add_port.currentText(),
        }
        if ctype in ("slider", "number"):
            spec["min"] = self._add_min.value()
            spec["max"] = self._add_max.value()
        self.control_add_requested.emit(spec)
        self._add_label.clear()

    def _gen_id(self, label: str) -> str:
        """Сгенерировать уникальный id из подписи (ASCII-слаг + суффикс при коллизии)."""
        base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "ctl"
        existing = {c.get("id") for c in self._controls}
        if base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    # ------------------------------------------------------------------ #
    # Рендер контролов (из state)
    # ------------------------------------------------------------------ #

    def current_controls(self) -> list[dict]:
        """Текущий набор контролов (копия) — для вычисления нового набора при add/remove."""
        return [dict(c) for c in self._controls if isinstance(c, dict)]

    def set_controls(self, controls: Any) -> None:
        """Перестроить ряды контролов из набора (list[dict])."""
        self._controls = list(controls) if isinstance(controls, list) else []
        # Очистить контейнер (кроме empty_label — им управляем видимостью).
        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty_label:
                w.deleteLater()
        if not self._controls:
            self._rows.addWidget(self._empty_label)
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)
        for c in self._controls:
            if isinstance(c, dict) and c.get("id"):
                self._rows.addWidget(self._build_row(c))

    def _build_row(self, c: dict) -> QWidget:
        """Ряд: подпись + операбельный виджет по типу + удаление."""
        cid = str(c.get("id"))
        ctype = c.get("type", "button")
        label = c.get("label") or cid
        port = c.get("port", "out_1")

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        # Кнопка сама несёт подпись — отдельный лейбл не нужен (иначе «Рисовать [Нажать]»).
        if ctype != "button":
            h.addWidget(QLabel(f"{label}"))

        h.addWidget(self._build_operable(cid, ctype, c, label), 1)

        port_lbl = QLabel(f"→ {port}")
        port_lbl.setProperty("role", "placeholder-italic")
        h.addWidget(port_lbl)

        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        rm.setToolTip("Удалить контрол")
        rm.clicked.connect(lambda _=False, _id=cid, _lbl=label: self._confirm_remove(_id, _lbl))
        h.addWidget(rm)
        return row

    def _confirm_remove(self, control_id: str, label: str) -> None:
        """Подтвердить удаление контрола (защита от случайного клика ✕)."""
        from PySide6.QtWidgets import QMessageBox

        resp = QMessageBox.question(
            self,
            "Удалить контрол?",
            f"Удалить контрол «{label}»? Изменение сохранится в рецепт при Save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self.control_remove_requested.emit(control_id)

    def _build_operable(self, cid: str, ctype: str, c: dict, label: str = "") -> QWidget:
        """Операбельный виджет контрола (эмитит control_operated при действии)."""
        if ctype == "toggle":
            cb = QCheckBox()
            cb.setChecked(bool(c.get("value")))
            cb.toggled.connect(lambda v, _id=cid: self.control_operated.emit(_id, bool(v)))
            return cb
        if ctype == "slider":
            lo, hi = int(c.get("min", 0)), int(c.get("max", 100))
            sld = QSlider(Qt.Orientation.Horizontal)
            sld.setRange(lo, max(lo, hi))
            try:
                sld.setValue(int(c.get("value", lo)))
            except (TypeError, ValueError):
                sld.setValue(lo)
            sld.valueChanged.connect(lambda v, _id=cid: self.control_operated.emit(_id, float(v)))
            return sld
        if ctype == "number":
            sp = QDoubleSpinBox()
            sp.setRange(float(c.get("min", -1e6)), float(c.get("max", 1e6)))
            try:
                sp.setValue(float(c.get("value", 0.0)))
            except (TypeError, ValueError):
                sp.setValue(0.0)
            sp.editingFinished.connect(lambda _id=cid, _w=sp: self.control_operated.emit(_id, _w.value()))
            return sp
        if ctype == "text":
            le = QLineEdit()
            le.setText(str(c.get("value") or ""))
            le.returnPressed.connect(lambda _id=cid, _w=le: self.control_operated.emit(_id, _w.text()))
            return le
        # button (по умолчанию) — подпись контрола на самой кнопке.
        btn = QPushButton(label or "Нажать")
        btn.clicked.connect(lambda _=False, _id=cid: self.control_operated.emit(_id, True))
        return btn
