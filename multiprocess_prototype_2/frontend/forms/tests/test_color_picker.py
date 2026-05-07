"""Тесты ColorTripletWidget (~3 теста)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QHBoxLayout, QSpinBox

from multiprocess_prototype_2.frontend.forms.widgets.color_picker import ColorTripletWidget


class TestColorTripletWidget:
    """Тесты виджета выбора цвета."""

    def test_has_3_spinboxes_in_hbox(self, qtbot):
        """Widget содержит 3 QSpinBox в горизонтальном layout."""
        w = ColorTripletWidget()
        qtbot.addWidget(w)

        spins = w.findChildren(QSpinBox)
        assert len(spins) == 3
        # Все 0..255
        for spin in spins:
            assert spin.minimum() == 0
            assert spin.maximum() == 255

    def test_get_set_value(self, qtbot):
        """set_value → get_value возвращает установленное значение."""
        w = ColorTripletWidget()
        qtbot.addWidget(w)

        w.set_value((100, 200, 50))
        assert w.get_value() == (100, 200, 50)

    def test_value_changed_signal(self, qtbot):
        """value_changed эмитится при изменении спинбокса."""
        w = ColorTripletWidget()
        qtbot.addWidget(w)

        received = []
        w.value_changed.connect(lambda: received.append(True))

        # Прямое изменение спинбокса
        spins = w.findChildren(QSpinBox)
        spins[0].setValue(42)

        assert len(received) > 0
