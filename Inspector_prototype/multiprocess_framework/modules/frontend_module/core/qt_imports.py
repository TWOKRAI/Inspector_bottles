# -*- coding: utf-8 -*-
"""
Central Qt imports for frontend_module.

Использует PySide6. Fail-fast если не установлен.

Transitional aliases (Phase 2 миграции PyQt5 → PySide6):
- ``pyqtSignal`` алиас для ``Signal``
- ``pyqtSlot`` алиас для ``Slot``

Алиасы убираются на Wave 5 после того как все callers перейдут на ``Signal``/``Slot``.
"""
from PySide6.QtCore import QEvent, QObject, Qt, QSize, QTimer, QThread, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QCursor,
    QDoubleValidator,
    QFont,
    QIcon,
    QImage,
    QIntValidator,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Transitional aliases — убрать на Wave 5
pyqtSignal = Signal
pyqtSlot = Slot

__all__ = [
    "QAbstractItemView",
    "QButtonGroup",
    "QStyledItemDelegate",
    "QApplication",
    "QCloseEvent",
    "QCheckBox",
    "QComboBox",
    "QDoubleSpinBox",
    "QDoubleValidator",
    "QEvent",
    "QFormLayout",
    "QFrame",
    "QGroupBox",
    "QGridLayout",
    "QHeaderView",
    "QHBoxLayout",
    "QIcon",
    "QImage",
    "QIntValidator",
    "QLabel",
    "QLineEdit",
    "QListWidget",
    "QMainWindow",
    "QMessageBox",
    "QObject",
    "QPlainTextEdit",
    "QProgressBar",
    "QPixmap",
    "QPushButton",
    "QScrollArea",
    "QSize",
    "QSizePolicy",
    "QSlider",
    "QSpinBox",
    "QStackedWidget",
    "QTabWidget",
    "QTableWidget",
    "QTableWidgetItem",
    "QToolButton",
    "QTreeWidget",
    "QTreeWidgetItem",
    "QThread",
    "QTimer",
    "QVBoxLayout",
    "QWidget",
    "Qt",
    "QCursor",
    "QFont",
    "Signal",
    "Slot",
    "pyqtSignal",
    "pyqtSlot",
]
