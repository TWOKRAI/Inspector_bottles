# -*- coding: utf-8 -*-
"""frontend/tests/test_wheel_guard.py — WheelGuard гасит колесо на полях ввода.

Тестирует:
  1. spinbox: значение НЕ меняется при wheel (фильтр вернул True).
  2. combobox: индекс НЕ меняется при wheel.
  3. scrollbar: колесо НЕ блокируется (фильтр вернул False) — прокрутка жива.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QScrollBar, QSpinBox

from multiprocess_prototype.frontend.wheel_guard import WheelGuard


def _wheel_event() -> QWheelEvent:
    """Скролл вверх на один «щелчок» (120 единиц)."""
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_spinbox_value_unchanged_on_wheel(qtbot) -> None:
    guard = WheelGuard()
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    qtbot.addWidget(spin)
    consumed = guard.eventFilter(spin, _wheel_event())
    assert consumed is True  # событие съедено
    assert spin.value() == 10  # значение не уехало


def test_combobox_index_unchanged_on_wheel(qtbot) -> None:
    guard = WheelGuard()
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    combo.setCurrentIndex(1)
    qtbot.addWidget(combo)
    consumed = guard.eventFilter(combo, _wheel_event())
    assert consumed is True
    assert combo.currentIndex() == 1


def test_scrollbar_wheel_not_blocked(qtbot) -> None:
    guard = WheelGuard()
    bar = QScrollBar(Qt.Orientation.Vertical)
    qtbot.addWidget(bar)
    # QScrollBar — наследник QAbstractSlider, но колесо ему нужно → не блокируем.
    assert guard.eventFilter(bar, _wheel_event()) is False


def test_non_wheel_event_passes_through(qtbot) -> None:
    guard = WheelGuard()
    spin = QSpinBox()
    qtbot.addWidget(spin)
    assert guard.eventFilter(spin, QEvent(QEvent.Type.MouseButtonPress)) is False
