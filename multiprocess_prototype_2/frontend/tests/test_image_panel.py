"""Тесты ImagePanelWidget, DisplaySlot, ImagePanelPresenter (Task 9.4)."""
import numpy as np
import pytest
from PySide6.QtGui import QPixmap

from multiprocess_prototype_2.frontend.widgets.image_panel import (
    ImagePanelWidget,
    DisplaySlot,
    ImagePanelPresenter,
)


# ---------------------------------------------------------------------------
# DisplaySlot
# ---------------------------------------------------------------------------


def test_display_slot_object_name(qtbot):
    """DisplaySlot должен иметь objectName='ImageSlot'."""
    slot = DisplaySlot(slot_id="test")
    qtbot.addWidget(slot)
    assert slot.objectName() == "ImageSlot"


def test_display_slot_initial_placeholder(qtbot):
    """DisplaySlot без label показывает 'Нет сигнала' по умолчанию."""
    slot = DisplaySlot(slot_id="main")
    qtbot.addWidget(slot)
    assert slot._label.text() == "Нет сигнала"


def test_display_slot_custom_label(qtbot):
    """DisplaySlot с label показывает label как placeholder."""
    slot = DisplaySlot(slot_id="cam", label="Camera 1")
    qtbot.addWidget(slot)
    assert slot._label.text() == "Camera 1"


def test_display_slot_set_placeholder(qtbot):
    """set_placeholder() меняет текст label."""
    slot = DisplaySlot(slot_id="x")
    qtbot.addWidget(slot)
    slot.set_placeholder("Offline")
    assert slot._label.text() == "Offline"


def test_display_slot_update_pixmap(qtbot):
    """update_pixmap() устанавливает pixmap в label."""
    slot = DisplaySlot(slot_id="main")
    qtbot.addWidget(slot)
    slot.show()

    pixmap = QPixmap(100, 100)
    pixmap.fill()
    slot.update_pixmap(pixmap)

    assert slot._label.pixmap() is not None
    assert not slot._label.pixmap().isNull()


def test_display_slot_id(qtbot):
    """slot_id доступен через свойство."""
    slot = DisplaySlot(slot_id="alpha")
    qtbot.addWidget(slot)
    assert slot.slot_id == "alpha"


# ---------------------------------------------------------------------------
# ImagePanelPresenter
# ---------------------------------------------------------------------------


def test_presenter_register_unregister(qtbot):
    """register_slot / unregister_slot добавляют и удаляют слот."""
    presenter = ImagePanelPresenter()
    slot = DisplaySlot(slot_id="s1")
    qtbot.addWidget(slot)

    presenter.register_slot("s1", slot)
    assert "s1" in presenter.slot_ids

    presenter.unregister_slot("s1")
    assert "s1" not in presenter.slot_ids


def test_presenter_unregister_unknown_no_crash(qtbot):
    """unregister_slot для неизвестного id не падает."""
    presenter = ImagePanelPresenter()
    # Не должно вызывать исключений
    presenter.unregister_slot("nonexistent")


def test_presenter_on_frame_valid(qtbot):
    """on_frame() с валидным BGR numpy array устанавливает pixmap в слот."""
    presenter = ImagePanelPresenter()
    slot = DisplaySlot(slot_id="main")
    qtbot.addWidget(slot)
    slot.show()

    presenter.register_slot("main", slot)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 2] = 200  # красный канал в BGR

    presenter.on_frame("main", frame)

    assert slot._label.pixmap() is not None
    assert not slot._label.pixmap().isNull()


def test_presenter_on_frame_none(qtbot):
    """on_frame() с frame=None устанавливает placeholder 'Нет сигнала'."""
    presenter = ImagePanelPresenter()
    slot = DisplaySlot(slot_id="main")
    qtbot.addWidget(slot)
    slot.show()

    presenter.register_slot("main", slot)

    # Сначала покажем кадр, потом None
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    presenter.on_frame("main", frame)

    presenter.on_frame("main", None)
    assert slot._label.text() == "Нет сигнала"


def test_presenter_on_frame_unknown_slot_no_crash(qtbot):
    """on_frame() для неизвестного slot_id не вызывает исключений."""
    presenter = ImagePanelPresenter()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    # Не должно вызывать исключений
    presenter.on_frame("ghost", frame)


