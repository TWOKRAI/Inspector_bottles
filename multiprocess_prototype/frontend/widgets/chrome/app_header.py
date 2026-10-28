"""AppHeaderWidget — верхняя панель главного окна (бренд + статус)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOption,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.widgets.chrome.login_button import LoginButton


class _OutlinedLabel(QLabel):
    """QLabel с тонким контуром вокруг глифов (QSS не умеет text-stroke).

    Фон и геометрию рисует QSS, текст — контуром и заливкой из палитры (цвет из QSS).
    """

    def __init__(self, text: str, outline: QColor, outline_width: float, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._outline = outline
        self._outline_width = outline_width

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)
        # Базовая линия по центру contentsRect (как у QLabel с AlignVCenter)
        rect = QRectF(self.contentsRect())
        metrics = QFontMetricsF(self.font())
        baseline = rect.top() + (rect.height() + metrics.ascent() - metrics.descent()) / 2
        # Контур строим из пути без stretch шрифта (path-текст с stretch даёт неверные шаги букв),
        # растяжение применяем к самому пути — перо при этом не искажается.
        flat = QFont(self.font())
        flat.setStretch(100)
        path = QPainterPath()
        path.addText(QPointF(0, baseline), flat, self.text())
        path = QTransform.fromScale(self.font().stretch() / 100, 1).map(path)
        path.translate(rect.left(), 0)
        painter.setPen(
            QPen(
                self._outline,
                self._outline_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(self.palette().windowText())
        painter.drawPath(path)
        painter.end()


class AppHeaderWidget(QWidget):
    """Заголовок приложения: логотип слева, статус справа.

    objectName="AppHeader" — для стилизации через QSS.
    """

    # Запрос на переключение полноэкранного режима (обрабатывает MainWindow).
    fullscreenToggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AppHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        # Бренд-лейбл (логотип ИННОТЕХ, шрифт Square721 BdEx BT — задаётся в QSS)
        self._brand_label = _OutlinedLabel("ИННОТЕХ", QColor("#000000"), 0.65)
        self._brand_label.setObjectName("BrandLabel")
        # Растяжение по горизонтали: QSS не умеет font-stretch. Шрифт с одним stretch,
        # чтобы не перебить family/size/weight из QSS.
        stretch = QFont()
        stretch.setStretch(135)
        self._brand_label.setFont(stretch)
        # Тень под логотипом (QSS не умеет text-shadow — делаем эффектом)
        shadow = QGraphicsDropShadowEffect(self._brand_label)
        shadow.setBlurRadius(8)
        shadow.setOffset(4, 4)
        shadow.setColor(QColor(0, 0, 0, 70))
        self._brand_label.setGraphicsEffect(shadow)
        layout.addWidget(self._brand_label)

        # Растяжка между брендом и статусом
        layout.addStretch(1)

        # Статус-лейбл (fps, backend status и т.д.)
        self._status_label = QLabel("")
        self._status_label.setObjectName("StatusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label)

        # Кнопка полноэкранного режима (toggle: вход / возврат обратно).
        self._fullscreen_btn = QPushButton("⛶")
        self._fullscreen_btn.setObjectName("FullscreenButton")
        self._fullscreen_btn.setFixedSize(36, 40)
        self._fullscreen_btn.setToolTip("Полноэкранный режим (F11)")
        self._fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fullscreen_btn.clicked.connect(self.fullscreenToggled.emit)
        layout.addWidget(self._fullscreen_btn)

    # -- Публичное API --

    def update_status(self, text: str) -> None:
        """Обновить текст статуса в правой части header."""
        self._status_label.setText(text)

    def set_fullscreen_state(self, is_fullscreen: bool) -> None:
        """Обновить вид кнопки под текущий режим окна.

        В полноэкранном режиме кнопка предлагает вернуться обратно.
        """
        self._fullscreen_btn.setText("🗗" if is_fullscreen else "⛶")
        self._fullscreen_btn.setToolTip(
            "Выйти из полноэкранного режима (F11 / Esc)" if is_fullscreen else "Полноэкранный режим (F11)"
        )

    def set_login_button(self, button: "LoginButton") -> None:
        """Вставить LoginButton справа от _status_label.

        Итоговый порядок элементов в layout:
            [BrandLabel] [stretch] [StatusLabel] [LoginButton]
        """
        self.layout().addWidget(button)
