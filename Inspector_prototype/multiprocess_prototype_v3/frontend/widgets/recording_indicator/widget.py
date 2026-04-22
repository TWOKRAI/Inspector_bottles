"""Виджет индикатора записи видео — красная точка, таймер, размер файла, кнопка toggle."""

from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import QTimer, pyqtSignal


class RecordingIndicator(QWidget):
    """
    Индикатор состояния записи видео.

    Отображает:
    - мигающую красную точку при активной записи
    - счётчик длительности в формате MM:SS
    - текущий размер записываемого файла
    - кнопку переключения записи (REC / STOP)

    Сигналы:
        record_toggled(camera_id: int, start: bool) — эмитируется при нажатии кнопки.
            start=True означает запрос на начало записи, False — остановку.
    """

    # Сигнал: (camera_id, start) — запрос переключения записи
    record_toggled = pyqtSignal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Идентификатор камеры (-1 = не привязан)
        self._camera_id: int = -1
        # Текущее состояние записи
        self._recording: bool = False

        # --- Строим layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Красная точка-индикатор
        self._dot_label = QLabel(self)
        self._dot_label.setFixedSize(12, 12)
        self._dot_label.setStyleSheet(
            "background-color: red; border-radius: 6px;"
        )
        layout.addWidget(self._dot_label)

        # Счётчик длительности записи
        self._duration_label = QLabel("00:00", self)
        layout.addWidget(self._duration_label)

        # Размер записываемого файла
        self._size_label = QLabel("0.0 MB", self)
        layout.addWidget(self._size_label)

        # Кнопка переключения записи
        self._toggle_btn = QPushButton("REC", self)
        layout.addWidget(self._toggle_btn)

        # --- Таймер мигания точки ---
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_dot_visibility)

        # --- Начальное состояние: не пишем ---
        self._apply_idle_state()

        # Подключаем кнопку
        self._toggle_btn.clicked.connect(self._on_toggle)

    # -------------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------------

    def set_camera_id(self, camera_id: int) -> None:
        """Привязать виджет к конкретной камере."""
        self._camera_id = camera_id

    def update_stats(
        self,
        recording_active: bool,
        duration_sec: float,
        file_size_mb: float,
    ) -> None:
        """
        Обновить состояние виджета по данным из RecorderWorker.stats.

        Args:
            recording_active: True — запись идёт, False — остановлена.
            duration_sec: Длительность текущей записи в секундах.
            file_size_mb: Размер записываемого файла в мегабайтах.
        """
        if recording_active and not self._recording:
            # Запись только что началась — включаем индикацию
            self._apply_recording_state()

        elif not recording_active and self._recording:
            # Запись только что завершилась — сбрасываем индикацию
            self._apply_idle_state()

        # Сохраняем актуальное состояние
        self._recording = recording_active

        # Обновляем labels вне зависимости от смены состояния
        # (значения могут обновляться каждую секунду во время записи)
        total_seconds = int(duration_sec)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        self._duration_label.setText(f"{minutes:02d}:{seconds:02d}")
        self._size_label.setText(f"{file_size_mb:.1f} MB")

    # -------------------------------------------------------------------------
    # Приватные методы
    # -------------------------------------------------------------------------

    def _apply_recording_state(self) -> None:
        """Переключить виджет в режим активной записи."""
        self._dot_label.setVisible(True)
        self._duration_label.setVisible(True)
        self._size_label.setVisible(True)
        self._toggle_btn.setText("STOP")
        self._blink_timer.start()

    def _apply_idle_state(self) -> None:
        """Переключить виджет в режим ожидания (не записывает)."""
        self._blink_timer.stop()
        self._dot_label.setVisible(False)
        self._duration_label.setVisible(False)
        self._size_label.setVisible(False)
        self._toggle_btn.setText("REC")

    def _toggle_dot_visibility(self) -> None:
        """Переключить видимость красной точки (мигание)."""
        self._dot_label.setVisible(not self._dot_label.isVisible())

    def _on_toggle(self) -> None:
        """Обработчик нажатия кнопки REC/STOP — эмитирует record_toggled."""
        # Запрашиваем противоположное текущему состоянию
        self.record_toggled.emit(self._camera_id, not self._recording)


__all__ = ["RecordingIndicator"]
