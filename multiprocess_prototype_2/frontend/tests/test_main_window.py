"""Тесты MainWindow v2 Layout (Task 9.3)."""
import pytest
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from multiprocess_prototype_2.frontend.windows.main_window import MainWindow
from multiprocess_prototype_2.frontend.widgets.chrome.app_header import AppHeaderWidget


# -- Создание с дефолтным конфигом --

def test_default_config(qtbot):
    """MainWindow с дефолтным конфигом: заголовок, min size."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == "Inspector v2"
    assert window.minimumWidth() == 1024
    assert window.minimumHeight() == 768


# -- Создание с кастомным конфигом --

def test_custom_config(qtbot):
    """MainWindow принимает dict-конфиг и корректно применяет."""
    cfg = {"window": {"title": "Custom Title", "min_width": 800, "min_height": 600}}
    window = MainWindow(config=cfg)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Custom Title"
    assert window.minimumWidth() == 800
    assert window.minimumHeight() == 600


# -- Layout содержит 3 компонента --

def test_layout_has_three_zones(qtbot):
    """Central layout содержит 3 виджета: header, placeholder, tab_widget."""
    window = MainWindow()
    qtbot.addWidget(window)

    layout = window._layout
    assert layout.count() == 3

    # Порядок: header (0), placeholder (1), tab_widget (2)
    assert layout.itemAt(0).widget() is window._header
    assert layout.itemAt(1).widget() is window._image_panel_placeholder
    assert layout.itemAt(2).widget() is window._tab_widget


# -- Header property --

def test_header_property(qtbot):
    """header property возвращает AppHeaderWidget с objectName='AppHeader'."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window.header, AppHeaderWidget)
    assert window.header.objectName() == "AppHeader"


# -- AppHeaderWidget содержит INNOTECH --

def test_header_brand_label(qtbot):
    """AppHeaderWidget содержит BrandLabel с текстом 'INNOTECH'."""
    window = MainWindow()
    qtbot.addWidget(window)

    brand = window.header._brand_label
    assert brand.text() == "INNOTECH"
    assert brand.objectName() == "BrandLabel"


# -- Header update_status_text --

def test_header_status_text(qtbot):
    """update_status_text обновляет StatusLabel."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.header.update_status_text("Online")
    assert window.header._status_label.text() == "Online"


# -- add_tab (обратная совместимость) --

def test_add_tab(qtbot):
    """add_tab добавляет вкладку, tab_widget.count() увеличивается."""
    window = MainWindow()
    qtbot.addWidget(window)

    dummy = QWidget()
    qtbot.addWidget(dummy)

    idx = window.add_tab(dummy, "Test Tab")
    assert idx == 0
    assert window.tab_widget.count() == 1


# -- tab_widget property --

def test_tab_widget_property(qtbot):
    """tab_widget property возвращает QTabWidget."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window.tab_widget, QTabWidget)


# -- update_status (обратная совместимость) --

def test_update_status(qtbot):
    """update_status обновляет fps и latency labels в StatusBar."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.update_status(fps=30.5, latency_ms=12.3)
    assert window._fps_label.text() == "FPS: 30.5"
    assert window._latency_label.text() == "Latency: 12.3 ms"


# -- frame count (обратная совместимость) --

def test_frame_count(qtbot):
    """increment_frame_count + reset_frame_count работают корректно."""
    window = MainWindow()
    qtbot.addWidget(window)

    for _ in range(5):
        window.increment_frame_count()

    count = window.reset_frame_count()
    assert count == 5
    assert window._frame_count == 0


# -- set_image_panel заменяет placeholder --

def test_set_image_panel(qtbot):
    """set_image_panel заменяет placeholder на реальный виджет."""
    window = MainWindow()
    qtbot.addWidget(window)

    real_panel = QWidget()
    real_panel.setObjectName("RealImagePanel")
    qtbot.addWidget(real_panel)

    window.set_image_panel(real_panel)

    # Виджет на позиции 1 теперь — real_panel
    layout = window._layout
    assert layout.itemAt(1).widget() is real_panel
    assert window._image_panel is real_panel

    # Общее количество виджетов в layout осталось 3
    assert layout.count() == 3
