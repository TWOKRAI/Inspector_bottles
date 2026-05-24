# -*- coding: utf-8 -*-
"""
Central Qt imports for frontend_module.

Использует PySide6. Fail-fast если не установлен.

Phase 2 миграции PyQt5 → PySide6 завершена (Wave 5): transitional aliases
``pyqtSignal``/``pyqtSlot`` удалены, все callers используют ``Signal``/``Slot``.

Phase 1B (B1) — это единая точка консолидации Qt-импортов для всего
``frontend_module``. Все production-файлы фреймворка должны импортировать
Qt-символы отсюда, а не напрямую из ``PySide6.*``. TYPE_CHECKING-блоки
(``SignalInstance``, ``QWheelEvent``) допустимо оставлять напрямую —
они не создают runtime-зависимости.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QChildEvent,
    QEvent,
    QObject,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QDoubleValidator,
    QFont,
    QIcon,
    QImage,
    QIntValidator,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    # Символы только для аннотаций — runtime-импорт не нужен.
    # SignalInstance используется в Protocol для типизации сигналов.
    # QWheelEvent — в overrides у DiffScrollTabLayout.
    from PySide6.QtCore import SignalInstance  # noqa: F401
    from PySide6.QtGui import QWheelEvent  # noqa: F401

__all__ = [
    "QAbstractItemView",
    "QAbstractScrollArea",
    "QApplication",
    "QButtonGroup",
    "QCheckBox",
    "QChildEvent",
    "QCloseEvent",
    "QColor",
    "QComboBox",
    "QCursor",
    "QDoubleSpinBox",
    "QDoubleValidator",
    "QEvent",
    "QFont",
    "QFormLayout",
    "QFrame",
    "QGridLayout",
    "QGroupBox",
    "QHBoxLayout",
    "QHeaderView",
    "QIcon",
    "QImage",
    "QIntValidator",
    "QLabel",
    "QLineEdit",
    "QListWidget",
    "QListWidgetItem",
    "QMainWindow",
    "QMessageBox",
    "QObject",
    "QPainter",
    "QPainterPath",
    "QPen",
    "QPixmap",
    "QPlainTextEdit",
    "QProgressBar",
    "QPropertyAnimation",
    "QPushButton",
    "QScrollArea",
    "QScrollBar",
    "QSettings",
    "QSize",
    "QSizePolicy",
    "QSlider",
    "QSpacerItem",
    "QSpinBox",
    "QSplitter",
    "QStackedWidget",
    "QStandardItem",
    "QStandardItemModel",
    "QStyledItemDelegate",
    "QTabWidget",
    "QTableWidget",
    "QTableWidgetItem",
    "QThread",
    "QTimer",
    "QToolButton",
    "QTreeView",
    "QTreeWidget",
    "QTreeWidgetItem",
    "QVBoxLayout",
    "QWidget",
    "Qt",
    "Signal",
    "Slot",
]
