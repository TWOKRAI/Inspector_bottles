"""WheelGuard — глобальный фильтр: колесо мыши НЕ меняет значения полей ввода.

Прокрутка колесом над QSpinBox / QDoubleSpinBox / QComboBox / QSlider — частая
причина СЛУЧАЙНЫХ правок (наводишь мышь, крутишь страницу — значение «уехало»).
Этот app-level eventFilter съедает wheel на таких виджетах, а саму прокрутку
переадресует ближайшей scroll-области, чтобы длинные панели (inspector, настройки)
продолжали скроллиться.

ВАЖНО: QScrollBar наследует QAbstractSlider — его НЕ блокируем (иначе колесо
перестанет крутить сами scroll-области).

Установка (один раз, в run_gui): ``app.installEventFilter(WheelGuard(app))``.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QScrollBar,
)


class WheelGuard(QObject):
    """App-level event filter: гасит wheel на полях ввода, прокрутку отдаёт scroll-области."""

    # Виджеты, у которых колесо меняет значение — блокируем.
    _INPUTS = (QAbstractSpinBox, QComboBox, QAbstractSlider)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.Wheel and isinstance(obj, self._INPUTS):
            if isinstance(obj, QScrollBar):
                return False  # сам scroll-bar — колесо ему нужно
            self._forward_to_scroll_area(obj, event)
            return True  # значение поля не трогаем
        return False

    @staticmethod
    def _forward_to_scroll_area(widget: QObject, event: QEvent) -> None:
        """Переадресовать wheel ближайшему scroll-контейнеру вверх по дереву."""
        parent = widget.parentWidget() if hasattr(widget, "parentWidget") else None
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return
            parent = parent.parentWidget()
