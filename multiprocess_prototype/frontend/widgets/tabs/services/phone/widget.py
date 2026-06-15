"""PhoneServiceWidget — карточка сервиса «Телефон».

Показывает статус сервера, адрес для телефона, QR-код, последнее принятое слово
и подсказку про брандмауэр. Кнопки Вкл/Выкл — в action-колонке секции.
"""

from __future__ import annotations

import base64

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PhoneServiceWidget(QWidget):
    """Виджет управления приёмом фото/слова с телефона по WiFi + пульт сигналов."""

    # Запрос эмитировать сигнал пульта: (port, value). Секция → presenter.emit_signal.
    signal_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("<b>Телефон → ПК (фото и слово по WiFi)</b>")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Привязывается к state (connection.running) через bindings.
        self.status_label = QLabel("Статус: —")
        layout.addWidget(self.status_label)

        self._url_label = QLabel("Адрес: —")
        self._url_label.setWordWrap(True)
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._url_label)

        # Прочие адреса (другие интерфейсы) — если основной не открывается на телефоне.
        self._alt_label = QLabel("")
        self._alt_label.setWordWrap(True)
        self._alt_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._alt_label.setProperty("role", "placeholder-italic")
        self._alt_label.setVisible(False)
        layout.addWidget(self._alt_label)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._qr_label)

        # Привязывается к state (phone.word) через bindings.
        self.word_label = QLabel("Последнее слово: —")
        layout.addWidget(self.word_label)

        # Превью принятого фото (base64-миниатюра из state, метод set_thumb_b64).
        layout.addWidget(QLabel("Последнее фото:"))
        self._thumb_label = QLabel("—")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_label)

        # --- Пульт (сигналы) — кнопки шлют сигнал на выходной порт ноды.
        layout.addWidget(QLabel("<b>🔘 Пульт (сигналы)</b>"))

        # signal_1 — координаты роботу {x_mm, y_mm}
        coord_row = QHBoxLayout()
        self._coord_x = QLineEdit()
        self._coord_x.setPlaceholderText("X, мм")
        self._coord_y = QLineEdit()
        self._coord_y.setPlaceholderText("Y, мм")
        btn_coords = QPushButton("Координаты → signal_1")
        btn_coords.setToolTip("Эмитировать {x_mm, y_mm} на порт signal_1 (вяжи к robot_io)")
        btn_coords.clicked.connect(self._emit_coords)
        coord_row.addWidget(self._coord_x)
        coord_row.addWidget(self._coord_y)
        coord_row.addWidget(btn_coords)
        layout.addLayout(coord_row)

        # signal_2 — текст (напр. слово)
        text_row = QHBoxLayout()
        self._signal_text = QLineEdit()
        self._signal_text.setPlaceholderText("значение / слово")
        btn_text = QPushButton("Текст → signal_2")
        btn_text.setToolTip("Эмитировать строку на порт signal_2")
        btn_text.clicked.connect(self._emit_text)
        text_row.addWidget(self._signal_text)
        text_row.addWidget(btn_text)
        layout.addLayout(text_row)

        # signal_3 — простой триггер (без значения)
        btn_trigger = QPushButton("Триггер → signal_3")
        btn_trigger.setToolTip("Эмитировать триггер (true) на порт signal_3")
        btn_trigger.clicked.connect(lambda: self.signal_requested.emit("signal_3", True))
        layout.addWidget(btn_trigger)

        hint = QLabel(
            "Телефон и ПК — в одной сети WiFi. Откройте адрес или отсканируйте QR "
            "в браузере телефона, затем «Включить» здесь. При первом запуске "
            "разрешите Python в брандмауэре Windows (частные сети)."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "placeholder-italic")
        layout.addWidget(hint)

        layout.addStretch()

    def set_connection(self, urls: list[str], qr_png: bytes | None) -> None:
        """Показать адрес(а) и QR. urls[0] — основной; QR=None если нет segno.

        Несколько адресов — у ПК несколько интерфейсов (WiFi/Ethernet/VPN).
        Телефон должен открыть тот, что в его сети WiFi.
        """
        primary = urls[0] if urls else "—"
        self._url_label.setText(f"Адрес: {primary}")
        if len(urls) > 1:
            self._alt_label.setText("Если не открывается — попробуйте: " + ",  ".join(urls[1:]))
            self._alt_label.setVisible(True)
        else:
            self._alt_label.setVisible(False)
        if qr_png:
            pixmap = QPixmap()
            pixmap.loadFromData(qr_png)
            self._qr_label.setPixmap(pixmap)
            self._qr_label.setText("")
        else:
            self._qr_label.setPixmap(QPixmap())
            self._qr_label.setText(
                "QR недоступен — установите segno (uv pip install segno).\nОткройте адрес выше на телефоне вручную."
            )

    def set_thumb_b64(self, b64: str) -> None:
        """Показать превью принятого фото из base64 JPEG (state-биндинг)."""
        if not b64:
            return
        try:
            data = base64.b64decode(b64)
        except Exception:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data) and not pixmap.isNull():
            if pixmap.width() > 360:
                pixmap = pixmap.scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
            self._thumb_label.setPixmap(pixmap)
            self._thumb_label.setText("")

    def _emit_coords(self) -> None:
        """Собрать {x_mm, y_mm} из полей и эмитировать на signal_1."""
        try:
            x = float(self._coord_x.text().strip().replace(",", "."))
            y = float(self._coord_y.text().strip().replace(",", "."))
        except ValueError:
            return
        self.signal_requested.emit("signal_1", {"x_mm": x, "y_mm": y})

    def _emit_text(self) -> None:
        """Эмитировать строку из поля на signal_2."""
        text = self._signal_text.text().strip()
        if text:
            self.signal_requested.emit("signal_2", text)
