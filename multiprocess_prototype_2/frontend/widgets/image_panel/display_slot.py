"""DisplaySlot — один слот отображения кадра в ImagePanel."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class DisplaySlot(QWidget):
    """Один слот отображения: умеет показывать QPixmap или текст-placeholder.

    Логика масштабирования взята из CameraView.
    """

    def __init__(self, slot_id: str, label: str = "", parent=None):
        super().__init__(parent)
        # Идентификатор слота для роутинга кадров
        self._slot_id = slot_id

        self.setObjectName("ImageSlot")

        # Подпись слота (опционально)
        self._label_text = label

        # QLabel — область отображения кадра
        placeholder = label if label else "Нет сигнала"
        self._label = QLabel(placeholder)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(320, 240)
        self._label.setStyleSheet(
            "background-color: #1a1a2e; color: #aaa; font-size: 16px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    @property
    def slot_id(self) -> str:
        """Идентификатор слота."""
        return self._slot_id

    def update_pixmap(self, pixmap: QPixmap) -> None:
        """Установить pixmap с масштабированием, сохраняя пропорции."""
        scaled = pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)

    def set_placeholder(self, text: str) -> None:
        """Показать текст-placeholder вместо изображения."""
        self._label.clear()
        self._label.setText(text)

    def resizeEvent(self, event) -> None:
        """При изменении размера — перемасштабировать текущий pixmap."""
        super().resizeEvent(event)
        pixmap = self._label.pixmap()
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._label.setPixmap(scaled)
