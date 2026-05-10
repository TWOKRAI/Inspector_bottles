"""ImagePanelPresenter — управляет набором DisplaySlot'ов."""
import logging

import numpy as np
from PySide6.QtGui import QImage, QPixmap

from .display_slot import DisplaySlot

logger = logging.getLogger(__name__)


class ImagePanelPresenter:
    """MVP presenter для ImagePanel.

    Хранит словарь зарегистрированных слотов и маршрутизирует
    BGR numpy-кадры в нужный DisplaySlot через конвертацию → QPixmap.
    """

    def __init__(self):
        # slot_id → DisplaySlot
        self._slots: dict[str, DisplaySlot] = {}

    # ------------------------------------------------------------------
    # Регистрация слотов
    # ------------------------------------------------------------------

    def register_slot(self, slot_id: str, slot: DisplaySlot) -> None:
        """Зарегистрировать слот под заданным идентификатором."""
        self._slots[slot_id] = slot
        logger.debug("Слот зарегистрирован: %s", slot_id)

    def unregister_slot(self, slot_id: str) -> None:
        """Удалить слот из presenter'а. Предупреждение если не найден."""
        if slot_id not in self._slots:
            logger.warning("unregister_slot: слот '%s' не найден", slot_id)
            return
        del self._slots[slot_id]
        logger.debug("Слот удалён: %s", slot_id)

    @property
    def slot_ids(self) -> list[str]:
        """Список зарегистрированных идентификаторов слотов."""
        return list(self._slots.keys())

    # ------------------------------------------------------------------
    # Отображение кадров
    # ------------------------------------------------------------------

    def on_frame(self, slot_id: str, frame) -> None:
        """Получен BGR-кадр для слота slot_id.

        Конвертирует numpy (BGR) → QImage → QPixmap → DisplaySlot.update_pixmap.
        При frame=None или пустом — показывает placeholder "Нет сигнала".
        При неизвестном slot_id — предупреждение в лог.
        """
        if slot_id not in self._slots:
            logger.warning("on_frame: неизвестный slot_id '%s'", slot_id)
            return

        slot = self._slots[slot_id]

        # Проверка валидности кадра
        if frame is None or (isinstance(frame, np.ndarray) and frame.size == 0):
            slot.set_placeholder("Нет сигнала")
            return

        try:
            # BGR → RGB: инвертируем порядок каналов (как в CameraPresenter)
            rgb = frame[..., ::-1].copy()  # copy() гарантирует contiguous memory
            h, w = rgb.shape[:2]
            bytes_per_line = 3 * w

            qimage = QImage(
                rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
            )
            pixmap = QPixmap.fromImage(qimage)
            slot.update_pixmap(pixmap)
        except Exception as exc:
            logger.error("Ошибка конвертации кадра для слота '%s': %s", slot_id, exc)
            slot.set_placeholder("Ошибка кадра")

    def on_frames(self, frames: dict) -> None:
        """Обработать несколько кадров сразу.

        frames: dict[slot_id, np.ndarray]
        """
        for slot_id, frame in frames.items():
            self.on_frame(slot_id, frame)
