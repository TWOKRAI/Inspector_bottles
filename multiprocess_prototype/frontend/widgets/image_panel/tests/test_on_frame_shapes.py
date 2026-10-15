# -*- coding: utf-8 -*-
"""Формы кадров в ImagePanelPresenter.on_frame (pytest-qt, настоящие виджеты).

Регрессия 2026-10-15: серый кадр камеры (H×W, 1 канал, image/gray) шёл в трёхканальную ветку,
Qt читал 3*w*h байт из буфера w*h — процесс gui падал с 0xC0000005 без трейсбека.

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_on_frame_shapes.py -v
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QColor

from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

_H, _W = 1024, 1280


@pytest.fixture()
def panel(qtbot):
    w = ImagePanelWidget()
    qtbot.addWidget(w)
    w.set_displays([{"id": "main", "label": "Main", "enabled": True, "x": 0, "y": 0}])
    return w


def _shown(panel) -> tuple[QColor, QColor, str]:
    """Цвет у левого и правого края показанной картинки и текст placeholder."""
    label = panel._presenter._slots["main"]._label
    pm = label.pixmap()
    if pm is None or pm.isNull():
        return QColor(), QColor(), label.text()
    img = pm.toImage()
    y = img.height() // 2
    return img.pixelColor(int(img.width() * 0.1), y), img.pixelColor(int(img.width() * 0.9), y), label.text()


def test_серый_кадр_показывается_без_падения(panel) -> None:
    gray = np.zeros((_H, _W), dtype=np.uint8)
    gray[:, _W // 2 :] = 255  # левая половина чёрная, правая белая

    panel.display_frame("main", gray)

    left, right, text = _shown(panel)
    assert text == ""
    assert (left.red(), left.green(), left.blue()) == (0, 0, 0)
    assert (right.red(), right.green(), right.blue()) == (255, 255, 255)


def test_серый_кадр_с_осью_каналов_один_показывается(panel) -> None:
    gray = np.zeros((_H, _W, 1), dtype=np.uint8)
    gray[:, _W // 2 :, 0] = 255

    panel.display_frame("main", gray)

    left, right, text = _shown(panel)
    assert text == ""
    assert (left.red(), right.red()) == (0, 255)


def test_bgr_кадр_по_прежнему_переставляет_каналы(panel) -> None:
    bgr = np.zeros((_H, _W, 3), dtype=np.uint8)
    bgr[:, : _W // 2, 0] = 255  # слева синий канал (BGR), справа красный
    bgr[:, _W // 2 :, 2] = 255

    panel.display_frame("main", bgr)

    left, right, text = _shown(panel)
    assert text == ""
    assert (left.red(), left.green(), left.blue()) == (0, 0, 255)
    assert (right.red(), right.green(), right.blue()) == (255, 0, 0)


def test_неподдерживаемая_форма_даёт_placeholder_а_не_падение(panel) -> None:
    bgra = np.zeros((_H, _W, 4), dtype=np.uint8)

    panel.display_frame("main", bgra)

    _, _, text = _shown(panel)
    assert text == "Ошибка кадра"
