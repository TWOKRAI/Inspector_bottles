"""Тесты MainWindow, CameraView и CameraPresenter (Task 4.2)."""
import numpy as np
import pytest
from PySide6.QtGui import QPixmap

from multiprocess_prototype.frontend.widgets.camera.view import CameraView
from multiprocess_prototype.frontend.widgets.camera.presenter import CameraPresenter
from multiprocess_prototype.frontend.windows.main_window import MainWindow


def test_camera_view_placeholder(qtbot):
    """CameraView при создании показывает placeholder 'Нет сигнала'."""
    view = CameraView()
    qtbot.addWidget(view)
    assert view._label.text() == "Нет сигнала"


def test_camera_view_update_pixmap(qtbot):
    """update_pixmap() устанавливает pixmap в label."""
    view = CameraView()
    qtbot.addWidget(view)
    view.show()

    pixmap = QPixmap(100, 100)
    pixmap.fill()
    view.update_pixmap(pixmap)

    assert view._label.pixmap() is not None
    assert not view._label.pixmap().isNull()


def test_camera_presenter_on_frame(qtbot):
    """on_frame() с BGR numpy array приводит к установке pixmap в view."""
    view = CameraView()
    qtbot.addWidget(view)
    view.show()

    presenter = CameraPresenter(view)

    # Создать синтетический BGR-кадр
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 2] = 200  # красный канал в BGR

    presenter.on_frame(frame)

    assert view._label.pixmap() is not None
    assert not view._label.pixmap().isNull()


def test_camera_presenter_on_no_signal(qtbot):
    """on_no_signal() устанавливает placeholder 'Нет сигнала'."""
    view = CameraView()
    qtbot.addWidget(view)

    presenter = CameraPresenter(view)

    # Сначала установим pixmap, затем вызовем on_no_signal
    pixmap = QPixmap(100, 100)
    pixmap.fill()
    view.update_pixmap(pixmap)

    presenter.on_no_signal()

    assert view._label.text() == "Нет сигнала"


def test_main_window_tabs(qtbot):
    """add_tab() добавляет вкладку; tab count становится 1."""
    window = MainWindow()
    qtbot.addWidget(window)

    dummy = CameraView()
    qtbot.addWidget(dummy)

    window.add_tab(dummy, "Camera")

    assert window.tab_widget.count() == 1


def test_main_window_fps_counter(qtbot):
    """increment_frame_count() × 5 → reset_frame_count() возвращает 5 и сбрасывает счётчик."""
    window = MainWindow()
    qtbot.addWidget(window)

    for _ in range(5):
        window.increment_frame_count()

    count = window.reset_frame_count()
    assert count == 5
    # После сброса счётчик равен нулю
    assert window._frame_count == 0
