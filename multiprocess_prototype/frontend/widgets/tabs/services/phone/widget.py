"""PhoneServiceWidget — карточка сервиса «Телефон» (только наблюдение).

Показывает статус сервера, адрес для телефона, QR-код, последнее принятое слово,
превью последнего фото и подсказку про брандмауэр. Кнопки Вкл/Выкл — в
action-колонке секции. Пульт сигналов сюда НЕ входит: сигналы эмитит HTML-страница
телефона (и, в перспективе, отдельный сервис-пульт), а GUI-вкладка — для наблюдения.
"""

from __future__ import annotations

import base64

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)


class PhoneServiceWidget(QWidget):
    """Виджет наблюдения за приёмом фото/слова с телефона по WiFi."""

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

        hint = QLabel(
            "Телефон и ПК — в одной сети WiFi. Откройте адрес или отсканируйте QR "
            "в браузере телефона, затем «Включить» здесь. При первом запуске "
            "разрешите Python в брандмауэре Windows (частные сети)."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "placeholder-italic")
        layout.addWidget(hint)

        layout.addStretch()

    def set_connection(self, endpoints: list[tuple[str, str]], qr_png: bytes | None) -> None:
        """Показать адрес(а) с меткой интерфейса и QR. endpoints[0] — основной.

        endpoints = [(метка_интерфейса, url)]; метка — имя адаптера (WiFi/Ethernet/…),
        чтобы было видно, какой адрес из WiFi. QR=None если нет segno.
        """
        primary = endpoints[0] if endpoints else ("", "—")
        self._url_label.setText(f"Адрес ({primary[0]}): {primary[1]}" if primary[0] else f"Адрес: {primary[1]}")
        if len(endpoints) > 1:
            alts = ";   ".join(f"{label}: {url}" if label else url for label, url in endpoints[1:])
            self._alt_label.setText("Если не открывается — попробуйте: " + alts)
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
