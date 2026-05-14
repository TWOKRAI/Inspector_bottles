# -*- coding: utf-8 -*-
"""
ImagePanelWidget — виджет отображения одного или нескольких изображений.

Конфиг: image_slots: [{id, label, visible_default}, ...]
Методы: display_frame(slot_id, frame), display_frames(dict).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QImage,
    QLabel,
    QPixmap,
    QSize,
    QWidget,
    Qt,
)

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def _frame_to_pixmap(frame: Any, label_size: QSize) -> QPixmap:
    """Конвертировать BGR numpy frame в QPixmap для label."""
    if frame is None or (HAS_NUMPY and hasattr(frame, "size") and frame.size == 0):
        return QPixmap()
    if not HAS_NUMPY:
        return QPixmap()
    h, w, ch = frame.shape
    bytes_per_line = ch * w
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
    pixmap = QPixmap.fromImage(q_img)
    return pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class ImagePanelWidget(QWidget):
    """
    Виджет с N слотами для изображений по конфигу.

    Конфиг:
        image_slots: [{"id": "original", "label": "Original", "visible_default": True}, ...]
    """

    def __init__(
        self,
        *,
        image_slots: Optional[List[Dict[str, Any]]] = None,
        min_slot_width: int = 280,
        min_slot_height: int = 180,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._slots_config = image_slots or [
            {"id": "original", "label": "Original", "visible_default": True},
            {"id": "mask", "label": "Mask", "visible_default": True},
        ]
        self._min_slot_width = min_slot_width
        self._min_slot_height = min_slot_height
        self._labels: Dict[str, QLabel] = {}
        self._visible: Dict[str, bool] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for slot_cfg in self._slots_config:
            slot_id = slot_cfg.get("id", "slot")
            label_text = slot_cfg.get("label", slot_id)
            visible_default = slot_cfg.get("visible_default", True)
            self._visible[slot_id] = visible_default

            lbl = QLabel(f"{label_text} (waiting...)")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumSize(self._min_slot_width, self._min_slot_height)
            lbl.setStyleSheet("background-color: #1e1e1e; color: white;")
            self._labels[slot_id] = lbl
            layout.addWidget(lbl, 1)

    def display_frame(self, slot_id: str, frame: Any) -> None:
        """Отобразить кадр в указанном слоте."""
        lbl = self._labels.get(slot_id)
        if lbl is None:
            return
        if not self._visible.get(slot_id, True):
            lbl.setText(f"{slot_id} (off)")
            lbl.setPixmap(QPixmap())
            return
        if frame is None or (HAS_NUMPY and hasattr(frame, "size") and frame.size == 0):
            lbl.setText(f"{slot_id} (waiting...)")
            lbl.setPixmap(QPixmap())
            return
        pix = _frame_to_pixmap(frame, lbl.size())
        lbl.setPixmap(pix)
        lbl.setText("")

    def display_frames(self, frames: Dict[str, Any]) -> None:
        """Отобразить несколько кадров: {slot_id: frame}."""
        for slot_id, frame in frames.items():
            self.display_frame(slot_id, frame)

    def set_slot_visible(self, slot_id: str, visible: bool) -> None:
        """Установить видимость слота."""
        self._visible[slot_id] = visible
        lbl = self._labels.get(slot_id)
        if lbl and not visible:
            lbl.setText(f"{slot_id} (off)")
            lbl.setPixmap(QPixmap())
