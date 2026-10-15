"""ImagePanelPresenter — управляет набором DisplaySlot'ов."""

from multiprocess_framework.modules.logger_module import get_std_logger

import numpy as np
from PySide6.QtGui import QImage, QPixmap

from .display_slot import DisplaySlot

logger = get_std_logger(__name__)

# Что принимает дисплей — текст для строки «Кадр отвергнут» (R.1, plans/code-reader-gui.md).
_EXPECTED_FRAME = "uint8 gray (H, W)|(H, W, 1) или BGR (H, W, 3)"


def _is_supported_frame(frame) -> bool:
    """uint8 gray (H, W) | (H, W, 1) или BGR (H, W, 3). Остальное — отказ до QImage."""
    return (
        isinstance(frame, np.ndarray)
        and frame.dtype == np.uint8
        and (frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] in (1, 3)))
    )


def _reject_key(slot_id: str, frame) -> tuple:
    """Причина отказа для троттлинга лога: слот + (dtype, ndim, число каналов)."""
    if not isinstance(frame, np.ndarray):
        return (slot_id, type(frame).__name__, None, None)
    channels = frame.shape[2] if frame.ndim == 3 else None
    return (slot_id, str(frame.dtype), frame.ndim, channels)


def _describe_frame(frame) -> str:
    """Что пришло: shape, dtype, contiguous, nbytes (без разделителей)."""
    if not isinstance(frame, np.ndarray):
        return f"тип={type(frame).__name__} (не numpy-массив)"
    return (
        f"shape={frame.shape}, dtype={frame.dtype}, "
        f"contiguous={bool(frame.flags['C_CONTIGUOUS'])}, nbytes={int(frame.nbytes)}"
    )


class ImagePanelPresenter:
    """MVP presenter для ImagePanel.

    Хранит словарь зарегистрированных слотов и маршрутизирует
    BGR numpy-кадры в нужный DisplaySlot через конвертацию → QPixmap.
    """

    def __init__(self):
        # slot_id → DisplaySlot
        self._slots: dict[str, DisplaySlot] = {}
        # slot_id → последний валидный кадр (для снимка/grab). Храним ссылку (дёшево);
        # снимок — редкая ручная операция, риск рассинхрона кадра приемлем.
        self._last_frames: dict = {}
        # slot_id незарегистрированных слотов, по которым уже выдано предупреждение.
        # Источник (например phone_camera) может слать ~30 fps на дисплей, который
        # выключен (enabled: false) — но всё ещё привязан в routing. Без троттлинга
        # это заливает лог одинаковыми строками. Предупреждаем один раз на slot_id.
        self._warned_unknown_slots: set[str] = set()
        # slot_id → счётчики кадров {"received", "shown", "rejected"} (R.1).
        self._frame_stats: dict[str, dict[str, int]] = {}
        # Причины отказа, по которым уже выдан WARNING: (slot_id, dtype, ndim, каналы).
        # Повтор той же причины не пишет вторую строку (счётчик растёт всегда).
        self._warned_rejects: set[tuple] = set()

    # ------------------------------------------------------------------
    # Регистрация слотов
    # ------------------------------------------------------------------

    def register_slot(self, slot_id: str, slot: DisplaySlot) -> None:
        """Зарегистрировать слот под заданным идентификатором."""
        self._slots[slot_id] = slot
        # Слот снова доступен — сбросить флаг «уже предупредили», чтобы при
        # повторном выключении дисплея предупреждение выдалось ещё раз.
        self._warned_unknown_slots.discard(slot_id)
        self._warned_rejects = {k for k in self._warned_rejects if k[0] != slot_id}
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
        """Получен кадр (uint8 gray или BGR) для слота slot_id.

        Конвертирует numpy → QImage → QPixmap → DisplaySlot.update_pixmap.
        При frame=None или пустом — показывает placeholder "Нет сигнала".
        Кадр другой формы/dtype отвергается до QImage: placeholder "Ошибка кадра",
        одна строка WARNING на причину, счётчик rejected (см. frame_stats).
        При неизвестном slot_id — кадр тихо отбрасывается; предупреждение в лог
        выдаётся один раз на slot_id (иначе живой источник на выключенный дисплей
        заливает лог — см. self._warned_unknown_slots).
        """
        if slot_id not in self._slots:
            if slot_id not in self._warned_unknown_slots:
                self._warned_unknown_slots.add(slot_id)
                logger.warning(
                    "on_frame: неизвестный slot_id '%s' — кадры отбрасываются "
                    "(дисплей выключен или нет привязки); далее без повтора",
                    slot_id,
                )
            return

        slot = self._slots[slot_id]

        stats = self._frame_stats.setdefault(slot_id, {"received": 0, "shown": 0, "rejected": 0})
        stats["received"] += 1

        # Проверка валидности кадра
        if frame is None or (isinstance(frame, np.ndarray) and frame.size == 0):
            slot.set_placeholder("Нет сигнала")
            return

        # Проверка формы ДО QImage: Qt читает буфер по заявленной ширине/формату,
        # чужая форма или dtype — чтение за границей буфера (нативное падение GUI).
        if not _is_supported_frame(frame):
            stats["rejected"] += 1
            self._warn_rejected(slot_id, frame)
            slot.set_placeholder("Ошибка кадра")
            return

        # Запомнить последний валидный кадр для снимка (grab_frame).
        self._last_frames[slot_id] = frame

        try:
            if frame.ndim == 3 and frame.shape[2] == 1:
                frame = frame[..., 0]
            if frame.ndim == 2:
                # Серый кадр (H×W, 1 канал, image/gray). Трёхканальная ветка ниже читала бы
                # 3*w*h байт из буфера w*h — нативное падение GUI (0xC0000005, 2026-10-15).
                gray = np.ascontiguousarray(frame)
                h, w = gray.shape
                qimage = QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8)
            else:
                # BGR → RGB: инвертируем порядок каналов (как в CameraPresenter)
                rgb = frame[..., ::-1].copy()  # copy() гарантирует contiguous memory
                h, w = rgb.shape[:2]
                qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)
            slot.update_pixmap(pixmap)
            stats["shown"] += 1
        except Exception as exc:
            stats["rejected"] += 1
            logger.error("Ошибка конвертации кадра для слота '%s': %s", slot_id, exc)
            slot.set_placeholder("Ошибка кадра")

    def _warn_rejected(self, slot_id: str, frame) -> None:
        """Одна строка WARNING на причину отказа (слот + dtype/ndim/каналы); повтор — молча."""
        key = _reject_key(slot_id, frame)
        if key in self._warned_rejects:
            return
        self._warned_rejects.add(key)
        logger.warning(
            "Кадр отвергнут: слот '%s': ожидали %s; пришло %s",
            slot_id,
            _EXPECTED_FRAME,
            _describe_frame(frame),
        )

    def frame_stats(self, slot_id: str) -> dict[str, int]:
        """Счётчики кадров слота: received (все, включая None/пустой), shown, rejected."""
        return dict(self._frame_stats.get(slot_id, {"received": 0, "shown": 0, "rejected": 0}))

    def on_frames(self, frames: dict) -> None:
        """Обработать несколько кадров сразу.

        frames: dict[slot_id, np.ndarray]
        """
        for slot_id, frame in frames.items():
            self.on_frame(slot_id, frame)

    def get_last_frame(self, slot_id: str):
        """Последний валидный кадр слота (BGR numpy) или None — для снимка."""
        return self._last_frames.get(slot_id)
