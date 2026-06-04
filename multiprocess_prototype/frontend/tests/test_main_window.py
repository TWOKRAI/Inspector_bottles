"""Тесты MainWindow v2 Layout (Task 9.3)."""

from PySide6.QtWidgets import QTabWidget, QWidget

from multiprocess_prototype.frontend.windows.main_window import MainWindow
from multiprocess_prototype.frontend.widgets.chrome.app_header import AppHeaderWidget


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
    """Central layout содержит 4 виджета: header, error_banner, placeholder, tab_widget."""
    window = MainWindow()
    qtbot.addWidget(window)

    layout = window._layout
    assert layout.count() == 4

    # Порядок: header (0), error_banner (1), placeholder (2), tab_widget (3)
    assert layout.itemAt(0).widget() is window._header
    assert layout.itemAt(1).widget() is window._error_banner
    assert layout.itemAt(2).widget() is window._image_panel_placeholder
    assert layout.itemAt(3).widget() is window._tab_widget


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


# -- Header update_status --


def test_header_status_text(qtbot):
    """update_status обновляет StatusLabel."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.header.update_status("Online")
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
    """update_status обновляет fps и latency labels в StatusBar и header."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.update_status(fps=30.5, latency_ms=12.3)
    assert window._fps_label.text() == "FPS: 30.5"
    assert window._latency_label.text() == "Latency: 12.3 ms"
    # Header тоже обновляется
    assert "30.5" in window.header._status_label.text()
    assert "12.3" in window.header._status_label.text()


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

    # Виджет на позиции 2 теперь — real_panel (header=0, error_banner=1, image=2, tabs=3)
    layout = window._layout
    assert layout.itemAt(2).widget() is real_panel
    assert window._image_panel is real_panel

    # Общее количество виджетов в layout осталось 4
    assert layout.count() == 4


# -- Undo/Redo controller (G.4.4: единая шина undo) --


class _FakeUndoController:
    """Минимальный UndoRedoController со счётчиками вызовов."""

    def __init__(self) -> None:
        self.undo_calls = 0
        self.redo_calls = 0
        self.callbacks: list = []

    def undo(self) -> bool:
        self.undo_calls += 1
        return True

    def redo(self) -> bool:
        self.redo_calls += 1
        return True

    def can_undo(self) -> bool:
        return True

    def can_redo(self) -> bool:
        return True

    def add_change_callback(self, cb) -> None:
        self.callbacks.append(cb)


def test_set_undo_controller_delegates_undo_redo(qtbot):
    """G.4.4: _on_undo/_on_redo делегируют в установленный controller (единая шина)."""
    window = MainWindow()
    qtbot.addWidget(window)
    controller = _FakeUndoController()

    window.set_undo_controller(controller)
    window._on_undo()
    window._on_redo()

    assert controller.undo_calls == 1
    assert controller.redo_calls == 1


def test_on_undo_redo_noop_without_controller(qtbot):
    """Без установленного controller _on_undo/_on_redo — безопасный no-op."""
    window = MainWindow()
    qtbot.addWidget(window)

    # set_undo_controller не вызывался → _undo_controller is None
    window._on_undo()
    window._on_redo()  # не должно бросать исключений


# -- Frame-trace аккумулятор (Task 3 frame-trace-envelope) --


def test_trace_segments_none_when_empty(qtbot):
    """reset_trace_segments → None, если трасс не накапливали."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.reset_trace_segments() is None


def test_trace_segments_average_and_order(qtbot):
    """Сегменты усредняются по label, порядок = порядок появления."""
    window = MainWindow()
    qtbot.addWidget(window)

    frame1 = [
        {"kind": "transport", "from": "cam", "to": "detector", "ms": 2.0},
        {"kind": "process", "node": "detector", "plugin": "hsv", "ms": 1.0},
    ]
    frame2 = [
        {"kind": "transport", "from": "cam", "to": "detector", "ms": 4.0},
        {"kind": "process", "node": "detector", "plugin": "hsv", "ms": 3.0},
    ]
    window.record_trace_spans(frame1)
    window.record_trace_spans(frame2)

    segments = window.reset_trace_segments()
    assert segments == [
        {"label": "cam→detector", "kind": "transport", "ms": 3.0},
        {"label": "detector:hsv", "kind": "process", "ms": 2.0},
    ]
    # Сброс после чтения.
    assert window.reset_trace_segments() is None


def test_trace_segments_ignores_garbage(qtbot):
    """Не-список / битые спаны молча игнорируются."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.record_trace_spans(None)
    window.record_trace_spans("nope")
    window.record_trace_spans([{"kind": "process"}, 42, {"kind": "x", "ms": 1.0}])

    assert window.reset_trace_segments() is None
