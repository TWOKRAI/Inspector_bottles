"""DisplaySlot — один слот отображения кадра в ImagePanel."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

# Защитный нижний предел метки слота: и минимум QLabel, и нижняя граница цели уменьшения кадра.
_MIN_WIDTH = 320
_MIN_HEIGHT = 240

# Плашка тишины: тёмный фон, светлый текст.
_PLATE_STYLE = "background-color: #202020; color: #e0e0e0;"


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

        # Исходный (не уменьшенный) кадр: ресайз масштабирует из него,
        # а не из уже уменьшенной копии в QLabel — иначе качество деградирует
        self._source_pixmap: QPixmap | None = None

        # Показана ли плашка тишины (на метке стоит _PLATE_STYLE)
        self._plate_shown = False

        # Колбэк перерисовки при ресайзе (задаёт presenter): cb() -> True, если слот уже перерисован
        self._resize_callback: Callable[[], bool] | None = None

        # QLabel — область отображения кадра
        placeholder = label if label else "Нет сигнала"
        self._label = QLabel(placeholder)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        self._label.setObjectName("DisplaySlotLabel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    @property
    def slot_id(self) -> str:
        """Идентификатор слота."""
        return self._slot_id

    def update_pixmap(self, pixmap: QPixmap) -> None:
        """Установить pixmap с масштабированием, сохраняя пропорции."""
        if pixmap.isNull():
            # Пустой кадр — не «оставить прежний на экране без привязки к исходнику», а «нет сигнала».
            self.clear()
            return
        self._drop_plate_style()
        self._source_pixmap = pixmap
        self._show_scaled()

    def target_size(self) -> tuple[int, int]:
        """Размер метки (ширина, высота), не ниже защитного предела 320x240 — цель уменьшения кадра."""
        size = self._label.size()
        return max(size.width(), _MIN_WIDTH), max(size.height(), _MIN_HEIGHT)

    def set_resize_callback(self, callback: Callable[[], bool] | None) -> None:
        """Задать перерисовку слота при ресайзе: ``callback() -> bool``.

        True — владелец кадра (presenter) перерисовал слот сам через ``update_pixmap`` из сырого кадра.
        False или нет колбэка — слот масштабирует свой pixmap (``_show_scaled``); масштабирование
        слота не пропускается ни на одном пути. Колбэк зовётся, только пока слот показывает изображение.

        Внимание: прямой вызов ``slot.update_pixmap`` мимо presenter-а при заданном колбэке воскресит
        старый кадр из ``_last_frames`` при следующем ресайзе.
        """
        self._resize_callback = callback

    def _show_scaled(self) -> None:
        """Показать исходный pixmap, масштабированный под текущий размер QLabel."""
        source = self._source_pixmap
        if source is None or source.isNull():
            return
        scaled = source.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)

    def set_placeholder(self, text: str) -> None:
        """Показать текст-placeholder вместо изображения."""
        self._drop_plate_style()
        self._source_pixmap = None
        self._label.clear()
        self._label.setText(text)

    def clear(self) -> None:
        """Очистить слот и показать placeholder 'Нет сигнала'."""
        placeholder = self._label_text if self._label_text else "Нет сигнала"
        self.set_placeholder(placeholder)

    def show_no_signal(self, text: str) -> None:
        """Показать тёмную плашку с текстом вместо кадра; прежний кадр забыт (ресайз его не вернёт)."""
        self._label.clear()
        self._source_pixmap = None
        self._label.setStyleSheet(_PLATE_STYLE)
        self._label.setWordWrap(True)  # длинный шаблон не должен уезжать за края слота
        self._label.setText(text)
        self._plate_shown = True

    def leave_no_signal(self) -> None:
        """Снять плашку (идемпотентно); без пришедшего после неё кадра — обычный placeholder слота."""
        if not self._plate_shown:
            return
        self._drop_plate_style()
        if self._source_pixmap is None:
            self.clear()

    def _drop_plate_style(self) -> None:
        """Снять стиль и перенос строк плашки; без плашки метка не трогается."""
        if self._plate_shown:
            self._label.setStyleSheet("")
            self._label.setWordWrap(False)
            self._plate_shown = False

    def resizeEvent(self, event) -> None:
        """При изменении размера — перерисовать кадр (колбэк) или перемасштабировать исходный pixmap."""
        super().resizeEvent(event)
        callback = self._resize_callback
        if callback is not None and self._source_pixmap is not None and callback():
            return
        self._show_scaled()
