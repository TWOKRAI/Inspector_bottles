# multiprocess_prototype\tests\test_gui_checkboxes.py
"""
Тест InspectorWindow: чекбоксы вызывают process.gui_set_*.

Unit-тест с mock process.
Требует DISPLAY для PyQt5.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.skip(reason="Legacy InspectorWindow removed; use MainWindow/ProcessingTabWidget tests")


def test_gui_checkboxes_call_process_methods():
    """Чекбоксы при изменении вызывают process.gui_set_show_original, gui_set_show_mask, gui_set_draw_contours."""
    from PyQt5.QtCore import Qt
    from multiprocess_prototype.frontend.windows.inspector_window import InspectorWindow

    mock_process = MagicMock()
    window = InspectorWindow("Test", 800, 600, mock_process)

    window._on_show_original_changed(Qt.Checked)
    mock_process.gui_set_show_original.assert_called_with(True)
    mock_process.reset_mock()

    window._on_show_original_changed(Qt.Unchecked)
    mock_process.gui_set_show_original.assert_called_with(False)
    mock_process.reset_mock()

    window._on_show_mask_changed(Qt.Checked)
    mock_process.gui_set_show_mask.assert_called_with(True)
    mock_process.reset_mock()

    window._on_draw_contours_changed(Qt.Unchecked)
    mock_process.gui_set_draw_contours.assert_called_with(False)


def test_update_frame_dual_images():
    """update_frame принимает original_frame и mask_frame."""
    from multiprocess_prototype.frontend.windows.inspector_window import InspectorWindow

    mock_process = MagicMock()
    window = InspectorWindow("Test", 800, 600, mock_process)

    orig = np.zeros((240, 320, 3), dtype=np.uint8)
    orig[:] = [100, 100, 100]
    mask = np.zeros((240, 320, 3), dtype=np.uint8)
    mask[:] = [50, 50, 50]

    window.update_frame(orig, mask, frame_id=1, show_original=True, show_mask=True)
    assert window._frame_count == 1
    assert window._video_label_original.pixmap() is not None
    assert window._video_label_mask.pixmap() is not None