def test_presenter_on_frames(qtbot):
    """on_frames() обрабатывает несколько кадров сразу."""
    presenter = ImagePanelPresenter()

    slot_a = DisplaySlot(slot_id="a")
    slot_b = DisplaySlot(slot_id="b")
    qtbot.addWidget(slot_a)
    qtbot.addWidget(slot_b)
    slot_a.show()
    slot_b.show()

    presenter.register_slot("a", slot_a)
    presenter.register_slot("b", slot_b)

    frames = {
        "a": np.zeros((240, 320, 3), dtype=np.uint8),
        "b": np.ones((240, 320, 3), dtype=np.uint8) * 128,
    }
    presenter.on_frames(frames)

    assert slot_a._label.pixmap() is not None
    assert not slot_a._label.pixmap().isNull()
    assert slot_b._label.pixmap() is not None
    assert not slot_b._label.pixmap().isNull()


# ---------------------------------------------------------------------------
# ImagePanelWidget
# ---------------------------------------------------------------------------


def test_widget_default_config(qtbot):
    """По умолчанию создаётся 1 слот 'main'."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    assert len(panel.slot_ids) == 1
    assert "main" in panel.slot_ids


def test_widget_custom_slots(qtbot):
    """Кастомный конфиг создаёт нужное количество слотов."""
    panel = ImagePanelWidget(slots=[
        {"id": "original", "label": "Original"},
        {"id": "processed", "label": "Processed"},
    ])
    qtbot.addWidget(panel)

    assert len(panel.slot_ids) == 2
    assert "original" in panel.slot_ids
    assert "processed" in panel.slot_ids


def test_widget_add_slot(qtbot):
    """add_slot() добавляет новый слот и возвращает DisplaySlot."""
    panel = ImagePanelWidget(slots=[])
    qtbot.addWidget(panel)

    slot = panel.add_slot("cam1", label="Camera 1")

    assert isinstance(slot, DisplaySlot)
    assert "cam1" in panel.slot_ids
    assert slot.slot_id == "cam1"


def test_widget_add_slot_duplicate_returns_existing(qtbot):
    """add_slot() для дублирующего id возвращает существующий слот."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    original = panel._slots["main"]
    duplicate = panel.add_slot("main")

    assert duplicate is original
    assert len(panel.slot_ids) == 1


def test_widget_remove_slot(qtbot):
    """remove_slot() удаляет слот из панели."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    panel.remove_slot("main")
    assert "main" not in panel.slot_ids
    assert len(panel.slot_ids) == 0


def test_widget_remove_slot_unknown_no_crash(qtbot):
    """remove_slot() для несуществующего id не вызывает исключений."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    # Не должно вызывать исключений
    panel.remove_slot("ghost_slot")


def test_widget_display_frame(qtbot):
    """display_frame() с валидным кадром устанавливает pixmap в слот."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)
    panel.show()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 0] = 100  # синий канал в BGR

    panel.display_frame("main", frame)

    slot = panel._slots["main"]
    assert slot._label.pixmap() is not None
    assert not slot._label.pixmap().isNull()


def test_widget_display_frame_unknown_no_crash(qtbot):
    """display_frame() для несуществующего slot_id не вызывает исключений."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    # Не должно вызывать исключений
    panel.display_frame("nonexistent", frame)


def test_widget_display_frames(qtbot):
    """display_frames() обрабатывает несколько слотов."""
    panel = ImagePanelWidget(slots=[
        {"id": "left", "label": "Left"},
        {"id": "right", "label": "Right"},
    ])
    qtbot.addWidget(panel)
    panel.show()

    frames = {
        "left": np.zeros((240, 320, 3), dtype=np.uint8),
        "right": np.ones((240, 320, 3), dtype=np.uint8) * 50,
    }
    panel.display_frames(frames)

    for sid in ("left", "right"):
        slot = panel._slots[sid]
        assert slot._label.pixmap() is not None
        assert not slot._label.pixmap().isNull()


def test_widget_presenter_property(qtbot):
    """Свойство presenter возвращает ImagePanelPresenter."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)

    assert isinstance(panel.presenter, ImagePanelPresenter)


def test_widget_slot_object_names(qtbot):
    """Все слоты имеют objectName='ImageSlot'."""
    panel = ImagePanelWidget(slots=[
        {"id": "a"},
        {"id": "b"},
    ])
    qtbot.addWidget(panel)

    for slot_id in ("a", "b"):
        slot = panel._slots[slot_id]
        assert slot.objectName() == "ImageSlot"


def test_widget_placeholder_none_frame(qtbot):
    """display_frame(None) устанавливает placeholder 'Нет сигнала'."""
    panel = ImagePanelWidget()
    qtbot.addWidget(panel)
    panel.show()

    # Сначала покажем кадр
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    panel.display_frame("main", frame)

    # Затем — None
    panel.display_frame("main", None)

    slot = panel._slots["main"]
    assert slot._label.text() == "Нет сигнала"
