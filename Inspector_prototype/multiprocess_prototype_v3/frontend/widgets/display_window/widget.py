"""Виджет display-окна — отображение одного видеоисточника."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_v3.frontend.utils import ensure_main_thread

from .source_selector import SourceSelectorCombo


# ---------------------------------------------------------------------------
# Приватная утилита конвертации кадра
# ---------------------------------------------------------------------------

def _frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    """Конвертация BGR numpy frame в QPixmap.

    Поддерживает:
    - 3-канальный BGR (OpenCV default) → RGB
    - 4-канальный BGRA → RGBA
    - Одноканальный (grayscale)

    Args:
        frame: numpy-массив кадра. None → пустой QPixmap.

    Returns:
        QPixmap для отображения в QLabel.
    """
    if frame is None:
        return QPixmap()

    h, w = frame.shape[:2]

    if len(frame.shape) == 3:
        ch = frame.shape[2]
        if ch == 3:
            # BGR → RGB (OpenCV → Qt)
            rgb = frame[..., ::-1].copy()
            img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        elif ch == 4:
            img = QImage(frame.data, w, h, w * 4, QImage.Format_RGBA8888)
        else:
            # Неожиданный формат — как grayscale
            img = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
    else:
        # 2D массив — grayscale
        img = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)

    return QPixmap.fromImage(img)


# ---------------------------------------------------------------------------
# Основной виджет
# ---------------------------------------------------------------------------

class DisplayWindow(QWidget):
    """Standalone виджет отображения одного видеоисточника.

    Содержит:
    - Заголовок окна (жирный)
    - SourceSelectorCombo для смены источника
    - Placeholder для RecordingIndicator
    - Кнопку закрытия ✕
    - Область отображения кадров (QLabel с чёрным фоном)

    Сигналы:
        closed(window_id: str) — эмитируется при закрытии окна.
        source_changed(window_id: str, new_source_ref: str) — при смене источника.
    """

    # Эмитируется при закрытии окна: передаёт window_id
    closed = Signal(str)
    # Эмитируется при смене источника: передаёт (window_id, new_source_ref)
    source_changed = Signal(str, str)

    def __init__(
        self,
        window_id: str,
        initial_source: str = "",
        title: str = "Display",
        parent=None,
    ) -> None:
        super().__init__(parent)

        # Идентификатор этого окна
        self._window_id = window_id

        # Строим UI
        self._build_ui(title)

        # Устанавливаем начальный источник (после того как список уже добавлен)
        if initial_source:
            self._source_selector.set_current_source(initial_source)

    # -------------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------------

    @property
    def window_id(self) -> str:
        """Идентификатор этого display-окна."""
        return self._window_id

    @property
    def source_ref(self) -> str:
        """Текущий выбранный source_ref."""
        return self._source_selector.current_source

    @ensure_main_thread
    def update_frame(self, frame: np.ndarray) -> None:
        """Отобразить новый кадр в области просмотра.

        Масштабирует кадр под текущий размер QLabel с сохранением пропорций.

        Args:
            frame: numpy BGR/grayscale массив кадра.
        """
        pixmap = _frame_to_pixmap(frame)
        if pixmap.isNull():
            return

        # Масштабируем под размер области отображения
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def set_recording_indicator_for_camera(self, camera_id: int) -> None:
        """Создать и установить RecordingIndicator для конкретной камеры.

        Args:
            camera_id: Идентификатор камеры для привязки индикатора.
        """
        from multiprocess_prototype_v3.frontend.widgets.recording_indicator.widget import RecordingIndicator

        indicator = RecordingIndicator(self)
        indicator.set_camera_id(camera_id)
        self.set_recording_indicator(indicator)
        self._recording_indicator = indicator

    def set_recording_indicator(self, indicator: QWidget) -> None:
        """Заменить placeholder на реальный RecordingIndicator.

        Args:
            indicator: Виджет индикатора записи (RecordingIndicator).
        """
        # Находим placeholder в top bar layout и заменяем его
        top_bar = self._top_bar_layout
        placeholder_index = top_bar.indexOf(self._indicator_placeholder)
        if placeholder_index >= 0:
            # Убираем placeholder
            top_bar.removeWidget(self._indicator_placeholder)
            self._indicator_placeholder.deleteLater()
            # Вставляем реальный индикатор на то же место
            top_bar.insertWidget(placeholder_index, indicator)
            self._indicator_placeholder = indicator

    # -------------------------------------------------------------------------
    # Переопределение Qt-событий
    # -------------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Эмитирует closed(window_id) перед закрытием."""
        self.closed.emit(self._window_id)
        event.accept()

    # -------------------------------------------------------------------------
    # Приватные методы
    # -------------------------------------------------------------------------

    def _build_ui(self, title: str) -> None:
        """Собрать UI виджета."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # --- Top bar ---
        self._top_bar_layout = QHBoxLayout()
        self._top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self._top_bar_layout.setSpacing(6)

        # Заголовок окна (жирный)
        title_label = QLabel(title)
        font = QFont()
        font.setBold(True)
        title_label.setFont(font)
        self._top_bar_layout.addWidget(title_label)

        # Селектор источника
        self._source_selector = SourceSelectorCombo()
        self._top_bar_layout.addWidget(self._source_selector)

        # Placeholder для RecordingIndicator (пустой, без размера)
        self._indicator_placeholder = QWidget()
        self._indicator_placeholder.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        self._indicator_placeholder.setFixedSize(0, 0)
        self._top_bar_layout.addWidget(self._indicator_placeholder)

        # Кнопка закрытия
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        self._top_bar_layout.addWidget(close_btn)

        main_layout.addLayout(self._top_bar_layout)

        # --- Область отображения кадров ---
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(320, 240)
        self._image_label.setStyleSheet("background-color: black;")
        main_layout.addWidget(self._image_label)

        # --- Подключение сигналов ---
        close_btn.clicked.connect(self.close)
        self._source_selector.source_changed.connect(self._on_source_changed)

    def _on_source_changed(self, new_source: str) -> None:
        """Ретранслирует смену источника, добавляя window_id."""
        self.source_changed.emit(self._window_id, new_source)


__all__ = ["DisplayWindow"]
